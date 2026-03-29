#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${ROOT_DIR}/.install"
LOG_FILE="${LOG_DIR}/install-$(date +%Y%m%d-%H%M%S).log"
STATE_FILE="${LOG_DIR}/install-state.env"
HOST_STATE_DIR="/var/lib/corporate-ai-assistant"
HOST_STATE_FILE="${HOST_STATE_DIR}/host-state.env"
HOST_BACKUP_DIR="${HOST_STATE_DIR}/backups"
HOST_DOCKER_REPO_BACKUP="${HOST_BACKUP_DIR}/docker.list.preinstall.bak"
INSTALL_USER="${SUDO_USER:-${USER:-$(id -un)}}"

mkdir -p "${LOG_DIR}"
touch "${LOG_FILE}"
chmod 700 "${LOG_DIR}"
chmod 600 "${LOG_FILE}"
exec > >(tee -a "${LOG_FILE}") 2>&1

readonly ROOT_DIR
readonly LOG_DIR
readonly LOG_FILE
readonly STATE_FILE
readonly HOST_STATE_DIR
readonly HOST_STATE_FILE
readonly HOST_BACKUP_DIR
readonly HOST_DOCKER_REPO_BACKUP
readonly INSTALL_USER

MANAGED_OVERRIDE_MARKER="# Managed by Corporate AI Assistant install.sh"
MANAGED_OVERRIDE_FILE="${ROOT_DIR}/docker-compose.override.yml"
readonly MANAGED_OVERRIDE_MARKER
readonly MANAGED_OVERRIDE_FILE

readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly RED='\033[0;31m'
readonly NC='\033[0m'

APT_UPDATED=0
OS_ID=""
OS_VERSION_ID=""
OS_CODENAME=""

DOMAIN=""
LDAP_SERVER_HOST=""
LDAP_SERVER_URL=""
BASE_DN=""
NETBIOS_DOMAIN=""
KERBEROS_REALM=""
KERBEROS_KDC=""
DEFAULT_MODEL="phi3:mini"
DOWNLOAD_DEFAULT_MODEL_NOW="true"
MODEL_ACCESS_CODING_GROUPS=""
MODEL_ACCESS_ADMIN_GROUPS=""
SSO_ENABLED="false"
SSO_SERVICE_PRINCIPAL=""
SSO_KEYTAB_PATH="/etc/corporate-ai-sso/http.keytab"
REDIS_PASSWORD=""
SECRET_KEY=""
TEST_ADMIN_USER=""
TEST_ADMIN_PASSWORD=""
AD_SERVER_IP_OVERRIDE=""
INSTALL_MODE="${INSTALL_MODE:-auto}"
INSTALL_NONINTERACTIVE="${INSTALL_NONINTERACTIVE:-}"
SELECTED_INSTALL_MODE=""

AUDIT_HOSTNAME="unknown"
AUDIT_IP_ADDRESSES="unknown"
AUDIT_CPU_MODEL="unknown"
AUDIT_CPU_CORES="unknown"
AUDIT_TOTAL_RAM_GB="unknown"
AUDIT_TOTAL_RAM_GB_RAW=0
AUDIT_DISK_FREE_GB="unknown"
AUDIT_DISK_FREE_GB_RAW=0
AUDIT_DOCKER_STATUS="not installed"
AUDIT_COMPOSE_STATUS="not installed"
AUDIT_GPU_STATUS="not detected"
AUDIT_GPU_VENDOR="unknown"
AUDIT_GPU_MODEL="unknown"
AUDIT_GPU_VRAM="unknown"
AUDIT_GPU_RUNTIME_STATUS="unknown"
AUDIT_GPU_PROFILE_STATUS="unknown"
AUDIT_NVIDIA_SMI_STATUS="not found"
AUDIT_LSPCI_STATUS="not found"
AUDIT_OUTBOUND_DOCKER_DOWNLOAD="unknown"
AUDIT_OUTBOUND_DOCKER_REGISTRY="unknown"
AUDIT_OUTBOUND_OLLAMA="unknown"
AUDIT_OUTBOUND_PYPI="unknown"
DETECTED_DEPLOYMENT_TARGET="unknown"
RECOMMENDED_INSTALL_MODE="cpu"
MODEL_BOOTSTRAP_STATUS="pending"
MODEL_PRESENT_AFTER_BOOTSTRAP="unknown"
CHAT_READY_IMMEDIATELY="no"
TLS_CERTS_GENERATED_BY_INSTALLER="0"
PREINSTALL_DOCKER_CLI="0"
PREINSTALL_DOCKER_COMPOSE_PLUGIN="0"
PREINSTALL_DOCKER_SERVICE_ENABLED="0"
PREINSTALL_DOCKER_SERVICE_ACTIVE="0"
PREINSTALL_OLLAMA_CLI="0"
PREINSTALL_OLLAMA_SERVICE_PRESENT="0"
PREINSTALL_OLLAMA_SERVICE_ENABLED="0"
PREINSTALL_OLLAMA_SERVICE_ACTIVE="0"
PREINSTALL_USER_IN_DOCKER_GROUP="0"
PREEXISTING_DOCKER_KEYRING="0"
PREEXISTING_DOCKER_REPO_FILE="0"
INSTALLER_MANAGED_DOCKER_REPO_FILE="0"
DOCKER_REPO_FILE_BACKUP=""
INSTALLER_ADDED_DOCKER_KEYRING="0"
INSTALLER_ADDED_USER_TO_DOCKER_GROUP="0"
INSTALLER_INSTALLED_DOCKER_ENGINE="0"
INSTALLER_INSTALLED_DOCKER_COMPOSE_PLUGIN="0"
INSTALLER_INSTALLED_OLLAMA_CLI="0"
POSTINSTALL_OLLAMA_BIN_PATH=""
POSTINSTALL_OLLAMA_SERVICE_FRAGMENT=""

declare -a APT_PACKAGES_INSTALLED_BY_INSTALLER=()

readonly SUPPORTED_INSTALL_MODES="auto cpu gpu"
readonly MIN_RECOMMENDED_CPU_CORES=4
readonly MIN_RECOMMENDED_RAM_GB=8
readonly MIN_RECOMMENDED_DISK_GB=40

print_header() {
    printf "%b========================================%b\n" "${BLUE}" "${NC}"
    printf "%b%s%b\n" "${BLUE}" "$1" "${NC}"
    printf "%b========================================%b\n" "${BLUE}" "${NC}"
}

print_success() {
    printf "%b[OK]%b %s\n" "${GREEN}" "${NC}" "$1"
}

print_warning() {
    printf "%b[WARN]%b %s\n" "${YELLOW}" "${NC}" "$1"
}

print_error() {
    printf "%b[ERROR]%b %s\n" "${RED}" "${NC}" "$1" >&2
}

print_info() {
    printf "%b[INFO]%b %s\n" "${BLUE}" "${NC}" "$1"
}

die() {
    print_error "$1"
    print_error "Install log: ${LOG_FILE}"
    exit 1
}

on_error() {
    local line="$1"
    print_error "Installer failed near line ${line}"
    print_error "Install log: ${LOG_FILE}"
}

trap 'on_error "${LINENO}"' ERR

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

trim_whitespace() {
    local value="$1"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf "%s" "${value}"
}

yes_no_unknown() {
    local value="$1"
    case "${value}" in
        yes|ok|available|installed|detected)
            printf "yes"
            ;;
        no|absent|missing|unavailable|"not installed"|"not detected"|"not found")
            printf "no"
            ;;
        *)
            printf "unknown"
            ;;
    esac
}

is_interactive_shell() {
    [[ -t 0 && -z "${INSTALL_NONINTERACTIVE}" ]]
}

is_positive_answer() {
    local value="${1,,}"
    [[ -z "${value}" || "${value}" == "y" || "${value}" == "yes" ]]
}

status_from_command() {
    if command_exists "$1"; then
        printf "installed"
    else
        printf "not installed"
    fi
}

bool_is_true() {
    [[ "${1:-0}" == "1" || "${1:-}" == "true" ]]
}

systemd_unit_exists() {
    command_exists systemctl && systemctl list-unit-files "$1" >/dev/null 2>&1
}

systemd_unit_enabled() {
    systemd_unit_exists "$1" && systemctl is-enabled "$1" >/dev/null 2>&1
}

systemd_unit_active() {
    systemd_unit_exists "$1" && systemctl is-active "$1" >/dev/null 2>&1
}

append_unique_installed_package() {
    local pkg="$1"
    local existing
    for existing in "${APT_PACKAGES_INSTALLED_BY_INSTALLER[@]}"; do
        [[ "${existing}" == "${pkg}" ]] && return
    done
    APT_PACKAGES_INSTALLED_BY_INSTALLER+=("${pkg}")
}

append_unique_array_item() {
    local array_name="$1"
    local item="$2"
    local existing
    local -n target_array="${array_name}"

    for existing in "${target_array[@]}"; do
        [[ "${existing}" == "${item}" ]] && return
    done
    target_array+=("${item}")
}

array_contains() {
    local needle="$1"
    shift
    local item
    for item in "$@"; do
        [[ "${item}" == "${needle}" ]] && return 0
    done
    return 1
}

state_file_value() {
    local file="$1"
    local key="$2"

    [[ -f "${file}" ]] || return 1
    awk -F= -v key="${key}" '$1 == key { print substr($0, index($0, "=") + 1) }' "${file}" | tail -n 1
}

coalesce_value() {
    local value
    for value in "$@"; do
        if [[ -n "${value}" ]]; then
            printf "%s" "${value}"
            return 0
        fi
    done
    return 1
}

or_bool() {
    if bool_is_true "${1:-0}" || bool_is_true "${2:-0}"; then
        printf "1"
    else
        printf "0"
    fi
}

join_by_space() {
    local output=""
    local item
    for item in "$@"; do
        [[ -z "${item}" ]] && continue
        if [[ -n "${output}" ]]; then
            output+=" "
        fi
        output+="${item}"
    done
    printf "%s" "${output}"
}

capture_preinstall_state() {
    if command_exists docker; then
        PREINSTALL_DOCKER_CLI="1"
        if docker compose version >/dev/null 2>&1; then
            PREINSTALL_DOCKER_COMPOSE_PLUGIN="1"
        fi
    fi

    if command_exists ollama; then
        PREINSTALL_OLLAMA_CLI="1"
    fi

    if id -nG "${INSTALL_USER}" 2>/dev/null | grep -qw docker; then
        PREINSTALL_USER_IN_DOCKER_GROUP="1"
    fi

    [[ -f /etc/apt/keyrings/docker.asc ]] && PREEXISTING_DOCKER_KEYRING="1"
    [[ -f /etc/apt/sources.list.d/docker.list ]] && PREEXISTING_DOCKER_REPO_FILE="1"

    if systemd_unit_exists docker.service; then
        systemd_unit_enabled docker.service && PREINSTALL_DOCKER_SERVICE_ENABLED="1"
        systemd_unit_active docker.service && PREINSTALL_DOCKER_SERVICE_ACTIVE="1"
    fi

    if systemd_unit_exists ollama.service; then
        PREINSTALL_OLLAMA_SERVICE_PRESENT="1"
        systemd_unit_enabled ollama.service && PREINSTALL_OLLAMA_SERVICE_ENABLED="1"
        systemd_unit_active ollama.service && PREINSTALL_OLLAMA_SERVICE_ACTIVE="1"
    fi
}

safe_lscpu_field() {
    local field="$1"
    if command_exists lscpu; then
        lscpu 2>/dev/null | awk -F: -v field="${field}" '$1 ~ field {sub(/^[ \t]+/, "", $2); print $2; exit}'
    fi
}

