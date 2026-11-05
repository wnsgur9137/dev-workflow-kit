---
title: Claude Code 권한 정책
tags: [security/permissions]
status: draft
created: 2026-11-05
updated: 2026-11-05
---

# Claude Code 권한 정책

상위: [[보안 툴킷]] · 관련: [[위협 모델#T5 프롬프트 인젝션]], [[ADR-006 플러그인 마켓플레이스 구조]]

## 원칙
1. 이 툴킷을 쓰는 세션은 **bypass permissions 모드를 쓰지 않는다**.
2. Claude는 스캔 스크립트만 승인 없이 실행할 수 있다.
3. 업데이트, 허용목록 수정, 시크릿 파일 열람, 플러그인 파일 수정은 Claude 권한 밖이다.

## 적용 방식 (플러그인 전환 후)
플러그인은 권한을 스스로 설정할 수 없다. 플러그인에 포함된 예시 `examples/settings.permissions.json`을 사용자가 **`~/.claude/settings.json`에 직접 병합**한다. README와 `/security:scan-*` 첫 실행 시 안내.

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

## 한계와 보완
- Bash 접두사 매칭 deny는 우회 가능(`sh -c` 등)하므로 **보안 경계가 아니라 실수 방지용**이다.
- 진짜 경계는 [[네트워크 격리]](스캐너 측)와 권한 프롬프트(Claude 측)다. allow에 없는 명령은 매번 사용자 승인을 받는다.
- 스킬 frontmatter `allowed-tools`로 스캔 스크립트만 허용하는 방식도 검토 (위 settings 병합 없이 동작 가능할 수 있음)
- 추가 옵션: Claude Code의 sandbox 기능 → [[미결정 사항]]

> [!warning] 검증 필요
> - permission 규칙에서 `~`·`*`(버전 폴더) glob 지원 여부 — 설치 경로 자체는 `~/.claude/plugins/cache/<마켓플레이스>/<플러그인>/<버전>/`로 확인됨
> - `disable-model-invocation` frontmatter 이름과 플러그인 스킬에서의 동작
> - 스킬 `allowed-tools`에 `${CLAUDE_PLUGIN_ROOT}` 경로 사용 가능 여부 → 가능하면 settings 병합 불필요
> - 툴킷 개발 시(레포에서 직접 수정)에는 플러그인 경로 deny와 무관 — 개발용은 레포 폴더에서 작업
