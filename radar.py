#!/usr/bin/env python3
"""Job Radar v2: company career sites first.

Usage: python radar.py [--dry-run] [--only fast,workday,wide,topup] [--max-boards N]
"""
import hashlib, json, re, sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import math, random, time
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from jr import filters, lists, notify, platforms, sources, wide
from jr.common import ET, NOW, NotFound, age_hours, iso, to_lines

ROOT = Path(__file__).parent
JOBS, DESC, STATE = ROOT / "docs/jobs.json", ROOT / "docs/desc.json", ROOT / "data/state.json"
STAMP = NOW.isoformat(timespec="seconds")
ARGS = sys.argv[1:]


def arg(name, default=None):
    return ARGS[ARGS.index(name) + 1] if name in ARGS and ARGS.index(name) + 1 < len(ARGS) else default


def load(p, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def read_list(p):
    return [l.strip() for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def bucket(s, n):
    return int(hashlib.md5(s.encode()).hexdigest()[:8], 16) % n


def slot_due(times, last_iso, now_et):
    """True if a scheduled time of day has passed today (ET) and we have not run since it."""
    last = datetime.fromisoformat(last_iso).astimezone(ET) if last_iso else None
    for t in times:
        h, m = map(int, t.split(":"))
        s = now_et.replace(hour=h, minute=m, second=0, microsecond=0)
        if now_et >= s and (last is None or last < s):
            return True
    return False


def norm(s):
    return re.sub(r"\W+", "", (s or "").lower())


def show_loc(locs):
    seen, out = set(), []
    for t, c in locs:
        t = t or c
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[0] + (f" (+{len(out) - 1} more)" if len(out) > 1 else "") if out else ""


class Radar:
    def __init__(self):
        self.cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
        self.titles = filters.Titles(self.cfg)
        self.state = load(STATE, {})
        self.state.setdefault("dead", {})
        self.state.setdefault("seen", {})
        self.state["run"] = self.state.get("run", 0) + 1
        rules = hashlib.md5((ROOT / "config.yaml").read_bytes() + (ROOT / "jr/filters.py").read_bytes()).hexdigest()
        if self.state.get("rules") != rules:          # rules changed: postings rejected under the old rules get a fresh look
            self.state["seen"], self.state["rules"] = {}, rules
        self.applied = {a["id"] for a in load(ROOT / "docs/applied.json", []) if isinstance(a, dict) and a.get("id")}
        self.jobs = {j["id"]: j for j in load(JOBS, {}).get("jobs", []) if j.get("v") == 2}
        self.desc = load(DESC, {})
        self.report, self.cands, self.present = [], [], {}
        self.max_boards = int(arg("--max-boards", 0) or 0)
        self.now_et = NOW.astimezone(ET)

    # ---------- stage 1: read boards ----------
    def _read(self, ats, board, terms=None):
        try:
            if ats == "workday":
                cs, ids = sources.workday(board, terms or self.cfg["workday_terms"], self.titles.ok)
            elif ats in sources.SEARCH:
                cs, ids = sources.SEARCH[ats](board, terms or self.cfg["search_terms"], self.titles.ok)
            else:
                cs, ids = sources.SIMPLE[ats](board)
            return ats, board, "ok", [c for c in cs if self.titles.ok(c["title"])], ids, len(cs)
        except NotFound:
            return ats, board, "404", [], None, 0
        except Exception as ex:
            return ats, board, f"{type(ex).__name__}: {str(ex)[:40]}", [], None, 0

    def scan(self, ats, boards, workers, total=None, terms=None, label=None):
        boards = [b for b in boards if self.state["dead"].get(f"{ats}/{b}", 0) < 3]
        if self.max_boards:
            boards = boards[: self.max_boards]
        st, hits = Counter(), set()
        random.shuffle(boards)                         # if time runs out, a different part is left for next time
        deadline = time.time() + self.cfg.get("system_seconds", 420)
        ex = ThreadPoolExecutor(workers)
        futs = [ex.submit(self._read, ats, b, terms) for b in boards]
        try:
            for f in as_completed(futs, timeout=max(1, deadline - time.time())):
                a, b, status, cs, ids, n = f.result()
                if "429" in status:
                    st["throttled"] += 1
                    if st["throttled"] >= 8:           # the system asks us to slow down: stop for this round
                        break
                key = f"{a}/{b}"
                if status == "ok":
                    st["ok"] += 1; st["jobs"] += n; st["match"] += len(cs)
                    if cs:
                        hits.add(b)
                    self.state["dead"].pop(key, None)
                    if cs and cs[0].get("nodate"):          # undated system: on a company's first read, age is unknown
                        known = self.state.setdefault("nodate_boards", [])
                        if key not in known:
                            known.append(key)
                            for c in cs:
                                c["newboard"] = True
                    self.cands.extend(cs)
                    if ids is not None:
                        self.present[key] = ids
                elif status == "404":
                    st["gone"] += 1
                    self.state["dead"][key] = self.state["dead"].get(key, 0) + 1
                else:
                    st["err"] += 1; st["e:" + status.replace("RuntimeError: ", "")[:22]] += 1
                    if "HTTP 4" in status and "429" not in status:   # a board that keeps answering 4xx is treated like a missing one
                        self.state["dead"][key] = self.state["dead"].get(key, 0) + 1
        except TimeoutError:
            st["timeout"] = 1
        left = sum(1 for f in futs if not f.done())
        ex.shutdown(wait=False, cancel_futures=True)
        errs = ", ".join(f"{k[2:]}×{v}" for k, v in st.items() if k.startswith("e:"))
        added = self.promote({ats: hits}) if hits else {}      # companies seen hiring for these roles are read more often
        self.report.append({"source": label or ats, "companies": total or len(boards), "scanned": len(boards) - left, "not_reached": left, "watch_added": added.get(ats, 0), "ok": st["ok"], "gone": st["gone"],
                            "errors": st["err"], "error_types": errs, "postings": st["jobs"], "title_match": st["match"]})

    def fast(self):
        """All career systems at once (each system keeps its own polite limit). Workday's two passes stay in one task."""
        run = self.state["run"]
        hourly = run % self.cfg.get("hourly_every_runs", 4) == 0 or "--all" in ARGS
        tasks = []
        for ats, n in self.cfg["rotation"].items():
            def t(ats=ats, n=n):
                watch = set(read_list(ROOT / f"data/watch/{ats}.txt"))
                allb = read_list(ROOT / f"data/boards/{ats}.txt")
                self.scan(ats, sorted(watch | {b for b in allb if bucket(b, n) == run % n}), 16, total=len(set(allb) | watch))
            tasks.append(t)
        caps = self.cfg.get("per_run_cap", {})
        for ats, n in self.cfg.get("rotation_wide", {}).items():
            def t(ats=ats, n=n):
                watch = set(read_list(ROOT / f"data/watch/{ats}.txt")) if hourly else set()
                allb = read_list(ROOT / f"data/boards/{ats}.txt")
                n = max(n, math.ceil(len(allb) / caps.get(ats, caps.get("default", 700))))   # big lists rotate over more runs
                self.scan(ats, sorted(watch | {b for b in allb if bucket(b, n) == run % n}), self.cfg.get("workers", {}).get(ats, 10), total=len(allb))
            tasks.append(t)

        def workday_all():
            wn = self.cfg.get("workday_watch_runs", 4)
            wlist = read_list(ROOT / "data/watch/workday.txt")
            self.scan("workday", [b for b in wlist if bucket(b, wn) == run % wn], self.cfg.get("workers", {}).get("workday", 6),
                      total=len(wlist), label="workday (companies hiring QA)")
            if hourly:
                self.workday_verify()
            n = self.cfg.get("workday_universe_runs", 48)
            wwatch = {b.lower() for b in wlist}
            allw = read_list(ROOT / "data/boards/workday.txt")
            self.scan("workday", [b for b in allw if bucket(b, n) == run % n and b.lower() not in wwatch], 5, total=len(allw),
                      terms=self.cfg.get("workday_universe_terms"), label="workday (all companies, rotating)")
        tasks.append(workday_all)

        def amazon():
            try:
                cs, _ = sources.amazon(self.cfg["amazon_terms"])
                keep = [c for c in cs if self.titles.ok(c["title"])]
                self.cands.extend(keep)
                self.report.append({"source": "amazon", "companies": 1, "scanned": 1, "ok": 1, "postings": len(cs), "title_match": len(keep)})
            except Exception as ex:
                self.report.append({"source": "amazon", "companies": 1, "scanned": 1, "ok": 0, "errors": 1, "error_types": type(ex).__name__})
        if hourly:
            tasks.append(amazon)
        with ThreadPoolExecutor(self.cfg.get("parallel_systems", 8)) as ex:
            for f in [ex.submit(t) for t in tasks]:
                try:
                    f.result()
                except Exception as e:
                    self.report.append({"source": "scan task", "ok": 0, "errors": 1, "error_types": f"{type(e).__name__}: {str(e)[:60]}"})
        self.report.sort(key=lambda r: r.get("source", ""))

    def workday(self):                      # manual full pass: python radar.py --only workday
        self.scan("workday", read_list(ROOT / "data/watch/workday.txt"), 5)
        self.workday_verify()
        self.state["workday_last"] = STAMP

    def workday_verify(self):
        gone = 0
        for j in [j for j in self.jobs.values() if j["ats"] == "workday"]:
            tenant, wd, site = j["board"].split("/", 1)[1].split("|")
            path = j["url"].split(f".myworkdayjobs.com/{site}", 1)[-1]
            if sources.workday_open(f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}", path) is False:
                self.drop(j["id"]); gone += 1
        self.report.append({"source": "workday (still open check)", "closed": gone, "ok": 1})

    def promote(self, promote):
        added = {}
        for ats, boards in promote.items():
            p = ROOT / f"data/watch/{ats}.txt"
            cur = set(read_list(p))
            low = {b.lower() for b in cur}
            new = {b for b in boards if b.lower() not in low and re.fullmatch(r"[A-Za-z0-9_.|\-]+", b)}
            if new:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("\n".join(sorted(cur | new)) + "\n")
                added[ats] = len(new)
        return added

    def sync_lists(self, man):
        """python radar.py --sync-lists : pull every open company list again (run by the loop once a day, in the background)."""
        found = defaultdict(set)
        steps = [("open lists", lists.from_open_lists), ("other lists", lists.from_other_lists)]
        if man:
            steps.append(("dataset companies", lambda: lists.from_dataset(man)))
        done = []
        for name, fn in steps:
            try:
                for ats, ids in fn().items():
                    found[ats] |= ids
                done.append(name)
            except Exception as ex:
                done.append(f"{name} failed ({type(ex).__name__})")
        added = lists.add(found)
        sizes = {f.stem: len(read_list(f)) for f in sorted((ROOT / "data/boards").glob("*.txt"))}
        rep = {"source": "company lists sync", "ok": 1, "when": STAMP, "steps": ", ".join(done), "added": added,
               "companies_total": sum(sizes.values()), "per_system": sizes}
        (ROOT / "data/lists_report.json").write_text(json.dumps(rep, indent=1))
        print(json.dumps(rep))

    def wide(self):
        last = load(ROOT / "data/lists_report.json", None)
        if last:
            self.report.append(last)
        try:
            man = wide.stapply_generated()
            if man.get("generated_at") != self.state.get("stapply_gen") or "--force" in ARGS:
                cs, promote, ids, counts = wide.stapply(man, self.cfg, self.titles)
                for c in cs:
                    c["boot"] = not self.state.get("stapply_gen")     # first snapshot: undated postings have unknown age
                self.cands += cs
                self.present["via:stapply"] = ids
                self.report.append({"source": "open dataset A (60+ career systems)", "companies": man.get("stats", {}).get("total_companies"),
                                    "postings": man.get("stats", {}).get("total_jobs"), "title_match": sum(counts.values()),
                                    "by_system": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
                                    "watch_added": self.promote(promote), "snapshot": man.get("generated_at"), "ok": 1})
                self.state["stapply_gen"] = man.get("generated_at")
        except Exception as ex:
            self.report.append({"source": "open dataset A (60+ career systems)", "ok": 0, "errors": 1, "error_types": f"{type(ex).__name__}: {str(ex)[:80]}"})
        try:
            upd = wide.feashliaa_updated()
            if upd != self.state.get("feash_upd") or "--force" in ARGS:
                cs, promote, ids = wide.feashliaa(self.titles)
                for c in cs:
                    c["boot"] = not self.state.get("feash_upd")
                self.cands += cs
                self.present["via:feashliaa"] = ids
                self.report.append({"source": "open dataset B (28k companies)", "title_match": len(cs), "watch_added": self.promote(promote),
                                    "snapshot": upd, "ok": 1})
                self.state["feash_upd"] = upd
        except Exception as ex:
            self.report.append({"source": "open dataset B (28k companies)", "ok": 0, "errors": 1, "error_types": f"{type(ex).__name__}: {str(ex)[:80]}"})

    # ---------- stage 2: decide ----------
    def judge(self, c, platform=False):
        """Returns a job record, or a rejection reason string."""
        if norm(c["company"]) in {norm(s) for s in self.titles.skip} or c["board"].split("/", 1)[-1].lower() in self.titles.skip:
            return "recruiter"
        if c["posted"] and not c["date_est"] and age_hours(c["posted"]) > self.cfg["max_age_days"] * 24:
            return "old"
        kind, why = filters.classify(c["locs"], c["remote"], c["title"], " ".join(to_lines(c["desc"])) if c["desc"] else "")
        if kind == "drop" and not c.get("multi"):
            return "location"
        if c.get("detail") and not c["desc"]:
            c["_detailed"] = True
            try:
                c["detail"](c)
            except Exception:
                pass
            if c.get("closed"):
                return "closed"
        elif c.get("refine") and kind != "drop":           # dataset text is flattened: try the real posting page
            before = c["desc"]
            try:
                c["refine"](c)
            except Exception:
                pass
            if len(c["desc"] or "") < 300 <= len(before or ""):
                c["desc"] = before
        lines = to_lines(c["desc"])
        text = " ".join(lines)
        kind, why = filters.classify(c["locs"], c["remote"], c["title"], text)
        if kind == "drop":
            return "location"
        if not filters.software_role(self.titles.is_strong(c["title"]), text) or not filters.testing_role(c["title"], text):
            return "not software"
        if c["posted"] and not c["date_est"] and age_hours(c["posted"]) > self.cfg["max_age_days"] * 24:
            return "old"
        deg = filters.degree(lines)
        if deg == "required":
            return "degree"
        if not lines and not platform:
            kind, why = "check", (why + "; " if why and kind == "check" else "") + "Description could not be read"
        posted = c["posted"] or STAMP
        return {"v": 2, "id": c["id"], "ats": c["ats"], "src": sources.LABEL.get(c["ats"]) or platforms.NAMES.get(c["ats"]) or c["ats"].title(),
                "via": "platform" if platform else c.get("via", "direct"), "board": c["board"], "title": c["title"], "company": c["company"],
                "location": show_loc(c["locs"]), "url": c["url"], "posted": posted, "date_est": bool(c["date_est"] or not c["posted"]),
                "first_seen": STAMP, "salary": filters.tidy_salary(c["salary"]) or filters.salary_from(text), "reqs": filters.requirements(lines),
                "kind": "platform" if platform else kind, "why": "" if platform else why, "ai": self.titles.is_ai(c["title"]),
                "degree": deg, "stale": bool((c.get("boot") or c.get("newboard")) and (c["date_est"] or not c["posted"])),
                "notify": "pending", "direct_link": bool(c.get("direct_link")), "_text": "\n".join(lines)[:7000]}

    def decide(self, cands, platform=False):
        keys = {(norm(j["title"]), norm(j["company"])): j["id"] for j in self.jobs.values()}
        urls = {j["url"].split("?")[0].rstrip("/").lower() for j in self.jobs.values()}
        todo, seen_ids = [], set()
        for c in cands:
            if c["id"] in self.jobs:
                self.jobs[c["id"]]["last_seen"] = STAMP
                continue
            if c["id"] in self.state["seen"] or c["id"] in seen_ids or not c["url"]:
                continue
            seen_ids.add(c["id"])
            todo.append(c)
        stats = Counter()
        with ThreadPoolExecutor(16) as ex:
            for c, res in zip(todo, ex.map(lambda c: self.judge(c, platform), todo)):
                if isinstance(res, str):
                    stats[res] += 1
                    if c.get("_detailed") or res == "degree":
                        self.state["seen"][c["id"]] = STAMP[:10]
                    continue
                k, u = (norm(res["title"]), norm(res["company"])), res["url"].split("?")[0].rstrip("/").lower()
                old = self.jobs.get(keys.get(k, ""))
                if old and old["via"] in ("stapply", "feashliaa") and res["via"] == "direct":
                    # the same posting, now read from the company's system itself: keep its history, switch the source
                    res.update(notify=old["notify"], first_seen=old["first_seen"], stale=old.get("stale", False))
                    self.drop(old["id"])
                    stats["now direct"] += 1
                    stats["accepted"] -= 1          # not a new posting, only a better source for a known one
                elif k in keys or u in urls:
                    stats["duplicate"] += 1
                    continue
                keys[k] = res["id"]; urls.add(u)
                self.desc[res["id"]] = res.pop("_text")
                self.jobs[res["id"]] = res
                stats["accepted"] += 1
        return stats

    def drop(self, jid):
        self.jobs.pop(jid, None)
        self.desc.pop(jid, None)

    def prune(self):
        closed = 0
        allowed = {platforms.NAMES.get(s, s) for s in self.cfg["platform_order"]}
        for j in list(self.jobs.values()):
            if j["kind"] == "platform" and j["src"] not in allowed:
                self.drop(j["id"])
                continue
            ids = self.present.get(j["board"]) if j["via"] == "direct" else self.present.get("via:" + j["via"])
            lim = 3 * 24 if j["kind"] == "platform" else self.cfg["max_age_days"] * 24
            if ids is not None and j["id"] not in ids and j.get("first_seen") != STAMP:
                self.drop(j["id"]); closed += 1
            elif age_hours(j["posted"]) > lim or not self.titles.ok(j["title"]):
                self.drop(j["id"])
        cut = iso(NOW - timedelta(days=45))[:10]
        self.state["seen"] = {k: v for k, v in self.state["seen"].items() if v >= cut}
        return closed

    # ---------- platforms ----------
    def discover(self, cs):
        """Platform postings reveal which companies are hiring right now: read those companies' own sites more often."""
        if not hasattr(self, "_names"):
            self._names = defaultdict(set)
            for f in (ROOT / "data/boards").glob("*.txt"):
                for b in read_list(f):
                    k = norm(re.split(r"[|.]", b.replace("careers-", ""))[0])
                    if len(k) >= 4:
                        self._names[k].add((f.stem, b))
        found = defaultdict(set)
        for c in cs:
            for ats in wide.WATCHED + ("oracle", "icims"):
                b = wide.board_of(ats, c.get("url") or "")
                if b:
                    found[ats].add(b)
            k = norm(re.sub(r"(?i)\b(inc|llc|corp(oration)?|co|ltd|group|technologies|solutions|services|north america|usa)\b\.?", "", c["company"]))
            for ats, b in self._names.get(k, ()):
                found[ats].add(b)
        for ats, bs in found.items():                 # a board seen for the first time also joins the full list
            f = ROOT / f"data/boards/{ats}.txt"
            if f.exists():
                cur = set(read_list(f))
                new = {b for b in bs if b not in cur and re.fullmatch(r"[A-Za-z0-9_.|\-]+", b)}
                if new:
                    f.write_text("\n".join(sorted(cur | new)) + "\n")
        return self.promote(found)

    def topup(self):
        today = self.now_et.date()
        boot = self.state.get("boot_done", "")
        have = sum(1 for j in self.jobs.values() if j["kind"] != "platform" and j["first_seen"] > boot
                   and datetime.fromisoformat(j["first_seen"]).astimezone(ET).date() == today)
        sent = sum(1 for j in self.jobs.values() if j["kind"] == "platform" and j["notify"] in ("sent", "pending")
                   and datetime.fromisoformat(j["first_seen"]).astimezone(ET).date() == today)
        need = max(0, self.cfg["daily_target"] - have - sent)
        for site in self.cfg.get("discovery_sites", []):      # read, never listed or sent
            try:
                cs = [c for c in platforms.SITES[site](self.cfg) if self.titles.ok(c["title"])]
                self.report.append({"source": f"discovery: {platforms.NAMES[site]}", "ok": 1, "title_match": len(cs), "watch_added": self.discover(cs)})
            except Exception as ex:
                self.report.append({"source": f"discovery: {platforms.NAMES[site]}", "ok": 0, "errors": 1, "error_types": f"{type(ex).__name__}: {str(ex)[:70]}"})
        got = []
        for site in self.cfg["platform_order"]:
            try:
                cs = [c for c in platforms.SITES[site](self.cfg) if self.titles.ok(c["title"])]
                self.discover(cs)
                before = set(self.jobs)
                st = self.decide(cs, platform=True)
                new = [self.jobs[i] for i in list(self.jobs) if i not in before]
                for j in [j for j in new if age_hours(j["posted"]) > 36]:
                    self.drop(j["id"])
                new = [j for j in new if j["id"] in self.jobs]
                got += new
                self.report.append({"source": f"platform: {platforms.NAMES[site]}", "ok": 1, "title_match": len(cs), "accepted": len(new)})
            except Exception as ex:
                self.report.append({"source": f"platform: {platforms.NAMES[site]}", "ok": 0, "errors": 1, "error_types": f"{type(ex).__name__}: {str(ex)[:70]}"})
        for i, j in enumerate(got):       # "hold": listed on the web page, not sent to Telegram
            j["notify"] = "hold"          # notify.process releases these when a Platforms tab exists
        self.state["topup_last"] = STAMP
        self.report.append({"source": "platform top-up", "company_postings_today": have, "platform_sent_today": sent + min(need, len(got)),
                            "target": self.cfg["daily_target"], "new_this_run": len(got), "ok": 1})

    # ---------- trace: why is a posting (not) here? ----------
    def trace(self, spec):
        loose = re.compile(r"(?i)\b(qa|qe|sdet|test|tester|testing|quality|eval\w*|automation|validation)\b")
        for item in [s.strip() for s in spec.split(",") if s.strip()]:
            if item.startswith("http"):
                ats = next((a for a in wide.WATCHED + ("oracle", "icims", "ukg", "jibe") if wide.board_of(a, item)), None)
                board = wide.board_of(ats, item) if ats else None
            else:
                ats, _, board = item.partition("/")
            print(f"\n=== TRACE {item} -> system={ats} company={board}")
            if not ats or not board:
                print("  cannot tell which career system this link belongs to"); continue
            lists = [f.stem for f in (ROOT / "data").glob("*/" + ats + ".txt") if board.lower() in {b.lower() for b in read_list(f)}]
            print("  in company lists:", lists or "NO (the bot does not know this company)")
            try:
                if ats == "workday" or ats in sources.SEARCH:
                    ok_all = lambda t: True
                    cs, _ = (sources.workday if ats == "workday" else sources.SEARCH[ats])(board, self.cfg.get("workday_terms" if ats == "workday" else "search_terms"), ok_all)
                else:
                    cs, _ = sources.SIMPLE[ats](board)
            except Exception as ex:
                print(f"  could not read this company: {type(ex).__name__}: {str(ex)[:80]}"); continue
            print(f"  postings read: {len(cs)}")
            for c in cs:
                if not loose.search(c["title"]):
                    continue
                if not self.titles.ok(c["title"]):
                    print(f"  TITLE FILTER  | {c['title'][:70]}"); continue
                self.state["seen"] = {}
                res = self.judge(dict(c))
                why = res if isinstance(res, str) else f"ACCEPTED as {res['kind']} {res['why']}".strip()
                listed = "  (already listed)" if c["id"] in self.jobs else ""
                print(f"  {why:22} | {c['title'][:60]} | {show_loc(c['locs'])[:50]} | posted {c['posted'][:10] or '?'}{listed}")

    # ---------- run ----------
    def ping(self):
        """python radar.py --ping : sends a test message to every configured chat and prints what Telegram says."""
        import os
        tok = os.getenv("TELEGRAM_TOKEN", "").strip()
        chats = [c.strip() for c in os.getenv("TELEGRAM_CHAT_ID", "").replace(";", ",").split(",") if c.strip()]
        print("chats configured:", len(chats))
        me = notify.api(tok, "getMe").get("result", {})
        for i, c in enumerate(chats, 1):
            info = notify.api(tok, "getChat", chat_id=c).get("result", {})
            mem = notify.api(tok, "getChatMember", chat_id=c, user_id=me.get("id", 0)).get("result", {})
            print(f"chat {i}: type={info.get('type')} title={info.get('title') or '(private chat)'} topics={info.get('is_forum')} "
                  f"bot_status={mem.get('status')} can_manage_topics={mem.get('can_manage_topics')}")
            for label, thread in (("main", None), ("tab", (notify.topics_for(tok, c, self.state) or {}).get("platform"))):
                if label == "tab" and not thread:
                    continue
                ok = notify.send(f"🔔 Job Radar test message ({label}). If you can read this, notifications reach this chat.", tok, c, thread=thread)
                print(f"   send to {label}: {'OK' if ok else 'FAILED ' + notify.LAST_ERROR[0]}")

    # ---------- gap report: LinkedIn's last-24h remote postings vs. what we decide on the company's own site ----------
    def gap(self):
        cs = [c for c in platforms.SITES["linkedin"](self.cfg) if self.titles.ok(c["title"])]
        self.discover([])                                  # builds the company-name index
        stop = {"senior", "sr", "staff", "lead", "ii", "iii", "i", "remote", "the", "and", "of", "principal", "jr", "junior"}
        words = lambda t: set(re.findall(r"[a-z0-9]+", t.lower())) - stop
        seen, rows = set(), []
        for c in cs:
            k = (norm(c["title"]), norm(c["company"]))
            if k not in seen:
                seen.add(k); rows.append(c)

        def check(c):
            k = norm(re.sub(r"(?i)\b(inc|llc|corp(oration)?|co|ltd|group|technologies|solutions|services|north america|usa)\b\.?", "", c["company"]))
            boards = sorted(self._names.get(k, ()))[:3]
            if not boards:
                return "NOT IN LISTS", ""
            notes = []
            for ats, b in boards:
                try:
                    if ats == "workday":
                        ps, _ = sources.workday(b, self.cfg["workday_terms"], lambda t: True)
                    elif ats in sources.SEARCH:
                        ps, _ = sources.SEARCH[ats](b, self.cfg["search_terms"], lambda t: True)
                    else:
                        ps, _ = sources.SIMPLE[ats](b)
                except Exception as ex:
                    notes.append(f"{ats}: read failed {type(ex).__name__}"); continue
                w = words(c["title"])
                best = [p for p in ps if len(w & words(p["title"])) >= max(2, round(0.7 * len(w)))]
                if not best:
                    notes.append(f"{ats}/{b}: no such title among {len(ps)}"); continue
                for p in best[:2]:
                    if not self.titles.ok(p["title"]):
                        notes.append(f"{ats}: TITLE FILTER '{p['title'][:40]}'"); continue
                    if p["id"] in self.jobs:
                        notes.append(f"{ats}: LISTED"); continue
                    res = self.judge(dict(p))
                    notes.append(f"{ats}: " + (res if isinstance(res, str) else "WOULD ACCEPT " + res["kind"]) + f" [{show_loc(p['locs'])[:38]} | {p['posted'][:10] or '?'}]")
            verdict = "LISTED" if any("LISTED" in n or "WOULD ACCEPT" in n for n in notes) else "REJECTED/MISSING"
            return verdict, "; ".join(notes)

        self.state["seen"] = {}
        with ThreadPoolExecutor(8) as ex:
            out = list(ex.map(check, rows))
        tally = Counter(v for v, _ in out)
        print("GAP total", len(rows), dict(tally))
        for c, (v, n) in sorted(zip(rows, out), key=lambda x: x[1][0]):
            print(f"GAP {v:17} | {c['title'][:42]:42} | {c['company'][:22]:22} | {show_loc(c['locs'])[:24]:24} | {n[:230]}")

    def run(self):
        if "--gap" in ARGS:
            return self.gap()
        if "--sync-lists" in ARGS:
            man = None
            try:
                man = wide.stapply_generated()
            except Exception:
                pass
            return self.sync_lists(man)
        if "--ping" in ARGS:
            return self.ping()
        if arg("--trace"):
            return self.trace(arg("--trace"))
        only = set((arg("--only") or "").split(",")) - {""}
        dry = "--dry-run" in ARGS
        want = lambda t, due: (t in only) if only else due
        if want("wide", True):
            self.wide()
        if want("fast", True):
            self.fast()
        if want("workday", False):
            self.workday()
        st = self.decide(self.cands)
        closed = self.prune()
        last = self.state.get("topup_last")
        since = (NOW - datetime.fromisoformat(last)).total_seconds() / 60 if last else 1e9
        if want("topup", since >= self.cfg.get("platform_every_minutes", 60) - 2 and not notify.quiet(self.now_et, self.cfg)):
            self.topup()
        if not self.state.get("bootstrapped"):
            for j in self.jobs.values():       # first run: do not send the whole backlog
                if j["kind"] == "platform" or j["date_est"] or age_hours(j["posted"]) > 24:
                    j["notify"] = "skip"
            self.state["bootstrapped"] = True
            self.state["boot_done"] = STAMP
        tg = notify.process(list(self.jobs.values()), self.state, self.cfg, dry=dry)
        acc = self.state.setdefault("since_status", {"scans": 0, "companies": 0, "new": 0})
        acc["scans"] += 1
        acc["companies"] += sum(r.get("scanned", 0) for r in self.report if isinstance(r.get("scanned"), int))
        acc["new"] += max(0, st.get("accepted", 0))
        if not dry and not only and slot_due(self.cfg.get("status_times", []), self.state.get("status_last"), self.now_et):
            today = self.now_et.date()
            mine = [j for j in self.jobs.values() if j["kind"] != "platform" and datetime.fromisoformat(j["first_seen"]).astimezone(ET).date() == today]
            failing = [r["source"] for r in self.report if r.get("ok") == 0 or (r.get("errors", 0) > 20 and "rotating" not in r["source"])]
            text = (f"📡 Job Radar status · {self.now_et:%a %b %-d, %-I:%M %p} ET\n\n"
                    f"Running normally. Since the last status: {acc['scans']} scans, {acc['companies']:,} company career pages read, "
                    f"{acc['new']} new postings.\n"
                    f"Today so far: {len(mine)} company postings ({sum(1 for j in mine if j['kind'] == 'ok')} confirmed, "
                    f"{sum(1 for j in mine if j['kind'] == 'check')} to check)."
                    + (f"\n⚠️ Sources with problems: {', '.join(failing[:6])}" if failing else ""))
            if notify.broadcast(text):
                self.state["status_last"] = STAMP
                self.state["since_status"] = {"scans": 0, "companies": 0, "new": 0}
        for j in self.jobs.values():
            j["applied"] = j["id"] in self.applied
        jobs = sorted(self.jobs.values(), key=lambda j: j["posted"], reverse=True)
        by = Counter(j["kind"] for j in jobs)
        summary = {"run": self.state["run"], "new": st.get("accepted", 0), "closed": closed, "rejected": {k: v for k, v in st.items() if k != "accepted"},
                   "listed": dict(by), "telegram": tg}
        for r in self.report:
            print(json.dumps(r, ensure_ascii=False))
        print("SUMMARY", json.dumps(summary, ensure_ascii=False))
        if dry:
            for j in jobs[:60]:
                print(f" [{j['kind']}] {j['posted'][:16]} | {j['title'][:50]} | {j['company'][:22]} | {j['location'][:40]} | {j['src']} | {j['salary']} | deg={j['degree']} | reqs={len(j['reqs'])}")
            return
        JOBS.parent.mkdir(exist_ok=True)
        JOBS.write_text(json.dumps({"updated": STAMP, "summary": summary, "report": self.report, "jobs": jobs}, indent=1, ensure_ascii=False))
        DESC.write_text(json.dumps({k: v for k, v in sorted(self.desc.items()) if k in self.jobs}, ensure_ascii=False))
        STATE.parent.mkdir(exist_ok=True)
        STATE.write_text(json.dumps(self.state, indent=1, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    Radar().run()
