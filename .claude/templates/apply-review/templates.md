# Apply Review Templates

`/apply-review` 커맨드에서 사용하는 출력 템플릿 모음입니다.

---

## usage_guide

```
=== Apply Review Command ===

Usage: /apply-review <PR_NUMBER_OR_URL> [options]
Example: /apply-review 32
         /apply-review https://github.com/owner/repo/pull/32
         /apply-review 32 --reviewer=octocat

-- Options --
  --reviewer=username  특정 리뷰어의 코멘트만 반영
  --auto-commit        확인 없이 자동 커밋 (push는 여전히 확인)
  --branch=name        변경 사항을 새 브랜치에 적용
  --help               이 도움말을 표시합니다

-- Process --
1. PR 정보 수집 + 브랜치 검증
2. 이전 반영 기록 확인 (증분/전체/제외항목 재확인)
3. 리뷰 코멘트 수집 및 분류
4. AI 합당성 판단
5. 사용자 확인 (전체 진행/전체 취소/개별 선택)
6. 대규모 변경 감지 + 브랜치 분리 제안
7. 코멘트 반영 (병렬 agent 활용)
8. 반영 결과 검증
9. 커밋 / Push / PR 생성 옵션
10. 리뷰 코멘트별 답글 작성 옵션 (gh CLI 필요)
11. 반영 기록 저장

-- AI Verdict --
  ✅ AGREE   : 동의 — 코멘트대로 반영
  🔶 PARTIAL : 부분 동의 — AI 대안으로 반영
  ❌ DISAGREE: 반대 — 반영 비추천 (사용자가 강제 가능)
  ⏭️ SKIP    : 건너뜀 — 질문/정보성 코멘트

========================
```

---

## repo_mismatch

```
⛔ 레포지토리 불일치

현재 로컬 레포: {local_owner}/{local_repo}
PR 대상 레포:   {pr_owner}/{pr_repo}

현재 디렉토리가 PR 대상 레포지토리와 일치하지 않습니다.
해당 레포지토리로 이동한 후 다시 실행해주세요.
```

---

## pr_summary

```
=== PR 요약 ===

📋 #{pr_number} {title}
👤 {author} → {base_branch}
📊 {state} | {mergeable} | 🔀 {head.ref}
📁 {changed_files}개 파일 변경 (+{additions}/-{deletions})

현재 브랜치: {current_branch} {✅ 일치 / ⚠️ 불일치}

===============
```

---

## previous_apply_history

```
=== 이전 반영 기록 감지 ===

📋 PR #{pr_number}에 대한 이전 반영 기록이 있습니다.
📅 마지막 반영: {last_applied_at}
🔢 반영된 코멘트: {applied_count}개
📝 커밋: {commit_hash}

===========================
```

---

## comment_collection_summary

```
=== 리뷰 코멘트 수집 결과 ===

📋 PR #{pr_number}: {title}
👀 리뷰어: @{reviewer1} ({state}), @{reviewer2} ({state})

총 {N}개 코멘트:
  🔧 CODE_CHANGE: {n}개
  ♻️ REFACTOR: {n}개
  ❓ QUESTION: {n}개
  🎨 STYLE: {n}개
  🏗️ ARCHITECTURE: {n}개
  ℹ️ INFO: {n}개

===========================
```

---

## ai_verdict

```
=== AI 합당성 판단 ===

#1 ✅ AGREE | 🔧 CODE_CHANGE | 📁 {file}:{line}
   리뷰어: @{reviewer}
   코멘트: "{코멘트 요약 1줄}"
   AI 판단: {판단 근거}
   예상 변경: {file} ({N}줄 수정)

#2 🔶 PARTIAL | ♻️ REFACTOR | 📁 {file}:{line}
   리뷰어: @{reviewer}
   코멘트: "{코멘트 요약 1줄}"
   AI 판단: {판단 근거 + 대안 설명}
   예상 변경: {file} ({N}줄 수정)

#3 ❌ DISAGREE | 🎨 STYLE | 📁 {file}:{line}
   리뷰어: @{reviewer}
   코멘트: "{코멘트 요약 1줄}"
   AI 판단: {반대 근거}

#4 ⏭️ SKIP | ❓ QUESTION | 📁 {file}:{line}
   리뷰어: @{reviewer}
   코멘트: "{질문 내용}"
   AI 판단: 질문 코멘트. 답변만 필요.

===========================
```

---

## apply_progress

```
=== 코멘트 반영 중 ===

[1/{total}] ✅ {file}:{line} — {코멘트 요약} 완료
[2/{total}] 🔄 {file}:{line} — {코멘트 요약} 처리 중...
[3/{total}] ⏳ 대기 중
```

---

## verification_result

```
=== 반영 결과 ===

✅ 반영 완료: {N}/{total}개 코멘트
❌ 반영 실패: {M}개

변경 파일:
  📝 {file1} (+{additions}, -{deletions})
  📝 {file2} (+{additions}, -{deletions})

{실패 항목이 있으면}
실패 항목:
  #{n} {file}:{line} — {실패 사유}

====================
```

---

## commit_message

```
🔧 Fix: PR #{number} 리뷰 피드백 반영

- {반영된 코멘트 1줄 요약}
- {반영된 코멘트 1줄 요약}

Reviewed-by: @{reviewer}
Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

## pr_body

```markdown
## 📌 개요

PR #{original_pr_number} 리뷰 피드백 반영

## 📋 변경사항

{반영된 코멘트별 변경 내용}

## 🙏 참고사항

- Original PR: #{original_pr_number}
- Reviewed by: @{reviewer}
```

---

## reply_applied

```markdown
✅ 반영했습니다.

{반영 내용 1~2줄 요약}
{PARTIAL인 경우: 반영하지 않은 부분과 이유 1줄}

커밋: {commit_url_or_hash}
{미검증 항목이 있으면: 빌드 확인, 실기기 미확인 등}
```

---

## reply_not_applied

```markdown
⏭️ 이번에는 반영하지 않았습니다.

사유: {이유 1~2줄}
```

---

## reply_answer

```markdown
💬 {질문에 대한 답변}
```

---

## feedback_comment

답글 스레드가 없는 코멘트(리뷰 본문, 일반 PR 코멘트)에 대한 답에만 사용합니다.

```markdown
> {원 코멘트 인용 1줄} ({원 코멘트 링크})

{reply_applied / reply_not_applied / reply_answer 본문}

*Applied with [Claude Code](https://claude.com/claude-code) `/apply-review` command*
```

---

## history_record

```json
{
  "pr_number": 32,
  "last_applied_at": "2026-03-25T14:30:00Z",
  "commit_hash": "abc1234",
  "applied_comments": [
    {
      "comment_id": 123456,
      "file": "src/app.ts",
      "line": 42,
      "category": "CODE_CHANGE",
      "verdict": "AGREE",
      "summary": "null check 추가"
    }
  ],
  "skipped_comments": [
    {
      "comment_id": 789012,
      "file": "src/utils.ts",
      "line": 15,
      "category": "STYLE",
      "verdict": "DISAGREE",
      "summary": "네이밍 변경 제안"
    }
  ],
  "history": [
    {
      "applied_at": "2026-03-24T10:00:00Z",
      "commit_hash": "def5678",
      "applied_count": 3,
      "skipped_count": 1
    }
  ]
}
```
