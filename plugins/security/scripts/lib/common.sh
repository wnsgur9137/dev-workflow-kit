# shellcheck shell=bash
# security 플러그인 공통 라이브러리 — 스캔 스크립트가 source 한다.
#
# 제공 기능
#   - 경로 별칭: SEC_PLUGIN($PLUGIN), SEC_DATA($DATA), SEC_CONF($CONF)
#   - 데이터·설정 폴더 생성 (폴더 700 / 파일 600)
#   - run-id 생성과 리포트 폴더 준비
#   - 점검 대상 경로 검증 (realpath, 금지 경로)
#   - 로그 출력
#   - Docker 런타임 사전 점검 D1~D6
#   - images.lock / rules.lock 조회
#
# macOS 기본 bash 3.2 에서 동작해야 한다 (연관 배열·mapfile·${v,,} 금지).

# ---------------------------------------------------------------------------
# 경로
# ---------------------------------------------------------------------------
# CDPATH 가 export 돼 있으면 cd 가 다른 폴더로 이동하며 경로를 stdout 에 찍는다 — 정규화 결과가 오염된다
unset CDPATH
SEC_PLUGIN="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
SEC_DATA="${DWK_SECURITY_DATA_DIR:-$HOME/.local/share/dev-workflow-kit/security}"
SEC_CONF="${DWK_SECURITY_CONF_DIR:-$HOME/.config/dev-workflow-kit/security}"
SEC_IMAGES_LOCK="${SEC_IMAGES_LOCK:-$SEC_PLUGIN/docker/images.lock}"
SEC_RULES_LOCK="${SEC_RULES_LOCK:-$SEC_PLUGIN/rules.lock}"

# 스캔 종류별 권장 VM 메모리(GiB) — docs/security/01 개요/Docker 런타임.md
sec_recommended_mem_gib() {
  case "$1" in
    code) echo 4 ;;
    web) echo 6 ;;
    app) echo 8 ;;
    *) echo 4 ;;
  esac
}

# ---------------------------------------------------------------------------
# 로그 (모두 stderr — stdout 은 결과 경로 등 기계용 출력에만 쓴다)
# ---------------------------------------------------------------------------
SEC_LOG_FILE=""

_sec_emit() {
  local level=$1
  shift
  printf '[security] %s%s\n' "$level" "$*" >&2
  if [ -n "$SEC_LOG_FILE" ]; then
    printf '%s %s%s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$level" "$*" >>"$SEC_LOG_FILE" 2>/dev/null || true
  fi
}
sec_log() { _sec_emit "" "$@"; }
sec_warn() { _sec_emit "경고: " "$@"; }
sec_err() { _sec_emit "오류: " "$@"; }
sec_die() {
  sec_err "$@"
  exit 1
}

# ---------------------------------------------------------------------------
# 데이터·설정 폴더
# ---------------------------------------------------------------------------
sec_init_dirs() {
  umask 077
  mkdir -p "$SEC_DATA/data" "$SEC_DATA/reports" "$SEC_CONF" || return 1
  chmod 700 "$SEC_DATA" "$SEC_DATA/data" "$SEC_DATA/reports" "$SEC_CONF" || return 1
}

# sec_new_run <code|app|web>  → SEC_RUN_ID, SEC_RUN_DIR 설정, raw/ 생성
sec_new_run() {
  local kind=$1 base n=1
  case "$kind" in
    code | app | web) ;;
    *)
      sec_err "알 수 없는 스캔 종류: $kind"
      return 1
      ;;
  esac
  sec_init_dirs || return 1
  base="$(date '+%Y%m%d-%H%M%S')-$kind"
  SEC_RUN_ID=$base
  # mkdir(-p 없이)의 성공 여부로 선점한다 — 동시 실행해도 두 스캔이 같은 폴더를 쓰지 않는다
  while ! mkdir "$SEC_DATA/reports/$SEC_RUN_ID" 2>/dev/null; do
    n=$((n + 1))
    [ "$n" -le 1000 ] || return 1
    SEC_RUN_ID="$base-$n"
  done
  SEC_RUN_DIR="$SEC_DATA/reports/$SEC_RUN_ID"
  mkdir "$SEC_RUN_DIR/raw" || return 1
  chmod 700 "$SEC_RUN_DIR" "$SEC_RUN_DIR/raw"
  SEC_LOG_FILE="$SEC_RUN_DIR/run.log"
  : >"$SEC_LOG_FILE"
  chmod 600 "$SEC_LOG_FILE"
  export SEC_RUN_ID SEC_RUN_DIR
}

