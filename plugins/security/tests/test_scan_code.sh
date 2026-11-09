# shellcheck shell=bash
# scan-code.sh 테스트
#   - 가짜 docker: 인자 거부(V3 도구 인자 주입), D6(데이터 없음), D7(마운트 가시성) — 컨테이너를 띄우지 않음을 확인
#   - 실제 Docker(통합): V1 N0 네트워크 차단, V2 기준선(시크릿·SAST·SCA), V3 리포트 위치·대상 무변화·원문 미노출
#     이미지·규칙·OSV DB 가 없으면 건너뛴다 (update.sh 를 먼저 실행).

SCAN="$PLUGIN_DIR/scripts/scan-code.sh"

# 가짜 홈·데이터 + 가짜 docker (images.lock 의 실제 digest 를 '있음'으로)
setup_fake() {
  export HOME="$SEC_TMP/home"
  mkdir -p "$HOME/proj"
  echo 'print(1)' >"$HOME/proj/a.py"
  export DWK_SECURITY_DATA_DIR="$HOME/.local/share/dev-workflow-kit/security"
  export DWK_SECURITY_CONF_DIR="$HOME/.config/dev-workflow-kit/security"
  mkdir -p "$SEC_TMP/bin"
  cp "$TESTS_DIR/lib/fake-docker" "$SEC_TMP/bin/docker"
  export PATH="$SEC_TMP/bin:$PATH"
  export FAKE_LOG="$SEC_TMP/docker.log"
  : >"$FAKE_LOG"
  FAKE_IMAGES=$(awk '!/^[[:space:]]*(#|$)/ { printf "%s@%s ", $2, $4 }' "$PLUGIN_DIR/docker/images.lock")
  export FAKE_IMAGES
}

fake_data() {
  mkdir -p "$DWK_SECURITY_DATA_DIR/data/semgrep-rules/generic" "$DWK_SECURITY_DATA_DIR/data/osv"
  echo "rules: []" >"$DWK_SECURITY_DATA_DIR/data/semgrep-rules/generic/x.yaml"
  echo deadbeef >"$DWK_SECURITY_DATA_DIR/data/semgrep-rules/.commit"
  date -u '+%Y-%m-%dT%H:%M:%SZ' >"$DWK_SECURITY_DATA_DIR/data/osv/UPDATED_AT"
}

no_container_started() {
  if grep -q '^docker run' "$FAKE_LOG"; then
    fail "컨테이너가 기동됨: $(grep '^docker run' "$FAKE_LOG" | head -n 1)"
  fi
}

test_rejects_unknown_option_without_starting_containers() {
  setup_fake
  assert_status 2 "$SCAN" --active-scan "$HOME/proj"
  assert_contains "$OUT" "알 수 없는 옵션"
  assert_status 2 "$SCAN" "$HOME/proj" --config=p/default
  assert_status 2 "$SCAN" "$HOME/proj" "$HOME/proj"
  assert_contains "$OUT" "하나만"
  assert_status 2 "$SCAN" "$HOME/proj" '--profile=web;rm'
  assert_status 2 "$SCAN"
  no_container_started
}

test_rejects_home_target() {
  setup_fake
  assert_status 1 "$SCAN" "$HOME"
  assert_contains "$OUT" "홈 디렉터리"
  no_container_started
}

test_d6_missing_rules_or_osv_db_points_to_update() {
  setup_fake
  assert_status 1 "$SCAN" "$HOME/proj"
  assert_contains "$OUT" "[D6]"
  assert_contains "$OUT" "update.sh"
  no_container_started
  [ ! -d "$DWK_SECURITY_DATA_DIR/reports" ] || [ -z "$(ls -A "$DWK_SECURITY_DATA_DIR/reports")" ] || fail "리포트 폴더가 생김"
}

test_d7_invisible_mount_stops_before_scanning() {
  setup_fake
  fake_data
  # 컨테이너 안에서 대상이 빈 폴더로 보이는 런타임 (Colima 기본: 홈 밖 경로)
  FAKE_RUN_OUTPUT="" assert_status 1 "$SCAN" "$HOME/proj"
  assert_contains "$OUT" "[D7]"
  assert_eq "$(grep -c '^docker run' "$FAKE_LOG")" 1 "(D7 확인용 컨테이너 1개만)"
  assert_contains "$(cat "$FAKE_LOG")" "--network none"
}

