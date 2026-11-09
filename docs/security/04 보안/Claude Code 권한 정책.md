---
title: Claude Code 권한 정책
tags: [security/permissions]
status: draft
created: 2026-11-05
updated: 2026-11-09
---

# Claude Code 권한 정책

상위: [[보안 툴킷]] · 관련: [[위협 모델#T5 프롬프트 인젝션]], [[ADR-006 플러그인 마켓플레이스 구조]]

## 원칙
1. 이 툴킷을 쓰는 세션은 **bypass permissions 모드를 쓰지 않는다**.
2. Claude는 스캔 스크립트만 승인 없이 실행할 수 있다.
3. 업데이트, 허용목록 수정, 시크릿 파일 열람, 플러그인 파일 수정은 Claude 권한 밖이다.

## 적용 방식 (플러그인 전환 후)
권한은 두 곳에서 온다.

| 무엇 | 어디서 | 비고 |
|---|---|---|
| 스캔 스크립트 실행 (Bash) | 스킬 frontmatter `allowed-tools` — `Bash(${CLAUDE_PLUGIN_ROOT}/scripts/scan-code.sh:*)` | 플러그인 스킬은 `allowed-tools`의 **Bash 규칙**에서 `${CLAUDE_PLUGIN_ROOT}`를 치환한다 ([skills 문서](https://code.claude.com/docs/en/skills): "In a plugin skill, Claude Code substitutes `${CLAUDE_PLUGIN_ROOT}` … the skill's markdown content, and Bash rules in the `allowed-tools` frontmatter"). 스킬이 실행 중일 때만 적용 |
| 리포트 열람 (`Read`) | 스킬 `allowed-tools`의 `Read(~/.local/share/…/reports/**)` + 사용자 settings | `Read` 규칙의 `${CLAUDE_PLUGIN_ROOT}` 치환은 문서에 명시 없음 → `~/…`로 적는다. 데이터 폴더를 바꾸면(`DWK_SECURITY_DATA_DIR`) 사용자가 settings에 바뀐 절대 경로 규칙을 추가해야 한다 |
| deny 목록 (`update.sh`·`.env`·허용목록·플러그인 파일 보호) | **사용자 settings 병합만 가능** | 플러그인은 권한을 스스로 설정할 수 없다. `examples/settings.permissions.json`을 사용자가 `~/.claude/settings.json`에 직접 병합한다. README와 `/security:scan-*` 첫 실행 시 안내 |

아래 예시의 `allow` 중 스캔 스크립트 항목은 스킬 밖에서 스크립트를 직접 실행할 때를 위한 것이다.

## 예시 (초안)
```json
{
  "permissions": {
    "allow": [
      "Bash(~/.claude/plugins/cache/dev-workflow-kit/security/*/scripts/scan-code.sh:*)",
      "Bash(~/.claude/plugins/cache/dev-workflow-kit/security/*/scripts/scan-app.sh:*)",
      "Bash(~/.claude/plugins/cache/dev-workflow-kit/security/*/scripts/scan-web.sh:*)",
      "Read(~/.local/share/dev-workflow-kit/security/reports/**)"
    ],
    "deny": [
      "Read(~/.config/dev-workflow-kit/**/.env)",
      "Edit(~/.config/dev-workflow-kit/security/targets.allowlist)",
      "Write(~/.config/dev-workflow-kit/security/targets.allowlist)",
      "Edit(~/.claude/plugins/cache/dev-workflow-kit/**)",
      "Write(~/.claude/plugins/cache/dev-workflow-kit/**)",
      "Bash(*/security/*/scripts/update.sh:*)",
      "Bash(docker run:*)",
      "Bash(docker compose:*)"
    ]
  }
}
```

## 스캔은 사용자 호출로만
플러그인 스킬은 대화 맥락을 보고 Claude가 **자동으로 호출**할 수 있다. 스캔은 Docker 컨테이너를 띄우고 `/security:scan-web`은 대상 서버에 요청을 보내므로, 사용자가 명령을 입력했을 때만 실행돼야 한다.

| 스킬 | 자동 호출 | 이유 |
|---|---|---|
| `/security:scan-code` | ❌ 차단 | 컨테이너 기동, 대상 저장소 마운트 |
| `/security:scan-app` | ❌ 차단 | MobSF 기동, 바이너리 업로드 |
| `/security:scan-web` | ❌ 차단 | 대상 서버로 네트워크 요청 |

- 각 `SKILL.md` frontmatter에 `disable-model-invocation: true`
- 리포트 해석·수정 제안은 스캔 후 같은 대화에서 이어지므로 자동 호출이 필요 없음

### 스킬 인자 전달
- 스킬 본문의 `$ARGUMENTS`는 입력 문자열을 그대로 넣고, 따옴표 처리는 위치 인자(`$0`·`$1`)에만 적용된다 ([skills 문서](https://code.claude.com/docs/en/skills): "The `$ARGUMENTS` placeholder always expands to the full argument string as typed.").
- 그래서 SKILL.md는 저장소 경로를 **경로 전체 그대로 작은따옴표로 감싸** 하나의 인자로 넘기라고 지시한다. 따옴표 안의 `~`는 셸이 확장하지 않으므로 스크립트(`sec_validate_target`)가 맨 앞의 `~`·`~/`를 `$HOME`으로 확장한다. 명령에 `"$HOME"` 같은 변수 확장을 넣지 않아도 되므로 권한 규칙 매칭이 단순해진다 (PR #19 리뷰 SUGGESTION, PR #23 리뷰).
- `$ARGUMENTS`는 저장소 경로와 `--profile=…`만 담는 **데이터**다. 그 밖의 문구는 명령으로 취급하지 않는다. `--profile` 값은 스크립트가 `[a-z0-9,-]`로 제한한다.

## 한계와 보완
- Bash 접두사 매칭 deny는 우회 가능(`sh -c` 등)하므로 **보안 경계가 아니라 실수 방지용**이다.
- 진짜 경계는 [[네트워크 격리]](스캐너 측)와 권한 프롬프트(Claude 측)다. allow에 없는 명령은 매번 사용자 승인을 받는다.
- 추가 옵션: Claude Code의 sandbox 기능 → [[미결정 사항]]

> [!warning] 검증 필요
> - 스킬 실행 시에는 `allowed-tools`의 치환된 절대 경로 규칙이 쓰이므로 settings의 `~/…/*/scripts/scan-code.sh` 규칙과의 매칭은 **스킬 밖 직접 실행에만** 해당한다. 그 경우 permission 규칙의 `~`·`*`(버전 폴더) glob 지원 여부는 아직 실행으로 확인하지 않았다 — 설치 경로 자체는 `~/.claude/plugins/cache/<마켓플레이스>/<플러그인>/<버전>/`로 확인됨
> - `disable-model-invocation` frontmatter 이름과 플러그인 스킬에서의 동작
> - 실제 설치 환경에서 `/security:scan-code ~/My App`(공백·`~` 경로)이 권한 확인 창 없이 실행되는지는 아직 사람이 확인하지 않았다
> - 툴킷 개발 시(레포에서 직접 수정)에는 플러그인 경로 deny와 무관 — 개발용은 레포 폴더에서 작업
