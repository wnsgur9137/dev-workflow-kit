# shellcheck shell=bash
# scan-web.sh 테스트
#   - 가짜 docker: 인자 거부·허용목록 거부(V3 — Docker 를 전혀 부르지 않음), D6, 격리 확인 실패·프록시 기동 실패 기록,
#     정상 경로(프록시 설정·차단 목록·리포트), 오래된 스택 정리
#   - 실제 Docker(통합): V1 N2(허용목록 밖 403 + 로그, 프록시 우회 불가, 필터의 '-' 호스트), 대상 서버 baseline 기준선
#     zap·egress-proxy 이미지가 없으면 건너뛴다 (update.sh 를 먼저 실행).

SCAN_WEB="$PLUGIN_DIR/scripts/scan-web.sh"

setup_web_fake() {
  export HOME="$SEC_TMP/home"
  mkdir -p "$HOME"
  export DWK_SECURITY_DATA_DIR="$HOME/.local/share/dev-workflow-kit/security"
  export DWK_SECURITY_CONF_DIR="$HOME/.config/dev-workflow-kit/security"
  mkdir -p "$DWK_SECURITY_CONF_DIR" "$SEC_TMP/bin"
  printf 'http://host.docker.internal:3000   # 개발 서버\nhttps://staging.example.invalid  # prod\n' \
    >"$DWK_SECURITY_CONF_DIR/targets.allowlist"
  chmod 600 "$DWK_SECURITY_CONF_DIR/targets.allowlist"
  cp "$TESTS_DIR/lib/fake-docker" "$SEC_TMP/bin/docker"
  export PATH="$SEC_TMP/bin:$PATH"
  export FAKE_LOG="$SEC_TMP/docker.log"
  : >"$FAKE_LOG"
  FAKE_IMAGES=$(awk '!/^[[:space:]]*(#|$)/ { printf "%s@%s ", $2, $4 }' "$PLUGIN_DIR/docker/images.lock")
  # egress-proxy 는 update.sh 가 로컬에서 빌드한다 (이슈 #35) — 지금 Dockerfile·베이스와 맞는 빌드 기록과 그 ID 의 이미지를 둔다
  FAKE_PROXY_ID="sha256:$(printf 'e%.0s' $(seq 64))"
  export FAKE_BUILD_STATE="$SEC_TMP/build.state"
  web_fake_built_proxy "$FAKE_PROXY_ID"
  export FAKE_IMAGES FAKE_PROXY_ID
}

# web_fake_built_proxy <이미지 ID> [입력] — $DWK_SECURITY_DATA_DIR 에 egress-proxy 빌드 기록을 쓰고, 가짜 docker 에 그 ID 의 이미지를
# 지금 입력 라벨로 둔다 (입력 기본값: 지금 빌드 문맥·베이스)
web_fake_built_proxy() {
  local input=${2:-} current
  # shellcheck disable=SC1091
  current=$(. "$PLUGIN_DIR/scripts/lib/common.sh" && sec_build_input egress-proxy) || fail "빌드 입력 계산 실패"
  mkdir -p "$DWK_SECURITY_DATA_DIR/data/images"
  # shellcheck disable=SC2031  # input 은 이 함수의 인자다
  printf '%s %s\n' "${input:-$current}" "$1" >"$DWK_SECURITY_DATA_DIR/data/images/egress-proxy.built"
  echo "dwk-security/egress-proxy:${current:0:12} $1 $current 1.11.3-r0+alpine3.24.2" >"$FAKE_BUILD_STATE"
}

# 실제 Docker 테스트가 데이터 폴더를 임시 폴더로 바꿀 때, 사용자가 update.sh 로 만든 빌드 기록을 옮겨 온다
web_copy_built_records() {
  mkdir -p "$DWK_SECURITY_DATA_DIR/data/images"
  cp "$REAL_SEC_DATA/data/images/"*.built "$DWK_SECURITY_DATA_DIR/data/images/" || fail "빌드 기록을 옮기지 못함"
}

no_docker_called() {
  [ ! -s "$FAKE_LOG" ] || fail "docker 가 호출됨: $(head -n 1 "$FAKE_LOG")"
}

test_web_rejects_options_and_extra_args_without_docker() {
  setup_web_fake
  assert_status 2 "$SCAN_WEB" --full-scan http://host.docker.internal:3000/
  assert_contains "$OUT" "알 수 없는 옵션"
  assert_status 2 "$SCAN_WEB" http://host.docker.internal:3000/ -z
  assert_status 2 "$SCAN_WEB" http://host.docker.internal:3000/ http://host.docker.internal:3000/a
  assert_contains "$OUT" "하나만"
  assert_status 2 "$SCAN_WEB"
  no_docker_called
}

