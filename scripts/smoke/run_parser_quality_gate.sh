#!/usr/bin/env bash

# Local deterministic parser/file-intelligence quality gate.
# This runner does not start services, call LLM/Ollama, require Docker, or require GPU.

set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
python_bin="${PYTHON:-python3}"
overall=0
results=()

core_modules=(
    tests.test_gold_file_corpus
    tests.test_gold_parser_quality
    tests.test_upload_backend
    tests.test_smoke_kit
    tests.smoke_evaluator_test
)

installer_contract_modules=(
    tests.test_install_postgres_profile
    tests.test_install_model_selection
    tests.test_bootstrap_ollama_models_contract
)

is_truthy() {
    case "${1:-}" in
        1|true|TRUE|yes|YES|y|Y|on|ON) return 0 ;;
        *) return 1 ;;
    esac
}

print_modules() {
    local label="$1"
    shift
    printf '%s\n' "${label}"
    local module
    for module in "$@"; do
        printf '  - %s\n' "${module}"
    done
}

run_module() {
    local module="$1"
    local status

    printf '\n== %s ==\n' "${module}"
    "${python_bin}" -m unittest "${module}"
    status=$?

    results+=("${module}:${status}")
    if [[ "${status}" -ne 0 ]]; then
        overall=1
    fi
}

if [[ ! -d "${repo_root}/.git" ]]; then
    printf 'ERROR: repo root not found: %s\n' "${repo_root}" >&2
    exit 2
fi

cd "${repo_root}" || exit 2

if ! command -v "${python_bin}" >/dev/null 2>&1; then
    printf 'ERROR: Python interpreter not found: %s\n' "${python_bin}" >&2
    printf 'Set PYTHON=/path/to/python or install python3.\n' >&2
    exit 2
fi

printf 'parser_quality_gate=1\n'
printf 'repo=%s\n' "${repo_root}"
printf 'git_head=%s\n' "$(git rev-parse --short HEAD 2>/dev/null || printf unknown)"
printf 'git_branch=%s\n' "$(git branch --show-current 2>/dev/null || printf unknown)"
printf 'python=%s\n' "${python_bin}"
"${python_bin}" --version

print_modules "core_modules:" "${core_modules[@]}"

modules=("${core_modules[@]}")
if is_truthy "${RUN_INSTALLER_CONTRACT:-0}"; then
    print_modules "installer_contract_modules:" "${installer_contract_modules[@]}"
    modules+=("${installer_contract_modules[@]}")
else
    printf 'installer_contract_modules=skipped; set RUN_INSTALLER_CONTRACT=1 to include them\n'
fi

for module in "${modules[@]}"; do
    run_module "${module}"
done

printf '\n=== parser quality gate summary ===\n'
for result in "${results[@]}"; do
    module="${result%%:*}"
    status="${result##*:}"
    if [[ "${status}" -eq 0 ]]; then
        printf 'PASS %s\n' "${module}"
    else
        printf 'FAIL %s status=%s\n' "${module}" "${status}"
    fi
done
printf 'overall=%s\n' "${overall}"

exit "${overall}"
