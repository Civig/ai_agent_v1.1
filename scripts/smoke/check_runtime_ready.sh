#!/usr/bin/env bash

set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib_smoke.sh"
cd "${SMOKE_REPO_ROOT}"
smoke_init_artifact_dir "runtime-ready" >/dev/null

runtime_dir="${SMOKE_ARTIFACT_DIR}/runtime-ready"
mkdir -p "${runtime_dir}"
status=0

{
    printf 'safe_env_report_generated_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    for key in DEFAULT_MODEL INSTALL_TEST_USER ENABLE_PARSER_STAGE ENABLE_PARSER_PUBLIC_CUTOVER LOCAL_ADMIN_ENABLED LOCAL_ADMIN_USERNAME LOCAL_ADMIN_FORCE_ROTATE LOCAL_ADMIN_BOOTSTRAP_REQUIRED FILE_PROCESSING_MAX_FILES FILE_PROCESSING_IMAGE_MAX_DIMENSION; do
        printf '%s=%s\n' "${key}" "$(smoke_env_value "${key}")"
    done
    for key in SECRET_KEY REDIS_PASSWORD POSTGRES_PASSWORD LOCAL_ADMIN_PASSWORD_HASH; do
        value="$(smoke_env_value "${key}")"
        if [[ -n "${value}" ]]; then
            printf '%s=present length=%s\n' "${key}" "${#value}"
        else
            printf '%s=missing\n' "${key}"
        fi
    done
} >"${runtime_dir}/env-safe-report.txt"

smoke_capture_command "${runtime_dir}/docker-compose-ps.txt" docker compose ps

mapfile -t curl_flags < <(smoke_curl_flags)
for endpoint in /health/live /health/ready; do
    name="${endpoint#/health/}"
    code="$(
        curl "${curl_flags[@]}" \
            -o "${runtime_dir}/health-${name}.json" \
            -w '%{http_code}' \
            -H 'Accept: application/json' \
            "${SMOKE_BASE_URL%/}${endpoint}" || true
    )"
    printf '%s\n' "${code}" >"${runtime_dir}/health-${name}.status"
    if [[ "${code}" != "200" ]]; then
        status=1
    fi
done

smoke_capture_shell "${runtime_dir}/ollama-list.txt" 'docker compose exec -T ollama ollama list'
smoke_capture_shell "${runtime_dir}/ollama-ps.txt" 'docker compose exec -T ollama ollama ps'
printf 'DEFAULT_MODEL=%s\n' "$(smoke_env_value DEFAULT_MODEL)" >"${runtime_dir}/default-model.txt"

bootstrap_file="${INSTALL_HOST_STATE_DIR:-/var/lib/corporate-ai-assistant}/local-admin-bootstrap.secret"
{
    printf 'path=%s\n' "${bootstrap_file}"
    if [[ -e "${bootstrap_file}" ]]; then
        printf 'exists=yes\n'
        stat -c 'mode=%a owner=%U group=%G size=%s' "${bootstrap_file}" || true
    else
        printf 'exists=no\n'
    fi
} >"${runtime_dir}/bootstrap-secret-file.txt"

if smoke_require_credentials; then
    cookiejar="${runtime_dir}/cookies.jar"
    if smoke_login_with_curl "${cookiejar}" "${runtime_dir}"; then
        csrf="$(smoke_extract_csrf "${cookiejar}")"
        printf 'csrf_present=%s\n' "$(test -n "${csrf}" && printf yes || printf no)" >"${runtime_dir}/csrf-status.txt"
        models_code="$(
            curl "${curl_flags[@]}" \
                -o "${runtime_dir}/api-models.json" \
                -w '%{http_code}' \
                -b "${cookiejar}" \
                -H 'Accept: application/json' \
                "${SMOKE_BASE_URL%/}/api/models" || true
        )"
        printf '%s\n' "${models_code}" >"${runtime_dir}/api-models.status"
        if [[ "${models_code}" != "200" ]]; then
            status=1
        fi
    else
        status=2
    fi
else
    mkdir -p "${runtime_dir}/auth"
    printf 'login_skipped=missing_smoke_credentials\n' >"${runtime_dir}/auth/login_status.txt"
    status=2
fi

printf 'Runtime ready check status=%s\n' "${status}"
smoke_print_artifact_hint
exit "${status}"