test_rules_mismatch_with_lock_is_warned() {
  setup_fake
  fake_data
  export FAKE_RUN_OUTPUT="a.py"
  local summary
  # PR #19 W7: 설치된 규칙(.commit)이 rules.lock 과 다르면 경고한다 (fake_data 의 커밋은 deadbeef)
  summary=$("$SCAN" "$HOME/proj" 2>/dev/null | tail -n 1)
  [ -f "$summary" ] || fail "summary 없음"
  assert_contains "$(cat "$(dirname "$summary")/raw/warnings.txt")" "rules.lock 과 다릅니다"
  local lock_commit lock_url lock_paths
  read -r lock_commit lock_url lock_paths <<<"$(awk '!/^[[:space:]]*(#|$)/ && $1 == "semgrep-rules" { print $3, $2, $4 }' "$PLUGIN_DIR/rules.lock")"
  # 커밋은 같고 paths 만 다르면 경고한다 (W7 의 핵심 경우), 이전 버전의 2줄 .commit 도 경고한다
  for content in "$lock_commit\n$lock_url\nother" "$lock_commit\n$lock_url"; do
    printf '%b\n' "$content" >"$DWK_SECURITY_DATA_DIR/data/semgrep-rules/.commit"
    summary=$("$SCAN" "$HOME/proj" 2>/dev/null | tail -n 1)
    [ -f "$summary" ] || fail "summary 없음"
    assert_contains "$(cat "$(dirname "$summary")/raw/warnings.txt")" "rules.lock 과 다릅니다"
  done
  # 커밋·paths 가 같으면 경고하지 않는다
  printf '%s\n%s\n%s\n' "$lock_commit" "$lock_url" "$lock_paths" >"$DWK_SECURITY_DATA_DIR/data/semgrep-rules/.commit"
  summary=$("$SCAN" "$HOME/proj" 2>/dev/null | tail -n 1)
  [ -f "$summary" ] || fail "summary 없음"
  assert_not_contains "$(cat "$(dirname "$summary")/raw/warnings.txt")" "rules.lock 과 다릅니다"
}

test_d7_probe_failure_is_not_blamed_on_mount_sharing() {
  setup_fake
  fake_data
  # PR #19 NITPICK: 컨테이너 자체가 실패하면(이미지·런타임 오류) 마운트 공유 문제로 안내하지 않는다
  assert_status 1 "$SCAN" "$HOME/proj"
  assert_contains "$OUT" "[D7] 대상 폴더 확인용 컨테이너를 실행하지 못했습니다 (종료코드 99)"
  assert_contains "$OUT" "가짜 docker 로 run 을 실행하면 안 됩니다"
  assert_not_contains "$OUT" "공유하지 않습니다"
}

# 가짜 docker 로 스캔을 끝까지 돌리고 status.tsv 의 한 도구 행을 돌려준다 (도구 결과는 없으므로 정규화 오류는 무시)
_status_row() {
  local target=$1 tool=$2 summary
  summary=$("$SCAN" "$target" 2>"$SEC_TMP/scan.err" | tail -n 1)
  [ -f "$summary" ] || fail "summary 없음: $(tail -n 5 "$SEC_TMP/scan.err")"
  awk -F '\t' -v t="$tool" '$1 == t' "$(dirname "$summary")/raw/status.tsv"
}

