# scan-web — docs/security/03 워크플로/scan-web.md
ZAP baseline(passive)이 확인하지 못하는 항목이다. `/security:scan-web` 리포트에만 붙는다.
- [ ] 소스맵 공개 여부 — 운영 빌드의 `*.js.map`(Next.js 는 `/_next/static/**.js.map`)이 내려받아지지 않는지 (`productionBrowserSourceMaps` 꺼짐)
- [ ] API 에러 응답에 스택트레이스·쿼리·내부 경로가 나오지 않는지 — 잘못된 입력으로 오류를 내 보는 확인은 사람이 한다 (툴킷은 공격성 요청을 보내지 않음)
- [ ] 로그인한 뒤에만 보이는 페이지의 보안 헤더·쿠키 속성 (baseline 은 인증 없이 크롤링한다)
- [ ] 운영 환경의 헤더 설정(CDN·리버스 프록시)이 점검한 개발·스테이징과 같은지
