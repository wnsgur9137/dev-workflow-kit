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

## 구현 메모 (S-Web)

| # | 구현 | 규칙·검사 ID | 심각도 |
|---|---|---|---|
| W1 | Gitleaks (공통) | — | high |
| W2 | Semgrep 커스텀(소스의 `process.env.X`·`import.meta.env.X`) + 스택 검사(`.env*` 키 이름) | `custom.web.public-env-secret`, `web.env-public-secret` | high |
| W3 | Semgrep 공식 `javascript`·`typescript` | `react-dangerouslysetinnerhtml` 등 | 규칙 기준 |
| W4 | **스택 검사**(설계는 Semgrep) — route 파일에 인증 호출(`auth()`·`getServerSession()` 등)이 없으면. `middleware`가 `/api`를 덮으면 low | `web.next-unauth-route` | medium / low |
| W5 | Semgrep 커스텀 taint (요청 쿼리·본문·`searchParams` → `fetch`·`axios`·`got`·`http(s).get`) | `custom.web.next-ssrf-fetch` | high |
| W6 | 스택 검사 — `headers()` 없음 / 일부 헤더 없음 / `remotePatterns`·`domains` 와일드카드 / `productionBrowserSourceMaps: true` | `web.next-config-*` | medium (일부 헤더 없음은 low) |
| W7 | OSV-Scanner (공통) | — | CVSS |
| W8 | 스택 검사 — `package-lock.json` v2+의 `hasInstallScript`, `pnpm-lock.yaml`의 `requiresBuild` | `web.npm-install-script` | info |

- **W2 이름 규칙**: 공개 접두사(`NEXT_PUBLIC_`·`VITE_`·`REACT_APP_`·`NUXT_PUBLIC_`·`GATSBY_`·`PUBLIC_`·`EXPO_PUBLIC_`) + `SECRET`·`PRIVATE`·`PASSWORD`·`TOKEN`·`SERVICE_ROLE`·`CREDENTIAL`. 공개용으로 설계된 키(`PUBLISHABLE`·`ANON`·`PUBLIC_KEY`·`SITE_KEY`)는 제외. `.env` 값은 읽어도 결과에 넣지 않는다. Semgrep 규칙 ID에 `secret`이 들어가 시크릿으로 분류되고 근거는 고정 문구로 대체된다.
- **W3 탐지 공백**: 공식 규칙은 taint 출처를 함수 매개변수 패턴으로 잡아, TS 타입을 붙인 props(`({ html }: Props)`)에서는 `dangerouslySetInnerHTML`을 탐지하지 못한다 (semgrep-rules `16b9e6d`에서 확인). 커스텀 보강은 후속 과제.
- **W4 휴리스틱**: 미들웨어·래퍼에서 인증하는 구조는 오탐이 된다. 서버 액션(`"use server"`)은 아직 다루지 않는다.
- **W8**: `yarn.lock`에는 설치 스크립트 표시가 없어 다루지 않는다.

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
> - W4 휴리스틱의 오탐률 (미들웨어에서 인증하는 구조 구분) — 실제 프로젝트 표본으로는 아직 측정하지 않음
> - ~~W8을 오프라인 lockfile만으로 판별 가능한지~~ → `package-lock.json` v2+ `hasInstallScript`, `pnpm-lock.yaml` `requiresBuild`로 가능 (yarn 제외)
