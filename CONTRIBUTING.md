# 기여 안내

이 저장소는 Claude Code·Codex 플러그인 마켓플레이스입니다. 플러그인은 `plugins/<이름>/`에 있고, 마켓플레이스 정의는 `.claude-plugin/marketplace.json`입니다.

## 개발

- 설치 없이 시험: `claude --plugin-dir plugins/workflow` (Codex는 `codex plugin marketplace add <clone 경로>`)
- workflow의 skill은 `plugins/workflow/skills/<이름>/SKILL.md`입니다. 각 skill 맨 앞의 "실행 환경" 블록은 Claude Code와 Codex 모두에서 동작하게 하기 위한 것이니 지우지 마세요. 안내 문장 안에는 `$ARGUMENTS`·`${CLAUDE_PLUGIN_ROOT}` 토큰을 쓰지 않습니다(Claude Code가 문장 안에서도 치환함).
- GitHub 작업은 `gh` CLI로 씁니다. 목록 조회는 `--paginate --jq '.[]'`로 받습니다.
- security 게이트: `plugins/security/tests/run.sh`(단위·통합 테스트), `plugins/security/tests/lint.sh`(shellcheck)

## 버전

플러그인마다 버전을 따로 매기고 [유의적 버전](https://semver.org/lang/ko/)을 따릅니다. security는 0.x라 마이너 버전에서도 동작이 바뀔 수 있습니다.

| 바뀐 것 | 올릴 자리 |
|---|---|
| 기존 사용자가 설정·사용법을 바꿔야 함 (요구 도구, 구조, 옵션 의미) | 메이저 (0.x는 마이너) |
| 기능 추가 | 마이너 |
| 버그 수정, 문서·안내 문구 | 패치 |

플러그인 폴더(`plugins/<이름>/`) 안의 파일을 바꾸면 플러그인 README·CHANGELOG만 바꿨더라도 **반드시 버전을 올립니다**(설치본에 함께 들어가기 때문). 버전이 그대로면 사용자의 업데이트가 새 내용을 받지 못할 수 있습니다. 저장소 루트 README·`docs/`만 바꾼 경우는 올리지 않습니다.

## 릴리스 절차

1. **버전 올리기** — 두 파일의 해당 플러그인 `version`을 같은 값으로 올립니다.
   - `plugins/<이름>/.claude-plugin/plugin.json`
   - `.claude-plugin/marketplace.json`
2. **변경 이력** — `plugins/<이름>/CHANGELOG.md`의 `[Unreleased]` 아래에 새 버전 절(`## [x.y.z] - YYYY-MM-DD`)을 만들고 `추가`·`변경`·`수정`으로 나눠 적습니다. 사용자가 바꿔야 하는 것은 **BREAKING**을 붙이고 맨 위 `> [!IMPORTANT]`로 알립니다. 맨 아래 링크 목록도 갱신합니다.
3. **PR 병합** 후 master에서 태그와 릴리스를 만듭니다.

   ```bash
   git checkout master && git pull --ff-only
   claude plugin tag plugins/<이름> --dry-run      # 만들 태그와 버전 일치를 먼저 확인
   claude plugin tag plugins/<이름> --push         # <이름>--v<버전> 태그
   gh release create <이름>--v<버전> --verify-tag --latest=false \
     --title "<이름> v<버전>" \
     --notes "$(scripts/release-notes.sh <이름> <버전>)"
   ```

   - `--verify-tag`: 태그를 잘못 적었을 때 새 태그를 만들지 않고 실패합니다.
   - `--latest=false`: 플러그인 두 개가 한 저장소에 있어 "Latest" 표시는 의미가 없습니다.
   - 0.x 플러그인도 `--prerelease`를 붙이지 않습니다(0.x 자체가 불안정 표시).
   - 지난 버전에 태그가 없으면 그 버전을 올린 커밋에 붙입니다: `git log --format='%h %s' -G'"version"' -- plugins/<이름>/.claude-plugin/plugin.json`으로 커밋을 찾고 `git tag -a <이름>--v<버전> <커밋> -m "<이름> <버전>"` 후 push합니다.

README의 버전 배지는 각 플러그인의 `plugin.json`을 읽으므로 따로 고치지 않습니다.
