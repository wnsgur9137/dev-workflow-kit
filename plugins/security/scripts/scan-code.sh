#!/usr/bin/env bash
# /security:scan-code — 소스 저장소 점검 (Gitleaks · Semgrep · OSV-Scanner, 네트워크 N0)
#
# 사용: scan-code.sh <저장소 경로> [--profile=a,b]
#
# - 모든 컨테이너는 --network none, 읽기 전용 루트, 권한 제거, 대상은 :ro 마운트
# - 이미지·규칙·OSV DB 를 받지 않는다 (없으면 update.sh 안내 후 종료)
# - 결과: $DATA/reports/<run-id>/{raw/,findings.json,summary.md,meta.json}
# - stdout 마지막 줄: summary.md 경로
#   docs/security/03 워크플로/scan-code.md
set -u
umask 077

SELF_DIR="$(cd -P "$(dirname "$0")" && pwd -P)"
# shellcheck source=scripts/lib/common.sh
. "$SELF_DIR/lib/common.sh"
# shellcheck source=scripts/lib/detect.sh
. "$SELF_DIR/lib/detect.sh"

usage() {
  cat >&2 <<'EOF'
사용: /security:scan-code <저장소 경로> [--profile=<이름,...>]
  --profile   스택 감지 대신 프로파일 강제 지정 (ios, android, flutter, react-native, web, server)
EOF
}

TARGET_ARG=""
FORCED_PROFILES=""
for arg in "$@"; do
  case "$arg" in
    --profile=*) FORCED_PROFILES=${arg#--profile=} ;;
    -h | --help)
      usage
      exit 0
      ;;
    -*)
      # 알 수 없는 옵션은 거부한다 (도구 인자 주입 방지)
      sec_err "알 수 없는 옵션: $arg"
      usage
      exit 2
      ;;
    *)
      if [ -n "$TARGET_ARG" ]; then
        sec_err "점검 대상은 하나만 지정합니다."
        exit 2
      fi
      TARGET_ARG=$arg
      ;;
  esac
done
[ -n "$TARGET_ARG" ] || {
  usage
  exit 2
}
case "$FORCED_PROFILES" in
  *[!a-z0-9,-]*)
    sec_err "--profile 값은 영소문자·숫자·쉼표·하이픈만 씁니다: $FORCED_PROFILES"
    exit 2
    ;;
esac

TARGET=$(sec_validate_target "$TARGET_ARG" dir) || exit 1
sec_require_python || exit 1

TOOLS="semgrep gitleaks osv-scanner"
# shellcheck disable=SC2086
sec_preflight code $TOOLS || exit 1

# 규칙·DB 존재 확인 (스캔은 다운로드하지 않는다)
RULES_DIR="$SEC_DATA/data/semgrep-rules"
OSV_DB="$SEC_DATA/data/osv"
if [ ! -f "$RULES_DIR/.commit" ] || [ ! -f "$OSV_DB/UPDATED_AT" ]; then
  sec_err "[D6] Semgrep 규칙 또는 OSV 오프라인 DB 가 없습니다."
  sec_log "  사용자가 직접 실행하세요: $SEC_PLUGIN/scripts/update.sh"
  exit 1
fi
RULES_COMMIT=$(head -n 1 "$RULES_DIR/.commit")
# 설치된 규칙이 rules.lock 과 다르면(플러그인 갱신 후 update.sh 미실행) 알린다 — 이미지 digest 검사(D6)와 같은 취지
RULES_LOCK_ENTRY=$(sec_rules_lock_entry semgrep-rules 2>/dev/null) || RULES_LOCK_ENTRY=""
RULES_MISMATCH=""
if [ -n "$RULES_LOCK_ENTRY" ] && ! sec_rules_installed_match "$RULES_DIR" "${RULES_LOCK_ENTRY%% *}" "${RULES_LOCK_ENTRY#* }"; then
  RULES_MISMATCH="설치된 Semgrep 규칙이 rules.lock 과 다릅니다 (커밋 또는 paths) — 사용자가 터미널에서 update.sh --rules 를 실행하세요."