# V3: 허용목록 밖 URL 은 스크립트가 거부하고 컨테이너를 띄우지 않는다 (Docker 자체를 부르지 않는다)
test_web_allowlist_refusals_happen_before_docker() {
  setup_web_fake
  assert_status 1 "$SCAN_WEB" http://example.com/
  assert_contains "$OUT" "허용목록에 없는 대상"
  # 같은 호스트의 다른 포트·scheme 도 다른 대상이다
  assert_status 1 "$SCAN_WEB" http://host.docker.internal:3001/
  assert_status 1 "$SCAN_WEB" https://host.docker.internal:3000/
  # prod 표시
  assert_status 1 "$SCAN_WEB" https://staging.example.invalid/
  assert_contains "$OUT" "운영(prod)"
  # localhost 는 컨테이너 자신 — 호스트 주소 안내
  assert_status 1 "$SCAN_WEB" http://localhost:3000/
  assert_contains "$OUT" "host.docker.internal"
  # 사용자 정보로 호스트 비교를 속이지 못한다 — 허용된 호스트가 '@' 뒤에 와도 거부 (리뷰 NITPICK)
  assert_status 1 "$SCAN_WEB" 'http://evil.example@host.docker.internal:3000/'
  assert_contains "$OUT" "사용자 정보"
  # 허용목록을 다른 사용자가 쓸 수 있으면 거부
  chmod 666 "$DWK_SECURITY_CONF_DIR/targets.allowlist"
  assert_status 1 "$SCAN_WEB" http://host.docker.internal:3000/
  assert_contains "$OUT" "chmod 600"
  # 허용목록이 없으면 만드는 방법을 안내한다 (스크립트가 만들지 않는다)
  rm -f "$DWK_SECURITY_CONF_DIR/targets.allowlist"
  assert_status 1 "$SCAN_WEB" http://host.docker.internal:3000/
  assert_contains "$OUT" "허용목록이 없습니다"
  [ ! -e "$DWK_SECURITY_CONF_DIR/targets.allowlist" ] || fail "스크립트가 허용목록을 만듦"
  no_docker_called
  [ ! -d "$DWK_SECURITY_DATA_DIR/reports" ] || [ -z "$(ls -A "$DWK_SECURITY_DATA_DIR/reports")" ] || fail "리포트 폴더가 생김"
}

test_web_d6_missing_zap_image_points_to_update() {
  setup_web_fake
  FAKE_IMAGES=$(awk '!/^[[:space:]]*(#|$)/ && $1 != "zap" { printf "%s@%s ", $2, $4 }' "$PLUGIN_DIR/docker/images.lock")
  assert_status 1 "$SCAN_WEB" http://host.docker.internal:3000/
  assert_contains "$OUT" "[D6]"
  assert_contains "$OUT" "zaproxy/zap-stable@sha256:"
  assert_contains "$OUT" "update.sh"
  if grep -q '^docker run' "$FAKE_LOG" || compose_calls up >/dev/null || compose_calls run >/dev/null; then fail "컨테이너가 기동됨"; fi
}

# 이슈 #35: egress-proxy 빌드 기록이 없거나·지금 Dockerfile·베이스와 다르거나·그 ID 의 이미지가 없으면 스캔하지 않고 update.sh 를 안내한다
test_web_d6_proxy_build_record_missing_stale_or_gone() {
  setup_web_fake
  rm -f "$DWK_SECURITY_DATA_DIR/data/images/egress-proxy.built"
  assert_status 1 "$SCAN_WEB" http://host.docker.internal:3000/
  assert_contains "$OUT" "egress-proxy — 로컬 빌드 기록이 없습니다"
  assert_contains "$OUT" "update.sh"
  web_fake_built_proxy "$FAKE_PROXY_ID" "$(printf '0%.0s' $(seq 64))"
  assert_status 1 "$SCAN_WEB" http://host.docker.internal:3000/
  assert_contains "$OUT" "이 바뀌어 다시 빌드해야 합니다"
  web_fake_built_proxy "$FAKE_PROXY_ID"
  : >"$FAKE_BUILD_STATE"
  assert_status 1 "$SCAN_WEB" http://host.docker.internal:3000/
  assert_contains "$OUT" "빌드한 이미지($FAKE_PROXY_ID)가 없습니다"
  # PR #37 리뷰 W1: 기록이 다른 로컬 이미지(예: 남은 kalaksi/tinyproxy)를 가리키면 라벨이 달라 쓰지 않는다
  FAKE_IMAGES="$FAKE_IMAGES $FAKE_PROXY_ID" assert_status 1 "$SCAN_WEB" http://host.docker.internal:3000/
  assert_contains "$OUT" "지금 빌드 입력으로 만든 것이 아닙니다"
  assert_contains "$OUT" "update.sh --images"
  if grep -q '^docker build\|^docker pull' "$FAKE_LOG" || compose_calls up >/dev/null || compose_calls run >/dev/null; then
    fail "스캔이 빌드·다운로드하거나 컨테이너를 띄움"
  fi
}

_web_scan() {
  local summary
  summary=$("$SCAN_WEB" "${1:-http://host.docker.internal:3000/}" 2>"$SEC_TMP/scan.err" | tail -n 1)
  [ -f "$summary" ] || fail "summary 없음: $(tail -n 5 "$SEC_TMP/scan.err")"
  WEB_RUN=$(dirname "$summary")
}

test_web_isolation_leak_stops_before_scanning_target() {
  setup_web_fake
  FAKE_COMPOSE_ISO_OUTPUT="LEAK dns:example.com proxy-allows-outside" _web_scan
  assert_contains "$(awk -F '\t' '$1 == "zap"' "$WEB_RUN/raw/status.tsv")" "격리 확인 실패"
  assert_contains "$(cat "$WEB_RUN/raw/status.tsv")" "proxy-allows-outside"
  # 격리 확인은 대상 host:port 직접 연결도 본다 — 출처의 호스트·포트를 인자로 넘긴다 (리뷰 W4)
  grep -q 'host\.docker\.internal 3000 http://host\.docker\.internal:3000/$' "$FAKE_LOG" ||
    fail "격리 확인에 대상 host·port·시작 URL 이 넘어가지 않음"
  # 대상에 요청하는 ZAP run(진입점 덮어쓰기 없는 run)은 호출되지 않는다
  if compose_calls run | grep -vq -- '--entrypoint python3'; then fail "격리 실패 뒤 스캔이 실행됨"; fi
  grep -q '^docker compose -p dwk-sec-web-[0-9a-f]\{12\} .* down -v' "$FAKE_LOG" || fail "down -v 가 호출되지 않음"
  assert_contains "$(cat "$WEB_RUN/summary.md")" "| zap | failed |"
}

