---
title: OSV-Scanner
tags: [tool/sca]
status: draft
created: 2026-11-05
license: Apache-2.0
network: none (스캔) / 외부 (DB 갱신 시만)
---

# OSV-Scanner

상위: [[보안 툴킷]] · 워크플로: [[scan-code]]

## 역할
lockfile·매니페스트 기반 의존성 취약점(SCA) 탐지. npm/yarn/pnpm, pub(Flutter), Gradle/Maven, CocoaPods, SwiftPM, pip 등.

## 외부 통신과 대응
| 항목 | 기본 동작 | 이 설계 |
|---|---|---|
| 취약점 조회 | 패키지명·버전을 `api.osv.dev`로 전송 | ❌ 오프라인 DB만 사용 |
| 전이 의존성 해석 | 일부 생태계(Maven 등)는 `deps.dev` 조회 | ❌ 오프라인 모드에서 비활성 |
| DB 다운로드 | — | [[업데이트 절차]]에서만 |

소스 코드는 어떤 모드에서도 전송하지 않는다. 다만 **의존성 목록도 프로젝트 정보**이므로 오프라인을 기본으로 한다.

## 실행 방식
```bash
# 스캔 (네트워크 차단)
docker run --rm --network none \
  -e OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY=/db \
  -v "$TARGET":/src:ro -v "$DB":/db:ro -v "$OUT":/out \
  ghcr.io/google/osv-scanner@sha256:<digest> \
  scan source -r --offline-vulnerabilities --format json --output /out/osv.json /src
```

## Severity 매핑
CVSS 점수 기준: ≥9.0 critical, ≥7.0 high, ≥4.0 medium, 그 외 low. 점수 없음 → medium.

## 한계
- lockfile 없는 프로젝트는 정확도 낮음 → 스킬에서 "lockfile 커밋 권장" 안내
- 오프라인 DB가 오래되면 최신 CVE 누락 → `meta.json`에 DB 갱신일 기록, 7일 초과 시 summary 경고

> [!warning] 검증 필요
> - v2 기준 서브커맨드, `--offline-vulnerabilities`/`--download-offline-databases` 플래그, 캐시 디렉터리 환경변수명
> - 공식 컨테이너 이미지 경로
