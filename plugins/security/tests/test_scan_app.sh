# shellcheck shell=bash
# scan-app.sh 테스트
#   - 가짜 docker: 인자 거부(V3), 산출물 검사(확장자·ZIP·크기), D6(이미지 없음), D7(마운트 가시성) — 컨테이너를 띄우지 않음을 확인
#   - 실제 Docker(통합): V1 N1(MobSF 외부 차단·호스트 노출 없음), V2 모바일 기준선(APK·AAB·IPA), V3 리포트 위치·원문 미노출·스택 정리
#     픽스처 앱은 MobSF 이미지 안의 apktool·aapt2·apksigner·bundletool 로 네트워크 없이 빌드한다 (IPA 는 Xcode clang).
#     mobsf·gitleaks 이미지가 없으면 건너뛴다 (update.sh 를 먼저 실행).

SCAN_APP="$PLUGIN_DIR/scripts/scan-app.sh"

setup_fake() {
  export HOME="$SEC_TMP/home"
  mkdir -p "$HOME/apps"
  export DWK_SECURITY_DATA_DIR="$HOME/.local/share/dev-workflow-kit/security"
  export DWK_SECURITY_CONF_DIR="$HOME/.config/dev-workflow-kit/security"
  mkdir -p "$SEC_TMP/bin"
  cp "$TESTS_DIR/lib/fake-docker" "$SEC_TMP/bin/docker"
  export PATH="$SEC_TMP/bin:$PATH"
  export FAKE_LOG="$SEC_TMP/docker.log"
  : >"$FAKE_LOG"
  FAKE_IMAGES=$(awk '!/^[[:space:]]*(#|$)/ { printf "%s@%s ", $2, $4 }' "$PLUGIN_DIR/docker/images.lock")
  export FAKE_IMAGES
  python3 - "$HOME/apps/app.apk" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1], "w") as z:
    z.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00")
    z.writestr("classes.dex", b"dex\n035\x00")
PY
}

no_container_started() {
  if grep -q '^docker run\|^docker compose .* up' "$FAKE_LOG"; then
    fail "컨테이너가 기동됨: $(grep '^docker run\|^docker compose .* up' "$FAKE_LOG" | head -n 1)"
  fi
}

test_app_rejects_options_and_extra_args_without_containers() {
  setup_fake
  assert_status 2 "$SCAN_APP" --profile=android "$HOME/apps/app.apk"
  assert_contains "$OUT" "알 수 없는 옵션"
  assert_status 2 "$SCAN_APP" "$HOME/apps/app.apk" "$HOME/apps/app.apk"
  assert_contains "$OUT" "하나만"
  assert_status 2 "$SCAN_APP"
  no_container_started
}

test_app_rejects_non_artifacts_before_docker() {
  setup_fake
  # 확장자 (폴더·zip·홈)
  assert_status 1 "$SCAN_APP" "$HOME/apps"
  assert_contains "$OUT" "일반 파일이 아닙니다"
  cp "$HOME/apps/app.apk" "$HOME/apps/app.zip"
  assert_status 1 "$SCAN_APP" "$HOME/apps/app.zip"
  assert_contains "$OUT" "앱 산출물"
  # 확장자는 맞지만 ZIP 이 아님 / 매니페스트 없음
  printf 'plain text pretending to be an apk file\n' >"$HOME/apps/fake.apk"
  assert_status 1 "$SCAN_APP" "$HOME/apps/fake.apk"
  assert_contains "$OUT" "ZIP 시그니처"
  python3 -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1], "w").writestr("Payload/X.app/X", b"x")' "$HOME/apps/bad.ipa"
  assert_status 1 "$SCAN_APP" "$HOME/apps/bad.ipa"
  assert_contains "$OUT" "Info.plist"
  # 대문자 확장자도 산출물로 받는다 (검사는 통과해 D6·D7 로 간다). macOS 는 대소문자를 무시하므로 다른 이름으로
  cp "$HOME/apps/app.apk" "$HOME/apps/RELEASE.APK"
  FAKE_IMAGES="" assert_status 1 "$SCAN_APP" "$HOME/apps/RELEASE.APK"
  assert_contains "$OUT" "[D6]"
  no_container_started
}