test_web_proxy_start_failure_is_recorded_and_stack_removed() {
  setup_web_fake
  FAKE_COMPOSE_UP_RC=1 _web_scan
  assert_contains "$(awk -F '\t' '$1 == "zap"' "$WEB_RUN/raw/status.tsv")" "egress-proxy 를 기동하지 못했습니다"
  assert_not_contains "$(cat "$FAKE_LOG")" "--entrypoint python3"
  grep -q ' down -v' "$FAKE_LOG" || fail "down -v 가 호출되지 않음"
  assert_contains "$(cat "$WEB_RUN/summary.md")" "| zap | failed |"
  # 차단 기록이 없다는 사실이 "없음"으로 감춰지지 않는다
  assert_contains "$(cat "$WEB_RUN/summary.md")" "프록시 차단 기록을 읽지 못했습니다"
}

test_web_success_path_builds_report_with_blocked_requests() {
  setup_web_fake
  cat >"$SEC_TMP/zap.json" <<'EOF'
{"site": [{"@name": "http://host.docker.internal:3000", "alerts": [
  {"pluginid": "10038", "alertRef": "10038-1", "alert": "Content Security Policy (CSP) Header Not Set", "riskcode": "2",
   "confidence": "3", "cweid": "693", "count": "1", "solution": "<p>set CSP</p>", "reference": "",
   "instances": [{"uri": "http://host.docker.internal:3000/", "method": "GET", "param": "", "evidence": ""}]}]}]}
EOF
  cat >"$SEC_TMP/proxy.log" <<'EOF'
NOTICE    Nov 17 05:33:16.110 [1]: Initializing tinyproxy ...
NOTICE    Nov 17 05:33:18.812 [1]: Proxying refused on filtered url "http://dwk-isolation-probe.invalid/"
NOTICE    Nov 17 05:33:19.000 [1]: Proxying refused on filtered url "http://cdn.example/a.js?token=abc123"
EOF
  FAKE_COMPOSE_RUN_FILE="$SEC_TMP/zap.json" FAKE_COMPOSE_LOGS_FILE="$SEC_TMP/proxy.log" _web_scan
  assert_eq "$(cat "$WEB_RUN/raw/status.tsv")" "$(printf 'zap\tok\t0\t')"
  local s
  s=$(cat "$WEB_RUN/summary.md")
  assert_contains "$(cat "$WEB_RUN/findings.json")" '"rule_id": "zap.10038-1"'
  assert_contains "$s" "http://cdn.example/a.js?token=[MASKED]"
  assert_not_contains "$s" "abc123"
  assert_not_contains "$s" "dwk-isolation-probe"
  assert_contains "$s" "egress-proxy: \`1.11.3-r0+alpine3.24.2\` (로컬 빌드 \`sha256:eeeeeeeeeeee"
  assert_contains "$(cat "$WEB_RUN/meta.json")" '"source": "local-build"'
  assert_contains "$(cat "$WEB_RUN/meta.json")" '"base": "alpine@sha256:294b683c' 
  # 리포트 메타의 프록시 이미지는 빌드 기록의 이미지 ID 다 (태그는 다른 빌드가 덮어쓸 수 있어 쓰지 않는다)
  assert_contains "$(cat "$WEB_RUN/meta.json")" "\"digest\": \"$FAKE_PROXY_ID\""
  # 프록시 설정·필터는 실행마다 환경변수로 넘긴다 — 이번 대상의 출처 하나만 연다
  grep -q '^docker compose -p dwk-sec-web-[0-9a-f]\{12\} -f .*/docker/compose-web.yml up -d --wait' "$FAKE_LOG" ||
    fail "egress-proxy up 이 호출되지 않음"
  grep -q ' down -v' "$FAKE_LOG" || fail "down -v 가 호출되지 않음"
  # 리포트는 데이터 폴더 아래에만, 권한 600
  case "$WEB_RUN" in "$DWK_SECURITY_DATA_DIR/reports/"*) ;; *) fail "리포트 위치: $WEB_RUN" ;; esac
  assert_eq "$(file_mode "$WEB_RUN/summary.md")" 600
}

# 2차 리뷰 W-B: 대상에 닿지 않으면 스캔하지 않는다 (ZAP 이 프록시 오류 페이지를 점검해 거짓 결과를 내지 않게)
test_web_unreachable_target_is_failed_without_scanning() {
  setup_web_fake
  FAKE_COMPOSE_ISO_OUTPUT="UNREACHABLE proxy-500" _web_scan
  assert_contains "$(awk -F '\t' '$1 == "zap"' "$WEB_RUN/raw/status.tsv")" "대상에 접속하지 못했습니다(proxy-500)"
  if compose_calls run | grep -vq -- '--entrypoint python3'; then fail "접속 불가인데 스캔이 실행됨"; fi
  grep -q ' down -v' "$FAKE_LOG" || fail "down -v 가 호출되지 않음"
  assert_contains "$(cat "$WEB_RUN/summary.md")" "| zap | failed |"
}