# 전제: 테스트 임시 폴더(TMPDIR)가 git 저장소 안에 있지 않다 (있으면 "git 저장소가 아님" 대신 하위 폴더 안내가 나온다)
test_history_skip_reason_for_worktree_and_subfolder() {
  setup_fake
  fake_data
  export FAKE_RUN_OUTPUT="a.py"
  # 호스트 git 을 실행하지 않는다 (위협 모델 T5) — 호출되면 기록되는 가짜 git
  printf '#!/bin/sh\necho "git $*" >>"%s"\nexit 1\n' "$SEC_TMP/git.log" >"$SEC_TMP/bin/git"
  chmod +x "$SEC_TMP/bin/git"
  # PR #19 W8: worktree·서브모듈(.git 이 파일)과 저장소 하위 폴더를 "git 저장소 아님"으로 안내하지 않는다
  printf 'gitdir: /elsewhere/.git/worktrees/proj\n' >"$HOME/proj/.git"
  assert_contains "$(_status_row "$HOME/proj" gitleaks-git)" "git worktree 또는 서브모듈입니다"
  rm -f "$HOME/proj/.git"
  mkdir -p "$HOME/repo/.git" "$HOME/repo/sub"
  echo 'print(1)' >"$HOME/repo/sub/a.py"
  assert_contains "$(_status_row "$HOME/repo/sub" gitleaks-git)" "최상위 경로($(cd -P "$HOME/repo" && pwd -P))로 실행하면"
  assert_contains "$(_status_row "$HOME/proj" gitleaks-git)" "git 저장소가 아님"
  # 서브모듈의 하위 폴더는 처음부터 worktree·서브모듈로 안내한다
  mkdir -p "$HOME/sm/sub"
  printf 'gitdir: ../.git/modules/sm\n' >"$HOME/sm/.git"
  echo 'print(1)' >"$HOME/sm/sub/a.py"
  assert_contains "$(_status_row "$HOME/sm/sub" gitleaks-git)" "worktree 또는 서브모듈("
  # 상위 .git 이 홈 디렉터리면(점검 대상으로 받지 않는 경로) 안내하지 않는다
  mkdir -p "$HOME/.git"
  assert_contains "$(_status_row "$HOME/proj" gitleaks-git)" "git 저장소가 아님"
  [ ! -s "$SEC_TMP/git.log" ] || fail "호스트 git 이 실행됨: $(cat "$SEC_TMP/git.log")"
}

test_oom_kill_is_named_in_failure_note() {
  setup_fake
  fake_data
  # PR #19 SUGGESTION: 종료코드 137 은 메모리 부족 가능성을 드러낸다
  export FAKE_RUN_OUTPUT="a.py" FAKE_RUN_FAIL_MATCH="semgrep scan" FAKE_RUN_FAIL_RC=137
  assert_contains "$(_status_row "$HOME/proj" semgrep)" "메모리 부족(OOM)"
}

test_unknown_forced_profile_is_rejected() {
  setup_fake
  fake_data
  FAKE_RUN_OUTPUT="a.py" assert_status 1 "$SCAN" "$HOME/proj" --profile=cobol
  assert_contains "$OUT" "알 수 없는 프로파일"
}

# --- 실제 Docker 통합 ----------------------------------------------------------

_real_ready() {
  [ "${SEC_TEST_DOCKER:-1}" = 0 ] && { echo "(SEC_TEST_DOCKER=0)"; return 1; }
  if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    echo "(Docker 엔진 없음)"; return 1
  fi
  # shellcheck disable=SC1091
  . "$PLUGIN_DIR/scripts/lib/common.sh"
  local n
  for n in semgrep gitleaks osv-scanner; do
    docker image inspect "$(sec_image_ref "$n")" >/dev/null 2>&1 || { echo "(이미지 없음: $n — update.sh 실행 필요)"; return 1; }
  done
  if [ ! -f "$SEC_DATA/data/semgrep-rules/.commit" ] || [ ! -f "$SEC_DATA/data/osv/UPDATED_AT" ]; then
    echo "(규칙·OSV DB 없음 — update.sh 실행 필요)"; return 1
  fi
}

# 홈 아래(Colima 공유 범위)에 임시 대상 저장소를 만든다: 픽스처 + 히스토리 속 AWS 키 + 미커밋 GitHub 토큰
_make_target() {
  local t
  mkdir -p "$HOME/.cache/dev-workflow-kit-tests"
  t=$(mktemp -d "$HOME/.cache/dev-workflow-kit-tests/scan.XXXXXX")
  cp -R "$TESTS_DIR/fixtures/common/." "$t/"
  mv "$t/package-lock.json.fixture" "$t/package-lock.json"
  mv "$t/requirements.txt.fixture" "$t/requirements.txt"
  AWS_KEY="AKIA$(LC_ALL=C tr -dc 'A-Z2-7' </dev/urandom | head -c 16)"
  GH_TOKEN_FAKE="ghp_$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 36)"
  (
    cd "$t" || exit 1
    git init -q && git config user.email t@example.com && git config user.name t &&
      printf 'AWS_ACCESS_KEY_ID = "%s"\n' "$AWS_KEY" >config.py &&
      git add -A && git commit -qm init && git rm -q config.py && git commit -qm "remove key"
  ) || return 1
  # 도구의 인라인 억제 주석이 있어도 탐지해야 한다 (--ignore-gitleaks-allow, --disable-nosem)
  printf 'token = "%s"  # gitleaks:allow\n' "$GH_TOKEN_FAKE" >"$t/.env.local"
  sed -i.bak 's|innerHTML = |innerHTML = /* nosemgrep */ |' "$t/web/render.js" && rm -f "$t/web/render.js.bak"
  # 일반 형태 시크릿 (따옴표로 감싼 키) — Semgrep 시크릿 규칙 경로로 원문이 새면 안 된다 (PR #19 C1)
  PLAIN_PW="Pw$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 18)"
  mkdir -p "$t/app" && printf '{\n  "password": "%s"\n}\n' "$PLAIN_PW" >"$t/app/config.json"
  # 대상 저장소의 억제 설정 — 툴킷은 이를 쓰지 않아야 한다 (PR #19 W2, 위협 모델 T5)
  printf "[allowlist]\npaths = ['.*']\n" >"$t/.gitleaks.toml"
  printf '[[PackageOverrides]]\nname = "requests"\nignore = true\n' >"$t/osv-scanner.toml"
  TARGET_DIR=$t
}

