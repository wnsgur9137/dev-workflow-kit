# shellcheck shell=bash
# common.sh 테스트 — 검증 계획 V3 안전장치(경로 검증·Docker 사전 점검), run-id, 폴더 권한, lock 형식
# 각 test_* 함수는 별도 프로세스에서 실행되며 $SEC_TMP 는 테스트마다 새 임시 폴더다.

# 가짜 홈·데이터·설정 폴더로 common.sh 를 불러온다 (실제 ~ 를 건드리지 않는다)
load_common() {
  REAL_HOME=$HOME
  export HOME="$SEC_TMP/home"
  mkdir -p "$HOME/projects/app" "$HOME/.ssh" "$HOME/.aws"
  export DWK_SECURITY_DATA_DIR="$HOME/.local/share/dev-workflow-kit/security"
  export DWK_SECURITY_CONF_DIR="$HOME/.config/dev-workflow-kit/security"
  # shellcheck disable=SC1091
  . "$PLUGIN_DIR/scripts/lib/common.sh"
}

# 가짜 docker 를 PATH 맨 앞에 둔다
use_fake_docker() {
  mkdir -p "$SEC_TMP/bin"
  cp "$TESTS_DIR/lib/fake-docker" "$SEC_TMP/bin/docker"
  export PATH="$SEC_TMP/bin:$PATH"
}

# --- 경로 검증 ---------------------------------------------------------------

test_validate_accepts_project_dir_and_prints_realpath() {
  load_common
  ln -s "$HOME/projects/app" "$SEC_TMP/link-to-app"
  local got
  got=$(sec_validate_target "$SEC_TMP/link-to-app" dir) || fail "정상 경로 거부: $got"
  assert_eq "$got" "$(cd -P "$HOME/projects/app" && pwd -P)"
}

test_validate_rejects_home_root_and_parents() {
  load_common
  assert_status 1 sec_validate_target "$HOME" dir
  assert_contains "$OUT" "홈 디렉터리"
  assert_status 1 sec_validate_target "$HOME/" dir
  assert_status 1 sec_validate_target "$(dirname "$HOME")" dir
  assert_status 1 sec_validate_target / dir
}

test_validate_rejects_tilde_style_home() {
  load_common
  # /security:scan-code ~ 는 셸이 확장해 홈 경로가 들어온다
  assert_status 1 sec_validate_target ~ dir
}

test_validate_rejects_symlink_to_home() {
  load_common
  ln -s "$HOME" "$HOME/projects/sneaky"
  assert_status 1 sec_validate_target "$HOME/projects/sneaky" dir
  assert_contains "$OUT" "홈 디렉터리"
}

test_validate_rejects_credential_dirs() {
  load_common
  assert_status 1 sec_validate_target "$HOME/.ssh" dir
  assert_contains "$OUT" "자격증명"
  mkdir -p "$HOME/.aws/sub"
  assert_status 1 sec_validate_target "$HOME/.aws/sub" dir
}

test_validate_rejects_system_and_top_level_dirs() {
  load_common
  assert_status 1 sec_validate_target /usr/bin dir
  assert_status 1 sec_validate_target /etc dir
  assert_status 1 sec_validate_target /tmp dir
  assert_status 1 sec_validate_target /System dir
  # 루트의 상대 심볼릭 링크(/etc -> private/etc)가 '//private/etc' 로 정규화돼 검사를 우회하면 안 된다
  [ -L /etc ] && { assert_eq "$(sec_realpath /etc)" "/private/etc"; }
  assert_status 1 sec_validate_target //etc dir
}

test_validate_rejects_toolkit_data_overlap() {
  load_common
  sec_init_dirs
  assert_status 1 sec_validate_target "$DWK_SECURITY_DATA_DIR/reports" dir
  assert_contains "$OUT" "툴킷 데이터"
  # 데이터 폴더를 포함하는 상위 경로도 금지
  assert_status 1 sec_validate_target "$HOME/.local" dir
}

test_validate_rejects_mount_breaking_chars_and_missing() {
  load_common
  mkdir -p "$HOME/projects/a:b" "$HOME/projects/a,b"
  assert_status 1 sec_validate_target "$HOME/projects/a:b" dir
  assert_contains "$OUT" "쓸 수 없습니다"
  assert_status 1 sec_validate_target "$HOME/projects/a,b" dir
  assert_status 1 sec_validate_target "$HOME/projects/nope" dir
  assert_contains "$OUT" "없습니다"
  assert_status 1 sec_validate_target "" dir
}

