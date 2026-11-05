---
title: Nuclei
tags: [tool/dast, optional]
status: draft
created: 2026-11-05
license: MIT
network: web-internal + egress-proxy (허용목록)
---

# Nuclei (선택)

상위: [[보안 툴킷]] · 워크플로: [[scan-web]]

> [!note] 선택 도구
> [[OWASP ZAP]] baseline으로 충분하면 도입하지 않는다. P3 이후 필요 시 추가. → [[구현 계획]]

## 역할
템플릿 기반으로 **알려진 설정 오류·노출**(관리자 페이지, `.git`/`.env` 노출, 디폴트 페이지, 오래된 소프트웨어 버전) 확인.

## 안전 제약
- 제외 태그 강제: `-etags intrusive,dos,fuzz,bruteforce` (스크립트에서 고정, 사용자 인자로 덮어쓰기 불가)
- 템플릿은 [[업데이트 절차]]로 받은 **고정 스냅샷**만 사용 (`-ud /templates`)
- 시작 시 자동 업데이트/버전 확인 비활성: `-duc`
- 클라우드 업로드·대시보드 옵션 사용 금지
- 요청 속도 제한: `-rl` 낮게 (예: 10 req/s)

## 외부 통신
| 항목 | 이 설계 |
|---|---|
| 템플릿 자동 업데이트(GitHub) | `-duc` + 프록시 차단 |
| 클라우드 업로드 | 옵션 미사용 + 프록시 차단 |
| 대상 접속 | 프록시 경유 허용목록만 |

## Severity 매핑
템플릿 severity 그대로 (`critical/high/medium/low/info`)

> [!warning] 검증 필요
> - 제외 태그 목록이 공격성 템플릿을 충분히 거르는지 (템플릿 저장소 태그 분포 확인)
> - 템플릿 서명 검증 방식과 커스텀 템플릿 사용 시 위험