test_app_d6_missing_mobsf_image_points_to_update() {
  setup_fake
  # gitleaks 만 있고 mobsf 가 없다
  FAKE_IMAGES=$(awk '!/^[[:space:]]*(#|$)/ && $1 != "mobsf" { printf "%s@%s ", $2, $4 }' "$PLUGIN_DIR/docker/images.lock")
  assert_status 1 "$SCAN_APP" "$HOME/apps/app.apk"
  assert_contains "$OUT" "[D6]"
  assert_contains "$OUT" "mobile-security-framework-mobsf@sha256:"
  assert_contains "$OUT" "update.sh"
  no_container_started
  [ ! -d "$DWK_SECURITY_DATA_DIR/reports" ] || [ -z "$(ls -A "$DWK_SECURITY_DATA_DIR/reports")" ] || fail "리포트 폴더가 생김"
}

test_app_d7_invisible_artifact_stops_before_mobsf() {
  setup_fake
  FAKE_RUN_OUTPUT="missing" assert_status 1 "$SCAN_APP" "$HOME/apps/app.apk"
  assert_contains "$OUT" "[D7]"
  assert_eq "$(grep -c '^docker run' "$FAKE_LOG")" 1 "(D7 확인용 컨테이너 1개만)"
  assert_contains "$(cat "$FAKE_LOG")" "--network none"
  assert_not_contains "$(cat "$FAKE_LOG")" " up "
  # 크기가 다르게 보여도 (일부만 공유·다른 파일) 멈춘다
  : >"$FAKE_LOG"
  FAKE_RUN_OUTPUT="12" assert_status 1 "$SCAN_APP" "$HOME/apps/app.apk"
  assert_contains "$OUT" "[D7]"
}

# --- 가짜 docker 로 MobSF 실패·정리 경로 (PR #32 리뷰 S7) ---------------------------------------------

# D7 을 통과시키고(크기 일치) Gitleaks 는 빈 결과를 내게 한다
_fake_pass_d7() {
  FAKE_RUN_OUTPUT=$(wc -c <"$HOME/apps/app.apk" | tr -d ' ')
  export FAKE_RUN_OUTPUT FAKE_RUN_REPORT_OUTPUT="[]"
}

_fake_scan() {
  local summary
  summary=$("$SCAN_APP" "$HOME/apps/app.apk" 2>"$SEC_TMP/scan.err" | tail -n 1)
  [ -f "$summary" ] || fail "summary 없음: $(tail -n 5 "$SEC_TMP/scan.err")"
  APP_RUN=$(dirname "$summary")
}

# 로그·status 에 실행별 API 키(64자 16진수)가 남지 않고 [MASKED] 로 바뀌었다
_assert_no_api_key_in_raw() {
  if grep -rqE '(^|[^:0-9a-f])[0-9a-f]{64}([^0-9a-f]|$)' "$APP_RUN/raw" "$SEC_TMP/scan.err"; then
    fail "API 키로 보이는 값이 남음: $(grep -rlE '[0-9a-f]{64}' "$APP_RUN/raw" | head -n 3)"
  fi
}

test_app_compose_up_failure_is_recorded_and_stack_removed() {
  setup_fake
  _fake_pass_d7
  FAKE_COMPOSE_UP_RC=1 _fake_scan
  assert_contains "$(awk -F '\t' '$1 == "mobsf"' "$APP_RUN/raw/status.tsv")" "MobSF 를 기동하지 못했습니다"
  assert_contains "$(cat "$APP_RUN/raw/compose-up.log")" "REST API Key: [MASKED]"
  _assert_no_api_key_in_raw
  grep -q '^docker compose -p dwk-sec-app-[0-9a-f]\{12\} .* down -v' "$FAKE_LOG" || fail "down -v 가 호출되지 않음"
  assert_not_contains "$(cat "$SEC_TMP/scan.err")" "내리지 못했습니다"
  assert_not_contains "$(cat "$FAKE_LOG")" "mobsf-client"
  assert_contains "$(cat "$APP_RUN/summary.md")" "| mobsf | failed |"
}