detect_cpu_model() {
    local value=""
    value="$(safe_lscpu_field "Model name" || true)"
    if [[ -z "${value}" && -r /proc/cpuinfo ]]; then
        value="$(awk -F: '/model name/ {sub(/^[ \t]+/, "", $2); print $2; exit}' /proc/cpuinfo 2>/dev/null || true)"
    fi
    value="$(trim_whitespace "${value}")"
    printf "%s" "${value:-unknown}"
}

detect_cpu_cores() {
    local value=""
    if command_exists nproc; then
        value="$(nproc 2>/dev/null || true)"
    fi
    value="$(trim_whitespace "${value}")"
    printf "%s" "${value:-unknown}"
}

detect_total_ram_gb_raw() {
    if [[ -r /proc/meminfo ]]; then
        awk '/MemTotal:/ {printf "%.0f", $2 / 1024 / 1024; exit}' /proc/meminfo 2>/dev/null
        return
    fi
    printf "0"
}

detect_disk_free_gb_raw() {
    df -Pk "${ROOT_DIR}" 2>/dev/null | awk 'NR == 2 {printf "%.0f", $4 / 1024 / 1024; exit}'
}

detect_ip_addresses() {
    local value=""
    value="$(hostname -I 2>/dev/null | xargs || true)"
    printf "%s" "${value:-unknown}"
}

probe_http_url() {
    local url="$1"
    if command_exists curl; then
        if curl -sS -I -o /dev/null --connect-timeout 5 "${url}" >/dev/null 2>&1; then
            printf "ok"
        else
            printf "failed"
        fi
        return
    fi

    if command_exists python3; then
        if python3 - "$url" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

url = sys.argv[1]
with urllib.request.urlopen(url, timeout=5) as response:
    status = getattr(response, "status", 200)
    if status >= 500:
        raise SystemExit(1)
PY
        then
            printf "ok"
        else
            printf "failed"
        fi
        return
    fi

    printf "unknown"
}

detect_outbound_connectivity() {
    AUDIT_OUTBOUND_DOCKER_DOWNLOAD="$(probe_http_url "https://download.docker.com/linux/")"
    AUDIT_OUTBOUND_DOCKER_REGISTRY="$(probe_http_url "https://registry-1.docker.io/v2/")"
    AUDIT_OUTBOUND_OLLAMA="$(probe_http_url "https://ollama.com")"
    AUDIT_OUTBOUND_PYPI="$(probe_http_url "https://pypi.org/simple/")"
}

detect_gpu_profile_status() {
    if grep -q "worker-gpu" "${ROOT_DIR}/docker-compose.yml" 2>/dev/null; then
        printf "available"
    else
        printf "missing"
    fi
}

detect_gpu_runtime_status() {
    local runtimes=""

    if ! command_exists docker; then
        printf "unknown"
        return
    fi

    if ! docker info >/dev/null 2>&1; then
        printf "unknown"
        return
    fi

    runtimes="$(docker info --format '{{json .Runtimes}}' 2>/dev/null || true)"
    if [[ -n "${runtimes}" ]] && grep -qi "nvidia" <<<"${runtimes}"; then
        printf "available"
        return
    fi

    if [[ -f /etc/docker/daemon.json ]] && grep -qi "nvidia" /etc/docker/daemon.json; then
        printf "configured"
        return
    fi

    printf "not detected"
}

detect_gpu_hardware() {
    local query_output=""
    local lspci_line=""

    AUDIT_GPU_STATUS="not detected"
    AUDIT_GPU_VENDOR="unknown"
    AUDIT_GPU_MODEL="unknown"
    AUDIT_GPU_VRAM="unknown"
    AUDIT_NVIDIA_SMI_STATUS="not found"
    AUDIT_LSPCI_STATUS="not found"

    if command_exists nvidia-smi; then
        AUDIT_NVIDIA_SMI_STATUS="present"
        query_output="$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -n1 || true)"
        if [[ -n "${query_output}" ]]; then
            AUDIT_GPU_STATUS="detected"
            AUDIT_GPU_VENDOR="NVIDIA"
            AUDIT_GPU_MODEL="$(trim_whitespace "${query_output%%,*}")"
            AUDIT_GPU_VRAM="$(trim_whitespace "${query_output#*,}")"
        fi
    fi

    if command_exists lspci; then
        AUDIT_LSPCI_STATUS="present"
        if [[ "${AUDIT_GPU_STATUS}" != "detected" ]]; then
            lspci_line="$(lspci 2>/dev/null | grep -Ei 'VGA compatible controller|3D controller|Display controller' | head -n1 || true)"
            if [[ -n "${lspci_line}" ]]; then
                AUDIT_GPU_STATUS="detected"
                if grep -qi "nvidia" <<<"${lspci_line}"; then
                    AUDIT_GPU_VENDOR="NVIDIA"
                elif grep -Eqi 'amd|ati|radeon' <<<"${lspci_line}"; then
                    AUDIT_GPU_VENDOR="AMD"
                elif grep -qi "intel" <<<"${lspci_line}"; then
                    AUDIT_GPU_VENDOR="Intel"
                else
                    AUDIT_GPU_VENDOR="unknown"
                fi
                AUDIT_GPU_MODEL="$(trim_whitespace "${lspci_line#*:}")"
            fi
        fi
    fi

    AUDIT_GPU_PROFILE_STATUS="$(detect_gpu_profile_status)"
    AUDIT_GPU_RUNTIME_STATUS="$(detect_gpu_runtime_status)"
}

detect_install_mode_recommendation() {
    local nvidia_gpu_capable_host="no"

    if [[ "${AUDIT_NVIDIA_SMI_STATUS}" == "present" ]]; then
        nvidia_gpu_capable_host="yes"
    elif [[ "${AUDIT_GPU_VENDOR}" == "NVIDIA" && "${AUDIT_GPU_MODEL}" != "unknown" ]]; then
        nvidia_gpu_capable_host="yes"
    fi

    if [[ "${nvidia_gpu_capable_host}" == "yes" ]]; then
        DETECTED_DEPLOYMENT_TARGET="GPU-capable host"
    else
        DETECTED_DEPLOYMENT_TARGET="CPU-only host"
    fi

    if [[ "${nvidia_gpu_capable_host}" == "yes" ]] && [[ "${AUDIT_GPU_PROFILE_STATUS}" == "available" ]] && {
        [[ "${AUDIT_DOCKER_STATUS}" != "installed" ]] || [[ "$(yes_no_unknown "${AUDIT_GPU_RUNTIME_STATUS}")" == "yes" ]];
    }; then
        RECOMMENDED_INSTALL_MODE="gpu"
    else
        RECOMMENDED_INSTALL_MODE="cpu"
    fi
}

normalize_install_mode() {
    local mode="${1,,}"
    case "${mode}" in
        auto|cpu|gpu)
            printf "%s" "${mode}"
            ;;
        *)
            return 1
            ;;
    esac
}

select_install_mode() {
    local requested_mode="${INSTALL_MODE:-auto}"
    local normalized_mode=""
    local prompt_options="cpu"
    local input=""

    normalized_mode="$(normalize_install_mode "${requested_mode}")" || die "Unsupported INSTALL_MODE='${requested_mode}'. Supported values: ${SUPPORTED_INSTALL_MODES}"

    if [[ "${normalized_mode}" == "auto" ]]; then
        normalized_mode="${RECOMMENDED_INSTALL_MODE}"
    fi

    if [[ "${DETECTED_DEPLOYMENT_TARGET}" == "GPU-capable host" ]]; then
        prompt_options="gpu/cpu"
    fi

    print_info "Detected deployment target: ${DETECTED_DEPLOYMENT_TARGET}"
    print_info "Recommended installation mode: ${RECOMMENDED_INSTALL_MODE^^}"

    if ! is_interactive_shell; then
        SELECTED_INSTALL_MODE="${normalized_mode}"
        print_info "Selected installation mode: ${SELECTED_INSTALL_MODE^^} (non-interactive)"
        return
    fi

    if [[ "${INSTALL_MODE:-auto}" != "auto" ]]; then
        SELECTED_INSTALL_MODE="${normalized_mode}"
        print_info "Selected installation mode: ${SELECTED_INSTALL_MODE^^} (requested)"
        return
    fi

    read -r -p "Proceed with installation mode / Продолжить с режимом установки [${prompt_options}] (example: ${normalized_mode}): " input
    input="${input:-${normalized_mode}}"
    input="$(normalize_install_mode "${input}")" || die "Unsupported installation mode selection"
    SELECTED_INSTALL_MODE="${input}"
    print_info "Selected installation mode: ${SELECTED_INSTALL_MODE^^}"
}

gpu_mode_prerequisites_ready() {
    [[ "${DETECTED_DEPLOYMENT_TARGET}" == "GPU-capable host" ]] || return 1
    [[ "${AUDIT_GPU_PROFILE_STATUS}" == "available" ]] || return 1
    [[ "$(yes_no_unknown "${AUDIT_GPU_RUNTIME_STATUS}")" == "yes" ]] || return 1
}

validate_install_mode() {
    refresh_runtime_dependent_audit

    if [[ "${SELECTED_INSTALL_MODE}" != "gpu" ]]; then
        print_info "Proceeding with CPU deployment mode"
        return
    fi

    if gpu_mode_prerequisites_ready; then
        print_success "GPU prerequisites look ready"
        return
    fi

    print_warning "GPU installation mode was selected, but GPU prerequisites are incomplete"
    print_warning "Detected target: ${DETECTED_DEPLOYMENT_TARGET}"
    print_warning "Docker GPU runtime: ${AUDIT_GPU_RUNTIME_STATUS}"
    print_warning "GPU compose profile: ${AUDIT_GPU_PROFILE_STATUS}"

    if is_interactive_shell; then
        local fallback_answer=""
        read -r -p "Continue with CPU mode instead / Переключиться на CPU mode [Y/n] (example: y): " fallback_answer
        fallback_answer="${fallback_answer,,}"
        if [[ -z "${fallback_answer}" || "${fallback_answer}" == "y" || "${fallback_answer}" == "yes" ]]; then
            SELECTED_INSTALL_MODE="cpu"
            print_info "Falling back to CPU deployment mode"
            return
        fi
    fi

    if [[ "${INSTALL_MODE:-auto}" == "auto" ]]; then
        SELECTED_INSTALL_MODE="cpu"
        print_warning "Falling back to CPU deployment mode because GPU prerequisites are not ready"
        return
    fi

    die "GPU installation mode requested, but GPU prerequisites are incomplete"
}

collect_system_audit() {
    AUDIT_HOSTNAME="$(hostname 2>/dev/null || printf "unknown")"
    AUDIT_IP_ADDRESSES="$(detect_ip_addresses)"
    AUDIT_CPU_MODEL="$(detect_cpu_model)"
    AUDIT_CPU_CORES="$(detect_cpu_cores)"
    AUDIT_TOTAL_RAM_GB_RAW="$(detect_total_ram_gb_raw)"
    AUDIT_TOTAL_RAM_GB="${AUDIT_TOTAL_RAM_GB_RAW} GB"
    AUDIT_DISK_FREE_GB_RAW="$(detect_disk_free_gb_raw)"
    AUDIT_DISK_FREE_GB="${AUDIT_DISK_FREE_GB_RAW} GB"
    AUDIT_DOCKER_STATUS="$(status_from_command docker)"
    if command_exists docker && docker compose version >/dev/null 2>&1; then
        AUDIT_COMPOSE_STATUS="installed"
    else
        AUDIT_COMPOSE_STATUS="not installed"
    fi
    detect_outbound_connectivity
    detect_gpu_hardware
    detect_install_mode_recommendation
}