# _check_baseline <findings.json> <baseline.json> — must_find 가 모두 있고 must_not_find 가 하나도 없어야 한다
_check_baseline() {
  python3 - "$1" "$2" <<'PY' || fail "기준선 회귀 ($(basename "$2"))"
import json, sys
found = json.load(open(sys.argv[1]))["findings"]
base = json.load(open(sys.argv[2]))
def match(f, b):
    return ((("tool" not in b) or f["tool"] == b["tool"])
            and (("rule_id" not in b) or f["rule_id"] == b["rule_id"])
            and (("rule_suffix" not in b) or f["rule_id"].endswith(b["rule_suffix"]))
            and (("package" not in b) or f["location"]["package"] == b["package"])
            and (("file" not in b) or f["location"]["file"] == b["file"])
            and (("severity" not in b) or f["severity"] == b["severity"]))
missing = [b for b in base["must_find"] if not any(match(f, b) for f in found)]
unexpected = [b for b in base.get("must_not_find", []) if any(match(f, b) for f in found)]
for m in missing:
    print("    기준선 누락:", m)
for u in unexpected:
    print("    나오면 안 되는 결과:", u)
print(f"    findings {len(found)}건, 기준선 {len(base['must_find'])}건 중 {len(base['must_find']) - len(missing)}건 확인")
sys.exit(1 if missing or unexpected else 0)
PY
}

test_real_scan_code_end_to_end() {
  _real_ready || exit 77
  _make_target || fail "대상 저장소 생성 실패 (git 필요)"
  # run.sh 의 SEC_TMP 정리 trap 을 덮어쓰므로 SEC_TMP 정리도 함께 한다
  trap 'rm -rf "$TARGET_DIR"; [ -n "${RUN_DIR:-}" ] && rm -rf "$RUN_DIR"; chmod -R u+w "$SEC_TMP" 2>/dev/null; rm -rf "$SEC_TMP"' EXIT

  # 모든 docker 호출을 기록하는 래퍼 (실제 docker 로 전달)
  local real_docker before_status after_status summary
  real_docker=$(command -v docker)
  mkdir -p "$SEC_TMP/wrap"
  printf '#!/bin/sh\nprintf "%%s\\n" "$*" >>"%s"\nexec "%s" "$@"\n' "$SEC_TMP/calls.log" "$real_docker" >"$SEC_TMP/wrap/docker"
  chmod +x "$SEC_TMP/wrap/docker"

  before_status=$(cd "$TARGET_DIR" && git status --porcelain && git rev-parse HEAD)
  summary=$(PATH="$SEC_TMP/wrap:$PATH" "$SCAN" "$TARGET_DIR" 2>"$SEC_TMP/scan.err" | tail -n 1)
  [ -f "$summary" ] || fail "summary 없음: $(tail -n 5 "$SEC_TMP/scan.err")"
  RUN_DIR=$(dirname "$summary")
  after_status=$(cd "$TARGET_DIR" && git status --porcelain && git rev-parse HEAD)

  # V3: 리포트는 $DATA/reports 에만, 대상 저장소는 변화 없음
  case "$RUN_DIR" in "$SEC_DATA/reports/"*) ;; *) fail "리포트 위치: $RUN_DIR" ;; esac
  assert_eq "$after_status" "$before_status" "(대상 저장소 변경됨)"

  # V1 N0: 스캔 컨테이너는 모두 --network none
  local runs
  runs=$(grep -c '^run ' "$SEC_TMP/calls.log")
  [ "$runs" -ge 4 ] || fail "docker run 호출이 너무 적음: $runs"
  assert_eq "$(grep '^run ' "$SEC_TMP/calls.log" | grep -vc -- '--network none')" 0 "(--network none 없는 컨테이너)"
  assert_eq "$(grep -c '^pull ' "$SEC_TMP/calls.log")" 0 "(스캔이 pull 함)"

  # 모든 도구 정상 종료
  assert_eq "$(awk -F '\t' '$2 != "ok"' "$RUN_DIR/raw/status.tsv")" "" "(도구 실패)"

  # V2: 기준선의 모든 항목이 나와야 한다
  _check_baseline "$RUN_DIR/findings.json" "$TESTS_DIR/baseline/common.json"

  # V2·T4: 시크릿 원문이 리포트 폴더 어디에도 없다 (raw 포함)
  if grep -rqF "$AWS_KEY" "$RUN_DIR" || grep -rqF "$GH_TOKEN_FAKE" "$RUN_DIR" || grep -rqF "$PLAIN_PW" "$RUN_DIR"; then
    fail "시크릿 원문이 리포트에 남음"
  fi

  # T5: 픽스처의 인젝션 문구는 summary 의 코드 블록 안에만
  python3 - "$summary" <<'PY' || fail "인젝션 문구가 코드 블록 밖에 있음"
