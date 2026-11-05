# BackEnd Review Priorities

| Priority | Category | Description |
|----------|----------|-------------|
| 1 | **Security** | SQL injection, authentication/authorization, input validation, secrets management |
| 2 | **Data Integrity** | Transaction handling, race conditions, idempotency, database constraints |
| 3 | **Error Handling** | Error propagation, HTTP status codes, structured logging, graceful degradation |
| 4 | **Performance** | N+1 queries, indexing, caching strategy, connection pooling, pagination |
| 5 | **API Design** | RESTful conventions, request/response schemas, versioning, backward compatibility |
| 6 | **Concurrency** | Goroutine/thread safety, mutex usage, deadlock prevention, channel patterns |
| 7 | **Architecture** | Layer separation, dependency injection, interface design, SOLID principles |
| 8 | **Observability** | Logging, metrics, tracing, health checks, alerting |
| 9 | **Testing** | Unit tests, integration tests, test database setup, fixture management |
| 10 | **Infrastructure** | Dockerfile best practices, environment config, migration scripts, CI/CD |

## BackEnd-Specific Checks

- Database migration reversibility
- API rate limiting and throttling
- Proper HTTP method and status code usage
- Graceful shutdown handling
- Secret/credential management (no hardcoded secrets)
- CORS configuration

## BackEnd Security Checklist

- 의존성 CVE 확인 (Dependabot alert 교차 참조)
- SQL 파라미터화 쿼리 사용 여부 (raw query 금지)
- 새 엔드포인트의 인증/인가 미들웨어 누락 확인
- 시크릿 하드코딩 탐지 (환경변수 또는 Vault 사용 여부)
- Rate limiting 적용 여부 (공개 엔드포인트)
- CORS wildcard (`*`) 사용 확인 (프로덕션 금지)
- 파일 업로드 시 MIME 타입/사이즈 검증
- 로그에 민감 정보 (패스워드, 토큰, PII) 노출 여부