refresh_runtime_dependent_audit() {
    AUDIT_DOCKER_STATUS="$(status_from_command docker)"
    if command_exists docker && docker compose version >/dev/null 2>&1; then
        AUDIT_COMPOSE_STATUS="installed"
    else
        AUDIT_COMPOSE_STATUS="not installed"
    fi
    AUDIT_GPU_RUNTIME_STATUS="$(detect_gpu_runtime_status)"
    AUDIT_GPU_PROFILE_STATUS="$(detect_gpu_profile_status)"
    detect_install_mode_recommendation
}

print_system_audit_summary() {
    print_header "Corporate AI Assistant - System Audit"
    printf "OS: %s %s\n" "${OS_ID:-unknown}" "${OS_VERSION_ID:-unknown}"
    printf "Hostname: %s\n" "${AUDIT_HOSTNAME}"
    printf "IP addresses: %s\n" "${AUDIT_IP_ADDRESSES}"
    printf "CPU: %s\n" "${AUDIT_CPU_MODEL}"
    printf "Cores: %s\n" "${AUDIT_CPU_CORES}"
    printf "RAM: %s\n" "${AUDIT_TOTAL_RAM_GB}"
    printf "Disk free: %s\n" "${AUDIT_DISK_FREE_GB}"
    printf "Docker: %s\n" "${AUDIT_DOCKER_STATUS}"
    printf "Compose: %s\n" "${AUDIT_COMPOSE_STATUS}"
    printf "GPU: %s\n" "${AUDIT_GPU_STATUS}"
    printf "GPU vendor: %s\n" "${AUDIT_GPU_VENDOR}"
    printf "GPU model: %s\n" "${AUDIT_GPU_MODEL}"
    printf "GPU VRAM: %s\n" "${AUDIT_GPU_VRAM}"
    printf "nvidia-smi: %s\n" "${AUDIT_NVIDIA_SMI_STATUS}"
    printf "lspci: %s\n" "${AUDIT_LSPCI_STATUS}"
    printf "Docker GPU runtime: %s\n" "${AUDIT_GPU_RUNTIME_STATUS}"
    printf "GPU compose profile: %s\n" "${AUDIT_GPU_PROFILE_STATUS}"
    printf "Outbound download.docker.com: %s\n" "${AUDIT_OUTBOUND_DOCKER_DOWNLOAD}"
    printf "Outbound registry-1.docker.io: %s\n" "${AUDIT_OUTBOUND_DOCKER_REGISTRY}"
    printf "Outbound ollama.com: %s\n" "${AUDIT_OUTBOUND_OLLAMA}"
    printf "Outbound pypi.org: %s\n" "${AUDIT_OUTBOUND_PYPI}"
    printf "Detected deployment target: %s\n" "${DETECTED_DEPLOYMENT_TARGET}"
    printf "Recommended installation mode: %s\n" "${RECOMMENDED_INSTALL_MODE^^}"
}

print_preflight_warnings() {
    if [[ "${AUDIT_CPU_CORES}" =~ ^[0-9]+$ ]] && (( AUDIT_CPU_CORES < MIN_RECOMMENDED_CPU_CORES )); then
        print_warning "Detected CPU cores (${AUDIT_CPU_CORES}) are below the recommended minimum (${MIN_RECOMMENDED_CPU_CORES})"
    fi

    if (( AUDIT_TOTAL_RAM_GB_RAW > 0 && AUDIT_TOTAL_RAM_GB_RAW < MIN_RECOMMENDED_RAM_GB )); then
        print_warning "Detected RAM (${AUDIT_TOTAL_RAM_GB}) is below the recommended minimum (${MIN_RECOMMENDED_RAM_GB} GB)"
    fi

    if (( AUDIT_DISK_FREE_GB_RAW > 0 && AUDIT_DISK_FREE_GB_RAW < MIN_RECOMMENDED_DISK_GB )); then
        print_warning "Free disk space (${AUDIT_DISK_FREE_GB}) is below the recommended minimum (${MIN_RECOMMENDED_DISK_GB} GB)"
    fi

    if [[ "${DETECTED_DEPLOYMENT_TARGET}" == "CPU-only host" ]]; then
        print_info "No supported NVIDIA GPU runtime was detected; CPU deployment remains available"
    elif [[ "$(yes_no_unknown "${AUDIT_GPU_RUNTIME_STATUS}")" != "yes" ]]; then
        print_warning "NVIDIA hardware may be present, but Docker GPU runtime is not ready yet"
    fi

    local unknown_checks=()
    [[ "${AUDIT_OUTBOUND_DOCKER_DOWNLOAD}" == "unknown" ]] && unknown_checks+=("download.docker.com")
    [[ "${AUDIT_OUTBOUND_DOCKER_REGISTRY}" == "unknown" ]] && unknown_checks+=("registry-1.docker.io")
    [[ "${AUDIT_OUTBOUND_OLLAMA}" == "unknown" ]] && unknown_checks+=("ollama.com")
    [[ "${AUDIT_OUTBOUND_PYPI}" == "unknown" ]] && unknown_checks+=("pypi.org")

    if [[ "${#unknown_checks[@]}" -gt 0 ]]; then
        print_warning "Some outbound checks could not be verified yet: ${unknown_checks[*]}"
    fi
}

as_root() {
    if [[ "${EUID}" -eq 0 ]]; then
        "$@"
    else
        sudo "$@"
    fi
}

docker_cmd() {
    if docker info >/dev/null 2>&1; then
        docker "$@"
    else
        as_root docker "$@"
    fi
}

docker_compose() {
    docker_cmd compose "$@"
}

docker_compose_for_install_mode() {
    if [[ "${SELECTED_INSTALL_MODE:-cpu}" == "gpu" ]]; then
        docker_compose --profile gpu "$@"
    else
        docker_compose "$@"
    fi
}

require_sudo_access() {
    if [[ "${EUID}" -ne 0 ]]; then
        command_exists sudo || die "sudo is required when running install.sh as a non-root user"
        sudo -v
    fi
}

load_os_release() {
    [[ -f /etc/os-release ]] || die "/etc/os-release not found"
    # shellcheck disable=SC1091
    source /etc/os-release
    OS_ID="${ID:-}"
    OS_VERSION_ID="${VERSION_ID:-}"
    OS_CODENAME="${VERSION_CODENAME:-}"
}

version_ge() {
    dpkg --compare-versions "$1" ge "$2"
}

precheck_os() {
    print_header "Precheck"
    [[ "${OSTYPE:-}" == linux* ]] || die "install.sh supports Linux only"

    load_os_release
    case "${OS_ID}" in
        ubuntu)
            version_ge "${OS_VERSION_ID}" "20.04" || die "Ubuntu 20.04 or newer is required"
            ;;
        debian)
            version_ge "${OS_VERSION_ID}" "11" || die "Debian 11 or newer is required"
            ;;
        *)
            die "Unsupported OS '${OS_ID}'. Supported: Ubuntu 20.04+, Debian 11+"
            ;;
    esac

    [[ -f "${ROOT_DIR}/docker-compose.yml" ]] || die "docker-compose.yml not found in ${ROOT_DIR}"
    [[ -f "${ROOT_DIR}/Dockerfile" ]] || die "Dockerfile not found in ${ROOT_DIR}"
    [[ -d "${ROOT_DIR}/deploy" ]] || die "deploy directory not found in ${ROOT_DIR}"

    require_sudo_access
    print_success "OS and privileges look good (${OS_ID} ${OS_VERSION_ID})"
}

network_check() {
    print_info "Checking outbound network"
    local failed_checks=()

    [[ "${AUDIT_OUTBOUND_DOCKER_DOWNLOAD}" == "failed" ]] && failed_checks+=("download.docker.com")
    [[ "${AUDIT_OUTBOUND_DOCKER_REGISTRY}" == "failed" ]] && failed_checks+=("registry-1.docker.io")
    [[ "${AUDIT_OUTBOUND_OLLAMA}" == "failed" ]] && failed_checks+=("ollama.com")
    [[ "${AUDIT_OUTBOUND_PYPI}" == "failed" ]] && failed_checks+=("pypi.org")

    if [[ "${#failed_checks[@]}" -gt 0 ]]; then
        die "Critical outbound connectivity check failed for: ${failed_checks[*]}"
    fi

    print_success "Outbound network looks healthy"
}

apt_update_if_needed() {
    if [[ "${APT_UPDATED}" -eq 0 ]]; then
        as_root apt-get update -y
        APT_UPDATED=1
    fi
}

apt_install_if_missing() {
    local missing=()
    local pkg
    for pkg in "$@"; do
        if ! dpkg -s "${pkg}" >/dev/null 2>&1; then
            missing+=("${pkg}")
            append_unique_installed_package "${pkg}"
        fi
    done

    if [[ "${#missing[@]}" -eq 0 ]]; then
        return
    fi

    apt_update_if_needed
    DEBIAN_FRONTEND=noninteractive as_root apt-get install -y "${missing[@]}"
}

install_base_packages() {
    print_header "System Packages"
    apt_install_if_missing \
        ca-certificates \
        curl \
        git \
        gnupg \
        jq \
        lsb-release \
        openssl \
        python3 \
        python3-venv \
        python3-pip \
        krb5-user \
        libsasl2-modules-gssapi-mit \
        ldap-utils

    print_success "Base packages are present"
}

configure_docker_repository() {
    local keyring="/etc/apt/keyrings/docker.asc"
    local repo_file="/etc/apt/sources.list.d/docker.list"
    local backup_file="${HOST_DOCKER_REPO_BACKUP}"
    local architecture
    local existing_owned_repo="0"

    existing_owned_repo="$(state_file_value "${HOST_STATE_FILE}" "OWNED_DOCKER_REPO_FILE" || true)"
    if bool_is_true "${existing_owned_repo}"; then
        DOCKER_REPO_FILE_BACKUP="$(state_file_value "${HOST_STATE_FILE}" "OWNED_DOCKER_REPO_BACKUP" || true)"
    fi
    architecture="$(dpkg --print-architecture)"
    as_root install -m 0755 -d /etc/apt/keyrings
    if [[ ! -f "${keyring}" ]]; then
        curl -fsSL "https://download.docker.com/linux/${OS_ID}/gpg" | as_root tee "${keyring}" >/dev/null
        as_root chmod a+r "${keyring}"
        INSTALLER_ADDED_DOCKER_KEYRING="1"
    fi

    if [[ -z "${OS_CODENAME}" ]]; then
        die "VERSION_CODENAME is missing in /etc/os-release"
    fi

    if [[ ! -f "${repo_file}" ]] || ! grep -q "download.docker.com/linux/${OS_ID}" "${repo_file}"; then
        if [[ -f "${repo_file}" && -z "${DOCKER_REPO_FILE_BACKUP}" ]] && ! bool_is_true "${existing_owned_repo}"; then
            as_root install -m 0755 -d "${HOST_BACKUP_DIR}"
            as_root cp "${repo_file}" "${backup_file}"
            as_root chmod 0644 "${backup_file}"
            DOCKER_REPO_FILE_BACKUP="${backup_file}"
        fi
        printf "deb [arch=%s signed-by=%s] https://download.docker.com/linux/%s %s stable\n" \
            "${architecture}" "${keyring}" "${OS_ID}" "${OS_CODENAME}" | as_root tee "${repo_file}" >/dev/null
        INSTALLER_MANAGED_DOCKER_REPO_FILE="1"
    fi
}

