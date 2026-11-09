#!/usr/bin/env bash
# security 플러그인 데이터 업데이트 — 툴킷에서 외부와 통신하는 **유일한** 스크립트.
# Claude 는 이 스크립트를 실행할 권한이 없다. 사용자가 터미널에서 직접 실행한다.
#
# 사용: update.sh [--images] [--rules] [--osv]   (인자가 없으면 전부)
#   --images  images.lock 의 이미지를 digest 그대로 pull
#   --rules   rules.lock 의 규칙 저장소를 고정 커밋으로 받아 $DATA/data/<name>/ 에 설치
#   --osv     OSV 오프라인 DB 를 받아 $DATA/data/osv/ 에 설치 (주 1회 권장)
#
#   docs/security/03 워크플로/업데이트 절차.md
set -u
umask 077

SELF_DIR="$(cd -P "$(dirname "$0")" && pwd -P)"
# shellcheck source=scripts/lib/common.sh
. "$SELF_DIR/lib/common.sh"

DO_IMAGES=0 DO_RULES=0 DO_OSV=0
for arg in "$@"; do
  case "$arg" in
    --images) DO_IMAGES=1 ;;
    --rules) DO_RULES=1 ;;
    --osv) DO_OSV=1 ;;
    -h | --help)
      sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      sec_err "알 수 없는 인자: $arg"
      exit 2
      ;;
  esac
done
if [ $DO_IMAGES -eq 0 ] && [ $DO_RULES -eq 0 ] && [ $DO_OSV -eq 0 ]; then
  DO_IMAGES=1 DO_RULES=1 DO_OSV=1
fi

sec_init_dirs || sec_die "데이터 폴더를 만들 수 없습니다: $SEC_DATA"
sec_validate_images_lock || sec_die "images.lock 형식 오류"
sec_validate_rules_lock || sec_die "rules.lock 형식 오류"

need_docker=$((DO_IMAGES + DO_OSV))
if [ $need_docker -gt 0 ]; then
  sec_preflight code || exit 1
  # Docker Desktop 을 지운 뒤 다른 런타임을 쓰면 credsStore 가 남아 pull 이 실패한다 (pull 하는 --images 에서만 검사)
  cfg="${DOCKER_CONFIG:-$HOME/.docker}/config.json"
  if [ $DO_IMAGES -eq 1 ] && [ -f "$cfg" ]; then
    store=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("credsStore",""))' "$cfg" 2>/dev/null)
    if [ -n "$store" ] && ! command -v "docker-credential-$store" >/dev/null 2>&1; then
      sec_err "$cfg 의 \"credsStore\": \"$store\" 에 해당하는 docker-credential-$store 가 없어 이미지를 받을 수 없습니다."
      sec_log "  Docker Desktop 을 지웠다면 그 줄을 삭제하세요 (공개 이미지만 받으므로 자격증명 저장소가 필요 없습니다)."
      exit 1
    fi
  fi
fi

# docker/osv-seed/ 의 씨앗이 받아야 하는 생태계 (OSV 디렉터리 이름)
OSV_ECOSYSTEMS="npm PyPI Go Maven Pub SwiftURL crates.io RubyGems Packagist NuGet"

TMP_ROOT="$SEC_DATA/data/.tmp-update-$$"
cleanup() { rm -rf "$TMP_ROOT"; }
trap cleanup EXIT
mkdir -p "$TMP_ROOT"
failed=0

