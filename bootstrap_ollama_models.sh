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

load_env_default_model() {
    local value=""
    if [[ -f "${ROOT_DIR}/.env" ]]; then
        value="$(awk -F= '$1=="DEFAULT_MODEL" {gsub(/\r/,"",$2); print $2; exit}' "${ROOT_DIR}/.env" || true)"
    fi
    printf '%s' "${value}"
}

DEFAULT_MODEL="${DEFAULT_MODEL:-$(load_env_default_model)}"
DEFAULT_MODEL="${DEFAULT_MODEL:-gemma2:2b}"
SECONDARY_MODEL="${SECONDARY_MODEL:-mistral}"
LOCAL_GGUF="${LOCAL_GGUF:-$(find "${ROOT_DIR}/models" -maxdepth 1 -type f -name '*.gguf' | head -n 1 || true)}"
OFFLINE_MODEL_NAME="${OFFLINE_MODEL_NAME:-phi3-local}"

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
    info "Attempting to pull ${model} into Ollama"
    if compose exec -T ollama ollama pull "${model}"; then
        success "Pulled ${model}"
        return 0
    fi
    warn "Failed to pull ${model}"
    return 1
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
    existing_models="$(list_models || true)"
    if [[ -n "${existing_models}" ]]; then
        warn "Default model ${DEFAULT_MODEL} is missing, but other models are present:"
        printf '%s\n' "${existing_models}"
        return 0
    fi

    if can_reach_ollama_registry; then
        pull_model "${DEFAULT_MODEL}" || true
        if [[ -n "${SECONDARY_MODEL}" ]]; then
            pull_model "${SECONDARY_MODEL}" || true
        fi
    else
        warn "Ollama registry is unreachable; assuming offline environment"
    fi

    if has_model "${DEFAULT_MODEL}" || [[ -n "$(list_models || true)" ]]; then
        success "Ollama model bootstrap completed with pulled models"
        list_models
        return 0
    fi

    if [[ -n "${LOCAL_GGUF}" ]] && create_offline_model_from_gguf "${LOCAL_GGUF}"; then
        list_models
        return 0
    fi

    warn "No Ollama models are available."
    warn "Runtime will stay up, but /api/chat will return 'No LLM models available' until at least one model is installed."
    return 1
}

main "$@"