ensure_docker_installed() {
    print_header "Docker"

    if command_exists docker && docker compose version >/dev/null 2>&1; then
        print_success "Docker and docker compose plugin are already installed"
    else
        print_info "Installing Docker Engine and docker compose plugin"
        apt_install_if_missing ca-certificates curl gnupg
        configure_docker_repository
        APT_UPDATED=0
        apt_install_if_missing docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    fi

    if array_contains "docker-ce" "${APT_PACKAGES_INSTALLED_BY_INSTALLER[@]}" || \
       array_contains "docker-ce-cli" "${APT_PACKAGES_INSTALLED_BY_INSTALLER[@]}" || \
       array_contains "containerd.io" "${APT_PACKAGES_INSTALLED_BY_INSTALLER[@]}"; then
        INSTALLER_INSTALLED_DOCKER_ENGINE="1"
    fi
    if array_contains "docker-compose-plugin" "${APT_PACKAGES_INSTALLED_BY_INSTALLER[@]}"; then
        INSTALLER_INSTALLED_DOCKER_COMPOSE_PLUGIN="1"
    fi

    as_root systemctl enable --now docker
    docker_cmd version >/dev/null

    if [[ "${EUID}" -ne 0 ]] && ! id -nG "${USER}" | grep -qw docker; then
        as_root usermod -aG docker "${USER}" || true
        INSTALLER_ADDED_USER_TO_DOCKER_GROUP="1"
        print_warning "User '${USER}' was added to the docker group. A new login session is required for passwordless docker use."
    fi

    print_success "Docker is ready"
}

ensure_ollama_cli() {
    print_header "Ollama CLI"

    if command_exists ollama; then
        print_success "Ollama CLI is already installed"
    else
        local installer
        installer="$(mktemp)"
        curl -fsSL https://ollama.com/install.sh -o "${installer}"
        as_root sh "${installer}"
        rm -f "${installer}"
        INSTALLER_INSTALLED_OLLAMA_CLI="1"
        print_success "Ollama CLI installed"
    fi

    as_root systemctl disable --now ollama.service >/dev/null 2>&1 || true
    POSTINSTALL_OLLAMA_BIN_PATH="$(command -v ollama || true)"
    if systemd_unit_exists ollama.service; then
        POSTINSTALL_OLLAMA_SERVICE_FRAGMENT="$(systemctl show -p FragmentPath --value ollama.service 2>/dev/null || true)"
    fi
    print_info "Host ollama service is disabled to avoid conflicts with the containerized runtime"
}

confirm_system_changes() {
    local answer=""

    if ! is_interactive_shell; then
        print_info "Proceeding non-interactively with ${SELECTED_INSTALL_MODE^^} installation mode"
        return
    fi

    print_info "The installer will now make system changes: package installation, Docker/Ollama setup, config generation, and Docker Compose deployment / Установщик сейчас внесёт системные изменения: пакеты, Docker/Ollama, генерация конфигурации и запуск Docker Compose"
    read -r -p "Continue / Продолжить [Y/n] (example: y): " answer
    is_positive_answer "${answer}" || die "Installation cancelled by user"
}

get_env_value() {
    local file="$1"
    local key="$2"
    [[ -f "${file}" ]] || return 1
    grep -E "^${key}=" "${file}" | tail -n 1 | cut -d'=' -f2- || true
}

prompt_with_default() {
    local label="$1"
    local default_value="$2"
    local input

    if [[ -n "${default_value}" ]]; then
        read -r -p "${label} [${default_value}]: " input
        printf "%s" "${input:-${default_value}}"
    else
        read -r -p "${label}: " input
        printf "%s" "${input}"
    fi
}

normalize_boolean_input() {
    local value="${1,,}"
    if [[ "${value}" == "true" || "${value}" == "1" || "${value}" == "yes" || "${value}" == "y" ]]; then
        printf "true"
    else
        printf "false"
    fi
}

prompt_boolean_with_default() {
    local label="$1"
    local default_value
    local input
    default_value="$(normalize_boolean_input "${2:-false}")"

    if ! is_interactive_shell; then
        printf "%s" "${default_value}"
        return
    fi

    if [[ "${default_value}" == "true" ]]; then
        read -r -p "${label} [Y/n]: " input
    else
        read -r -p "${label} [y/N]: " input
    fi
    if [[ -z "${input}" ]]; then
        printf "%s" "${default_value}"
        return
    fi
    if is_positive_answer "${input}"; then
        printf "true"
    else
        printf "false"
    fi
}

prompt_secret_or_generate() {
    local label="$1"
    local existing_value="$2"
    local generator="$3"
    local input

    read -r -s -p "${label} (leave blank to ${existing_value:+keep existing}${existing_value:+" or "}generate): " input
    printf "\n" >&2
    if [[ -n "${input}" ]]; then
        printf "%s" "${input}"
        return
    fi
    if [[ -n "${existing_value}" ]]; then
        printf "%s" "${existing_value}"
        return
    fi
    "${generator}"
}

validate_env_value() {
    local key="$1"
    local value="$2"
    if [[ "${value}" == *$'\n'* || "${value}" == *$'\r'* ]]; then
        die "Refusing to write multiline value for ${key} into .env"
    fi
}

append_env_line() {
    local file="$1"
    local key="$2"
    local value="$3"
    validate_env_value "${key}" "${value}"
    printf '%s=%s\n' "${key}" "${value}" >>"${file}"
}

generate_hex_secret() {
    openssl rand -hex 32
}

generate_base64_secret() {
    openssl rand -base64 48 | tr -d '\n'
}

derive_base_dn() {
    local domain="$1"
    local dn=""
    local part
    IFS='.' read -r -a parts <<<"${domain}"
    for part in "${parts[@]}"; do
        [[ -n "${dn}" ]] && dn+=","
        dn+="dc=${part}"
    done
    printf "%s" "${dn}"
}

derive_netbios() {
    local domain="$1"
    local first="${domain%%.*}"
    printf "%s" "${first^^}"
}

normalize_host_input() {
    local value="$1"
    value="${value#ldap://}"
    value="${value#ldaps://}"
    value="${value%%/*}"
    value="${value%%:*}"
    printf "%s" "${value}"
}

normalize_group_mapping_csv() {
    local value="$1"
    local -a normalized=()
    local -A seen=()
    local raw candidate key
    IFS=',' read -r -a raw_groups <<<"${value}"
    for raw in "${raw_groups[@]}"; do
        candidate="$(trim_whitespace "${raw}")"
        [[ -n "${candidate}" ]] || continue
        key="${candidate,,}"
        [[ -n "${seen[${key}]:-}" ]] && continue
        seen["${key}"]=1
        normalized+=("${candidate}")
    done
    local result=""
    for candidate in "${normalized[@]}"; do
        [[ -n "${result}" ]] && result+=","
        result+="${candidate}"
    done
    printf "%s" "${result}"
}

is_ipv4() {
    [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]
}

model_catalog_records() {
    cat <<'EOF'
phi3:mini|Phi-3 Mini|Light general-purpose assistant for pilot and CPU-first deployments|ok|8 GB|16 GB|optional|0 GB|Best default for conservative CPU-only rollouts.|model_policies/general + .env.example + docs
gemma2:2b|Gemma 2 2B|Light general chat alternative with low resource expectations|ok|8 GB|16 GB|optional|0 GB|Good fallback when you want a small general model beside Phi-3.|model_policies/general + bootstrap_ollama_models.sh
mistral|Mistral 7B|Balanced general-purpose model with better quality but more weight|limited|12 GB|16 GB|optional|6 GB|Common general model in project docs and bootstrap fallback path.|model_policies/general + bootstrap_ollama_models.sh + docs
deepseek-coder:7b|DeepSeek Coder 7B|Code-oriented assistant for implementation and debugging tasks|limited|16 GB|24 GB|recommended|8 GB|Practical coding choice when CPU is acceptable but GPU is preferred.|model_policies/coding
qwen2.5-coder:7b|Qwen 2.5 Coder 7B|Coding-focused model with stronger multi-language code help|limited|16 GB|24 GB|recommended|8 GB|Useful coding-focused default when a GPU-backed pilot is available.|model_policies/coding
llama3.1:8b|Llama 3.1 8B|Stronger general/admin analysis model than the lightweight defaults|limited|16 GB|24 GB|recommended|8 GB|Good step-up model for broader reasoning on better-equipped hosts.|model_policies/admin
codellama:13b|Code Llama 13B|Heavier coding model for larger coding workloads|not recommended|24 GB|32 GB|recommended|12 GB|Large for CPU-only hosts; use mainly on better GPU-backed installs.|model_policies/coding
qwen2.5:14b|Qwen 2.5 14B|Heavy admin-tier model for stronger reasoning and long-form analysis|not recommended|24 GB|32 GB|recommended|12 GB|Marked experimental/heavier in repo policy; best on GPU-capable hosts.|model_policies/admin
EOF
}

print_model_catalog() {
    local index=1
    local model_id display_name purpose cpu_guidance min_ram rec_ram gpu_guidance min_vram comment source_hint

    print_header "Model Selection"
    print_info "Deployment profile: ${SELECTED_INSTALL_MODE^^}"
    print_info "Installer model catalog: curated project-oriented options from bootstrap script, docs, policy files, and current defaults"

    while IFS='|' read -r model_id display_name purpose cpu_guidance min_ram rec_ram gpu_guidance min_vram comment source_hint; do
        [[ -n "${model_id}" ]] || continue
        printf "%2d. %s (%s)\n" "${index}" "${model_id}" "${display_name}"
        printf "    Purpose: %s\n" "${purpose}"
        printf "    CPU: %s | Minimum RAM: %s | Recommended RAM: %s\n" "${cpu_guidance}" "${min_ram}" "${rec_ram}"
        printf "    GPU: %s | Minimum VRAM: %s\n" "${gpu_guidance}" "${min_vram}"
        printf "    Comment: %s\n" "${comment}"
        printf "    Source: %s\n" "${source_hint}"
        index=$((index + 1))
    done < <(model_catalog_records)

    printf "%2d. custom (enter any Ollama model name manually)\n" "${index}"
    printf "    Purpose: use a model not listed in the curated project catalog\n"
    printf "    CPU: depends on model | Minimum RAM: depends on model | Recommended RAM: depends on model\n"
    printf "    GPU: depends on model | Minimum VRAM: depends on model\n"
    printf "    Comment: choose this if your target model is supported by your runtime but not listed above\n"
}

resolve_model_choice() {
    local choice="$1"
    local default_model="$2"
    local index=1
    local custom_index=1
    local model_id display_name purpose cpu_guidance min_ram rec_ram gpu_guidance min_vram comment source_hint

    while IFS='|' read -r model_id display_name purpose cpu_guidance min_ram rec_ram gpu_guidance min_vram comment source_hint; do
        [[ -n "${model_id}" ]] || continue
        custom_index=$((custom_index + 1))
        if [[ "${model_id}" == "${default_model}" ]]; then
            custom_index="${index}"
        fi
        if [[ "${choice}" == "${index}" ]]; then
            printf '%s' "${model_id}"
            return 0
        fi
        index=$((index + 1))
    done < <(model_catalog_records)

    if [[ "${choice}" == "${custom_index}" || "${choice}" == "custom" ]]; then
        printf 'custom'
        return 0
    fi
    return 1
}

