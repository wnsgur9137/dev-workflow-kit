# web 픽스처 (S-Web 기준선)

`tests/baseline/web.json` 의 기대 결과를 만드는 일부러 취약한 Next.js 앱입니다. 실제 서비스 코드가 아닙니다.

| 점검 | 파일 | 기대 |
|---|---|---|
| W2 공개 변수 시크릿 | `app/page.tsx`, `env.fixture`(테스트에서 `.env` 로 복사) | `public-env-secret`, `env-public-secret` |
| W3 XSS 싱크 | `app/page.tsx` | `react-dangerouslysetinnerhtml` |
| W4 인증 없는 라우트 | `app/api/proxy/route.ts`, `pages/api/legacy.js` (음성: `app/api/me/route.ts`) | `next-unauth-route` |
| W5 SSRF | `app/api/proxy/route.ts`, `pages/api/legacy.js` | `next-ssrf-fetch` |
| W6 next.config | `next.config.js` | `next-config-no-security-headers`, `next-config-wildcard-remote-image`, `next-config-browser-sourcemaps` |
| W7 취약 의존성 | `package-lock.json.fixture`(테스트에서 `package-lock.json` 으로 복사) | `next@13.4.0` |
| W8 설치 스크립트 | `package-lock.json.fixture` | `npm-install-script` (`esbuild`) |

lockfile·`.env` 는 저장소의 의존성 알림·시크릿 스캐너가 이 픽스처를 실제 파일로 오인하지 않도록 이름을 바꿔 둡니다.
