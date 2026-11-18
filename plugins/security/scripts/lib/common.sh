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
  # 파일(run.log)에 먼저 쓴다 — stderr 가 닫혀 있으면 printf 의 SIGPIPE 로 여기서 끝나므로, 순서가 반대면
  # "스택을 내리지 못했습니다" 같은 경고가 run.log 에도 남지 않는다 (이슈 #36, PR #34 8차 R8-N3)
  if [ -n "$SEC_LOG_FILE" ]; then
    printf '%s %s%s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$level" "$*" >>"$SEC_LOG_FILE" 2>/dev/null || true
  fi
  printf '[security] %s%s\n' "$level" "$*" >&2
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

# sec_cleanup_reports — 보관 기간(기본 30일, DWK_SECURITY_RETENTION_DAYS)이 지난 리포트를 지운다
#   스캔마다 자동, scripts/cleanup.sh 와 같은 규칙(scripts/lib/cleanup_reports.py). 실패해도 스캔은 계속한다 — 경고만 낸다.
#   지운 run-id 는 SEC_CLEANED 에 남겨 sec_new_run 이 새 run.log 에 적는다 (PR #38 리뷰 N1)
sec_cleanup_reports() {
  local out err rc days names n
  SEC_CLEANED=""
  err=$(mktemp "${TMPDIR:-/tmp}/dwk-cleanup.XXXXXX") || { sec_warn "오래된 리포트를 정리하지 못했습니다 (임시 파일)"; return 0; }
  # stdout(지운 이름)과 stderr(실패·경고)를 따로 받는다 — 섞으면 실패 원인 대신 지운 이름이 보인다 (리뷰 W1)
  out=$(python3 -I "$SEC_PLUGIN/scripts/lib/cleanup_reports.py" "$SEC_DATA/reports" 2>"$err")
  rc=$?
  days=$(printf '%s\n' "$out" | sed -n '1s/^days=//p')
  names=$(printf '%s\n' "$out" | sed '1{/^days=/d;}')
  n=$(printf '%s' "$names" | grep -c .)
  SEC_CLEANED=$names
  [ "$n" -gt 0 ] && sec_log "보관 기간(${days:-?}일)이 지난 리포트 ${n}개를 지웠습니다"
  if [ "$rc" -ne 0 ] || [ -s "$err" ]; then
    while IFS= read -r line; do [ -n "$line" ] && sec_warn "리포트 정리: $line"; done <"$err"
    [ "$rc" -ne 0 ] && sec_warn "오래된 리포트를 다 정리하지 못했습니다 — $SEC_PLUGIN/scripts/cleanup.sh --dry-run 으로 확인하세요"
  fi
  rm -f "$err"
  return 0
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
  sec_cleanup_reports
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
  if [ -n "${SEC_CLEANED:-}" ]; then
    printf '%s\n' "$SEC_CLEANED" | sed 's/^/보관 기간이 지나 지운 리포트: /' >>"$SEC_LOG_FILE"
  fi
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
  # 따옴표로 감싸 넘긴 경로는 셸이 ~ 를 확장하지 않는다 — 맨 앞의 ~ · ~/ 만 직접 확장한다 (SKILL 은 경로 전체를 인용한다)
  # shellcheck disable=SC2088 # 인용된 ~ 문자 자체를 비교하는 것이 목적이다
  case "$raw" in
    "~") raw=$HOME ;;
    "~/"*) raw="$HOME/${raw#"~/"}" ;;
    "~"*)
      sec_err "~사용자 형식 경로는 지원하지 않습니다. 절대 경로로 지정하세요: $raw"
      return 1
      ;;
  esac
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

# 로컬에서 빌드하는 이미지 (이슈 #35) — 이름 → images.lock 의 베이스 항목 이름. 빌드 문맥은 $SEC_PLUGIN/docker/<이름>/
#   update.sh --images 가 베이스를 digest 로 받은 뒤 빌드하고, 이미지 ID 를 $SEC_DATA/data/images/<이름>.built 에 기록한다.
#   스캔 스크립트는 빌드하지 않는다 — 기록의 입력(Dockerfile + 베이스 digest)이 지금과 같고 그 ID 의 이미지가 있을 때만 쓴다 (D6)
SEC_BUILT_IMAGES="egress-proxy:egress-proxy-base"