prompt_default_model_selection() {
    local existing_default_model="$1"
    local default_choice_model="${existing_default_model:-${DEFAULT_MODEL}}"
    local model_choice=""
    local resolved_choice=""
    local custom_model=""

    if ! is_interactive_shell; then
        DEFAULT_MODEL="${default_choice_model}"
        DOWNLOAD_DEFAULT_MODEL_NOW="true"
        print_info "Selected default model: ${DEFAULT_MODEL} (non-interactive)"
        print_info "Model pre-pull: enabled by default in non-interactive mode"
        return
    fi

    print_model_catalog
    read -r -p "Default model / Модель по умолчанию: choose number or 'custom' [default: ${default_choice_model}] (example: phi3:mini): " model_choice
    model_choice="$(trim_whitespace "${model_choice}")"

    if [[ -z "${model_choice}" ]]; then
        DEFAULT_MODEL="${default_choice_model}"
    elif [[ "${model_choice}" == *:* || "${model_choice}" == *"/"* ]]; then
        DEFAULT_MODEL="${model_choice}"
    else
        resolved_choice="$(resolve_model_choice "${model_choice}" "${default_choice_model}" || true)"
        if [[ -z "${resolved_choice}" ]]; then
            die "Unsupported model selection"
        fi
        if [[ "${resolved_choice}" == "custom" ]]; then
            read -r -p "Custom Ollama model name / Пользовательская Ollama-модель (example: qwen2.5:7b or llama3.1:8b): " custom_model
            custom_model="$(trim_whitespace "${custom_model}")"
            [[ -n "${custom_model}" ]] || die "Custom model name cannot be empty"
            DEFAULT_MODEL="${custom_model}"
        else
            DEFAULT_MODEL="${resolved_choice}"
        fi
    fi

    DOWNLOAD_DEFAULT_MODEL_NOW="$(prompt_boolean_with_default "Download selected model now so chat is ready immediately / Скачать выбранную модель сейчас, чтобы чат был готов сразу (example: y)" "true")"
    print_info "Selected default model: ${DEFAULT_MODEL}"
    print_info "Model pre-pull requested: ${DOWNLOAD_DEFAULT_MODEL_NOW}"
}