# ---------------------------------------------------------------------------
# 경로 정규화·검증
# ---------------------------------------------------------------------------

# sec_realpath <path> — 심볼릭 링크를 모두 풀어 절대 경로 출력. 없으면 실패.
#   realpath(1) 가 있으면 우선 쓴다 — macOS 의 /bin/realpath 는 대소문자를 디스크의 실제 이름으로 바로잡는다
#   (대소문자를 구분하지 않는 APFS 에서 '/users/me' 로 금지 경로 비교를 우회하지 못하게).
sec_realpath() {
  local p=$1 link dir out="" i=0
  [ -n "$p" ] || return 1
  case "$p" in
    /*) ;;
    *) p="./$p" ;; # '-' 같은 이름이 cd 옵션으로 해석되지 않게
  esac
  [ -e "$p" ] || return 1
  if command -v realpath >/dev/null 2>&1; then
    out=$(realpath "$p" 2>/dev/null) || out=""
  fi
  if [ -z "$out" ]; then
    if [ -d "$p" ]; then
      out=$(cd -P -- "$p" 2>/dev/null && pwd -P) || return 1
    else
      while [ -L "$p" ]; do
        i=$((i + 1))
        [ "$i" -le 40 ] || return 1
        link=$(readlink "$p") || return 1
        case "$link" in
          /*) p=$link ;;
          *) p="$(dirname -- "$p")/$link" ;;
        esac
      done
      if [ -d "$p" ]; then
        out=$(cd -P -- "$p" 2>/dev/null && pwd -P) || return 1
      else
        [ -e "$p" ] || return 1
        dir=$(cd -P -- "$(dirname -- "$p")" 2>/dev/null && pwd -P) || return 1
        out="${dir%/}/$(basename -- "$p")"
      fi
    fi
  fi
  # '//x' 같은 중복 슬래시를 하나로 — 금지 경로 비교가 우회되지 않게 한다
  printf '%s\n' "$out" | sed -e 's#//*#/#g'
}

# _sec_fold <path> — 비교용 정규형: 소문자 + (비ASCII 면) 유니코드 NFC.
#   realpath 가 없거나 대소문자를 바로잡지 못하는 환경에서도 금지 경로 비교가 우회되지 않게 하는 이중 장치.
#   대소문자를 구분하는 파일시스템에서는 더 보수적으로(더 많이) 거부할 뿐이다.
_sec_fold() {
  if printf '%s' "$1" | LC_ALL=C grep -q '[^ -~]' && command -v python3 >/dev/null 2>&1; then
    python3 -c 'import sys, unicodedata; print(unicodedata.normalize("NFC", sys.argv[1]).casefold())' "$1"
  else
    printf '%s\n' "$1" | LC_ALL=C tr '[:upper:]' '[:lower:]'
  fi
}

# _sec_is_within <path> <dir> — path 가 dir 자신이거나 그 하위이면 참 (대소문자·정규화 무시)
_sec_is_within() {
  local a b
  a=$(_sec_fold "$1")
  b=$(_sec_fold "${2%/}")
  [ -n "$b" ] || b=/
  [ "$a" = "$b" ] && return 0
  [ "$b" = "/" ] && return 0
  case "$a" in
    "$b"/*) return 0 ;;
  esac
  return 1
}

# _sec_resolved_or_raw <path> — 존재하면 realpath, 없으면 그대로
_sec_resolved_or_raw() {
  sec_realpath "$1" 2>/dev/null || printf '%s\n' "$1"
}

# 자격증명·개인 설정 폴더 (홈 기준). 대상이 이 안이거나, 이것을 포함하면 거부한다.
SEC_HOME_DENY=".ssh .aws .azure .gnupg .kube .docker .config .claude .netrc .gradle .android
  .m2 .cargo .npmrc .pypirc .git-credentials .password-store .terraform.d .oci .gcloud
  .local/share/keyrings Library"
SEC_SYSTEM_DENY="/etc /private/etc /System /usr /bin /sbin /Library /private/var/root"
# scan-app 이 받는 산출물 확장자 (file 종류)
SEC_ARTIFACT_EXTS="apk aab ipa"

# sec_validate_target <path> <dir|file>
#   검증에 통과하면 정규화된 절대 경로를 stdout 으로 출력한다.
#   금지: 루트·홈 디렉터리 자체와 그 상위, 최상위 폴더, 자격증명·시스템 폴더(심볼릭 링크를 푼 실제 위치 포함),
#         툴킷 데이터·설정 폴더와 겹치는 경로, docker 마운트 문법을 깨는 문자.
#   file 종류는 앱 산출물 확장자(apk·aab·ipa)만 허용한다.
sec_validate_target() {
  local raw=$1 kind=${2:-dir} resolved home depth d dr ext
  if [ -z "$raw" ]; then
    sec_err "점검 대상 경로가 비어 있습니다."
    return 1
  fi
  if [ ! -e "$raw" ]; then
    sec_err "점검 대상이 없습니다: $raw"
    return 1
  fi
  resolved=$(sec_realpath "$raw") || {
    sec_err "경로를 정규화할 수 없습니다: $raw"
    return 1
  }
  case "$kind" in
    dir) [ -d "$resolved" ] || {
      sec_err "디렉터리가 아닙니다: $resolved"
      return 1
    } ;;
    file)
      [ -f "$resolved" ] || {
        sec_err "일반 파일이 아닙니다: $resolved"
        return 1
      }
      ext=$(printf '%s' "${resolved##*.}" | LC_ALL=C tr '[:upper:]' '[:lower:]')
      case " $SEC_ARTIFACT_EXTS " in
        *" $ext "*) ;;
        *)
          sec_err "앱 산출물(${SEC_ARTIFACT_EXTS// /, })만 점검할 수 있습니다: $resolved"
          return 1
          ;;
      esac
      ;;
    *)
      sec_err "알 수 없는 대상 종류: $kind"
      return 1
      ;;
  esac

  # docker -v / --mount 문법을 깨거나 로그를 오염시키는 문자
  case "$resolved" in
    *:* | *,* | *"
"*)
      sec_err "경로에 ':' ',' 줄바꿈 문자는 쓸 수 없습니다: $resolved"
      return 1
      ;;
  esac

  home=$(_sec_resolved_or_raw "$HOME")

  # 루트, 홈 자체, 홈의 상위 경로 (홈 전체가 마운트된다)
  if [ "$resolved" = "/" ] || _sec_is_within "$home" "$resolved" || _sec_is_within "$HOME" "$resolved"; then
    sec_err "홈 디렉터리 전체 또는 그 상위 경로는 점검할 수 없습니다: $resolved"
    return 1
  fi

  # 최상위 폴더(/tmp, /opt, /Volumes ...) 자체
  depth=$(printf '%s' "$resolved" | tr -cd '/' | wc -c | tr -d ' ')
  if [ "$depth" -le 1 ]; then
    sec_err "최상위 폴더는 점검할 수 없습니다. 프로젝트 폴더를 지정하세요: $resolved"
    return 1
  fi
  for d in /private/var /private/tmp /private/var/folders /private/etc; do
    if [ "$(_sec_fold "$resolved")" = "$(_sec_fold "$d")" ]; then
      sec_err "시스템 공용 폴더는 점검할 수 없습니다: $resolved"
      return 1
    fi
  done

  # 자격증명·시스템 폴더: 그 안이거나, 그것(심볼릭 링크를 푼 실제 위치 포함)을 포함하면 거부
  #   예) ~/.aws -> ~/dotfiles/aws 이면 ~/dotfiles/aws 와 ~/dotfiles 도 거부
  for d in $SEC_HOME_DENY; do
    for dr in "$home/$d" "$(_sec_resolved_or_raw "$home/$d")"; do
      if _sec_is_within "$resolved" "$dr" || { [ -e "$dr" ] && _sec_is_within "$dr" "$resolved"; }; then
        sec_err "자격증명·개인 설정 폴더와 겹치는 경로는 점검할 수 없습니다: $resolved (${d})"
        return 1
      fi
    done
  done
  for d in $SEC_SYSTEM_DENY; do
    for dr in "$d" "$(_sec_resolved_or_raw "$d")"; do
      if _sec_is_within "$resolved" "$dr"; then
        sec_err "시스템 폴더는 점검할 수 없습니다: $resolved"
        return 1
      fi
    done
  done

  # 툴킷 데이터·설정 폴더(리포트, MobSF 키)를 포함하거나 그 안인 경로
  for d in "$(_sec_resolved_or_raw "$SEC_DATA")" "$(_sec_resolved_or_raw "$SEC_CONF")"; do
    if _sec_is_within "$d" "$resolved" || _sec_is_within "$resolved" "$d"; then
      sec_err "툴킷 데이터·설정 폴더와 겹치는 경로는 점검할 수 없습니다: $resolved"
      return 1
    fi
  done

  printf '%s\n' "$resolved"
}

# ---------------------------------------------------------------------------
# lock 파일
# ---------------------------------------------------------------------------
# images.lock 형식 (공백 구분, # 주석):
#   <name> <image> <tag> <digest> <platforms>
#   예) semgrep semgrep/semgrep 1.100.0 sha256:<64hex> linux/amd64,linux/arm64

# sec_lock_line <name> — images.lock 에서 해당 이름의 줄 출력
sec_lock_line() {
  [ -f "$SEC_IMAGES_LOCK" ] || return 1
  awk -v n="$1" '!/^[[:space:]]*(#|$)/ && $1 == n { print; found=1; exit } END { exit !found }' "$SEC_IMAGES_LOCK"
}

# sec_image_ref <name> — docker run 에 쓸 <image>@<digest>
sec_image_ref() {
  local line
  line=$(sec_lock_line "$1") || return 1
  printf '%s\n' "$line" | awk '{ print $2 "@" $4 }'
}

# sec_image_field <name> <tag|digest|platforms|image>
sec_image_field() {
  local line col
  line=$(sec_lock_line "$1") || return 1
  case "$2" in
    image) col=2 ;;
    tag) col=3 ;;
    digest) col=4 ;;
    platforms) col=5 ;;
    *) return 1 ;;
  esac
  printf '%s\n' "$line" | awk -v c="$col" '{ print $c }'
}

# sec_validate_images_lock — 형식 검사 (열 개수, digest 형식, 이름 중복)
sec_validate_images_lock() {
  [ -f "$SEC_IMAGES_LOCK" ] || {
    sec_err "images.lock 이 없습니다: $SEC_IMAGES_LOCK"
    return 1
  }
  awk '
    /^[[:space:]]*(#|$)/ { next }
    {
      if (NF != 5) { printf "images.lock:%d: 열이 5개가 아닙니다\n", NR; bad=1; next }
      if ($4 !~ /^sha256:[0-9a-f]+$/ || length($4) != 71) { printf "images.lock:%d: digest 형식 오류: %s\n", NR, $4; bad=1 }
      if ($5 !~ /^linux\/[a-z0-9]+(,linux\/[a-z0-9]+)*$/) { printf "images.lock:%d: platforms 형식 오류: %s\n", NR, $5; bad=1 }
      if (seen[$1]++) { printf "images.lock:%d: 이름 중복: %s\n", NR, $1; bad=1 }
    }
    END { exit bad }
  ' "$SEC_IMAGES_LOCK" >&2
}

# rules.lock 형식 (공백 구분, # 주석):
#   <name> <git-url> <commit-sha40> <paths(쉼표 구분)>
sec_validate_rules_lock() {
  [ -f "$SEC_RULES_LOCK" ] || {
    sec_err "rules.lock 이 없습니다: $SEC_RULES_LOCK"
    return 1
  }
  awk '
    /^[[:space:]]*(#|$)/ { next }
    {
      if (NF != 4) { printf "rules.lock:%d: 열이 4개가 아닙니다\n", NR; bad=1; next }
      if ($2 !~ /^https:\/\//) { printf "rules.lock:%d: https URL 이 아닙니다: %s\n", NR, $2; bad=1 }
      if ($3 !~ /^[0-9a-f]+$/ || length($3) != 40) { printf "rules.lock:%d: 커밋 해시 형식 오류: %s\n", NR, $3; bad=1 }
      if (seen[$1]++) { printf "rules.lock:%d: 이름 중복: %s\n", NR, $1; bad=1 }
    }
    END { exit bad }
  ' "$SEC_RULES_LOCK" >&2
}

# ---------------------------------------------------------------------------
# Docker 런타임 사전 점검 D1~D6
# ---------------------------------------------------------------------------
# sec_preflight <code|app|web> [image-name ...]
#   하나라도 실패하면 안내를 출력하고 1 반환 (컨테이너를 띄우지 않는다).
#   D5(메모리)는 경고만 한다. 결과 요약은 SEC_DOCKER_CONTEXT 등에 남긴다.
export SEC_DOCKER_CONTEXT=""
export SEC_DOCKER_MEM_BYTES=""

sec_preflight() {
  local kind=$1 compose_ver major components mem rec_gib rec_bytes name ref missing=""
  shift

  # D1 docker CLI
  if ! command -v docker >/dev/null 2>&1; then
    sec_err "[D1] docker CLI 를 찾을 수 없습니다."
    sec_log "  Docker 호환 런타임이 필요합니다. 무료 권장: Colima"
    sec_log "    brew install colima docker docker-compose"
    sec_log "    colima start --cpu 4 --memory 8 --disk 60"
    sec_log "  자세히: docs/security/01 개요/Docker 런타임.md"
    return 1
  fi

  # D2 엔진 실행 중
  if ! docker info >/dev/null 2>&1; then
    sec_err "[D2] Docker 엔진에 연결할 수 없습니다 (꺼져 있음)."
    sec_log "  Colima: colima start   ·   Docker Desktop: 앱 실행"
    sec_log "  여러 런타임이 있으면 docker context ls 로 현재 컨텍스트를 확인하세요."
    return 1
  fi

  # D3 compose v2 이상
  compose_ver=$(docker compose version --short 2>/dev/null | head -n 1 | tr -d 'v[:space:]')
  major=${compose_ver%%.*}
  case "$major" in
    '' | *[!0-9]*) major=0 ;;
  esac
  if [ "$major" -lt 2 ]; then
    sec_err "[D3] docker compose v2 이상이 필요합니다 (현재: ${compose_ver:-없음})."
    sec_log "  brew install docker-compose 후 ~/.docker/config.json 에"
    sec_log '    "cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]'
    sec_log "  를 추가하세요 (Intel Mac: /usr/local/lib/docker/cli-plugins)."
    return 1
  fi

  # D4 dockerd(moby) 엔진
  components=$(docker version --format '{{range .Server.Components}}{{.Name}} {{end}}' 2>/dev/null)
  case "$components" in
    *[Pp]odman*)
      sec_err "[D4] Podman 엔진은 지원하지 않습니다 (compose·internal 네트워크 동작 차이)."
      sec_log "  Colima, Docker Desktop, Rancher Desktop(dockerd 모드), OrbStack 중 하나를 쓰세요."
      return 1
      ;;
    *Engine*) ;;
    *)
      sec_err "[D4] dockerd(moby) 엔진을 확인할 수 없습니다 (구성요소: ${components:-없음})."
      sec_log "  Rancher Desktop 이면 컨테이너 엔진을 dockerd(moby)로 설정하세요."
      return 1
      ;;
  esac

  SEC_DOCKER_CONTEXT=$(docker context show 2>/dev/null || echo unknown)

  # D5 VM 메모리 (경고만, 10% 여유 허용 — VM 이 보고하는 값은 설정값보다 조금 작다)
  mem=$(docker info --format '{{.MemTotal}}' 2>/dev/null)
  case "$mem" in
    '' | *[!0-9]*) mem="" ;;
  esac
  SEC_DOCKER_MEM_BYTES=$mem
  rec_gib=$(sec_recommended_mem_gib "$kind")
  rec_bytes=$((rec_gib * 1024 * 1024 * 1024 * 9 / 10))
  if [ -z "$mem" ]; then
    sec_warn "[D5] VM 메모리를 확인할 수 없습니다. 권장: ${rec_gib}GB 이상"
  elif [ "$mem" -lt "$rec_bytes" ]; then
    sec_warn "[D5] VM 메모리 $((mem / 1024 / 1024))MB — 이 스캔의 권장치는 ${rec_gib}GB 입니다. 계속 진행합니다."
    sec_log "  Colima: colima stop && colima start --memory ${rec_gib}"
  fi

  # D6 필요한 이미지가 images.lock digest 로 존재 (스캔은 다운로드하지 않는다)
  for name in "$@"; do
    if ! ref=$(sec_image_ref "$name"); then
      sec_err "[D6] images.lock 에 '$name' 항목이 없습니다: $SEC_IMAGES_LOCK"
      return 1
    fi
    if ! docker image inspect "$ref" >/dev/null 2>&1; then
      missing="$missing $ref"
    fi
  done
  if [ -n "$missing" ]; then
    sec_err "[D6] 고정된 digest 의 이미지가 로컬에 없습니다:"
    for ref in $missing; do sec_log "    $ref"; done
    sec_log "  사용자가 직접 실행하세요 (스캔 스크립트는 다운로드하지 않습니다):"
    sec_log "    $SEC_PLUGIN/scripts/update.sh"
    return 1
  fi
  return 0
}