# sec_built_base <name> — 로컬 빌드 이미지면 베이스 항목 이름을 출력, 아니면 실패
sec_built_base() {
  local e
  for e in $SEC_BUILT_IMAGES; do
    [ "${e%%:*}" = "$1" ] && { printf '%s\n' "${e#*:}"; return 0; }
  done
  return 1
}

# sec_build_input <name> — 빌드 입력의 sha256: 빌드 문맥 폴더($SEC_PLUGIN/docker/<이름>/)의 모든 파일(상대 경로·내용, 이름순)
#   + 베이스 <image>@<digest>. 하나라도 바뀌면 다시 빌드해야 한다 (Dockerfile 이 COPY 할 파일도 덮는다, PR #37 리뷰 S3)
sec_build_input() {
  local base ref
  base=$(sec_built_base "$1") || return 1
  ref=$(sec_image_ref "$base") || return 1
  python3 -I - "$SEC_PLUGIN/docker/$1" "$ref" 2>/dev/null <<'PY'
import hashlib, os, sys
root, ref = sys.argv[1], sys.argv[2]
if not os.path.isfile(os.path.join(root, "Dockerfile")):
    sys.exit(1)
import stat
# 숨김·편집기 임시 파일은 빼고(빌드 문맥의 .dockerignore 와 같은 규칙), 일반 파일이 아닌 항목(FIFO·링크·장치)은 실패,
# 파일의 실행 비트도 넣는다 — COPY 가 모드를 보존한다 (이슈 #36, PR #37 2차 R2-N1)
def ignored(name):
    return name.startswith(".") or name.endswith("~") or name.endswith(".swp")
h = hashlib.sha256()
for d, dirs, files in os.walk(root):
    dirs[:] = sorted(x for x in dirs if not ignored(x))
    for f in sorted(files):
        if ignored(f):
            continue
        p = os.path.join(d, f)
        st = os.lstat(p)
        if not stat.S_ISREG(st.st_mode):
            sys.exit(1)
        rel = os.path.relpath(p, root).encode()
        with open(p, "rb") as fh:
            data = fh.read()
        h.update(b"F\0%d\0%s\0%d\0%d\0" % (len(rel), rel, 1 if st.st_mode & 0o111 else 0, len(data)) + data)
h.update(b"BASE\0" + ref.encode())
print(h.hexdigest())
PY
}

# sec_valid_image_id <값> — sha256:<64 hex> 인지 (빌드 기록·iidfile 이 같은 검사를 쓴다, 이슈 #36 R2-N3)
sec_valid_image_id() {
  case "$1" in sha256:*) ;; *) return 1 ;; esac
  case "${1#sha256:}" in *[!0-9a-f]*) return 1 ;; esac
  [ ${#1} -eq 71 ]
}

sec_built_record() { printf '%s\n' "$SEC_DATA/data/images/$1.built"; }

# sec_built_id <name> — 기록이 지금 입력과 맞으면 기록한 이미지 ID(sha256:<64 hex>)를 출력.
#   1 기록 없음 · 2 입력 불일치(다시 빌드) · 3 입력 계산 불가(images.lock 베이스·Dockerfile) · 4 기록 손상 (리뷰 N3·N4)
sec_built_id() {
  local input rec_input rec_id
  input=$(sec_build_input "$1") || return 3
  [ -f "$(sec_built_record "$1")" ] || return 1
  read -r rec_input rec_id <"$(sec_built_record "$1")" || return 4
  sec_valid_image_id "$rec_id" || return 4
  [ "$rec_input" = "$input" ] || return 2
  printf '%s\n' "$rec_id"
}

# sec_built_verify <name> <이미지 ID> — 그 이미지가 있고 지금 입력으로 빌드된 것(라벨 dwk.security.build-input)인지.
#   기록 파일만 바꿔 다른 로컬 이미지(예: 옛 kalaksi/tinyproxy)를 프록시로 쓰게 할 수 없게 한다 (PR #37 리뷰 W1)
sec_built_verify() {
  local label
  label=$(docker image inspect --format '{{index .Config.Labels "dwk.security.build-input"}}' "$2" 2>/dev/null) || return 1
  # 빈 값 검사: 입력 계산이 실패해 양쪽이 빈 문자열일 때 같다고 보지 않게 (지우지 말 것, R2-N3)
  [ -n "$label" ] && [ "$label" = "$(sec_build_input "$1")" ]
}

# sec_image_ref <name> — docker run 에 쓸 <image>@<digest>. 로컬 빌드 이미지는 기록한 이미지 ID (바뀌지 않는 참조)
sec_image_ref() {
  local line
  if sec_built_base "$1" >/dev/null; then
    sec_built_id "$1"
    return
  fi
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
      # name 은 $DATA/data/<name> 이 되어 rm -rf·mv 에 쓰인다 — 경로 문자·예약 이름(osv) 금지
      if ($1 !~ /^[a-z0-9][a-z0-9_-]*$/) { printf "rules.lock:%d: 이름은 영소문자·숫자·_·- 만 씁니다: %s\n", NR, $1; bad=1 }
      if ($1 == "osv") { printf "rules.lock:%d: osv 는 OSV DB 폴더 이름이라 쓸 수 없습니다\n", NR; bad=1 }
    }
    END { exit bad }
  ' "$SEC_RULES_LOCK" >&2
}

