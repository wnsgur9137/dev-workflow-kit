#!/usr/bin/env bash
# /security:scan-web — 웹 대상 수동(passive) 점검 (OWASP ZAP baseline, 네트워크 N2 — 허용목록 이그레스)
#
# 사용: scan-web.sh <URL>
#
# - URL 의 scheme+host+port 가 허용목록($CONF/targets.allowlist)에 정확히 있어야 한다 (1차, 이 스크립트).
#   허용목록은 사용자가 직접 관리한다 — 없거나 맞지 않으면 컨테이너를 띄우지 않고 끝낸다
# - ZAP 은 internal 네트워크에서만 돌고, 바깥으로는 egress-proxy(tinyproxy)를 거쳐서만 나간다.
#   프록시는 이번 대상의 출처 하나만 열고 나머지는 403 으로 막는다 (2차, 독립 강제). 막힌 요청은 summary 에 남긴다
# - baseline(passive)만 실행한다. active·full scan 은 실행하지 않고, ZAP 인자를 받지 않는다 (ADR-005)
# - 이미지를 받지 않는다 (없으면 update.sh 안내 후 종료)
# - 결과: $DATA/reports/<run-id>/{raw/,findings.json,summary.md,meta.json}
# - stdout 마지막 줄: summary.md 경로
#   docs/security/03 워크플로/scan-web.md
set -u
umask 077

SELF_DIR="$(cd -P "$(dirname "$0")" && pwd -P)"
# shellcheck source=scripts/lib/common.sh
. "$SELF_DIR/lib/common.sh"
# shellcheck source=scripts/lib/detect.sh
. "$SELF_DIR/lib/detect.sh"   # sec_require_python

usage() {
  cat >&2 <<'EOF'
사용: /security:scan-web <URL>
  허용목록(~/.config/dev-workflow-kit/security/targets.allowlist)에 있는 대상만 점검합니다.
  호스트에서 띄운 개발 서버는 http://host.docker.internal:<포트> 처럼 호스트 주소로 지정합니다.
EOF
}

URL_ARG=""
for arg in "$@"; do
  case "$arg" in
    -h | --help)
      usage
      exit 0
      ;;
    -*)
      # 알 수 없는 옵션은 거부한다 (active scan·ZAP 인자 주입 방지)
      sec_err "알 수 없는 옵션: $arg"
      usage
      exit 2
      ;;
    *)
      if [ -n "$URL_ARG" ]; then
        sec_err "점검 대상은 하나만 지정합니다."
        exit 2
      fi
      URL_ARG=$arg
      ;;
  esac
done
[ -n "$URL_ARG" ] || {
  usage
  exit 2
}

sec_require_python || exit 1
ALLOWLIST="$SEC_CONF/targets.allowlist"
TAB=$(printf '\t')

# [1차] 허용목록 검사 — 통과하기 전에는 Docker 를 건드리지 않는다 (V3)
CHECK_ERR=$(mktemp "${TMPDIR:-/tmp}/sec-web.XXXXXX") || sec_die "임시 파일을 만들 수 없습니다."
if ! CHECK=$(python3 -I "$SEC_PLUGIN/scripts/lib/web_target.py" check "$ALLOWLIST" "$URL_ARG" 2>"$CHECK_ERR"); then
  sec_err "점검하지 않습니다 — $(head -c 2000 "$CHECK_ERR")"
  rm -f "$CHECK_ERR"
  exit 1
fi
rm -f "$CHECK_ERR"
TARGET_URL="" DISPLAY_URL="" ORIGIN="" FILTER="" CHECK_WARN=""
while IFS="$TAB" read -r kind value; do
  case "$kind" in
    url) TARGET_URL=$value ;;
    display) DISPLAY_URL=$value ;;
    origin) ORIGIN=$value ;;
    warning) CHECK_WARN="${CHECK_WARN:+$CHECK_WARN
}$value" ;;
    filter) FILTER="${FILTER:+$FILTER
}$value" ;;
  esac
done <<EOF
$CHECK
EOF
if [ -z "$TARGET_URL" ] || [ -z "$DISPLAY_URL" ] || [ -z "$FILTER" ]; then
  sec_die "허용목록 검사 결과를 읽지 못했습니다."
fi

