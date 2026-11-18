"""scripts/lib/cleanup_reports.py — 보관 기간이 지난 리포트만, 형식에 맞는 실제 폴더만 지운다 (Q10, PR #38)."""

import datetime as dt
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(os.path.dirname(HERE), "scripts", "lib")
sys.path.insert(0, LIB)

import cleanup_reports as c  # noqa: E402

NOW = dt.datetime(2026, 11, 18, 12, 0, 0)


def rid(days_ago, kind="code", hours=0, suffix=""):
    return (NOW - dt.timedelta(days=days_ago, hours=hours)).strftime("%Y%m%d-%H%M%S") + "-" + kind + suffix


def run(argv, now=NOW, environ=None):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = c.main(argv, now, environ if environ is not None else {})
    lines = out.getvalue().splitlines()
    names = [x for x in lines[1:] if not x.startswith("!")]
    # 경고·실패는 stdout 의 '!warn '·'!fail ' 줄과 stderr 를 합쳐 돌려준다 (이슈 #39)
    msgs = "\n".join(x for x in lines if x.startswith("!")) + "\n" + err.getvalue()
    return rc, names, lines[0] if lines else "", msgs


class CleanupTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.out = tempfile.mkdtemp()   # 링크 대상 — 지워지면 안 된다
        # 나중에 등록한 것이 먼저 돈다 — 권한을 되돌린 뒤 지운다 (2차 리뷰 N5)
        self.addCleanup(shutil.rmtree, self.d, True)
        self.addCleanup(shutil.rmtree, self.out, True)
        self.addCleanup(self._chmod_back)

    def _chmod_back(self):
        for root, dirs, _ in os.walk(self.d):
            for x in dirs:
                os.chmod(os.path.join(root, x), 0o700)

    def mk(self, name, kind="dir", base=None):
        p = os.path.join(base or self.d, name)
        if kind == "dir":
            os.makedirs(os.path.join(p, "raw"))
            open(os.path.join(p, "summary.md"), "w").close()
        elif kind == "file":
            open(p, "w").close()
        elif kind == "link":
            os.symlink(self.out, p)
        return p

    def test_only_old_run_dirs_with_valid_names_and_exact_boundary_is_kept(self):
        old = [rid(31), rid(30, hours=1, kind="web"), rid(400, kind="app", suffix="-2"), rid(40, suffix="-1000")]
        keep = [rid(30), rid(29), rid(30, hours=-1), rid(0), rid(-1)]          # 정확히 30일·30일 안·미래 (리뷰 W3)
        for n in old + keep:
            self.mk(n)
        for n in ("notes", rid(90) + ".bak", "20261001-120000-scan", "2026101-120000-code", "20261340-120000-code",
                  ".tmp-x", rid(90, suffix="-1"), rid(90, suffix="-0"), rid(90, suffix="-1001"), rid(90, kind="CODE"),
                  "２０２４０１０１-000000-code", rid(90) + "\n"):                # 리뷰 S2: 접미사·대소문자·유니코드 숫자·개행
            self.mk(n)
        self.mk(rid(60, kind="code", suffix="-9"), "file")
        self.mk(rid(60, kind="app"), "link")
        rc, names, first, _ = run([self.d, "--dry-run"])
        self.assertEqual((rc, first, names), (0, "days=30", sorted(old)))

    def test_deletes_without_following_links_and_dry_run_keeps(self):
        old = self.mk(rid(45))
        link = self.mk(rid(60, kind="app"), "link")
        keep = self.mk(rid(3))
        os.symlink(self.out, os.path.join(old, "raw", "escape"))
        open(os.path.join(self.out, "precious"), "w").close()
        self.assertEqual(run([self.d, "--dry-run"])[:2], (0, [os.path.basename(old)]))
        self.assertTrue(os.path.isdir(old))
        self.assertEqual(run([self.d])[:2], (0, [os.path.basename(old)]))
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.islink(link))
        self.assertTrue(os.path.isdir(keep))
        self.assertTrue(os.path.exists(os.path.join(self.out, "precious")))

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root 는 권한 거부를 재현할 수 없다 (2차 리뷰 S1)")
    def test_partial_failure_reports_the_failed_run_and_keeps_going(self):
        bad = self.mk(rid(50))
        good = self.mk(rid(60, kind="web"))
        os.makedirs(os.path.join(bad, "raw", "sub"))
        open(os.path.join(bad, "raw", "sub", "f"), "w").close()
        os.chmod(os.path.join(bad, "raw", "sub"), 0o500)
        rc, names, _, err = run([self.d])
        self.assertEqual(rc, 1)
        self.assertEqual(names, [os.path.basename(good)])            # 실패한 이름은 '지움'에 없다 (리뷰 W1·W3)
        self.assertIn(f"지우지 못했습니다: {os.path.basename(bad)}", err)
        self.assertFalse(os.path.exists(good))

    def test_pre311_path_removes_relative_to_the_opened_folder(self):
        # 이슈 #39 (R2-S2): 3.8~3.10 경로 — 연 폴더(fd)로 들어가 상대 경로로 지우고, 끝나면 원래 작업 폴더로 돌아온다
        from unittest import mock
        old = self.mk(rid(45))
        cwd = os.getcwd()
        with mock.patch.object(c.sys, "version_info", (3, 9, 0)):
            self.assertEqual(run([self.d])[:2], (0, [os.path.basename(old)]))
        self.assertFalse(os.path.exists(old))
        self.assertEqual(os.getcwd(), cwd)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root 는 권한 거부를 재현할 수 없다")
    def test_pre311_path_works_from_an_unreadable_working_folder(self):
        # PR #47 리뷰 S1: 실행 권한만 있는 작업 폴더에서도 지운다 (작업 폴더를 열 수 없으면 경로로 돌아온다)
        from unittest import mock
        old = self.mk(rid(45))
        noread = tempfile.mkdtemp()
        self.addCleanup(os.chmod, noread, 0o700)
        cwd = os.getcwd()
        os.chdir(noread)
        os.chmod(noread, 0o311)
        try:
            with mock.patch.object(c.sys, "version_info", (3, 9, 0)):
                self.assertEqual(run([self.d])[:2], (0, [os.path.basename(old)]))
        finally:
            os.chmod(noread, 0o700)
            os.chdir(cwd)
        self.assertFalse(os.path.exists(old))

    def test_pre311_path_survives_a_swapped_root(self):
        # 이슈 #39: 고른 뒤 reports 경로가 다른 폴더로 바뀌어도(이름 바꾸기 + 같은 이름의 미끼) 연 폴더 안의 것만 지운다
        from unittest import mock
        name = rid(45)
        self.mk(name)
        moved = self.d + "-moved"
        self.addCleanup(__import__("shutil").rmtree, moved, True)
        orig = c.expired

        def swap(*a, **k):
            res = orig(*a, **k)
            os.rename(self.d, moved)
            os.makedirs(os.path.join(self.d, name, "raw"))      # 같은 이름의 미끼 — 지워지면 안 된다
            return res
        with mock.patch.object(c.sys, "version_info", (3, 9, 0)), mock.patch.object(c, "expired", swap):
            run([self.d])
        self.assertTrue(os.path.isdir(os.path.join(self.d, name)), "바뀐 경로의 미끼를 지움")
        self.assertFalse(os.path.exists(os.path.join(moved, name)))

    def test_concurrent_cleanups_do_not_report_failure(self):
        # 동시 스캔 두 개가 같은 run 을 함께 지워도 이미 사라진 항목은 성공 (리뷰 W2)
        for i in range(30):
            p = self.mk(rid(40 + i))
            for j in range(150):
                open(os.path.join(p, "raw", f"f{j}"), "w").close()
        cmd = [sys.executable, "-I", os.path.join(LIB, "cleanup_reports.py"), self.d]
        procs = [subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) for _ in range(3)]
        for p in procs:
            _, err = p.communicate(timeout=60)
            self.assertEqual(p.returncode, 0, err.decode())
            self.assertNotIn("지우지 못했습니다", err.decode())
        self.assertEqual(os.listdir(self.d), [])

    def test_linked_reports_root_cleans_the_real_folder(self):
        real = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, real, True)
        old = self.mk(rid(45), base=real)
        keep = self.mk(rid(2), base=real)
        root = os.path.join(self.d, "reports")
        os.symlink(real, root)
        self.assertEqual(run([root])[:2], (0, [os.path.basename(old)]))   # 스캔도 이 링크로 쓴다 (리뷰 W4)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.isdir(keep))
        self.assertTrue(os.path.islink(root))

    def test_days_from_option_then_env_then_default(self):
        self.mk(rid(8))
        self.mk(rid(45, kind="app"))
        self.assertEqual(run([self.d, "--dry-run", "--days", "7"])[1:3], (sorted([rid(8), rid(45, kind="app")]), "days=7"))
        env = {c.ENV_DAYS: "60"}
        self.assertEqual(run([self.d, "--dry-run"], environ=env)[1:3], ([], "days=60"))
        self.assertEqual(run([self.d, "--dry-run", "--days", "7"], environ=env)[2], "days=7")
        rc, names, first, err = run([self.d, "--dry-run"], environ={c.ENV_DAYS: "0"})
        self.assertEqual((rc, first, names), (0, "days=30", [rid(45, kind="app")]))
        self.assertIn(c.ENV_DAYS, err)

    def test_bad_arguments(self):
        for bad in (["--days", "0"], ["--days", "x"], ["--days", "3651"], ["--days"], ["--days", "³"], ["--days", "٣٠"],
                    ["--force"], [], [self.d, "extra"]):
            self.assertEqual(run(([self.d] if bad and bad[0] != self.d else []) + bad)[0], 2, bad)

    def test_future_names_warn_and_missing_root_is_fine(self):
        self.mk(rid(-5))
        self.mk(rid(-9, kind="web"))
        rc, names, _, err = run([self.d])
        self.assertEqual((rc, names), (0, []))
        self.assertEqual(err.count("미래인 리포트"), 1)                  # 리뷰 S1 — 한 줄로 묶음 (이슈 #39)
        self.assertIn("미래인 리포트 2개", err)
        self.assertEqual(run([os.path.join(self.d, "none")])[0], 0)
        f = os.path.join(self.d, "file-root")
        open(f, "w").close()
        self.assertEqual(run([f])[0], 1)


if __name__ == "__main__":
    unittest.main()
