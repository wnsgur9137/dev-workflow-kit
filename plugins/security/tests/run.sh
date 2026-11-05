#!/usr/bin/env bash
# security 플러그인 테스트 실행기 (게이트)
#   tests/run.sh            전체 실행
#   tests/run.sh test_x.sh  특정 bash 테스트 파일만
# bash 테스트: tests/test_*.sh 의 test_* 함수를 각각 별도 프로세스에서 실행한다.
# Python 테스트: tests/test_*.py (unittest)
# Docker 가 필요한 통합 테스트는 SEC_TEST_DOCKER=0 이면 건너뛴다.
set -u
TESTS_DIR="$(cd -P "$(dirname "$0")" && pwd -P)"
PLUGIN_DIR="$(dirname "$TESTS_DIR")"
export TESTS_DIR PLUGIN_DIR
pass=0 failed=0 skipped=0 failures=""

files=("$@")
[ ${#files[@]} -gt 0 ] || files=("$TESTS_DIR"/test_*.sh)

for f in "${files[@]}"; do
  case "$f" in /*) ;; *) f="$TESTS_DIR/$f" ;; esac
  [ -f "$f" ] || continue
  echo "# $(basename "$f")"
  # 문법 오류가 있으면 그 뒤 테스트가 조용히 빠지므로 파일 단위로 실패 처리한다
  if ! bash -n "$f" 2>"${TMPDIR:-/tmp}/sec-test-syntax.$$"; then
    failed=$((failed + 1)); failures="$failures $(basename "$f")(문법)"
    echo "FAIL $(basename "$f") 문법 오류"; sed 's/^/    /' "${TMPDIR:-/tmp}/sec-test-syntax.$$"
    rm -f "${TMPDIR:-/tmp}/sec-test-syntax.$$"
    continue
  fi
  rm -f "${TMPDIR:-/tmp}/sec-test-syntax.$$"
  fns=$(bash -c ". '$f' >/dev/null 2>&1; declare -F" | awk '$3 ~ /^test_/ { print $3 }')
  if [ -z "$fns" ]; then
    failed=$((failed + 1)); failures="$failures $(basename "$f")(테스트 0개)"
    echo "FAIL $(basename "$f") 테스트 함수가 없습니다"
    continue
  fi
  for fn in $fns; do
    out=$(
      cd "$TESTS_DIR" || exit 1
      SEC_TMP=$(mktemp -d "${TMPDIR:-/tmp}/sec-test.XXXXXX")
      export SEC_TMP
      trap 'chmod -R u+w "$SEC_TMP" 2>/dev/null; rm -rf "$SEC_TMP"' EXIT
      # shellcheck disable=SC1091
      . "$TESTS_DIR/lib/assert.sh"
      # shellcheck disable=SC1090
      . "$f"
      "$fn"
    )
    rc=$?
    if [ $rc -eq 0 ]; then
      pass=$((pass + 1)); echo "ok   $fn"
    elif [ $rc -eq 77 ]; then
      skipped=$((skipped + 1)); echo "skip $fn ${out}"
    else
      failed=$((failed + 1)); failures="$failures $fn"
      echo "FAIL $fn"
      [ -n "$out" ] && printf '%s\n' "$out" | sed 's/^/    /'
    fi
  done
done

if [ $# -eq 0 ]; then
  echo "# python (unittest)"
  pyout=$(cd "$TESTS_DIR" && python3 -m unittest discover -s "$TESTS_DIR" -p 'test_*.py' -v 2>&1)
  pyrc=$?
  printf '%s\n' "$pyout" | sed 's/^/    /'
  if [ $pyrc -ne 0 ]; then
    failed=$((failed + 1)); failures="$failures python-unittest"
  fi
fi

echo
echo "결과: bash 통과 $pass · 실패 $failed · 건너뜀 $skipped (python 은 위 unittest 요약 참조)"
if [ $failed -ne 0 ]; then
  echo "실패:$failures"
  exit 1
fi