test_app_isolation_leak_stops_before_upload() {
  setup_fake
  _fake_pass_d7
  FAKE_COMPOSE_EXEC_OUTPUT="LEAK dns:example.com" _fake_scan
  assert_contains "$(awk -F '\t' '$1 == "mobsf"' "$APP_RUN/raw/status.tsv")" "격리 확인 실패"
  assert_contains "$(cat "$APP_RUN/raw/status.tsv")" "CVE-2024-29018"
  # 앱을 올리는 mobsf-client run 은 호출되지 않는다
  assert_not_contains "$(cat "$FAKE_LOG")" "mobsf-client"
  grep -q ' down -v' "$FAKE_LOG" || fail "down -v 가 호출되지 않음"
}

test_app_client_report_is_sanitized_and_original_removed() {
  setup_fake
  _fake_pass_d7
  # 시크릿 원문이 든 MobSF 리포트를 가짜 client 가 stdout 으로 낸다
  sed -e "s/@@GOOGLE_KEY@@/$GOOGLE_KEY_FAKE/g" -e "s/@@AWS_KEY@@/$AWS_KEY_FAKE/g" \
    "$TESTS_DIR/fixtures/app/mobsf-android.json" >"$SEC_TMP/report.json"
  FAKE_COMPOSE_RUN_FILE="$SEC_TMP/report.json" _fake_scan
  assert_eq "$(awk -F '\t' '$1 == "mobsf" { print $2 }' "$APP_RUN/raw/status.tsv")" ok
  [ ! -e "$APP_RUN/raw/mobsf-full.json" ] || fail "원본 리포트가 남음"
  [ -s "$APP_RUN/raw/mobsf.json" ] || fail "정제본 없음"
  if grep -rqF "$GOOGLE_KEY_FAKE" "$APP_RUN" || grep -rqF "$AWS_KEY_FAKE" "$APP_RUN"; then
    fail "시크릿 원문이 리포트 폴더에 남음"
  fi
  assert_contains "$(cat "$APP_RUN/raw/mobsf-client.log")" "REST API Key: [MASKED]"
  _assert_no_api_key_in_raw
  assert_contains "$(cat "$APP_RUN/findings.json")" "mobsf.manifest.app-is-debuggable"
  [ ! -e "$APP_RUN/raw/gitleaks.cid" ] || fail "cidfile 이 남음"
}

test_app_client_failure_removes_partial_report() {
  setup_fake
  _fake_pass_d7
  printf '{"partial": "%s"' "$AWS_KEY_FAKE" >"$SEC_TMP/partial.json"
  FAKE_COMPOSE_RUN_FILE="$SEC_TMP/partial.json" FAKE_COMPOSE_RUN_RC=5 _fake_scan
  assert_eq "$(awk -F '\t' '$1 == "mobsf" { print $2 }' "$APP_RUN/raw/status.tsv")" failed
  [ ! -e "$APP_RUN/raw/mobsf-full.json" ] || fail "실패한 실행의 원본 리포트가 남음"
  if grep -rqF "$AWS_KEY_FAKE" "$APP_RUN"; then fail "부분 리포트의 시크릿이 남음"; fi
  _assert_no_api_key_in_raw
}