TOOLS="zap egress-proxy"
# shellcheck disable=SC2086
sec_preflight web $TOOLS || exit 1
IMG_ZAP=$(sec_image_ref zap)
IMG_PROXY=$(sec_image_ref egress-proxy)

sec_new_run web || sec_die "리포트 폴더를 만들 수 없습니다."
RAW="$SEC_RUN_DIR/raw"
STATUS="$RAW/status.tsv"
: >"$STATUS"
WARNINGS_FILE="$RAW/warnings.txt"
: >"$WARNINGS_FILE"
STARTED_AT=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
sec_log "run-id: $SEC_RUN_ID"
# 로그·리포트에는 질의 문자열 값·조각을 가린 URL 만 남긴다 (ZAP 에는 원문, PR #34 리뷰 W1)
sec_log "대상: $DISPLAY_URL (프록시가 여는 출처: $ORIGIN)"
if [ -n "$CHECK_WARN" ]; then
  printf '%s\n' "$CHECK_WARN" >>"$WARNINGS_FILE"
  sec_warn "$CHECK_WARN"
fi
ORIGIN_HP=${ORIGIN#*://}
ORIGIN_HOST=${ORIGIN_HP%:*}
ORIGIN_PORT=${ORIGIN_HP##*:}

record() { printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" >>"$STATUS"; }
rand_hex() { od -An -N"$1" -tx1 /dev/urandom 2>/dev/null | tr -d ' \n'; }
tail_log() { tail -n 3 "$1" 2>/dev/null | tr '\n\t' '  ' | cut -c1-280; }

PROJECT_SUFFIX=$(rand_hex 6)
[ ${#PROJECT_SUFFIX} -eq 12 ] || sec_die "무작위 값을 만들 수 없습니다 (od·/dev/urandom 확인)."
COMPOSE_PROJECT="dwk-sec-web-$PROJECT_SUFFIX"

# 스파이더 3분 + 수동 규칙 대기 최대 10분 (docs/security/02 도구/OWASP ZAP.md). 전체는 SCAN_TIMEOUT 초에서 끊는다
DWK_SPIDER_MIN=3
DWK_PASSIVE_MIN=10
SCAN_TIMEOUT_DEFAULT=1800
SCAN_TIMEOUT=$SCAN_TIMEOUT_DEFAULT
# 테스트 전용: 시간 초과 경로를 확인하려고 상한을 **줄이기만** 할 수 있다 (늘릴 수는 없다)
case "${DWK_SEC_TEST_SCAN_TIMEOUT:-}" in
  '' | *[!0-9]*) ;;
  *) [ "$DWK_SEC_TEST_SCAN_TIMEOUT" -lt "$SCAN_TIMEOUT" ] && SCAN_TIMEOUT=$DWK_SEC_TEST_SCAN_TIMEOUT ;;
esac
if [ "$SCAN_TIMEOUT" -lt "$SCAN_TIMEOUT_DEFAULT" ]; then
  printf '%s\n' "테스트 전용 시간 상한(${SCAN_TIMEOUT}초, DWK_SEC_TEST_SCAN_TIMEOUT)이 적용됐습니다 — 의도한 것이 아니면 셸에서 이 변수를 지우세요" >>"$WARNINGS_FILE"
fi
DWK_ZAP_IMAGE=$IMG_ZAP
DWK_PROXY_IMAGE=$IMG_PROXY
DWK_TARGET_URL=$TARGET_URL
DWK_PROXY_FILTER=$FILTER
# tinyproxy 1.11 — 필터에 맞지 않는 요청은 모두 거부(FilterDefaultDeny), 요청 URL 전체에 맞춘다(FilterURLs).
# CONNECT 는 https 대상의 포트만 연다. 로그는 stdout(docker logs)으로 — 차단 줄은 NOTICE 'Proxying refused on filtered url'
DWK_PROXY_CONF=$(printf '%s\n' 'Port 8888' 'Listen 0.0.0.0' 'Timeout 60' 'MaxClients 64' 'LogLevel Notice' \
  'DisableViaHeader Yes' 'FilterDefaultDeny Yes' 'FilterType ere' 'FilterURLs On' 'Filter "/run/dwk/filter"')
case "$ORIGIN" in
  https://*) DWK_PROXY_CONF="$DWK_PROXY_CONF
ConnectPort ${ORIGIN##*:}" ;;
  # http 대상만 열 때는 CONNECT 를 쓸 일이 없다 — 필터에도 맞지 않지만 포트도 닫아 둔다
  *) DWK_PROXY_CONF="$DWK_PROXY_CONF
ConnectPort 1" ;;
esac
export DWK_ZAP_IMAGE DWK_PROXY_IMAGE DWK_TARGET_URL DWK_SPIDER_MIN DWK_PASSIVE_MIN DWK_PROXY_CONF DWK_PROXY_FILTER
COMPOSE_FILE_PATH="$SEC_PLUGIN/docker/compose-web.yml"
compose() { docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE_PATH" "$@"; }

# 이전 실행이 SIGKILL 등으로 trap 없이 끝나 남긴 스택을 지운다 — 동시에 도는 다른 실행을 건드리지 않게
# 가장 최근 활동이 STALE_MIN 분보다 오래된 것만 (한 실행의 최대 시간 = 프록시 기동 60초 + 격리 확인 + SCAN_TIMEOUT 30분보다 길다).
# 시각 판정은 scripts/lib/stale_projects.py (scan-app 과 같은 규칙 — 엔진 시계 기준, 시각을 모르면 지우지 않음)
STALE_MIN=120
cleanup_stale() {
  local ids nets projects p n=0 now
  now=$(docker info --format '{{.SystemTime}}' 2>/dev/null)
  [ -n "$now" ] || return 0
  ids=$(docker ps -aq --filter label=com.docker.compose.project 2>/dev/null)
  # 컨테이너는 지워지고 네트워크만 남은 프로젝트도 찾는다 (PR #34 리뷰 S5)
  nets=$(docker network ls -q --filter label=com.docker.compose.project 2>/dev/null)
  # shellcheck disable=SC2086  # id 목록 — 공백 없는 이름이다
  projects=$({
    [ -n "$ids" ] && docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}} {{.Created}}' $ids 2>/dev/null
    [ -n "$nets" ] && docker network inspect -f '{{index .Labels "com.docker.compose.project"}} {{.Created}}' $nets 2>/dev/null
  } | python3 -I "$SEC_PLUGIN/scripts/lib/stale_projects.py" dwk-sec-web "$STALE_MIN" "$now" 2>/dev/null)
  for p in $projects; do
    docker compose -p "$p" -f "$COMPOSE_FILE_PATH" --profile scan down -v --remove-orphans --timeout 5 >/dev/null 2>&1 && n=$((n + 1))
  done
  [ $n -gt 0 ] && printf '%s\n' "이전 실행이 남긴 ZAP 스택 ${n}개(${STALE_MIN}분 이상 지난 것)를 지웠습니다." >>"$WARNINGS_FILE"
  return 0
}

STACK_UP=0
pid_scan=""
pid_watchdog=""
ZAP_LOG_REDACTED=0
stack_down() {
  compose --profile scan down -v --remove-orphans --timeout 10 >/dev/null 2>&1 && STACK_UP=0
}
cleanup() {
  # 정리 중 두 번째 Ctrl-C·TERM 으로 스택 내리기·진행 로그 가림을 건너뛰지 않게 막는다 (5차 리뷰 R5-S3).
  # 무시는 자식(docker compose down)에도 물려진다 — 정리 중에는 Ctrl-C 가 듣지 않으므로 한 줄 알린다 (6차 리뷰 R6-N2).
  # 정리 중 출력은 서브셸에서 낸다 — '… | tee' 로 실행하다 Ctrl-C 로 파이프가 닫히면 printf 의 SIGPIPE 가
  # 이 셸을 죽여 스택 내리기·진행 로그 가림을 건너뛴다 (7차 리뷰 R7-W1)
  trap '' INT TERM
  [ -n "$pid_watchdog" ] && kill "$pid_watchdog" 2>/dev/null
  # 백그라운드 compose run CLI 는 down 으로 컨테이너가 사라지면 함께 끝난다
  [ -n "$pid_scan" ] && kill "$pid_scan" 2>/dev/null
  if [ $STACK_UP -eq 1 ]; then
    ( sec_log "ZAP 스택 정리 중 (최대 수십 초, 이 동안 Ctrl-C 는 듣지 않습니다)..." )
    stack_down
  fi
  # 스캔 도중 중단(INT·TERM)돼도 진행 로그의 URL 값을 가려 둔다 — 정상 경로는 run_zap 이 가린다 (3차 리뷰 R3-S4).
  # 스택을 내린 뒤에 가린다 — 죽어 가는 compose CLI 가 zap.log 에 마지막 줄을 쓰는 중에 다시 쓰지 않게 (4차 리뷰 R4-S3)
  if [ "$ZAP_LOG_REDACTED" -eq 0 ] && [ -f "$RAW/zap.log" ]; then
    python3 -I "$SEC_PLUGIN/scripts/lib/web_target.py" redact-file "$RAW/zap.log" 2>/dev/null || : >"$RAW/zap.log"
  fi
  if [ $STACK_UP -eq 1 ]; then
    ( sec_warn "ZAP 스택을 내리지 못했습니다 — docker compose -p $COMPOSE_PROJECT -f $COMPOSE_FILE_PATH --profile scan down -v 로 직접 지우세요." )
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cleanup_stale

save_proxy_log() {
  # 차단 목록은 프록시 로그에서만 알 수 있다 — 스택을 내리기 전에 받는다.
  # 로그를 받지 못했거나 tinyproxy 시작 줄이 없으면(빈 로그·다른 출력) 차단 목록을 만들지 않는다 → normalize 가
  # "없음" 대신 "읽지 못했습니다" 경고를 낸다 (PR #34 리뷰 W2)
  rm -f "$RAW/proxy-denied.json"
  compose logs --no-color --no-log-prefix egress-proxy >"$RAW/proxy.log" 2>/dev/null || return 0
  grep -q 'Initializing tinyproxy' "$RAW/proxy.log" || return 0
  python3 -I "$SEC_PLUGIN/scripts/lib/web_target.py" denied "$RAW/proxy.log" >"$RAW/proxy-denied.json" 2>/dev/null ||
    rm -f "$RAW/proxy-denied.json"
}

run_zap() {
  local rc iso
  sec_log "egress-proxy 기동 중 (허용 출처: $ORIGIN)..."
  STACK_UP=1
  if ! compose up -d --wait --wait-timeout 60 egress-proxy >"$RAW/compose-up.log" 2>&1; then
    compose logs --no-color --tail 40 egress-proxy >>"$RAW/compose-up.log" 2>/dev/null
    record zap failed - "egress-proxy 를 기동하지 못했습니다: $(tail_log "$RAW/compose-up.log")"
    stack_down
    return
  fi
  # 스캔 전에 격리를 실제로 확인한다 (V1 N2) — ZAP 컨테이너에서
  #   직접 이름 풀이·IP 연결·대상 직접 연결이 되면(프록시 우회) 중단, 프록시 변수가 남아 있으면 중단,
  #   프록시가 허용목록 밖 요청을 403 으로 막지 않으면(필터가 안 먹음) 중단한다.
  #   허용목록 밖 확인용 이름은 .invalid 라 프록시가 필터에서 막고 이름 풀이도 하지 않는다 (차단 목록에서는 뺀다)
  # 검사 내용은 scripts/lib/iso_probe.py (ZAP 컨테이너에 마운트가 없으므로 내용을 -c 로 넘긴다). 대상 host:port 직접 연결도 본다
  iso=$(compose --profile scan run --rm --no-deps -T --entrypoint python3 zap -I -c "$(cat "$SEC_PLUGIN/scripts/lib/iso_probe.py")" \
    "$ORIGIN_HOST" "$ORIGIN_PORT" "$TARGET_URL" 2>&1 | tail -n 1)
  case "$iso" in
    "UNREACHABLE timeout")
      # 서버는 떠 있을 수 있다 — 개발 서버 첫 요청 컴파일·콜드 스타트 (3차 리뷰 R3-S3)
      record zap failed - "대상이 55초 안에 응답하지 않았습니다 — 점검하지 않았습니다. 개발 서버라면 브라우저로 한 번 열어 첫 컴파일을 끝낸 뒤 다시 실행하세요 ($ORIGIN)"
      save_proxy_log
      stack_down
      return
      ;;
    "UNREACHABLE "*)
      # 격리는 정상 — 대상에 닿지 않을 뿐이다. 그대로 스캔하면 ZAP 이 프록시의 500 오류 페이지를 점검해 거짓 결과를 낸다 (2차 리뷰 W-B)
      record zap failed - "대상에 접속하지 못했습니다(${iso#UNREACHABLE }) — 점검하지 않았습니다. 서버가 떠 있는지, 허용목록의 포트·주소($ORIGIN)가 맞는지 확인하세요 (호스트의 개발 서버는 host.docker.internal 로 지정)"
      save_proxy_log
      stack_down
      return
      ;;
  esac
  if [ "$iso" != isolated ]; then
    record zap failed - "격리 확인 실패 — ZAP 컨테이너에서 프록시를 거치지 않는 통신·프록시 변수·필터 미적용이 확인됩니다(${iso:-확인 불가}). 대상에 요청하지 않았습니다. Docker 엔진 버전(예: CVE-2024-29018)·~/.docker/config.json 의 proxies·런타임 네트워크 설정을 확인하세요"
    save_proxy_log
    stack_down
    return
  fi
  sec_log "ZAP baseline 실행 중 (passive 규칙만 · 스파이더 ${DWK_SPIDER_MIN}분 · 최대 ${SCAN_TIMEOUT}초)..."
  # 백그라운드 + wait: 포그라운드면 TERM 이 와도 bash 가 compose run 이 끝날 때까지 trap 을 미룬다.
  # 시간 상한은 watchdog 이 스택을 내려서 건다 (macOS 에 timeout 명령이 없다)
  compose --profile scan run --rm --no-deps -T zap >"$RAW/zap.json" 2>"$RAW/zap.log" </dev/null &
  pid_scan=$!
  # watchdog 의 출력은 버린다 — sleep 이 stdout 을 쥐고 남으면 이 스크립트를 $(…) 로 부른 쪽이 끝나지 않는다.
  # 스캔이 먼저 끝나 TERM 을 받으면 sleep 도 함께 끝낸다 (서브셸만 죽이면 sleep 이 고아로 남는다)
  (
    exec >/dev/null 2>&1
    # trap 을 sleep 보다 먼저 걸고, 변수 대신 작업 목록으로 끝낸다 — sleep 직후 s=$! 전에 TERM 이 와도 고아를 남기지 않는다
    # (1차 리뷰 S6·2차 리뷰 S-C)
    # shellcheck disable=SC2046  # 작업 pid 목록 — 공백 없는 값이다
    trap 'kill $(jobs -p) 2>/dev/null; exit 0' TERM
    sleep "$SCAN_TIMEOUT" &
    wait $! || exit 0
    : >"$RAW/zap.timeout"
    # compose run 이 띄운 일회성 컨테이너도 서비스 라벨은 zap 이다 — 프록시는 남겨 차단 로그를 받는다
    # shellcheck disable=SC2046  # 컨테이너 id 목록 — 공백 없는 값이다
    docker kill $(docker ps -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT" \
      --filter label=com.docker.compose.service=zap 2>/dev/null) >/dev/null 2>&1
  ) &
  pid_watchdog=$!
  wait "$pid_scan"
  rc=$?
  pid_scan=""
  kill "$pid_watchdog" 2>/dev/null
  wait "$pid_watchdog" 2>/dev/null
  pid_watchdog=""
  save_proxy_log
  # 진행 로그에는 크롤링한 URL(질의값 포함)이 찍힌다 — 실패 메모가 이 꼬리에서 만들어지므로 먼저 가린다 (2차 리뷰 W-A·S-B)
  python3 -I "$SEC_PLUGIN/scripts/lib/web_target.py" redact-file "$RAW/zap.log" 2>/dev/null || : >"$RAW/zap.log"
  ZAP_LOG_REDACTED=1
  # 스캔 도중 대상 접속이 끊긴 요청 — 결과가 일부 페이지만 반영됐을 수 있다
  local lost
  lost=$(grep -c "Could not establish a connection to $ORIGIN_HOST:$ORIGIN_PORT\$" "$RAW/proxy.log" 2>/dev/null)
  case "$lost" in '' | 0 | *[!0-9]*) ;; *)
    printf '%s\n' "점검 중 대상($ORIGIN)에 접속하지 못한 요청이 ${lost}건 있습니다 — 그 페이지는 프록시 오류 페이지로 점검됐을 수 있습니다. 서버가 중간에 멈추지 않았는지 확인하세요" >>"$WARNINGS_FILE" ;;
  esac
  # zap-baseline.py 종료코드: 0 통과 · 1 FAIL 규칙 · 2 WARN(-I 면 0) · 3 그 밖의 오류
  if [ -f "$RAW/zap.timeout" ]; then
    record zap failed "$rc" "시간 상한(${SCAN_TIMEOUT}초)을 넘어 중단했습니다 — 결과가 일부만 있을 수 있어 리포트에 넣지 않았습니다"
    : >"$RAW/zap.json"
  elif [ "$rc" -le 2 ] && [ -s "$RAW/zap.json" ]; then
    record zap ok "$rc" ""
  else
    local note
    note=$(grep -v '^[[:space:]]*$' "$RAW/zap.log" | tail -n 3 | tr '\n\t' '  ' | cut -c1-280)
    [ "$rc" = 137 ] && note="ZAP 이 메모리 상한(3GB)·VM 메모리 부족으로 강제 종료됐을 수 있습니다. $note"
    record zap failed "$rc" "${note:-출력 없음}"
  fi
  rm -f "$RAW/zap.timeout"
  stack_down
}

