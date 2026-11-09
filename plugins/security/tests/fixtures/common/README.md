# common 픽스처 — /security:scan-code 회귀 기준선 (V2)

의도적으로 취약한 샘플입니다. 실제 서비스 코드가 아닙니다.

- `src/app.py`: 셸 인젝션·SQL 문자열 조합 (Semgrep python)
- `web/render.js`: DOM XSS (Semgrep javascript)
- `package-lock.json.fixture`, `requirements.txt.fixture`: 알려진 취약 버전 고정 (OSV). 저장소의 의존성 알림이
  실제 의존성으로 오인하지 않도록 `.fixture` 로 두고, 테스트가 임시 폴더에 원래 이름으로 복사한다.
- 시크릿은 **커밋하지 않는다.** 테스트(`tests/test_scan_code.sh`)가 임시 git 저장소에서 가짜 키를 만들어
  커밋 후 삭제(히스토리)·미커밋 파일(작업 트리)로 배치한다.
- `src/app.py` 의 셸 인젝션 줄 끝 주석은 리포트 프롬프트 인젝션 검증용 문구다 (V3).
