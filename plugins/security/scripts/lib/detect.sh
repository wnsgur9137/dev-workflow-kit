# shellcheck shell=bash
# 스택 프로파일 감지 — common.sh 다음에 source 한다.
# 실제 파싱·감지는 profiles.py(표준 라이브러리만 사용)가 한다.
#   docs/security/07 스택별 설계/스택 프로파일 개요.md#감지 규칙

SEC_PROFILES_PY="$SEC_PLUGIN/scripts/lib/profiles.py"
SEC_PROFILE_DIR="${SEC_PROFILE_DIR:-$SEC_PLUGIN/profiles}"

# sec_require_python — python3 3.8 이상 확인 (normalize.py·profiles.py 실행에 필요)
sec_require_python() {
  if ! command -v python3 >/dev/null 2>&1; then
    sec_err "python3 를 찾을 수 없습니다 (3.8 이상 필요). macOS: xcode-select --install 또는 brew install python"
    return 1
  fi
  if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
    sec_err "python3 3.8 이상이 필요합니다 (현재: $(python3 -V 2>&1))"
    return 1
  fi
}

# sec_detect_profiles <target> [profile,profile...]
#   stdout: 한 줄에 "<프로파일>\t<하위 경로>" (루트는 ".")
#   두 번째 인자가 있으면 감지하지 않고 그 프로파일을 루트에 강제 적용한다.
sec_detect_profiles() {
  local target=$1 forced=${2:-}
  sec_require_python || return 1
  python3 "$SEC_PROFILES_PY" --dir "$SEC_PROFILE_DIR" detect "$target" --profiles "$forced"
}

# sec_profile_labels — sec_detect_profiles 출력을 "flutter, android:android/" 형태로
sec_profile_labels() {
  awk -F '\t' '
    NF >= 2 { label = ($2 == ".") ? $1 : $1 ":" $2 "/"; out = out (n++ ? ", " : "") label }
    END { print (n ? out : "(감지 없음 — 공통 기반만 적용)") }
  '
}
