# server 픽스처 (S-Server 기준선)

`tests/baseline/server.json` 의 기대 결과를 만드는 일부러 취약한 서버 코드입니다. 실제 서비스 코드가 아닙니다.

| 점검 | 파일 | 기대 |
|---|---|---|
| S1 설정 파일 평문 비밀번호 | `api/src/main/resources/application.yml` | `config-plaintext-secret` |
| S2 인젝션·역직렬화 | `web/app.py`(SQL·pickle), `gosvc/main.go`(exec.Command) | 공식 규칙 |
| S3 디버그 모드 | `web/app.py`(`debug=True`), `web/settings.py`(`DEBUG = True`), `application.yml`(actuator 전체 노출) | `debug-enabled`, `django-debug-true`, `spring-actuator-*` |
| S4 약한 해시 | `web/app.py`(`hashlib.md5`) | 공식 규칙 |
| S5 Dockerfile | `Dockerfile` | `missing-user`, `dockerfile-copy-env`, `dockerfile-add-remote` |
| S6 compose | `docker-compose.yml` | `compose-privileged`, `compose-db-port-exposed`, `compose-docker-socket` |
| 음성 사례 | `infra/Dockerfile.prod`(`.env.example`·`--checksum`·`.envrc`), `infra/docker-compose.safe.yml`(루프백·mongo-express·환경 변수 docker.sock), `web/settings/dev.py`, `application-safe.yml` | 기준선 `must_not_find` |
| S5 Containerfile | `deploy/Containerfile` | `dockerfile-copy-env` (generic 언어로 점검) |
| S7 취약 의존성 | `requirements.txt.fixture`(테스트에서 `web/requirements.txt` 로 복사) | `django@3.2.0` |