fi
OSV_UPDATED=$(head -n 1 "$OSV_DB/UPDATED_AT")

# 이미지 참조
IMG_SEMGREP=$(sec_image_ref semgrep)
IMG_GITLEAKS=$(sec_image_ref gitleaks)
IMG_OSV=$(sec_image_ref osv-scanner)

# 공통 docker run 옵션: 네트워크 차단, 읽기 전용 루트, 권한 제거, 호스트 사용자로 실행
# (bash 3.2 호환 인덱스 배열 — 경로에 공백이 있어도 안전)
DOCKER_HARDEN=(--rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges
  --pids-limit 512 --user "$(id -u):$(id -g)" -e HOME=/tmp)

# [D7] 마운트 가시성 — 런타임 VM 이 대상 경로를 공유하지 않으면 컨테이너에는 빈 폴더로 보여
#      "결과 0건" 으로 조용히 끝난다 (Colima 기본 설정은 홈 디렉터리만 공유).
if [ -n "$(ls -A "$TARGET" 2>/dev/null)" ]; then
  probe_err=$(mktemp "${TMPDIR:-/tmp}/sec-d7.XXXXXX") || sec_die "임시 파일을 만들 수 없습니다."
  trap 'rm -f "$probe_err"' EXIT
  seen=$(docker run "${DOCKER_HARDEN[@]}" --tmpfs /tmp:rw,size=8m -v "$TARGET:/src:ro" --entrypoint sh "$IMG_GITLEAKS" -c 'ls -A /src | head -n 1' 2>"$probe_err")
  probe_rc=$?
  probe_msg=$(tail -n 3 "$probe_err" | tr '\n' ' ' | cut -c1-300)
  rm -f "$probe_err"
  trap - EXIT
  # 컨테이너 자체가 실패한 경우(이미지·런타임 오류)를 마운트 공유 문제로 잘못 안내하지 않는다
  if [ $probe_rc -ne 0 ]; then
    sec_err "[D7] 대상 폴더 확인용 컨테이너를 실행하지 못했습니다 (종료코드 $probe_rc): ${probe_msg:-출력 없음}"
    sec_log "  docker info 로 런타임 상태를 확인하고, 이미지가 손상됐으면 update.sh --images 를 다시 실행하세요."
    exit 1
  fi
  if [ -z "$seen" ]; then
    sec_err "[D7] 컨테이너에서 대상 폴더가 비어 보입니다 — Docker 런타임이 이 경로를 공유하지 않습니다: $TARGET"
    sec_log "  Colima 는 기본적으로 홈 디렉터리만 공유합니다. 프로젝트를 홈 아래로 옮기거나"
    sec_log "  ~/.colima/default/colima.yaml 의 mounts 에 경로를 추가한 뒤 colima restart 하세요."
    exit 1
  fi
fi

sec_new_run code || sec_die "리포트 폴더를 만들 수 없습니다."
RAW="$SEC_RUN_DIR/raw"
STATUS="$RAW/status.tsv"
: >"$STATUS"
STARTED_AT=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
sec_log "run-id: $SEC_RUN_ID"
sec_log "대상: $TARGET"

# 프로파일 감지
PROFILES_TSV="$RAW/profiles.tsv"
if ! sec_detect_profiles "$TARGET" "$FORCED_PROFILES" >"$PROFILES_TSV" 2>"$RAW/detect.log"; then
  sec_die "프로파일 감지 실패: $(tail -n 3 "$RAW/detect.log")"
fi
sec_log "프로파일: $(sec_profile_labels <"$PROFILES_TSV")"

# Semgrep 설정 조립: generic + 감지된 프로파일의 언어 규칙셋 + 프로파일 커스텀 규칙 + 사용자 커스텀 규칙
PLAN="$RAW/plan.tsv"
if ! python3 "$SEC_PROFILES_PY" --dir "$SEC_PROFILE_DIR" plan "$PROFILES_TSV" \
  --rules-dir "$RULES_DIR" --custom-dir "$SEC_PLUGIN/rules/custom" >"$PLAN" 2>>"$RAW/detect.log"; then
  sec_die "스캔 계획 생성 실패: $(tail -n 3 "$RAW/detect.log")"
