# Review Output Templates

`/pr-review` 커맨드에서 사용하는 출력 템플릿 모음입니다.

---

## usage_guide

```
=== PR Review Command ===

Usage: /pr-review <PR_URL> [options]
Example: /pr-review https://github.com/owner/repo/pull/123
         /pr-review https://github.com/owner/repo/pull/123 --mode=strict
         /pr-review https://github.com/owner/repo/pull/123 --focus=security --skip=nitpick

-- Options --
  --mode=strict    모든 severity 코멘트 생성, WARNING 2개 이상이면 REQUEST_CHANGES
  --mode=normal    표준 판정 매트릭스 적용 (기본값)
  --mode=relaxed   CRITICAL만 코멘트, 나머지는 Summary에만 기록
  --focus=항목,...  지정 카테고리만 집중 리뷰 (예: security,performance,memory)
  --skip=항목,...   지정 severity/카테고리 건너뛰기 (예: nitpick,style)
  --no-codex       Codex 교차 리뷰를 끄고 Claude 리뷰만 합니다
  --help           도움말을 표시합니다

-- Review Process --
1. PR URL 파싱 + 상태 확인 (draft/merged/CI)
2. `gh` CLI로 PR 정보를 수집합니다.
3. 보안 스캔 (Secret/Code/Dependabot alerts)
4. 변경 파일 확장자로 PR 타입을 감지합니다.
   - iOS (.swift, .m, .xib, .pbxproj ...)
   - Android (.kt, .java, build.gradle ...)
   - FrontEnd (.ts, .tsx, .vue, .css ...)
   - BackEnd (.go, .py, .rs, Dockerfile ...)
5. Codex 교차 리뷰를 백그라운드로 시작합니다. (PR 코드·diff가 OpenAI로 전송됩니다)
6. 타입별 우선순위에 따라 코드를 리뷰합니다.
7. Codex 결과를 검증해 합칩니다. (사용량 제한·미설치 등이면 생략)
8. GitHub PR에 라인별 인라인 코멘트를 생성합니다.
9. 리뷰 결과를 기록합니다.

-- Severity Levels --
  🚨 CRITICAL  : 머지 전 반드시 수정 (버그, 보안, 데이터 손실)
  ⚠️ WARNING   : 수정 권장 (성능, 코드 스멜)
  💡 SUGGESTION: 개선 제안 (가독성, 베스트 프랙티스)
  ❓ QUESTION  : 작성자에게 확인 필요
  🔹 NITPICK   : 사소한 스타일 이슈

========================
```

---

## pr_summary

```
=== PR 요약 ===

📋 #{pr_number} {title}
👤 {author} → {base_branch}
📊 {state} | {draft ? "Draft" : ""} {mergeable ? "✅ Mergeable" : "⚠️ Conflict"} | CI: {ci_status}
📁 {changed_files}개 파일 변경 (+{additions}/-{deletions})
🔀 {commits}개 커밋

📝 설명:
{body를 3줄 이내로 요약. body가 없으면 "설명 없음"}

🔗 관련 이슈: {linked_issues 또는 "없음"}
👀 기존 리뷰: {existing_reviews 요약 또는 "없음"}

===============
```

---

## review_result

```
=== 리뷰 결과 ===

📁 {file_path}:{line}
  [{emoji} {severity}] {category} · {Claude | Codex | Claude+Codex}
  {description}
  {suggestion code if applicable}

📁 {file_path}:{line}
  [{emoji} {severity}] {category} · {Claude | Codex | Claude+Codex}
  {description}

...

--- 판정 ---
{verdict}: {판정 근거}
🚨 {critical} / ⚠️ {warning} / 💡 {suggestion} / ❓ {question} / 🔹 {nitpick}
🤖 Codex: 지적 {N} → 채택 {a} (Claude와 겹침 {m}) · 기각 {r} · 기존 중복 {d} · 옵션 제외 {f} | 생략({사유})
```

---

## comment_format

```
**[{emoji} {severity}]** {category}

{description}

{suggestion if applicable - see below}

<sub>리뷰: {Claude | Codex | Claude+Codex}</sub>
<!-- dwk:reviewer={claude | codex | claude+codex} -->
```

---

## suggestion_block

````
```suggestion
수정된 코드
```
````

---

## comment_example

```
**[🚨 CRITICAL]** Crash Prevention

`force unwrap`이 사용되어 nil일 경우 크래시가 발생합니다. 옵셔널 바인딩을 사용하세요.

```suggestion
guard let value = optionalValue else { return }
```
```

---

## review_summary

```
## Review Summary

**PR Type**: {detected types}
**Files Reviewed**: {count}
**Binary Files Skipped**: {count} (if any)
**Comments**: 🚨 {critical} critical, ⚠️ {warning} warnings, 💡 {suggestion} suggestions, ❓ {question} questions, 🔹 {nitpick} nitpicks
**Verdict**: {APPROVE / COMMENT / REQUEST_CHANGES} - {판정 근거 한줄}

### Verdict Matrix
| 조건 | 판정 |
|------|------|
| 🔒 Secret alert 발견 | REQUEST_CHANGES (무조건) |
| 🚨 CRITICAL >= 1 | REQUEST_CHANGES |
| ⚠️ WARNING >= 3 (normal) / >= 2 (strict) | REQUEST_CHANGES |
| ⚠️ WARNING 1~2 | COMMENT |
| 💡 SUGGESTION만 존재 | COMMENT |
| 이슈 없음 / 🔹 NITPICK만 | APPROVE |
| Draft PR | COMMENT (고정) |

> 이 PR의 판정: **{verdict}** — {판정에 해당하는 조건 설명}

### Security Scan (if alerts found)
- Secret Scanning: {count} alerts
- Code Scanning: {count} alerts ({critical} critical, {high} high)
- Dependabot: {count} alerts (CVSS {max_score})

### Key Findings
- {bullet points of most important findings}

### Linked Issues Coverage (if issues linked)
- #{issue_number}: {title} - {covered/partially covered/not addressed}

### Commit Quality
- Total commits: {count}
- {observations: squash recommendation, WIP commits, formatting-only commits}

### Codex 교차 리뷰
- 결과: 실행됨 (범위: {range} | diff만 — 저장소 원본 없음) | 생략({--no-codex | 실행 환경이 Codex | 미설치 | 미로그인 | 변경 없음 | 사용량 제한, {재시도 가능 시각} | 시간 초과 | 오류: {요약}})
- 범위 변경: {증분 시작점이 조상이 아니거나 compare 실패로 전체 범위를 봄 — 있으면}
- 지적 {N} → 채택 {a} (Claude와 겹침 {m}) · 기각 {r} · 기존 중복 {d} · 옵션 제외 {f}
- 기각: {file:line} — {이유} (있으면)
- 인라인 불가: {file:line} [{emoji} {severity}] — {요약} <!-- dwk:reviewer={codex | claude+codex} item={게시하는 항목에 1부터 매기는 번호} --> (있으면, 게시하기로 한 항목만, 항목마다 표식. relaxed 모드에서 Summary에만 적는 지적은 표식 없음)

### Already Flagged (if duplicates skipped)
- {file:line} - Already flagged by {reviewer}

### Impact Analysis (code-review-graph 사용 시에만 포함)
- Analysis Method: code-review-graph (AST-based)
- Changed Nodes: {count} ({functions} functions, {classes} classes)
- Impacted Nodes: {count} (within {max_depth} hops)
- Impacted Files: {count} (PR 외부)
- Test Coverage: {tested_count}/{total_changed_count} changed functions have tests
- Blast Radius: {low/medium/high} — {판단 근거}
```
