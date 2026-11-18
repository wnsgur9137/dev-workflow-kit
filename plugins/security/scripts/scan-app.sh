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
if ! INSPECT=$(python3 -I "$SEC_PLUGIN/scripts/lib/artifact.py" inspect "$TARGET" "$EXT" 2>"$INSPECT_ERR"); then
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

# [D7] 마운트 가시성 — 런타임 VM 이 산출물 경로를 공유하지 않으면 컨테이너에서 파일이 없거나 빈 폴더로 보인다.
#      mobsf-client 가 마운트하는 플러그인 폴더(scripts/lib)도 함께 본다 (리뷰 N7)
HOST_SIZE=$(wc -c <"$TARGET" | tr -d ' ')
probe_err=$(mktemp "${TMPDIR:-/tmp}/sec-d7.XXXXXX") || sec_die "임시 파일을 만들 수 없습니다."
seen=$(docker run "${DOCKER_HARDEN[@]}" --tmpfs /tmp:rw,size=8m -v "$TARGET:/in/artifact.zip:ro" \
  -v "$SEC_PLUGIN/scripts/lib:/client:ro" --entrypoint sh "$IMG_GITLEAKS" \
  -c 'if [ ! -f /client/mobsf_client.py ]; then echo client-missing; elif [ -f /in/artifact.zip ]; then wc -c </in/artifact.zip; else echo missing; fi' \
  2>"$probe_err")
probe_rc=$?
probe_msg=$(tail -n 3 "$probe_err" | tr '\n' ' ' | cut -c1-300)
rm -f "$probe_err"
seen=$(printf '%s' "$seen" | tr -d ' \n')
if [ $probe_rc -ne 0 ] && [ -z "$seen" ]; then
  sec_err "[D7] 산출물 확인용 컨테이너를 실행하지 못했습니다 (종료코드 $probe_rc): ${probe_msg:-출력 없음}"
  sec_log "  Docker 런타임이 이 경로를 공유하지 않거나(Colima 기본값은 홈 아래만 공유) 이미지가 손상됐을 수 있습니다."
  exit 1
fi
if [ "$seen" = client-missing ]; then
  sec_err "[D7] 컨테이너에서 플러그인 폴더가 보이지 않습니다 — Docker 런타임이 이 경로를 공유하지 않습니다: $SEC_PLUGIN"
  sec_log "  Colima 는 기본적으로 홈 디렉터리만 공유합니다. 플러그인을 홈 아래에 설치하거나 mounts 에 경로를 추가하세요."
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
TEXT_ENTRIES=""
TAB=$(printf '\t')
while IFS="$TAB" read -r kind value; do
  case "$kind" in
    profile) printf '%s\t.\t\n' "$value" >>"$PROFILES_TSV" ;;
    warning) printf '%s\n' "$value" >>"$WARNINGS_FILE" ;;
    text_entries) TEXT_ENTRIES=$value ;;
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

# 이전 실행이 SIGKILL 등으로 trap 없이 끝나 남긴 스택(앱 원본·디컴파일 결과가 든 볼륨)과 시크릿 원본 리포트를 지운다
# (리뷰 W5). 동시에 도는 다른 실행을 건드리지 않게 가장 최근 활동이 STALE_MIN 분보다 오래된 것만 지운다 — 한 실행의
# 최대 시간(기동 300초 + AAB 변환 900초 + 준비 180초 + 업로드 600초 + 스캔 3600초 + 리포트 600초 ≈ 104분)보다 길다.
# 생성 시각은 엔진(VM) 시계로 찍히므로 비교 기준도 엔진 시계(docker info .SystemTime)를 쓴다 — 잠자기 뒤 VM 시계가
# 밀려도 방금 시작한 다른 실행을 오래된 것으로 보지 않게 (2차 리뷰 NS3). 엔진 시각을 모르면 스택은 정리하지 않는다(원본
# 리포트는 호스트 파일 시각으로 늘 정리한다).
STALE_MIN=180
cleanup_stale() {
  local ids vols projects p n=0 now
  # 시크릿 원본 리포트는 호스트 파일 시각으로 판정하므로 엔진 시각과 상관없이 늘 정리한다 (3차 리뷰 NS-A)
  find "$SEC_DATA/reports" -mindepth 3 -maxdepth 3 -name mobsf-full.json -mmin +"$STALE_MIN" -exec rm -f {} + 2>/dev/null
  now=$(docker info --format '{{.SystemTime}}' 2>/dev/null)
  [ -n "$now" ] || return 0
  ids=$(docker ps -aq --filter label=com.docker.compose.project 2>/dev/null)
  vols=$(docker volume ls -q --filter label=com.docker.compose.project 2>/dev/null)
  # shellcheck disable=SC2086  # id·볼륨 이름 목록 — 공백 없는 이름이다
  projects=$({
    [ -n "$ids" ] && docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}} {{.Created}}' $ids 2>/dev/null
    [ -n "$vols" ] && docker volume inspect -f '{{index .Labels "com.docker.compose.project"}} {{.CreatedAt}}' $vols 2>/dev/null
  } | python3 -I "$SEC_PLUGIN/scripts/lib/stale_projects.py" dwk-sec-app "$STALE_MIN" "$now" 2>/dev/null)
  for p in $projects; do
    docker compose -p "$p" -f "$COMPOSE_FILE_PATH" --profile client down -v --remove-orphans --timeout 5 >/dev/null 2>&1 && n=$((n + 1))
    # 컨테이너 없이 볼륨만 남은 프로젝트도 지운다 (2차 리뷰 Open Question)
    # shellcheck disable=SC2046  # 볼륨 이름 목록 — 공백 없는 이름이다
    docker volume rm $(docker volume ls -q --filter "label=com.docker.compose.project=$p" 2>/dev/null) >/dev/null 2>&1
  done
  [ $n -gt 0 ] && printf '%s\n' "이전 실행이 남긴 MobSF 스택 ${n}개(${STALE_MIN}분 이상 지난 것)를 지웠습니다." >>"$WARNINGS_FILE"
  return 0
}