# ---------------------------------------------------------------------------
# 이미지
# ---------------------------------------------------------------------------
update_images() {
  local arch name image tag digest platforms ref
  arch=$(uname -m)
  while read -r name image tag digest platforms; do
    case "$name" in '' | \#*) continue ;; esac
    ref="$image@$digest"
    case "$arch" in
      arm64 | aarch64)
        case ",$platforms," in
          *,linux/arm64,*) ;;
          *) sec_warn "$name($tag) 는 arm64 이미지가 없어 amd64 에뮬레이션으로 느리게 동작합니다." ;;
        esac
        ;;
    esac
    if docker image inspect "$ref" >/dev/null 2>&1; then
      sec_log "이미지 있음: $name $tag"
      continue
    fi
    sec_log "이미지 받는 중: $name $tag ($ref)"
    if ! docker pull "$ref" >/dev/null; then
      sec_err "pull 실패: $ref"
      failed=1
      continue
    fi
    # digest 로 pull 하므로 내용은 고정되지만, 로컬 기록도 한 번 더 확인한다
    if ! docker image inspect --format '{{join .RepoDigests "\n"}}' "$ref" 2>/dev/null | grep -qxF "$ref"; then
      sec_err "받은 이미지의 digest 가 images.lock 과 다릅니다: $ref — 중단합니다."
      exit 1
    fi
    sec_log "  완료: $(docker image inspect --format '{{.Size}}' "$ref" | awk '{ printf "%.0fMB", $1/1024/1024 }')"
  done <"$SEC_IMAGES_LOCK"
}

# ---------------------------------------------------------------------------
# 규칙 (GitHub 커밋 tarball → 경로 필터 → 규칙 YAML 만 설치)
# ---------------------------------------------------------------------------
update_rules() {
  local name url commit paths repo dest work
  while read -r name url commit paths; do
    case "$name" in '' | \#*) continue ;; esac
    dest="$SEC_DATA/data/$name"
    if [ -f "$dest/.commit" ] && [ "$(head -n 1 "$dest/.commit")" = "$commit" ]; then
      sec_log "규칙 최신: $name ${commit:0:12}"
      continue
    fi
    case "$url" in
      https://github.com/*/*) repo=${url#https://github.com/} repo=${repo%.git} ;;
      *)
        sec_err "지원하지 않는 규칙 저장소 주소(GitHub https 만 지원): $url"
        failed=1
        continue
        ;;
    esac
    work="$TMP_ROOT/$name"
    mkdir -p "$work"
    sec_log "규칙 받는 중: $name ${commit:0:12}"
    if ! curl -fsSL --proto '=https' --tlsv1.2 --max-time 300 -o "$work/src.tgz" \
      "https://codeload.github.com/$repo/tar.gz/$commit"; then
      sec_err "다운로드 실패: $url@$commit"
      failed=1
      continue
    fi
    if ! python3 - "$work/src.tgz" "$work/out" "$paths" <<'PY'; then
import os, re, sys, tarfile
src, out, paths = sys.argv[1], sys.argv[2], [p.strip("/") for p in sys.argv[3].split(",") if p.strip()]
RULE_TOP = re.compile(r"^rules\s*:", re.M)
count = 0
with tarfile.open(src, "r:gz") as tf:
    for m in tf:
        # 안전한 추출: 일반 파일만, 절대 경로·상위 경로 금지, 심볼릭 링크 금지
        if not m.isfile():
            continue
        parts = m.name.split("/")
        if len(parts) < 2 or m.name.startswith("/") or ".." in parts:
            continue
        rel = "/".join(parts[1:])  # 최상위 <repo>-<commit>/ 제거
        if paths != ["."] and not any(rel == p or rel.startswith(p + "/") for p in paths):
            continue
        if not rel.endswith((".yaml", ".yml")) or "/.github/" in "/" + rel:
            continue
        if m.size > 2_000_000:
            continue
        data = tf.extractfile(m).read()
        text = data.decode("utf-8", "replace")
        # 규칙 파일만 (테스트용 YAML 대상 파일 제외)
        if not RULE_TOP.search(text):
            continue
        dst = os.path.join(out, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(data)
        count += 1
if count == 0:
    sys.exit("규칙 파일이 하나도 없습니다")
PY
      sec_err "규칙 추출 실패: $name"
      failed=1
      continue
    fi
    printf '%s\n%s\n' "$commit" "$url" >"$work/out/.commit"
    rm -rf "$dest.old"
    [ -d "$dest" ] && mv "$dest" "$dest.old"
    mv "$work/out" "$dest" && rm -rf "$dest.old"
    sec_log "  설치: $dest ($(find "$dest" -name '*.y*ml' | wc -l | tr -d ' ')개 규칙 파일)"
  done <"$SEC_RULES_LOCK"
}