test_validate_kind_dir_vs_file() {
  load_common
  echo x >"$HOME/projects/app/app.apk"
  assert_status 1 sec_validate_target "$HOME/projects/app/app.apk" dir
  assert_status 0 sec_validate_target "$HOME/projects/app/app.apk" file
  assert_status 1 sec_validate_target "$HOME/projects/app" file
}

# --- 폴더·run-id -------------------------------------------------------------

test_init_dirs_permissions() {
  load_common
  sec_init_dirs || fail "sec_init_dirs 실패"
  assert_eq "$(file_mode "$DWK_SECURITY_DATA_DIR")" 700
  assert_eq "$(file_mode "$DWK_SECURITY_DATA_DIR/reports")" 700
  assert_eq "$(file_mode "$DWK_SECURITY_CONF_DIR")" 700
}

test_new_run_creates_unique_run_dirs() {
  load_common
  sec_new_run code || fail "sec_new_run 실패"
  local first=$SEC_RUN_DIR
  case "$SEC_RUN_ID" in
    [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]-code) ;;
    *) fail "run-id 형식 오류: $SEC_RUN_ID" ;;
  esac
  [ -d "$first/raw" ] || fail "raw/ 없음"
  assert_eq "$(file_mode "$first")" 700
  assert_eq "$(file_mode "$first/run.log")" 600
  sec_log "기록 테스트"
  assert_contains "$(cat "$first/run.log")" "기록 테스트"
  sec_new_run code
  [ "$SEC_RUN_DIR" != "$first" ] || fail "같은 초에 run-id 가 겹침"
  assert_status 1 sec_new_run exploit
}

test_new_run_files_stay_inside_data_dir() {
  load_common
  sec_new_run web
  _sec_is_within "$SEC_RUN_DIR" "$DWK_SECURITY_DATA_DIR/reports" || fail "리포트가 데이터 폴더 밖: $SEC_RUN_DIR"
  # 점검 대상 폴더에는 아무것도 생기지 않는다
  assert_eq "$(ls -A "$HOME/projects/app")" ""
}

# --- lock 파일 ---------------------------------------------------------------

test_repo_lock_files_are_valid() {
  load_common
  sec_validate_images_lock || fail "images.lock 형식 오류"
  sec_validate_rules_lock || fail "rules.lock 형식 오류"
}

test_images_lock_parsing_and_validation() {
  load_common
  local d1 d2
  d1=$(printf 'a%.0s' $(seq 64))
  d2=$(printf 'b%.0s' $(seq 64))
  export SEC_IMAGES_LOCK="$SEC_TMP/images.lock"
  printf '# 주석\n\nsemgrep semgrep/semgrep 1.0.0 sha256:%s linux/amd64,linux/arm64\n' "$d1" >"$SEC_IMAGES_LOCK"
  sec_validate_images_lock || fail "정상 lock 거부"
  assert_eq "$(sec_image_ref semgrep)" "semgrep/semgrep@sha256:$d1"
  assert_eq "$(sec_image_field semgrep platforms)" "linux/amd64,linux/arm64"
  assert_status 1 sec_image_ref nope
  printf 'semgrep img 1 sha256:%s linux/amd64\nsemgrep img 1 sha256:%s linux/amd64\nx img 1 latest linux/amd64\ny img 1\n' "$d1" "$d2" >"$SEC_IMAGES_LOCK"
  assert_status 1 sec_validate_images_lock
  assert_contains "$OUT" "이름 중복"
  assert_contains "$OUT" "digest 형식 오류"
  assert_contains "$OUT" "열이 5개가 아닙니다"
}

test_rules_lock_validation() {
  load_common
  export SEC_RULES_LOCK="$SEC_TMP/rules.lock"
  printf 'semgrep-rules https://github.com/semgrep/semgrep-rules %s generic,python\n' "$(printf 'c%.0s' $(seq 40))" >"$SEC_RULES_LOCK"
  sec_validate_rules_lock || fail "정상 rules.lock 거부"
  printf 'r http://x main .\n' >"$SEC_RULES_LOCK"
  assert_status 1 sec_validate_rules_lock
  assert_contains "$OUT" "https URL"
  assert_contains "$OUT" "커밋 해시"
}

# --- Docker 사전 점검 D1~D6 ---------------------------------------------------

