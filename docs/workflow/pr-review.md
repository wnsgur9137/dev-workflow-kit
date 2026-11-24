---
title: /pr-review
tags: [workflow, command]
---

# /pr-review

상위: [Home](../Home.md) · [README](../../README.md)

PR의 변경 사항을 분석하고, GitHub에 인라인 리뷰 코멘트를 자동으로 게시합니다.

## 사용법

```
/pr-review <PR_URL | PR_NUMBER> [options]
```

PR 번호(`32`, `#32`)만 넘기면 현재 폴더의 GitHub 저장소의 PR로 봅니다. fork처럼 GitHub remote가 둘 이상이고 `gh repo set-default`로 정한 적이 없으면 어느 저장소인지 묻습니다. github.com 저장소만 번호로 받고, 저장소를 찾지 못하면 URL 전체를 입력하라고 안내하고 멈춥니다.

## 예시

```
/pr-review https://github.com/owner/repo/pull/123
/pr-review 123
/pr-review https://github.com/owner/repo/pull/123 --mode=strict
/pr-review https://github.com/owner/repo/pull/123 --focus=security,performance
```

## 옵션

| 옵션 | 설명 |
|------|------|
| `--mode=strict` | 모든 severity 코멘트 생성, WARNING 2개 이상이면 REQUEST_CHANGES |
| `--mode=normal` | 표준 판정 매트릭스 적용 (기본값) |
| `--mode=relaxed` | CRITICAL만 코멘트, 나머지는 Summary에만 기록 |
| `--focus=항목,...` | 지정 카테고리만 집중 리뷰 (예: security,performance,memory) |
| `--skip=항목,...` | 지정 severity/카테고리 건너뛰기 (예: nitpick,style) |
| `--no-codex` | [Codex 교차 리뷰](#codex-교차-리뷰)를 끄고 Claude 리뷰만 수행 |
| `--help` | `/pr-review` 도움말 표시 |

## 리뷰 프로세스

1. PR URL·번호 파싱 + 상태 확인 (draft/merged/CI)
2. `gh` CLI로 PR 정보 수집 (기존 리뷰 중복 방지, 재리뷰 감지)
3. 보안 스캔 (Secret/Code/Dependabot alerts를 동시에 조회)
4. 레포지토리 컨텍스트 분석 (로컬 일치 시 자동, 외부 레포 시 사용자 선택)
5. 변경 파일 확장자로 PR 타입 감지 (iOS/Android/FrontEnd/BackEnd)
6. Codex 교차 리뷰를 백그라운드로 시작
7. 타입별 우선순위에 따라 코드 리뷰 (Claude)
8. 보안 민감 변경이 있으면 [보안 관점 패스](#보안-관점-패스)
9. Codex 결과를 검증해 Claude 리뷰와 합침
10. CLI에 리뷰 결과 출력 → 사용자가 게시할 코멘트를 선택
11. GitHub PR에 선택된 인라인 코멘트 게시
12. 리뷰 결과 기록

## 보안 관점 패스

플랫폼 기준 리뷰(7번)는 전체를 훑느라 보안 문제를 얕게 볼 수 있어, 보안에 민감한 변경이 있으면 **그 파일만 보안 관점으로 한 번 더** 봅니다.

- **실행 조건**: 경로·파일 이름(`auth`, `token`, `crypto`, `payment` 등), diff 내용(비밀번호·키 처리, 암호화, SQL·셸 문자열 조립, 역직렬화, 쿠키·CORS·TLS 설정, `innerHTML` 같은 HTML 주입 지점 등), 플랫폼 설정(`Info.plist` ATS, `AndroidManifest.xml` exported 등), 보안 경고, `--focus=security` 중 하나라도 해당하면 실행합니다. `--focus=security`면 변경 파일 전체를 봅니다. `--skip=security`로 끕니다.
- **점검 항목**: 주입, 인증·인가, 시크릿, 데이터 노출, 암호, 입력 검증, 플랫폼별 항목(iOS·Android·Web·Backend)
- **판정**: 실제 보안 문제만 지적합니다. 악용 가능하면 CRITICAL, 추가 조건이 필요한 약점이면 WARNING, 다른 저장소라 입력 출처를 확인할 수 없으면 QUESTION. 앞선 리뷰·보안 경고와 겹치면 새로 만들지 않고 합칩니다.
- 대상 diff가 크면 서브에이전트에 맡길 수 있습니다. 앞선 리뷰의 결론은 넘기지 않고, 빈 응답이면 직접 수행합니다.
- 결과는 Summary의 `Security Pass` 섹션에 실행 여부와 근거로 남습니다.

## Codex 교차 리뷰

Claude 리뷰에 **Codex 리뷰를 더합니다.** Claude 리뷰를 대신하지 않습니다. 옵션 없이 기본으로 실행하고, `--no-codex`로 끕니다.

> **외부 전송**: PR의 코드·diff가 Codex(OpenAI)로 전송됩니다. 외부로 보내면 안 되는 저장소에서는 `--no-codex`를 쓰세요.

**필요한 것**: [Codex CLI](https://github.com/openai/codex) 설치와 로그인(`codex login`). 없으면 생략합니다.

**동작**

- Claude가 리뷰하는 동안 `codex exec`(읽기 전용 sandbox, 세션 기록 없음)를 백그라운드로 돌립니다. **Claude 리뷰 결과는 Codex에 넘기지 않습니다** — 독립된 시각을 유지하기 위해서입니다.
- 리뷰 범위

  | PR | Codex가 보는 것 |
  |---|---|
  | 현재 저장소 | PR head의 임시 worktree. 커밋된 파일만 있고 변경 밖 코드도 읽음. 작업 폴더의 `.env` 같은 ignore·미추적 파일은 넘기지 않음 |
  | 다른 저장소 | PR diff만 |

  증분 리뷰를 고르면 Codex도 이전 리뷰 이후 커밋만 봅니다.
- PR 내용이 Codex를 조종하지 못하도록 사용자 `~/.codex/config.toml`(MCP 서버 등), 저장소의 `AGENTS.md`, 웹 검색을 쓰지 않고 실행합니다. 다만 Codex의 읽기 전용 sandbox는 디스크 읽기를 막지 않으므로, PR에 숨은 지시가 Codex에게 로컬 파일을 읽게 할 가능성은 남습니다. 민감한 환경에서는 `--no-codex`를 쓰세요.
- `~/.codex/config.toml`을 읽지 않으므로 거기 적은 모델·공급자 설정(Azure, 로컬 모델 등)도 쓰지 않습니다. 그런 설정이 있어야만 동작하는 환경에서는 Codex 리뷰가 오류로 생략됩니다.
- 등급 변환: critical·high → CRITICAL, medium → WARNING, low → SUGGESTION (confidence 0.5 미만은 한 단계 내림)
- Claude가 지적마다 코드를 직접 읽고 채택·수정 채택·기각합니다. Claude 지적과 겹치면 하나로 합칩니다.
- 리뷰는 **1건**으로 게시하고, 코멘트마다 출처(`Claude`·`Codex`·`Claude+Codex`)와 표식(`<!-- dwk:reviewer=... -->`)을 남깁니다. `/apply-review`는 이 표식이 있으면 본인 계정 코멘트여도 반영 대상에 넣습니다.

**생략** — 다음 경우 Codex만 생략하고 Claude 리뷰로 끝까지 진행합니다. 사유는 Summary의 "Codex 교차 리뷰" 섹션에 남습니다.

| 경우 | 처리 |
|---|---|
| `--no-codex` · 실행 환경이 Codex(Codex가 Codex를 부르면 교차 리뷰가 아님) · 미설치 · 미로그인(API 키 환경 변수도 없음) · 준비 실패 · 리뷰할 변경 없음 | 시작하지 않음 |
| 사용량 제한 | 재시도하지 않고 생략, 재시도 가능 시각이 있으면 기록 |
| 오류(종료 코드 ≠ 0, 결과 없음·JSON 깨짐) | 1회 재시도 후 생략 |
| 15분 초과 | 명령에 걸린 시간 제한으로 끝나고 생략 (재시도 없음) |

일부만 나온 결과는 리뷰로 취급하지 않습니다. 프롬프트·출력 스키마: `plugins/workflow/templates/codex-review/`

## Severity 레벨

| Emoji | Level | 설명 |
|-------|-------|------|
| 🚨 | `CRITICAL` | 머지 전 반드시 수정 (버그, 보안, 데이터 손실) |
| ⚠️ | `WARNING` | 수정 권장 (성능, 코드 스멜) |
| 💡 | `SUGGESTION` | 개선 제안 (가독성, 베스트 프랙티스) |
| ❓ | `QUESTION` | 작성자에게 확인 필요 |
| 🔹 | `NITPICK` | 사소한 스타일 이슈 |

## 판정 매트릭스

| 조건 | 판정 |
|------|------|
| PR 변경 파일·본문의 Secret alert | REQUEST_CHANGES (Draft·자기 PR이면 COMMENT) |
| CRITICAL >= 1 | REQUEST_CHANGES |
| WARNING >= 3 (normal) / >= 2 (strict) | REQUEST_CHANGES |
| WARNING 1~2 | COMMENT |
| SUGGESTION만 | COMMENT |
| 이슈 없음 / NITPICK만 | APPROVE |
| Draft PR | COMMENT (고정) |

## 코멘트 선택 게시

리뷰 결과가 CLI에 출력된 후, 게시 방식을 선택할 수 있습니다:

| 옵션 | 설명 |
|------|------|
| **전체 코멘트 게시** | 모든 리뷰 코멘트를 그대로 PR에 게시 |
| **코멘트 선택 후 게시** | 게시할 코멘트를 개별 선택 (체크박스) |
| **코멘트 없이 종료** | CLI 출력만으로 리뷰 종료 |

"코멘트 선택 후 게시"를 선택하면:
- 코멘트 4개 이하: 각 코멘트를 개별 체크박스로 선택
- 코멘트 5개 이상: severity 그룹 단위 선택 → 필요 시 그룹 내 개별 제외

## 외부 레포지토리 분석

PR이 현재 프로젝트와 다른 레포지토리인 경우, 캐시 유무에 따라 적절한 옵션만 노출됩니다:

**캐시가 없는 경우:**

| 옵션             | 설명                                                      |
| -------------- | ------------------------------------------------------- |
| **분석 없이 진행**   | PR diff만으로 리뷰                                           |
| **레포 분석 후 진행** | CLAUDE.md, README 등을 가져와 `.claude/repo-cache/`에 저장 후 리뷰 |

**캐시가 있는 경우:**

| 옵션              | 설명                                |
| --------------- | --------------------------------- |
| **분석 없이 진행**    | PR diff만으로 리뷰                     |
| **기존 캐시 참조**    | 이전에 저장된 분석 문서 활용 (30일 경과 시 갱신 안내) |
| **캐시 삭제 후 재분석** | 기존 캐시 초기화 후 새로 분석                 |

## 재리뷰 감지

동일 PR에 현재 사용자의 이전 리뷰가 있으면 자동으로 감지하여 옵션을 제시합니다:

- **증분 리뷰**: 이전 리뷰 이후 추가된 커밋만 리뷰
- **전체 리뷰**: PR 전체를 처음부터 다시 리뷰

## 지원 플랫폼

- **iOS**: `.swift`, `.m`, `.xib`, `.pbxproj` 등
- **Android**: `.kt`, `.java`, `build.gradle` 등
- **FrontEnd**: `.ts`, `.tsx`, `.vue`, `.css` 등
- **BackEnd**: `.go`, `.py`, `.rs`, `Dockerfile` 등

## 대규모 PR 처리

리뷰 비용과 시간을 줄이기 위해 커맨드가 실제로 적용하는 규칙입니다.

| 조건 | 동작 |
|------|------|
| 변경 파일 50개 초과 | "대규모 PR" 안내 후 주요 로직 파일 위주로 리뷰 |
| 변경 라인 1000줄 초과 | 리뷰 시간이 길어질 수 있다고 안내 |
| 변경 파일 200개 초과 | PR 분할을 강력 권장 (Summary에 SUGGESTION으로 기록) |
| 자동 생성 파일 (`*.generated.*`, `*.min.js`, `*.lock`, `*.sum`, `*.pbxproj` 등) | 우선순위 최하위, 축약 리뷰 |
| 바이너리 파일 (이미지, 폰트, 압축 파일 등) | 리뷰에서 제외 |
| 변경 파일 20개 초과 | 영향도 분석(Step 4.5) 생략, Summary에 기록 |
| 재리뷰 | 이전 리뷰 이후 커밋만 보는 **증분 리뷰** 선택 가능 ([재리뷰 감지](#재리뷰-감지)) |

> 이전 문서에 있던 "전용 서브에이전트로 모델 분기(Haiku/Sonnet/Opus)"와 "code-review-graph 자동 통합"은 커맨드에 구현된 적이 없는 내용이라 삭제했습니다 (#8).