import sys
inside = bad = False
seen = False
for ln in open(sys.argv[1], encoding="utf-8"):
    if ln.startswith("````"):
        inside = not inside
        continue
    if "IGNORE ALL PREVIOUS INSTRUCTIONS" in ln:
        seen = True
        bad |= not inside
sys.exit(1 if bad or not seen else 0)
PY

  # 억제 설정이 있었다는 사실은 summary 에 드러난다
  assert_contains "$(cat "$summary")" "결과 억제 설정이 있습니다"

  # 권한: 리포트 폴더 700, 파일 600
  assert_eq "$(file_mode "$RUN_DIR")" 700
  local bad_modes
  bad_modes=$(find "$RUN_DIR" -type f ! -perm 600 -exec stat -f '%Sp %N' {} + 2>/dev/null)
  assert_eq "$bad_modes" "" "(600 아닌 리포트 파일)"
}

# PR #19 W3: 오프라인 DB 가 없는 생태계 lockfile 이 섞이면 SCA 전체가 실패한다 — 0건이 아니라 실패와 원인을 보여야 한다
test_real_unsupported_ecosystem_fails_loudly() {
  _real_ready || exit 77
  # trap 은 함수가 끝난 뒤 실행되므로 지역 변수가 아닌 전역 변수를 쓴다
  local summary
  mkdir -p "$HOME/.cache/dev-workflow-kit-tests"
  ECO_DIR=$(mktemp -d "$HOME/.cache/dev-workflow-kit-tests/eco.XXXXXX")
  trap 'rm -rf "$ECO_DIR"; [ -n "${ECO_RUN:-}" ] && rm -rf "$ECO_RUN"; chmod -R u+w "$SEC_TMP" 2>/dev/null; rm -rf "$SEC_TMP"' EXIT
  printf 'requests==2.19.0\n' >"$ECO_DIR/requirements.txt"
  # Hex(Elixir) 는 osv-seed 에 없는 생태계
  printf '%%{\n  "jason": {:hex, :jason, "1.4.1", "af1504e35f629ddcdd6addb3513c3853991f694921b1b9368b0bd32beb9f1b63", [:mix], [], "hexpm", "fbb01ecdfd565b56261302f7e1fcc27c4fb8f32d56eab74db621fc154604a7a1"},\n}\n' >"$ECO_DIR/mix.lock"
  summary=$("$SCAN" "$ECO_DIR" 2>"$SEC_TMP/scan.err" | tail -n 1)
  [ -f "$summary" ] || fail "summary 없음: $(tail -n 5 "$SEC_TMP/scan.err")"
  ECO_RUN=$(dirname "$summary")
  assert_contains "$(awk -F '\t' '$1 == "osv-scanner"' "$ECO_RUN/raw/status.tsv")" "failed"
  assert_contains "$(cat "$summary")" "오프라인 DB 가 없는 생태계(Hex"
}

