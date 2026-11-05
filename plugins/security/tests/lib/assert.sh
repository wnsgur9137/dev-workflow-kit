# shellcheck shell=bash
# 최소 단언 함수 — tests/run.sh 가 각 테스트 함수 실행 전에 source 한다.

fail() {
  printf '    단언 실패: %s\n' "$*" >&2
  exit 1
}
assert_eq() { [ "$1" = "$2" ] || fail "기대 '$2', 실제 '$1' ${3:-}"; }
assert_contains() {
  case "$1" in *"$2"*) ;; *) fail "'$2' 가 출력에 없음: $1" ;; esac
}
assert_not_contains() {
  case "$1" in *"$2"*) fail "'$2' 가 출력에 있으면 안 됨: $1" ;; esac
}
# assert_status <기대 종료코드> <명령...>  — 출력은 $OUT 에 남긴다
assert_status() {
  local want=$1 got
  shift
  OUT=$("$@" 2>&1)
  got=$?
  [ "$got" = "$want" ] || fail "종료코드 기대 $want, 실제 $got: $* → $OUT"
}
file_mode() { stat -f '%Lp' "$1" 2>/dev/null || stat -c '%a' "$1"; }
