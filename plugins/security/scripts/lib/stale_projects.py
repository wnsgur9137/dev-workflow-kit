#!/usr/bin/env python3
"""이전 실행이 SIGKILL 등으로 trap 없이 끝나 남긴 툴킷 compose 프로젝트 중 오래된 것을 고른다.

사용: <프로젝트 이름> <생성 시각> 줄들 | stale_projects.py <접두사> <분> <엔진 현재 시각>
  - 접두사: dwk-sec-app | dwk-sec-web — 이름이 '<접두사>-<16진수 12자>' 인 프로젝트만 본다
  - 시각은 엔진(VM) 시계로 찍힌 RFC3339(Nano) — 비교 기준도 엔진 시계(docker info .SystemTime)를 쓴다
    (잠자기 뒤 VM 시계가 밀려도 방금 시작한 다른 실행을 오래된 것으로 보지 않게, PR #32 2차 리뷰 NS3)
  - 한 프로젝트의 가장 최근 활동이 <분> 보다 오래된 것만 stdout 에 공백으로 구분해 쓴다
  - 시각을 모르는 줄(필드 없음·형식 오류·Go zero time)이 하나라도 있는 프로젝트는 "모름"이라 지우지 않는다 —
    줄 순서와 상관없이 (PR #32 3·4·6차 리뷰)
scan-app.sh 에서 옮겼다 (PR #32 의 판정 그대로, scan-web.sh 와 함께 쓴다).
"""

import datetime as dt
import re
import sys


def parse(t):
    # RFC3339Nano(소수점 1~9자리)·Z·+09:00 — 3.9 의 fromisoformat 은 소수점 6자리만 받는다
    t = re.sub(r"\.(\d{1,9})", lambda m: "." + (m.group(1) + "000000")[:6], t.strip()).replace("Z", "+00:00")
    ts = dt.datetime.fromisoformat(t)
    if ts.tzinfo is None:
        raise ValueError("시간대 없음")
    return ts


def stale(lines, prefix, limit_min, now):
    name_re = re.compile(re.escape(prefix) + r"-[0-9a-f]{12}")
    limit = limit_min * 60
    newest = {}
    for line in lines:
        p = line.split()
        if not p or not name_re.fullmatch(p[0]):
            continue
        try:
            if len(p) != 2:
                raise ValueError("시각 없음")
            ts = parse(p[1])
            if ts.year < 2000:
                raise ValueError("zero time")   # Go 의 zero time(0001-01-01)은 "모름"이다 (3차 리뷰 NT1)
        except ValueError:
            newest[p[0]] = None          # 시각을 모르는 프로젝트는 지우지 않는다
            continue
        if p[0] in newest and newest[p[0]] is None:
            continue
        newest[p[0]] = max(newest.get(p[0]) or ts, ts)
    return [k for k, v in newest.items() if v is not None and (now - v).total_seconds() > limit]


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ("dwk-sec-app", "dwk-sec-web"):
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    print(" ".join(stale(sys.stdin, sys.argv[1], int(sys.argv[2]), parse(sys.argv[3]))))
