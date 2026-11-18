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
    """같은 규칙·파일에서 줄만 다르면 '위치 이동'으로 짝지어진다 — 진짜 신규·해결은 규칙을 다르게 준다."""
    return {"check_id": check, "path": path, "start": {"line": line}, "end": {"line": line},
            "extra": {"severity": "ERROR", "message": "dangerous", "lines": "x", "metadata": {}}}


class BaselineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.reports = os.path.join(self.tmp.name, "reports")
        self.target = os.path.join(self.tmp.name, "target")
        _w(os.path.join(self.target, "src", "app.py"), "\n".join(f"os.system(c{i})" for i in range(20)) + "\n")

    def scan(self, run_id, semgrep, status=None, target=None, checks=True, semgrep_errors=None, meta_in=None, checks_data=None):
        run = os.path.join(self.reports, run_id)
        st = dict.fromkeys(CODE_TOOLS, "ok")
        st.update(status or {})
        _w(os.path.join(run, "raw", "status.tsv"), "".join(f"{t}\t{s}\t0\t\n" for t, s in st.items()))
        _w(os.path.join(run, "raw", "semgrep.json"),
           {"results": semgrep, "errors": semgrep_errors or []} if st["semgrep"] == "ok" else "")
        _w(os.path.join(run, "raw", "gitleaks-git.json"), [])
        _w(os.path.join(run, "raw", "gitleaks-dir.json"), [])
        _w(os.path.join(run, "raw", "osv.json"), {"results": []})
        _w(os.path.join(run, "raw", "checks.json"),
           (checks_data or {"results": [], "errors": [], "warnings": []}) if checks else "")
        _w(os.path.join(run, "raw", "profiles.tsv"), "")
        _w(os.path.join(run, "raw", "meta-in.json"), dict({"osv_db_updated_at": "2099-01-01T00:00:00Z", "plugin_version": "0.11.0",
           "tools": [{"name": "semgrep", "digest": "sha256:a"}], "rules": [{"name": "semgrep-rules", "commit": "c1"}]},
           **(meta_in or {})))
        rc = normalize.main(["--run-dir", run, "--kind", "code", "--target", target or self.target,
                             "--profiles-tsv", os.path.join(run, "raw", "profiles.tsv"),
                             "--meta-json", os.path.join(run, "raw", "meta-in.json")])
        self.assertEqual(rc, 0)
        return (_read(os.path.join(run, "findings.json"))["findings"], _read(os.path.join(run, "meta.json")),
                _read(os.path.join(run, "summary.md"), False))

    def test_new_existing_resolved_against_previous_run_of_same_target(self):
        A, B, C = "r.a", "r.b", "r.c"
        f1, m1, s1 = self.scan("20261101-100000-code", [sg(1, A), sg(2, B)])
        self.assertEqual(m1["baseline"]["run_id"], None)
        self.assertIn("비교하지 않았습니다", s1)
        self.assertEqual({f["baseline"] for f in f1}, {"not-compared"})
        self.assertIn("semgrep", m1["complete_units"])
        f2, m2, s2 = self.scan("20261102-100000-code", [sg(2, B), sg(3, C)])
        b = m2["baseline"]
        self.assertEqual((b["run_id"], b["new"], b["existing"], b["resolved"]), ("20261101-100000-code", 1, 1, 1))
        self.assertEqual(sorted((f["location"]["line"], f["baseline"]) for f in f2), [(2, "existing"), (3, "new")])
        self.assertEqual(b["resolved_items"][0]["location"]["line"], "1")
        self.assertIn("**신규 1** · 유지 1 · **해결 1**", s2)
        self.assertIn("[high] [신규] semgrep", s2)
        self.assertIn("`src/app.py:1`", s2)

    def test_line_moves_are_paired_not_new_and_resolved(self):
        # 리뷰 W2: 위에 줄이 추가돼 같은 결과의 줄 번호만 바뀌면 id 가 달라진다 — 신규+해결이 아니라 위치 이동
        self.scan("20261101-100000-code", [sg(1), sg(5), sg(9, "r.other")])
        f, m, s = self.scan("20261102-100000-code", [sg(2), sg(6), sg(7)])
        b = m["baseline"]
        self.assertEqual((b["new"], b["moved"], b["resolved"]), (1, 2, 1))    # 같은 규칙에 하나가 더 늘었고 r.other 는 해결
        self.assertEqual(b["resolved_items"][0]["rule_id"], "r.other")
        self.assertIn("유지 2 (위치 이동 2)", s)
        self.assertIn("고쳤다고 단정하기 전에", s)

    def test_partial_results_are_not_complete(self):
        # 리뷰 W1: semgrep 이 일부 파일에서 실패(warn)하거나 checks 가 시간 제한·결과 상한에 걸리면 '해결'로 보지 않는다
        self.scan("20261101-100000-code", [sg(1, "r.a"), sg(2, "r.b")])
        _, m, s = self.scan("20261102-100000-code", [], semgrep_errors=[{"level": "warn", "type": "Timeout", "path": "/src/src/app.py",
                                                                          "message": "t"}],
                            checks_data={"results": [], "errors": ["스택 검사가 시간 제한(1초)을 넘어 중단됐습니다"], "warnings": []})
        self.assertNotIn("semgrep", m["complete_units"])
        self.assertNotIn("checks", m["complete_units"])
        self.assertEqual(m["baseline"]["resolved"], 0)
        _, m, _ = self.scan("20261103-100000-code", [sg(1, "r.a")],
                            checks_data={"results": [], "errors": [], "warnings": ["web/x: 결과 900건 중 500건만 리포트에 담았습니다"]})
        self.assertNotIn("checks", m["complete_units"])

    def test_rule_tool_profile_or_plugin_changes_are_not_compared(self):
        # 리뷰 W3: 규칙 커밋·이미지·플러그인 버전이 바뀌면 그 단위는 비교하지 않는다
        self.scan("20261101-100000-code", [sg(1, "r.a")])
        f, m, s = self.scan("20261102-100000-code", [sg(1, "r.b")], meta_in={"rules": [{"name": "semgrep-rules", "commit": "c2"}]})
        b = m["baseline"]
        self.assertIn("semgrep", b["changed_units"])
        self.assertEqual((b["resolved"], [x["baseline"] for x in f]), (0, ["not-compared"]))
        self.assertIn("osv-scanner", b["compared_units"])               # 규칙과 무관한 도구는 비교한다
        self.assertIn("규칙·도구 이미지·프로파일·플러그인 버전이 바뀌어", s)
        _, m, _ = self.scan("20261103-100000-code", [sg(1, "r.b")],
                            meta_in={"rules": [{"name": "semgrep-rules", "commit": "c2"}], "plugin_version": "0.12.0"})
        self.assertEqual(m["baseline"]["compared_units"], [])
        _, m, s = self.scan("20261104-100000-code", [sg(1, "r.b")],
                            meta_in={"rules": [{"name": "semgrep-rules", "commit": "c2"}], "plugin_version": "0.12.0",
                                     "tools": [{"name": "semgrep", "digest": "sha256:b"}]})
        self.assertEqual(m["baseline"]["changed_units"], ["semgrep"])

    def test_same_second_suffixes_are_ordered_numerically(self):
        # 리뷰 N1: 같은 초의 -9 와 -10 — '-10' 의 직전은 '-9' 다
        self.scan("20261101-100000-code", [sg(1, "r.a")])
        self.scan("20261101-100000-code-9", [sg(1, "r.a")])
        _, m, _ = self.scan("20261101-100000-code-10", [sg(1, "r.a")])
        self.assertEqual(m["baseline"]["run_id"], "20261101-100000-code-9")

    def test_resolved_list_is_capped(self):
        self.scan("20261101-100000-code", [sg(i, f"r.n{i}") for i in range(1, 53)])
        _, m, s = self.scan("20261102-100000-code", [sg(1, "r.n1")])
        b = m["baseline"]
        self.assertEqual((b["resolved"], len(b["resolved_items"])), (51, 50))
        self.assertIn("처음 50건", s)

    def test_failed_tool_in_either_run_is_not_compared(self):
        self.scan("20261101-100000-code", [sg(1, "r.a"), sg(2, "r.b")])
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
        self.assertIn("semgrep", m3["baseline"]["not_compared_units"])       # '바뀜'이 아니라 '한쪽에서 실패'
        self.assertNotIn("semgrep", m3["baseline"]["changed_units"])
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
        # meta.json 이 링크인 실행은 읽지 않는다
        linked = os.path.join(self.reports, "20261104-200000-code")
        os.makedirs(linked)
        os.symlink(os.path.join(self.reports, "20261104-100000-code", "meta.json"), os.path.join(linked, "meta.json"))
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