# 2차 리뷰 W-B: 스캔 도중 대상 접속이 끊긴 요청은 경고로 드러난다
test_web_lost_target_connections_warn() {
  setup_web_fake
  printf '{"site": []}' >"$SEC_TMP/zap.json"
  printf 'NOTICE x: Initializing tinyproxy ...\nERROR x: opensock: Could not establish a connection to host.docker.internal:3000\nERROR x: opensock: Could not establish a connection to host.docker.internal:3000\n' >"$SEC_TMP/proxy.log"
  FAKE_COMPOSE_RUN_FILE="$SEC_TMP/zap.json" FAKE_COMPOSE_LOGS_FILE="$SEC_TMP/proxy.log" _web_scan
  assert_contains "$(cat "$WEB_RUN/summary.md")" "접속하지 못한 요청이 2건"
}

# 2차 리뷰 W-A·S-B: ZAP 진행 로그(실패 메모의 출처)의 URL 값도 가린다
test_web_failure_note_and_zap_log_are_redacted() {
  setup_web_fake
  printf 'Using the Automation Framework\nJob spider error accessing URL http://host.docker.internal:3000/cb?code=QQLOG42 status code returned : 500 expected 200\n' >"$SEC_TMP/zap.err"
  printf 'Initializing tinyproxy ...\n' >"$SEC_TMP/proxy.log"
  FAKE_COMPOSE_RUN_RC=3 FAKE_COMPOSE_RUN_STDERR_FILE="$SEC_TMP/zap.err" FAKE_COMPOSE_LOGS_FILE="$SEC_TMP/proxy.log" _web_scan
  assert_contains "$(awk -F '\t' '$1 == "zap"' "$WEB_RUN/raw/status.tsv")" "cb?code=[MASKED]"
  if grep -rq QQLOG42 "$WEB_RUN"; then fail "진행 로그의 질의값이 남음: $(grep -rl QQLOG42 "$WEB_RUN" | head -n 3)"; fi
}

# 2차 리뷰 S-D: 프록시 로그 수집 명령이 실패하면(시작 줄이 있어도) 차단 목록을 만들지 않는다
test_web_proxy_log_command_failure_is_not_reported_as_none() {
  setup_web_fake
  printf 'NOTICE x: Initializing tinyproxy ...\n' >"$SEC_TMP/proxy.log"
  FAKE_COMPOSE_LOGS_RC=1 FAKE_COMPOSE_LOGS_FILE="$SEC_TMP/proxy.log" _web_scan
  assert_contains "$(cat "$WEB_RUN/summary.md")" "프록시 차단 기록을 읽지 못했습니다"
}

# 리뷰 W1: 점검 URL 의 질의 문자열·조각 값은 로그·리포트에 남지 않는다 (ZAP 에는 원문이 간다)
test_web_target_query_is_redacted_in_logs_and_report() {
  setup_web_fake
  printf '%s\n' "$(printf 'Initializing tinyproxy ...')" >"$SEC_TMP/proxy.log"
  FAKE_COMPOSE_LOGS_FILE="$SEC_TMP/proxy.log" _web_scan 'http://host.docker.internal:3000/cb?code=QQTOKEN77#QQFRAG88'
  if grep -rq 'QQTOKEN77\|QQFRAG88' "$WEB_RUN" "$SEC_TMP/scan.err"; then
    fail "점검 URL 의 값이 남음: $(grep -rl 'QQTOKEN77\|QQFRAG88' "$WEB_RUN" "$SEC_TMP/scan.err" | head -n 3)"
  fi
  # 조각은 점검 URL 을 만들 때 버린다 (ZAP 에도 넘기지 않는다)
  assert_contains "$(cat "$WEB_RUN/summary.md")" "\`http://host.docker.internal:3000/cb?code=[MASKED]\`"
}

# 리뷰 W2: 프록시 로그를 받지 못하면 "막은 요청 없음" 이 아니라 경고로 드러난다
test_web_unreadable_proxy_log_is_not_reported_as_none() {
  setup_web_fake
  : >"$SEC_TMP/empty.log"
  FAKE_COMPOSE_LOGS_FILE="$SEC_TMP/empty.log" _web_scan
  assert_contains "$(cat "$WEB_RUN/summary.md")" "프록시 차단 기록을 읽지 못했습니다"
  assert_not_contains "$(cat "$WEB_RUN/summary.md")" "## 프록시가 막은 요청"
  [ ! -e "$WEB_RUN/raw/proxy-denied.json" ] || fail "빈 로그로 차단 목록이 만들어짐"
}

# 가짜 docker 의 장시간 run(sleep)을 정리한다 — run.sh 의 EXIT trap 이 부른다(판정이 실패해 exit 해도, 이슈 #36 R8-N2).
# 테스트에서 trap 을 직접 걸면 run.sh 의 SEC_TMP 정리를 덮어쓴다 (PR #45 리뷰 W1)
sec_test_cleanup() {
  local p
  [ -f "${FAKE_RUN_PIDFILE:-}" ] && while read -r p; do kill "$p" 2>/dev/null; done <"$FAKE_RUN_PIDFILE"
  return 0
}

