#!/usr/bin/env bash

set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib_smoke.sh"
cd "${SMOKE_REPO_ROOT}"
smoke_init_artifact_dir "full-smoke" >/dev/null

summary="${SMOKE_ARTIFACT_DIR}/summary.txt"
: >"${summary}"
overall=0

run_step() {
    local name="$1"
    shift
    printf '== %s ==\n' "${name}" | tee -a "${summary}"
    set +e
    "$@" >"${SMOKE_ARTIFACT_DIR}/${name}.log" 2>&1
    local code=$?
    set -e
    printf '%s=%s\n' "${name}" "${code}" | tee -a "${summary}"
    if [[ "${code}" -ne 0 && "${overall}" -eq 0 ]]; then
        overall="${code}"
    fi
}

run_step preflight "${SMOKE_REPO_ROOT}/scripts/smoke/preflight_gpu_host.sh"
run_step runtime_ready "${SMOKE_REPO_ROOT}/scripts/smoke/check_runtime_ready.sh"
run_step chat_smoke "${SMOKE_REPO_ROOT}/scripts/smoke/run_chat_smoke.sh"
run_step file_chat_smoke "${SMOKE_REPO_ROOT}/scripts/smoke/run_file_chat_smoke.sh"
run_step metrics_final "${SMOKE_REPO_ROOT}/scripts/smoke/collect_metrics.sh" --phase final

printf 'overall=%s\nartifacts=%s\n' "${overall}" "${SMOKE_ARTIFACT_DIR}" | tee -a "${summary}"
cat "${summary}"
exit "${overall}"
