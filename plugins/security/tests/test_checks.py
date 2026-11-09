"""checks.py 단위 테스트 — 스택별 커스텀 검사 (S-Web: W2 .env 키, W4 인증 없는 라우트, W6 next.config, W8 설치 스크립트)."""

import json
import os
import re
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))

import checks  # noqa: E402
import profiles  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "web")


def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class ChecksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.defs = profiles.load_profiles(profiles.DEFAULT_PROFILE_DIR)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = os.path.join(self.tmp.name, "target")
        os.makedirs(self.t)

    def tearDown(self):
        self.tmp.cleanup()

    def run_checks(self, detected=(("web", ".", []),), allow_errors=False):
        report = checks.run(self.t, list(detected), self.defs)
        if not allow_errors:
            self.assertEqual(report["errors"], [], "검사 예외가 결과를 비우지 않았는지")
        return report

    def rules(self, report):
        return sorted((r["rule_id"], r["file"]) for r in report["results"])

    def test_all_profile_checks_are_registered(self):
        for name, p in self.defs.items():
            for c in p.get("checks") or []:
                self.assertIn(c, checks.CHECKS, f"{name}.yaml 의 검사 '{c}' 가 checks.py 에 없습니다")

    def test_env_public_secret_reports_key_name_only(self):
        value = "Zq9" + "notArealSecretValue"
        _w(os.path.join(self.t, ".env.production"),
           f"NEXT_PUBLIC_API_SECRET={value}\nexport VITE_AUTH_TOKEN=x\nNEXT_PUBLIC_SUPABASE_ANON_KEY=a\n"
           "VITE_STRIPE_PUBLISHABLE_KEY=pk\nDATABASE_PASSWORD=p\nNEXT_PUBLIC_SITE_URL=u\nNEXT_PUBLIC_OPENAI_API_KEY=k\n")
        report = self.run_checks()
        found = [(r["line"], r["severity"], r["category"]) for r in report["results"] if r["rule_id"] == "web.env-public-secret"]
        self.assertEqual(found, [(1, "high", "secret"), (2, "high", "secret"), (7, "medium", "config")])
        self.assertNotIn(value, json.dumps(report))   # 값은 결과에 넣지 않는다

    def test_public_env_name_rules(self):
        """PR #24 리뷰: 접두사를 뗀 나머지에서 단어 단위로 판정 (부분 문자열 오판 방지)"""
        cases = {"NEXT_PUBLIC_KEY_SECRET": "high", "NEXT_PUBLIC_CANONICAL_TOKEN": "high", "EXPO_PUBLIC_API_SECRET": "high",
                 "NEXT_PUBLIC_OPENAI_API_KEY": "medium", "VITE_API_KEY": "medium", "NEXT_PUBLIC_SUPABASE_SERVICE_ROLE_KEY": "high",
                 "NEXT_PUBLIC_SUPABASE_ANON_KEY": None, "NEXT_PUBLIC_MAPBOX_TOKEN": None, "NEXT_PUBLIC_FIREBASE_API_KEY": None,
                 "VITE_STRIPE_PUBLISHABLE_KEY": None, "NEXT_PUBLIC_RECAPTCHA_SITE_KEY": None, "NEXT_PUBLIC_SITE_URL": None,
                 "DATABASE_PASSWORD": None, "NEXT_PUBLIC_TOKENIZER_URL": None,
                 # 강한 단어는 공개용 조각과 함께 있어도 high (재리뷰)
                 "NEXT_PUBLIC_FIREBASE_PRIVATE_KEY": "high", "NEXT_PUBLIC_FIREBASE_ADMIN_CLIENT_SECRET": "high",
                 "NEXT_PUBLIC_SITE_ADMIN_PASSWORD": "high", "NEXT_PUBLIC_MAPBOX_SECRET_TOKEN": "high",
                 "NEXT_PUBLIC_PUBLIC_KEY_PASSWORD": "high", "VITE_SITE_TOKEN": "high"}
        for name, want in cases.items():
            self.assertEqual(checks.public_env_severity(name), want, name)

    def test_semgrep_public_env_rules_use_same_regex(self):
        """W2 의 두 구현(checks.py·Semgrep 규칙)이 같은 이름 규칙을 쓴다"""
        rules_dir = os.path.join(HERE, "..", "rules", "custom", "web")
        for fn, rxs in (("public-env-secret.yaml", (checks.PUBLIC_ENV_SECRET_RE, checks.PUBLIC_ENV_SECRET_BRACKET_RE)),
                        ("public-env-api-key.yaml", (checks.PUBLIC_ENV_KEY_RE, checks.PUBLIC_ENV_KEY_BRACKET_RE))):
            with open(os.path.join(rules_dir, fn), encoding="utf-8") as f:
                text = f.read()
            for rx in rxs:
                self.assertIn("regex: '" + rx.replace("'", "''") + "'", text, fn)

    def test_strip_js_comments(self):
        f = checks.strip_js_comments
        self.assertEqual(f("a // x\nb /* y\nz */ c"), "a \nb \n c")
        self.assertEqual(f("s = 'a//b' // c"), "s = 'a//b' ")
        self.assertEqual(f("t = `x ${y} // not comment`"), "t = `x ${y} // not comment`")
        self.assertEqual(f("e = 'it\\'s' // c"), "e = 'it\\'s' ")
        # 정규식 리터럴 안의 /* · ' 는 주석·문자열 시작이 아니다
        self.assertEqual(f("const re = /^\\/v1\\/*/\nexport function GET(){}"), "const re = /^\\/v1\\/*/\nexport function GET(){}")
        self.assertEqual(f("const q = /'/\n// auth()\n"), "const q = /'/\n\n")
        self.assertEqual(f("x = a / b // c"), "x = a / b ")                      # 나눗셈
        self.assertEqual(f("if (/[/]x/.test(s)) {} // c"), "if (/[/]x/.test(s)) {} ")
        # JSX 텍스트의 아포스트로피는 그 줄에서 끝난다
        self.assertEqual(f("<p>Don't</p>\n// auth()\n"), "<p>Don't</p>\n\n")
        # 닫히지 않은 블록 주석은 그대로 둔다
        self.assertEqual(f("a /* b\nexport function GET(){}"), "a /* b\nexport function GET(){}")

    def test_linear_time_per_input(self):
        """재리뷰: 검사별 악성 입력이 실제로 해당 코드를 거치고, 크기를 두 배로 늘려도 시간이 이차로 늘지 않는다"""
        cases = {
            ".env": lambda k: "\n" * (k * 100_000),
            "next.config.js": lambda k: "domains:[" * (k * 10_000),
            "pnpm-lock.yaml": lambda k: "lockfileVersion: '6.0'\npackages:\n" + ("  a@" + "1" * 3000 + "x\n") * (k * 30),
            "app/api/x/route.ts": lambda k: ("export{" + " " * 290 + "\n") * (k * 1500),
            "middleware.ts": lambda k: "export const config = { matcher: [" + "'a," * (k * 50_000) + "\n",
            "main.js": lambda k: ("x = a / b /'/ c\n/* " * (k * 20_000)),
        }
        for name, gen in cases.items():
            times = []
            for k in (1, 2):
                path = os.path.join(self.t, name)
                _w(path, gen(k))
                t0 = time.time()
                if name == "main.js":
                    checks.strip_js_comments(open(path, encoding="utf-8").read())
                else:
                    self.run_checks()
                times.append(time.time() - t0)
                os.remove(path)
            self.assertLess(times[1], max(times[0] * 3.5, 0.3), (name, times))

    def test_linear_time_on_adversarial_files(self):
        """PR #24 리뷰 CRITICAL: 1MB 가까운 악성 파일에서도 정규식이 선형 시간이어야 한다"""
        big = 900_000
        _w(os.path.join(self.t, ".env"), "\n" * big)
        _w(os.path.join(self.t, "next.config.js"), "domains:[" * (big // 9))
        _w(os.path.join(self.t, "pnpm-lock.yaml"), "lockfileVersion: '6.0'\npackages:\n  a@" + "1" * (big - 40) + "x\n")
        _w(os.path.join(self.t, "app/api/x/route.ts"), "export {" + " " * (big - 20) + "\n")
        _w(os.path.join(self.t, "middleware.ts"), "matcher: [" + "'" * (big // 2) + "\n")
        t0 = time.time()
        self.run_checks()
        self.assertLess(time.time() - t0, 5.0)

    def test_oversized_files_are_skipped(self):
        _w(os.path.join(self.t, ".env"), "NEXT_PUBLIC_A_SECRET=x\n" + "#" * checks.MAX_FILE)
        self.assertEqual(self.run_checks()["results"], [])

    def test_run_timeout_keeps_partial_results(self):
        defs = {"web": dict(self.defs["web"], checks=["next-config", "slow"])}
        _w(os.path.join(self.t, "next.config.js"), "module.exports = {}\n")
        checks.CHECKS["slow"] = lambda ctx: time.sleep(5) or []
        try:
            report = checks.run(self.t, [("web", ".", [])], defs, timeout=1)
        finally:
            del checks.CHECKS["slow"]
        self.assertTrue(any("시간 제한" in e for e in report["errors"]))
        self.assertTrue(any(r["rule_id"] == "web.next-config-no-security-headers" for r in report["results"]))

    def test_unauth_route_heuristic(self):
        _w(os.path.join(self.t, "app/api/open/route.ts"), "export async function POST(req) { return Response.json({}) }\n")
        _w(os.path.join(self.t, "app/api/route.ts"), "export const GET = () => Response.json({})\n")
        _w(os.path.join(self.t, "pages/api/arrow.js"), "export default async (req, res) => { res.end() }\n")
        _w(os.path.join(self.t, "pages/api/wrapped.js"), "const h = (req, res) => res.end()\nexport default withSentry(h)\n")
        _w(os.path.join(self.t, "app/api/db/route.ts"), "export async function GET() { const u = await getUser(1); return Response.json(u) }\n")
        _w(os.path.join(self.t, "app/api/c/route.ts"), "// TODO auth()\nexport async function GET() {}\n")
        _w(os.path.join(self.t, "app/api/sb/route.ts"), "export async function GET() { await supabase.auth.getUser() }\n")
        _w(os.path.join(self.t, "app/api/safe/route.ts"),
           "import { auth } from '@/auth'\nexport async function GET() { const s = await auth(); return Response.json(s) }\n")
        _w(os.path.join(self.t, "app/api/lib/helper.ts"), "export function GET() {}\n")   # route 파일 아님
        _w(os.path.join(self.t, "pages/api/old.js"), "export default function handler(req, res) { res.end() }\n")
        report = self.run_checks()
        hits = [r for r in report["results"] if r["rule_id"] == "web.next-unauth-route"]
        self.assertEqual(sorted(r["file"] for r in hits), [
            "app/api/c/route.ts", "app/api/db/route.ts", "app/api/open/route.ts", "app/api/route.ts",
            "pages/api/arrow.js", "pages/api/old.js", "pages/api/wrapped.js"])
        self.assertTrue(all(r["severity"] == "medium" for r in hits))

    def test_unauth_route_severity_follows_middleware_matcher(self):
        """PR #24 리뷰: 루트의 middleware(proxy) matcher 가 /api 를 덮을 때만 low"""
        _w(os.path.join(self.t, "app/api/open/route.ts"), "export async function GET() {}\n")
        cases = [
            ("middleware.ts", "export const config = { matcher: ['/api/:path*'] }\n", "low"),
            ("src/proxy.ts", "export function proxy() {}\n", "low"),                       # matcher 없음 = 전체
            ("middleware.ts", "export const config = { matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'] }\n", "medium"),
            ("middleware.ts", "import x from '@/lib/api-client'\nexport const config = { matcher: ['/dashboard/:path*'] }\n", "medium"),
            ("server/middleware.js", "module.exports = (req, res, next) => next()\n", "medium"),   # 루트 밖 Express 미들웨어
            ("middleware.ts", "// matcher: ['/api']\nexport const config = { matcher: ['/admin'] }\n", "medium"),
            # 재리뷰: matcher 배열 밖의 '/' · 가져온 matcher · 정규식 리터럴 뒤의 config
            ("middleware.ts", "export const config = { matcher: ['/dashboard/:path*'] }\nNextResponse.redirect(new URL('/', req.url))\n", "medium"),
            ("middleware.ts", "import { matcher } from './m'\nconst home = '/'\n", "medium"),
            ("middleware.ts", "if (/^\\/static\\/*/.test(p)) {}\nexport const config = { matcher: ['/admin'] }\n", "medium"),
            ("middleware.ts", "export const config = { matcher: '/api/:path*' }\n", "low"),
        ]
        for rel, text, want in cases:
            for old in ("middleware.ts", "src/proxy.ts", "server/middleware.js"):
                if os.path.exists(os.path.join(self.t, old)):
                    os.remove(os.path.join(self.t, old))
            _w(os.path.join(self.t, rel), text)
            (hit,) = [r for r in self.run_checks()["results"] if r["rule_id"] == "web.next-unauth-route"]
            self.assertEqual(hit["severity"], want, (rel, text))

    def test_next_config_ignores_comments_and_detects_url_form(self):
        _w(os.path.join(self.t, "next.config.ts"),
           "// headers: later\nexport default { images: { remotePatterns: [new URL('https://**/**')] } }\n")
        rules = {r["rule_id"] for r in self.run_checks()["results"]}
        self.assertIn("web.next-config-no-security-headers", rules)
        self.assertIn("web.next-config-wildcard-remote-image", rules)

    def test_next_config_checks(self):
        _w(os.path.join(self.t, "next.config.mjs"),
           "export default { async headers() { return [{ source: '/(.*)', headers: [{ key: 'Content-Security-Policy', value: \"default-src 'self'\" }] }] },\n"
           "  images: { remotePatterns: [{ hostname: '*' }] } }\n")
        rules = {r["rule_id"]: r for r in self.run_checks()["results"]}
        self.assertNotIn("web.next-config-no-security-headers", rules)
        self.assertIn("Strict-Transport-Security", rules["web.next-config-missing-security-headers"]["evidence"])
        self.assertIn("web.next-config-wildcard-remote-image", rules)
        self.assertNotIn("web.next-config-browser-sourcemaps", rules)

    def test_npm_install_scripts_package_lock_and_pnpm(self):
        _w(os.path.join(self.t, "package-lock.json"), json.dumps({"lockfileVersion": 3, "packages": {
            "": {"name": "x"}, "node_modules/esbuild": {"version": "0.18.20", "hasInstallScript": True},
            "node_modules/a/node_modules/@scope/b": {"version": "1.0.0", "hasInstallScript": True},
            "packages/app": {"version": "1.0.0", "hasInstallScript": True},          # 워크스페이스 자체 — 제외
            "node_modules/한글pkg": {"version": "1.0.0", "hasInstallScript": True},
            "node_modules/plain": {"version": "1.0.0"}}}, ensure_ascii=False, indent=1))
        _w(os.path.join(self.t, "v6/pnpm-lock.yaml"),
           "lockfileVersion: '6.0'\npackages:\n  /sharp@0.32.6:\n    resolution: {integrity: x}\n    requiresBuild: true\n"
           "  /@img/sharp-darwin@0.33.0(peer@1.0.0):\n    requiresBuild: true\n  /lodash@4.17.21:\n    resolution: {integrity: y}\n")
        _w(os.path.join(self.t, "v5/pnpm-lock.yaml"),
           "lockfileVersion: 5.4\npackages:\n  /esbuild/0.15.0:\n    requiresBuild: true\n"
           "  /styled-jsx/5.1.1_react@18.2.0:\n    requiresBuild: true\n  /@swc/core/1.3.0_@swc+helpers@0.5.0:\n    requiresBuild: true\n")
        _w(os.path.join(self.t, "v9/pnpm-lock.yaml"), "lockfileVersion: '9.0'\npackages:\n  esbuild@0.20.0:\n    resolution: {}\n")
        report = self.run_checks()
        hits = [r for r in report["results"] if r["rule_id"] == "web.npm-install-script"]
        self.assertEqual(sorted(r["package"] for r in hits), [
            "@img/sharp-darwin@0.33.0", "@scope/b@1.0.0", "@swc/core@1.3.0", "esbuild@0.15.0", "esbuild@0.18.20",
            "sharp@0.32.6", "styled-jsx@5.1.1", "한글pkg@1.0.0"])
        self.assertTrue(all(r["line"] for r in hits))
        self.assertTrue(any("v9/pnpm-lock.yaml" in w and "판별하지 못했습니다" in w for w in report["warnings"]))

    def test_truncation_is_reported(self):
        lock = {"lockfileVersion": 3, "packages": {f"node_modules/p{i}": {"version": "1.0.0", "hasInstallScript": True}
                                                   for i in range(checks.MAX_RESULTS_PER_CHECK + 5)}}
        _w(os.path.join(self.t, "package-lock.json"), json.dumps(lock))
        report = self.run_checks()
        self.assertEqual(len(report["results"]), checks.MAX_RESULTS_PER_CHECK)
        self.assertTrue(any("건만 리포트에 담았습니다" in w for w in report["warnings"]))

    def test_symlinks_are_not_followed_and_outside_files_not_read(self):
        outside = os.path.join(self.tmp.name, "outside")
        _w(os.path.join(outside, ".env"), "NEXT_PUBLIC_LEAK_SECRET=x\n")
        _w(os.path.join(outside, "next.config.js"), "module.exports = {}\n")
        os.symlink(os.path.join(outside, ".env"), os.path.join(self.t, ".env"))
        os.symlink(outside, os.path.join(self.t, "linked"))
        self.assertEqual(self.run_checks()["results"], [])

    def test_scoped_to_profile_root_and_excluded_subpaths(self):
        _w(os.path.join(self.t, "web/.env"), "NEXT_PUBLIC_A_SECRET=x\n")
        _w(os.path.join(self.t, "other/.env"), "NEXT_PUBLIC_B_SECRET=x\n")
        _w(os.path.join(self.t, "web/apps/mobile/.env"), "NEXT_PUBLIC_C_SECRET=x\n")
        _w(os.path.join(self.t, "web/node_modules/pkg/.env"), "NEXT_PUBLIC_D_SECRET=x\n")
        report = self.run_checks([("web", "web", ["web/apps/mobile"])])
        self.assertEqual([r["file"] for r in report["results"]], ["web/.env"])

    def test_unknown_check_and_check_exception_become_errors(self):
        defs = {"web": dict(self.defs["web"], checks=["nope", "next-config"])}
        _w(os.path.join(self.t, "next.config.js"), "module.exports = {}\n")
        orig = checks.CHECKS["next-config"]
        checks.CHECKS["next-config"] = lambda ctx: 1 / 0
        try:
            report = checks.run(self.t, [("web", ".", [])], defs)
        finally:
            checks.CHECKS["next-config"] = orig
        self.assertEqual(report["results"], [])
        self.assertTrue(any("알 수 없는 검사 'nope'" in e for e in report["errors"]))
        self.assertTrue(any("next-config: 검사 실패" in e for e in report["errors"]))

    def test_compose_checks(self):
        """S6 — privileged·docker.sock·DB 포트 (짧은·긴·흐름 문법, 루프백 제외, DB 아닌 서비스 제외)"""
        _w(os.path.join(self.t, "infra/docker-compose.prod.yml"),
           "services:\n  db:\n    image: \"postgres:16\"\n    ports:\n      - \"5432:5432\"\n      - 127.0.0.1:5433:5432\n"
           "      - target: 5432\n        published: 5434\n      - target: 5432\n        published: 5435\n        host_ip: 127.0.0.1\n"
           "  mongo:\n    image: mongo\n    ports: [\"27017:27017\"]\n  web:\n    image: nginx\n    privileged: true\n    ports:\n    - \"80:80\"\n"
           "    volumes:\n      - /var/run/docker.sock:/var/run/docker.sock:ro\n")
        report = self.run_checks([("server", "backend", [])])   # compose 는 저장소 전체를 본다
        got = sorted((r["rule_id"], r["line"]) for r in report["results"])
        self.assertEqual(got, [("server.compose-db-port-exposed", 5), ("server.compose-db-port-exposed", 7),
                               ("server.compose-db-port-exposed", 14), ("server.compose-docker-socket", 21),
                               ("server.compose-privileged", 17)])

    def test_repo_wide_check_runs_once(self):
        _w(os.path.join(self.t, "docker-compose.yml"), "services:\n  a:\n    privileged: true\n")
        report = self.run_checks([("server", "api", []), ("server", "worker", [])])
        self.assertEqual(len(report["results"]), 1)

    def test_spring_config_secret_reports_key_only(self):
        value = "Zq9" + "plaintextPw"
        _w(os.path.join(self.t, "api/src/main/resources/application-prod.yml"),
           f"spring:\n  datasource:\n    password: {value}\n    username: app\njwt:\n  secret: ${{JWT_SECRET}}\n"
           f"crypto:\n  token: '{{cipher}}abc'\n# api-key: commented\n")
        _w(os.path.join(self.t, "api/src/main/resources/application.properties"),
           f"app.api-key={value}\nother.secret=${{X}}\n! old.password=y\n")
        report = self.run_checks([("server", "api", [])])
        got = sorted((r["file"].rsplit("/", 1)[-1], r["line"], r["evidence"].split(" ")[1]) for r in report["results"])
        self.assertEqual(got, [("application-prod.yml", 3, "spring.datasource.password"),
                               ("application.properties", 1, "app.api-key")])
        self.assertNotIn(value, json.dumps(report))

    def test_compose_review_cases(self):
        """PR #25 리뷰 재현 사례 — 서비스 경계(주석·앵커), 흐름 문법, published 생략, - 다음 줄 키, True, docker.sock 범위, DB 판정"""
        _w(os.path.join(self.t, "compose.yaml"), "\n".join([
            "services:",
            "  db:",                                   # 2
            "    image: postgres",
            "  web:   # frontend",                     # 4 — 주석 붙은 서비스 키
            "    image: nginx",
            "    ports:",
            "      - \"80:80\"",                      # 7 — nginx 는 DB 아님
            "  pg: &pg",                               # 8 — 앵커 서비스
            "    image: bitnami/postgresql:16",
            "    ports:",
            "      - \"5432:5432\"",                  # 11 → 노출
            "  m:",
            "    image: mongo",
            "    ports: [\"27017:27017\"]  # db",      # 14 → 1건만
            "  r:",
            "    image: redis",
            "    ports: [{target: 6379, published: 6379, host_ip: 127.0.0.1}]",   # 17 → 루프백
            "  r2:",
            "    image: redis:7",
            "    ports: [",
            "      \"6380:6379\"",
            "    ]",                                   # 20 줄 시작 → 노출 (여러 줄 흐름)
            "  e:",
            "    image: elasticsearch:8",
            "    privileged: True",                    # 25 → privileged
            "    ports:",
            "      - target: 9200",                    # 27 → published 생략도 노출
            "      -",
            "        target: 9300",                    # 28 의 항목 → 노출
            "        published: 9300",
            "    environment:",
            "      DOCKER_HOST: unix:///var/run/docker.sock",   # 환경 변수 — 마운트 아님
            "  ui:",
            "    image: mongo-express",                # DB 아님
            "    ports:",
            "      - \"8081:8081\"",
            "    volumes:",
            "      - /var/run/docker.sock:/var/run/docker.sock:ro",   # 38 → docker.sock
            ""]))
        got = sorted((r["rule_id"].split(".")[1], r["line"]) for r in self.run_checks([("server", ".", [])])["results"])
        self.assertEqual(got, [("compose-db-port-exposed", 11), ("compose-db-port-exposed", 14),
                               ("compose-db-port-exposed", 20), ("compose-db-port-exposed", 27),
                               ("compose-db-port-exposed", 28), ("compose-docker-socket", 38),
                               ("compose-privileged", 25)])

    def test_compose_file_name_and_evidence(self):
        _w(os.path.join(self.t, "composer.yml"), "services:\n  a:\n    privileged: true\n")
        self.assertEqual(self.run_checks([("server", ".", [])])["results"], [])
        _w(os.path.join(self.t, "compose.prod.yml"), "services:\n  db:\n    image: postgres\n    ports: [\"5432:5432\"]\n")
        (r,) = self.run_checks([("server", ".", [])])["results"]
        self.assertIn("서비스 db, 포트 5432:5432", r["evidence"])

    def test_spring_review_cases(self):
        _w(os.path.join(self.t, "api/src/main/resources/application.yml"), "\n".join([
            "app:",
            "  require-password: true",                # 불리언 — 제외
            "  max-token: 100",                        # 숫자 — 제외
            "  password: &pw Zq9plain",                # 4 — 앵커 값
            "  db:",
            "    password: ${DB_PASSWORD:Zq9default}", # 6 — 자리표시자 기본값
            "    token: ${TOKEN}",                     # 자리표시자 — 제외
            "  props: |",
            "    db.password: inblock",                # 블록 스칼라 — 제외
            "  users:",
            "    - password: Zq9inlist",               # 11 — 리스트 항목
            "---",
            "  password: Zq9doc2",                     # 13 — 새 문서, 스택 초기화
            ""]))
        _w(os.path.join(self.t, "api/src/main/resources/application.properties"),
           "app.desc=hello \\\n  password=continued\napp.db\\.password=Zq9esc\napp.secret Zq9space\n")
        _w(os.path.join(self.t, "api/src/test/resources/application-test.yml"), "spring:\n  password: sa\n")
        rs = self.run_checks([("server", "api", [])])["results"]
        got = sorted((r["file"].rsplit("/", 1)[-1], r["line"], r["evidence"].split(" ")[1], r["severity"]) for r in rs)
        self.assertEqual(got, [
            ("application-test.yml", 2, "spring.password", "low"),
            ("application.properties", 3, "app.db.password", "high"),
            ("application.properties", 4, "app.secret", "high"),
            ("application.yml", 4, "app.password", "high"),
            ("application.yml", 6, "app.db.password", "high"),
            ("application.yml", 11, "app.users.password", "high"),
            ("application.yml", 13, "password", "high")])
        self.assertTrue(any("자리표시자의 기본값" in r["evidence"] for r in rs))
        for v in ("Zq9plain", "Zq9default", "Zq9inlist", "Zq9doc2", "Zq9esc", "Zq9space"):
            self.assertNotIn(v, json.dumps(rs))

    def test_compose_rereview_cases(self):
        """PR #25 재리뷰: volumes 긴·흐름 문법 docker.sock, ports ${VAR}·!override, DB 이미지 추가·${VAR:-기본값}, 하위 매핑 무시"""
        _w(os.path.join(self.t, "docker-compose.yml"), "\n".join([
            "services:",
            "  a:",
            "    image: alpine",
            "    volumes:",
            "      - type: bind",                          # 5 → 긴 문법 docker.sock
            "        source: /var/run/docker.sock",
            "        target: /var/run/docker.sock",
            "  b:",
            "    image: alpine",
            "    volumes: [\"/var/run/docker.sock:/var/run/docker.sock\"]",   # 10
            "  c:",
            "    image: alpine",
            "    volumes: [",                              # 13 → 여러 줄 흐름
            "      \"/var/run/docker.sock:/s\"",
            "    ]",
            "  db:",
            "    image: mysql/mysql-server:8.0",
            "    ports:",
            "      - ${DB_PORT:-3306}:3306",                # 19
            "  pg:",
            "    image: ${PG_IMAGE:-postgres:16}",
            "    ports: !override",
            "      - \"5432:5432\"",                       # 23
            "  web:",
            "    image: postgres",
            "    labels:",
            "      ports: \"[5432]\"",                     # 하위 매핑 — 무시
            ""]))
        got = sorted((r["rule_id"].split(".")[1], r["line"]) for r in self.run_checks([("server", ".", [])])["results"])
        self.assertEqual(got, [("compose-db-port-exposed", 19), ("compose-db-port-exposed", 23),
                               ("compose-docker-socket", 5), ("compose-docker-socket", 10), ("compose-docker-socket", 13)])

    def test_spring_rereview_cases(self):
        _w(os.path.join(self.t, "api/src/main/resources/application.yml"),
           "spring:\n  datasource:\n    password: 1234\napp:\n  password: '*Zq9star'\n  token: '|Zq9pipe'\n  alias: *ref\n")
        _w(os.path.join(self.t, "api/src/main/resources/application.properties"),
           "spring.datasource.password=1234\napp.x=" + "a" * 4100 + "\\\n  password=continued\n")
        _w(os.path.join(self.t, "api/src/integrationTest/resources/application.yml"), "spring:\n  password: sa\n")
        got = sorted((r["file"].split("/")[-3] + "/" + r["file"].rsplit("/", 1)[-1], r["line"], r["severity"])
                     for r in self.run_checks([("server", "api", [])])["results"])
        self.assertEqual(got, [("integrationTest/application.yml", 2, "low"),
                               ("main/application.properties", 1, "high"),
                               ("main/application.yml", 3, "high"),
                               ("main/application.yml", 5, "high"),
                               ("main/application.yml", 6, "high")])

    def test_server_line_length_is_linear(self):
        """PR #25 재리뷰: 줄 길이에 대한 이차는 줄 수 비율로 안 보인다 — 같은 줄 수에서 줄 길이를 2배로 늘려 비교"""
        def compose(pad):
            return "services:\n" + "".join(f"  s{i}:{pad}x\n    image: a\n" for i in range(100))
        def compose_tab(pad):
            return "services:\n" + "".join(f"  s{i}:{pad.replace(' ', chr(9))}x\n    image: a\n" for i in range(100))
        def yml(pad):
            return "".join(f"password:{pad}v\n" for _ in range(100))
        for name, gen in (("docker-compose.yml", compose), ("compose.yaml", compose_tab), ("api/application.yml", yml)):
            times = []
            for width in (1900, 3800):
                path = os.path.join(self.t, name)
                _w(path, gen(" " * width))
                t0 = time.time()
                self.run_checks([("server", "api", [])])
                times.append(time.time() - t0)
                os.remove(path)
            self.assertLess(times[1], max(times[0] * 3.0, 0.3), (name, times))

    def test_server_checks_linear_time_per_input(self):
        """PR #25 리뷰: 악성 입력이 실제로 해당 코드를 거치고(결과 1건 이상), 크기를 두 배로 늘려도 이차로 늘지 않는다"""
        pad = " " * 3900
        cases = {
            "api/application.yml": lambda k: ("password: a" + pad + "b\n") * (k * 120),
            "docker-compose.yml": lambda k: "services:\n  db:\n    image: postgres\n    ports:\n" + ("      - a" + pad + "b\n") * (k * 120),
            "compose.yaml": lambda k: "services:\n" + "".join(f"  s{i}:\n    image: a{pad}b\n    privileged: true\n" for i in range(k * 120)),
            "api/application.properties": lambda k: ("app.password=a" + pad + "b\n") * (k * 120),
        }
        for name, gen in cases.items():
            times = []
            for k in (1, 2):
                path = os.path.join(self.t, name)
                _w(path, gen(k))
                t0 = time.time()
                rs = self.run_checks([("server", "api", [])])["results"]
                times.append(time.time() - t0)
                self.assertTrue(rs, name)          # 경로를 실제로 거쳤는지
                os.remove(path)
            self.assertLess(times[1], max(times[0] * 3.5, 0.5), (name, times))
            # 줄 길이에 대한 이차(이전 `\\s+#.*$`: 이 입력에서 4초 이상)는 줄 수 비율로는 안 보이므로 절대 상한도 둔다
            self.assertLess(times[1], 1.5, (name, times))

    def test_server_fixture_expectations(self):
        import shutil
        fx = os.path.join(HERE, "fixtures", "server")
        shutil.copytree(fx, self.t, dirs_exist_ok=True)
        shutil.move(os.path.join(self.t, "requirements.txt.fixture"), os.path.join(self.t, "web", "requirements.txt"))
        detected = profiles.detect_full(self.t, self.defs)
        self.assertEqual(sorted((n, r) for n, r, _ in detected), [("server", "api"), ("server", "gosvc"), ("server", "web")])
        self.assertEqual(self.rules(checks.run(self.t, detected, self.defs)), [
            ("server.compose-db-port-exposed", "docker-compose.yml"),
            ("server.compose-docker-socket", "docker-compose.yml"),
            ("server.compose-privileged", "docker-compose.yml"),
            ("server.config-plaintext-secret", "api/src/main/resources/application.yml"),
        ])

    def test_android_manifest_and_nsc(self):
        _w(os.path.join(self.t, "app/src/main/AndroidManifest.xml"), """<?xml version="1.0"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
  <application android:allowBackup="false" android:networkSecurityConfig="@xml/nsc">
    <activity android:name=".Main" android:exported="true">
      <intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter>
    </activity>
    <activity android:name=".Deep" android:exported="true"/>
    <service android:name=".S" android:exported="true" android:permission="x.P"/>
    <receiver android:name=".R" android:exported="false"/>
  </application>
</manifest>
""")
        _w(os.path.join(self.t, "app/src/main/res/xml/nsc.xml"),
           '<network-security-config><domain-config cleartextTrafficPermitted="true"><domain>10.0.2.2</domain></domain-config>'
           '<debug-overrides><trust-anchors><certificates src="system"/></trust-anchors></debug-overrides></network-security-config>')
        got = sorted((r["rule_id"], r["severity"], r["evidence"]) for r in self.run_checks([("android", ".", [])])["results"])
        self.assertEqual([(a, b) for a, b, _ in got], [("android.manifest-exported-component", "high"), ("android.nsc-cleartext", "medium")])
        self.assertIn(".Deep", got[0][2])

    def test_android_xml_with_doctype_is_refused(self):
        _w(os.path.join(self.t, "AndroidManifest.xml"),
           '<?xml version="1.0"?><!DOCTYPE m [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><manifest><application/></manifest>')
        report = self.run_checks([("android", ".", [])])
        self.assertEqual(report["results"], [])
        self.assertTrue(any("DOCTYPE" in w for w in report["warnings"]))

    def test_android_gradle_release(self):
        _w(os.path.join(self.t, "a/build.gradle.kts"),
           'plugins { id("com.android.application") }\nandroid { buildTypes { getByName("release") { isMinifyEnabled = true } } }\n')
        _w(os.path.join(self.t, "b/build.gradle"),
           "plugins { id 'com.android.application' }\nandroid {\n  buildTypes {\n    debug { minifyEnabled true }\n  }\n}\n")
        _w(os.path.join(self.t, "c/build.gradle"),
           "plugins { id 'com.android.library' }\nandroid { buildTypes { release { minifyEnabled false } } }\n")   # 라이브러리 — 대상 아님
        _w(os.path.join(self.t, "d/build.gradle"),
           "plugins { id 'com.android.application' }\nandroid { buildTypes { release {\n // minifyEnabled true\n minifyEnabled false } } }\n")
        got = sorted((r["file"], r["evidence"][:14]) for r in self.run_checks([("android", ".", [])])["results"])
        self.assertEqual(got, [("b/build.gradle", "release 빌드 타입이"), ("d/build.gradle", "release 빌드 타입에")])

    def test_android_properties_secret(self):
        value = "Zq9" + "storepw"
        _w(os.path.join(self.t, "gradle.properties"),
           f"org.gradle.jvmargs=-Xmx2g\nRELEASE_STORE_PASSWORD={value}\nKEY_PASSWORD=${{KEY_PW}}\nandroid.enableR8=true\n"
           "KEYSTORE_PASSWORD=123456\n")
        _w(os.path.join(self.t, "local.properties"), "sdk.dir=/Users/x/Library/Android/sdk\nMAPS_API_KEY=" + value + "\n")
        rs = self.run_checks([("android", ".", [])])["results"]
        self.assertEqual(sorted((r["file"], r["line"]) for r in rs),
                         [("gradle.properties", 2), ("gradle.properties", 5), ("local.properties", 2)])   # 숫자 비밀번호도
        self.assertNotIn(value, json.dumps(rs))

    def test_android_checks_line_length_is_linear(self):
        """S-Server 리뷰 교훈: 줄 길이를 2배로 늘려도 시간이 이차로 늘지 않는다 (해당 경로를 거치는지 결과로 확인)"""
        def gradle(pad):
            body = "".join(f"minifyEnabled{pad}x\n" for _ in range(150))
            return "plugins { id 'com.android.application' }\nandroid { buildTypes { release {\n" + body + "} } }\n"
        def props(pad):
            return "".join(f"STORE_PASSWORD={pad}v\n" for _ in range(150))
        for name, gen in (("app/build.gradle", gradle), ("gradle.properties", props)):
            times = []
            for width in (1900, 3800):
                path = os.path.join(self.t, name)
                _w(path, gen(" " * width))
                t0 = time.time()
                rs = self.run_checks([("android", ".", [])])["results"]
                times.append(time.time() - t0)
                self.assertTrue(rs, name)
                os.remove(path)
            self.assertLess(times[1], max(times[0] * 3.0, 0.3), (name, times))

    def test_android_fixture_expectations(self):
        import shutil
        shutil.copytree(os.path.join(HERE, "fixtures", "android"), self.t, dirs_exist_ok=True)
        detected = profiles.detect_full(self.t, self.defs)
        self.assertEqual([(n, r) for n, r, _ in detected], [("android", ".")])
        report = checks.run(self.t, detected, self.defs)
        self.assertEqual(report["errors"], [])
        self.assertEqual(self.rules(report), [
            ("android.gradle-release-minify-disabled", "app/build.gradle"),
            ("android.manifest-allow-backup", "app/src/main/AndroidManifest.xml"),
            ("android.manifest-cleartext", "app/src/main/AndroidManifest.xml"),
            ("android.manifest-debuggable", "app/src/main/AndroidManifest.xml"),
            ("android.manifest-exported-component", "app/src/main/AndroidManifest.xml"),
            ("android.manifest-exported-component", "app/src/main/AndroidManifest.xml"),
            ("android.nsc-cleartext", "app/src/main/res/xml/network_security_config.xml"),
            ("android.nsc-user-certs", "app/src/main/res/xml/network_security_config.xml"),
            ("android.properties-secret", "gradle.properties"),
        ])

    def test_ios_ats_xml_and_binary_plist(self):
        import plistlib
        conf = {"NSAppTransportSecurity": {"NSAllowsArbitraryLoadsInWebContent": True, "NSExceptionDomains": {
            "a.example.com": {"NSTemporaryExceptionAllowsInsecureHTTPLoads": True},
            "b.example.com": {"NSExceptionMinimumTLSVersion": "TLSv1.2"}}}}
        os.makedirs(os.path.join(self.t, "App"), exist_ok=True)
        with open(os.path.join(self.t, "App/Info.plist"), "wb") as f:
            f.write(plistlib.dumps(conf, fmt=plistlib.FMT_BINARY))
        with open(os.path.join(self.t, "App/Ext-Info.plist"), "wb") as f:
            f.write(plistlib.dumps({"NSAppTransportSecurity": {"NSAllowsArbitraryLoads": False}}))
        got = sorted((r["file"], r["rule_id"]) for r in self.run_checks([("ios", ".", [])])["results"])
        self.assertEqual(got, [("App/Info.plist", "ios.ats-arbitrary-loads-partial"),
                               ("App/Info.plist", "ios.ats-insecure-http-exception")])

    def test_ios_plist_entity_declaration_is_refused(self):
        _w(os.path.join(self.t, "Info.plist"), '<?xml version="1.0"?><!DOCTYPE plist [<!ENTITY a "x">]>'
           '<plist><dict><key>NSAppTransportSecurity</key><dict><key>NSAllowsArbitraryLoads</key><true/></dict></dict></plist>')
        report = self.run_checks([("ios", ".", [])])
        self.assertEqual(report["results"], [])
        self.assertTrue(any("plist 를 해석하지 못했습니다" in w for w in report["warnings"]))

    def test_ios_xcconfig_secret(self):
        value = "Zq9" + "xcsecret"
        _w(os.path.join(self.t, "Config/Release.xcconfig"),
           f"API_URL = https:/$()/x.example.com\nAPI_TOKEN = {value} // 주석\nCLIENT_SECRET = $(INHERITED_SECRET)\n"
           f"// OLD_SECRET = {value}\nSWIFT_VERSION = 5.0\nSIGN_PASSWORD[config=Release] = {value}\n")
        rs = self.run_checks([("ios", ".", [])])["results"]
        self.assertEqual([(r["line"], r["evidence"].split(" ")[1]) for r in rs], [(2, "API_TOKEN"), (6, "SIGN_PASSWORD")])
        self.assertNotIn(value, json.dumps(rs))

    def test_ios_fixture_expectations(self):
        import shutil
        shutil.copytree(os.path.join(HERE, "fixtures", "ios"), self.t, dirs_exist_ok=True)
        detected = profiles.detect_full(self.t, self.defs)
        self.assertEqual([(n, r) for n, r, _ in detected], [("ios", ".")])
        report = checks.run(self.t, detected, self.defs)
        self.assertEqual(report["errors"], [])
        self.assertEqual(self.rules(report), [
            ("ios.ats-arbitrary-loads", "App/Info.plist"),
            ("ios.ats-insecure-http-exception", "App/Info.plist"),
            ("ios.ats-weak-tls", "App/Info.plist"),
            ("ios.xcconfig-secret", "App/Config.xcconfig"),
        ])

    def test_web_fixture_expectations(self):
        """tests/fixtures/web 의 README 표와 같은 결과 (env·lockfile 은 테스트에서 실제 이름으로 복사)"""
        import shutil
        shutil.copytree(FIXTURE, self.t, dirs_exist_ok=True)
        shutil.copy(os.path.join(FIXTURE, "env.fixture"), os.path.join(self.t, ".env"))
        shutil.copy(os.path.join(FIXTURE, "package-lock.json.fixture"), os.path.join(self.t, "package-lock.json"))
        report = self.run_checks()
        self.assertEqual(report["errors"], [])      # 검사 예외는 결과가 비는 것으로만 드러나므로 따로 확인한다
        self.assertEqual(self.rules(report), [
            ("web.env-public-secret", ".env"),
            ("web.next-config-browser-sourcemaps", "next.config.js"),
            ("web.next-config-no-security-headers", "next.config.js"),
            ("web.next-config-wildcard-remote-image", "next.config.js"),
            ("web.next-unauth-route", "app/api/proxy/route.ts"),
            ("web.next-unauth-route", "app/api/search/route.ts"),
            ("web.next-unauth-route", "pages/api/legacy.js"),
            ("web.npm-install-script", "package-lock.json"),
        ])


if __name__ == "__main__":
    unittest.main()