run_zap

find "$SEC_RUN_DIR" -type f -exec chmod 600 {} + 2>/dev/null
find "$SEC_RUN_DIR" -type d -exec chmod 700 {} + 2>/dev/null

META_IN="$RAW/meta-in.json"
# 로컬 빌드 이미지(egress-proxy)는 images.lock 에 없다 — 이름·Dockerfile 의 tinyproxy 버전·베이스 태그·이미지 ID 를 넘긴다
PROXY_TOOL=$(printf '%s\t%s\t%s\t%s' egress-proxy dwk-security/egress-proxy \
  "$(sed -n 's/^ARG TINYPROXY_VERSION=//p' "$SEC_PLUGIN/docker/egress-proxy/Dockerfile")+alpine$(sec_image_field egress-proxy-base tag)" \
  "$IMG_PROXY")
# shellcheck disable=SC2086
python3 - "$META_IN" "$STARTED_AT" "$SEC_DOCKER_CONTEXT" "$SEC_IMAGES_LOCK" \
  "$SEC_PLUGIN/.claude-plugin/plugin.json" "$WARNINGS_FILE" "$PROXY_TOOL" $TOOLS <<'PY'
import json, sys
out, started, ctx, lock, plugin_json, warn_file, built, *tools = sys.argv[1:]
images = {}
with open(lock, encoding="utf-8") as f:
    for line in f:
        p = line.split()
        if len(p) == 5 and not p[0].startswith("#"):
            images[p[0]] = {"name": p[0], "image": p[1], "tag": p[2], "digest": p[3]}
