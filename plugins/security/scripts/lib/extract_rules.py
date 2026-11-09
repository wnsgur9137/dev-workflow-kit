#!/usr/bin/env python3
"""규칙 저장소 tarball(GitHub codeload) 에서 규칙 YAML 만 안전하게 꺼낸다 — update.sh 가 호출한다.

사용: extract_rules.py <src.tgz> <출력 폴더> <paths(쉼표, 전체면 '.')> <commit>

- 일반 파일만 꺼낸다. 절대 경로·상위 경로(..)·심볼릭/하드 링크·장치 파일은 건너뛴다.
- 모든 항목의 최상위 폴더가 `<repo>-<commit>` 이어야 한다. codeload 는 fork 네트워크에만 있는 커밋도
  원래 저장소 경로로 내려주므로, 최상위 폴더 이름으로 요청한 커밋인지 확인한다 (다르면 실패).
- `rules:` 로 시작하는 YAML(규칙 파일)만 설치한다. 테스트용 대상 YAML·.github 는 제외한다.
"""

from __future__ import annotations

import os
import re
import sys
import tarfile

RULE_TOP = re.compile(r"^rules\s*:", re.M)
MAX_FILE = 2_000_000


def extract(src: str, out: str, paths_arg: str, commit: str) -> int:
    paths = [p.strip("/") for p in paths_arg.split(",") if p.strip()]
    suffix = "-" + commit
    count = 0
    with tarfile.open(src, "r:gz") as tf:
        for m in tf:
            parts = m.name.split("/")
            # 최상위 폴더는 링크·파일을 포함한 모든 항목에서 확인한다 (pax 헤더 제외)
            if m.type in (tarfile.XHDTYPE, tarfile.XGLTYPE):
                continue
            if not parts[0].endswith(suffix):
                raise SystemExit(f"tarball 최상위 폴더가 요청한 커밋과 다릅니다: {parts[0][:80]}")
            # 안전한 추출: 일반 파일만, 절대 경로·상위 경로 금지 (링크는 isfile() 이 거짓)
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
    if len(argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    extract(*argv)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
