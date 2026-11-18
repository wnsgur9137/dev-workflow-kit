"""scripts/lib/web_target.py — 허용목록·URL 검사, 프록시 필터, 차단 로그 해석 (V3 허용목록)."""

import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts", "lib"))

import iso_probe  # noqa: E402
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

    def test_file_owned_by_another_user_is_refused(self):
        from unittest import mock
        self.write("http://host.docker.internal:3000\n")
        with mock.patch.object(w.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaises(w.TargetError) as cm:
                w.parse_allowlist(self.path)
        self.assertIn("소유자", str(cm.exception))

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
               "http://999.1.1.1", "http://0x7f000001", "http://0x7f.1:3000", "http://2130706433", "http://017700000001"]
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
                    "http://a.example/" + "x" * 2100, "//a.example/", "http:///path",
                    # 16진·정수 IPv4 변형 표기는 loopback 안내를 우회한다 (리뷰 S3)
                    "http://0x7f000001/", "http://0x7f.1/", "http://0x7F.0x0.0x0.0x1/", "http://2130706433/",
                    # 호스트는 첫 ':', 포트는 마지막 ':' 로 따로 해석되면 어긋난다 (리뷰 S3)
                    "http://host.docker.internal:3000:80/", "http://a.example::80/",
                    # '0x' 단독 라벨은 inet_aton 이 0.0.0.0 으로 본다 (2차 리뷰 S-D)
                    "http://0x/", "http://0x.0x/"):
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
                   "http://HOST.docker.internal:3000", "http://host.docker.internal:3000/?@evil.example:3000/"):
            self.assertTrue(self.allowed(f, ok), ok)
        for no in ("http://host.docker.internal:30001/", "http://host.docker.internal:300/", "http://host.docker.internal/",
                   # tinyproxy 는 첫 '/' 앞을 호스트 부분으로 보고 '@' 앞을 버린다 — '?@' 는 다른 곳으로 접속한다 (리뷰 C1)
                   "http://host.docker.internal:3000?@evil.example:3000/", "http://host.docker.internal:3000?x",
                   "http://host.docker.internal:3000#@evil.example/", "http://host.docker.internal:3000;@evil.example/",
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


class RedactTest(unittest.TestCase):
    def test_fragment_path_params_query_and_userinfo(self):
        self.assertEqual(w._redact_url("http://a/p;jsessionid=SECRET1;x#tok=abc?x=1"), "http://a/p;jsessionid=[MASKED];x#[MASKED]")
        self.assertEqual(w._redact_url("http://a/reset#access_token=SECRET2"), "http://a/reset#[MASKED]")
        self.assertEqual(w._redact_url("http://u:p@a/x?y=1&z&code=Q9"), "http://[MASKED]@a/x?y=[MASKED]&z&code=[MASKED]")
        # 인코딩 안 된 '@' 가 든 비밀번호도 출처 부분의 마지막 '@' 까지 가린다 (2차 리뷰 NITPICK)
        self.assertEqual(w._redact_url("http://a@b@c/x"), "http://[MASKED]@c/x")
        self.assertEqual(w._redact_url("//u:p@h/cb?code=R2"), "//[MASKED]@h/cb?code=[MASKED]")
        self.assertEqual(w._redact_url("api.example:443"), "api.example:443")
        self.assertEqual(w._redact_url("http://a:3000/b/c"), "http://a:3000/b/c")
        self.assertEqual(w.display_url("http://h:3000/x?sig=ZZ#f"), "http://h:3000/x?sig=[MASKED]#[MASKED]")

    def test_redact_text_covers_urls_in_free_text(self):
        """근거·로그 안의 URL (2차 리뷰 S-A·W-A): 대문자 scheme, 스킴 상대, 질의가 붙은 상대 경로, JSON 이스케이프, Set-Cookie 값."""
        cases = {
            "Location: HTTPS://h/cb?code=UPPER1": "Location: HTTPS://h/cb?code=[MASKED]",
            "Location: //u:p@h/cb?code=REL2": "Location: //[MASKED]@h/cb?code=[MASKED]",
            "Location: /cb?code=REL3": "Location: /cb?code=[MASKED]",
            '"http:\\/\\/h\\/cb?code=Q13"': '"http://h/cb?code=[MASKED]"',
            "Set-Cookie: sid=COOKIE8; Path=/": "Set-Cookie: sid=[MASKED]; Path=/",
            "url(http://h/cb?code=Q5)": "url(http://h/cb?code=[MASKED])",
            "Job spider error accessing URL http://h:1/cb?code=QS status code returned : 500":
                "Job spider error accessing URL http://h:1/cb?code=[MASKED] status code returned : 500",
            "ratio 1/2 and /docs/page.html stay": "ratio 1/2 and /docs/page.html stay",
            # 3차 리뷰 R3-S2: 스킴 상대·상대 경로의 경로 매개변수, 대문자 scheme 의 경로 매개변수, 그 밖의 상대 URL, 쿠키, 인코딩된 URL
            "Location: HTTPS://h/a;jsessionid=SJ0": "Location: HTTPS://h/a;jsessionid=[MASKED]",
            "Location: //h/cb;jsessionid=SJ1": "Location: //h/cb;jsessionid=[MASKED]",
            "Location: /cb;jsessionid=SJ2": "Location: /cb;jsessionid=[MASKED]",
            "Location: /cb;jsessionid=SJ3?x=1": "Location: /cb;jsessionid=[MASKED]?x=[MASKED]",
            'href="cb?code=REL12"': 'href="cb?code=[MASKED]"',
            "Location: ../cb?code=REL13": "Location: ../cb?code=[MASKED]",
            "url=x/cb?code=REL14": "url=x/cb?code=[MASKED]",
            "Cookie: sid=COOKIE7; b=C9": "Cookie: sid=[MASKED]; b=[MASKED]",
            'Set-Cookie: sid="a COOKIE8"; Path=/': "Set-Cookie: sid=[MASKED]; Path=/",
            "next=http%3A%2F%2Fh%2Fcb%3Fcode%3DENC11": "next=http://h/cb?code=[MASKED]",
            "issue #12 a;b x=1 100%": "issue #12 a;b x=1 100%",
            # 4차 리뷰 R4-W1: 상대 URL 질의 안의 절대 URL(인코딩 여부 무관) — 앞 질의값까지 가린다
            "Location: /authorize?client_id=c&code=SEC2&redirect_uri=https://app/cb":
                "Location: /authorize?client_id=[MASKED]&code=[MASKED]&redirect_uri=[MASKED]",
            "url=/cb?state=SEC4&return=http://x/": "url=/cb?state=[MASKED]&return=[MASKED]",
            "cb?code=SEC3&next=//h/x": "cb?code=[MASKED]&next=[MASKED]",
            "Location: /authorize?code=SEC1&redirect_uri=https%3A%2F%2Fapp%2Fcb%3Fx%3D1":
                "Location: /authorize?code=[MASKED]&redirect_uri=[MASKED]",
            # R4-S1: 한 줄의 쿠키 헤더 여럿(이스케이프된 줄바꿈 포함)·쌍 문법 뒤의 줄 나머지는 남김
            "Set-Cookie: a=1; Path=/ Set-Cookie: b=SEC8": "Set-Cookie: a=[MASKED]; Path=/ Set-Cookie: b=[MASKED]",
            "Set-Cookie: a=1; Path=/\\r\\nSet-Cookie: b=SEC7; Path=/":
                "Set-Cookie: a=[MASKED]; Path=/\\r\\nSet-Cookie: b=[MASKED]; Path=/",
            "cookie: sid=L29 then http://h/a": "cookie: sid=[MASKED] then http://h/a",
            "Cookie: a=1;  b=SEC15": "Cookie: a=[MASKED];  b=[MASKED]",
            # R4-S4: 두 번 인코딩, JSON 유니코드 이스케이프, '/' 없는 상대 URL 의 경로 매개변수·조각, 백틱 경계
            "http%253A%252F%252Fh%252Fcb%253Fcode%253DL9": "http://h/cb?code=[MASKED]",
            "http:\\u002f\\u002fh\\u002fcb?a=1\\u0026code=SEC10": "http://h/cb?a=[MASKED]&code=[MASKED]",
            "Location: cb;jsessionid=SEC13": "Location: cb;jsessionid=[MASKED]",
            "cb#access_token=SEC14": "cb#[MASKED]",
            "`http://h/a?code=L2`": "`http://h/a?code=[MASKED]`",
            # 이슈 #36: 값에 붙은 헤더, 접힌 Set-Cookie(Expires 의 ',' 는 건너뜀), Cookie 의 값 없는 토큰, 3중 인코딩
            "Set-Cookie: a=Set-Cookie: sid=SECRET1": "Set-Cookie: a=[MASKED] sid=[MASKED]",
            "Set-Cookie:a=Set-Cookie:sid=SECRET9": "Set-Cookie:a=[MASKED]",
            # PR #46 2차 리뷰 R2-W1: 값 안의 'cookie:' 글자 때문에 값 꼬리·같은 헤더의 다른 쿠키가 남지 않는다
            "Cookie: a=x-cookie:; sid=SECRETX": "Cookie: a=[MASKED]; sid=[MASKED]",
            "Cookie: lang=en-set-cookie:t=1; session=SECRETX": "Cookie: lang=[MASKED]; session=[MASKED]",
            "Cookie: sid=Set-Cookie:SECRETX": "Cookie: sid=[MASKED]",
            'Set-Cookie: s="v cookie: SECRETX"; Path=/': "Set-Cookie: s=[MASKED]; Path=[MASKED]",
            # 2차 리뷰 S1·S3: 포함·부분 겹침은 합쳐서 한 번 가린다 (중복·연속 마스크 없음)
            "Set-Cookie: a=x,b=SECRETX": "Set-Cookie: a=[MASKED]",
            'Set-Cookie: a=x,b="foo; bar SECRETX"': "Set-Cookie: a=[MASKED]",
            'Set-Cookie: a=x,b="q"zz': "Set-Cookie: a=[MASKED]",
            'Set-Cookie: a="x Set-Cookie: b=SECRETX"': "Set-Cookie: a=[MASKED]",
            "Cookie: a=https://h/x?u=set-cookie:1 sid=SECRETX": "Cookie: a=[MASKED] sid=[MASKED]",
            # PR #46 리뷰 S1·S2·T1: 겹치는 구간(중복·누락 없음), 첫 값에 ',' 가 든 접힘, 줄 넘김, 다음 헤더 이름
            "Set-Cookie: a=Cookie:x=1; sid=SECRETX, b=c": "Set-Cookie: a=[MASKED]; sid=[MASKED] b=[MASKED]",
            "Set-Cookie: a=Cookie:x=1;sid=S, b=c": "Set-Cookie: a=[MASKED];sid=[MASKED] b=[MASKED]",
            "Set-Cookie: a=1, sid=SECRETX": "Set-Cookie: a=[MASKED] sid=[MASKED]",
            "Set-Cookie: a=1\nfoo, bar=baz": "Set-Cookie: a=[MASKED]\nfoo, bar=baz",
            "Set-Cookie: a=1\\r\\nX-Note: hi, bar=baz": "Set-Cookie: a=[MASKED]\\r\\nX-Note: hi, bar=baz",
            "Set-Cookie: a=1, b=Set-Cookie: c=1": "Set-Cookie: a=[MASKED] b=Set-Cookie: c=[MASKED]",
            "Set-Cookie: a=1; Path=/, sid=SECRET2": "Set-Cookie: a=[MASKED]; Path=/, sid=[MASKED]",
            "Set-Cookie: a=1; Expires=Wed, 21 Oct 2026 07:28:00 GMT, sid=SECRET4; Path=/":
                "Set-Cookie: a=[MASKED]; Expires=Wed, 21 Oct 2026 07:28:00 GMT, sid=[MASKED]; Path=/",
            "Set-Cookie: a=1; Path=/, Max-Age=5": "Set-Cookie: a=[MASKED]; Path=/, Max-Age=5",
            "Cookie: x, sid=SECRET5": "Cookie: x, sid=[MASKED]",
            "Cookie: x; sid=SECRET6": "Cookie: x; sid=[MASKED]",
            "next=http%25253A%25252F%25252Fh%25252Fcb%25253Fcode%25253DSECRET3": "next=http://h/cb?code=[MASKED]",
            # 5차 리뷰 R5-S2: ';'·'=' 앞뒤 공백, '\' 가 든 값, JSON 이스케이프된 따옴표 값, 같은 토큰의 따옴표 값, 접두 붙은 헤더, 빈 이름
            "Cookie: a=1 ; b=SECRET1": "Cookie: a=[MASKED] ; b=[MASKED]",
            "Cookie: sid=abc\\def; tok=SECRET2": "Cookie: sid=[MASKED]; tok=[MASKED]",
            'Cookie: a=\\"q\\"; tok=SECRET41': "Cookie: a=[MASKED]; tok=[MASKED]",
            'Cookie: a=1;tok="x SECRET40"': "Cookie: a=[MASKED];tok=[MASKED]",
            "X-Session-Cookie: sid=SECRET3": "X-Session-Cookie: sid=[MASKED]",
            "Cookie: sid = SECRET14": "Cookie: sid = [MASKED]",
            "Cookie: =SECRET15; b=SECRET16": "Cookie: =[MASKED]; b=[MASKED]",
            "xcookie: a=1": "xcookie: a=1",
            # 6차 리뷰 R6-W1: 공백·탭·', ' 로 구분된 쌍, 따옴표 값 뒤 공백 구분 / R6-S1: JSON 공백 제어문자 이스케이프 뒤 헤더 /
            # R6-S2: 256자 넘는 이름 / 빈 쌍 / 값 안 ','
            "Cookie: a=1 b=SECRET": "Cookie: a=[MASKED] b=[MASKED]",
            "Cookie: a=1\tb=SECRET": "Cookie: a=[MASKED]\tb=[MASKED]",
            "Cookie: a=1, b=SECRET": "Cookie: a=[MASKED] b=[MASKED]",
            "Cookie: a=1 b=SECRET; c=SECRET2": "Cookie: a=[MASKED] b=[MASKED]; c=[MASKED]",
            'Cookie: a="SECRET; b" c=SECRET2': "Cookie: a=[MASKED] c=[MASKED]",
            "x\\u000aCookie: sid=SECRET": "x\\u000aCookie: sid=[MASKED]",
            "\\u0009Cookie: sid=SECRET": "\\u0009Cookie: sid=[MASKED]",
            "Cookie: a=1; " + "n" * 300 + "=SECRET": "Cookie: a=[MASKED]; " + "n" * 300 + "=[MASKED]",
            "Cookie: a=1; ; b=SECRET": "Cookie: a=[MASKED]; ; b=[MASKED]",
            "Cookie: a=x,y=SECRET": "Cookie: a=[MASKED]",
            # 7차 리뷰 R7-S2: 이름 안 ','
            "Cookie: a,b=SECRET": "Cookie: a,b=[MASKED]",
            "Cookie: a=1; b,c=SECRET": "Cookie: a=[MASKED]; b,c=[MASKED]",
            "Cookie: ,sid=SECRET": "Cookie: ,sid=[MASKED]",
            "cookie:" * 40 + " sid=SECRET": "cookie:" * 40 + " sid=[MASKED]",
            # R5 NITPICK: 제어문자 이스케이프는 풀지 않는다
            "\\u001b[31m": "\\u001b[31m",
        }
        for src, want in cases.items():
            self.assertEqual(w.redact_text(src), want, src)

    def test_long_url_tail_is_redacted(self):
        """2000자 넘는 URL 의 꼬리·500자 넘는 상대 경로 뒤 질의도 가린다 — 가린 뒤에만 자른다 (3차 리뷰 R3-W2)."""
        line = ("Job spider error accessing URL http://h:3000/sso?SAMLRequest=" + "A" * 2100 +
                "&RelayState=RSLEAK1&code=QLEAK2 status code returned : 500")
        got = w.redact_text(line)
        self.assertNotIn("RSLEAK1", got)
        self.assertNotIn("QLEAK2", got)
        self.assertTrue(got.endswith("&RelayState=[MASKED]&code=[MASKED] status code returned : 500"), got[-120:])
        got = w.redact_text("Location: /" + "p" * 501 + "?code=QLEAK3")
        self.assertNotIn("QLEAK3", got)
        self.assertTrue(got.endswith("…[TRUNCATED]"), got[-40:])
        long_path = w._redact_url("http://h/" + "x" * 600 + "?code=QLEAK4")
        self.assertNotIn("QLEAK4", long_path)
        self.assertEqual(len(long_path), w.URL_SHOW_MAX + len("…[TRUNCATED]"))

    def test_redact_text_is_linear(self):
        # 시작 위치마다 다시 훑는 입력('-/'·'?/')·인코딩 풀기('%2')·쿠키 이름이 다음 헤더까지 이어지는 경로(R5-S1)를 포함한다.
        # 4배 입력에 8배 미만 — 선형이면 약 4배, 이차면 약 16배라 둘을 가른다 (2배·6배 비교는 이차도 통과했다, 5차 리뷰 R5-S1).
        # 기준 시간이 너무 짧으면 잡음에 묻히므로 패턴마다 기준이 10ms 를 넘을 때까지 입력을 키운다 (6차 리뷰 R6-N1)
        import time
        for pat in ("-/", "/a", "?/", "%2", "//", "%25", "Cookie: a=1;", "cookie:a=;", "\\u002f", "a;=", "a#=",
                    "cookie:", "set-cookie:/", 'cookie:"', "Cookie: " + "a" * 300,
                    "Cookie: a=1 x ", " ;", ("cookie:", " "), ("Cookie: a=1 cookie:", "\t"),
                    "Set-Cookie: a=1, ", "Set-Cookie: a=", ("Set-Cookie: a=1; Path=/", ", x"), ("Cookie: x", "; x,"),
                    # PR #46 리뷰 W1: 공백 없이 이어진 Set-Cookie — 값이 다음 헤더까지 한 덩어리
                    ("Set-Cookie:a=", ""), ("set-cookie:a=-", ""), ("Set-Cookie:a=\\u000a", ""), ("Set-Cookie:a=", ";,"),
                    ('Set-Cookie: a="', ""), ('Set-Cookie:a="', ""),
                    # 2차 리뷰 R2-W1 의 값 안 'cookie:' 경로
                    ("Cookie: a=x-cookie:", ""), ("Cookie: a=1;b=-cookie:", "")):
            # (패턴, 꼬리): 꼬리를 n 번 붙인다 — 헤더 여럿이 같은 긴 공백 앞에서 끝나는 입력 (7차 리뷰 R7-S1)
            pat, tail = pat if isinstance(pat, tuple) else (pat, None)
            def t1(n):
                # CPU 시간 — 다른 프로세스와 경쟁해도 덜 흔들린다 (PR #46 2차 리뷰 S2)
                s = time.process_time()
                # 기본 꼬리는 긴 URL 토큰 하나(' //bbb…') — 사용자 정보 정규식 같은 긴 토큰 경로를 넓게 본다 (이슈 #36, PR #34 8차 R8-N1)
                w.redact_text(pat * n + (tail * n if tail is not None else " //" + "b" * n))
                return time.process_time() - s

            def t(n):
                # 3번 재서 가장 짧은 값 — 한 번 재면 일시적인 지연에 흔들린다 (PR #34 7차 R7-N2, PR #46 에서 실제로 한 번 흔들림)
                return min(t1(n) for _ in range(3))
            n = 2000
            base = t(n)
            while base < 0.01 and n < 2_000_000:
                n *= 2
                base = t(n)
            self.assertLess(t(n * 4), base * 8, (pat, n))

    def test_prod_like_host(self):
        for h in ("api.prod.example.com", "production.example.com", "app-prod.example", "prod-api.example"):
            self.assertTrue(w.prod_like_host(h), h)
        for h in ("product.example.com", "prodigy.example", "host.docker.internal", "staging.example"):
            self.assertFalse(w.prod_like_host(h), h)


class IsoProbeTest(unittest.TestCase):
    """scan-web.sh 의 격리 확인 — 각 검사가 누출을 실제로 잡는지 (리뷰 W3: 실제 환경은 늘 격리돼 있어 통합 테스트로는 못 본다)."""

    @staticmethod
    def fail(*a, **k):
        raise OSError("blocked")

    class Conn:
        def close(self):
            pass

    def proxy_403(self, url, timeout=0):
        import urllib.error
        raise urllib.error.HTTPError(url, 403, "Filtered", None, None)

    def run_probe(self, resolve=None, connect=None, proxy_open=None, environ=None):
        return iso_probe.probe("host.docker.internal", "3000", resolve=resolve or self.fail, connect=connect or self.fail,
                               proxy_open=proxy_open or self.proxy_403, environ=environ or {})

    def test_isolated_when_everything_is_blocked(self):
        self.assertEqual(self.run_probe(), [])

    def test_each_leak_is_reported(self):
        self.assertEqual(self.run_probe(resolve=lambda h, p: [("x",)]), ["dns:example.com", "dns:www.zaproxy.org"])
        self.assertEqual(self.run_probe(connect=lambda a, timeout=0: self.Conn() if a == ("1.1.1.1", 443) else self.fail()),
                         ["ip"])
        self.assertEqual(self.run_probe(connect=lambda a, timeout=0: self.Conn() if a == ("host.docker.internal", 3000)
                                        else self.fail()), ["target-direct"])
        self.assertEqual(self.run_probe(environ={"https_proxy": "http://corp:3128", "NO_PROXY": "x", "HTTP_PROXY": " "}),
                         ["proxy-env:https_proxy", "proxy-env:NO_PROXY"])   # no_proxy 도 프록시를 건너뛰게 한다 (4차 리뷰 NITPICK)
        self.assertEqual(self.run_probe(proxy_open=lambda u, timeout=0: self.Conn()), ["proxy-allows-outside"])

        def proxy_502(url, timeout=0):
            import urllib.error
            raise urllib.error.HTTPError(url, 502, "Bad", None, None)
        self.assertEqual(self.run_probe(proxy_open=proxy_502), ["proxy-status:502"])

        def proxy_404(url, timeout=0):     # 403 이 아닌 4xx 도 필터 미적용이다 (2차 리뷰 S-D)
            import urllib.error
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        self.assertEqual(self.run_probe(proxy_open=proxy_404), ["proxy-status:404"])
        self.assertEqual(self.run_probe(proxy_open=self.fail), ["proxy-unreachable"])


class ReachTest(unittest.TestCase):
    """격리 확인 뒤 대상 도달 확인 (2차 리뷰 W-B) — tinyproxy 의 접속 실패 응답만 '닿지 않음'으로 본다."""

    @staticmethod
    def http_error(code, server):
        import email.message
        import urllib.error
        h = email.message.Message()
        if server:
            h["Server"] = server

        def op(url, timeout=0):
            raise urllib.error.HTTPError(url, code, "x", h, None)
        return op

    def test_proxy_connect_failure_is_unreachable(self):
        self.assertEqual(iso_probe.reach("http://h:1/", self.http_error(500, "tinyproxy")), "proxy-500")
        self.assertEqual(iso_probe.reach("http://h:1/", self.http_error(502, "tinyproxy/1.11.3")), "proxy-502")

    def test_target_responses_count_as_reached(self):
        for code, server in ((500, "nginx"), (404, None), (401, "tinyproxy"), (503, "")):
            self.assertIsNone(iso_probe.reach("http://h:1/", self.http_error(code, server)), (code, server))
        self.assertIsNone(iso_probe.reach("http://h:1/", lambda u, timeout=0: IsoProbeTest.Conn()))

    def test_network_error_is_unreachable(self):
        def op(url, timeout=0):
            raise ConnectionRefusedError("refused")
        self.assertEqual(iso_probe.reach("http://h:1/", op), "ConnectionRefusedError")


class ReachOpenerTest(unittest.TestCase):
    """기본 opener 를 가짜 프록시로 돌린다 — 리다이렉트를 따라가지 않고, 사유를 구분한다 (3차 리뷰 R3-W1·S1·S3·S5)."""

    def setUp(self):
        # ProxyHandler 는 no_proxy·macOS 시스템 프록시 예외를 본다 — 개발 PC 설정에 따라 가짜 프록시를 건너뛰지 않게 고정 (4차 리뷰 NITPICK)
        from unittest import mock
        for k in ("no_proxy", "NO_PROXY"):
            p = mock.patch.dict(os.environ, {k: ""})
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("urllib.request.proxy_bypass", return_value=False)
        p.start()
        self.addCleanup(p.stop)

    def serve(self, reply, delay=0.0):
        import socket
        import threading
        import time
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(8)
        self.addCleanup(srv.close)
        lines = []

        def loop():
            while True:
                try:
                    c, _ = srv.accept()
                except OSError:
                    return
                with c:
                    data = b""
                    c.settimeout(2)
                    try:
                        while b"\r\n\r\n" not in data:
                            chunk = c.recv(4096)
                            if not chunk:
                                break
                            data += chunk
                    except OSError:
                        pass
                    lines.append(data.split(b"\r\n", 1)[0].decode("latin-1"))
                    time.sleep(delay)
                    try:
                        c.sendall(reply)
                    except OSError:
                        pass
        threading.Thread(target=loop, daemon=True).start()
        return "http://127.0.0.1:%d" % srv.getsockname()[1], lines

    def ftp_listener(self):
        import socket
        lst = socket.socket()
        lst.bind(("127.0.0.1", 0))
        lst.listen(1)
        lst.settimeout(0.5)
        self.addCleanup(lst.close)
        return lst

    def assert_no_connection(self, lst):
        import socket
        try:
            c, _ = lst.accept()
            c.close()
            self.fail("프록시를 거치지 않는 직접 접속이 있었습니다")
        except socket.timeout:
            pass

    def test_redirects_are_not_followed(self):
        lst = self.ftp_listener()
        for loc in ("https://staging.example/", "https://login.idp.example/sso?x=1", "http://other.example/",
                    "ftp://127.0.0.1:%d/x" % lst.getsockname()[1]):
            reply = ("HTTP/1.1 302 Found\r\nLocation: %s\r\nContent-Length: 0\r\nConnection: close\r\n\r\n" % loc).encode()
            proxy, lines = self.serve(reply)
            self.assertIsNone(iso_probe.reach("http://staging.example/", proxy=proxy, timeout=5), loc)
            self.assertEqual(lines, ["GET http://staging.example/ HTTP/1.1"], loc)
        self.assert_no_connection(lst)

    def test_tinyproxy_error_and_target_error(self):
        proxy, _ = self.serve(b"HTTP/1.1 500 Unable to connect\r\nServer: tinyproxy/1.11.3\r\nContent-Length: 0\r\n\r\n")
        self.assertEqual(iso_probe.reach("http://h.example:3000/", proxy=proxy, timeout=5), "proxy-500")
        proxy, _ = self.serve(b"HTTP/1.1 500 Oops\r\nServer: nginx\r\nContent-Length: 0\r\n\r\n")
        self.assertIsNone(iso_probe.reach("http://h.example:3000/", proxy=proxy, timeout=5))

    def test_non_http_reply_is_unreachable_not_leak(self):
        proxy, _ = self.serve(b"SSH-2.0-OpenSSH_9\r\n\r\n")
        self.assertEqual(iso_probe.reach("http://h.example:22/", proxy=proxy, timeout=5), "BadStatusLine")

    def test_reasons_are_distinguished(self):
        proxy, _ = self.serve(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n", delay=1.5)
        self.assertEqual(iso_probe.reach("http://h.example/", proxy=proxy, timeout=0.5), "timeout")
        proxy, _ = self.serve(b"HTTP/1.1 403 Filtered\r\nServer: tinyproxy\r\nContent-Length: 0\r\n\r\n")
        self.assertEqual(iso_probe.reach("https://h.example/", proxy=proxy, timeout=5), "tunnel-403")
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        self.assertEqual(iso_probe.reach("http://h.example/", proxy="http://127.0.0.1:%d" % port, timeout=5),
                         "ConnectionRefusedError")
        # 도달 확인 제한은 egress-proxy 의 Timeout 보다 짧아야 시간 초과가 늘 'timeout' 으로 나온다 (4차 리뷰 R4-S2)
        with open(os.path.join(os.path.dirname(HERE), "scripts", "scan-web.sh"), encoding="utf-8") as f:
            proxy_timeout = int(re.search(r"'Timeout (\d+)'", f.read()).group(1))
        self.assertLess(iso_probe.REACH_TIMEOUT, proxy_timeout)


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
            "url\thttp://host.docker.internal:3000/x", "display\thttp://host.docker.internal:3000/x",
            "origin\thttp://host.docker.internal:3000",
            "filter\t^http://host\\.docker\\.internal:3000(/|$)"])
        self.assertIn("운영(prod)", err.getvalue())
        # 호스트 이름 라벨이 prod 면 경고 줄을 낸다 (리뷰 S7)
        with open(p, "a", encoding="utf-8") as f:
            f.write("http://api.prod.example:8080\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(w.main(["check", p, "http://api.prod.example:8080/"]), 0)
        self.assertIn("warning\t호스트 이름(api.prod.example)에 prod", out.getvalue())
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