for line in built.splitlines():
    p = line.split("\t")
    if len(p) == 4:
        images[p[0]] = {"name": p[0], "image": p[1], "tag": p[2], "digest": p[3]}
try:
    version = json.load(open(plugin_json, encoding="utf-8")).get("version")
except Exception:
    version = None
warnings = [l.strip() for l in open(warn_file, encoding="utf-8") if l.strip()]
json.dump({
    "started_at": started, "docker_context": ctx, "plugin_version": version,
    "tools": [images[t] for t in tools if t in images], "rules": [], "warnings": warnings,
}, open(out, "w", encoding="utf-8"), ensure_ascii=False)
PY

if ! python3 -I "$SEC_PLUGIN/scripts/normalize.py" --run-dir "$SEC_RUN_DIR" --kind web \
  --target "$DISPLAY_URL" --meta-json "$META_IN" 2>>"$SEC_LOG_FILE"; then
  sec_die "리포트 정규화 실패 — $SEC_LOG_FILE 확인"
fi

failed=$(awk -F '\t' '$2 == "failed" { printf "%s ", $1 }' "$STATUS")
[ -n "$failed" ] && sec_warn "실패한 도구: $failed(summary.md 의 '실행 오류' 참조)"
sec_log "완료. 요약: $SEC_RUN_DIR/summary.md"
find "$SEC_RUN_DIR" -type f ! -perm 600 -exec chmod 600 {} + 2>/dev/null
printf '%s\n' "$SEC_RUN_DIR/summary.md"
