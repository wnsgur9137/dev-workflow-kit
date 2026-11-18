"""scripts/lib/cleanup_reports.py — 보관 기간이 지난 리포트만, 형식에 맞는 실제 폴더만 지운다 (Q10)."""

import datetime as dt
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts", "lib"))

import cleanup_reports as c  # noqa: E402

NOW = dt.datetime(2026, 11, 18, 12, 0, 0)


def rid(days_ago, kind="code", hours=0, suffix=""):
    return (NOW - dt.timedelta(days=days_ago, hours=hours)).strftime("%Y%m%d-%H%M%S") + "-" + kind + suffix


class ExpiredTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.out = tempfile.mkdtemp()   # 링크 대상 — 지워지면 안 된다

    def mk(self, name, kind="dir"):
        p = os.path.join(self.d, name)
        if kind == "dir":
            os.makedirs(os.path.join(p, "raw"))
            open(os.path.join(p, "summary.md"), "w").close()
        elif kind == "file":
            open(p, "w").close()
        elif kind == "link":
            os.symlink(self.out, p)
        return p

    def test_only_old_run_dirs_with_valid_names(self):
        old = [rid(31), rid(30, hours=1, kind="web"), rid(400, kind="app", suffix="-2")]
        keep = [rid(29), rid(30, hours=-1), rid(0), rid(-1)]          # 30일 안·미래 시각
        for n in old + keep:
            self.mk(n)
        for n in ("notes", "20261001-120000-code.bak", "20261001-120000-scan", "2026101-120000-code",
                  "20261340-120000-code", ".tmp-x"):
            self.mk(n)
        self.mk(rid(90, kind="web", suffix="-3") + "x")
        self.mk(rid(60, kind="code", suffix="-9"), "file")                # 이름은 맞지만 파일
        self.mk(rid(60, kind="app"), "link")                              # 이름은 맞지만 링크
        self.assertEqual(c.expired(self.d, 30, NOW), sorted(old))

    def test_main_deletes_and_dry_run_keeps(self):
        old = self.mk(rid(45))
        link = self.mk(rid(60, kind="app"), "link")
        keep = self.mk(rid(3))
        # 지우는 폴더 안의 링크는 따라가지 않는다
        os.symlink(self.out, os.path.join(old, "raw", "escape"))
        open(os.path.join(self.out, "precious"), "w").close()
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(c.main([self.d, "--dry-run"], NOW), 0)
        self.assertEqual(buf.getvalue().split(), [os.path.basename(old)])
        self.assertTrue(os.path.isdir(old))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(c.main([self.d], NOW), 0)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.islink(link))
        self.assertTrue(os.path.isdir(keep))
        self.assertTrue(os.path.exists(os.path.join(self.out, "precious")))

    def test_days_option_and_arguments(self):
        self.mk(rid(8))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(len(c.expired(self.d, 7, NOW)), 1)
            self.assertEqual(len(c.expired(self.d, 30, NOW)), 0)
        with redirect_stderr(io.StringIO()):
            for bad in (["--days", "0"], ["--days", "x"], ["--days", "3651"], ["--days"], ["--force"], []):
                self.assertEqual(c.main(([self.d] if bad != [] else []) + bad), 2, bad)

    def test_missing_reports_dir_is_fine_and_link_root_is_refused(self):
        self.assertEqual(c.main([os.path.join(self.d, "none")]), 0)
        root = os.path.join(self.d, "reports-link")
        os.symlink(self.out, root)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(c.main([root]), 1)


if __name__ == "__main__":
    unittest.main()