# 리뷰 W3: 중단 신호에도 스택을 내린다 (trap)
test_web_term_during_scan_removes_stack() {
  setup_web_fake
  export FAKE_COMPOSE_RUN_SLEEP=30 FAKE_RUN_PIDFILE="$SEC_TMP/run.pids"
  local pid rc start
  "$SCAN_WEB" http://host.docker.internal:3000/ >/dev/null 2>"$SEC_TMP/scan.err" &
  pid=$!
  for _ in $(seq 1 50); do grep -q ' run --rm --no-deps -T zap' "$FAKE_LOG" 2>/dev/null && break; sleep 0.2; done
  start=$(date +%s)
  kill -TERM "$pid"
  wait "$pid"
  rc=$?
  assert_eq "$rc" 143 "(TERM 종료코드)"
  [ $(($(date +%s) - start)) -le 5 ] || fail "TERM 뒤 정리에 5초 넘게 걸림"
  grep -q ' down -v' "$FAKE_LOG" || fail "TERM 뒤 down -v 가 호출되지 않음"
  return 0
}

# 7차 리뷰 R7-W1: '… 2>&1 | tee' 로 실행하다 Ctrl-C 로 파이프가 닫혀도 정리(스택 내리기)를 끝까지 한다
#   (정리 안내 printf 의 SIGPIPE 가 셸을 죽이면 down -v 가 호출되지 않는다)
test_web_term_with_closed_stderr_pipe_still_cleans_up() {
  setup_web_fake
  export FAKE_COMPOSE_RUN_SLEEP=30 FAKE_RUN_PIDFILE="$SEC_TMP/run.pids"
  local pid rc rpid fifo="$SEC_TMP/err.fifo"
  mkfifo "$fifo"
  cat "$fifo" >/dev/null &
  rpid=$!
  "$SCAN_WEB" http://host.docker.internal:3000/ >/dev/null 2>"$fifo" &
  pid=$!
  for _ in $(seq 1 50); do grep -q ' run --rm --no-deps -T zap' "$FAKE_LOG" 2>/dev/null && break; sleep 0.2; done
  kill "$rpid"
  wait "$rpid" 2>/dev/null
  kill -TERM "$pid"
  wait "$pid"
  rc=$?
  grep -q ' down -v' "$FAKE_LOG" || fail "파이프가 닫힌 뒤 TERM 에 down -v 가 호출되지 않음 (rc=$rc)"
  assert_eq "$rc" 143 "(TERM 종료코드)"
  return 0
}

# 이슈 #36 (PR #37 2차 R2-N2): 버전 라벨이 없으면 summary 에 unknown 으로 보인다
test_web_missing_proxy_version_label_is_unknown() {
  setup_web_fake
  local input
  input=$(awk '{print $3}' "$FAKE_BUILD_STATE")
  echo "dwk-security/egress-proxy:x $FAKE_PROXY_ID $input" >"$FAKE_BUILD_STATE"
  printf '{"site":[]}' >"$SEC_TMP/zap.json"
  FAKE_COMPOSE_RUN_FILE="$SEC_TMP/zap.json" _web_scan
  assert_contains "$(cat "$WEB_RUN/summary.md")" "egress-proxy: \`unknown\`"
  # 라벨에 탭·줄바꿈이 있어도 메타 항목이 깨져 빠지지 않는다
  FAKE_VERSION_LABEL=$(printf '1.0\tx\ny') FAKE_COMPOSE_RUN_FILE="$SEC_TMP/zap.json" _web_scan
  assert_contains "$(cat "$WEB_RUN/summary.md")" "egress-proxy: \`1.0xy\`"
}

# 이슈 #36 (PR #34 8차 R8-N3): 파이프가 닫히고 스택 내리기까지 실패해도 진행 로그는 가리고, 경고는 run.log 에 남는다
test_web_closed_pipe_and_failed_down_still_redact_and_log() {
  setup_web_fake
  export FAKE_COMPOSE_RUN_SLEEP=30 FAKE_RUN_PIDFILE="$SEC_TMP/run.pids" FAKE_COMPOSE_DOWN_RC=1
  export FAKE_COMPOSE_RUN_STDERR_FILE="$SEC_TMP/zap-progress.log"
  printf 'Job spider error accessing URL http://host.docker.internal:3000/cb?code=SECRETQ1 status code returned : 500\n' >"$FAKE_COMPOSE_RUN_STDERR_FILE"
  local pid rc rpid fifo="$SEC_TMP/err.fifo" run
  mkfifo "$fifo"
  cat "$fifo" >/dev/null &
  rpid=$!
  "$SCAN_WEB" http://host.docker.internal:3000/ >/dev/null 2>"$fifo" &
  pid=$!
  for _ in $(seq 1 50); do grep -q ' run --rm --no-deps -T zap' "$FAKE_LOG" 2>/dev/null && break; sleep 0.2; done
  sleep 0.5
  kill "$rpid"
  wait "$rpid" 2>/dev/null
  kill -TERM "$pid"
  wait "$pid"
  rc=$?
  assert_eq "$rc" 143 "(TERM 종료코드)"
  run=$(find "$DWK_SECURITY_DATA_DIR/reports" -mindepth 1 -maxdepth 1 -type d -name '*-web' | sort | tail -n 1)
  [ -n "$run" ] || fail "실행 폴더 없음"
  grep -q 'code=\[MASKED\]' "$run/raw/zap.log" || fail "zap.log 가 가려지지 않음: $(cat "$run/raw/zap.log")"
  if grep -q 'SECRETQ1' "$run/raw/zap.log"; then fail "zap.log 에 질의값이 남음"; fi
  assert_contains "$(cat "$run/run.log")" "ZAP 스택을 내리지 못했습니다"
  return 0
}

