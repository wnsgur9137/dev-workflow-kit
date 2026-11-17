"""scripts/lib/web_target.py — 허용목록·URL 검사, 프록시 필터, 차단 로그 해석 (V3 허용목록)."""

import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts", "lib"))

import stale_projects  # noqa: E402
import web_target as w  # noqa: E402


class AllowlistTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "targets.allowlist")

    def write(self, text, mode=0o600):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(self.path, mode)

    def test_missing_file_explains_how_to_create(self):
        with self.assertRaises(w.TargetError) as cm:
            w.parse_allowlist(self.path)
        self.assertIn("허용목록이 없습니다", str(cm.exception))
        self.assertIn("http://host.docker.internal:3000", str(cm.exception))

    def test_group_or_other_writable_file_is_refused(self):
        for mode in (0o620, 0o602, 0o666):
            self.write("http://host.docker.internal:3000\n", mode)
            with self.assertRaises(w.TargetError, msg=oct(mode)) as cm:
                w.parse_allowlist(self.path)
            self.assertIn("chmod 600", str(cm.exception))
        self.write("http://host.docker.internal:3000\n", 0o644)   # 읽기만 열린 것은 괜찮다
        self.assertEqual(len(w.parse_allowlist(self.path)), 1)

    def test_entries_comments_default_ports_and_prod_marker(self):
        self.write("# 주석 줄\n\n"
                   "  http://Host.Docker.Internal:3000/   # 개발 서버\n"
                   "https://staging.my-app.example  # prod\n"
                   "http://a.example # PRODUCTION 미러\n"
                   "http://b.example:8080 # prodigy 는 prod 표시가 아니다\n"
                   "http://c.example:81 # prod-like 는 prod 로 본다\n")
        got = w.parse_allowlist(self.path)
        self.assertEqual([(e[0], e[1], e[2], e[3]) for e in got], [
            ("http", "host.docker.internal", 3000, False),
            ("https", "staging.my-app.example", 443, True),
            ("http", "a.example", 80, True),
            ("http", "b.example", 8080, True),     # 주석에 단어 'prod' 가 따로 있으면 prod 로 본다 (보수적으로)
            ("http", "c.example", 81, True),
        ])

    def test_prodigy_alone_is_not_prod(self):
        self.write("http://b.example:8080 # prodigy\n")
        self.assertFalse(w.parse_allowlist(self.path)[0][3])

    def test_invalid_lines_reject_whole_file(self):
        bad = ["http://*.example.com", "http://example.com/path", "ftp://example.com", "http://user@example.com",
               "example.com", "http://example.com:0", "http://example.com:70000", "http://[::1]:3000",
               "http://localhost:3000", "http://127.0.0.1:3000", "http://ex ample.com", "http://0.0.0.0:80",
               "http://999.1.1.1"]
        for line in bad:
            self.write("http://ok.example:3000\n" + line + "\n")
            with self.assertRaises(w.TargetError, msg=line) as cm:
                w.parse_allowlist(self.path)
            self.assertIn("2번째 줄", str(cm.exception), line)

    def test_empty_allowlist_is_refused(self):
        self.write("# 아직 아무것도 없음\n\n")
        with self.assertRaises(w.TargetError):
            w.parse_allowlist(self.path)


class TargetTest(unittest.TestCase):
    def test_normalizes_scheme_host_and_default_port(self):
        self.assertEqual(w.parse_target("HTTP://Host.Docker.Internal:3000"),
                         ("http", "host.docker.internal", 3000, "http://host.docker.internal:3000/"))
        self.assertEqual(w.parse_target("https://staging.example/a/b?x=1#frag")[3], "https://staging.example:443/a/b?x=1")
        self.assertEqual(w.parse_target("http://a.example.:80/")[1:3], ("a.example", 80))

    def test_rejects_unsafe_urls(self):
        for url in ("", "javascript:alert(1)", "file:///etc/passwd", "http://user:pw@a.example/", "http://@a.example/",
                    "http://a.example/ x", "http://a.example/\x00", "http://a.example\\@b.example/", "http://ä.example/",
                    "http://localhost:3000/", "http://LOCALHOST/", "http://app.localhost/", "http://127.0.0.2/",
                    "http://[::1]:3000/", "http://0.0.0.0/", "http://a.example:99999/", "http://a.example:abc/",
                    "http://a.example/" + "x" * 2100, "//a.example/", "http:///path"):
            with self.assertRaises(w.TargetError, msg=repr(url)):
                w.parse_target(url)

    def test_match_requires_exact_scheme_host_port(self):
        entries = [("http", "host.docker.internal", 3000, False, 1), ("https", "s.example", 443, False, 2)]
        self.assertIsNotNone(w.match(entries, "http", "host.docker.internal", 3000))
        self.assertIsNotNone(w.match(entries, "https", "s.example", 443))
        for t in (("https", "host.docker.internal", 3000), ("http", "host.docker.internal", 3001),
                  ("http", "s.example", 443), ("http", "docker.internal", 3000), ("https", "x.s.example", 443)):
            self.assertIsNone(w.match(entries, *t), t)


