---
title: /create-pr
tags: [workflow, command]
---

# /create-pr

상위: [Home](../Home.md) · [README](../../README.md)

현재 브랜치의 커밋과 diff를 분석해 프로젝트 PR 템플릿에 맞춰 PR을 생성합니다. 기본은 **Draft**, `--open` 인자를 주면 **Open** 상태로 만듭니다.

## 사용법

```
/create-pr [--open] [base=<branch>]
```

## 예시

```
/create-pr
/create-pr --open
/create-pr base=main
/create-pr --open base=develop
```

## 옵션

| 옵션 | 설명 |
|------|------|
| `--open` (또는 `open`) | Draft 대신 Open 상태로 PR 생성 |
| `base=<branch>` | base 브랜치를 강제로 지정 (예: `base=main`) |
| (인자 없음) | Draft 모드 + 자동 base 추론 |

## 실행 절차

1. 현재 브랜치 / 커밋 / 푸시 상태 파악 (보호 브랜치 차단)
2. Base 브랜치 결정 (인자 → `CLAUDE.md`/`AGENTS.md` 명시 → `origin/develop` → `origin/main`/`master` 순)
3. 변경 내역 분석 (`origin/<base>..HEAD` 커밋과 diff 수집)
4. 원격 푸시 확인 및 필요 시 `git push -u` (사용자 확인 후, force push는 금지)
5. PR 템플릿 로드 (`.github/PULL_REQUEST_TEMPLATE.md` 등 여러 경로 순차 탐색, 없으면 기본 본문)
6. 본문 작성: 커밋 prefix(`feat:`/`fix:`/`refactor:`/`update:`) 기반 분류, HTML 주석 유지, 데모 자리 비움
   - **라벨**: 저장소에 이미 있는 라벨 중 커밋 prefix·diff에 맞는 것을 모두 고른다 (새 라벨은 만들지 않음, 맞는 라벨이 없으면 생략하고 보고)
   - **연결 이슈·마일스톤**: 브랜치의 이슈 번호·작업 ID로 연결 이슈를 찾아 `Closes #N`, PR 마일스톤은 연결 이슈의 것을 사용 (임의 생성 금지)
7. PR 생성 (`mcp__github__create_pull_request` 우선, 실패 시 사용자 승인 후 `gh pr create` 폴백). MCP는 라벨·마일스톤을 받지 않으므로 생성 직후 붙이고 확인
8. URL / Draft·Open 상태 / base ← head / 커밋 수 / 변경 파일 / 라벨 / 마일스톤·연결 이슈 / 다음 단계 보고

## Base 브랜치 자동 추론

| 우선순위 | 조건 |
|---------|------|
| 1 | 인자에 `base=<branch>` 명시 |
| 2 | `CLAUDE.md` / `AGENTS.md`에 "PR 대상", "base branch", "기본 브랜치" 표기 존재 |
| 3 | `origin/develop` 존재 (Git-flow 컨벤션) |
| 4 | `origin/main` → `origin/master` 순서로 폴백 |

## PR 템플릿 탐색 경로

1. `.github/PULL_REQUEST_DESCRIPTION_TEMPLATE.md`
2. `.github/PULL_REQUEST_TEMPLATE.md`
3. `.github/pull_request_template.md`
4. `.github/PULL_REQUEST_TEMPLATE/*.md` (여러 개면 첫 번째)
5. `docs/PULL_REQUEST_TEMPLATE.md`
6. `docs/pull_request_template.md`
7. `PULL_REQUEST_TEMPLATE.md`
8. `pull_request_template.md`

발견되지 않으면 `🎯 요약 / 📋 작업 배경 / 🔧 변경 사항` 섹션만 가진 최소 본문을 사용합니다.

## 안전 규칙

- 현재 브랜치가 `main` / `master` / `develop` 같은 보호 브랜치면 PR 생성을 중단
- 동일 head→base 조합으로 이미 Open된 PR이 있으면 (`mcp__github__list_pull_requests` 또는 `gh pr list --head`) 신규 생성 대신 기존 URL을 안내
- `.env`, `*.key`, `credentials*` 등 민감 파일이 변경에 포함되면 사용자에게 경고 후 진행 여부 확인
- force push, base 브랜치 직접 commit, 다른 브랜치 checkout, 기존 PR 수정/머지/클로즈는 사용자 확인 없이 절대 수행하지 않음
- 본문에 사용자/동료의 개인정보 · API 키 · 토큰을 인용하지 않음
