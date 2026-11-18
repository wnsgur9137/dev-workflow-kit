"""오래된 스캔 리포트 삭제 — $DATA/reports/<run-id>/ 중 보관 기간(기본 30일, 미결정 사항 Q10)이 지난 것.

나이는 폴더 이름의 시각(run-id = YYYYMMDD-HHMMSS-<code|app|web>[-n], 로컬 시각)으로 정한다 — 수정 시각은 복사·백업으로 바뀐다.
이 형식에 맞는 **실제 폴더**만 지운다. 심볼릭 링크·파일·다른 이름은 건드리지 않는다 (사용자가 둔 것일 수 있다).

  python3 -I cleanup_reports.py <reports 폴더> [--days N] [--dry-run]
  출력: 지운(또는 --dry-run 이면 지울) run-id 한 줄씩. 종료코드 0 정상 · 1 일부 실패 · 2 인자 오류
"""

import datetime as _dt
import os
import re
import shutil
import stat
import sys

DEFAULT_DAYS = 30
MAX_DAYS = 3650
RUN_ID = re.compile(r"^(\d{8})-(\d{6})-(?:code|app|web)(?:-\d{1,4})?$")


def run_time(name: str):
    m = RUN_ID.match(name)
    if not m:
        return None
    try:
        return _dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def expired(reports: str, days: int, now=None):
    """보관 기간이 지난 run-id 목록 (이름순). 이름이 형식에 맞고 실제 폴더(링크 아님)인 것만."""
    now = now or _dt.datetime.now()
    limit = now - _dt.timedelta(days=days)
    out = []
    for name in sorted(os.listdir(reports)):
        t = run_time(name)
        if t is None or t >= limit:
            continue
        try:
            st = os.lstat(os.path.join(reports, name))
        except OSError:
            continue
        if stat.S_ISDIR(st.st_mode):
            out.append(name)
    return out


def main(argv, now=None):
    args, days, dry = [], DEFAULT_DAYS, False
    it = iter(argv)
    for a in it:
        if a == "--dry-run":
            dry = True
        elif a == "--days":
            v = next(it, "")
            if not v.isdigit() or not 1 <= int(v) <= MAX_DAYS:
                print(f"--days 는 1~{MAX_DAYS} 사이의 정수입니다: {v!r}", file=sys.stderr)
                return 2
            days = int(v)
        elif a.startswith("-"):
            print(f"알 수 없는 인자: {a}", file=sys.stderr)
            return 2
        else:
            args.append(a)
    if len(args) != 1:
        print("사용: cleanup_reports.py <reports 폴더> [--days N] [--dry-run]", file=sys.stderr)
        return 2
    reports = args[0]
    try:
        st = os.lstat(reports)
    except OSError:
        return 0          # 아직 스캔한 적 없음
    if not stat.S_ISDIR(st.st_mode):
        print(f"리포트 폴더가 실제 폴더가 아닙니다(링크·파일): {reports}", file=sys.stderr)
        return 1
    rc = 0
    for name in expired(reports, days, now):
        if not dry:
            try:
                # rmtree 는 안쪽 심볼릭 링크를 따라가지 않고 링크만 지운다
                shutil.rmtree(os.path.join(reports, name))
            except OSError as e:
                print(f"지우지 못했습니다: {name} ({e.__class__.__name__})", file=sys.stderr)
                rc = 1
                continue
        print(name)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
