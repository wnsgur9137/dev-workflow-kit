---
title: /pr-review
tags: [workflow, command]
---

# /pr-review

상위: [Home](../Home.md) · [README](../../README.md)

PR의 변경 사항을 분석하고, GitHub에 인라인 리뷰 코멘트를 자동으로 게시합니다.

## 사용법

```
/pr-review <PR_URL> [options]
```

## 예시

```
/pr-review https://github.com/owner/repo/pull/123
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
| `--help` | `/pr-review` 도움말 표시 |

## 리뷰 프로세스

1. PR URL 파싱 + 상태 확인 (draft/merged/CI)
2. GitHub MCP를 통해 PR 정보 수집 (기존 리뷰 중복 방지, 재리뷰 감지)
3. 보안 스캔 (Secret/Code/Dependabot alerts)
4. 레포지토리 컨텍스트 분석 (로컬 일치 시 자동, 외부 레포 시 사용자 선택)
5. 변경 파일 확장자로 PR 타입 감지 (iOS/Android/FrontEnd/BackEnd)
6. 타입별 우선순위에 따라 코드 리뷰
7. CLI에 리뷰 결과 출력 → 사용자가 게시할 코멘트를 선택
8. GitHub PR에 선택된 인라인 코멘트 게시
9. 리뷰 결과 기록

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
| Secret alert 발견 | REQUEST_CHANGES (무조건) |
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

