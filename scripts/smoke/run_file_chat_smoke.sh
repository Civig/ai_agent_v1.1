#!/usr/bin/env bash

set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib_smoke.sh"
cd "${SMOKE_REPO_ROOT}"
smoke_init_artifact_dir "file-chat-smoke" >/dev/null

tls_args=()
if smoke_bool "${SMOKE_INSECURE}"; then
    tls_args+=(--insecure)
fi

set +e
"${SMOKE_PYTHON}" "${SMOKE_REPO_ROOT}/scripts/smoke/smoke_runner.py" \
    file-chat \
    --host "${SMOKE_BASE_URL}" \
    --output-dir "${SMOKE_ARTIFACT_DIR}" \
    --spec "${SMOKE_REPO_ROOT}/tests/smoke/specs/file_chat_cases.json" \
    --timeout-seconds "${SMOKE_TIMEOUT_SECONDS}" \
    "${tls_args[@]}"
status=$?
set -e

"${SMOKE_REPO_ROOT}/scripts/smoke/collect_metrics.sh" --phase file-chat || true
smoke_print_artifact_hint
exit "${status}"
