#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

readonly BLUE='\033[0;34m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly RED='\033[0;31m'
readonly NC='\033[0m'

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

docker_compose() {
    docker compose "$@"
}

confirm() {
    local prompt="$1"
    local answer
    read -r -p "${prompt} [y/N]: " answer
    [[ "${answer,,}" == "y" || "${answer,,}" == "yes" ]]
}

main() {
    cd "${ROOT_DIR}"
    [[ -f docker-compose.yml ]] || { print_error "docker-compose.yml was not found"; exit 1; }

    print_header "Corporate AI Assistant Cleanup"
    docker_compose down --remove-orphans
    print_success "Compose stack stopped"

    if confirm "Remove persistent Docker volumes (Redis/Ollama data)?"; then
        docker_compose down -v --remove-orphans
        print_warning "Persistent volumes removed"
    fi

    rm -rf .install __pycache__
    find . -type d -name "__pycache__" -prune -exec rm -rf {} +
    find . -type f \( -name "*.pyc" -o -name "*.pyo" -o -name "*.log" \) -delete
    print_success "Local caches and generated logs removed"

    if confirm "Remove generated deployment files (.env backup, certs, override, krb5.conf)?"; then
        rm -rf deploy/certs
        rm -f deploy/krb5.conf docker-compose.override.yml
        find . -maxdepth 1 -type f -name ".env.bak.*" -delete
        print_warning "Generated deployment files removed"
    fi

    print_success "Cleanup complete"
}

main "$@"
