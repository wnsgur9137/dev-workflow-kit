# shellcheck shell=bash
# update.sh --rules 테스트 (네트워크 없음: 가짜 curl 이 로컬 tarball 을 내려준다)
#   - rules.lock 의 paths 변경 시 재설치 (PR #19 W7)
#   - 악성 tarball: 심볼릭 링크·상위 경로·절대 경로·다른 커밋의 최상위 폴더 (PR #19 SUGGESTION)

UPDATE="$PLUGIN_DIR/scripts/update.sh"
COMMIT=$(printf 'a%.0s' $(seq 40))

setup_update() {
  export HOME="$SEC_TMP/home"
  mkdir -p "$HOME"
  export DWK_SECURITY_DATA_DIR="$HOME/data-root"
  export DWK_SECURITY_CONF_DIR="$HOME/conf"
  export SEC_RULES_LOCK="$SEC_TMP/rules.lock"
  mkdir -p "$SEC_TMP/bin"
  # 가짜 curl: -o 대상에 $FAKE_TGZ 를 복사하고 호출을 기록한다
  cat >"$SEC_TMP/bin/curl" <<'SH'
#!/usr/bin/env bash
echo "curl $*" >>"$FAKE_CURL_LOG"
out=""
while [ $# -gt 0 ]; do
  [ "$1" = -o ] && { out=$2; shift; }
  shift
done
cp "$FAKE_TGZ" "$out"
SH
  chmod +x "$SEC_TMP/bin/curl"
  export PATH="$SEC_TMP/bin:$PATH"
  export FAKE_CURL_LOG="$SEC_TMP/curl.log" FAKE_TGZ="$SEC_TMP/src.tgz"
  : >"$FAKE_CURL_LOG"
  RULES="$DWK_SECURITY_DATA_DIR/data/semgrep-rules"
}

write_lock() {
  printf 'semgrep-rules https://github.com/semgrep/semgrep-rules %s %s\n' "$COMMIT" "$1" >"$SEC_RULES_LOCK"
}

# make_tgz <top> [extra...] — python 으로 tarball 을 만든다.
#   extra: symlink | hardlink | dotdot | paxpath | absolute | mixedtop
make_tgz() {
  python3 - "$FAKE_TGZ" "$@" <<'PY'
import io, sys, tarfile
out, top, *extra = sys.argv[1:]
def add(tf, name, data=b"rules:\n  - id: x\n", kind=tarfile.REGTYPE, link=""):
    ti = tarfile.TarInfo(name)
    ti.type, ti.linkname = kind, link
    ti.size = len(data) if kind == tarfile.REGTYPE else 0
    tf.addfile(ti, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
with tarfile.open(out, "w:gz", format=tarfile.PAX_FORMAT) as tf:
    add(tf, f"{top}/python/a.yaml")
    add(tf, f"{top}/go/b.yaml")
    add(tf, f"{top}/python/target.yaml", b"x: 1\n")         # 규칙 아님
    add(tf, f"{top}/python/.github/ci.yaml")                 # .github 제외
    if "symlink" in extra:
        add(tf, f"{top}/python/link.yaml", kind=tarfile.SYMTYPE, link="/etc/passwd")
    if "dotdot" in extra:
        add(tf, f"{top}/python/../../../../../escape.yaml")
    if "hardlink" in extra:
        add(tf, f"{top}/python/hard.yaml", kind=tarfile.LNKTYPE, link="/etc/passwd")
    if "paxpath" in extra:
        # pax 확장 헤더의 path 로 이름을 덮어써 최상위 폴더 검사를 우회하려는 항목
        ti = tarfile.TarInfo(f"{top}/python/innocent.yaml")
        ti.pax_headers = {"path": f"{top}/python/../../../../../paxescape.yaml"}
        data = b"rules:\n  - id: x\n"
        ti.size = len(data)
        tf.addfile(ti, io.BytesIO(data))
    if "absolute" in extra:
        add(tf, "/abs/evil.yaml")
    if "mixedtop" in extra:
        # 같은 커밋 접미사를 단 다른 최상위 폴더가 정상 파일을 덮어쓰려는 항목
        add(tf, "evil-" + top.rsplit("-", 1)[1] + "/python/a.yaml", b"rules:\n  - id: EVIL\n")
PY
}

test_update_rules_installs_and_reinstalls_when_paths_change() {
  setup_update
  write_lock python
  make_tgz "semgrep-rules-$COMMIT"
  assert_status 0 "$UPDATE" --rules
  [ -f "$RULES/python/a.yaml" ] || fail "규칙 미설치: $OUT"
  [ ! -e "$RULES/go/b.yaml" ] || fail "paths 밖 규칙이 설치됨"
  [ ! -e "$RULES/python/target.yaml" ] || fail "규칙이 아닌 YAML 이 설치됨"
  [ ! -e "$RULES/python/.github/ci.yaml" ] || fail ".github 가 설치됨"
  assert_eq "$(sed -n 3p "$RULES/.commit")" python "(.commit 3행 paths)"

  # 같은 커밋·paths 면 받지 않는다
  assert_status 0 "$UPDATE" --rules
  assert_contains "$OUT" "규칙 최신"
  assert_eq "$(grep -c '^curl' "$FAKE_CURL_LOG")" 1 "(다시 받음)"

  # 같은 커밋이라도 paths 가 바뀌면 다시 받는다 (PR #19 W7)
  write_lock python,go
  assert_status 0 "$UPDATE" --rules
  [ -f "$RULES/go/b.yaml" ] || fail "paths 변경 후 재설치 안 됨: $OUT"
  assert_eq "$(grep -c '^curl' "$FAKE_CURL_LOG")" 2
  # 남은 임시 폴더 없음
  assert_eq "$(find "$DWK_SECURITY_DATA_DIR/data" -maxdepth 1 -name '.tmp-update*' | wc -l | tr -d ' ')" 0 "(임시 폴더 잔여)"
}

test_update_rules_skips_links_and_parent_paths() {
  setup_update
  write_lock python
  make_tgz "semgrep-rules-$COMMIT" symlink hardlink dotdot paxpath
  assert_status 0 "$UPDATE" --rules
  [ -f "$RULES/python/a.yaml" ] || fail "정상 규칙 미설치: $OUT"
  [ ! -e "$RULES/python/hard.yaml" ] || fail "하드링크가 설치됨"
  [ -z "$(find "$DWK_SECURITY_DATA_DIR" "$HOME" -name paxescape.yaml 2>/dev/null)" ] || fail "pax path 항목이 추출됨"
  if [ -e "$RULES/python/link.yaml" ] || [ -L "$RULES/python/link.yaml" ]; then
    fail "심볼릭 링크가 설치됨"
  fi
  [ -z "$(find "$DWK_SECURITY_DATA_DIR" "$HOME" -name escape.yaml 2>/dev/null)" ] || fail "상위 경로 항목이 추출됨"
}

test_update_rules_rejects_foreign_top_dir_and_absolute_paths() {
  setup_update
  write_lock python
  make_tgz "semgrep-rules-$COMMIT"
  assert_status 0 "$UPDATE" --rules
  local before
  before=$(cat "$RULES/.commit")
  # 요청과 다른 커밋의 tarball — 설치를 바꾸지 않고 실패
  local COMMIT2
  COMMIT2=$(printf 'b%.0s' $(seq 40))
  printf 'semgrep-rules https://github.com/semgrep/semgrep-rules %s python\n' "$COMMIT2" >"$SEC_RULES_LOCK"
  assert_status 1 "$UPDATE" --rules
  assert_contains "$OUT" "최상위 폴더가 요청한 커밋과 다릅니다"
  assert_eq "$(cat "$RULES/.commit")" "$before" "(기존 설치가 바뀜)"
  # 절대 경로 항목이 섞인 tarball (최상위 폴더가 빈 문자열이라 최상위 폴더 검사에서 실패)
  write_lock python,go
  make_tgz "semgrep-rules-$COMMIT" absolute
  assert_status 1 "$UPDATE" --rules
  assert_contains "$OUT" "최상위 폴더가 요청한 커밋과 다릅니다"
  assert_eq "$(cat "$RULES/.commit")" "$before" "(기존 설치가 바뀜)"
  # 같은 커밋 접미사를 단 다른 최상위 폴더가 섞인 tarball (PR #21 리뷰 W)
  make_tgz "semgrep-rules-$COMMIT" mixedtop
  assert_status 1 "$UPDATE" --rules
  assert_contains "$OUT" "최상위 폴더가 요청한 커밋과 다릅니다"
  assert_not_contains "$(cat "$RULES/python/a.yaml")" "EVIL"
}

test_update_rules_redownloads_legacy_two_line_commit_file() {
  setup_update
  write_lock python
  make_tgz "semgrep-rules-$COMMIT"
  # 이전 버전이 남긴 2줄 .commit (paths 없음) — 같은 커밋이라도 한 번 다시 받는다
  mkdir -p "$RULES"
  printf '%s\nhttps://github.com/semgrep/semgrep-rules\n' "$COMMIT" >"$RULES/.commit"
  assert_status 0 "$UPDATE" --rules
  assert_eq "$(grep -c '^curl' "$FAKE_CURL_LOG")" 1 "(2줄 .commit 인데 다시 받지 않음)"
  assert_eq "$(sed -n 3p "$RULES/.commit")" python
}

test_update_removes_stale_temp_dirs() {
  setup_update
  write_lock python
  make_tgz "semgrep-rules-$COMMIT"
  mkdir -p "$DWK_SECURITY_DATA_DIR/data/.tmp-update-123/x" "$DWK_SECURITY_DATA_DIR/data/.tmp-update.fresh"
  touch -t 202001010000 "$DWK_SECURITY_DATA_DIR/data/.tmp-update-123"
  assert_status 0 "$UPDATE" --rules
  [ ! -e "$DWK_SECURITY_DATA_DIR/data/.tmp-update-123" ] || fail "하루 지난 작업 폴더가 남음"
  [ -d "$DWK_SECURITY_DATA_DIR/data/.tmp-update.fresh" ] || fail "최근 작업 폴더를 지움 (동시 실행 중일 수 있음)"
}
