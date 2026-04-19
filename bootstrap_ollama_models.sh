#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

trim_whitespace() {
    local value="$1"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf "%s" "${value}"
}

model_latest_alias() {
    local model
    model="$(trim_whitespace "${1:-}")"
    [[ -n "${model}" ]] || return 1
    if [[ "${model}" == *:* ]]; then
        printf '%s' "${model}"
    else
        printf '%s:latest' "${model}"
    fi
}

model_name_matches() {
    local requested="$1"
    local latest_alias=""
    local candidate=""

    requested="$(trim_whitespace "${requested}")"
    [[ -n "${requested}" ]] || return 1
    latest_alias="$(model_latest_alias "${requested}")"

    while IFS= read -r candidate; do
        candidate="$(trim_whitespace "${candidate}")"
        [[ -n "${candidate}" ]] || continue
        [[ "${candidate}" == "${requested}" ]] && return 0
        if [[ "${requested}" != *:* && "${candidate}" == "${latest_alias}" ]]; then
            return 0
        fi
    done
    return 1
}

info() {
    printf '[INFO] %s\n' "$*"
}

warn() {
    printf '[WARN] %s\n' "$*" >&2
}

success() {
    printf '[OK] %s\n' "$*"
}

compose() {
    docker compose -f "${ROOT_DIR}/docker-compose.yml" "$@"
}

load_env_value() {
    local key="$1"
    local value=""
    if [[ -f "${ROOT_DIR}/.env" ]]; then
        value="$(awk -F= -v key="${key}" '$1==key {gsub(/\r/,"",$2); print $2; exit}' "${ROOT_DIR}/.env" || true)"
    fi
    printf '%s' "${value}"
}

is_positive_integer() {
    [[ "${1:-}" =~ ^[0-9]+$ ]] && [[ "${1}" -gt 0 ]]
}

join_csv() {
    local result=""
    local item
    for item in "$@"; do
        [[ -n "${item}" ]] || continue
        [[ -n "${result}" ]] && result+=","
        result+="${item}"
    done
    printf '%s' "${result}"
}

append_unique_array_item() {
    local array_name="$1"
    local item="$2"
    local existing=""
    local -n target_array="${array_name}"

    [[ -n "${item}" ]] || return 0
    for existing in "${target_array[@]}"; do
        [[ "${existing}" == "${item}" ]] && return 0
    done
    target_array+=("${item}")
}

run_with_timeout() {
    local timeout_seconds="$1"
    shift

    if command -v timeout >/dev/null 2>&1; then
        timeout --foreground "${timeout_seconds}" "$@"
        return $?
    fi

    if command -v python3 >/dev/null 2>&1; then
        python3 - "$timeout_seconds" "$@" <<'PY'
import subprocess
import sys

timeout_seconds = int(sys.argv[1])
command = sys.argv[2:]

try:
    completed = subprocess.run(command, timeout=timeout_seconds)
except subprocess.TimeoutExpired:
    raise SystemExit(124)

raise SystemExit(completed.returncode)
PY
        return $?
    fi

    warn "Cannot enforce a bounded Ollama pull because neither 'timeout' nor 'python3' is available"
    return 127
}

DEFAULT_MODEL="${DEFAULT_MODEL:-$(load_env_value "DEFAULT_MODEL")}"
DEFAULT_MODEL="${DEFAULT_MODEL:-gemma2:2b}"
SECONDARY_MODEL="${SECONDARY_MODEL:-}"
SECONDARY_MODELS="${SECONDARY_MODELS:-}"
LOCAL_GGUF="${LOCAL_GGUF:-$(find "${ROOT_DIR}/models" -maxdepth 1 -type f -name '*.gguf' | head -n 1 || true)}"
OFFLINE_MODEL_NAME="${OFFLINE_MODEL_NAME:-${DEFAULT_MODEL}}"
OLLAMA_PULL_TIMEOUT_SECONDS="${OLLAMA_PULL_TIMEOUT_SECONDS:-$(load_env_value "OLLAMA_PULL_TIMEOUT_SECONDS")}"
OLLAMA_PULL_TIMEOUT_SECONDS="${OLLAMA_PULL_TIMEOUT_SECONDS:-900}"
readonly PULL_MAX_ATTEMPTS=2
readonly PULL_RETRY_BACKOFF_SECONDS=5
declare -a SECONDARY_MODEL_LIST=()
declare -a BOOTSTRAP_SUCCESS_MODELS=()
declare -a BOOTSTRAP_FAILED_MODELS=()
declare -a BOOTSTRAP_FAILED_DETAILS=()

if ! is_positive_integer "${OLLAMA_PULL_TIMEOUT_SECONDS}"; then
    warn "Invalid OLLAMA_PULL_TIMEOUT_SECONDS='${OLLAMA_PULL_TIMEOUT_SECONDS}', falling back to 900 seconds"
    OLLAMA_PULL_TIMEOUT_SECONDS="900"
fi