# 리뷰 W3: 시간 상한을 넘으면 ZAP 을 끄고 실패로 기록한다 (결과를 리포트에 넣지 않는다)
test_web_scan_timeout_is_recorded_as_failure() {
  setup_web_fake
  export FAKE_COMPOSE_RUN_SLEEP=8 FAKE_RUN_PIDFILE="$SEC_TMP/run.pids"
  printf '{"site": []}' >"$SEC_TMP/zap.json"
  local start
  start=$(date +%s)
  # 가짜 docker kill 은 아무것도 하지 않으므로 run 은 8초 뒤 스스로 끝난다 — 그 사이 watchdog(2초)이 시간 초과를 표시한다
  DWK_SEC_TEST_SCAN_TIMEOUT=2 FAKE_COMPOSE_RUN_FILE="$SEC_TMP/zap.json" _web_scan
  assert_contains "$(awk -F '\t' '$1 == "zap"' "$WEB_RUN/raw/status.tsv")" "시간 상한(2초)"
  grep -q '^docker kill\|^docker ps -q --filter label=com.docker.compose.project=dwk-sec-web-' "$FAKE_LOG" ||
    fail "시간 초과 뒤 ZAP 컨테이너를 끄지 않음"
  # 테스트 전용 상한이 적용됐다는 사실이 리포트에 남는다 (2차 리뷰 S-E)
  assert_contains "$(cat "$WEB_RUN/summary.md")" "테스트 전용 시간 상한(2초"
  local p
  [ -f "$FAKE_RUN_PIDFILE" ] && while read -r p; do kill "$p" 2>/dev/null; done <"$FAKE_RUN_PIDFILE"
  [ $(($(date +%s) - start)) -le 20 ] || fail "시간 초과 경로가 너무 오래 걸림"
}

test_web_test_timeout_cannot_raise_limit() {
  setup_web_fake
  DWK_SEC_TEST_SCAN_TIMEOUT=999999 _web_scan
  assert_contains "$(cat "$SEC_TMP/scan.err")" "최대 1800초"
  assert_not_contains "$(cat "$WEB_RUN/summary.md")" "테스트 전용 시간 상한"
}

test_web_prod_like_host_warns() {
  setup_web_fake
  printf 'http://api.prod.example.invalid:8080\n' >>"$DWK_SECURITY_CONF_DIR/targets.allowlist"
  _web_scan 'http://api.prod.example.invalid:8080/'
  assert_contains "$(cat "$WEB_RUN/summary.md")" "prod 가 들어 있습니다"
}

test_web_proxy_config_and_filter_are_derived_from_target() {
  setup_web_fake
  # 가짜 docker 가 compose 에 넘어온 환경변수를 기록하게 한다
  cat >"$SEC_TMP/bin/docker" <<EOF
#!/usr/bin/env bash
case "\$*" in *" up "*) { printf 'CONF<<%s>>\n' "\$DWK_PROXY_CONF"; printf 'FILTER<<%s>>\n' "\$DWK_PROXY_FILTER";
  printf 'URL<<%s>>\n' "\$DWK_TARGET_URL"; } >>"$SEC_TMP/env.log" ;; esac
exec "$TESTS_DIR/lib/fake-docker" "\$@"
EOF
  chmod +x "$SEC_TMP/bin/docker"
  printf 'https://staging.example.invalid:8443\n' >>"$DWK_SECURITY_CONF_DIR/targets.allowlist"
  _web_scan 'http://HOST.docker.internal:3000/app?x=1'
  local env
  env=$(cat "$SEC_TMP/env.log")
  assert_contains "$env" 'FILTER<<^http://host\.docker\.internal:3000(/|$)>>'
  assert_contains "$env" 'URL<<http://host.docker.internal:3000/app?x=1>>'
  assert_contains "$env" "FilterDefaultDeny Yes"
  assert_contains "$env" "ConnectPort 1"
  : >"$SEC_TMP/env.log"
  _web_scan 'https://staging.example.invalid:8443/'
  env=$(cat "$SEC_TMP/env.log")
  assert_contains "$env" 'FILTER<<^staging\.example\.invalid:8443$>>'
  assert_contains "$env" "ConnectPort 8443"
}

test_web_cleanup_stale_only_removes_old_web_stacks() {
  setup_web_fake
  cat >"$SEC_TMP/inspect.txt" <<'EOF'
dwk-sec-web-0000000000aa 2029-12-31T20:00:00Z
dwk-sec-web-0000000000bb 2030-01-01T11:30:00+09:00
dwk-sec-app-0000000000cc 2029-01-01T00:00:00Z
dwk-sec-web-0000000000dd
dwk-sec-web-0000000000dd 2020-01-01T00:00:00Z
EOF
  # 컨테이너 없이 네트워크만 남은 프로젝트도 지운다 (리뷰 S5)
  printf 'dwk-sec-web-0000000000ee 2029-12-30T00:00:00Z\n' >"$SEC_TMP/networks.txt"
  FAKE_NETWORKS="n1" FAKE_NETWORK_LINES="$SEC_TMP/networks.txt" \
    FAKE_SYSTEM_TIME="2030-01-01T12:00:00+09:00" FAKE_PS_IDS="c1 c2 c3" FAKE_INSPECT_LINES="$SEC_TMP/inspect.txt" _web_scan
  local downs
  downs=$(grep ' down ' "$FAKE_LOG")
  assert_contains "$downs" "dwk-sec-web-0000000000aa"
  assert_not_contains "$downs" "dwk-sec-web-0000000000bb"     # 30분 전 — 다른 실행일 수 있다
  assert_not_contains "$downs" "dwk-sec-app-0000000000cc"     # scan-app 스택은 건드리지 않는다
  assert_not_contains "$downs" "dwk-sec-web-0000000000dd"     # 시각을 모르는 줄이 섞이면 지우지 않는다
  assert_contains "$downs" "dwk-sec-web-0000000000ee"
  assert_contains "$(cat "$WEB_RUN/summary.md")" "이전 실행이 남긴 ZAP 스택 2개"
}

