# FrontEnd Review Priorities

| Priority | Category | Description |
|----------|----------|-------------|
| 1 | **Security** | XSS prevention, `dangerouslySetInnerHTML`, input sanitization, CSRF tokens |
| 2 | **Performance** | Bundle size impact, unnecessary re-renders, `useMemo`/`useCallback` usage, code splitting |
| 3 | **State Management** | State location (local vs global), state updates, race conditions |
| 4 | **Accessibility** | ARIA attributes, semantic HTML, keyboard navigation, screen reader support |
| 5 | **Error Handling** | Error boundaries, API error states, loading states, empty states |
| 6 | **TypeScript** | Type safety, `any` usage, proper generics, discriminated unions |
| 7 | **Component Design** | Single responsibility, prop drilling, composition patterns, reusability |
| 8 | **Styling** | CSS specificity, responsive design, design system compliance, CSS-in-JS patterns |
| 9 | **Testing** | Component tests, integration tests, mocking, test coverage |
| 10 | **SEO/Core Web Vitals** | Meta tags, LCP/FID/CLS optimization, SSR/SSG considerations |

## FrontEnd-Specific Checks

- React hooks rules and dependency arrays
- Next.js `use client` / `use server` directives
- Vue reactivity pitfalls (`ref` vs `reactive`)
- Proper `key` prop usage in lists
- Image optimization (`next/image`, lazy loading)
- Environment variable exposure (`NEXT_PUBLIC_` prefix)

## FrontEnd Security Checklist

- CSP (Content Security Policy) 헤더/메타 설정 확인
- 환경변수 노출 확인 (`NEXT_PUBLIC_`, `VITE_` 등 클라이언트 노출 변수에 시크릿 포함 여부)
- `innerHTML`/`dangerouslySetInnerHTML` 사용 시 sanitization 확인 (DOMPurify 등)
- Third-party 스크립트 무결성 (SRI - Subresource Integrity)
- 쿠키 설정 (`httpOnly`, `secure`, `sameSite`)
- `eval()`, `new Function()` 사용 금지 확인
- localStorage/sessionStorage에 토큰/시크릿 저장 여부
- CORS preflight 요청 처리 확인
