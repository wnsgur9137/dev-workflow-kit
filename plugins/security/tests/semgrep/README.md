# 커스텀 Semgrep 규칙 단위 테스트

`rules/custom/<스택>/<규칙 파일>.yaml` 과 같은 이름의 파일을 `tests/semgrep/<스택>/` 에 둡니다.
`// ruleid: <규칙 id>` 다음 줄은 반드시 잡혀야 하고, `// ok: <규칙 id>` 다음 줄은 잡히면 안 됩니다.
`tests/test_scan_code.sh` 의 `test_real_semgrep_rule_unit_tests` 가 고정 이미지에서 `semgrep --test` 로 실행합니다.
