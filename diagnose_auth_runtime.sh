#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.yml"
APP_SERVICE="app"
APP_CONTAINER="corporate-ai-assistant"
LDAP_URI="${LDAP_URI:-ldap://srv-ad}"
LDAP_BASE_DN="${LDAP_BASE_DN:-DC=corp,DC=local}"
KRB_SERVICE="${KRB_SERVICE:-ldap/srv-ad}"
USERNAME="${1:-${AUTH_CHECK_USER:-}}"
PASSWORD="${AUTH_CHECK_PASSWORD:-}"

if ! command -v docker >/dev/null 2>&1; then
    echo "[ERROR] docker is required" >&2
    exit 1
fi

docker compose -f "${COMPOSE_FILE}" ps "${APP_SERVICE}" >/dev/null

echo "[INFO] Runtime auth diagnostics for ${APP_CONTAINER}"
echo "[INFO] LDAP URI: ${LDAP_URI}"
echo "[INFO] Kerberos service: ${KRB_SERVICE}"
echo

echo "[STEP] DNS resolution"
docker compose -f "${COMPOSE_FILE}" exec -T "${APP_SERVICE}" sh -lc "getent hosts srv-ad"
echo

if [[ -z "${USERNAME}" || -z "${PASSWORD}" ]]; then
    cat <<EOF
[WARN] Username and password were not provided.
[WARN] DNS was checked, but Kerberos and LDAP checks were skipped.

To run the full diagnostic:
  AUTH_CHECK_PASSWORD='your-password' ./diagnose_auth_runtime.sh your.username
EOF
    exit 0
fi

echo "[STEP] Kerberos TGT"
docker compose -f "${COMPOSE_FILE}" exec -T \
    -e AUTH_CHECK_USER="${USERNAME}" \
    -e AUTH_CHECK_PASSWORD="${PASSWORD}" \
    "${APP_SERVICE}" sh -lc \
    'rm -f /tmp/auth-check.ccache && printf "%s\n" "$AUTH_CHECK_PASSWORD" | KRB5CCNAME=FILE:/tmp/auth-check.ccache kinit "${AUTH_CHECK_USER}@CORP.LOCAL"'
echo

echo "[STEP] Kerberos service ticket"
docker compose -f "${COMPOSE_FILE}" exec -T "${APP_SERVICE}" sh -lc \
    "KRB5CCNAME=FILE:/tmp/auth-check.ccache kvno '${KRB_SERVICE}'"
echo

echo "[STEP] LDAP GSSAPI search"
docker compose -f "${COMPOSE_FILE}" exec -T \
    -e AUTH_CHECK_USER="${USERNAME}" \
    "${APP_SERVICE}" sh -lc \
    "KRB5CCNAME=FILE:/tmp/auth-check.ccache ldapsearch -LLL -N -Y GSSAPI -H '${LDAP_URI}' -b '${LDAP_BASE_DN}' \"(sAMAccountName=\$AUTH_CHECK_USER)\" sAMAccountName displayName mail"
echo

echo "[STEP] Cleanup"
docker compose -f "${COMPOSE_FILE}" exec -T "${APP_SERVICE}" sh -lc \
    "KRB5CCNAME=FILE:/tmp/auth-check.ccache kdestroy >/dev/null 2>&1 || true; rm -f /tmp/auth-check.ccache"

echo
echo "[OK] Authentication runtime diagnostics completed successfully"
