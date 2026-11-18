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

sec_cleanup_run "$@"
[ "$SEC_CLEAN_RC" -eq 2 ] && { printf '%s\n' "$SEC_CLEAN_WARN" >&2; exit 2; }   # 인자 오류 — 메시지만 내고 끝낸다
case " $* " in *" --dry-run "*) verb="지울 대상" ;; *) verb="지움" ;; esac
if [ -n "$SEC_CLEANED" ]; then
  sec_log "$verb: $(printf '%s\n' "$SEC_CLEANED" | grep -c .)개 — ${SEC_CLEAN_DAYS}일보다 오래됨 ($SEC_DATA/reports)"
  printf '%s\n' "$SEC_CLEANED" | while IFS= read -r n; do sec_log "  $n"; done
fi
if [ -n "$SEC_CLEAN_WARN" ]; then
  printf '%s\n' "$SEC_CLEAN_WARN" | while IFS= read -r line; do sec_warn "$line"; done
fi
if [ "$SEC_CLEAN_RC" -ne 0 ]; then
  sec_err "정리하지 못한 항목이 있습니다 — 위 메시지를 확인하세요"
elif [ -z "$SEC_CLEANED" ]; then
  sec_log "${SEC_CLEAN_DAYS}일보다 오래된 리포트가 없습니다 ($SEC_DATA/reports)"
fi
exit "$SEC_CLEAN_RC"
