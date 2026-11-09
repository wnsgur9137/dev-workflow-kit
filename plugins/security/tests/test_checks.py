"""checks.py 단위 테스트 — 스택별 커스텀 검사 (S-Web: W2 .env 키, W4 인증 없는 라우트, W6 next.config, W8 설치 스크립트)."""

import json
import os
import sys
import tempfile
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

    def run_checks(self, detected=(("web", ".", []),)):
        return checks.run(self.t, list(detected), self.defs)

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
           "VITE_STRIPE_PUBLISHABLE_KEY=pk\nDATABASE_PASSWORD=p\nNEXT_PUBLIC_SITE_URL=u\n")
        report = self.run_checks()
        found = [r for r in report["results"] if r["rule_id"] == "web.env-public-secret"]
        self.assertEqual([r["line"] for r in found], [1, 2])
        self.assertTrue(all(r["severity"] == "high" and r["category"] == "secret" for r in found))
        self.assertNotIn(value, json.dumps(report))   # 값은 결과에 넣지 않는다

    def test_unauth_route_heuristic(self):
        _w(os.path.join(self.t, "app/api/open/route.ts"), "export async function POST(req) { return Response.json({}) }\n")
        _w(os.path.join(self.t, "app/api/safe/route.ts"),
           "import { auth } from '@/auth'\nexport async function GET() { const s = await auth(); return Response.json(s) }\n")
        _w(os.path.join(self.t, "app/api/lib/helper.ts"), "export function GET() {}\n")   # route 파일 아님
        _w(os.path.join(self.t, "pages/api/old.js"), "export default function handler(req, res) { res.end() }\n")
        report = self.run_checks()
        hits = [r for r in report["results"] if r["rule_id"] == "web.next-unauth-route"]
        self.assertEqual(sorted(r["file"] for r in hits), ["app/api/open/route.ts", "pages/api/old.js"])
        self.assertTrue(all(r["severity"] == "medium" for r in hits))

    def test_unauth_route_is_lowered_when_middleware_covers_api(self):
        _w(os.path.join(self.t, "app/api/open/route.ts"), "export async function GET() {}\n")
        _w(os.path.join(self.t, "middleware.ts"), "export const config = { matcher: ['/api/:path*'] }\n")
        (hit,) = [r for r in self.run_checks()["results"] if r["rule_id"] == "web.next-unauth-route"]
        self.assertEqual(hit["severity"], "low")

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
            "node_modules/plain": {"version": "1.0.0"}}}))
        _w(os.path.join(self.t, "sub/pnpm-lock.yaml"),
           "lockfileVersion: '6.0'\npackages:\n  /sharp@0.32.6:\n    resolution: {integrity: x}\n    requiresBuild: true\n"
           "  /lodash@4.17.21:\n    resolution: {integrity: y}\n")
        pkgs = sorted(r["package"] for r in self.run_checks()["results"] if r["rule_id"] == "web.npm-install-script")
        self.assertEqual(pkgs, ["@scope/b@1.0.0", "esbuild@0.18.20", "sharp@0.32.6"])

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

    def test_web_fixture_expectations(self):
        """tests/fixtures/web 의 README 표와 같은 결과 (env·lockfile 은 테스트에서 실제 이름으로 복사)"""
        import shutil
        shutil.copytree(FIXTURE, self.t, dirs_exist_ok=True)
        shutil.copy(os.path.join(FIXTURE, "env.fixture"), os.path.join(self.t, ".env"))
        shutil.copy(os.path.join(FIXTURE, "package-lock.json.fixture"), os.path.join(self.t, "package-lock.json"))
        self.assertEqual(self.rules(self.run_checks()), [
            ("web.env-public-secret", ".env"),
            ("web.next-config-browser-sourcemaps", "next.config.js"),
            ("web.next-config-no-security-headers", "next.config.js"),
            ("web.next-config-wildcard-remote-image", "next.config.js"),
            ("web.next-unauth-route", "app/api/proxy/route.ts"),
            ("web.next-unauth-route", "pages/api/legacy.js"),
            ("web.npm-install-script", "package-lock.json"),
        ])


if __name__ == "__main__":
    unittest.main()
