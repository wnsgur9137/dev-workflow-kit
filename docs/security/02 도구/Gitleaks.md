---
title: Gitleaks
tags: [tool/secret]
status: draft
created: 2026-11-05
license: MIT
network: none
---

# Gitleaks

상위: [[보안 툴킷]] · 워크플로: [[scan-code]] · 관련: [[시크릿 처리]]

## 역할
작업 트리와 **git 히스토리** 전체의 하드코딩된 시크릿(API 키, 토큰, 비밀번호, 개인키) 탐지.

## 실행 방식
- 이미지: `ghcr.io/gitleaks/gitleaks` (digest 고정)
- 네트워크: `--network none` (원래 외부 통신 없음, 이중 보장)
- 두 번 실행:
  1. `git` 모드 — 커밋 히스토리 (지워진 키도 히스토리에 남아 있음)
  2. `dir` 모드 — 커밋되지 않은 파일 포함 작업 트리

```bash
docker run --rm --network none \
  -v "$TARGET":/repo:ro -v "$OUT":/out \
  ghcr.io/gitleaks/gitleaks@sha256:<digest> \
  git /repo --redact --report-format json --report-path /out/gitleaks-git.json
```

## 필수 옵션
- **`--redact`**: 리포트에 시크릿 원문을 남기지 않음. 생략 금지 (스크립트에서 강제)

## Severity 매핑
모든 탐지는 기본 `high`. 개인키·클라우드 루트키 패턴은 `critical`.

## 탐지 후 대응 원칙
키가 히스토리에 있으면 **삭제가 아니라 폐기(rotate)** 가 우선. Claude의 수정 제안에도 이 순서를 지시. → [[scan-code]]

> [!warning] 검증 필요
> - 현재 버전의 서브커맨드(`git`/`dir`) 및 플래그 이름
> - `:ro` 마운트 저장소에서 git 명령이 `safe.directory` 오류를 내는지