test_app_stale_full_report_from_killed_run_is_removed() {
  setup_fake
  _fake_pass_d7
  # SIGKILL 로 끝난 이전 실행이 남긴 원본 리포트 (3시간 넘게 지남) — 다음 실행이 지운다 (리뷰 W5)
  local old="$DWK_SECURITY_DATA_DIR/reports/20200101-000000-app/raw"
  mkdir -p "$old"
  echo '{}' >"$old/mobsf-full.json"
  touch -t 202001010000 "$old/mobsf-full.json"
  local fresh="$DWK_SECURITY_DATA_DIR/reports/20991231-000000-app/raw"
  mkdir -p "$fresh"
  echo '{}' >"$fresh/mobsf-full.json"   # 지금 도는 다른 실행의 것 — 건드리면 안 된다
  _fake_scan
  [ ! -e "$old/mobsf-full.json" ] || fail "오래된 원본 리포트가 남음"
  [ -e "$fresh/mobsf-full.json" ] || fail "최근 원본 리포트(다른 실행)를 지움"
}

# --- 실제 Docker 통합 ----------------------------------------------------------

_app_ready() {
  [ "${SEC_TEST_DOCKER:-1}" = 0 ] && { echo "(SEC_TEST_DOCKER=0)"; return 1; }
  if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    echo "(Docker 엔진 없음)"; return 1
  fi
  # shellcheck disable=SC1091
  . "$PLUGIN_DIR/scripts/lib/common.sh"
  local n
  for n in mobsf gitleaks; do
    docker image inspect "$(sec_image_ref "$n")" >/dev/null 2>&1 || { echo "(이미지 없음: $n — update.sh 실행 필요)"; return 1; }
  done
}

# 커밋하지 않는 가짜 키 (실행할 때 조립)
GOOGLE_KEY_FAKE="AI""za""SyD""7Kq2Lm9Xw4Vb8Nc1Rt6Yh3Ju5Fg0Pe2S" # AIza + 35자 (gitleaks gcp-api-key)
AWS_KEY_FAKE="AK""IA""QZ7RT2XNVB4K8M3P"

# 홈 아래(Colima 공유 범위) 작업 폴더에 픽스처 소스를 복사하고 키를 넣는다
_app_workdir() {
  mkdir -p "$HOME/.cache/dev-workflow-kit-tests"
  APP_WORK=$(mktemp -d "$HOME/.cache/dev-workflow-kit-tests/app.XXXXXX")
  cp -R "$TESTS_DIR/fixtures/app/android" "$TESTS_DIR/fixtures/app/ios" "$APP_WORK/"
  find "$APP_WORK" -type f \( -name '*.xml' -o -name '*.smali' -o -name '*.c' -o -name '*.jsbundle' \) -print0 |
    xargs -0 python3 -c '
import sys
g, a, *files = sys.argv[1:]
for p in files:
    t = open(p, encoding="utf-8").read()
    open(p, "w", encoding="utf-8").write(t.replace("@@GOOGLE_KEY@@", g).replace("@@AWS_KEY@@", a))
' "$GOOGLE_KEY_FAKE" "$AWS_KEY_FAKE"
  mkdir -p "$APP_WORK/out"
}

# MobSF 이미지로 APK(디버그 키 서명)·AAB 를 네트워크 없이 빌드한다
_build_android() {
  docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
    -e HOME=/tmp -v "$APP_WORK:/w" --entrypoint sh "$(sec_image_ref mobsf)" -c '
set -e
T=$(dirname "$(ls /home/mobsf/Mobile-Security-Framework-MobSF/mobsf/StaticAnalyzer/tools/apktool_*.jar | head -n 1)")
cp -R /w/android /tmp/src
java -jar "$(ls "$T"/apktool_*.jar | head -n 1)" b -o /tmp/u.apk /tmp/src >/dev/null 2>&1
zipalign -f 4 /tmp/u.apk /tmp/a.apk
keytool -genkeypair -keystore /tmp/k.jks -storepass android -keypass android -alias androiddebugkey -keyalg RSA \
  -keysize 2048 -validity 3650 -dname "CN=Android Debug,O=Android,C=US" >/dev/null 2>&1
apksigner sign --ks /tmp/k.jks --ks-pass pass:android --out /w/out/vulnapp.apk /tmp/a.apk
aapt2 convert --output-format proto -o /tmp/p.apk /tmp/u.apk
python3 - <<PY
import zipfile
src = zipfile.ZipFile("/tmp/p.apk")
with zipfile.ZipFile("/tmp/base.zip", "w", zipfile.ZIP_DEFLATED) as out:
    for n in src.namelist():
        if n.startswith("META-INF/"):
            continue
        dst = "manifest/AndroidManifest.xml" if n == "AndroidManifest.xml" else ("dex/" + n if n.endswith(".dex") else n)
        out.writestr(dst, src.read(n))
PY
java -jar "$(ls "$T"/bundletool-all-*.jar | head -n 1)" build-bundle --modules=/tmp/base.zip --output=/w/out/vulnapp.aab >/dev/null 2>&1
' >"$APP_WORK/build.log" 2>&1
}