# sec_rules_lock_entry <name> — rules.lock 의 해당 항목을 "<commit> <paths>" 로 출력 (없으면 1)
sec_rules_lock_entry() {
  awk -v n="$1" '!/^[[:space:]]*(#|$)/ && $1 == n { print $3, $4; found=1; exit } END { exit !found }' "$SEC_RULES_LOCK"
}

# sec_rules_installed_match <설치 폴더> <commit> <paths> — 설치된 .commit 이 같은 커밋·paths 인지
sec_rules_installed_match() {
  local f="$1/.commit"
  [ -f "$f" ] || return 1
  [ "$(sed -n 1p "$f")" = "$2" ] && [ "$(sed -n 3p "$f")" = "$3" ]
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
  local kind=$1 compose_ver major components mem rec_gib rec_bytes name ref missing="" NL=$'\n'
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

  # D6 필요한 이미지가 images.lock digest 로 존재 (스캔은 다운로드하지 않는다).
  #   로컬 빌드 이미지는 빌드 기록이 지금 Dockerfile·베이스와 맞고 그 ID 의 이미지가 있어야 한다 (스캔은 빌드하지 않는다)
  for name in "$@"; do
    if sec_built_base "$name" >/dev/null; then
      ref=$(sec_built_id "$name")
      case $? in
        0)
          if ! docker image inspect "$ref" >/dev/null 2>&1; then
            missing="$missing$NL$name — 빌드한 이미지($ref)가 없습니다"
          elif ! sec_built_verify "$name" "$ref"; then
            missing="$missing$NL$name — 빌드 기록이 가리키는 이미지($ref)가 지금 빌드 입력으로 만든 것이 아닙니다"
          fi
          ;;
        2) missing="$missing$NL$name — Dockerfile 또는 베이스가 바뀌어 다시 빌드해야 합니다" ;;
        3) missing="$missing$NL$name — 빌드 입력을 계산할 수 없습니다 (images.lock 의 베이스 항목·$SEC_PLUGIN/docker/$name/Dockerfile 확인)" ;;
        4) missing="$missing$NL$name — 빌드 기록이 손상됐습니다" ;;
        *) missing="$missing$NL$name — 로컬 빌드 기록이 없습니다" ;;
      esac
      continue
    fi
    if ! ref=$(sec_image_ref "$name"); then
      sec_err "[D6] images.lock 에 '$name' 항목이 없습니다: $SEC_IMAGES_LOCK"
      return 1
    fi
    if ! docker image inspect "$ref" >/dev/null 2>&1; then
      missing="$missing$NL$ref"
    fi
  done
  if [ -n "$missing" ]; then
    sec_err "[D6] 필요한 이미지가 준비되지 않았습니다:"
    printf '%s\n' "${missing#"$NL"}" | while IFS= read -r ref; do sec_log "    $ref"; done
    sec_log "  사용자가 직접 실행하세요 (스캔 스크립트는 다운로드·빌드하지 않습니다):"
    # D6 는 이미지만 본다 — --images 로 충분하다 (인자 없이 돌리면 OSV DB 까지 받는다, PR #37 리뷰 N2)
    sec_log "    $SEC_PLUGIN/scripts/update.sh --images"
    return 1
  fi
  return 0
}
