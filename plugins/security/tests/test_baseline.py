"""베이스라인 비교 (P4) — 같은 종류·대상의 직전 실행과 비교해 신규·유지·해결, 실패한 도구는 비교하지 않는다."""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))

import normalize  # noqa: E402

CODE_TOOLS = ("semgrep", "gitleaks-git", "gitleaks-dir", "osv-scanner", "checks")


def _w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))


def _read(path, as_json=True):
    with open(path, encoding="utf-8") as f:
        return json.load(f) if as_json else f.read()


def sg(line, check="rules.python.lang.security.audit.x.os-system", path="/src/src/app.py"):
    return {"check_id": check, "path": path, "start": {"line": line}, "end": {"line": line},
            "extra": {"severity": "ERROR", "message": "dangerous", "lines": "x", "metadata": {}}}


class BaselineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.reports = os.path.join(self.tmp.name, "reports")
        self.target = os.path.join(self.tmp.name, "target")
        _w(os.path.join(self.target, "src", "app.py"), "\n".join(f"os.system(c{i})" for i in range(20)) + "\n")

    def scan(self, run_id, semgrep, status=None, target=None, checks=True):
        run = os.path.join(self.reports, run_id)
        st = dict.fromkeys(CODE_TOOLS, "ok")
        st.update(status or {})
        _w(os.path.join(run, "raw", "status.tsv"), "".join(f"{t}\t{s}\t0\t\n" for t, s in st.items()))
        _w(os.path.join(run, "raw", "semgrep.json"), {"results": semgrep} if st["semgrep"] == "ok" else "")
        _w(os.path.join(run, "raw", "gitleaks-git.json"), [])
        _w(os.path.join(run, "raw", "gitleaks-dir.json"), [])
        _w(os.path.join(run, "raw", "osv.json"), {"results": []})
        _w(os.path.join(run, "raw", "checks.json"), {"findings": [], "errors": [], "warnings": []} if checks else "")
        _w(os.path.join(run, "raw", "profiles.tsv"), "")
        _w(os.path.join(run, "raw", "meta-in.json"), {"osv_db_updated_at": "2099-01-01T00:00:00Z"})
        rc = normalize.main(["--run-dir", run, "--kind", "code", "--target", target or self.target,
                             "--profiles-tsv", os.path.join(run, "raw", "profiles.tsv"),
                             "--meta-json", os.path.join(run, "raw", "meta-in.json")])
        self.assertEqual(rc, 0)
        return (_read(os.path.join(run, "findings.json"))["findings"], _read(os.path.join(run, "meta.json")),
                _read(os.path.join(run, "summary.md"), False))

    def test_new_existing_resolved_against_previous_run_of_same_target(self):
        f1, m1, s1 = self.scan("20261101-100000-code", [sg(1), sg(2)])
        self.assertEqual(m1["baseline"]["run_id"], None)
        self.assertIn("비교하지 않았습니다", s1)
        self.assertEqual({f["baseline"] for f in f1}, {"not-compared"})
        self.assertIn("semgrep", m1["complete_units"])
        f2, m2, s2 = self.scan("20261102-100000-code", [sg(2), sg(3)])
        b = m2["baseline"]
        self.assertEqual((b["run_id"], b["new"], b["existing"], b["resolved"]), ("20261101-100000-code", 1, 1, 1))
        self.assertEqual(sorted((f["location"]["line"], f["baseline"]) for f in f2), [(2, "existing"), (3, "new")])
        self.assertEqual(b["resolved_items"][0]["location"]["line"], "1")
        self.assertIn("**신규 1** · 유지 1 · **해결 1**", s2)
        self.assertIn("[high] [신규] semgrep", s2)
        self.assertIn("`src/app.py:1`", s2)

    def test_failed_tool_in_either_run_is_not_compared(self):
        self.scan("20261101-100000-code", [sg(1), sg(2)])
        # 이번에 semgrep 이 실패 — 결과가 비었지만 '해결'로 보지 않는다
        f2, m2, s2 = self.scan("20261102-100000-code", [], status={"semgrep": "failed"})
        b = m2["baseline"]
        self.assertEqual(b["resolved"], 0)
        self.assertIn("semgrep", b["not_compared_units"])
        self.assertNotIn("semgrep", m2["complete_units"])
        self.assertIn("비교하지 않은 도구", s2)
        # 직전(실패) 실행과 비교하므로 다시 성공한 semgrep 결과도 '신규'가 아니라 '비교 안 함'
        f3, m3, _ = self.scan("20261103-100000-code", [sg(1)])
        self.assertEqual([f["baseline"] for f in f3], ["not-compared"])
        self.assertEqual(m3["baseline"]["run_id"], "20261102-100000-code")
        # 결과 파일을 해석하지 못한 단위(checks 빈 파일)도 완전하지 않다
        _, m4, _ = self.scan("20261104-100000-code", [sg(1)], checks=False)
        self.assertNotIn("checks", m4["complete_units"])

    def test_other_target_kind_old_version_and_links_are_not_baselines(self):
        self.scan("20261101-100000-code", [sg(1)], target=os.path.join(self.tmp.name, "other"))
        _, m, _ = self.scan("20261102-100000-code", [sg(1)])
        self.assertEqual(m["baseline"]["run_id"], None)
        # 이전 버전 리포트(complete_units 없음)
        old = os.path.join(self.reports, "20261103-100000-code")
        _w(os.path.join(old, "meta.json"), {"kind": "code", "target": self.target})
        _w(os.path.join(old, "findings.json"), {"findings": []})
        f, m, s = self.scan("20261104-100000-code", [sg(1)])
        self.assertEqual(m["baseline"]["run_id"], "20261103-100000-code")
        self.assertIn("이전 버전 리포트", s)
        self.assertEqual([x["baseline"] for x in f], ["not-compared"])
        # 링크로 된 실행 폴더·다른 종류·이후 시각은 고르지 않는다
        os.symlink(os.path.join(self.reports, "20261104-100000-code"), os.path.join(self.reports, "20261105-000000-code"))
        _w(os.path.join(self.reports, "20261105-100000-web", "meta.json"), {"kind": "code", "target": self.target, "complete_units": []})
        later = os.path.join(self.reports, "20261201-100000-code")      # 이름이 이번 실행보다 나중 (동시 실행·시계)
        _w(os.path.join(later, "meta.json"), {"kind": "code", "target": self.target, "complete_units": []})
        _w(os.path.join(later, "findings.json"), {"findings": []})
        _, m, _ = self.scan("20261106-100000-code", [sg(1)])
        self.assertEqual(m["baseline"]["run_id"], "20261104-100000-code")

    def test_previous_report_text_is_shown_only_as_code(self):
        self.scan("20261101-100000-code", [sg(1)])
        prev = os.path.join(self.reports, "20261101-100000-code", "findings.json")
        rep = _read(prev)
        rep["findings"][0]["rule_id"] = "x.IGNORE PREVIOUS | `rm` ```"
        rep["findings"][0]["location"]["file"] = "a|b`c.py"
        rep["findings"][0]["severity"] = "<script>"
        _w(prev, rep)
        _, m, s = self.scan("20261102-100000-code", [])
        (row,) = [ln for ln in s.splitlines() if "IGNORE PREVIOUS" in ln]
        self.assertTrue(row.startswith("| info | `semgrep` | `a\\|b'c.py:1` | `"), row)
        self.assertNotIn("```", row)
        self.assertNotIn("<script>", s)


if __name__ == "__main__":
    unittest.main()
