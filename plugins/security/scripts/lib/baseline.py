"""베이스라인 비교 — 같은 종류·같은 대상의 직전 실행과 결과를 비교해 신규·유지·해결을 표시한다 (P4, 리포트 포맷).

거짓 '해결'·'신규'를 줄이는 규칙 (PR #40 리뷰 W1~W3):
- 두 실행 모두에서 **완전했던 단위**(status.tsv 의 도구가 ok, 결과 파일 해석 성공, 부분 오류·결과 상한 없음 — complete_units)만 비교한다.
- 단위마다 **비교 키**(id 계산 버전·플러그인 버전·이미지 digest·Semgrep 규칙 커밋·프로파일)를 남기고, 키가 다르면 비교하지 않는다
  — 규칙·도구·파서가 바뀌면 코드와 무관하게 결과가 생기거나 사라진다.
- id 에 줄 번호가 들어 있어 위치만 바뀐 결과는 id 가 달라진다. 정확히 같은 id 를 맞춘 뒤 남은 신규·해결을
  (단위, 규칙, 파일, 패키지)별로 짝지어 '위치 이동'으로 센다.
이전 실행의 findings.json 은 도구가 대상에서 뽑은 데이터가 든 파일이다 — 형식을 검증하고 짧은 식별자만 꺼낸다.
"""

import hashlib
import json
import os
import stat

import cleanup_reports as _runs

RESOLVED_MAX = 50
SEVERITIES = ("critical", "high", "medium", "low", "info")
MAX_FILE = 64 * 1024 * 1024
ID_VERSION = 1      # normalize.finding_id 의 입력이 바뀌면 올린다 — 다르면 비교하지 않는다 (리뷰 S6)
# 단위 → 이미지 이름(images.lock). checks 는 툴킷 자체 검사라 플러그인 버전이 곧 도구 버전이다
UNIT_TOOL = {"semgrep": "semgrep", "gitleaks-git": "gitleaks", "gitleaks-dir": "gitleaks", "osv-scanner": "osv-scanner",
             "checks": None, "mobsf": "mobsf", "gitleaks-artifact": "gitleaks", "zap": "zap"}


def unit_keys(units, tools, rules, profiles, plugin_version):
    """단위별 비교 키. OSV DB 날짜는 넣지 않는다 — DB 갱신으로 새 취약점이 '신규'로 보이는 것은 의도한 동작이다."""
    digest = {t.get("name"): t.get("digest") for t in tools or [] if isinstance(t, dict)}
    commits = sorted(f"{r.get('name')}@{r.get('commit')}" for r in rules or [] if isinstance(r, dict))
    out = {}
    for u in units:
        parts = [f"id={ID_VERSION}", f"plugin={plugin_version}"]
        if UNIT_TOOL.get(u):
            parts.append(f"image={digest.get(UNIT_TOOL[u])}")
        if u in ("semgrep", "checks"):
            parts.append("profiles=" + ",".join(sorted(str(p) for p in profiles or [])))
        if u == "semgrep":
            parts += commits
        out[u] = hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]
    return out


