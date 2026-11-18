#!/usr/bin/env bash
# 보관 기간이 지난 스캔 리포트를 지운다 — $DATA/reports/<run-id>/ (기본 30일, 미결정 사항 Q10)
# 스캔할 때마다 자동으로도 실행된다(common.sh sec_new_run). 외부와 통신하지 않는다.
#
# 사용: cleanup.sh [--days N] [--dry-run]
#   --days N    N일(1~3650)보다 오래된 리포트를 지운다 (기본 30)
#   --dry-run   지우지 않고 지울 대상만 보여 준다
#
#   docs/security/04 보안/시크릿 처리.md (4. 리포트 보관)
set -u
umask 077

SELF_DIR="$(cd -P "$(dirname "$0")" && pwd -P)"
# shellcheck source=scripts/lib/common.sh
. "$SELF_DIR/lib/common.sh"

for arg in "$@"; do
  case "$arg" in
    -h | --help)
      sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
  esac
done

out=$(python3 -I "$SEC_PLUGIN/scripts/lib/cleanup_reports.py" "$SEC_DATA/reports" "$@")
rc=$?
case " $* " in *" --dry-run "*) verb="지울 대상" ;; *) verb="지움" ;; esac
if [ -n "$out" ]; then
  sec_log "$verb: $(printf '%s\n' "$out" | wc -l | tr -d ' ')개 ($SEC_DATA/reports)"
  printf '%s\n' "$out" | while IFS= read -r n; do sec_log "  $n"; done
else
  sec_log "보관 기간이 지난 리포트가 없습니다 ($SEC_DATA/reports)"
fi
exit "$rc"