# --- 실제 Docker 통합 ----------------------------------------------------------

_web_ready() {
  [ "${SEC_TEST_DOCKER:-1}" = 0 ] && { echo "(SEC_TEST_DOCKER=0)"; return 1; }
  if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    echo "(Docker 엔진 없음)"; return 1
  fi
  # shellcheck disable=SC1091
  . "$PLUGIN_DIR/scripts/lib/common.sh"
  REAL_SEC_DATA=$SEC_DATA
  local n
  for n in zap egress-proxy; do
    docker image inspect "$(sec_image_ref "$n")" >/dev/null 2>&1 || { echo "(이미지 없음: $n — update.sh 실행 필요)"; return 1; }
  done
}

# 호스트 127.0.0.1 에 대상 서버를 띄운다 → WEB_PORT, WEB_SRV_PID
_web_target_up() {
  python3 "$TESTS_DIR/fixtures/web-target/server.py" "$SEC_TMP/port" &
  WEB_SRV_PID=$!
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do [ -s "$SEC_TMP/port" ] && break; sleep 0.3; done
  WEB_PORT=$(cat "$SEC_TMP/port" 2>/dev/null)
  [ -n "$WEB_PORT" ] || fail "대상 서버를 띄우지 못함"
}

# V1 N2: 허용목록 밖은 프록시가 403 + 로그, 프록시를 거치지 않으면 나갈 수 없다 (compose-web.yml 그대로)
test_real_n2_proxy_enforces_allowlist_and_blocks_bypass() {
  _web_ready || return 77
  _web_target_up
  local p out logs
  p="dwk-sec-web-$(od -An -N6 -tx1 /dev/urandom | tr -d ' \n')"
  export DWK_ZAP_IMAGE DWK_PROXY_IMAGE DWK_TARGET_URL DWK_SPIDER_MIN=1 DWK_PASSIVE_MIN=1 DWK_PROXY_CONF DWK_PROXY_FILTER
  DWK_ZAP_IMAGE=$(sec_image_ref zap)
  DWK_PROXY_IMAGE=$(sec_image_ref egress-proxy)
  DWK_TARGET_URL="http://host.docker.internal:$WEB_PORT/"
  DWK_PROXY_CONF=$(printf 'Port 8888\nListen 0.0.0.0\nLogLevel Notice\nFilterDefaultDeny Yes\nFilterType ere\nFilterURLs On\nFilter "/run/dwk/filter"\nConnectPort 1')
  # '-' 가 든 호스트 필터가 tinyproxy(musl ERE)에서도 맞는지 함께 본다 — 맞으면 403 이 아니라 이름 풀이 실패로 끝난다
  DWK_PROXY_FILTER=$(cd "$PLUGIN_DIR/scripts/lib" && python3 -c '
import web_target as w, sys
print("\n".join(w.proxy_filters("http", "host.docker.internal", int(sys.argv[1])) + w.proxy_filters("http", "dwk-allowed-host.invalid", 8080)))' "$WEB_PORT")
  local c=(docker compose -p "$p" -f "$PLUGIN_DIR/docker/compose-web.yml")
  "${c[@]}" up -d --wait --wait-timeout 60 egress-proxy >/dev/null 2>&1 || { "${c[@]}" down -v >/dev/null 2>&1; kill "$WEB_SRV_PID"; fail "프록시 기동 실패"; }
  out=$("${c[@]}" --profile scan run --rm --no-deps -T --entrypoint python3 zap -I -c '
import socket, sys, urllib.request, urllib.error
socket.setdefaulttimeout(5)
port = sys.argv[1]
op = urllib.request.build_opener(urllib.request.ProxyHandler({"http": "http://egress-proxy:8888"}))
def get(u):
    try:
        return str(op.open(u, timeout=8).status)
    except urllib.error.HTTPError as e:
        return str(e.code)
    except OSError as e:
        return "err"
print("allowed", get("http://host.docker.internal:%s/about" % port))
print("otherport", get("http://host.docker.internal:%d/" % (int(port) + 1)))
print("outside", get("http://example.com/"))
print("hyphen", get("http://dwk-allowed-host.invalid:8080/"))
# 리뷰 C1: tinyproxy 는 첫 '/' 앞의 '@' 앞을 버리고 접속한다 — 필터가 '?@' 를 허용하면 다른 곳으로 간다.
# urllib 은 요청줄을 정규화하므로 원시 소켓으로 보낸다
def raw(line):
    s = socket.create_connection(("egress-proxy", 8888), timeout=8)
    s.sendall(("GET %s HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n" % line).encode())
    data = s.recv(200).decode("latin-1")
    s.close()
    return data.split(" ")[1] if data.startswith("HTTP/") else "err"
print("qat", raw("http://host.docker.internal:%s?@example.com:80/" % port))
print("hashat", raw("http://host.docker.internal:%s#@example.com:80/" % port))
for h, pt in (("host.docker.internal", int(port)), ("1.1.1.1", 443)):
    try:
        socket.create_connection((h, pt), timeout=4); print("direct", h, "open")
    except OSError:
        print("direct", h, "blocked")
' "$WEB_PORT" 2>&1)
  logs=$("${c[@]}" logs --no-color --no-log-prefix egress-proxy 2>&1)
  "${c[@]}" --profile scan down -v --remove-orphans >/dev/null 2>&1
  kill "$WEB_SRV_PID" 2>/dev/null
  assert_contains "$out" "allowed 200"
  assert_contains "$out" "otherport 403"
  assert_contains "$out" "outside 403"
  assert_not_contains "$out" "hyphen 403"
  assert_contains "$out" "qat 403"
  assert_contains "$out" "hashat 403"
  assert_contains "$out" "direct host.docker.internal blocked"
  assert_contains "$out" "direct 1.1.1.1 blocked"
  assert_contains "$logs" 'Proxying refused on filtered url "http://example.com/"'
  [ -z "$(docker ps -aq --filter "label=com.docker.compose.project=$p")" ] || fail "스택이 남음"
}

_web_projects() {
  docker ps -aq --filter label=com.docker.compose.project 2>/dev/null |
    xargs docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' 2>/dev/null | grep '^dwk-sec-web-' | sort -u
}

test_real_scan_web_baseline() {
  _web_ready || return 77
  _web_target_up
  export DWK_SECURITY_DATA_DIR="$SEC_TMP/data" DWK_SECURITY_CONF_DIR="$SEC_TMP/conf"
  web_copy_built_records
  mkdir -p "$DWK_SECURITY_CONF_DIR"
  printf 'http://host.docker.internal:%s\n' "$WEB_PORT" >"$DWK_SECURITY_CONF_DIR/targets.allowlist"
  chmod 600 "$DWK_SECURITY_CONF_DIR/targets.allowlist"
  local summary run s x
  WEB_BEFORE=$(_web_projects)
  summary=$("$SCAN_WEB" "http://host.docker.internal:$WEB_PORT/" 2>"$SEC_TMP/scan.err" | tail -n 1)
  kill "$WEB_SRV_PID" 2>/dev/null
  [ -f "$summary" ] || fail "summary 없음: $(tail -n 5 "$SEC_TMP/scan.err")"
  run=$(dirname "$summary")
  assert_eq "$(awk -F '\t' '$1 == "zap" { print $2 }' "$run/raw/status.tsv")" ok "($(cat "$run/raw/status.tsv"))"
  s=$(cat "$summary")
  # 기준선: 보안 헤더 누락·쿠키 속성·오류 정보 노출 (tests/fixtures/web-target/server.py 가 일부러 넣은 것)
  local r
  for r in zap.10038 zap.10020 zap.10021 zap.10010 zap.10054 zap.90022; do
    x=$(python3 -c 'import json,sys; print(any(f["rule_id"].startswith(sys.argv[2]) for f in json.load(open(sys.argv[1]))["findings"]))' \
      "$run/findings.json" "$r") || fail "findings.json 을 읽지 못함"
    assert_eq "$x" True "($r)"
  done
  # 범위 밖 링크(example.com)는 요청하지 않는다 — 차단 목록이 비어 있다
  assert_eq "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["total"])' "$run/raw/proxy-denied.json")" 0
  # 응답 안의 지시문은 표·제목·목록 줄에 나오지 않는다 (코드 블록 안에만)
  if printf '%s\n' "$s" | grep 'IGNORE PREVIOUS' | grep -q '^\(#\||\|- \)'; then fail "인젝션 문구가 코드 블록 밖에 있음"; fi
  # 이번 실행의 스택이 남지 않는다 (동시에 도는 다른 실행과 구분하려고 실행 전후의 툴킷 web 프로젝트 목록을 비교)
  assert_eq "$(_web_projects)" "$WEB_BEFORE" "(실행 뒤 남은 dwk-sec-web 스택)"
  case "$run" in "$SEC_TMP/data/reports/"*) ;; *) fail "리포트 위치: $run" ;; esac
}

