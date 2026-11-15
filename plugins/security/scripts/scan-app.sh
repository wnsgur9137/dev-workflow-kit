#!/usr/bin/env bash
# /security:scan-app — 앱 산출물(APK·AAB·IPA) 정적 분석 (MobSF, 네트워크 N1 · Gitleaks, 네트워크 N0)
#
# 사용: scan-app.sh <산출물 경로(.apk|.aab|.ipa)>
#
# - MobSF 는 internal 네트워크(인터넷·호스트 포트 없음)에서만 돌고, 실행마다 새 스택(컨테이너·네트워크·볼륨)을 띄웠다 지운다
# - Gitleaks 는 --network none 으로 산출물(ZIP) 안의 텍스트 파일(RN 번들 등)에서 키를 찾는다
# - 이미지를 받지 않는다 (없으면 update.sh 안내 후 종료). 산출물은 읽기 전용으로 마운트한다
# - 결과: $DATA/reports/<run-id>/{raw/,findings.json,summary.md,meta.json}
# - stdout 마지막 줄: summary.md 경로
#   docs/security/03 워크플로/scan-app.md
set -u
umask 077

SELF_DIR="$(cd -P "$(dirname "$0")" && pwd -P)"
# shellcheck source=scripts/lib/common.sh
. "$SELF_DIR/lib/common.sh"
# shellcheck source=scripts/lib/detect.sh
. "$SELF_DIR/lib/detect.sh"

usage() {
  cat >&2 <<'EOF'
사용: /security:scan-app <산출물 경로>
  APK·AAB·IPA 파일 하나를 지정합니다 (직접 빌드한 릴리스 산출물 권장).
EOF
}

TARGET_ARG=""
for arg in "$@"; do
  case "$arg" in
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

TARGET=$(sec_validate_target "$TARGET_ARG" file) || exit 1
EXT=$(printf '%s' "${TARGET##*.}" | LC_ALL=C tr '[:upper:]' '[:lower:]')
sec_require_python || exit 1

# 산출물 사전 검사 (ZIP 시그니처·크기·항목 수, 스택 판정) — 압축을 풀지 않고 항목 이름만 읽는다
INSPECT_ERR=$(mktemp "${TMPDIR:-/tmp}/sec-app.XXXXXX") || sec_die "임시 파일을 만들 수 없습니다."
if ! INSPECT=$(python3 "$SEC_PLUGIN/scripts/lib/artifact.py" inspect "$TARGET" "$EXT" 2>"$INSPECT_ERR"); then
  sec_err "산출물 검사 실패: $(head -c 300 "$INSPECT_ERR")"
  rm -f "$INSPECT_ERR"
  exit 1
fi
rm -f "$INSPECT_ERR"

TOOLS="mobsf gitleaks"
# shellcheck disable=SC2086
sec_preflight app $TOOLS || exit 1
IMG_MOBSF=$(sec_image_ref mobsf)
IMG_GITLEAKS=$(sec_image_ref gitleaks)

DOCKER_HARDEN=(--rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges
  --pids-limit 512 --user "$(id -u):$(id -g)" -e HOME=/tmp)

# [D7] 마운트 가시성 — 런타임 VM 이 산출물 경로를 공유하지 않으면 컨테이너에서 파일이 없거나 빈 폴더로 보인다
HOST_SIZE=$(wc -c <"$TARGET" | tr -d ' ')
probe_err=$(mktemp "${TMPDIR:-/tmp}/sec-d7.XXXXXX") || sec_die "임시 파일을 만들 수 없습니다."
seen=$(docker run "${DOCKER_HARDEN[@]}" --tmpfs /tmp:rw,size=8m -v "$TARGET:/in/artifact.zip:ro" --entrypoint sh \
  "$IMG_GITLEAKS" -c 'if [ -f /in/artifact.zip ]; then wc -c </in/artifact.zip; else echo missing; fi' 2>"$probe_err")
