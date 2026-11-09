#!/usr/bin/env python3
"""규칙 저장소 tarball(GitHub codeload) 에서 규칙 YAML 만 안전하게 꺼낸다 — update.sh 가 호출한다.

사용: extract_rules.py <src.tgz> <출력 폴더> <paths(쉼표, 전체면 '.')> <commit> <저장소 이름>

- 일반 파일만 꺼낸다. 절대 경로·상위 경로(..)·심볼릭/하드 링크·장치 파일은 건너뛴다.
- 모든 항목의 최상위 폴더가 정확히 `<저장소 이름>-<commit>` 이어야 한다 (다르거나 섞이면 실패).
  이것은 응답이 요청한 커밋의 tarball 인지만 확인한다. codeload 는 fork 네트워크에만 있는 커밋도
  `<저장소 이름>-<commit>` 으로 내려주므로 fork 커밋은 이 확인으로 구분되지 않는다 — fork 커밋 차단은
  rules.lock 갱신 리뷰(업데이트 절차 5단계, compare API)에서 한다.
- `rules:` 로 시작하는 YAML(규칙 파일)만 설치한다. 테스트용 대상 YAML·.github 는 제외한다.
"""

from __future__ import annotations

import os
import re
import sys
import tarfile

RULE_TOP = re.compile(r"^rules\s*:", re.M)
MAX_FILE = 2_000_000


def extract(src: str, out: str, paths_arg: str, commit: str, repo_name: str) -> int:
    paths = [p.strip("/") for p in paths_arg.split(",") if p.strip()]
    top = f"{repo_name}-{commit}"
    count = 0
    with tarfile.open(src, "r:gz") as tf:
        for m in tf:
            parts = m.name.split("/")
            # 최상위 폴더는 링크·파일을 포함한 모든 항목에서 확인한다. pax 헤더는 tarfile 이 내부에서
            # 처리해(이름에 반영) 항목으로 나오지 않는다 — 아래 분기는 방어용이다
            if m.type in (tarfile.XHDTYPE, tarfile.XGLTYPE):
                continue
            if parts[0] != top:
                raise SystemExit(f"tarball 최상위 폴더가 요청한 커밋과 다릅니다: {parts[0][:80]}")
            # 안전한 추출: 일반 파일만, 절대 경로·상위 경로 금지 (링크는 isfile() 이 거짓).
            # 절대 경로는 parts[0] 이 빈 문자열이라 위에서 먼저 걸린다 (이중 방어)
            if not m.isfile():
                continue
            if len(parts) < 2 or m.name.startswith("/") or ".." in parts:
                continue
            rel = "/".join(parts[1:])  # 최상위 <repo>-<commit>/ 제거
            if paths != ["."] and not any(rel == p or rel.startswith(p + "/") for p in paths):
                continue
            if not rel.endswith((".yaml", ".yml")) or "/.github/" in "/" + rel:
                continue
            if m.size > MAX_FILE:
                continue
            data = tf.extractfile(m).read()
            # 규칙 파일만 (테스트용 YAML 대상 파일 제외)
            if not RULE_TOP.search(data.decode("utf-8", "replace")):
                continue
            dst = os.path.join(out, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
            count += 1
    if count == 0:
        raise SystemExit("규칙 파일이 하나도 없습니다")
    return count


def main(argv) -> int:
    if len(argv) != 5:
        print(__doc__, file=sys.stderr)
        return 2
    extract(*argv)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
