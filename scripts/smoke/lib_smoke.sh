#!/usr/bin/env bash

set -Eeuo pipefail

SMOKE_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SMOKE_REPO_ROOT="$(cd "${SMOKE_SCRIPT_DIR}/../.." && pwd)"
SMOKE_PYTHON="${SMOKE_PYTHON:-python3}"
SMOKE_BASE_URL="${SMOKE_BASE_URL:-https://127.0.0.1}"
SMOKE_INSECURE="${SMOKE_INSECURE:-1}"
SMOKE_TIMEOUT_SECONDS="${SMOKE_TIMEOUT_SECONDS:-240}"
SMOKE_CONNECT_TIMEOUT_SECONDS="${SMOKE_CONNECT_TIMEOUT_SECONDS:-10}"
SMOKE_LOG_TAIL="${SMOKE_LOG_TAIL:-1000}"

smoke_bool() {
    case "${1:-}" in
        1|true|TRUE|yes|YES|y|Y|on|ON) return 0 ;;
        *) return 1 ;;
    esac
}

smoke_python_insecure_args() {
    if smoke_bool "${SMOKE_INSECURE}"; then
        printf '%s\n' "--insecure"
    fi
}

smoke_init_artifact_dir() {
    local label="$1"
    if [[ -z "${SMOKE_ARTIFACT_DIR:-}" ]]; then
        SMOKE_ARTIFACT_DIR="$(
            "${SMOKE_PYTHON}" "${SMOKE_REPO_ROOT}/scripts/smoke/smoke_common.py" \
                create-artifact-dir \
                --root "${SMOKE_REPO_ROOT}/artifacts/smoke" \
                --label "${label}"
        )"
        export SMOKE_ARTIFACT_DIR
    else
        mkdir -p "${SMOKE_ARTIFACT_DIR}"
    fi
    printf '%s\n' "${SMOKE_ARTIFACT_DIR}"
}

smoke_env_value() {
    local key="$1"
    "${SMOKE_PYTHON}" - "${SMOKE_REPO_ROOT}/.env" "${key}" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
if not path.exists():
    raise SystemExit(0)
for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    current, value = line.split("=", 1)
    if current.strip() == key:
        print(value.strip().strip("'\""))
        break
PY
}

smoke_resolve_username() {
    if [[ -n "${SMOKE_USERNAME:-}" ]]; then
        printf '%s\n' "${SMOKE_USERNAME}"
        return
    fi
    smoke_env_value "INSTALL_TEST_USER"
}

smoke_resolve_password() {
    if [[ -n "${SMOKE_PASSWORD:-}" ]]; then
        printf '%s\n' "${SMOKE_PASSWORD}"
        return
    fi
    if [[ -n "${SMOKE_PASSWORD_FILE:-}" && -f "${SMOKE_PASSWORD_FILE}" ]]; then
        "${SMOKE_PYTHON}" - "${SMOKE_PASSWORD_FILE}" <<'PY'
import sys
from scripts.smoke.smoke_common import read_password_file
print(read_password_file(sys.argv[1]))
PY
    fi
}

smoke_require_credentials() {
    local username password
    username="$(smoke_resolve_username)"
    password="$(smoke_resolve_password)"
    if [[ -z "${username}" || -z "${password}" ]]; then
        printf 'Smoke credentials are missing. Set SMOKE_USERNAME and SMOKE_PASSWORD, or SMOKE_PASSWORD_FILE plus INSTALL_TEST_USER in .env.\n' >&2
        return 2
    fi
}

smoke_curl_flags() {
    local flags=("-sS" "--connect-timeout" "${SMOKE_CONNECT_TIMEOUT_SECONDS}" "--max-time" "${SMOKE_TIMEOUT_SECONDS}")
    if smoke_bool "${SMOKE_INSECURE}"; then
        flags=("-k" "${flags[@]}")
    fi
    printf '%s\n' "${flags[@]}"
}

smoke_capture_command() {
    local output_file="$1"
    shift
    mkdir -p "$(dirname "${output_file}")"
    {
        printf '$'
        printf ' %q' "$@"
        printf '\n'
        "$@"
    } >"${output_file}" 2>&1 || {
        local code=$?
        printf '\n[command exited with %s]\n' "${code}" >>"${output_file}"
        return 0
    }
}

smoke_capture_shell() {
    local output_file="$1"
    local command_text="$2"
    mkdir -p "$(dirname "${output_file}")"
    {
        printf '$ %s\n' "${command_text}"
        bash -lc "${command_text}"
    } >"${output_file}" 2>&1 || {
        local code=$?
        printf '\n[command exited with %s]\n' "${code}" >>"${output_file}"
        return 0
    }
}

smoke_extract_csrf() {
    local cookiejar="$1"
    "${SMOKE_PYTHON}" "${SMOKE_REPO_ROOT}/scripts/smoke/smoke_common.py" \
        extract-cookie \
        --cookiejar "${cookiejar}" \
        --name "csrf_token"
}

smoke_login_with_curl() {
    local cookiejar="$1"
    local output_dir="$2"
    local username password code user_code
    mapfile -t curl_flags < <(smoke_curl_flags)
    username="$(smoke_resolve_username)"
    password="$(smoke_resolve_password)"
    mkdir -p "${output_dir}/auth"

    curl "${curl_flags[@]}" \
        -c "${cookiejar}" \
        -b "${cookiejar}" \
        -o "${output_dir}/auth/login_page.html" \
        "${SMOKE_BASE_URL%/}/login" || true

    code="$(
        curl "${curl_flags[@]}" \
            -o "${output_dir}/auth/login_response.html" \
            -w '%{http_code}' \
            -c "${cookiejar}" \
            -b "${cookiejar}" \
            -X POST "${SMOKE_BASE_URL%/}/login" \
            --data-urlencode "username=${username}" \
            --data-urlencode "password=${password}"
    )"
    if [[ "${code}" != "303" && "${code}" != "302" && "${code}" != "200" ]]; then
        printf 'login_http_status=%s\n' "${code}" >"${output_dir}/auth/login_status.txt"
        return 2
    fi

    user_code="$(
        curl "${curl_flags[@]}" \
            -o "${output_dir}/auth/api_user.json" \
            -w '%{http_code}' \
            -b "${cookiejar}" \
            -H 'Accept: application/json' \
            "${SMOKE_BASE_URL%/}/api/user"
    )"
    printf 'login_http_status=%s\napi_user_http_status=%s\ncsrf_present=%s\n' \
        "${code}" \
        "${user_code}" \
        "$(test -n "$(smoke_extract_csrf "${cookiejar}")" && printf yes || printf no)" \
        >"${output_dir}/auth/login_status.txt"
    [[ "${user_code}" == "200" ]]
}

smoke_print_artifact_hint() {
    printf 'Artifacts: %s\n' "${SMOKE_ARTIFACT_DIR}"
}