collect_secondary_models() {
    SECONDARY_MODEL_LIST=()
    if [[ -n "${SECONDARY_MODEL}" ]]; then
        append_unique_array_item "SECONDARY_MODEL_LIST" "$(trim_whitespace "${SECONDARY_MODEL}")"
    fi

    local raw_models=()
    local model=""
    IFS=',' read -r -a raw_models <<<"${SECONDARY_MODELS}"
    for model in "${raw_models[@]}"; do
        model="$(trim_whitespace "${model}")"
        if [[ -z "${model}" || "${model}" == "${DEFAULT_MODEL}" ]]; then
            continue
        fi
        append_unique_array_item "SECONDARY_MODEL_LIST" "${model}"
    done
}

record_bootstrap_success() {
    append_unique_array_item "BOOTSTRAP_SUCCESS_MODELS" "$1"
}

record_bootstrap_failure() {
    local model="$1"
    local reason="$2"
    append_unique_array_item "BOOTSTRAP_FAILED_MODELS" "${model}"
    BOOTSTRAP_FAILED_DETAILS+=("${model}|${reason}")
}

emit_bootstrap_summary() {
    printf 'BOOTSTRAP_SUMMARY|selected|%s\n' "$(join_csv "${DEFAULT_MODEL}" "${SECONDARY_MODEL_LIST[@]}")"
    printf 'BOOTSTRAP_SUMMARY|successful|%s\n' "$(join_csv "${BOOTSTRAP_SUCCESS_MODELS[@]}")"
    printf 'BOOTSTRAP_SUMMARY|failed|%s\n' "$(join_csv "${BOOTSTRAP_FAILED_MODELS[@]}")"

    local failure_detail=""
    for failure_detail in "${BOOTSTRAP_FAILED_DETAILS[@]}"; do
        printf 'BOOTSTRAP_FAILURE_DETAIL|%s\n' "${failure_detail}"
    done
}

list_models() {
    compose exec -T ollama ollama list 2>/dev/null | awk 'NR>1 && NF {print $1}'
}

has_model() {
    local model="$1"
    list_models | model_name_matches "${model}"
}

can_reach_ollama_registry() {
    getent hosts ollama.com >/dev/null 2>&1 || return 1
    if command -v curl >/dev/null 2>&1; then
        curl -fsSLI --connect-timeout 5 https://ollama.com >/dev/null 2>&1
        return $?
    fi
    return 1
}

pull_model() {
    local model="$1"
    local attempt
    local status=0

    for attempt in $(seq 1 "${PULL_MAX_ATTEMPTS}"); do
        info "Attempting to pull ${model} into Ollama (attempt ${attempt}/${PULL_MAX_ATTEMPTS}, timeout ${OLLAMA_PULL_TIMEOUT_SECONDS}s)"
        if run_with_timeout "${OLLAMA_PULL_TIMEOUT_SECONDS}" \
            docker compose -f "${ROOT_DIR}/docker-compose.yml" exec -T ollama ollama pull "${model}"; then
            success "Pulled ${model}"
            return 0
        else
            status=$?
        fi

        if [[ "${status}" -eq 124 ]]; then
            warn "Timed out while pulling ${model} after ${OLLAMA_PULL_TIMEOUT_SECONDS}s"
        else
            warn "Failed to pull ${model} (exit ${status})"
        fi

        if [[ "${attempt}" -lt "${PULL_MAX_ATTEMPTS}" ]]; then
            info "Retrying ${model} after ${PULL_RETRY_BACKOFF_SECONDS}s backoff"
            sleep "${PULL_RETRY_BACKOFF_SECONDS}"
        fi
    done

    return "${status}"
}

create_offline_model_from_gguf() {
    local gguf_path="$1"
    local gguf_name
    gguf_name="$(basename "${gguf_path}")"

    if [[ ! -f "${gguf_path}" ]]; then
        return 1
    fi

    info "Attempting offline bootstrap from local GGUF ${gguf_name}"
    if compose exec -T ollama /bin/sh -lc "test -f '/models/${gguf_name}'"; then
        compose exec -T ollama /bin/sh -lc "cat >/tmp/Modelfile <<'EOF'
FROM /models/${gguf_name}
PARAMETER num_ctx 4096
EOF
/bin/ollama create '${OFFLINE_MODEL_NAME}' -f /tmp/Modelfile"
        success "Created offline Ollama model ${OFFLINE_MODEL_NAME} from ${gguf_name}"
        return 0
    fi

    warn "GGUF ${gguf_name} is not visible inside the Ollama container"
    return 1
}

