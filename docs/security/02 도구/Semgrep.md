---
title: Semgrep
tags: [tool/sast]
status: draft
created: 2026-11-05
license: LGPL-2.1 (엔진), 규칙은 Semgrep Rules License
network: none
---

# Semgrep (Community Edition)

상위: [[보안 툴킷]] · 워크플로: [[scan-code]]

## 역할
소스 코드 정적분석(SAST). 웹·앱 공통 언어(JS/TS, Dart, Kotlin, Swift, Python 등) 취약 패턴 탐지.

## 실행 방식
- 이미지: `semgrep/semgrep` (digest 고정 → `$PLUGIN/docker/images.lock`)
- 네트워크: `--network none`
- 입력: 대상 저장소 `:ro`, 규칙 `$DATA/data/semgrep-rules/:ro`
- 출력: `$DATA/reports/<run-id>/raw/semgrep.json`

```bash
docker run --rm --network none \
  -e SEMGREP_ENABLE_VERSION_CHECK=0 \
  -v "$TARGET":/src:ro -v "$RULES":/rules:ro -v "$OUT":/out \
  semgrep/semgrep@sha256:<digest> \
  semgrep scan --config /rules --metrics=off --json -o /out/semgrep.json /src
```

## 외부 통신
| 항목 | 기본 동작 | 이 설계 |
|---|---|---|
| 레지스트리 규칙(`p/...`) | semgrep.dev에서 다운로드 | ❌ 사용 안 함. 로컬 규칙만 |
| 사용 통계(metrics) | 레지스트리 사용 시 전송 | `--metrics=off` + 네트워크 차단 |
| 버전 확인 | semgrep.dev 조회 | 환경변수 + 네트워크 차단 |

규칙 갱신은 [[업데이트 절차]]에서만 수행.

## 규칙 소스
- `semgrep/semgrep-rules` 저장소에서 필요한 언어 디렉터리만 `$DATA/data/semgrep-rules/`에 받고, 고정 커밋 해시는 `$PLUGIN/rules.lock`에서 관리
- 커스텀 규칙: `$CONF/semgrep-custom/` (예: 프로젝트 고유 위험 API)

## Severity 매핑
| Semgrep | 정규화 |
|---|---|
| ERROR | high |
| WARNING | medium |
| INFO | low |

> [!warning] 검증 필요
> - `SEMGREP_ENABLE_VERSION_CHECK` 환경변수명과 `--metrics=off` 동작을 현재 버전 문서로 확인
> - `semgrep-rules` 라이선스(Semgrep Rules License)가 개인 내부 사용에 문제 없는지 확인
> - 로컬 규칙 디렉터리 지정 시 `.yaml` 외 파일(테스트 픽스처) 제외 방법
