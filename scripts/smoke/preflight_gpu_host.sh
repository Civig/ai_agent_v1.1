#!/usr/bin/env bash

set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib_smoke.sh"
cd "${SMOKE_REPO_ROOT}"
smoke_init_artifact_dir "preflight" >/dev/null

preflight_dir="${SMOKE_ARTIFACT_DIR}/preflight"
mkdir -p "${preflight_dir}"

smoke_capture_command "${preflight_dir}/hostname.txt" hostname
smoke_capture_command "${preflight_dir}/whoami.txt" whoami
smoke_capture_command "${preflight_dir}/pwd.txt" pwd
smoke_capture_command "${preflight_dir}/date.txt" date -u
smoke_capture_command "${preflight_dir}/uname.txt" uname -a
smoke_capture_shell "${preflight_dir}/os-release.txt" 'test -f /etc/os-release && sed -n "1,80p" /etc/os-release || true'
smoke_capture_command "${preflight_dir}/nvidia-smi.txt" nvidia-smi
smoke_capture_command "${preflight_dir}/docker-version.txt" docker version
smoke_capture_command "${preflight_dir}/docker-compose-version.txt" docker compose version
smoke_capture_command "${preflight_dir}/git-version.txt" git version
smoke_capture_command "${preflight_dir}/docker-ps-a.txt" docker ps -a
smoke_capture_command "${preflight_dir}/docker-volume-ls.txt" docker volume ls

gpu_image="${SMOKE_GPU_CHECK_IMAGE:-nvidia/cuda:12.4.1-base-ubuntu22.04}"
smoke_capture_shell "${preflight_dir}/docker-gpu-check.txt" "
set -u
printf '# docker info runtimes\n'
docker info 2>/dev/null | grep -Ei 'runtimes|nvidia|gpu' || true
printf '\n# compose ollama nvidia-smi\n'
docker compose exec -T ollama nvidia-smi || true
printf '\n# docker run --gpus all --pull=never\n'
docker run --rm --pull=never --gpus all '${gpu_image}' nvidia-smi || true
"

printf 'Preflight complete\n'
smoke_print_artifact_hint