bootstrap_secondary_models() {
    local registry_reachable="$1"
    local model=""
    local pull_status=0
    local reason=""

    if [[ "${#SECONDARY_MODEL_LIST[@]}" -eq 0 ]]; then
        return 0
    fi

    info "Attempting bootstrap for selected secondary models: $(join_csv "${SECONDARY_MODEL_LIST[@]}")"
    for model in "${SECONDARY_MODEL_LIST[@]}"; do
        if has_model "${model}"; then
            success "Secondary model ${model} is already available"
            record_bootstrap_success "${model}"
            continue
        fi

        if [[ "${registry_reachable}" != "1" ]]; then
            reason="registry unreachable"
            warn "Secondary model ${model} was not pulled because the Ollama registry is unreachable"
            record_bootstrap_failure "${model}" "${reason}"
            continue
        fi

        set +e
        pull_model "${model}"
        pull_status=$?
        set -e
        if [[ "${pull_status}" -eq 0 ]]; then
            if has_model "${model}"; then
                success "Secondary model ${model} is available after bounded online bootstrap"
                record_bootstrap_success "${model}"
                continue
            fi
            reason="pull completed but model is still missing"
            warn "Secondary model ${model} is still missing after bounded online bootstrap"
            record_bootstrap_failure "${model}" "${reason}"
            continue
        fi

        if [[ "${pull_status}" -eq 124 ]]; then
            reason="bounded pull timed out"
        else
            reason="pull exited with status ${pull_status}"
        fi
        warn "Secondary model ${model} failed: ${reason}"
        record_bootstrap_failure "${model}" "${reason}"
    done
}

main() {
    collect_secondary_models

    info "Checking current Ollama models"
    if has_model "${DEFAULT_MODEL}"; then
        success "Default model ${DEFAULT_MODEL} is already available"
        record_bootstrap_success "${DEFAULT_MODEL}"
        local registry_reachable="0"
        if can_reach_ollama_registry; then
            registry_reachable="1"
        else
            warn "Ollama registry is unreachable; selected secondary models may remain unavailable"
        fi
        bootstrap_secondary_models "${registry_reachable}"
        list_models
        emit_bootstrap_summary
        return 0
    fi

    local existing_models
    local pull_status=0
    local registry_reachable="0"
    existing_models="$(list_models || true)"
    if [[ -n "${existing_models}" ]]; then
        warn "Default model ${DEFAULT_MODEL} is missing, but other models are present. Bootstrap will continue for the selected default model:"
        printf '%s\n' "${existing_models}"
    fi

    if can_reach_ollama_registry; then
        registry_reachable="1"
        set +e
        pull_model "${DEFAULT_MODEL}"
        pull_status=$?
        set -e
        if [[ "${pull_status}" -eq 0 ]]; then
            pull_status=0
        fi
    else
        warn "Ollama registry is unreachable; skipping online pull and trying local assets if available"
    fi

    if has_model "${DEFAULT_MODEL}"; then
        success "Default model ${DEFAULT_MODEL} is available after bounded online bootstrap"
        record_bootstrap_success "${DEFAULT_MODEL}"
        bootstrap_secondary_models "${registry_reachable}"
        list_models
        emit_bootstrap_summary
        return 0
    fi

    if [[ -n "${LOCAL_GGUF}" ]] && create_offline_model_from_gguf "${LOCAL_GGUF}"; then
        if has_model "${DEFAULT_MODEL}"; then
            success "Default model ${DEFAULT_MODEL} is available after local GGUF bootstrap"
            record_bootstrap_success "${DEFAULT_MODEL}"
            bootstrap_secondary_models "${registry_reachable}"
            list_models
            emit_bootstrap_summary
            return 0
        fi

        warn "Local GGUF bootstrap created ${OFFLINE_MODEL_NAME}, but the required default model ${DEFAULT_MODEL} is still unavailable"
    fi

    bootstrap_secondary_models "${registry_reachable}"
    if [[ "${registry_reachable}" != "1" ]]; then
        warn "Model bootstrap failed: Ollama registry is unreachable and no usable local GGUF asset was available for ${DEFAULT_MODEL}"
        record_bootstrap_failure "${DEFAULT_MODEL}" "registry unreachable and no usable local GGUF asset"
    elif [[ -z "${LOCAL_GGUF}" ]]; then
        warn "Model bootstrap failed: bounded pull for ${DEFAULT_MODEL} did not complete successfully and no local GGUF asset is available"
        record_bootstrap_failure "${DEFAULT_MODEL}" "bounded pull failed and no local GGUF asset is available"
    elif [[ "${pull_status}" -eq 124 ]]; then
        warn "Model bootstrap failed: bounded pull for ${DEFAULT_MODEL} timed out and local GGUF fallback did not produce the required default model"
        record_bootstrap_failure "${DEFAULT_MODEL}" "bounded pull timed out and local GGUF fallback did not recover the default model"
    else
        warn "Model bootstrap failed: bounded pull for ${DEFAULT_MODEL} did not produce the required default model and local GGUF fallback did not recover it"
        record_bootstrap_failure "${DEFAULT_MODEL}" "bounded pull did not recover the default model and local GGUF fallback failed"
    fi

    if [[ -n "${existing_models}" || -n "$(list_models || true)" ]]; then
        warn "Other Ollama models may still be present, but the configured DEFAULT_MODEL=${DEFAULT_MODEL} is unavailable"
    else
        warn "No Ollama models are available."
    fi
    warn "Runtime will stay up, but chat requests that depend on DEFAULT_MODEL=${DEFAULT_MODEL} will fail until that model is installed or DEFAULT_MODEL is changed to an available local model."
    emit_bootstrap_summary
    return 1
}

if [[ "${BOOTSTRAP_OLLAMA_SOURCE_ONLY:-0}" != "1" ]]; then
    main "$@"
fi