fi

SEMGREP_ARGS=()
SEMGREP_MOUNTS=()
WARNINGS_FILE="$RAW/warnings.txt"
: >"$WARNINGS_FILE"
[ -n "$RULES_MISMATCH" ] && printf '%s\n' "$RULES_MISMATCH" >>"$WARNINGS_FILE"
while IFS="$(printf '\t')" read -r kind value; do
  case "$kind" in
    ruleset) SEMGREP_ARGS+=(--config "/rules/$value") ;;
    custom)
      SEMGREP_MOUNTS+=(-v "$SEC_PLUGIN/rules/custom/$value:/custom/$value:ro")
      SEMGREP_ARGS+=(--config "/custom/$value")
      ;;
    exclude) SEMGREP_ARGS+=(--exclude "$value") ;;
    warning) printf '%s\n' "$value" >>"$WARNINGS_FILE" ;;
  esac
done <"$PLAN"
# Python 가상환경(pyvenv.cfg 와 site-packages 가 있는 폴더)은 이름과 상관없이 Semgrep 점검에서 뺀다 — --no-git-ignore 로
# git 이 무시하던 가상환경까지 보면 서드파티 코드의 결과가 리포트를 덮는다 (PR #30 3차 리뷰 W-A). 뺀 폴더는 summary 에
# 드러낸다. 이름이 .venv 인 폴더는 Semgrep 기본 무시 목록이 이미 빼므로 경고에서 뺀다 (경고 피로, 4차 리뷰 S-2).
VENVS_TSV="$RAW/venvs.tsv"
if ! python3 "$SEC_PROFILES_PY" --dir "$SEC_PROFILE_DIR" venvs "$TARGET" >"$VENVS_TSV" 2>>"$RAW/detect.log"; then
  sec_die "가상환경 폴더 확인 실패: $(tail -n 3 "$RAW/detect.log")"
fi
if VENV_LIMIT_LINE=$(grep -m 1 '^가상환경 확인:' "$RAW/detect.log" 2>/dev/null); then
  printf '%s\n' "$VENV_LIMIT_LINE" >>"$WARNINGS_FILE"
fi
VENV_LIST=""
VENV_COUNT=0
while IFS="$(printf '\t')" read -r rel pat; do
  [ -n "$pat" ] || continue
  SEMGREP_ARGS+=(--exclude "$pat")
  case "$rel" in .venv | */.venv) continue ;; esac
  VENV_COUNT=$((VENV_COUNT + 1))
  [ $VENV_COUNT -le 5 ] && VENV_LIST="$VENV_LIST$rel/ "
done <"$VENVS_TSV"
if [ $VENV_COUNT -gt 0 ]; then
  [ $VENV_COUNT -gt 5 ] && VENV_LIST="${VENV_LIST}외 $((VENV_COUNT - 5))개(전체 목록: raw/venvs.tsv) "
  printf '%s\n' "Python 가상환경(pyvenv.cfg 와 site-packages 가 있는 폴더) ${VENV_COUNT}개를 Semgrep 점검에서 뺐습니다: ${VENV_LIST}— 소스 폴더라면 그 안의 pyvenv.cfg 를 확인하세요." >>"$WARNINGS_FILE"
fi
if [ -d "$SEC_CONF/semgrep-custom" ] && [ -n "$(ls -A "$SEC_CONF/semgrep-custom" 2>/dev/null)" ]; then
  SEMGREP_MOUNTS+=(-v "$SEC_CONF/semgrep-custom:/user:ro")
  SEMGREP_ARGS+=(--config /user)
fi

