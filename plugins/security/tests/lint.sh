#!/usr/bin/env bash
# 린트 게이트 — 로컬 shellcheck 가 없으면 digest 고정 컨테이너로 실행한다.
set -u
cd "$(dirname "$0")/.." || exit 1
IMAGE="koalaman/shellcheck@sha256:2097951f02e735b613f4a34de20c40f937a6c8f18ecb170612c88c34517221fb" # v0.10.0
files=$(find scripts tests -type f \( -name '*.sh' -o -name 'fake-docker' \) | sort)
if command -v shellcheck >/dev/null 2>&1; then
  # shellcheck disable=SC2086
  exec shellcheck -x -s bash $files
fi
# shellcheck disable=SC2086
exec docker run --rm --network none -e LANG=C.UTF-8 -e LC_ALL=C.UTF-8 -v "$PWD":/mnt:ro -w /mnt "$IMAGE" -x -s bash $files
