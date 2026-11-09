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
  seen=$(docker run "${DOCKER_HARDEN[@]}" --tmpfs /tmp:rw,size=8m -v "$TARGET:/src:ro" --entrypoint sh "$IMG_GITLEAKS" -c 'ls -A /src | head -n 1' 2>/dev/null)
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
if [ -d "$SEC_CONF/semgrep-custom" ] && [ -n "$(ls -A "$SEC_CONF/semgrep-custom" 2>/dev/null)" ]; then
  SEMGREP_MOUNTS+=(-v "$SEC_CONF/semgrep-custom:/user:ro")
  SEMGREP_ARGS+=(--config /user)
fi

record() { printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" >>"$STATUS"; }
tail_log() { tail -n 3 "$1" 2>/dev/null | tr '\n\t' '  ' | cut -c1-280; }

run_semgrep() {
  docker run "${DOCKER_HARDEN[@]}" --tmpfs /tmp:rw,size=1g \
    -e SEMGREP_ENABLE_VERSION_CHECK=0 -e SEMGREP_SEND_METRICS=off \
    -v "$TARGET:/src:ro" -v "$RULES_DIR:/rules:ro" ${SEMGREP_MOUNTS[@]+"${SEMGREP_MOUNTS[@]}"} -v "$RAW:/out" \
    "$IMG_SEMGREP" semgrep scan "${SEMGREP_ARGS[@]}" --metrics=off --disable-version-check \
    --json -o /out/semgrep.json /src >"$RAW/semgrep.log" 2>&1
  local rc=$?
  # semgrep: 0 정상, 1 발견 있음(--error 미사용 시에도 일부 버전), 그 외 오류
  if [ $rc -le 1 ] && [ -s "$RAW/semgrep.json" ]; then
    record semgrep ok "$rc" ""
  else
    record semgrep failed "$rc" "$(tail_log "$RAW/semgrep.log")"
  fi
}

run_gitleaks() {
  local mode=$1 rc log
  log="$RAW/gitleaks-$mode.log"
  # 호스트 사용자로 실행하면 컨테이너 안 git 이 저장소 소유자 불일치(dubious ownership)로 거부한다.
  # 읽기 전용 루트라 git config 를 쓸 수 없으므로 환경변수로 safe.directory 를 준다.
  docker run "${DOCKER_HARDEN[@]}" --tmpfs /tmp:rw,size=64m \
    -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0=/repo \
    -v "$TARGET:/repo:ro" -v "$RAW:/out" "$IMG_GITLEAKS" \
    "$mode" /repo --redact --no-banner --no-color --exit-code 0 \
    --report-format json --report-path "/out/gitleaks-$mode.json" >"$log" 2>&1
  rc=$?
  # gitleaks 는 git 오류가 나도 "0 commits scanned" 후 종료코드 0 으로 끝날 수 있다 — 누락을 성공으로 기록하지 않는다
  if [ $rc -ne 0 ] || [ ! -f "$RAW/gitleaks-$mode.json" ]; then
    record "gitleaks-$mode" failed "$rc" "$(tail_log "$log")"
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
  docker run "${DOCKER_HARDEN[@]}" --tmpfs /tmp:rw,size=512m \
    -e OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY=/db \
    -v "$TARGET:/src:ro" -v "$OSV_DB:/db:ro" -v "$RAW:/out" "$IMG_OSV" \
    scan source -r --offline --offline-vulnerabilities \
    --format json --output /out/osv.json /src >"$RAW/osv.log" 2>&1
  rc=$?
  # osv-scanner: 0 취약점 없음, 1 취약점 있음, 128 패키지(lockfile) 없음
  if { [ $rc -eq 0 ] || [ $rc -eq 1 ]; } && [ -s "$RAW/osv.json" ]; then
    record osv-scanner ok "$rc" ""
  elif [ $rc -eq 128 ]; then
    record osv-scanner skipped "$rc" "lockfile·매니페스트를 찾지 못함"
  else
    record osv-scanner failed "$rc" "$(tail_log "$RAW/osv.log")"
  fi
}

sec_log "도구 실행 중 (Semgrep · Gitleaks · OSV-Scanner, 네트워크 차단)..."
run_semgrep &
pid_semgrep=$!
if [ -d "$TARGET/.git" ]; then
  run_gitleaks git &
  pid_git=$!
else
  record gitleaks-git skipped - "git 저장소가 아님 (.git 폴더 없음) — 히스토리 점검 생략"
  pid_git=""
fi
run_gitleaks dir &
pid_dir=$!
run_osv &
pid_osv=$!
wait $pid_semgrep $pid_dir $pid_osv ${pid_git:+$pid_git}

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
printf '%s\n' "$SEC_RUN_DIR/summary.md"