class UnitsTest(unittest.TestCase):
    """리뷰 S1: app·web 의 단위 이름이 status.tsv 와 같아야 비교된다. mobsf 를 읽지 못하면 완전하지 않다."""

    def run_kind(self, kind, status, files):
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        run = os.path.join(d, "reports", "20261101-100000-" + kind)
        _w(os.path.join(run, "raw", "status.tsv"), "".join(f"{t}\tok\t0\t\n" for t in status))
        for n, v in files.items():
            _w(os.path.join(run, "raw", n), v)
        _w(os.path.join(run, "raw", "profiles.tsv"), "")
        _w(os.path.join(run, "raw", "meta-in.json"), {})
        rc = normalize.main(["--run-dir", run, "--kind", kind, "--target", "https://h.example/" if kind == "web" else "/x/app.apk",
                             "--profiles-tsv", os.path.join(run, "raw", "profiles.tsv"), "--meta-json", os.path.join(run, "raw", "meta-in.json")])
        self.assertEqual(rc, 0)
        self.last_meta = os.path.join(run, "meta.json")
        return _read(self.last_meta)

    def findings_of(self, meta):
        return _read(os.path.join(os.path.dirname(self.last_meta), "findings.json"))["findings"]

    def test_web_and_app_units(self):
        zap = {"site": [{"@name": "https://h.example", "alerts": [{"pluginid": "10038", "alertRef": "10038-1", "alert": "CSP",
               "riskcode": "2", "confidence": "2", "instances": [{"uri": "https://h.example/", "method": "GET"}], "desc": "d", "solution": "s"}]}]}
        m = self.run_kind("web", ["zap"], {"zap.json": zap})
        self.assertEqual(m["complete_units"], ["zap"])
        self.assertEqual({f["unit"] for f in self.findings_of(m)}, {"zap"})      # 결과의 단위 = status 의 도구 이름
        leak = [{"RuleID": "aws", "File": "/in/artifact.zip!a.txt", "StartLine": 1, "Secret": "x", "Match": "x"}]
        m = self.run_kind("app", ["mobsf", "gitleaks-artifact"], {"gitleaks-artifact.json": leak})
        self.assertEqual(m["complete_units"], ["gitleaks-artifact"])     # mobsf 결과 없음 → 완전하지 않음
        self.assertEqual({f["unit"] for f in self.findings_of(m)}, {"gitleaks-artifact"})
        m = self.run_kind("app", ["mobsf", "gitleaks-artifact"], {"gitleaks-artifact.json": [], "mobsf-full.json": "{oops"})
        self.assertNotIn("mobsf", m["complete_units"])
        # mobsf 해석이 예외를 내면 완전하지 않다
        from unittest import mock
        with mock.patch.object(normalize, "parse_mobsf", side_effect=ValueError("x")):
            m = self.run_kind("app", ["mobsf", "gitleaks-artifact"], {"gitleaks-artifact.json": [], "mobsf-full.json": {"appsec": {}}})
        self.assertNotIn("mobsf", m["complete_units"])
        with mock.patch.object(normalize, "parse_mobsf", return_value=([], [])):
            m = self.run_kind("app", ["mobsf", "gitleaks-artifact"], {"gitleaks-artifact.json": [], "mobsf-full.json": {"appsec": {}}})
        self.assertIn("mobsf", m["complete_units"])
