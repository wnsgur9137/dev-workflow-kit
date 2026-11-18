#!/usr/bin/env bash
# 보관 기간이 지난 스캔 리포트를 지운다 — $DATA/reports/<run-id>/ (기본 30일, 미결정 사항 Q10)
# 스캔할 때마다 자동으로도 실행된다(common.sh sec_new_run). 외부와 통신하지 않는다.
#
# 사용: cleanup.sh [--days N] [--dry-run]
#   --days N    N일(1~3650)보다 오래된 리포트를 지운다 (기본: DWK_SECURITY_RETENTION_DAYS, 없으면 30)
#               자동 정리는 DWK_SECURITY_RETENTION_DAYS 를 따르므로, 더 오래 남기려면 그 환경변수를 바꾼다
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
      sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
  esac
done

out=$(python3 -I "$SEC_PLUGIN/scripts/lib/cleanup_reports.py" "$SEC_DATA/reports" "$@")
rc=$?
[ "$rc" -eq 2 ] && exit 2   # 인자 오류 — 메시지는 이미 나갔다
days=$(printf '%s\n' "$out" | sed -n '1s/^days=//p')
names=$(printf '%s\n' "$out" | sed '1{/^days=/d;}')
case " $* " in *" --dry-run "*) verb="지울 대상" ;; *) verb="지움" ;; esac
if [ -n "$names" ]; then
  sec_log "$verb: $(printf '%s\n' "$names" | grep -c .)개 — ${days}일보다 오래됨 ($SEC_DATA/reports)"
  printf '%s\n' "$names" | while IFS= read -r n; do sec_log "  $n"; done
fi
if [ "$rc" -ne 0 ]; then
  sec_err "일부 리포트를 지우지 못했습니다 — 위 메시지를 확인하세요"
elif [ -z "$names" ]; then
  sec_log "${days}일보다 오래된 리포트가 없습니다 ($SEC_DATA/reports)"
fi
exit "$rc"
