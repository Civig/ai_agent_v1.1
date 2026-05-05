#!/usr/bin/env bash

# Local deterministic comparison-engine quality gate.
# This runner does not start services, call LLM/Ollama, require Docker, or require GPU.

set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
python_bin="${PYTHON:-python3}"
overall=0
results=()

comparison_modules=(
    tests.test_comparison_engine_normalizer
    tests.test_comparison_engine_diff
    tests.test_comparison_engine_report
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

run_parser_gate() {
    local parser_gate="${repo_root}/scripts/smoke/run_parser_quality_gate.sh"
    local status

    printf '\n== parser quality gate ==\n'
    if [[ ! -f "${parser_gate}" ]]; then
        printf 'ERROR: parser quality gate not found: %s\n' "${parser_gate}" >&2
        results+=("parser_quality_gate:2")
        overall=1
        return
    fi

    PYTHON="${python_bin}" bash "${parser_gate}"
    status=$?
    results+=("parser_quality_gate:${status}")
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

printf 'comparison_quality_gate=1\n'
printf 'repo=%s\n' "${repo_root}"
printf 'git_head=%s\n' "$(git rev-parse --short HEAD 2>/dev/null || printf unknown)"
printf 'git_branch=%s\n' "$(git branch --show-current 2>/dev/null || printf unknown)"
printf 'python=%s\n' "${python_bin}"
"${python_bin}" --version

print_modules "comparison_modules:" "${comparison_modules[@]}"
if is_truthy "${RUN_PARSER_GATE:-0}"; then
    printf 'parser_quality_gate=enabled\n'
else
    printf 'parser_quality_gate=skipped; set RUN_PARSER_GATE=1 to include it\n'
fi

for module in "${comparison_modules[@]}"; do
    run_module "${module}"
done

if is_truthy "${RUN_PARSER_GATE:-0}"; then
    run_parser_gate
fi

printf '\n=== comparison quality gate summary ===\n'
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
