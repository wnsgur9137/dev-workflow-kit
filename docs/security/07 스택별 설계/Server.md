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
| Java/Kotlin | `pom.xml`, `{ glob: "**/src/main/resources/application*", root_markers: [pom.xml, build.gradle, build.gradle.kts] }` (모듈 루트로 올려 잡음) | `pom.xml`, `gradle.lockfile` |
| Node | `{ file: "**/package.json", has_dependency: [express, fastify, "@nestjs/core", koa, hono] }` | `package-lock.json` 등 |

- Java/Kotlin은 `build.gradle*`가 Android와 겹치므로 `exclude_if: [android]` — 같은 하위 프로젝트에 `AndroidManifest.xml`이 있으면 그 경로는 Android만 적용 ([[스택 프로파일 개요#감지 규칙]] 4번)
- Node는 서버 프레임워크 의존성이 있을 때만 Server로 판정한다. Next.js API 라우트·서버 액션은 web 프로파일(W4·W5)이 담당하고, Next.js에 express 등 커스텀 서버를 붙인 경우에만 web·server가 함께 적용된다

## 점검 항목

| # | 점검 | 방법 | 대상 | 심각도 |
|---|---|---|---|---|
| S1 | 하드코딩 시크릿, `.env`·`application-*.yml`의 비밀 값 | Gitleaks | 소스, 설정 파일 | high |
| S2 | SQL·명령어·템플릿 인젝션, 역직렬화(`pickle`, `yaml.load`, `ObjectInputStream`) | Semgrep 공식 `python`·`go`·`java`·`javascript` (django, flask, fastapi, gin, spring, express 규칙 포함) | 소스 | high |
| S3 | 디버그 모드 배포 (`DEBUG=True`, `app.run(debug=True)`, Spring actuator 전체 노출) | Semgrep 공식 + 커스텀 `server/django-debug-true` | 소스, 설정 | high |
| S4 | 약한 해시·암호화 (MD5/SHA1 비밀번호, 고정 IV) | Semgrep 공식 | 소스 | medium |
| S5 | Dockerfile: `USER` 미지정(root), `ADD`로 원격 다운로드, `COPY .env`, `:latest` 베이스 | Semgrep 공식 `dockerfile` + 커스텀 | `Dockerfile*` | medium (`COPY .env`·`USER` 미지정은 high — 구현 메모) |
| S6 | `docker-compose`의 `privileged: true`, 호스트 포트 `0.0.0.0` 바인딩 DB | 커스텀 검사 (YAML 파싱) | `docker-compose*.yml` | medium |
| S7 | 취약 의존성 | OSV-Scanner | 위 lockfile | CVSS 기준 |

## 구현 메모 (S-Server)

| # | 구현 | 규칙·검사 ID | 심각도 |
|---|---|---|---|
| S1 | Gitleaks (공통) + 스택 검사 — Spring `application*`·`bootstrap*`(`.yml`·`.properties`)의 비밀 키(`password`·`secret`·`token`·`api-key` 등)에 평문 값. `${ENV}`·`{cipher}`·`ENC(…)`·불리언은 제외, 숫자는 비밀번호 키(`password`·`pwd`)일 때만 결과(`password: 1234`), `${ENV:기본값}`은 기본값이 평문이면 결과. 리스트 항목·앵커·여러 문서(`---`)·properties 이어짐·이스케이프 키 처리. **키 이름만** 기록 | `server.config-plaintext-secret` | high (`src/*test*/`·`-test.` 설정은 low) |
| S2 | Semgrep 공식 `python`·`go`·`java`·`kotlin`·`javascript`·`typescript` | `tainted-sql-string`, `insecure-deserialization`, `dangerous-exec-command` 등 | 규칙 기준 |
| S3 | 공식(Flask `debug-enabled`, Spring `spring-actuator-*`) + 커스텀 Django `DEBUG = True`(`settings*.py`, `settings/dev.py`·`local*`·`test*` 등 개발 설정 제외) | `custom.server.django-debug-true` | high |
| S4 | Semgrep 공식 | `insecure-hash-algorithm-md5`, `md5-used-as-password` 등 | 규칙 기준 |
| S5 | 공식 `dockerfile`(`missing-user`, `avoid-latest-version` 등) + 커스텀 `COPY/ADD .env`(소스 인자만, `.env.example`·`.env.local.example` 등 예시 파일은 토큰 단위로 제외)·`ADD <URL>`(`--checksum` 있으면 제외). 커스텀은 `generic` 언어 + 경로 지정(`Dockerfile*`·`dockerfile*`·`Containerfile*`·`*.Dockerfile`, `*.md`·`*.txt` 제외)이라 `Dockerfile.prod`·`Dockerfile-prod`도 본다 | `custom.server.dockerfile-copy-env`, `custom.server.dockerfile-add-remote` | high / medium |
| S6 | 스택 검사(저장소 전체) — `privileged: true`, `volumes`의 docker.sock 마운트, DB·캐시 이미지(이미지 이름 마지막 구성 요소가 정확히 일치, `${VAR:-기본값}`은 기본값으로)의 포트를 루프백 없이 게시(짧은·긴·흐름 문법, 긴 문법은 `published` 생략 포함, `!override` 태그). docker.sock 은 `volumes`의 짧은·긴(`source:`)·흐름 문법. 서비스 직속 키만 해석(labels 등 하위 매핑 무시). evidence 에 서비스명·포트 | `server.compose-*` | medium |
| S7 | OSV-Scanner (공통) | — | CVSS |

- compose 해석은 표준 라이브러리만 쓰는 들여쓰기 기반이라 병합(`<<: *x`) 같은 고급 문법은 보이는 줄만 본다. 서비스 키의 앵커(`db: &db`)·줄 끝 주석은 처리한다. 주석 제거와 해석은 줄 길이에 선형이다 (PR #25 리뷰 — `\s+#.*$`·서비스 키 정규식의 이차 백트래킹 수정, 줄 길이 2배 비교 테스트로 고정).
- 공식 `dockerfile` 규칙셋에는 best-practice·audit 규칙(`dockerfile-source-not-pinned`, 캐시 정리 등)도 들어 있어 low 결과가 늘 수 있고, `prefer-copy-over-add`는 `dockerfile-add-remote`와 같은 줄에 겹쳐 나온다. 규칙셋 이름이 하위 폴더를 고르지 못해 지금은 전체를 쓴다.
- **한계**: 공식 `dockerfile` 규칙은 Semgrep 이 Dockerfile 로 인식하는 이름(`Dockerfile`, `*.Dockerfile`)에만 적용되고 `Dockerfile.prod`·`Containerfile`은 커스텀 규칙만 본다. `ADD \`·`COPY \` 줄 이어짐, `ADD git@…`, `COPY .env* ./`(와일드카드)·`COPY .env/ …`는 다루지 않는다.
- **한계**: compose·Dockerfile 점검은 server 프로파일이 감지될 때만 켜진다. web 만 감지되는 저장소(예: Next.js + 루트 compose)는 S5·S6 이 빠진다 — 인프라 파일 공통 점검은 후속 과제.

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
> - ~~Semgrep `dockerfile` 공식 규칙 범위~~ → `security/`(missing-user, last-user-is-root, secret-in-build-arg, dockerd-socket-mount 등)·`best-practice/`·`audit/` (semgrep-rules `16b9e6d`). `COPY .env`·`ADD <URL>`은 없어 커스텀으로 보완
> - OSV-Scanner의 `uv.lock`·`requirements.txt`(버전 미고정 시) 처리