STACK_UP=0
GITLEAKS_CID="$RAW/gitleaks.cid"
pid_gitleaks=""
stack_down() {
  compose --profile client down -v --remove-orphans --timeout 10 >/dev/null 2>&1 && STACK_UP=0
}
cleanup() {
  # 중단되면 백그라운드 Gitleaks 와 그 컨테이너도 멈춘다 (비대화형 bash 의 & 작업은 SIGINT 를 받지 않는다, 리뷰 S6)
  if [ -n "$pid_gitleaks" ] && kill -0 "$pid_gitleaks" 2>/dev/null; then
    kill "$pid_gitleaks" 2>/dev/null
    [ -s "$GITLEAKS_CID" ] && docker rm -f "$(cat "$GITLEAKS_CID")" >/dev/null 2>&1
  fi
  # cidfile 이 써지기 전에 중단되면 Gitleaks 컨테이너는 스스로 끝날 때까지 남는다(--rm, 네트워크 없음). 백그라운드
  # compose run CLI 는 down 으로 컨테이너가 사라지면 함께 끝난다 (2차 리뷰 NN5)
  rm -f "$GITLEAKS_CID"
  [ $STACK_UP -eq 1 ] && stack_down
  if [ $STACK_UP -eq 1 ]; then
    sec_warn "MobSF 스택을 내리지 못했습니다 — docker compose -p $COMPOSE_PROJECT -f $COMPOSE_FILE_PATH down -v 로 직접 지우세요."
  fi
  # 시크릿 원문이 든 원본 리포트는 정제본만 남기고 지운다 (정규화 전에 실패해도. SIGKILL 이면 다음 실행의 cleanup_stale 이 지운다)
  rm -f "$RAW/mobsf-full.json"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cleanup_stale

# --- Gitleaks: 산출물(ZIP) 안의 텍스트 파일 (N0) --------------------------------------------------------
# .zip 이름으로 마운트해야 압축 안까지 본다 (v8.30.1 실측 — .apk·.ipa 이름은 0바이트로 끝남). dex·so 같은 바이너리는 보지 않는다
run_gitleaks_artifact() {
  local rc log="$RAW/gitleaks-artifact.log"
  # 압축은 신뢰하지 않는 입력이다 — 압축 폭탄이 VM 메모리를 다 쓰지 않게 상한을 둔다 (넘으면 137 → OOM 안내)
  docker run "${DOCKER_HARDEN[@]}" --cidfile "$GITLEAKS_CID" --memory 2g --tmpfs /tmp:rw,size=256m \
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
    # 압축을 열지 못하면 0바이트로 "no leaks" 가 된다 — 누락을 성공으로 기록하지 않는다.
    # 다만 텍스트로 보이는 항목이 하나도 없는 산출물(바이너리만)은 볼 것이 없어서 0바이트다 (리뷰 S3)
    if [ "$TEXT_ENTRIES" = 0 ]; then
      record gitleaks-artifact skipped "$rc" "산출물에 텍스트 파일이 없어 Gitleaks 가 볼 내용이 없습니다 (바이너리 안은 MobSF 결과로 확인)"
    else
      record gitleaks-artifact failed "$rc" "산출물 안을 읽지 못했습니다 (0바이트 스캔)"
    fi
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
    stack_down
    return
  fi
  # 업로드 전에 격리를 실제로 확인한다 — 외부 이름 풀이·IP 연결이 되면 중단한다. internal 네트워크의 외부 DNS 를
  # dockerd 가 대신 보내던 엔진(CVE-2024-29018, Moby 26.0.0·25.0.5·23.0.11 미만)에서는 스토어·Firebase 조회가
  # DNS 로 새어 나간다 (리뷰 W6). 몇 초면 끝난다
  local iso
  # 검사 내용은 scripts/lib/app_iso_probe.py (MobSF 컨테이너에 마운트가 없으므로 내용을 -c 로 넘긴다, PR #32 5차 N1)
  iso=$(compose exec -T mobsf python3 -I -c "$(cat "$SEC_PLUGIN/scripts/lib/app_iso_probe.py")" 2>&1 | tail -n 1)
  if [ "$iso" != isolated ]; then
    record mobsf failed - "격리 확인 실패 — MobSF 컨테이너에서 외부 이름 풀이·연결·프록시 설정이 확인됩니다(${iso:-확인 불가}). 앱을 올리지 않았습니다. Docker 엔진 버전(예: CVE-2024-29018)·~/.docker/config.json 의 proxies·런타임 네트워크 설정을 확인하세요"
    stack_down
    return
  fi
  client_args=(--url http://mobsf:8000 --file "/in/$APP_NAME")
  [ "$EXT" = aab ] && client_args+=(--convert-aab)
  sec_log "MobSF 정적 분석 중 (앱 크기에 따라 수 분)..."
  # 리포트는 stdout 으로만 받는다 — 호스트가 umask 077(600) 로 쓴다.
  # 백그라운드 + wait: 포그라운드면 TERM 이 와도 bash 가 compose run 이 끝날 때(최대 1시간)까지 trap 을 미룬다 (리뷰 W5)
  compose --profile client run --rm --no-deps -T mobsf-client "${client_args[@]}" \
    >"$RAW/mobsf-full.json" 2>"$RAW/mobsf-client.raw.log" </dev/null &
  wait $!
  rc=$?
  redact_secrets <"$RAW/mobsf-client.raw.log" >"$RAW/mobsf-client.log"
  rm -f "$RAW/mobsf-client.raw.log"
  if [ $rc -eq 0 ] && [ -s "$RAW/mobsf-full.json" ]; then
    record mobsf ok "$rc" ""
  else
    compose logs --no-color --tail 30 mobsf 2>/dev/null | redact_secrets >"$RAW/mobsf-server.log"
    local note
    note=$(grep 'mobsf_client:' "$RAW/mobsf-client.log" | tail -n 2 | tr '\n\t' '  ' | cut -c1-280)
    [ "$rc" = 137 ] && note="mobsf-client 가 메모리 상한(4GB)·VM 메모리 부족으로 강제 종료됐을 수 있습니다. $note"
    # MobSF 서버가 메모리 상한(6GB)에 걸리면 클라이언트에는 연결 오류로만 보인다 (리뷰 W4)
    local sid
    sid=$(compose ps -aq mobsf 2>/dev/null | head -n 1)
    if [ -n "$sid" ] && [ "$(docker inspect -f '{{.State.OOMKilled}}' "$sid" 2>/dev/null)" = true ]; then
      note="MobSF 가 메모리 상한(6GB)을 넘어 강제 종료됐습니다 — 압축 폭탄이거나 매우 큰 앱일 수 있습니다. $note"
    fi
    record mobsf failed "$rc" "${note:-$(tail_log "$RAW/mobsf-client.log")}"
  fi
  stack_down
}

sec_log "도구 실행 중 (MobSF · Gitleaks)..."
run_gitleaks_artifact &
pid_gitleaks=$!
run_mobsf
wait $pid_gitleaks
pid_gitleaks=""
rm -f "$GITLEAKS_CID"

if [ "$EXT" = aab ] && awk -F '\t' '$1 == "mobsf" && $2 == "ok" { f = 1 } END { exit !f }' "$STATUS"; then
  printf '%s\n' "AAB 는 bundletool 로 universal APK 를 만들어 분석했습니다 (MobSF v4.6.4 의 자체 AAB 변환은 arm64 이미지에서 실패하므로 툴킷이 미리 변환)." >>"$WARNINGS_FILE"
fi

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

if ! python3 -I "$SEC_PLUGIN/scripts/normalize.py" --run-dir "$SEC_RUN_DIR" --kind app \
  --target "$TARGET" --profiles-tsv "$PROFILES_TSV" --meta-json "$META_IN" 2>>"$SEC_LOG_FILE"; then
  sec_die "리포트 정규화 실패 — $SEC_LOG_FILE 확인"
fi
rm -f "$RAW/mobsf-full.json"

failed=$(awk -F '\t' '$2 == "failed" { printf "%s ", $1 }' "$STATUS")
[ -n "$failed" ] && sec_warn "실패한 도구: $failed(summary.md 의 '실행 오류' 참조)"
sec_log "완료. 요약: $SEC_RUN_DIR/summary.md"
find "$SEC_RUN_DIR" -type f ! -perm 600 -exec chmod 600 {} + 2>/dev/null
printf '%s\n' "$SEC_RUN_DIR/summary.md"