# 2차 리뷰 W-B: 아무도 듣지 않는 포트는 "대상에 접속하지 못했습니다"로 실패하고, 프록시 오류 페이지를 결과로 내지 않는다
test_real_scan_web_unreachable_target_fails() {
  _web_ready || return 77
  export DWK_SECURITY_DATA_DIR="$SEC_TMP/data" DWK_SECURITY_CONF_DIR="$SEC_TMP/conf"
  web_copy_built_records
  mkdir -p "$DWK_SECURITY_CONF_DIR"
  local port summary run
  port=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
  printf 'http://host.docker.internal:%s\n' "$port" >"$DWK_SECURITY_CONF_DIR/targets.allowlist"
  chmod 600 "$DWK_SECURITY_CONF_DIR/targets.allowlist"
  summary=$("$SCAN_WEB" "http://host.docker.internal:$port/" 2>"$SEC_TMP/scan.err" | tail -n 1)
  [ -f "$summary" ] || fail "summary 없음: $(tail -n 5 "$SEC_TMP/scan.err")"
  run=$(dirname "$summary")
  assert_contains "$(awk -F '\t' '$1 == "zap"' "$run/raw/status.tsv")" "대상에 접속하지 못했습니다"
  assert_eq "$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["findings"]))' "$run/findings.json")" 0
}
