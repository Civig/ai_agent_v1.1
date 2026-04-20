#!/usr/bin/env bash

set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib_smoke.sh"
cd "${SMOKE_REPO_ROOT}"
phase="final"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase)
            phase="$2"
            shift 2
            ;;
        *)
            printf 'Unknown argument: %s\n' "$1" >&2
            exit 2
            ;;
    esac
done

smoke_init_artifact_dir "metrics" >/dev/null
metrics_dir="${SMOKE_ARTIFACT_DIR}/metrics/${phase}"
logs_dir="${metrics_dir}/logs"
mkdir -p "${logs_dir}"

smoke_capture_command "${metrics_dir}/docker-compose-ps.txt" docker compose ps
smoke_capture_command "${metrics_dir}/docker-ps-a.txt" docker ps -a
smoke_capture_command "${metrics_dir}/nvidia-smi.txt" nvidia-smi
smoke_capture_shell "${metrics_dir}/ollama-ps.txt" 'docker compose exec -T ollama ollama ps'

available_services="$(docker compose ps --services 2>/dev/null || true)"
services=(app worker-gpu worker-parser scheduler worker-chat ollama nginx)
for service in "${services[@]}"; do
    if grep -qx "${service}" <<<"${available_services}"; then
        smoke_capture_command "${logs_dir}/${service}.log" docker compose logs --no-color --tail="${SMOKE_LOG_TAIL}" "${service}"
    else
        printf 'service_not_present_or_not_running=%s\n' "${service}" >"${logs_dir}/${service}.log"
    fi
done

combined="${metrics_dir}/combined-runtime.log"
cat "${logs_dir}"/*.log >"${combined}" 2>/dev/null || true
"${SMOKE_PYTHON}" "${SMOKE_REPO_ROOT}/scripts/smoke/smoke_common.py" \
    observability \
    --input "${combined}" \
    --jsonl "${metrics_dir}/observability.jsonl" \
    --csv "${metrics_dir}/observability.csv" \
    >"${metrics_dir}/observability-count.txt"

grep -E 'pending_wait_ms|admitted_wait_ms|queue_wait_ms|inference_ms|total_job_ms|parse_ms|doc_chars|job_terminal_observability|file_parse_observability' \
    "${combined}" >"${metrics_dir}/observability-lines.txt" 2>/dev/null || true

printf 'Metrics collected for phase=%s\n' "${phase}"
smoke_print_artifact_hint
