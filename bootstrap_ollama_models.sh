#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

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
LOCAL_GGUF="${LOCAL_GGUF:-$(find "${ROOT_DIR}/models" -maxdepth 1 -type f -name '*.gguf' | head -n 1 || true)}"
OFFLINE_MODEL_NAME="${OFFLINE_MODEL_NAME:-${DEFAULT_MODEL}}"
OLLAMA_PULL_TIMEOUT_SECONDS="${OLLAMA_PULL_TIMEOUT_SECONDS:-$(load_env_value "OLLAMA_PULL_TIMEOUT_SECONDS")}"
OLLAMA_PULL_TIMEOUT_SECONDS="${OLLAMA_PULL_TIMEOUT_SECONDS:-900}"
readonly PULL_MAX_ATTEMPTS=2
readonly PULL_RETRY_BACKOFF_SECONDS=5

if ! is_positive_integer "${OLLAMA_PULL_TIMEOUT_SECONDS}"; then
    warn "Invalid OLLAMA_PULL_TIMEOUT_SECONDS='${OLLAMA_PULL_TIMEOUT_SECONDS}', falling back to 900 seconds"
    OLLAMA_PULL_TIMEOUT_SECONDS="900"
fi

list_models() {
    compose exec -T ollama ollama list 2>/dev/null | awk 'NR>1 && NF {print $1}'
}

has_model() {
    local model="$1"
    list_models | grep -Fx "${model}" >/dev/null 2>&1
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

main() {
    info "Checking current Ollama models"
    if has_model "${DEFAULT_MODEL}"; then
        success "Default model ${DEFAULT_MODEL} is already available"
        list_models
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
        if pull_model "${DEFAULT_MODEL}"; then
            pull_status=0
        else
            pull_status=$?
        fi
    else
        warn "Ollama registry is unreachable; skipping online pull and trying local assets if available"
    fi

    if has_model "${DEFAULT_MODEL}"; then
        success "Default model ${DEFAULT_MODEL} is available after bounded online bootstrap"
        if [[ -n "${SECONDARY_MODEL}" && "${SECONDARY_MODEL}" != "${DEFAULT_MODEL}" ]]; then
            pull_model "${SECONDARY_MODEL}" || warn "Optional secondary model ${SECONDARY_MODEL} was not pulled; continuing with default model only"
        fi
        list_models
        return 0
    fi

    if [[ -n "${LOCAL_GGUF}" ]] && create_offline_model_from_gguf "${LOCAL_GGUF}"; then
        if has_model "${DEFAULT_MODEL}"; then
            success "Default model ${DEFAULT_MODEL} is available after local GGUF bootstrap"
            list_models
            return 0
        fi

        warn "Local GGUF bootstrap created ${OFFLINE_MODEL_NAME}, but the required default model ${DEFAULT_MODEL} is still unavailable"
    fi

    if [[ "${registry_reachable}" != "1" ]]; then
        warn "Model bootstrap failed: Ollama registry is unreachable and no usable local GGUF asset was available for ${DEFAULT_MODEL}"
    elif [[ -z "${LOCAL_GGUF}" ]]; then
        warn "Model bootstrap failed: bounded pull for ${DEFAULT_MODEL} did not complete successfully and no local GGUF asset is available"
    elif [[ "${pull_status}" -eq 124 ]]; then
        warn "Model bootstrap failed: bounded pull for ${DEFAULT_MODEL} timed out and local GGUF fallback did not produce the required default model"
    else
        warn "Model bootstrap failed: bounded pull for ${DEFAULT_MODEL} did not produce the required default model and local GGUF fallback did not recover it"
    fi

    if [[ -n "${existing_models}" || -n "$(list_models || true)" ]]; then
        warn "Other Ollama models may still be present, but the configured DEFAULT_MODEL=${DEFAULT_MODEL} is unavailable"
    else
        warn "No Ollama models are available."
    fi
    warn "Runtime will stay up, but chat requests that depend on DEFAULT_MODEL=${DEFAULT_MODEL} will fail until that model is installed or DEFAULT_MODEL is changed to an available local model."
    return 1
}

if [[ "${BOOTSTRAP_OLLAMA_SOURCE_ONLY:-0}" != "1" ]]; then
    main "$@"
fi
