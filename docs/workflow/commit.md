---
title: /commit
tags: [workflow, command]
---

# /commit

상위: [Home](../Home.md) · [README](../../README.md)

스테이징된 변경과 **이 레포의 기존 커밋 컨벤션**을 분석해 커밋 메시지를 만들고 커밋합니다. gitmoji와 Conventional Commits 형식을 지원하며, push는 절대 자동 실행하지 않습니다.

## 사용법

```
/commit [-G|--no-gitmoji] [-g|--gitmoji] [-C|--no-coauthor] [-a|--all] [-e|--amend] [-S|--no-split] [-y|--yes] [-h|--help]
```

## 예시

```
/commit                  # 컨벤션 감지 → 메시지 생성 → 미리보기 후 커밋
/commit --gitmoji        # 컨벤션이 이모지를 안 써도 gitmoji 강제
/commit --no-gitmoji     # gitmoji 없이
/commit -ay              # = --all --yes (전체 스테이징 + 미리보기 생략)
/commit --amend          # 직전 커밋 수정
/commit --no-coauthor    # Co-Authored-By 푸터 제거
```

## 옵션

> 별칭 규칙: **소문자 = 동작 켜기, 대문자 = 끄기/제거(`--no-*`)**. 묶어 쓰기 가능(예: `-ay` = `--all --yes`).

| 옵션 | 짧은 별칭 | 설명 |
|------|------|------|
| `--no-gitmoji` | `-G` | gitmoji를 절대 붙이지 않음 (최우선) |
| `--gitmoji` | `-g` | 컨벤션이 이모지를 안 써도 gitmoji 강제 |
| `--no-coauthor` | `-C` | `Co-Authored-By: Claude ...` 푸터 제거 (기본은 유지) |
| `--all` | `-a` | 스테이징된 변경이 없을 때 확인 없이 `git add -A` 후 진행 |
| `--amend` | `-e` | 새 커밋 대신 직전 커밋 수정 (푸시된 경우 경고) |
| `--no-split` | `-S` | 변경이 섞여 있어도 커밋 분리를 제안하지 않고 단일 커밋 |
| `--yes` | `-y` | 커밋 전 미리보기 확인 생략 (민감 파일 경고는 유지) |
| `--help` | `-h` | 옵션 설명·동작 절차를 출력하고 종료 (커밋하지 않음) |

## gitmoji 사용 여부 우선순위

| 우선순위 | 조건 | 결과 |
|---------|------|------|
| 1 | `--no-gitmoji` 인자 | 사용 안 함 |
| 2 | `--gitmoji` 인자 | 사용 |
| 3 | 기존 커밋이 이모지를 **일관되게 사용** | 사용 |
| 3 | 기존 커밋이 이모지를 **안 씀** | 사용 안 함 |
| 4 | 컨벤션 불명확 / 히스토리 거의 없음 | 기본값 ON |

> gitmoji를 쓰기로 결정됐는데 CLI가 없으면 설치 여부를 묻고, 승인 시 `brew install gitmoji`(없으면 `npm i -g gitmoji-cli`)로 설치합니다. 메시지에는 유니코드 이모지 문자(`✨`)를 직접 넣습니다.

## 실행 절차

1. 변경 / 스테이징 상태 파악 (스테이징 없으면 확인, 보호 브랜치 경고)
2. 기존 커밋 컨벤션 분석 (형식·이모지·언어·본문·scope·co-author 패턴)
3. gitmoji 사용 여부 결정 (위 우선순위, 필요 시 CLI 설치)
4. 커밋 분리 판단 (여러 논리 단위면 분리 제안, `--no-split`로 생략)
5. 메시지 생성 (`[emoji ]type(scope): 요약` + 선택적 본문 + Co-Authored-By 푸터)
6. 미리보기 + 사용자 확인 (`--yes`면 생략)
7. 커밋 실행 (`git commit -F -`, `--amend` 지원, pre-commit hook 존중)
8. SHA / 변경 파일 / gitmoji·co-author 여부 / 다음 단계 보고

## 안전 규칙

- push, force push, 브랜치 checkout/생성, reset/rebase는 사용자 확인 없이 절대 자동 실행하지 않음 (커밋까지만)
- `.env`, `*.key`, `*.pem`, `credentials*` 등 민감 파일이 스테이징에 포함되면 경고 후 진행 여부 확인 (`--yes`여도 유지)
- API 키·토큰·비밀번호가 diff에 보이면 경고하고 메시지에 인용하지 않음
- 보호 브랜치(`main`/`master`/`develop`) 직접 커밋 시 경고
