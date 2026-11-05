---
title: Web
tags: [security/stack, stack/web]
status: draft
created: 2026-11-05
profile: web
---

# Web (JS/TS — Node, React, Next.js)

상위: [[스택 프로파일 개요]] · 결정: [[ADR-008 스택별 프로파일]] · 동적 점검: [[scan-web]]

## 주요 위협
1. 클라이언트 번들로 새는 시크릿 (`NEXT_PUBLIC_`, `VITE_`, `REACT_APP_` 접두사 변수)
2. XSS (`dangerouslySetInnerHTML`, `innerHTML`, `eval`)
3. 보안 헤더·쿠키 설정 누락 (CSP, HSTS, `SameSite`)
4. 서버 액션·API 라우트의 인증 누락, SSRF
5. 취약 npm 의존성, 공급망(설치 스크립트)

## 감지 (`profiles/web.yaml`)
```yaml
detect:
  - "**/next.config.*"
  - "**/vite.config.*"
  - { file: "**/package.json", has_dependency: [next, react, react-dom, vue, svelte, "@angular/core", vite] }
exclude_if: [react-native]                      # RN 앱의 react 의존성은 web으로 보지 않음
exclude_paths: ["**/node_modules/**", "**/.next/**", "**/dist/**", "**/build/**", "**/coverage/**"]
```

## 점검 항목 — 정적 (`/security:scan-code`)

| # | 점검 | 방법 | 대상 | 심각도 |
|---|---|---|---|---|
| W1 | 하드코딩 시크릿, `.env*` 커밋 | Gitleaks | 소스, `.env*` | high |
| W2 | 공개 접두사 변수에 비밀 값 (`NEXT_PUBLIC_*SECRET*`, `*_KEY` 등) | Semgrep 커스텀 `web/public-env-secret` + `.env*` 키 이름 검사 | `.env*`, 소스 | high |
| W3 | XSS 싱크 (`dangerouslySetInnerHTML`, `innerHTML`, `document.write`, `eval`) | Semgrep 공식 `javascript`/`typescript`/`react` | 소스 | high |
| W4 | API 라우트·서버 액션의 인증 확인 누락 (휴리스틱) | Semgrep 커스텀 `web/next-unauth-route` | `app/api/**`, `pages/api/**`, `"use server"` | medium |
| W5 | SSRF (사용자 입력 URL로 `fetch`) | Semgrep 공식 + 커스텀 | 서버 코드 | high |
| W6 | `next.config.*`의 보안 헤더 미설정, `images.remotePatterns` 와일드카드 | 커스텀 검사 | `next.config.*` | medium |
| W7 | 취약 의존성 | OSV-Scanner | `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml` | CVSS 기준 |
| W8 | `postinstall` 등 설치 스크립트가 있는 의존성 목록 | 스크립트 검사 (lockfile 메타데이터) | lockfile | info |

## 점검 항목 — 동적 (`/security:scan-web`, [[OWASP ZAP]] baseline)
- 보안 헤더(CSP, HSTS, X-Frame-Options, X-Content-Type-Options), 쿠키 속성, 정보 노출(서버 버전, 스택트레이스, 소스맵 공개)
- Next.js 특화: `/_next/static/**/*.map` 공개 여부를 확인 항목에 추가 (프로덕션 소스맵 노출)
- 대상은 로컬 `next start`(프로덕션 모드) 권장 — `next dev`는 헤더·에러 페이지가 달라 오탐

## 수동 체크리스트
- [ ] 인증 라이브러리(NextAuth 등) 세션 쿠키 설정
- [ ] 배포 플랫폼(Vercel, Cloudflare 등)의 환경 변수 범위(Preview/Production) 분리
- [ ] CORS 허용 출처

## 픽스처
`tests/fixtures/web/`: `NEXT_PUBLIC_API_SECRET`, `dangerouslySetInnerHTML`, 인증 없는 `app/api/*/route.ts`, 헤더 없는 `next.config.js`, 알려진 취약 버전 고정 `package-lock.json`

> [!warning] 검증 필요
> - W4 휴리스틱의 오탐률 (미들웨어에서 인증하는 구조 구분)
> - W8을 오프라인 lockfile만으로 판별 가능한지 (`hasInstallScript` 필드 등)