test_real_n0_containers_cannot_reach_network() {
  _real_ready || exit 77
  local g s
  g=$(sec_image_ref gitleaks)
  s=$(sec_image_ref semgrep)
  # 같은 명령이 네트워크 차단 때문에 실패해야 한다 (DNS·IP 모두)
  if docker run --rm --network none --entrypoint sh "$g" -c 'wget -q -T 3 -O /dev/null http://1.1.1.1 || wget -q -T 3 -O /dev/null https://example.com' >/dev/null 2>&1; then
    fail "gitleaks 이미지가 --network none 에서 외부에 접속함"
  fi
  # HTTP 응답 코드와 무관하게 TCP 연결 성립 여부로 판정한다 (403 응답도 '접속됨'이다)
  if docker run --rm --network none --entrypoint python3 "$s" -c 'import socket; socket.create_connection(("1.1.1.1", 80), timeout=3)' >/dev/null 2>&1; then
    fail "semgrep 이미지가 --network none 에서 외부에 접속함"
  fi
}

# PR #22: exclude_paths 를 하위 경로로 한정한 Semgrep --exclude 가 실제로 의도한 경로만 뺀다
test_real_exclude_paths_are_scoped_to_profile_root() {
  _real_ready || exit 77
  mkdir -p "$HOME/.cache/dev-workflow-kit-tests"
  EXCL_DIR=$(mktemp -d "$HOME/.cache/dev-workflow-kit-tests/excl.XXXXXX")
  trap 'rm -rf "$EXCL_DIR"; chmod -R u+w "$SEC_TMP" 2>/dev/null; rm -rf "$SEC_TMP"' EXIT
  local f img scanned
  for f in macos/a.py ios/macos/b.py macos/Pods/c.py x/ios/Pods/d.py 'a[1]/macos/e.py' a1/macos/g.py; do
    mkdir -p "$EXCL_DIR/src/$(dirname "$f")"
    echo 'eval(x)' >"$EXCL_DIR/src/$f"
  done
  mkdir -p "$EXCL_DIR/rules"
  printf 'rules:\n- id: ev\n  pattern: eval(...)\n  message: m\n  languages: [python]\n  severity: ERROR\n' >"$EXCL_DIR/rules/r.yaml"
  printf 'flutter\t.\t\nios\tios\t\nreact-native\t.\t\nios\ta[1]\t\n' >"$EXCL_DIR/profiles.tsv"
  local -a args=()
  while IFS="$(printf '\t')" read -r kind value; do
    [ "$kind" = exclude ] && args+=(--exclude "$value")
  done < <(python3 "$PLUGIN_DIR/scripts/lib/profiles.py" plan "$EXCL_DIR/profiles.tsv" --rules-dir "$EXCL_DIR/none" --custom-dir "$EXCL_DIR/none")
  img=$(sec_image_ref semgrep)
  scanned=$(docker run --rm --network none -v "$EXCL_DIR/src:/src:ro" -v "$EXCL_DIR/rules:/r:ro" "$img" \
    semgrep scan --config /r --metrics=off --disable-version-check --json "${args[@]}" /src 2>/dev/null |
    python3 -c 'import json,sys; print(" ".join(sorted(p.replace("/src/","") for p in json.load(sys.stdin)["paths"]["scanned"])))')
  # 루트 macos 러너·이름만 비슷한 a1/ 은 점검, 나머지는 제외
  assert_eq "$scanned" "a1/macos/g.py macos/a.py" "(제외 결과)"
}