class ProxyFilterTest(unittest.TestCase):
    """필터는 tinyproxy(POSIX ERE, 대소문자 무시) 가 요청 URL 전체에 맞춘다. 여기서는 같은 식을 Python re 로 확인한다
    (실제 tinyproxy 동작은 test_scan_web.sh 의 Docker 통합 테스트가 확인)."""

    def allowed(self, filters, url):
        return any(re.search(f, url, re.I) for f in filters)

    def test_http_filter_allows_only_the_origin(self):
        f = w.proxy_filters("http", "host.docker.internal", 3000)
        for ok in ("http://host.docker.internal:3000/", "http://host.docker.internal:3000/a?b=c",
                   "http://HOST.docker.internal:3000", "http://host.docker.internal:3000?x"):
            self.assertTrue(self.allowed(f, ok), ok)
        for no in ("http://host.docker.internal:30001/", "http://host.docker.internal:300/", "http://host.docker.internal/",
                   "http://host.docker.internal.evil.example:3000/", "http://hostXdocker.internal:3000/",
                   "http://host.docker.internal:3000@evil.example/", "https://host.docker.internal:3000/",
                   "host.docker.internal:3000", "http://evil.example/http://host.docker.internal:3000/"):
            self.assertFalse(self.allowed(f, no), no)

    def test_default_port_may_be_omitted_only_for_that_port(self):
        f = w.proxy_filters("http", "a.example", 80)
        self.assertTrue(self.allowed(f, "http://a.example/"))
        self.assertTrue(self.allowed(f, "http://a.example:80/"))
        self.assertFalse(self.allowed(f, "http://a.example:8080/"))

    def test_https_filter_matches_connect_target_only(self):
        f = w.proxy_filters("https", "staging.my-app.example", 443)
        self.assertTrue(self.allowed(f, "staging.my-app.example:443"))
        for no in ("staging.my-app.example:4430", "xstaging.my-app.example:443", "staging.my-app.example:443.evil",
                   "http://staging.my-app.example/", "evil.example:443"):
            self.assertFalse(self.allowed(f, no), no)

    def test_filter_uses_only_portable_ere_escapes(self):
        # POSIX ERE 에서 '\-' 처럼 정의되지 않은 이스케이프를 쓰지 않는다 — '\.' 만 남는다
        for f in w.proxy_filters("http", "my-app.dev-1.example", 8080) + w.proxy_filters("https", "a-b.example", 8443):
            self.assertEqual(re.findall(r"\\(.)", f), ["."] * len(re.findall(r"\\(.)", f)), f)


class DeniedTest(unittest.TestCase):
    LOG = "\n".join([
        'NOTICE    Nov 17 05:33:16.110 [1]: Initializing tinyproxy ...',
        'NOTICE    Nov 17 05:33:18.812 [1]: Proxying refused on filtered url "http://dwk-isolation-probe.invalid/"',
        'NOTICE    Nov 17 05:33:19.000 [1]: Proxying refused on filtered url "http://cdn.example/a.js?token=abc123&v"',
        'NOTICE    Nov 17 05:33:19.100 [1]: Proxying refused on filtered url "http://cdn.example/a.js?token=zzz999&v"',
        'NOTICE    Nov 17 05:33:19.200 [1]: Proxying refused on filtered url "http://u:secret@evil.example/x"',
        'NOTICE    Nov 17 05:33:19.300 [1]: Proxying refused on filtered url "api.example:443"',
    ])

    def test_collects_dedupes_and_redacts(self):
        got = w.denied_requests(self.LOG)
        self.assertEqual(got["total"], 4)                   # 격리 확인 요청은 뺀다
        self.assertEqual(got["urls"], ["http://cdn.example/a.js?token=[MASKED]&v", "http://[MASKED]@evil.example/x",
                                       "api.example:443"])
        self.assertEqual(got["unique"], 3)
        self.assertNotIn("abc123", str(got))
        self.assertNotIn("secret", str(got))

    def test_caps_list_but_keeps_counts(self):
        log = "\n".join(f'Proxying refused on filtered url "http://x{i}.example/"' for i in range(80))
        got = w.denied_requests(log)
        self.assertEqual((got["total"], got["unique"], len(got["urls"])), (80, 80, w.DENIED_MAX))

    def test_empty_log(self):
        self.assertEqual(w.denied_requests(""), {"total": 0, "unique": 0, "urls": []})


class CliTest(unittest.TestCase):
    def test_check_prints_url_origin_filter_and_refuses_prod(self):
        import contextlib
        import io
        d = tempfile.mkdtemp()
        p = os.path.join(d, "targets.allowlist")
        with open(p, "w", encoding="utf-8") as f:
            f.write("http://host.docker.internal:3000\nhttps://s.example # prod\n")
        os.chmod(p, 0o600)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(w.main(["check", p, "http://host.docker.internal:3000/x"]), 0)
            self.assertEqual(w.main(["check", p, "https://s.example/"]), 1)
            self.assertEqual(w.main(["check", p, "http://host.docker.internal:3001/"]), 1)
        self.assertEqual(out.getvalue().splitlines(), [
            "url\thttp://host.docker.internal:3000/x", "origin\thttp://host.docker.internal:3000",
            "filter\t^http://host\\.docker\\.internal:3000([/?]|$)"])
        self.assertIn("운영(prod)", err.getvalue())
        self.assertIn("허용목록에 없는 대상", err.getvalue())


class StaleProjectsTest(unittest.TestCase):
    def test_prefix_is_respected(self):
        now = stale_projects.parse("2030-01-01T12:00:00Z")
        lines = ["dwk-sec-web-0000000000aa 2029-12-31T00:00:00Z", "dwk-sec-app-0000000000bb 2029-12-31T00:00:00Z",
                 "dwk-sec-web-0000000000cc 2030-01-01T11:30:00Z", "dwk-sec-web-0000000000dd",
                 "dwk-sec-web-0000000000dd 2029-12-31T00:00:00Z"]
        self.assertEqual(stale_projects.stale(lines, "dwk-sec-web", 120, now), ["dwk-sec-web-0000000000aa"])
        self.assertEqual(stale_projects.stale(lines, "dwk-sec-app", 120, now), ["dwk-sec-app-0000000000bb"])


if __name__ == "__main__":
    unittest.main()