probe_rc=$?
probe_msg=$(tail -n 3 "$probe_err" | tr '\n' ' ' | cut -c1-300)
rm -f "$probe_err"
seen=$(printf '%s' "$seen" | tr -d ' \n')
if [ $probe_rc -ne 0 ] && [ -z "$seen" ]; then
  sec_err "[D7] 산출물 확인용 컨테이너를 실행하지 못했습니다 (종료코드 $probe_rc): ${probe_msg:-출력 없음}"
  sec_log "  Docker 런타임이 이 경로를 공유하지 않거나(Colima 기본값은 홈 아래만 공유) 이미지가 손상됐을 수 있습니다."
  exit 1
fi
if [ "$seen" != "$HOST_SIZE" ]; then
  sec_err "[D7] 컨테이너에서 산출물이 보이지 않습니다 — Docker 런타임이 이 경로를 공유하지 않습니다: $TARGET"
  sec_log "  Colima 는 기본적으로 홈 디렉터리만 공유합니다. 파일을 홈 아래로 옮기거나"
  sec_log "  ~/.colima/default/colima.yaml 의 mounts 에 경로를 추가한 뒤 colima restart 하세요."
  exit 1
fi

sec_new_run app || sec_die "리포트 폴더를 만들 수 없습니다."
RAW="$SEC_RUN_DIR/raw"
STATUS="$RAW/status.tsv"
: >"$STATUS"
WARNINGS_FILE="$RAW/warnings.txt"
: >"$WARNINGS_FILE"
STARTED_AT=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
sec_log "run-id: $SEC_RUN_ID"
sec_log "대상: $TARGET"

# 판정 결과 → profiles.tsv (normalize 의 프로파일 표기와 같은 형식, 하위 경로는 산출물 전체 '.')
PROFILES_TSV="$RAW/profiles.tsv"
: >"$PROFILES_TSV"
TAB=$(printf '\t')
while IFS="$TAB" read -r kind value; do
  case "$kind" in
    profile) printf '%s\t.\t\n' "$value" >>"$PROFILES_TSV" ;;
    warning) printf '%s\n' "$value" >>"$WARNINGS_FILE" ;;
  esac
done <<EOF
$INSPECT
EOF
sec_log "프로파일: $(cut -f1 "$PROFILES_TSV" | tr '\n' ' ')"

record() { printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" >>"$STATUS"; }
rand_hex() { od -An -N"$1" -tx1 /dev/urandom 2>/dev/null | tr -d ' \n'; }

# 실행마다 새 비밀값 — MobSF 는 API 키를 로그에 찍는다
DWK_MOBSF_API_KEY=$(rand_hex 32)
DWK_MOBSF_SECRET=$(rand_hex 32)
DWK_MOBSF_ADMIN_PW=$(rand_hex 24)
PROJECT_SUFFIX=$(rand_hex 6)
if [ ${#DWK_MOBSF_API_KEY} -ne 64 ] || [ ${#DWK_MOBSF_SECRET} -ne 64 ] || [ ${#PROJECT_SUFFIX} -ne 12 ]; then
  sec_die "무작위 값을 만들 수 없습니다 (od·/dev/urandom 확인)."
fi
COMPOSE_PROJECT="dwk-sec-app-$PROJECT_SUFFIX"
APP_NAME="app.$EXT"
DWK_MOBSF_IMAGE=$IMG_MOBSF
DWK_UID_GID="$(id -u):$(id -g)"
DWK_APP_FILE=$TARGET
DWK_APP_NAME=$APP_NAME
DWK_CLIENT_DIR="$SEC_PLUGIN/scripts/lib"
export DWK_MOBSF_IMAGE DWK_MOBSF_API_KEY DWK_MOBSF_SECRET DWK_MOBSF_ADMIN_PW DWK_UID_GID DWK_APP_FILE DWK_APP_NAME DWK_CLIENT_DIR
COMPOSE_FILE_PATH="$SEC_PLUGIN/docker/compose.yml"
compose() { docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE_PATH" "$@"; }

# 로그에서 이번 실행의 비밀값을 가린다 (status 메모·raw 로그에 남기 전에)
redact_secrets() { sed -e "s/$DWK_MOBSF_API_KEY/[MASKED]/g" -e "s/$DWK_MOBSF_SECRET/[MASKED]/g" -e "s/$DWK_MOBSF_ADMIN_PW/[MASKED]/g"; }
tail_log() { tail -n 3 "$1" 2>/dev/null | redact_secrets | tr '\n\t' '  ' | cut -c1-280; }

STACK_UP=0
cleanup() {
  if [ $STACK_UP -eq 1 ]; then
    compose --profile client down -v --remove-orphans --timeout 10 >/dev/null 2>&1 || true
    STACK_UP=0
  fi
  # 시크릿 원문이 든 원본 리포트는 정제본만 남기고 지운다 (정규화 전에 실패해도)
  rm -f "$RAW/mobsf-full.json"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# --- Gitleaks: 산출물(ZIP) 안의 텍스트 파일 (N0) --------------------------------------------------------
# .zip 이름으로 마운트해야 압축 안까지 본다 (v8.30.1 실측 — .apk·.ipa 이름은 0바이트로 끝남). dex·so 같은 바이너리는 보지 않는다
run_gitleaks_artifact() {
  local rc log="$RAW/gitleaks-artifact.log"
  # 압축은 신뢰하지 않는 입력이다 — 압축 폭탄이 VM 메모리를 다 쓰지 않게 상한을 둔다 (넘으면 137 → OOM 안내)
  docker run "${DOCKER_HARDEN[@]}" --memory 2g --tmpfs /tmp:rw,size=256m \
    -v "$TARGET:/in/artifact.zip:ro" -v "$SEC_PLUGIN/config:/cfg:ro" "$IMG_GITLEAKS" \
    dir /in --config /cfg/gitleaks.toml --gitleaks-ignore-path /cfg --ignore-gitleaks-allow --max-archive-depth 2 \
    --redact --no-banner --no-color --exit-code 0 \
    --report-format json --report-path - >"$RAW/gitleaks-artifact.json" 2>"$log"
  rc=$?
  if [ $rc -eq 137 ]; then
    record gitleaks-artifact failed "$rc" "메모리 상한(2GB)을 넘어 강제 종료됐습니다 — 압축 폭탄이거나 매우 큰 산출물일 수 있습니다. $(tail_log "$log")"
  elif [ $rc -ne 0 ] || [ ! -s "$RAW/gitleaks-artifact.json" ]; then
    record gitleaks-artifact failed "$rc" "$(tail_log "$log")"
  elif grep -q ' ERR ' "$log"; then
    record gitleaks-artifact failed "$rc" "도구 오류: $(grep ' ERR ' "$log" | head -n 2 | tr '\n\t' '  ' | cut -c1-240)"
  elif grep -q 'scanned ~0 bytes' "$log"; then
    # 압축을 열지 못하면 0바이트로 "no leaks" 가 된다 — 누락을 성공으로 기록하지 않는다
    record gitleaks-artifact failed "$rc" "산출물 안을 읽지 못했습니다 (0바이트 스캔)"
  else
    record gitleaks-artifact ok "$rc" ""
  fi
}

# --- MobSF (N1) -----------------------------------------------------------------------------------------
run_mobsf() {
  local rc client_args
  sec_log "MobSF 기동 중 (internal 네트워크, 호스트 포트 없음 — 처음 30초 안팎)..."
  STACK_UP=1
  if ! compose up -d --wait --wait-timeout 300 mobsf >"$RAW/compose-up.log" 2>&1; then
    compose logs --no-color --tail 40 mobsf 2>/dev/null | redact_secrets >>"$RAW/compose-up.log"
    record mobsf failed - "MobSF 를 기동하지 못했습니다: $(tail_log "$RAW/compose-up.log")"
    return
  fi
  client_args=(--url http://mobsf:8000 --file "/in/$APP_NAME")
  [ "$EXT" = aab ] && client_args+=(--convert-aab)
  sec_log "MobSF 정적 분석 중 (앱 크기에 따라 수 분)..."
  # 리포트는 stdout 으로만 받는다 — 호스트가 umask 077(600) 로 쓴다
  compose --profile client run --rm --no-deps -T mobsf-client "${client_args[@]}" \
    >"$RAW/mobsf-full.json" 2>"$RAW/mobsf-client.raw.log"
  rc=$?
  redact_secrets <"$RAW/mobsf-client.raw.log" >"$RAW/mobsf-client.log"
  rm -f "$RAW/mobsf-client.raw.log"
  if [ $rc -eq 0 ] && [ -s "$RAW/mobsf-full.json" ]; then
    record mobsf ok "$rc" ""
  else
    compose logs --no-color --tail 30 mobsf 2>/dev/null | redact_secrets >"$RAW/mobsf-server.log"
    local note
    note=$(grep 'mobsf_client:' "$RAW/mobsf-client.log" | tail -n 2 | tr '\n\t' '  ' | cut -c1-280)
    [ "$rc" = 137 ] && note="메모리 부족(OOM)으로 강제 종료됐을 수 있습니다 — Docker VM 메모리를 8GB 이상으로 늘리세요. $note"
    record mobsf failed "$rc" "${note:-$(tail_log "$RAW/mobsf-client.log")}"
  fi
  compose --profile client down -v --remove-orphans --timeout 10 >/dev/null 2>&1 && STACK_UP=0
}

sec_log "도구 실행 중 (MobSF · Gitleaks)..."
run_gitleaks_artifact &
pid_gitleaks=$!
run_mobsf
wait $pid_gitleaks
if [ $STACK_UP -eq 1 ]; then
  sec_warn "MobSF 스택을 내리지 못했습니다 — docker compose -p $COMPOSE_PROJECT down -v 로 직접 지우세요."
fi

[ "$EXT" = aab ] && printf '%s\n' "AAB 는 bundletool 로 universal APK 를 만들어 분석했습니다 (MobSF 의 AAB 변환은 arm64 에서 실패하므로 툴킷이 미리 변환)." >>"$WARNINGS_FILE"

find "$SEC_RUN_DIR" -type f -exec chmod 600 {} + 2>/dev/null
find "$SEC_RUN_DIR" -type d -exec chmod 700 {} + 2>/dev/null

META_IN="$RAW/meta-in.json"
# shellcheck disable=SC2086
python3 - "$META_IN" "$STARTED_AT" "$SEC_DOCKER_CONTEXT" "$SEC_IMAGES_LOCK" \
  "$SEC_PLUGIN/.claude-plugin/plugin.json" "$WARNINGS_FILE" $TOOLS <<'PY'
import json, sys
out, started, ctx, lock, plugin_json, warn_file, *tools = sys.argv[1:]
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
    "tools": [images[t] for t in tools if t in images], "rules": [], "warnings": warnings,
}, open(out, "w", encoding="utf-8"), ensure_ascii=False)
PY

if ! python3 "$SEC_PLUGIN/scripts/normalize.py" --run-dir "$SEC_RUN_DIR" --kind app \
  --target "$TARGET" --profiles-tsv "$PROFILES_TSV" --meta-json "$META_IN" 2>>"$SEC_LOG_FILE"; then
  sec_die "리포트 정규화 실패 — $SEC_LOG_FILE 확인"
fi
rm -f "$RAW/mobsf-full.json"

failed=$(awk -F '\t' '$2 == "failed" { printf "%s ", $1 }' "$STATUS")
[ -n "$failed" ] && sec_warn "실패한 도구: $failed(summary.md 의 '실행 오류' 참조)"
sec_log "완료. 요약: $SEC_RUN_DIR/summary.md"
find "$SEC_RUN_DIR" -type f ! -perm 600 -exec chmod 600 {} + 2>/dev/null
printf '%s\n' "$SEC_RUN_DIR/summary.md"
