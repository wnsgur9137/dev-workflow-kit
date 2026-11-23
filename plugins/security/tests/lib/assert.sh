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
# compose_calls <하위 명령> [기록 파일]  — 가짜 docker 기록에서 `docker compose … <하위 명령>` 호출 줄만 고른다.
# 하위 명령 앞뒤에 옵션이 없어도(`docker compose run x`, `docker compose up`) 맞는다 (이슈 #33, PR #44 리뷰 N3)
# 하위 명령은 정규식에 그대로 들어가므로 소문자 단어만 받는다 (PR #51 리뷰 N2) — 글자를 나열해 로케일 정렬 순서와 무관하게 (2차 B).
# 파이프 앞(`compose_calls x | grep`)에서는 서브셸이라 이 fail 이 테스트를 멈추지 못한다 — 인자는 리터럴만 쓴다 (2차 A)
compose_calls() {
  case "$1" in '' | *[!abcdefghijklmnopqrstuvwxyz]*) fail "compose_calls: 하위 명령은 소문자 단어만: '$1'" ;; esac
  grep -E "^docker compose( .*)? $1( |\$)" "${2:-$FAKE_LOG}"
}
