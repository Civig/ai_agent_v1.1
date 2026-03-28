#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

readonly BLUE='\033[0;34m'
readonly GREEN='\033[0;32m'
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

print_error() {
    printf "%b[ERROR]%b %s\n" "${RED}" "${NC}" "$1" >&2
}

docker_compose() {
    docker compose "$@"
}

wait_for_ready() {
    local retries=60
    local attempt
    for attempt in $(seq 1 "${retries}"); do
        if curl -k -fsS --connect-timeout 3 https://127.0.0.1/health/ready >/dev/null 2>&1; then
            return
        fi
        sleep 2
    done
    return 1
}

main() {
    cd "${ROOT_DIR}"
    [[ -f docker-compose.yml ]] || { print_error "docker-compose.yml was not found"; exit 1; }

    print_header "Corporate AI Assistant"
    docker_compose up -d

    if wait_for_ready; then
        print_success "System is ready: https://$(hostname -I 2>/dev/null | awk '{print $1}')"
        exit 0
    fi

    print_error "Stack started, but /health/ready did not become healthy in time"
    docker_compose ps
    exit 1
}

main "$@"