# S-Web: 웹 픽스처 기준선 (W1~W8) — 커스텀 Semgrep 규칙·스택 검사·OSV 가 모두 연결되는지
test_real_scan_code_web_baseline() {
  _real_ready || exit 77
  mkdir -p "$HOME/.cache/dev-workflow-kit-tests"
  WEB_DIR=$(mktemp -d "$HOME/.cache/dev-workflow-kit-tests/web.XXXXXX")
  trap 'rm -rf "$WEB_DIR"; [ -n "${WEB_RUN:-}" ] && rm -rf "$WEB_RUN"; chmod -R u+w "$SEC_TMP" 2>/dev/null; rm -rf "$SEC_TMP"' EXIT
  cp -R "$TESTS_DIR/fixtures/web/." "$WEB_DIR/"
  mv "$WEB_DIR/env.fixture" "$WEB_DIR/.env"
  mv "$WEB_DIR/package-lock.json.fixture" "$WEB_DIR/package-lock.json"
  local summary
  summary=$("$SCAN" "$WEB_DIR" 2>"$SEC_TMP/scan.err" | tail -n 1)
  [ -f "$summary" ] || fail "summary 없음: $(tail -n 5 "$SEC_TMP/scan.err")"
  WEB_RUN=$(dirname "$summary")
  assert_eq "$(awk -F '\t' '$2 != "ok" && $1 != "gitleaks-git"' "$WEB_RUN/raw/status.tsv")" "" "(도구 실패)"
  assert_contains "$(cat "$WEB_RUN/raw/profiles.tsv")" "web"
  _check_baseline "$WEB_RUN/findings.json" "$TESTS_DIR/baseline/web.json"
  # .env 의 값은 리포트 어디에도 없다 (키 이름만)
  if grep -rqF "fixture-not-a-real-value" "$WEB_RUN"; then
    fail ".env 값이 리포트에 남음"
  fi
}

# S-Server: 서버 픽스처 기준선 (S1~S7) — 하위 경로 서버 3개(api·gosvc·web) + 저장소 루트 Dockerfile·compose
test_real_scan_code_server_baseline() {
  _real_ready || exit 77
  mkdir -p "$HOME/.cache/dev-workflow-kit-tests"
  SRV_DIR=$(mktemp -d "$HOME/.cache/dev-workflow-kit-tests/server.XXXXXX")
  trap 'rm -rf "$SRV_DIR"; [ -n "${SRV_RUN:-}" ] && rm -rf "$SRV_RUN"; chmod -R u+w "$SEC_TMP" 2>/dev/null; rm -rf "$SEC_TMP"' EXIT
  cp -R "$TESTS_DIR/fixtures/server/." "$SRV_DIR/"
  mv "$SRV_DIR/requirements.txt.fixture" "$SRV_DIR/web/requirements.txt"
  local summary
  summary=$("$SCAN" "$SRV_DIR" 2>"$SEC_TMP/scan.err" | tail -n 1)
  [ -f "$summary" ] || fail "summary 없음: $(tail -n 5 "$SEC_TMP/scan.err")"
  SRV_RUN=$(dirname "$summary")
  assert_eq "$(awk -F '\t' '$2 != "ok" && $1 != "gitleaks-git"' "$SRV_RUN/raw/status.tsv")" "" "(도구 실패)"
  _check_baseline "$SRV_RUN/findings.json" "$TESTS_DIR/baseline/server.json"
  # 설정 파일의 평문 비밀번호 값은 리포트 어디에도 없다 (키 이름만)
  if grep -rqF "fixture-plaintext-pw" "$SRV_RUN"; then
    fail "설정 파일 비밀번호 값이 리포트에 남음"
  fi
}

# S-Android: 안드로이드 픽스처 기준선 (A1~A8)
test_real_scan_code_android_baseline() {
  _real_ready || exit 77
  mkdir -p "$HOME/.cache/dev-workflow-kit-tests"
  AND_DIR=$(mktemp -d "$HOME/.cache/dev-workflow-kit-tests/android.XXXXXX")
  trap 'rm -rf "$AND_DIR"; [ -n "${AND_RUN:-}" ] && rm -rf "$AND_RUN"; chmod -R u+w "$SEC_TMP" 2>/dev/null; rm -rf "$SEC_TMP"' EXIT
  cp -R "$TESTS_DIR/fixtures/android/." "$AND_DIR/"
  mv "$AND_DIR/gradle.lockfile.fixture" "$AND_DIR/app/gradle.lockfile"
  local summary
  summary=$("$SCAN" "$AND_DIR" 2>"$SEC_TMP/scan.err" | tail -n 1)
  [ -f "$summary" ] || fail "summary 없음: $(tail -n 5 "$SEC_TMP/scan.err")"
  AND_RUN=$(dirname "$summary")
  assert_eq "$(awk -F '\t' '$2 != "ok" && $1 != "gitleaks-git"' "$AND_RUN/raw/status.tsv")" "" "(도구 실패)"
  _check_baseline "$AND_RUN/findings.json" "$TESTS_DIR/baseline/android.json"
  if grep -rqF "fixture-store-pw" "$AND_RUN"; then
    fail "서명 비밀번호 값이 리포트에 남음"
  fi
}
