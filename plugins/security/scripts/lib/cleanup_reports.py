"""오래된 스캔 리포트 삭제 — $DATA/reports/<run-id>/ 중 보관 기간(기본 30일, 미결정 사항 Q10)이 지난 것.

나이는 폴더 이름의 시각(run-id = YYYYMMDD-HHMMSS-<code|app|web>[-n], 로컬 시각)으로 정한다 — 수정 시각은 복사·백업으로 바뀐다.
이 형식에 맞는 **실제 폴더**만 지운다. 심볼릭 링크·파일·다른 이름은 건드리지 않는다 (사용자가 둔 것일 수 있다).
reports 자체가 링크면 그 실제 폴더를 정리한다 — 스캔도 그 링크를 따라 쓰므로 (PR #38 리뷰 W4). 실제 경로를 한 번 해석해
폴더 fd 로 고정하고 그 안에서만 찾고 지운다 (중간에 경로가 바뀌어도 다른 곳을 지우지 않게, 리뷰 S3).

  python3 -I cleanup_reports.py <reports 폴더> [--days N] [--dry-run]
  보관 기간: --days N > 환경변수 DWK_SECURITY_RETENTION_DAYS > 30 (1~3650)
  stdout: 첫 줄 "days=<N>", 이어서 지운(--dry-run 이면 지울) run-id 한 줄씩
  stderr: 실패·경고 (실패한 run-id 포함)
  종료코드 0 정상 · 1 일부 실패 · 2 인자 오류
"""

import datetime as _dt
import errno
import os
import re
import shutil
import stat
import sys

DEFAULT_DAYS = 30
MAX_DAYS = 3650
ENV_DAYS = "DWK_SECURITY_RETENTION_DAYS"
# sec_new_run 이 만드는 이름만: ASCII 숫자, 접미사는 -2 ~ -1000 (리뷰 S2)
RUN_ID = re.compile(r"([0-9]{8})-([0-9]{6})-(?:code|app|web)(?:-(?:[2-9]|[1-9][0-9]{1,2}|1000))?")
DAYS = re.compile(r"[0-9]{1,4}")
FUTURE_SLACK = _dt.timedelta(days=1)


def run_time(name: str):
    m = RUN_ID.fullmatch(name)
    if not m:
        return None
    try:
        return _dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def parse_days(v):
    if v is None or not DAYS.fullmatch(v) or not 1 <= int(v) <= MAX_DAYS:
        return None
    return int(v)


def expired(names, is_dir, days: int, now=None, warn=None):
    """보관 기간이 지난 run-id 목록 (이름순). 정확히 기간과 같은 시각은 남긴다 (경계: 'days 일보다 오래된 것')."""
    now = now or _dt.datetime.now()
    limit = now - _dt.timedelta(days=days)
    out = []
    for name in sorted(names):
        t = run_time(name)
        if t is None:
            continue
        if t > now + FUTURE_SLACK and warn:
            # 시계가 앞서 있을 때 만든 리포트는 시각이 지날 때까지 남는다 — 알린다 (리뷰 S1)
            warn(f"이름의 시각이 현재보다 미래인 리포트가 있습니다(시계 확인): {name}")
        if t < limit and is_dir(name):
            out.append(name)
    return out


def _gone_ok(func, path, exc_info):
    # 다른 스캔이 같은 run 을 동시에 지우는 중이면 이미 사라진 항목은 성공으로 친다 (리뷰 W2)
    e = exc_info[1] if isinstance(exc_info, tuple) else exc_info
    if isinstance(e, FileNotFoundError):
        return
    raise e


def _remove(fd, root, name):
    if sys.version_info >= (3, 12):
        shutil.rmtree(name, dir_fd=fd, onexc=_gone_ok)
        return
    if sys.version_info >= (3, 11):
        shutil.rmtree(name, dir_fd=fd, onerror=_gone_ok)
        return
    # 3.8~3.10: dir_fd 를 받지 못한다 — 지우기 직전 root 경로가 아직 연 폴더와 같은지 확인하고 경로로 지운다
    st, cur = os.fstat(fd), os.lstat(root)
    if (st.st_dev, st.st_ino) != (cur.st_dev, cur.st_ino):
        raise OSError(errno.ESTALE, "리포트 폴더가 바뀌었습니다")
    shutil.rmtree(os.path.join(root, name), onerror=_gone_ok)


def main(argv, now=None, environ=None):
    environ = os.environ if environ is None else environ
    args, days, dry = [], None, False
    it = iter(argv)
    for a in it:
        if a == "--dry-run":
            dry = True
        elif a == "--days":
            v = next(it, "")
            days = parse_days(v)
            if days is None:
                print(f"--days 는 1~{MAX_DAYS} 사이의 정수입니다: {v!r}", file=sys.stderr)
                return 2
        elif a.startswith("-"):
            print(f"알 수 없는 인자: {a}", file=sys.stderr)
            return 2
        else:
            args.append(a)
    if len(args) != 1:
        print("사용: cleanup_reports.py <reports 폴더> [--days N] [--dry-run]", file=sys.stderr)
        return 2
    if days is None:
        env = environ.get(ENV_DAYS)
        days = parse_days(env) if env is not None else DEFAULT_DAYS
        if days is None:
            print(f"{ENV_DAYS} 값이 잘못됐습니다(1~{MAX_DAYS} 정수): {env!r} — 기본 {DEFAULT_DAYS}일로 정리합니다", file=sys.stderr)
            days = DEFAULT_DAYS
    print(f"days={days}")
    if not os.path.lexists(args[0]):
        return 0          # 아직 스캔한 적 없음
    root = os.path.realpath(args[0])
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as e:
        print(f"리포트 폴더를 열 수 없습니다: {root} ({e.__class__.__name__})", file=sys.stderr)
        return 1
    rc = 0
    try:
        def is_dir(name):
            try:
                return stat.S_ISDIR(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode)
            except OSError:
                return False
        warn = lambda m: print(m, file=sys.stderr)  # noqa: E731
        for name in expired(os.listdir(fd), is_dir, days, now, warn):
            if not dry:
                try:
                    _remove(fd, root, name)
                except OSError as e:
                    print(f"지우지 못했습니다: {name} ({e.__class__.__name__}: {e.strerror or e})", file=sys.stderr)
                    rc = 1
                    continue
            print(name)
    finally:
        os.close(fd)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