collect_configuration() {
    print_header "Interactive Configuration"

    local existing_env="${ROOT_DIR}/.env"
    local example_env="${ROOT_DIR}/.env.example"
    local default_domain default_ldap_host default_kdc_host default_base_dn default_admin_user default_ip_override
    local default_coding_groups default_admin_groups default_sso_enabled default_sso_principal default_sso_keytab
    local existing_redis_password existing_secret_key existing_default_model

    default_domain="$(get_env_value "${existing_env}" "LDAP_DOMAIN" || get_env_value "${example_env}" "LDAP_DOMAIN" || true)"
    default_domain="${default_domain:-example.local}"

    default_ldap_host="$(get_env_value "${existing_env}" "LDAP_SERVER" || get_env_value "${example_env}" "LDAP_SERVER" || true)"
    default_ldap_host="$(normalize_host_input "${default_ldap_host:-srv-ad.${default_domain}}")"

    default_kdc_host="$(get_env_value "${existing_env}" "KERBEROS_KDC" || get_env_value "${example_env}" "KERBEROS_KDC" || true)"
    default_kdc_host="$(normalize_host_input "${default_kdc_host:-${default_ldap_host}}")"

    default_base_dn="$(get_env_value "${existing_env}" "LDAP_BASE_DN" || get_env_value "${example_env}" "LDAP_BASE_DN" || true)"
    default_base_dn="${default_base_dn:-$(derive_base_dn "${default_domain}")}"

    default_admin_user="$(get_env_value "${existing_env}" "INSTALL_TEST_USER" || true)"
    default_ip_override="$(get_env_value "${existing_env}" "AD_SERVER_IP_OVERRIDE" || true)"
    default_coding_groups="$(get_env_value "${existing_env}" "MODEL_ACCESS_CODING_GROUPS" || get_env_value "${example_env}" "MODEL_ACCESS_CODING_GROUPS" || true)"
    default_admin_groups="$(get_env_value "${existing_env}" "MODEL_ACCESS_ADMIN_GROUPS" || get_env_value "${example_env}" "MODEL_ACCESS_ADMIN_GROUPS" || true)"
    default_sso_enabled="$(get_env_value "${existing_env}" "SSO_ENABLED" || get_env_value "${example_env}" "SSO_ENABLED" || true)"
    default_sso_principal="$(get_env_value "${existing_env}" "SSO_SERVICE_PRINCIPAL" || get_env_value "${example_env}" "SSO_SERVICE_PRINCIPAL" || true)"
    default_sso_keytab="$(get_env_value "${existing_env}" "SSO_KEYTAB_PATH" || get_env_value "${example_env}" "SSO_KEYTAB_PATH" || true)"
    existing_default_model="$(get_env_value "${existing_env}" "DEFAULT_MODEL" || get_env_value "${example_env}" "DEFAULT_MODEL" || true)"
    existing_redis_password="$(get_env_value "${existing_env}" "REDIS_PASSWORD" || true)"
    existing_secret_key="$(get_env_value "${existing_env}" "SECRET_KEY" || true)"

    DOMAIN="$(prompt_with_default "AD domain / Домен AD (example: corp.local)" "${default_domain}")"
    DOMAIN="${DOMAIN,,}"
    [[ -n "${DOMAIN}" ]] || die "AD domain cannot be empty"

    LDAP_SERVER_HOST="$(prompt_with_default "LDAP server hostname or FQDN / LDAP-сервер: имя хоста или FQDN (example: srv-ad or srv-ad.corp.local)" "${default_ldap_host}")"
    LDAP_SERVER_HOST="$(normalize_host_input "${LDAP_SERVER_HOST}")"
    [[ -n "${LDAP_SERVER_HOST}" ]] || die "LDAP server cannot be empty"
    if is_ipv4 "${LDAP_SERVER_HOST}"; then
        die "LDAP server must be a hostname or FQDN, not an IP address"
    fi

    KERBEROS_KDC="$(prompt_with_default "Kerberos KDC hostname or FQDN / Kerberos KDC: имя хоста или FQDN (example: srv-ad.corp.local)" "${default_kdc_host}")"
    KERBEROS_KDC="$(normalize_host_input "${KERBEROS_KDC}")"
    [[ -n "${KERBEROS_KDC}" ]] || die "Kerberos KDC cannot be empty"
    if is_ipv4 "${KERBEROS_KDC}"; then
        die "Kerberos KDC must be a hostname or FQDN, not an IP address"
    fi

    BASE_DN="$(prompt_with_default "LDAP Base DN / Базовый DN LDAP (example: DC=corp,DC=local)" "${default_base_dn}")"
    [[ -n "${BASE_DN}" ]] || die "Base DN cannot be empty"

    TEST_ADMIN_USER="$(prompt_with_default "AD test user for smoke test / Тестовый пользователь AD для smoke-проверки (example: aitest)" "${default_admin_user}")"
    if [[ -n "${TEST_ADMIN_USER}" ]]; then
        read -r -s -p "Password for '${TEST_ADMIN_USER}' / Пароль для '${TEST_ADMIN_USER}' (example: leave blank to skip): " TEST_ADMIN_PASSWORD
        printf "\n"
    else
        TEST_ADMIN_PASSWORD=""
    fi

    AD_SERVER_IP_OVERRIDE="$(prompt_with_default "LDAP/KDC IP override for container hosts (optional) / IP override для контейнеров LDAP/KDC (необязательно) (example: 10.10.10.10)" "${default_ip_override}")"
    if [[ -n "${AD_SERVER_IP_OVERRIDE}" ]] && ! is_ipv4 "${AD_SERVER_IP_OVERRIDE}"; then
        die "LDAP/KDC IP override must be a valid IPv4 address"
    fi

    MODEL_ACCESS_CODING_GROUPS="$(prompt_with_default "Coding model access AD groups (comma-separated, optional) / AD-группы для coding-моделей (через запятую, необязательно) (example: AI_Coding_Users)" "${default_coding_groups}")"
    MODEL_ACCESS_CODING_GROUPS="$(normalize_group_mapping_csv "${MODEL_ACCESS_CODING_GROUPS}")"

    MODEL_ACCESS_ADMIN_GROUPS="$(prompt_with_default "Admin model access AD groups (comma-separated, optional) / AD-группы для admin-моделей (через запятую, необязательно) (example: AI_Admins)" "${default_admin_groups}")"
    MODEL_ACCESS_ADMIN_GROUPS="$(normalize_group_mapping_csv "${MODEL_ACCESS_ADMIN_GROUPS}")"

    default_sso_enabled="$(normalize_boolean_input "${default_sso_enabled:-false}")"
    SSO_ENABLED="$(prompt_boolean_with_default "Enable trusted reverse-proxy AD SSO / Включить доверенный reverse-proxy AD SSO (example: n)" "${default_sso_enabled}")"
    if [[ "${SSO_ENABLED}" == "true" ]]; then
        default_sso_principal="${default_sso_principal:-HTTP/$(hostname -f 2>/dev/null || hostname)@${KERBEROS_REALM}}"
        default_sso_keytab="${default_sso_keytab:-/etc/corporate-ai-sso/http.keytab}"
        SSO_SERVICE_PRINCIPAL="$(prompt_with_default "HTTP service principal for SSO / HTTP service principal для SSO (example: HTTP/ai.corp.local@CORP.LOCAL)" "${default_sso_principal}")"
        SSO_KEYTAB_PATH="$(prompt_with_default "Container path to SSO keytab / Путь к SSO keytab внутри контейнера (example: /etc/corporate-ai-sso/http.keytab)" "${default_sso_keytab}")"
        [[ -n "${SSO_SERVICE_PRINCIPAL}" ]] || die "SSO service principal cannot be empty when SSO is enabled"
        [[ "${SSO_SERVICE_PRINCIPAL}" == */*@* ]] || die "SSO service principal must look like HTTP/fqdn@REALM"
        [[ "${SSO_KEYTAB_PATH}" == /etc/corporate-ai-sso/* ]] || die "SSO keytab path must stay under /etc/corporate-ai-sso/"
    else
        SSO_SERVICE_PRINCIPAL=""
        SSO_KEYTAB_PATH="/etc/corporate-ai-sso/http.keytab"
    fi

    REDIS_PASSWORD="$(prompt_secret_or_generate "Redis password / Пароль Redis (example: leave blank to generate)" "${existing_redis_password}" generate_hex_secret)"
    [[ -n "${REDIS_PASSWORD}" ]] || die "Redis password cannot be empty"

    SECRET_KEY="$(prompt_secret_or_generate "JWT secret key / JWT secret: ключ подписи (example: leave blank to generate)" "${existing_secret_key}" generate_base64_secret)"
    [[ ${#SECRET_KEY} -ge 32 ]] || die "JWT secret key must be at least 32 characters long"

    NETBIOS_DOMAIN="$(derive_netbios "${DOMAIN}")"
    KERBEROS_REALM="${DOMAIN^^}"
    LDAP_SERVER_URL="ldap://${LDAP_SERVER_HOST}"
    prompt_default_model_selection "${existing_default_model}"

    print_info "Configuration summary"
    printf "  DOMAIN=%s\n" "${DOMAIN}"
    printf "  LDAP_SERVER=%s\n" "${LDAP_SERVER_URL}"
    printf "  BASE_DN=%s\n" "${BASE_DN}"
    printf "  NETBIOS=%s\n" "${NETBIOS_DOMAIN}"
    printf "  KERBEROS_REALM=%s\n" "${KERBEROS_REALM}"
    printf "  KERBEROS_KDC=%s\n" "${KERBEROS_KDC}"
    printf "  DEFAULT_MODEL=%s\n" "${DEFAULT_MODEL}"
    printf "  DOWNLOAD_DEFAULT_MODEL_NOW=%s\n" "${DOWNLOAD_DEFAULT_MODEL_NOW}"
    printf "  MODEL_ACCESS_CODING_GROUPS=%s\n" "${MODEL_ACCESS_CODING_GROUPS:-<none>}"
    printf "  MODEL_ACCESS_ADMIN_GROUPS=%s\n" "${MODEL_ACCESS_ADMIN_GROUPS:-<none>}"
    printf "  SSO_ENABLED=%s\n" "${SSO_ENABLED}"
    if [[ "${SSO_ENABLED}" == "true" ]]; then
        printf "  SSO_SERVICE_PRINCIPAL=%s\n" "${SSO_SERVICE_PRINCIPAL}"
        printf "  SSO_KEYTAB_PATH=%s\n" "${SSO_KEYTAB_PATH}"
    fi
    printf "  AUTH_SMOKE_TEST=%s\n" "$( [[ -n "${TEST_ADMIN_USER}" && -n "${TEST_ADMIN_PASSWORD}" ]] && printf "enabled" || printf "skipped" )"
    if [[ -n "${AD_SERVER_IP_OVERRIDE}" ]]; then
        printf "  CONTAINER_HOST_OVERRIDE=%s -> %s\n" "${LDAP_SERVER_HOST}" "${AD_SERVER_IP_OVERRIDE}"
    fi
}

validate_directory_service_resolution() {
    local unresolved_hosts=()

    if ! getent hosts "${LDAP_SERVER_HOST}" >/dev/null 2>&1; then
        unresolved_hosts+=("${LDAP_SERVER_HOST}")
    fi

    if [[ "${KERBEROS_KDC}" != "${LDAP_SERVER_HOST}" ]] && ! getent hosts "${KERBEROS_KDC}" >/dev/null 2>&1; then
        unresolved_hosts+=("${KERBEROS_KDC}")
    fi

    if [[ "${#unresolved_hosts[@]}" -eq 0 ]]; then
        print_success "Directory service hostnames resolve on the host"
        return
    fi

    if [[ -n "${AD_SERVER_IP_OVERRIDE}" ]]; then
        print_warning "Host DNS could not resolve: ${unresolved_hosts[*]}. Continuing because an AD IP override was provided for containers"
        return
    fi

    die "Cannot resolve required directory service hostnames: ${unresolved_hosts[*]}. Fix DNS or provide an AD IP override"
}

validate_sso_keytab_material() {
    if [[ "${SSO_ENABLED}" != "true" ]]; then
        return
    fi

    local host_keytab_dir="${ROOT_DIR}/deploy/sso"
    local host_keytab_path="${host_keytab_dir}/$(basename "${SSO_KEYTAB_PATH}")"

    mkdir -p "${host_keytab_dir}"
    chmod 700 "${host_keytab_dir}"

    if [[ ! -f "${host_keytab_path}" ]]; then
        die "Trusted proxy SSO is enabled, but the required host keytab is missing: ${host_keytab_path}. Place the HTTP service keytab there before continuing"
    fi

    chmod 600 "${host_keytab_path}" || true
    print_success "Trusted proxy SSO keytab material is present"
}

write_env_file() {
    local env_file="${ROOT_DIR}/.env"
    local backup_file=""
    local temp_file preserved_file regex
    local gpu_enabled_value redis_url_value
    local managed_keys=(
        LDAP_SERVER LDAP_DOMAIN LDAP_BASE_DN LDAP_NETBIOS_DOMAIN
        KERBEROS_REALM KERBEROS_KDC
        SECRET_KEY ALGORITHM ACCESS_TOKEN_EXPIRE_MINUTES REFRESH_TOKEN_EXPIRE_DAYS
        COOKIE_SECURE COOKIE_SAMESITE COOKIE_DOMAIN TRUSTED_AUTH_PROXY_ENABLED
        SSO_ENABLED SSO_LOGIN_PATH SSO_SERVICE_PRINCIPAL SSO_KEYTAB_PATH
        MODEL_POLICY_DIR MODEL_ACCESS_CODING_GROUPS MODEL_ACCESS_ADMIN_GROUPS
        OLLAMA_URL DEFAULT_MODEL AUTO_START_OLLAMA GPU_ENABLED
        REDIS_URL REDIS_PASSWORD RATE_LIMIT_REQUESTS RATE_LIMIT_WINDOW_SECONDS
        LOGIN_RATE_LIMIT_REQUESTS LOGIN_RATE_LIMIT_WINDOW_SECONDS
        APP_HOST APP_PORT APP_RELOAD LOG_LEVEL DEBUG_LOAD_ENABLED
        AD_SERVER_IP_OVERRIDE INSTALL_TEST_USER
    )

    temp_file="$(mktemp)"
    preserved_file="$(mktemp)"
    gpu_enabled_value="$( [[ "${SELECTED_INSTALL_MODE:-cpu}" == "gpu" ]] && printf "true" || printf "false" )"
    redis_url_value="redis://:${REDIS_PASSWORD}@redis:6379/0"

    : >"${temp_file}"
    append_env_line "${temp_file}" "LDAP_SERVER" "${LDAP_SERVER_URL}"
    append_env_line "${temp_file}" "LDAP_DOMAIN" "${DOMAIN}"
    append_env_line "${temp_file}" "LDAP_BASE_DN" "${BASE_DN}"
    append_env_line "${temp_file}" "LDAP_NETBIOS_DOMAIN" "${NETBIOS_DOMAIN}"
    printf '\n' >>"${temp_file}"
    append_env_line "${temp_file}" "KERBEROS_REALM" "${KERBEROS_REALM}"
    append_env_line "${temp_file}" "KERBEROS_KDC" "${KERBEROS_KDC}"
    printf '\n' >>"${temp_file}"
    append_env_line "${temp_file}" "SECRET_KEY" "${SECRET_KEY}"
    append_env_line "${temp_file}" "ALGORITHM" "HS256"
    append_env_line "${temp_file}" "ACCESS_TOKEN_EXPIRE_MINUTES" "480"
    append_env_line "${temp_file}" "REFRESH_TOKEN_EXPIRE_DAYS" "7"
    append_env_line "${temp_file}" "COOKIE_SECURE" "true"
    append_env_line "${temp_file}" "COOKIE_SAMESITE" "lax"
    append_env_line "${temp_file}" "TRUSTED_AUTH_PROXY_ENABLED" "${SSO_ENABLED}"
    append_env_line "${temp_file}" "SSO_ENABLED" "${SSO_ENABLED}"
    append_env_line "${temp_file}" "SSO_LOGIN_PATH" "/auth/sso/login"
    append_env_line "${temp_file}" "SSO_SERVICE_PRINCIPAL" "${SSO_SERVICE_PRINCIPAL}"
    append_env_line "${temp_file}" "SSO_KEYTAB_PATH" "${SSO_KEYTAB_PATH}"
    append_env_line "${temp_file}" "MODEL_POLICY_DIR" "model_policies"
    append_env_line "${temp_file}" "MODEL_ACCESS_CODING_GROUPS" "${MODEL_ACCESS_CODING_GROUPS}"
    append_env_line "${temp_file}" "MODEL_ACCESS_ADMIN_GROUPS" "${MODEL_ACCESS_ADMIN_GROUPS}"
    append_env_line "${temp_file}" "COOKIE_DOMAIN" ""
    printf '\n' >>"${temp_file}"
    append_env_line "${temp_file}" "OLLAMA_URL" "http://ollama:11434/api/chat"
    append_env_line "${temp_file}" "DEFAULT_MODEL" "${DEFAULT_MODEL}"
    append_env_line "${temp_file}" "AUTO_START_OLLAMA" "false"
    append_env_line "${temp_file}" "GPU_ENABLED" "${gpu_enabled_value}"
    printf '\n' >>"${temp_file}"
    append_env_line "${temp_file}" "REDIS_URL" "${redis_url_value}"
    append_env_line "${temp_file}" "REDIS_PASSWORD" "${REDIS_PASSWORD}"
    append_env_line "${temp_file}" "RATE_LIMIT_REQUESTS" "20"
    append_env_line "${temp_file}" "RATE_LIMIT_WINDOW_SECONDS" "60"
    append_env_line "${temp_file}" "LOGIN_RATE_LIMIT_REQUESTS" "5"
    append_env_line "${temp_file}" "LOGIN_RATE_LIMIT_WINDOW_SECONDS" "300"
    printf '\n' >>"${temp_file}"
    append_env_line "${temp_file}" "APP_HOST" "0.0.0.0"
    append_env_line "${temp_file}" "APP_PORT" "8000"
    append_env_line "${temp_file}" "APP_RELOAD" "false"
    append_env_line "${temp_file}" "LOG_LEVEL" "INFO"
    append_env_line "${temp_file}" "DEBUG_LOAD_ENABLED" "false"
    append_env_line "${temp_file}" "AD_SERVER_IP_OVERRIDE" "${AD_SERVER_IP_OVERRIDE}"
    append_env_line "${temp_file}" "INSTALL_TEST_USER" "${TEST_ADMIN_USER}"

    if [[ -f "${env_file}" ]]; then
        backup_file="${env_file}.bak.$(date +%Y%m%d-%H%M%S)"
        cp "${env_file}" "${backup_file}"
        regex="$(printf '%s|' "${managed_keys[@]}")"
        regex="${regex%|}"
        awk -F= -v regex="^(${regex})$" '
            /^[[:space:]]*#/ { print; next }
            /^[A-Za-z_][A-Za-z0-9_]*=/ {
                if ($1 ~ regex) {
                    next
                }
            }
            { print }
        ' "${env_file}" >"${preserved_file}"

        if [[ -s "${preserved_file}" ]]; then
            {
                printf "\n# Preserved custom settings\n"
                cat "${preserved_file}"
            } >>"${temp_file}"
        fi
        print_info "Existing .env backed up to ${backup_file}"
    fi

    mv "${temp_file}" "${env_file}"
    chmod 600 "${env_file}"
    rm -f "${preserved_file}"
    print_success ".env written securely"
}

write_krb5_conf() {
    local krb5_file="${ROOT_DIR}/deploy/krb5.conf"
    install -d -m 0755 "${ROOT_DIR}/deploy"
    cat >"${krb5_file}" <<EOF
[libdefaults]
    default_realm = ${KERBEROS_REALM}
    dns_lookup_kdc = false
    dns_lookup_realm = false
    rdns = false
    ticket_lifetime = 10h
    renew_lifetime = 24h
    forwardable = true

[realms]
    ${KERBEROS_REALM} = {
        kdc = ${KERBEROS_KDC}
        admin_server = ${KERBEROS_KDC}
    }

[domain_realm]
    .${DOMAIN} = ${KERBEROS_REALM}
    ${DOMAIN} = ${KERBEROS_REALM}
EOF
    chmod 644 "${krb5_file}"
    print_success "deploy/krb5.conf generated"
}

write_compose_override_if_needed() {
    local existing_override="${MANAGED_OVERRIDE_FILE}"
    local candidate_hosts=()
    local host_entries=()
    local short_ldap="${LDAP_SERVER_HOST%%.*}"
    local short_kdc="${KERBEROS_KDC%%.*}"
    local temp_file
    local host_name
    local -A seen_hosts=()

    if [[ -z "${AD_SERVER_IP_OVERRIDE}" ]]; then
        if [[ -f "${existing_override}" ]] && grep -qF "${MANAGED_OVERRIDE_MARKER}" "${existing_override}"; then
            rm -f "${existing_override}"
            print_info "Removed installer-managed docker-compose.override.yml because no host override is required"
        fi
        return
    fi

    if [[ -f "${existing_override}" ]] && ! grep -qF "${MANAGED_OVERRIDE_MARKER}" "${existing_override}"; then
        die "Existing docker-compose.override.yml is not installer-managed. Resolve it manually before using AD host overrides."
    fi

    candidate_hosts+=("${short_ldap}" "${LDAP_SERVER_HOST}")
    if [[ "${KERBEROS_KDC}" != "${LDAP_SERVER_HOST}" ]]; then
        candidate_hosts+=("${short_kdc}" "${KERBEROS_KDC}")
    fi
    for host_name in "${candidate_hosts[@]}"; do
        if [[ -n "${host_name}" && -z "${seen_hosts["${host_name}"]+x}" ]]; then
            seen_hosts["${host_name}"]=1
            host_entries+=("${host_name}:${AD_SERVER_IP_OVERRIDE}")
        fi
    done

    temp_file="$(mktemp)"
    {
        printf "%s\n" "${MANAGED_OVERRIDE_MARKER}"
        printf "services:\n"
        for service in app scheduler worker-chat worker-siem worker-batch worker-gpu; do
            printf "  %s:\n" "${service}"
            printf "    extra_hosts:\n"
            local entry host_name host_ip
            for entry in "${host_entries[@]}"; do
                host_name="${entry%%:*}"
                host_ip="${entry#*:}"
                printf "      %s: '%s'\n" "${host_name}" "${host_ip}"
            done
        done
    } >"${temp_file}"

    mv "${temp_file}" "${existing_override}"
    chmod 644 "${existing_override}"
    print_success "docker-compose.override.yml written for AD host override"
}

extract_ollama_host_dir() {
    local match
    match="$(awk '/\/root\/\.ollama/ && $1 == "-" { print $2; exit }' "${ROOT_DIR}/docker-compose.yml")"
    match="${match%%:/root/.ollama*}"
    printf "%s" "${match}"
}

ensure_ollama_host_dir() {
    local ollama_dir
    ollama_dir="$(extract_ollama_host_dir)"
    [[ -n "${ollama_dir}" ]] || return 0
    as_root install -d -m 0755 "${ollama_dir}"
    if [[ "${EUID}" -ne 0 ]]; then
        as_root chown -R "${USER}:${USER}" "${ollama_dir}" || true
    fi
    print_success "Ollama model directory ready at ${ollama_dir}"
}

detect_primary_ip() {
    local ip
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    printf "%s" "${ip}"
}

ensure_tls_certs() {
    local cert_dir="${ROOT_DIR}/deploy/certs"
    local cert_file="${cert_dir}/server.crt"
    local key_file="${cert_dir}/server.key"
    local host_ip host_short host_fqdn san_config

    if [[ -f "${cert_file}" && -f "${key_file}" ]]; then
        TLS_CERTS_GENERATED_BY_INSTALLER="0"
        print_success "TLS certificates already exist"
        return
    fi

    host_ip="$(detect_primary_ip)"
    host_short="$(hostname -s 2>/dev/null || hostname)"
    host_fqdn="$(hostname -f 2>/dev/null || printf "%s" "${host_short}")"
    san_config="$(mktemp)"

    mkdir -p "${cert_dir}"
    cat >"${san_config}" <<EOF
[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_req
prompt = no

[req_distinguished_name]
CN = ${host_fqdn}

[v3_req]
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
DNS.2 = ${host_short}
DNS.3 = ${host_fqdn}
IP.1 = 127.0.0.1
EOF

    if [[ -n "${host_ip}" ]]; then
        printf "IP.2 = %s\n" "${host_ip}" >>"${san_config}"
    fi

    openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
        -keyout "${key_file}" \
        -out "${cert_file}" \
        -config "${san_config}" >/dev/null 2>&1
    chmod 600 "${key_file}"
    chmod 644 "${cert_file}"
    rm -f "${san_config}"
    TLS_CERTS_GENERATED_BY_INSTALLER="1"
    print_success "Self-signed TLS certificates generated"
}

write_install_manifest() {
    local ollama_dir
    ollama_dir="$(extract_ollama_host_dir)"

    cat >"${STATE_FILE}" <<EOF
# Generated by Corporate AI Assistant install.sh
MANIFEST_VERSION=2
REPO_ROOT=${ROOT_DIR}
HOST_STATE_DIR=${HOST_STATE_DIR}
HOST_STATE_FILE=${HOST_STATE_FILE}
INSTALL_USER=${INSTALL_USER}
OLLAMA_HOST_DIR=${ollama_dir}
GENERATED_ENV_FILE=1
GENERATED_KRB5_CONF=1
GENERATED_TLS_CERTS=${TLS_CERTS_GENERATED_BY_INSTALLER}
CERTS_GENERATED_BY_INSTALLER=${TLS_CERTS_GENERATED_BY_INSTALLER}
PREINSTALL_DOCKER_CLI=${PREINSTALL_DOCKER_CLI}
PREINSTALL_DOCKER_COMPOSE_PLUGIN=${PREINSTALL_DOCKER_COMPOSE_PLUGIN}
PREINSTALL_DOCKER_SERVICE_ENABLED=${PREINSTALL_DOCKER_SERVICE_ENABLED}
PREINSTALL_DOCKER_SERVICE_ACTIVE=${PREINSTALL_DOCKER_SERVICE_ACTIVE}
PREINSTALL_OLLAMA_CLI=${PREINSTALL_OLLAMA_CLI}
PREINSTALL_OLLAMA_SERVICE_PRESENT=${PREINSTALL_OLLAMA_SERVICE_PRESENT}
PREINSTALL_OLLAMA_SERVICE_ENABLED=${PREINSTALL_OLLAMA_SERVICE_ENABLED}
PREINSTALL_OLLAMA_SERVICE_ACTIVE=${PREINSTALL_OLLAMA_SERVICE_ACTIVE}
PREINSTALL_USER_IN_DOCKER_GROUP=${PREINSTALL_USER_IN_DOCKER_GROUP}
PREEXISTING_DOCKER_KEYRING=${PREEXISTING_DOCKER_KEYRING}
PREEXISTING_DOCKER_REPO_FILE=${PREEXISTING_DOCKER_REPO_FILE}
INSTALLER_MANAGED_DOCKER_REPO_FILE=${INSTALLER_MANAGED_DOCKER_REPO_FILE}
DOCKER_REPO_FILE_BACKUP=${DOCKER_REPO_FILE_BACKUP}
INSTALLER_ADDED_DOCKER_KEYRING=${INSTALLER_ADDED_DOCKER_KEYRING}
INSTALLER_ADDED_USER_TO_DOCKER_GROUP=${INSTALLER_ADDED_USER_TO_DOCKER_GROUP}
INSTALLER_INSTALLED_DOCKER_ENGINE=${INSTALLER_INSTALLED_DOCKER_ENGINE}
INSTALLER_INSTALLED_DOCKER_COMPOSE_PLUGIN=${INSTALLER_INSTALLED_DOCKER_COMPOSE_PLUGIN}
INSTALLER_INSTALLED_OLLAMA_CLI=${INSTALLER_INSTALLED_OLLAMA_CLI}
POSTINSTALL_OLLAMA_BIN_PATH=${POSTINSTALL_OLLAMA_BIN_PATH}
POSTINSTALL_OLLAMA_SERVICE_FRAGMENT=${POSTINSTALL_OLLAMA_SERVICE_FRAGMENT}
APT_PACKAGES_INSTALLED_BY_INSTALLER=$(join_by_space "${APT_PACKAGES_INSTALLED_BY_INSTALLER[@]}")
EOF
    chmod 600 "${STATE_FILE}"
    print_success "Install manifest recorded at ${STATE_FILE}"
}

write_host_state_manifest() {
    local existing_owned_packages existing_owned_docker_engine existing_owned_compose_plugin
    local existing_owned_repo_file existing_owned_repo_backup existing_owned_keyring
    local existing_owned_group existing_owned_group_user existing_owned_ollama_cli
    local existing_owned_ollama_bin existing_owned_ollama_service
    local existing_pre_docker_cli existing_pre_docker_compose existing_pre_docker_enabled existing_pre_docker_active
    local existing_pre_ollama_cli existing_pre_ollama_service_present existing_pre_ollama_enabled existing_pre_ollama_active
    local owned_docker_engine owned_compose_plugin owned_repo_file owned_keyring owned_group owned_ollama_cli
    local owned_group_user owned_repo_backup owned_ollama_bin owned_ollama_service
    local pre_docker_cli pre_docker_compose pre_docker_enabled pre_docker_active
    local pre_ollama_cli pre_ollama_service_present pre_ollama_enabled pre_ollama_active
    local temp_file pkg
    local -a merged_owned_packages=()

    existing_owned_packages="$(state_file_value "${HOST_STATE_FILE}" "OWNED_APT_PACKAGES" || true)"
    existing_owned_docker_engine="$(state_file_value "${HOST_STATE_FILE}" "OWNED_DOCKER_ENGINE" || true)"
    existing_owned_compose_plugin="$(state_file_value "${HOST_STATE_FILE}" "OWNED_DOCKER_COMPOSE_PLUGIN" || true)"
    existing_owned_repo_file="$(state_file_value "${HOST_STATE_FILE}" "OWNED_DOCKER_REPO_FILE" || true)"
    existing_owned_repo_backup="$(state_file_value "${HOST_STATE_FILE}" "OWNED_DOCKER_REPO_BACKUP" || true)"
    existing_owned_keyring="$(state_file_value "${HOST_STATE_FILE}" "OWNED_DOCKER_KEYRING" || true)"
    existing_owned_group="$(state_file_value "${HOST_STATE_FILE}" "OWNED_DOCKER_GROUP_MEMBERSHIP" || true)"
    existing_owned_group_user="$(state_file_value "${HOST_STATE_FILE}" "OWNED_DOCKER_GROUP_USER" || true)"
    existing_owned_ollama_cli="$(state_file_value "${HOST_STATE_FILE}" "OWNED_OLLAMA_CLI" || true)"
    existing_owned_ollama_bin="$(state_file_value "${HOST_STATE_FILE}" "OWNED_OLLAMA_BIN_PATH" || true)"
    existing_owned_ollama_service="$(state_file_value "${HOST_STATE_FILE}" "OWNED_OLLAMA_SERVICE_FRAGMENT" || true)"
    existing_pre_docker_cli="$(state_file_value "${HOST_STATE_FILE}" "PREINSTALL_DOCKER_CLI" || true)"
    existing_pre_docker_compose="$(state_file_value "${HOST_STATE_FILE}" "PREINSTALL_DOCKER_COMPOSE_PLUGIN" || true)"
    existing_pre_docker_enabled="$(state_file_value "${HOST_STATE_FILE}" "PREINSTALL_DOCKER_SERVICE_ENABLED" || true)"
    existing_pre_docker_active="$(state_file_value "${HOST_STATE_FILE}" "PREINSTALL_DOCKER_SERVICE_ACTIVE" || true)"
    existing_pre_ollama_cli="$(state_file_value "${HOST_STATE_FILE}" "PREINSTALL_OLLAMA_CLI" || true)"
    existing_pre_ollama_service_present="$(state_file_value "${HOST_STATE_FILE}" "PREINSTALL_OLLAMA_SERVICE_PRESENT" || true)"
    existing_pre_ollama_enabled="$(state_file_value "${HOST_STATE_FILE}" "PREINSTALL_OLLAMA_SERVICE_ENABLED" || true)"
    existing_pre_ollama_active="$(state_file_value "${HOST_STATE_FILE}" "PREINSTALL_OLLAMA_SERVICE_ACTIVE" || true)"

    if [[ -n "${existing_owned_packages}" ]]; then
        local -a existing_packages=()
        read -r -a existing_packages <<<"${existing_owned_packages}"
        for pkg in "${existing_packages[@]}"; do
            append_unique_array_item "merged_owned_packages" "${pkg}"
        done
    fi
    for pkg in "${APT_PACKAGES_INSTALLED_BY_INSTALLER[@]}"; do
        append_unique_array_item "merged_owned_packages" "${pkg}"
    done

    owned_docker_engine="$(or_bool "${existing_owned_docker_engine}" "${INSTALLER_INSTALLED_DOCKER_ENGINE}")"
    owned_compose_plugin="$(or_bool "${existing_owned_compose_plugin}" "${INSTALLER_INSTALLED_DOCKER_COMPOSE_PLUGIN}")"
    owned_repo_file="$(or_bool "${existing_owned_repo_file}" "${INSTALLER_MANAGED_DOCKER_REPO_FILE}")"
    owned_keyring="$(or_bool "${existing_owned_keyring}" "${INSTALLER_ADDED_DOCKER_KEYRING}")"
    owned_group="$(or_bool "${existing_owned_group}" "${INSTALLER_ADDED_USER_TO_DOCKER_GROUP}")"
    owned_ollama_cli="$(or_bool "${existing_owned_ollama_cli}" "${INSTALLER_INSTALLED_OLLAMA_CLI}")"

    owned_group_user="${existing_owned_group_user}"
    if [[ -z "${owned_group_user}" ]] && bool_is_true "${INSTALLER_ADDED_USER_TO_DOCKER_GROUP}"; then
        owned_group_user="${INSTALL_USER}"
    fi
    owned_repo_backup="$(coalesce_value "${existing_owned_repo_backup}" "${DOCKER_REPO_FILE_BACKUP}" || true)"

    if bool_is_true "${owned_ollama_cli}"; then
        owned_ollama_bin="$(coalesce_value "${existing_owned_ollama_bin}" "${POSTINSTALL_OLLAMA_BIN_PATH}" || true)"
        owned_ollama_service="$(coalesce_value "${existing_owned_ollama_service}" "${POSTINSTALL_OLLAMA_SERVICE_FRAGMENT}" || true)"
    else
        owned_ollama_bin=""
        owned_ollama_service=""
    fi

    pre_docker_cli="$(coalesce_value "${existing_pre_docker_cli}" "${PREINSTALL_DOCKER_CLI}" || true)"
    pre_docker_compose="$(coalesce_value "${existing_pre_docker_compose}" "${PREINSTALL_DOCKER_COMPOSE_PLUGIN}" || true)"
    pre_docker_enabled="$(coalesce_value "${existing_pre_docker_enabled}" "${PREINSTALL_DOCKER_SERVICE_ENABLED}" || true)"
    pre_docker_active="$(coalesce_value "${existing_pre_docker_active}" "${PREINSTALL_DOCKER_SERVICE_ACTIVE}" || true)"
    pre_ollama_cli="$(coalesce_value "${existing_pre_ollama_cli}" "${PREINSTALL_OLLAMA_CLI}" || true)"
    pre_ollama_service_present="$(coalesce_value "${existing_pre_ollama_service_present}" "${PREINSTALL_OLLAMA_SERVICE_PRESENT}" || true)"
    pre_ollama_enabled="$(coalesce_value "${existing_pre_ollama_enabled}" "${PREINSTALL_OLLAMA_SERVICE_ENABLED}" || true)"
    pre_ollama_active="$(coalesce_value "${existing_pre_ollama_active}" "${PREINSTALL_OLLAMA_SERVICE_ACTIVE}" || true)"

    temp_file="$(mktemp)"
    cat >"${temp_file}" <<EOF
# Generated by Corporate AI Assistant install.sh
HOST_STATE_VERSION=1
LAST_REPO_ROOT=${ROOT_DIR}
INSTALL_USER=${INSTALL_USER}
OWNED_APT_PACKAGES=$(join_by_space "${merged_owned_packages[@]}")
OWNED_DOCKER_ENGINE=${owned_docker_engine}
OWNED_DOCKER_COMPOSE_PLUGIN=${owned_compose_plugin}
OWNED_DOCKER_REPO_FILE=${owned_repo_file}
OWNED_DOCKER_REPO_BACKUP=${owned_repo_backup}
OWNED_DOCKER_KEYRING=${owned_keyring}
OWNED_DOCKER_GROUP_MEMBERSHIP=${owned_group}
OWNED_DOCKER_GROUP_USER=${owned_group_user}
OWNED_OLLAMA_CLI=${owned_ollama_cli}
OWNED_OLLAMA_BIN_PATH=${owned_ollama_bin}
OWNED_OLLAMA_SERVICE_FRAGMENT=${owned_ollama_service}
PREINSTALL_DOCKER_CLI=${pre_docker_cli}
PREINSTALL_DOCKER_COMPOSE_PLUGIN=${pre_docker_compose}
PREINSTALL_DOCKER_SERVICE_ENABLED=${pre_docker_enabled}
PREINSTALL_DOCKER_SERVICE_ACTIVE=${pre_docker_active}
PREINSTALL_OLLAMA_CLI=${pre_ollama_cli}
PREINSTALL_OLLAMA_SERVICE_PRESENT=${pre_ollama_service_present}
PREINSTALL_OLLAMA_SERVICE_ENABLED=${pre_ollama_enabled}
PREINSTALL_OLLAMA_SERVICE_ACTIVE=${pre_ollama_active}
CERTS_GENERATED_BY_INSTALLER=${TLS_CERTS_GENERATED_BY_INSTALLER}
EOF

    as_root install -m 0755 -d "${HOST_STATE_DIR}"
    as_root cp "${temp_file}" "${HOST_STATE_FILE}"
    as_root chmod 0644 "${HOST_STATE_FILE}"
    rm -f "${temp_file}"
    print_success "Durable host ownership manifest recorded at ${HOST_STATE_FILE}"
}

wait_for_ollama_container() {
    local retries=60
    local attempt

    for attempt in $(seq 1 "${retries}"); do
        if docker_compose exec -T ollama ollama list >/dev/null 2>&1; then
            print_success "Ollama container is ready"
            return
        fi
        sleep 2
    done

    die "Timed out waiting for the Ollama container"
}

ensure_default_model_available() {
    print_header "Ollama Model"
    if docker_compose exec -T ollama ollama list 2>/dev/null | awk 'NR>1 && NF {print $1}' | grep -Fx "${DEFAULT_MODEL}" >/dev/null 2>&1; then
        MODEL_BOOTSTRAP_STATUS="already-present"
        MODEL_PRESENT_AFTER_BOOTSTRAP="yes"
        CHAT_READY_IMMEDIATELY="yes"
        print_success "Selected default model ${DEFAULT_MODEL} is already present"
        return
    fi

    if [[ "${DOWNLOAD_DEFAULT_MODEL_NOW}" != "true" ]]; then
        MODEL_BOOTSTRAP_STATUS="skipped"
        MODEL_PRESENT_AFTER_BOOTSTRAP="no"
        CHAT_READY_IMMEDIATELY="no"
        print_warning "Selected default model ${DEFAULT_MODEL} was not downloaded during install"
        print_warning "The stack can start, but chat will not be ready until the selected model is installed"
        return
    fi

    print_info "Attempting to pull selected default model ${DEFAULT_MODEL}"
    if docker_compose exec -T ollama ollama pull "${DEFAULT_MODEL}"; then
        MODEL_BOOTSTRAP_STATUS="done"
    else
        MODEL_BOOTSTRAP_STATUS="failed"
        print_warning "Failed to pull selected default model ${DEFAULT_MODEL}"
    fi

    if docker_compose exec -T ollama ollama list 2>/dev/null | awk 'NR>1 && NF {print $1}' | grep -Fx "${DEFAULT_MODEL}" >/dev/null 2>&1; then
        MODEL_PRESENT_AFTER_BOOTSTRAP="yes"
        CHAT_READY_IMMEDIATELY="yes"
        print_success "Selected default model ${DEFAULT_MODEL} is present in runtime"
        return
    fi

    MODEL_PRESENT_AFTER_BOOTSTRAP="no"
    CHAT_READY_IMMEDIATELY="no"
    print_warning "Selected default model ${DEFAULT_MODEL} is still missing after bootstrap attempt"
    print_warning "The application will start, but chat requests will return a model-unavailable error until the model is installed"
}

wait_for_ready() {
    local retries=90
    local attempt
    local ready_url="https://127.0.0.1/health/ready"

    print_header "Health Check"
    for attempt in $(seq 1 "${retries}"); do
        if curl -k -fsS --connect-timeout 3 "${ready_url}" >/dev/null 2>&1; then
            print_success "Application is ready"
            return
        fi
        sleep 3
    done

    docker_compose ps || true
    docker_compose logs --no-color --tail=120 || true
    die "Timed out waiting for ${ready_url}"
}

run_auth_smoke_test() {
    local cookiejar
    local login_code
    local user_code

    if [[ -z "${TEST_ADMIN_USER}" || -z "${TEST_ADMIN_PASSWORD}" ]]; then
        print_info "Skipping auth smoke test"
        return
    fi

    print_header "Auth Smoke Test"
    cookiejar="$(mktemp)"

    login_code="$(
        curl -k -sS -o /dev/null -w '%{http_code}' \
            -c "${cookiejar}" \
            -X POST "https://127.0.0.1/login" \
            --data-urlencode "username=${TEST_ADMIN_USER}" \
            --data-urlencode "password=${TEST_ADMIN_PASSWORD}"
    )"
    [[ "${login_code}" == "303" ]] || die "Authentication smoke test failed: /login returned ${login_code}"

    user_code="$(
        curl -k -sS -o /dev/null -w '%{http_code}' \
            -b "${cookiejar}" \
            "https://127.0.0.1/api/user"
    )"
    rm -f "${cookiejar}"

    [[ "${user_code}" == "200" ]] || die "Authentication smoke test failed: /api/user returned ${user_code}"
    print_success "Kerberos + LDAP login smoke test passed"
}

build_and_start_stack() {
    print_header "Docker Compose Deployment"
    docker_compose_for_install_mode build
    docker_compose_for_install_mode up -d redis ollama
    wait_for_ollama_container
    ensure_default_model_available
    docker_compose_for_install_mode up -d
    print_success "Docker Compose stack is running"
}

print_final_summary() {
    local host_ip
    host_ip="$(detect_primary_ip)"
    print_header "Deployment Complete"
    print_success "System is ready: https://${host_ip:-localhost}"
    print_info "DEFAULT_MODEL=${DEFAULT_MODEL}"
    print_info "Model pre-pull: ${MODEL_BOOTSTRAP_STATUS}"
    print_info "Model present in runtime: ${MODEL_PRESENT_AFTER_BOOTSTRAP}"
    print_info "Chat ready immediately: ${CHAT_READY_IMMEDIATELY}"
    print_info "If the browser warns about TLS, accept the self-signed certificate once / Если браузер предупреждает о TLS, один раз примите self-signed certificate"
    print_info "Install log: ${LOG_FILE}"
}

main() {
    precheck_os
    capture_preinstall_state
    collect_system_audit
    print_system_audit_summary
    print_preflight_warnings
    select_install_mode
    confirm_system_changes
    network_check
    install_base_packages
    ensure_docker_installed
    ensure_ollama_cli
    validate_install_mode
    collect_configuration
    validate_directory_service_resolution
    validate_sso_keytab_material
    write_env_file
    write_krb5_conf
    write_compose_override_if_needed
    ensure_ollama_host_dir
    ensure_tls_certs
    write_host_state_manifest
    write_install_manifest
    build_and_start_stack
    wait_for_ready
    run_auth_smoke_test
    print_final_summary
}

if [[ "${INSTALL_SH_SOURCE_ONLY:-0}" != "1" ]]; then
    main "$@"
fi