test_preflight_d1_no_docker_cli() {
  load_common
  mkdir -p "$SEC_TMP/emptybin"
  # docker 가 없는 PATH (기본 유틸만)
  PATH="$SEC_TMP/emptybin:/usr/bin:/bin" assert_status 1 sec_preflight code
  assert_contains "$OUT" "[D1]"
  assert_contains "$OUT" "colima"
}

test_preflight_d2_engine_stopped() {
  load_common
  use_fake_docker
  FAKE_INFO_FAIL=1 assert_status 1 sec_preflight code
  assert_contains "$OUT" "[D2]"
  assert_contains "$OUT" "colima start"
}

test_preflight_d3_compose_v1_or_missing() {
  load_common
  use_fake_docker
  FAKE_COMPOSE=1.29.2 assert_status 1 sec_preflight code
  assert_contains "$OUT" "[D3]"
  FAKE_COMPOSE="" assert_status 1 sec_preflight code
  assert_contains "$OUT" "[D3]"
  FAKE_COMPOSE=v5.1.0 assert_status 0 sec_preflight code
}

test_preflight_d4_podman_rejected() {
  load_common
  use_fake_docker
  FAKE_COMPONENTS="Podman Engine Conmon" assert_status 1 sec_preflight code
  assert_contains "$OUT" "[D4]"
  assert_contains "$OUT" "Podman"
  FAKE_COMPONENTS="" assert_status 1 sec_preflight code
  assert_contains "$OUT" "[D4]"
}

test_preflight_d5_low_memory_warns_only() {
  load_common
  use_fake_docker
  FAKE_MEM=$((2 * 1024 * 1024 * 1024)) assert_status 0 sec_preflight app
  assert_contains "$OUT" "[D5]"
  assert_contains "$OUT" "8GB"
  # 4GB 로 설정한 VM 은 보고값이 조금 작아도 scan-code 경고 없음
  FAKE_MEM=4100000000 assert_status 0 sec_preflight code
  assert_not_contains "$OUT" "[D5]"
}

test_preflight_d6_missing_image_points_to_update_and_never_pulls() {
  load_common
  use_fake_docker
  local d
  d=$(printf 'a%.0s' $(seq 64))
  export SEC_IMAGES_LOCK="$SEC_TMP/images.lock"
  printf 'semgrep semgrep/semgrep 1.0.0 sha256:%s linux/arm64\n' "$d" >"$SEC_IMAGES_LOCK"
  export FAKE_LOG="$SEC_TMP/docker.log"
  assert_status 1 sec_preflight code semgrep
  assert_contains "$OUT" "[D6]"
  assert_contains "$OUT" "update.sh"
  assert_not_contains "$(cat "$FAKE_LOG")" "pull"
  assert_not_contains "$(cat "$FAKE_LOG")" "docker run"
  FAKE_IMAGES="semgrep/semgrep@sha256:$d" assert_status 0 sec_preflight code semgrep
  assert_status 1 sec_preflight code unknown-tool
  assert_contains "$OUT" "images.lock 에 'unknown-tool'"
}

test_preflight_real_docker_runtime() {
  [ "${SEC_TEST_DOCKER:-1}" = 0 ] && { echo "(SEC_TEST_DOCKER=0)"; exit 77; }
  if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    echo "(Docker 엔진 없음)"
    exit 77
  fi
  load_common
  # docker CLI 는 ~/.docker 의 컨텍스트 설정을 읽으므로 실제 홈으로 실행한다
  HOME=$REAL_HOME sec_preflight code || fail "실제 런타임에서 사전 점검 실패"
  [ -n "$SEC_DOCKER_CONTEXT" ] || fail "컨텍스트 기록 없음"
}

# --- detect.sh ---------------------------------------------------------------

test_detect_sh_labels() {
  load_common
  # shellcheck disable=SC1091
  . "$PLUGIN_DIR/scripts/lib/detect.sh"
  local tsv
  tsv=$(sec_detect_profiles "$TESTS_DIR/fixtures/detect/flutter-app") || fail "감지 실패"
  assert_eq "$(printf '%s\n' "$tsv" | sec_profile_labels)" "android:android/, flutter, ios:ios/"
  assert_eq "$(sec_detect_profiles "$TESTS_DIR/fixtures/detect/none" | sec_profile_labels)" "(감지 없음 — 공통 기반만 적용)"
  assert_eq "$(sec_detect_profiles "$TESTS_DIR/fixtures/detect/none" web | sec_profile_labels)" "web"
}