# ---------------------------------------------------------------------------
# OSV 오프라인 DB
# ---------------------------------------------------------------------------
update_osv() {
  local ref seed db rc f
  ref=$(sec_image_ref osv-scanner) || {
    sec_err "images.lock 에 osv-scanner 가 없습니다."
    failed=1
    return
  }
  if ! docker image inspect "$ref" >/dev/null 2>&1; then
    sec_err "osv-scanner 이미지가 없습니다. update.sh --images 를 먼저 실행하세요."
    failed=1
    return
  fi
  seed="$TMP_ROOT/osv-seed"
  db="$TMP_ROOT/osv"
  mkdir -p "$seed" "$db"
  for f in "$SEC_PLUGIN"/docker/osv-seed/*.seed; do
    cp "$f" "$seed/$(basename "$f" .seed)"
  done
  sec_log "OSV 오프라인 DB 받는 중 (${OSV_ECOSYSTEMS// /, } — 수백 MB)..."
  # 이 컨테이너만 네트워크를 쓴다 (기본 bridge). 씨앗 lockfile 외에 사용자 코드는 마운트하지 않는다.
  docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
    --user "$(id -u):$(id -g)" -e HOME=/tmp --tmpfs /tmp:rw,size=256m \
    -e OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY=/db \
    -v "$seed:/seed:ro" -v "$db:/db" "$ref" \
    scan source -r --offline-vulnerabilities --download-offline-databases \
    --format json --output /tmp/seed.json /seed >"$TMP_ROOT/osv.log" 2>&1
  rc=$?
  if [ $rc -gt 1 ]; then
    sec_err "OSV DB 다운로드 실패 (종료코드 $rc): $(tail -n 3 "$TMP_ROOT/osv.log" | tr '\n' ' ')"
    failed=1
    return
  fi
  # 씨앗마다 기대하는 생태계 DB 가 모두 받아졌는지 확인 (일부만 받고 성공으로 끝나지 않게)
  local eco missing=""
  for eco in $OSV_ECOSYSTEMS; do
    [ -n "$(find "$db" -path "*/$eco/all.zip" 2>/dev/null | head -n 1)" ] || missing="$missing $eco"
  done
  if [ -n "$missing" ]; then
    sec_err "OSV DB 일부 생태계를 받지 못했습니다:$missing — 로그: $(tail -n 3 "$TMP_ROOT/osv.log" | tr '\n' ' ')"
    failed=1
    return
  fi
  date -u '+%Y-%m-%dT%H:%M:%SZ' >"$db/UPDATED_AT"
  rm -rf "$SEC_DATA/data/osv.old"
  [ -d "$SEC_DATA/data/osv" ] && mv "$SEC_DATA/data/osv" "$SEC_DATA/data/osv.old"
  mv "$db" "$SEC_DATA/data/osv" && rm -rf "$SEC_DATA/data/osv.old"
  sec_log "  설치: $SEC_DATA/data/osv ($(du -sh "$SEC_DATA/data/osv" | cut -f1), $(find "$SEC_DATA/data/osv" -name all.zip | wc -l | tr -d ' ')개 생태계)"
}

[ $DO_IMAGES -eq 1 ] && update_images
[ $DO_RULES -eq 1 ] && update_rules
[ $DO_OSV -eq 1 ] && update_osv

if [ $failed -ne 0 ]; then
  sec_err "일부 항목을 갱신하지 못했습니다. 위 메시지를 확인하세요."
  exit 1
fi
sec_log "업데이트 완료."