# 대상의 .semgrepignore 대신 읽을 파일 이름 — 대상에 없는 이름을 주면 Semgrep 은 대상의 .semgrepignore 를
# 모두 무시하고 기본 무시 목록(tests/·test/·*_test.go·build·dist·node_modules·vendor·.venv·.tox·.env·.npm·.yarn·*.min.js)만 쓴다
# (1.182.0 실측). 내부 옵션(--x-)이라 이미지 갱신으로 사라지면 Semgrep 이 인자 오류로 실패해 드러난다.
# git 저장소인 대상도 git 파일 목록이 아니라 폴더 전체를 본다(--no-git-ignore) — 그렇지 않으면 서브모듈·중첩 저장소와
# git 이 무시하는 추적되지 않는 파일을 경고 없이 건너뛴다 (PR #30 2차 리뷰 W-1). 의존성·산출물은 기본 무시 목록·전역 제외·
# 프로파일 exclude_paths·가상환경 제외가 빼지만, 소스 이름과 겹치는 산출물(out/·target/·coverage/)은 프로파일이 감지된
# 하위 경로 밖이면 점검된다.
# 이름이 고정이면 대상이 그 이름(대소문자 변형·심볼릭 링크 포함)의 파일을 미리 둘 수 있으므로 실행마다 무작위로 정한다.
SEMGREPIGNORE_DECOY_PREFIX=.dev-workflow-kit-semgrepignore
DECOY_SUFFIX=$(od -An -N16 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n')
[ ${#DECOY_SUFFIX} -eq 32 ] || sec_die "무작위 값을 만들 수 없습니다 (od·/dev/urandom 확인)."
SEMGREPIGNORE_DECOY="$SEMGREPIGNORE_DECOY_PREFIX-$DECOY_SUFFIX"
# 대상 저장소가 도구 결과를 억제하는 설정을 갖고 있으면 알린다 (툴킷은 그 설정을 쓰지 않는다)
SUPPRESS=$(find "$TARGET" \( -name node_modules -o -name .git -o -name Pods -o -name build \) -prune -o -type f \
  \( -name .gitleaks.toml -o -name .gitleaksignore -o -name .semgrepignore -o -name osv-scanner.toml \) -print 2>/dev/null |
  cut -c$((${#TARGET} + 2))- | head -n 5 | tr '\n' ' ')
if [ -n "$SUPPRESS" ]; then
  printf '%s\n' "대상 저장소에 결과 억제 설정이 있습니다: ${SUPPRESS}— .gitleaks.toml·.gitleaksignore·.semgrepignore·osv-scanner.toml 은 무시하고 툴킷 설정으로 점검했습니다." >>"$WARNINGS_FILE"
fi

# 컨테이너가 결과 파일을 새로 만들면 컨테이너 umask(644)로 생긴다. 권한 600 빈 파일을 미리 만들어 두면
# semgrep·osv-scanner 는 기존 파일을 덮어쓰므로 권한이 유지된다 (실측. gitleaks 는 stdout 으로 받는다)
precreate() { (umask 077 && : >"$1"); }

record() { printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" >>"$STATUS"; }
tail_log() { tail -n 3 "$1" 2>/dev/null | tr '\n\t' '  ' | cut -c1-280; }
# 실패 메모: 컨테이너가 SIGKILL(137)로 끝났으면 대개 메모리 부족이다 — 원인을 드러낸다
fail_note() {
  if [ "$1" = 137 ]; then
    printf '메모리 부족(OOM)으로 강제 종료됐을 수 있습니다 — Docker VM 메모리를 늘린 뒤 다시 실행하세요. %s' "$(tail_log "$2")" | cut -c1-280
  else
    tail_log "$2"
  fi
}

run_semgrep() {
  # 실행할 규칙이 하나도 없으면 실행하지 않는다 (bash 3.2 는 set -u 에서 빈 배열 확장이 오류다)
  local a has_rule=0
  for a in ${SEMGREP_ARGS[@]+"${SEMGREP_ARGS[@]}"}; do
    [ "$a" = --config ] && has_rule=1
  done
  if [ $has_rule -eq 0 ]; then
    record semgrep failed - "실행할 규칙셋이 없습니다 (generic 규칙이 설치되지 않음 — update.sh --rules)"
    return
  fi
  precreate "$RAW/semgrep.json"
  docker run "${DOCKER_HARDEN[@]}" --tmpfs /tmp:rw,size=1g \
    -e SEMGREP_ENABLE_VERSION_CHECK=0 -e SEMGREP_SEND_METRICS=off \
    -v "$TARGET:/src:ro" -v "$RULES_DIR:/rules:ro" ${SEMGREP_MOUNTS[@]+"${SEMGREP_MOUNTS[@]}"} -v "$RAW:/out" \
    "$IMG_SEMGREP" semgrep scan "${SEMGREP_ARGS[@]}" --disable-nosem --metrics=off --disable-version-check \
    --no-git-ignore "--x-semgrepignore-filename=$SEMGREPIGNORE_DECOY" \
    --json -o /out/semgrep.json /src >"$RAW/semgrep.log" 2>&1
  local rc=$?
  # semgrep: 0 정상, 1 발견 있음(--error 미사용 시에도 일부 버전), 그 외 오류
  if [ $rc -le 1 ] && [ -s "$RAW/semgrep.json" ]; then
    record semgrep ok "$rc" ""
  else
    record semgrep failed "$rc" "$(fail_note "$rc" "$RAW/semgrep.log")"
  fi
}

run_gitleaks() {
  local mode=$1 rc log
  log="$RAW/gitleaks-$mode.log"
  # 호스트 사용자로 실행하면 컨테이너 안 git 이 저장소 소유자 불일치(dubious ownership)로 거부한다.
  # 읽기 전용 루트라 git config 를 쓸 수 없으므로 환경변수로 safe.directory 를 준다.
  # gitleaks 는 리포트 파일을 지우고 새로 만들어 권한이 644 가 되므로, 리포트는 stdout 으로 받아 호스트가
  # umask 077(600) 로 쓴다. 로그는 stderr 로 분리된다. 덕분에 gitleaks 에는 쓰기 마운트가 없다.
  docker run "${DOCKER_HARDEN[@]}" --tmpfs /tmp:rw,size=64m \
    -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0=/repo \
    -v "$TARGET:/repo:ro" -v "$SEC_PLUGIN/config:/cfg:ro" "$IMG_GITLEAKS" \
    "$mode" /repo --config /cfg/gitleaks.toml --gitleaks-ignore-path /cfg --ignore-gitleaks-allow \
    --redact --no-banner --no-color --exit-code 0 \
    --report-format json --report-path - >"$RAW/gitleaks-$mode.json" 2>"$log"
  rc=$?
  # gitleaks 는 git 오류가 나도 "0 commits scanned" 후 종료코드 0 으로 끝날 수 있다 — 누락을 성공으로 기록하지 않는다
  if [ $rc -ne 0 ] || [ ! -s "$RAW/gitleaks-$mode.json" ]; then
    record "gitleaks-$mode" failed "$rc" "$(fail_note "$rc" "$log")"
  elif grep -q ' ERR ' "$log"; then
    record "gitleaks-$mode" failed "$rc" "도구 오류: $(grep ' ERR ' "$log" | head -n 2 | tr '\n\t' '  ' | cut -c1-240)"
  elif [ "$mode" = git ] && grep -q ' 0 commits scanned' "$log"; then
    record "gitleaks-$mode" failed "$rc" "커밋을 하나도 읽지 못했습니다 (빈 저장소이거나 git 오류)"
  else
    record "gitleaks-$mode" ok "$rc" ""
  fi
}

run_osv() {
  local rc
  precreate "$RAW/osv.json"
  docker run "${DOCKER_HARDEN[@]}" --tmpfs /tmp:rw,size=512m \
    -e OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY=/db \
    -v "$TARGET:/src:ro" -v "$OSV_DB:/db:ro" -v "$SEC_PLUGIN/config:/cfg:ro" -v "$RAW:/out" "$IMG_OSV" \
    scan source -r --offline --offline-vulnerabilities --config /cfg/osv-scanner.toml \
    --format json --output /out/osv.json /src >"$RAW/osv.log" 2>&1
  rc=$?
  if grep -q 'ignored package' "$RAW/osv.log"; then
    printf '%s\n' "OSV-Scanner 가 일부 패키지를 무시했습니다: $(grep -o 'Filtered [0-9]* ignored package[^ ]*' "$RAW/osv.log" | head -n 1)" >>"$WARNINGS_FILE"
  fi
  # osv-scanner: 0 취약점 없음, 1 취약점 있음, 128 패키지(lockfile) 없음
  if { [ $rc -eq 0 ] || [ $rc -eq 1 ]; } && [ -s "$RAW/osv.json" ]; then
    record osv-scanner ok "$rc" ""
  elif [ $rc -eq 128 ]; then
    record osv-scanner skipped "$rc" "lockfile·매니페스트를 찾지 못함"
  elif grep -q 'could not load db for' "$RAW/osv.log"; then
    # 오프라인 DB 가 없는 생태계 lockfile 이 하나라도 있으면 osv-scanner 는 전체를 실패시킨다
    local ecos
    ecos=$(grep -o 'could not load db for [^ ]* ecosystem' "$RAW/osv.log" | awk '{print $6}' | sort -u | tr '\n' ' ')
    record osv-scanner failed "$rc" "오프라인 DB 가 없는 생태계(${ecos% }) lockfile 때문에 의존성 점검 전체가 중단됐습니다. update.sh --osv 로 DB 를 갱신하거나, 지원하지 않는 생태계면 해당 lockfile 을 점검에서 빼야 합니다"
  else
    record osv-scanner failed "$rc" "$(fail_note "$rc" "$RAW/osv.log")"
  fi
}

# 상위 폴더에서 .git 을 찾는다. 대상 저장소의 git 설정을 읽지 않도록 호스트 git 은 실행하지 않는다 (위협 모델 T5)
# 홈 디렉터리와 그 위는 점검 대상으로 받지 않으므로(sec_validate_target) 거기서 멈춘다
git_toplevel_above() {
  local d home
  home=$(cd -P "$HOME" 2>/dev/null && pwd -P) || home=$HOME
  d=$(dirname "$1")
  while [ -n "$d" ] && [ "$d" != / ] && [ "$d" != "$home" ]; do
    if [ -e "$d/.git" ]; then
      printf '%s\n' "$d"
      return 0
    fi
    d=$(dirname "$d")
  done
  return 1
}

# 스택별 커스텀 검사 (설정 파일·lockfile 메타데이터) — 호스트 Python 으로 대상 파일을 읽기만 한다. 컨테이너·네트워크 없음
run_checks() {
  local rc
  python3 "$SEC_PLUGIN/scripts/lib/checks.py" --profile-dir "$SEC_PROFILE_DIR" --target "$TARGET" \
    --profiles-tsv "$PROFILES_TSV" --out "$RAW/checks.json" 2>"$RAW/checks.log"
  rc=$?
  if [ $rc -eq 0 ] && [ -s "$RAW/checks.json" ]; then
    record checks ok "$rc" ""
  else
    record checks failed "$rc" "$(tail_log "$RAW/checks.log")"
  fi
}

sec_log "도구 실행 중 (Semgrep · Gitleaks · OSV-Scanner · 스택 검사, 네트워크 차단)..."
run_semgrep &
pid_semgrep=$!
pid_git=""
if [ -d "$TARGET/.git" ]; then
  run_gitleaks git &
  pid_git=$!
elif [ -f "$TARGET/.git" ]; then
  # worktree·서브모듈은 .git 이 gitdir 를 가리키는 파일이다. gitdir 는 마운트 밖이라 컨테이너에서 읽을 수 없다
  record gitleaks-git skipped - "git worktree 또는 서브모듈입니다 (.git 이 파일) — 히스토리가 대상 폴더 밖에 있어 점검을 생략했습니다. 원본 저장소 경로로 다시 실행하면 히스토리도 점검합니다"
elif top=$(git_toplevel_above "$TARGET") && [ -n "$top" ] && [ -f "$top/.git" ]; then
  # 서브모듈·worktree 의 하위 폴더 — 그 최상위로 다시 실행해도 히스토리는 마운트 밖이다
  record gitleaks-git skipped - "git worktree 또는 서브모듈($top)의 하위 폴더입니다 — 히스토리가 대상 폴더 밖에 있어 점검을 생략했습니다. 원본 저장소 경로로 다시 실행하면 히스토리도 점검합니다"
elif [ -n "${top:-}" ]; then
  record gitleaks-git skipped - "저장소의 하위 폴더입니다 — 히스토리 점검을 생략했습니다. 최상위 경로($top)로 실행하면 히스토리도 점검합니다"
else
  record gitleaks-git skipped - "git 저장소가 아님 (.git 없음) — 히스토리 점검 생략"
fi
run_gitleaks dir &
pid_dir=$!
run_osv &
pid_osv=$!
run_checks &
pid_checks=$!
wait $pid_semgrep $pid_dir $pid_osv $pid_checks ${pid_git:+$pid_git}

# 리포트 파일 권한 정리 (컨테이너가 만든 파일 포함)
find "$SEC_RUN_DIR" -type f -exec chmod 600 {} + 2>/dev/null
find "$SEC_RUN_DIR" -type d -exec chmod 700 {} + 2>/dev/null

# 메타 (normalize.py 가 meta.json 으로 합친다)
META_IN="$RAW/meta-in.json"
# $TOOLS 는 도구 이름 목록 — 인자 여러 개로 나누려는 의도
# shellcheck disable=SC2086
python3 - "$META_IN" "$STARTED_AT" "$SEC_DOCKER_CONTEXT" "$RULES_COMMIT" "$OSV_UPDATED" \
  "$SEC_IMAGES_LOCK" "$SEC_PLUGIN/.claude-plugin/plugin.json" "$WARNINGS_FILE" $TOOLS <<'PY'
import json, sys
out, started, ctx, rules_commit, osv_updated, lock, plugin_json, warn_file, *tools = sys.argv[1:]
images = {}
with open(lock, encoding="utf-8") as f:
    for line in f:
        p = line.split()
        if len(p) == 5 and not p[0].startswith("#"):
            images[p[0]] = {"name": p[0], "image": p[1], "tag": p[2], "digest": p[3]}
try:
    version = json.load(open(plugin_json, encoding="utf-8")).get("version")
except Exception:
    version = None
warnings = [l.strip() for l in open(warn_file, encoding="utf-8") if l.strip()]
json.dump({
    "started_at": started, "docker_context": ctx, "plugin_version": version,
    "tools": [images[t] for t in tools if t in images],
    "rules": [{"name": "semgrep-rules", "commit": rules_commit}],
    "osv_db_updated_at": osv_updated, "warnings": warnings,
}, open(out, "w", encoding="utf-8"), ensure_ascii=False)
PY

if ! python3 "$SEC_PLUGIN/scripts/normalize.py" --run-dir "$SEC_RUN_DIR" --kind code \
  --target "$TARGET" --profiles-tsv "$PROFILES_TSV" --meta-json "$META_IN" 2>>"$SEC_LOG_FILE"; then
  sec_die "리포트 정규화 실패 — $SEC_LOG_FILE 확인"
fi

failed=$(awk -F '\t' '$2 == "failed" { printf "%s ", $1 }' "$STATUS")
[ -n "$failed" ] && sec_warn "실패한 도구: $failed(summary.md 의 '실행 오류' 참조)"
sec_log "완료. 요약: $SEC_RUN_DIR/summary.md"
# 정규화 후 한 번 더 권한 정리 (늦게 보인 컨테이너 생성 파일 포함)
find "$SEC_RUN_DIR" -type f ! -perm 600 -exec chmod 600 {} + 2>/dev/null
printf '%s\n' "$SEC_RUN_DIR/summary.md"