_build_ipa() {
  command -v xcrun >/dev/null 2>&1 && xcrun --sdk iphoneos --show-sdk-path >/dev/null 2>&1 || return 1
  local app="$APP_WORK/ipa/Payload/VulnApp.app"
  mkdir -p "$app"
  xcrun --sdk iphoneos clang -arch arm64 -miphoneos-version-min=12.0 -O0 -fno-stack-protector \
    -o "$app/VulnApp" "$APP_WORK/ios/main.c" >>"$APP_WORK/build.log" 2>&1 || return 1
  cp "$APP_WORK/ios/Info.plist" "$APP_WORK/ios/main.jsbundle" "$app/"
  (cd "$APP_WORK/ipa" && python3 -c '
import os, sys, zipfile
with zipfile.ZipFile(sys.argv[1], "w", zipfile.ZIP_DEFLATED) as z:
    for root, _d, files in os.walk("Payload"):
        for f in files:
            z.write(os.path.join(root, f))
' "$APP_WORK/out/vulnapp.ipa")
}

# 모든 docker 호출을 기록하는 래퍼 (실제 docker 로 전달)
_wrap_docker() {
  local real_docker
  real_docker=$(command -v docker)
  mkdir -p "$SEC_TMP/wrap"
  printf '#!/bin/sh\nprintf "%%s\\n" "$*" >>"%s"\nexec "%s" "$@"\n' "$SEC_TMP/calls.log" "$real_docker" >"$SEC_TMP/wrap/docker"
  chmod +x "$SEC_TMP/wrap/docker"
  : >"$SEC_TMP/calls.log"
}

# _scan_app <산출물> — APP_RUN 에 리포트 폴더
_scan_app() {
  local summary
  summary=$(PATH="$SEC_TMP/wrap:$PATH" "$SCAN_APP" "$1" 2>"$SEC_TMP/scan.err" | tail -n 1)
  [ -f "$summary" ] || fail "summary 없음: $(tail -n 8 "$SEC_TMP/scan.err")"
  APP_RUN=$(dirname "$summary")
  RUNS="${RUNS:-} $APP_RUN"
}

# 공통 단언: V3 리포트 위치·권한, 원문 미노출, N0/N1 호출 형태, 스택 정리
_assert_app_run_common() {
  case "$APP_RUN" in "$SEC_DATA/reports/"*) ;; *) fail "리포트 위치: $APP_RUN" ;; esac
  assert_eq "$(awk -F '\t' '$2 != "ok"' "$APP_RUN/raw/status.tsv")" "" "(도구 실패: $(cat "$APP_RUN/raw/status.tsv"))"
  if grep -rqF "$GOOGLE_KEY_FAKE" "$APP_RUN" || grep -rqF "$AWS_KEY_FAKE" "$APP_RUN"; then
    fail "시크릿 원문이 리포트에 남음"
  fi
  [ ! -e "$APP_RUN/raw/mobsf-full.json" ] || fail "정제 전 원본 리포트가 남음"
  # MobSF API 키(실행마다 무작위 64자 16진수)가 로그에 남지 않는다
  if grep -qE 'REST API Key|(^|[^:0-9a-f])[0-9a-f]{64}([^0-9a-f]|$)' "$APP_RUN/raw"/*.log "$SEC_TMP/scan.err" 2>/dev/null; then
    fail "API 키로 보이는 값이 로그에 남음"
  fi
  # docker run 은 전부 --network none, compose 는 툴킷 compose 파일과 실행별 프로젝트만, pull 없음
  assert_eq "$(grep '^run ' "$SEC_TMP/calls.log" | grep -vc -- '--network none')" 0 "(--network none 없는 docker run)"
  assert_eq "$(grep -c '^pull \|^compose.* pull' "$SEC_TMP/calls.log")" 0 "(스캔이 pull 함)"
  # (compose version 은 사전 점검 D3)
  assert_eq "$(grep '^compose ' "$SEC_TMP/calls.log" | grep -v '^compose version' |
    grep -vc -- "^compose -p dwk-sec-app-[0-9a-f]\{12\} -f $PLUGIN_DIR/docker/compose.yml ")" 0 "(다른 compose 호출)"
  grep -q '^compose .* down -v' "$SEC_TMP/calls.log" || fail "compose down -v 가 호출되지 않음"
  local proj
  proj=$(grep -o 'dwk-sec-app-[0-9a-f]\{12\}' "$SEC_TMP/calls.log" | head -n 1)
  [ -n "$proj" ] || fail "compose 프로젝트 이름을 찾지 못함"
  assert_eq "$(docker ps -a -q --filter "label=com.docker.compose.project=$proj")" "" "(남은 컨테이너)"
  assert_eq "$(docker volume ls -q --filter "label=com.docker.compose.project=$proj")" "" "(남은 볼륨)"
  assert_eq "$(docker network ls -q --filter "label=com.docker.compose.project=$proj")" "" "(남은 네트워크)"
  # 앱 문자열의 인젝션 문구는 summary 의 코드 블록 밖에 나오지 않는다 (T5)
  python3 - "$APP_RUN/summary.md" <<'PY' || fail "인젝션 문구가 코드 블록 밖에 있음"
import sys
inside = bad = False
for ln in open(sys.argv[1], encoding="utf-8"):
    if ln.startswith("````"):
        inside = not inside
    elif "IGNORE ALL PREVIOUS INSTRUCTIONS" in ln and not inside:
        bad = True
sys.exit(1 if bad else 0)
PY
  assert_eq "$(file_mode "$APP_RUN")" 700
  assert_eq "$(find "$APP_RUN" -type f ! -perm 600 | head -n 3)" "" "(600 아닌 리포트 파일)"
}

# _check_app_baseline <findings.json> <baseline.json> — test_scan_code.sh 의 _check_baseline 과 같은 형식
_check_app_baseline() {
  python3 - "$1" "$2" <<'PY' || fail "기준선 회귀 ($(basename "$2"))"
import json, sys
found = json.load(open(sys.argv[1]))["findings"]
base = json.load(open(sys.argv[2]))
def match(f, b):
    return ((("tool" not in b) or f["tool"] == b["tool"])
            and (("rule_id" not in b) or f["rule_id"] == b["rule_id"])
            and (("rule_prefix" not in b) or f["rule_id"].startswith(b["rule_prefix"]))
            and (("package" not in b) or f["location"]["package"] == b["package"])
            and (("file" not in b) or f["location"]["file"] == b["file"])
            and (("severity" not in b) or f["severity"] == b["severity"]))
missing = [b for b in base["must_find"] if not any(match(f, b) for f in found)]
unexpected = [b for b in base.get("must_not_find", []) if any(match(f, b) for f in found)]
for m in missing:
    print("    기준선 누락:", m)
for u in unexpected:
    print("    나오면 안 되는 결과:", u)
sys.exit(1 if missing or unexpected else 0)
PY
}

_cleanup_app() {
  # shellcheck disable=SC2086  # RUNS 는 공백으로 구분한 리포트 폴더 목록
  [ -n "${APP_WORK:-}" ] && rm -rf "$APP_WORK"
  for r in ${RUNS:-}; do rm -rf "$r"; done
  chmod -R u+w "$SEC_TMP" 2>/dev/null
  rm -rf "$SEC_TMP"
}

test_real_scan_app_android_apk_and_aab() {
  _app_ready || exit 77
  trap _cleanup_app EXIT
  _app_workdir
  _build_android || fail "픽스처 APK·AAB 빌드 실패: $(tail -n 5 "$APP_WORK/build.log")"
  if [ ! -s "$APP_WORK/out/vulnapp.apk" ] || [ ! -s "$APP_WORK/out/vulnapp.aab" ]; then
    fail "빌드 산출물 없음"
  fi
  _wrap_docker

  # APK — 디버그 키 서명이므로 debuggable 은 '릴리스로 다시 점검' 안내와 함께 나온다
  _scan_app "$APP_WORK/out/vulnapp.apk"
  _assert_app_run_common
  _check_app_baseline "$APP_RUN/findings.json" "$TESTS_DIR/baseline/app-android.json"
  local summary
  summary=$(cat "$APP_RUN/summary.md")
  assert_contains "$summary" "디버그 키(CN=Android Debug)로 서명된 빌드입니다"
  assert_contains "$summary" "## 수동 확인 (스택별 체크리스트)"
  assert_contains "$summary" "Play App Signing"
  assert_contains "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["profiles"])' "$APP_RUN/meta.json")" "android"
  # 앱이 정한 파일 이름(assets/<인젝션 문구>.jks)은 위치 열에 식별자 문자만 남아 렌더링된다 (리뷰 W1·W2) —
  # 렌더링 자체를 먼저 확인해야 "코드 블록 밖에 없음" 단언이 의미를 가진다
  assert_contains "$summary" "IGNORE?ALL?PREVIOUS?INSTRUCTIONS"

  # AAB — 툴킷이 universal APK 로 바꿔 분석한다 (MobSF 자체 변환은 arm64 에서 실패). 서명 결과는 빠진다
  _wrap_docker
  _scan_app "$APP_WORK/out/vulnapp.aab"
  _assert_app_run_common
  _check_app_baseline "$APP_RUN/findings.json" "$TESTS_DIR/baseline/app-android.json"
  local certs
  certs=$(python3 -c 'import json,sys; print(len([f for f in json.load(open(sys.argv[1]))["findings"] if f["rule_id"].startswith("mobsf.cert.")]))' "$APP_RUN/findings.json") ||
    fail "findings.json 을 읽지 못함"
  assert_eq "$certs" 0 "(AAB 에서 서명 결과가 나옴)"
  assert_contains "$(cat "$APP_RUN/summary.md")" "AAB 는 bundletool 로 universal APK 를 만들어 분석했습니다"
}

test_real_scan_app_ios_react_native_ipa() {
  _app_ready || exit 77
  trap _cleanup_app EXIT
  _app_workdir
  _build_ipa || { echo "(Xcode iphoneos SDK 없음)"; exit 77; }
  _wrap_docker
  _scan_app "$APP_WORK/out/vulnapp.ipa"
  _assert_app_run_common
  _check_app_baseline "$APP_RUN/findings.json" "$TESTS_DIR/baseline/app-ios.json"
  local profiles
  profiles=$(python3 -c 'import json,sys; print(" ".join(json.load(open(sys.argv[1]))["profiles"]))' "$APP_RUN/meta.json") ||
    fail "meta.json 을 읽지 못함"
  assert_eq "$profiles" "ios react-native"
  assert_contains "$(cat "$APP_RUN/summary.md")" "React Native: JS 번들"
}

# V1 N1: MobSF 컨테이너는 외부로 나갈 수 없고(IP·DNS), 호스트에 포트가 열리지 않는다 — scan-app.sh 와 같은 compose 파일·환경
test_real_n1_mobsf_is_internal_only() {
  _app_ready || exit 77
  N1_PROJECT="dwk-sec-app-$(od -An -N6 -tx1 /dev/urandom | tr -d ' \n')"
  trap 'docker compose -p "$N1_PROJECT" -f "$PLUGIN_DIR/docker/compose.yml" --profile client down -v --timeout 5 >/dev/null 2>&1; chmod -R u+w "$SEC_TMP" 2>/dev/null; rm -rf "$SEC_TMP"' EXIT
  DWK_MOBSF_IMAGE=$(sec_image_ref mobsf)
  DWK_MOBSF_API_KEY=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
  DWK_MOBSF_SECRET=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
  DWK_MOBSF_ADMIN_PW=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
  DWK_UID_GID="$(id -u):$(id -g)"
  DWK_APP_FILE="$PLUGIN_DIR/docker/compose.yml" DWK_APP_NAME=app.apk DWK_CLIENT_DIR="$PLUGIN_DIR/scripts/lib"
  export DWK_MOBSF_IMAGE DWK_MOBSF_API_KEY DWK_MOBSF_SECRET DWK_MOBSF_ADMIN_PW DWK_UID_GID DWK_APP_FILE DWK_APP_NAME DWK_CLIENT_DIR
  local c=(docker compose -p "$N1_PROJECT" -f "$PLUGIN_DIR/docker/compose.yml")
  "${c[@]}" up -d --wait --wait-timeout 300 mobsf >"$SEC_TMP/up.log" 2>&1 || fail "MobSF 기동 실패: $(tail -n 5 "$SEC_TMP/up.log")"
  local cid
  cid=$("${c[@]}" ps -q mobsf)
  [ -n "$cid" ] || fail "mobsf 컨테이너 id 없음"
  # 외부 IP·DNS 모두 실패해야 하고, 같은 네트워크의 mobsf 이름은 풀려야 한다 (차단이 '전부 실패'로 보이는 오판 방지)
  local probe
  probe=$("${c[@]}" exec -T mobsf python3 -c '
import socket
r = []
for t in (("1.1.1.1", 80), ("8.8.8.8", 53)):
    try:
        socket.create_connection(t, timeout=3); r.append("open")
    except OSError:
        r.append("blocked")
try:
    socket.gethostbyname("example.com"); r.append("dns-open")
except OSError:
    r.append("dns-blocked")
try:
    socket.gethostbyname("mobsf"); r.append("internal-ok")
except OSError:
    r.append("internal-fail")
print(" ".join(r))
') || fail "컨테이너 안 확인 실패"
  assert_eq "$probe" "blocked blocked dns-blocked internal-ok" "(N1 외부 차단)"
  # 호스트 노출 없음: 포트 바인딩이 없고, 네트워크는 internal
  assert_eq "$(docker inspect -f '{{json .HostConfig.PortBindings}}' "$cid")" "{}"
  assert_eq "$(docker inspect -f '{{range $p, $b := .NetworkSettings.Ports}}{{if $b}}{{$p}} {{end}}{{end}}' "$cid")" "" "(호스트에 열린 포트)"
  local net
  net=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$cid")
  assert_eq "$(docker network inspect -f '{{.Internal}}' "$net")" "true" "(scan-internal 이 internal 이 아님)"
  if curl -s -m 3 -o /dev/null http://127.0.0.1:8000/; then
    # 다른 프로그램이 8000 을 쓰고 있을 수 있다 — 그 경우 MobSF 응답인지 본다
    curl -s -m 3 http://127.0.0.1:8000/login/ | grep -qi mobsf && fail "호스트 127.0.0.1:8000 에서 MobSF 가 응답함"
  fi
}