def _load(path):
    """링크·큰 파일은 읽지 않는다 — 연 파일 자체를 확인한다 (리뷰 N2)."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FILE:
            return None
        with os.fdopen(fd, encoding="utf-8") as f:
            fd = None
            return json.load(f)
    except (OSError, ValueError):
        return None
    finally:
        if fd is not None:
            os.close(fd)


def _order(name):
    """같은 초의 접미사(-2 … -1000)를 숫자로 비교한다 ('-10' 이 '-9' 보다 뒤, 리뷰 N1)."""
    t = _runs.run_time(name)
    parts = name.split("-")
    return (t, int(parts[3]) if len(parts) > 3 else 1)


def find_previous(run_dir, kind, target):
    """(run_id, meta, findings) — 같은 종류·대상의 가장 최근 이전 실행. 없으면 None.
    meta 에 complete_units·unit_keys 가 없으면(이전 버전 리포트) findings 는 None 으로 돌려준다."""
    reports, me = os.path.split(os.path.normpath(run_dir))
    if _runs.run_time(me) is None:
        return None
    try:
        names = os.listdir(reports)
    except OSError:
        return None
    mine = _order(me)
    cands = sorted((n for n in names if _runs.run_time(n) is not None and n.split("-")[2] == kind and _order(n) < mine),
                   key=_order)
    for name in reversed(cands):
        d = os.path.join(reports, name)
        try:
            if not stat.S_ISDIR(os.lstat(d).st_mode):
                continue
        except OSError:
            continue
        meta = _load(os.path.join(d, "meta.json"))
        if not isinstance(meta, dict) or meta.get("kind") != kind or meta.get("target") != target:
            continue
        if not isinstance(meta.get("complete_units"), list) or not isinstance(meta.get("unit_keys"), dict):
            return name, meta, None
        rep = _load(os.path.join(d, "findings.json"))
        if not isinstance(rep, dict) or not isinstance(rep.get("findings"), list):
            return name, meta, None
        return name, meta, rep["findings"]
    return None


def _brief(f):
    loc = f.get("location") if isinstance(f.get("location"), dict) else {}
    sev = f.get("severity") if f.get("severity") in SEVERITIES else "info"
    return {"id": str(f.get("id", ""))[:64], "severity": sev, "tool": str(f.get("tool", ""))[:40],
            "rule_id": str(f.get("rule_id", ""))[:200],
            "location": {k: (str(loc[k])[:300] if loc.get(k) is not None else None) for k in ("file", "line", "url", "package")}}


def _move_key(f):
    loc = f.get("location") if isinstance(f.get("location"), dict) else {}
    return (f.get("unit"), str(f.get("rule_id")), str(loc.get("file") or loc.get("url")), str(loc.get("package")))


def compare(findings, complete_units, keys, prev):
    """findings 에 'baseline'(new|existing|moved|not-compared)을 붙이고 meta 용 요약을 돌려준다."""
    def none(run_id, reason):
        for f in findings:
            f["baseline"] = "not-compared"
        return {"run_id": run_id, "reason": reason}

    if prev is None:
        return none(None, "같은 대상의 이전 실행이 없습니다(또는 보관 기간이 지나 지워졌습니다)")
    name, meta, prev_findings = prev
    if prev_findings is None:
        return none(name, "이전 실행이 비교 정보가 없는 이전 버전 리포트이거나 읽을 수 없습니다")
    prev_complete = {u for u in meta["complete_units"] if u in UNIT_TOOL}
    both = set(complete_units) & prev_complete
    changed = {u for u in both if meta["unit_keys"].get(u) != keys.get(u)}
    comparable = both - changed
    prev_ids = {}
    for f in prev_findings:
        if isinstance(f, dict) and f.get("unit") in comparable and isinstance(f.get("id"), str):
            prev_ids.setdefault(f["id"], f)
    cur_ids, new = set(), []
    for f in findings:
        if f.get("unit") in comparable:
            cur_ids.add(f["id"])
            if f["id"] in prev_ids:
                f["baseline"] = "existing"
            else:
                f["baseline"] = "new"
                new.append(f)
        else:
            f["baseline"] = "not-compared"
    gone = [f for i, f in prev_ids.items() if i not in cur_ids]
    # 위치만 바뀐 결과 — 같은 (단위, 규칙, 파일, 패키지)에 남은 신규와 해결을 개수만큼 짝짓는다 (리뷰 W2)
    pool = {}
    for f in gone:
        pool.setdefault(_move_key(f), []).append(f)
    for f in new:
        bucket = pool.get(_move_key(f))
        if bucket:
            bucket.pop()
            f["baseline"] = "moved"
    gone = [f for b in pool.values() for f in b]
    counts = {k: sum(1 for f in findings if f["baseline"] == k) for k in ("new", "existing", "moved", "not-compared")}
    order = {s: i for i, s in enumerate(SEVERITIES)}
    resolved = sorted((_brief(f) for f in gone), key=lambda b: (order[b["severity"]], b["tool"], b["location"].get("file") or ""))
    units = set(complete_units) | prev_complete
    return {"run_id": name, "compared_units": sorted(comparable), "changed_units": sorted(changed),
            "not_compared_units": sorted(units - both), "new": counts["new"], "existing": counts["existing"],
            "moved": counts["moved"], "not_compared": counts["not-compared"],
            "resolved": len(resolved), "resolved_items": resolved[:RESOLVED_MAX]}
