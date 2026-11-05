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
   - **code-review-graph 감지 시**: AST 기반 구조 분석 자동 활용
5. 변경 파일 확장자로 PR 타입 감지 (iOS/Android/FrontEnd/BackEnd)
6. 타입별 우선순위에 따라 코드 리뷰
   - **code-review-graph 감지 시**: 구조적 리뷰 컨텍스트 + blast radius 분석
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

## code-review-graph 통합

[code-review-graph](https://github.com/tirth8205/code-review-graph)가 설치되고 그래프가 빌드된 프로젝트에서는 자동으로 AST 기반 정밀 분석을 활용합니다. 설치되지 않은 경우 기존 Grep/Glob 방식으로 폴백합니다.

| 기능 | graph 없음 (기존) | graph 있음 (강화) |
|------|-------------------|-------------------|
| **영향 분석** | Grep 문자열 검색 | AST call graph BFS 탐색 |
| **호출자 추적** | 함수명 텍스트 매칭 | `callers_of` 정확한 호출 관계 |
| **테스트 커버리지** | 확인 불가 | `tests_for`로 테스트 유무 검증 |
| **Blast Radius** | 수동 추정 | 자동 계산 (depth, node count) |
| **대규모 함수 탐지** | 없음 | `find_large_functions` 자동 감지 |

**설치 방법:**
```bash
pip install code-review-graph
code-review-graph install
# 프로젝트에서 그래프 빌드
code-review-graph build
```

설치 후 별도 설정 없이 `/pr-review` 실행 시 자동 감지됩니다.

## 토큰 최적화

`/pr-review` 커맨드는 토큰 효율성을 위해 `~/.claude/agents/`에 정의된 전용 서브에이전트를 활용하여 모델을 강제 분기합니다.

**전용 서브에이전트:**

| 에이전트 | 모델 (frontmatter 고정) | 상대 비용 | 용도 |
|---------|----------------------|----------|------|
| `review-diff-reader` | **Haiku** | 1x | diff 파싱, 파일별 변경 요약, 함수명 추출 |
| `review-analyzer` | **Sonnet** | 4x | 리뷰 기준 적용, 인라인 코멘트 생성 |
| `review-security` | **Opus** | 19x | 보안 취약점 심층 분석 (필요 시에만) |

에이전트 정의 파일의 `model` frontmatter로 모델이 고정되므로, 지시문 수준이 아닌 **시스템 레벨에서 강제 적용**됩니다.

**실행 흐름 (변경 라인 500줄 이상 PR):**
```
1. review-diff-reader (Haiku)  → diff 요약 생성
2. review-analyzer (Sonnet)    → 요약 기반으로 인라인 코멘트 생성
3. review-security (Opus)      → 보안 관련 변경이 있을 때만 병렬 실행
```

**최적화 원칙:**
- **메인 세션은 Sonnet**으로 실행, 서브에이전트 레벨에서만 모델 분기
- **파일 읽기는 Haiku 서브에이전트**에 위임 → 요약만 메인 세션에 반환 (컨텍스트 격리)
- **보안 관련 변경이 있을 때만** Opus 에이전트 생성 (불필요 시 생략)
- **독립 태스크는 병렬 실행** (보안 스캔 3종 동시 호출, 분석 에이전트 background 실행)
- **code-review-graph 선활용** — 파일을 직접 읽기 전에 구조 요약(~200토큰)으로 대체
