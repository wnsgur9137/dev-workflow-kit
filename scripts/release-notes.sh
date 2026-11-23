#!/usr/bin/env bash
# CHANGELOG에서 한 버전의 절을 꺼내 릴리스 노트로 출력한다.
# 사용: scripts/release-notes.sh <workflow|security> <버전>
set -euo pipefail
plugin="${1:?플러그인 이름(workflow|security)}"; version="${2:?버전 (예: 2.0.1)}"
file="$(cd "$(dirname "$0")/.." && pwd)/plugins/$plugin/CHANGELOG.md"
[ -f "$file" ] || { echo "CHANGELOG 없음: $file" >&2; exit 1; }
notes="$(awk -v v="$version" '
  index($0, "## [" v "]") == 1 { on=1; next }
  on && /^## \[/ { exit }
  on && /^\[[^]]+\]: http/ { exit }
  on { print }
' "$file" | sed '/./,$!d')"
[ -n "$(printf '%s' "$notes" | tr -d '[:space:]')" ] || { echo "$file 에 [$version] 절이 없거나 비어 있습니다" >&2; exit 1; }
# 릴리스 화면에서는 상대 링크가 깨지므로 플러그인 폴더 기준 절대 주소로 바꾼다 (http·# 링크는 그대로)
base="https://github.com/wnsgur9137/dev-workflow-kit/blob/master/plugins/$plugin"
notes="$(printf '%s\n' "$notes" | perl -pe 's{\]\((?!https?://|#|mailto:)([^)\s]+)\)}{](BASE/$1)}g' | sed "s|](BASE/|]($base/|g")"
printf '%s\n\n전체 변경 이력: [CHANGELOG](https://github.com/wnsgur9137/dev-workflow-kit/blob/master/plugins/%s/CHANGELOG.md)\n' "$notes" "$plugin"
