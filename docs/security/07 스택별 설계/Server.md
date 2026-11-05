---
title: Server
tags: [security/stack, stack/server]
status: draft
created: 2026-11-05
profile: server
---

# Server (Python / Go / Java / Node)

상위: [[스택 프로파일 개요]] · 결정: [[ADR-008 스택별 프로파일]] · 동적 점검: [[scan-web]]

## 주요 위협
1. 인젝션 (SQL, 명령어, 템플릿), 역직렬화
2. 인증·인가 결함, 약한 비밀번호 저장(해시 미사용·MD5)
3. 설정 파일·환경 변수의 시크릿, 디버그 모드로 배포
4. 컨테이너 설정 (root 실행, 시크릿을 이미지에 복사, `latest` 베이스 이미지)
5. 취약 의존성

## 감지 (`profiles/server.yaml`)
| 언어 | detect | lockfile |
|---|---|---|
| Python | `pyproject.toml`, `requirements*.txt`, `Pipfile` | `poetry.lock`, `requirements*.txt`, `Pipfile.lock`, `uv.lock` |
| Go | `go.mod` | `go.mod`/`go.sum` |
| Java/Kotlin | `pom.xml`, `build.gradle*` + `src/main/resources/application*` | `pom.xml`, `gradle.lockfile` |
| Node | `{ file: "**/package.json", has_dependency: [express, fastify, "@nestjs/core", koa, hono] }` | `package-lock.json` 등 |

- Java/Kotlin은 `build.gradle*`가 Android와 겹치므로 `exclude_if: [android]` — 같은 하위 프로젝트에 `AndroidManifest.xml`이 있으면 그 경로는 Android만 적용 ([[스택 프로파일 개요#감지 규칙]] 4번)
- Node는 서버 프레임워크 의존성이 있을 때만 Server로 판정한다. Next.js API 라우트·서버 액션은 web 프로파일(W4·W5)이 담당하고, Next.js에 express 등 커스텀 서버를 붙인 경우에만 web·server가 함께 적용된다

## 점검 항목

| # | 점검 | 방법 | 대상 | 심각도 |
|---|---|---|---|---|
| S1 | 하드코딩 시크릿, `.env`·`application-*.yml`의 비밀 값 | Gitleaks | 소스, 설정 파일 | high |
| S2 | SQL·명령어·템플릿 인젝션, 역직렬화(`pickle`, `yaml.load`, `ObjectInputStream`) | Semgrep 공식 `python`·`go`·`java`·`javascript` (django, flask, fastapi, gin, spring, express 규칙 포함) | 소스 | high |
| S3 | 디버그 모드 배포 (`DEBUG=True`, `app.run(debug=True)`, Spring actuator 전체 노출) | Semgrep 공식 + 커스텀 `server/debug-mode` | 소스, 설정 | high |
| S4 | 약한 해시·암호화 (MD5/SHA1 비밀번호, 고정 IV) | Semgrep 공식 | 소스 | medium |
| S5 | Dockerfile: `USER` 미지정(root), `ADD`로 원격 다운로드, `COPY .env`, `:latest` 베이스 | Semgrep 공식 `dockerfile` + 커스텀 | `Dockerfile*` | medium |
| S6 | `docker-compose`의 `privileged: true`, 호스트 포트 `0.0.0.0` 바인딩 DB | 커스텀 검사 (YAML 파싱) | `docker-compose*.yml` | medium |
| S7 | 취약 의존성 | OSV-Scanner | 위 lockfile | CVSS 기준 |

## 동적 점검 (`/security:scan-web`)
- API 서버도 [[OWASP ZAP]] **baseline**만 사용 (passive). OpenAPI 기반 `zap-api-scan`은 기본이 active라 사용하지 않음 → [[ADR-005 Active Scan 금지]]
- 확인 항목: 에러 응답의 스택트레이스 노출, 보안 헤더, CORS 와일드카드, 서버 버전 헤더

## 수동 체크리스트
- [ ] DB·캐시가 외부 네트워크에 노출되지 않는지 (클라우드 보안 그룹)
- [ ] 로그에 개인정보·토큰이 남지 않는지
- [ ] 관리자 엔드포인트 인증·IP 제한

## 픽스처
`tests/fixtures/server/`: Flask `debug=True` + 문자열 조합 SQL, Go `exec.Command` 사용자 입력, Spring `application.yml` 평문 비밀번호, root로 실행되는 Dockerfile, `privileged` compose

## 범위 밖
- Terraform·Kubernetes 매니페스트 등 IaC 전용 점검 → 필요 시 별도 ADR ([[ADR-003 Trivy 제외]]의 재검토 조건)

> [!warning] 검증 필요
> - Semgrep `dockerfile` 공식 규칙 범위
> - OSV-Scanner의 `uv.lock`·`requirements.txt`(버전 미고정 시) 처리
