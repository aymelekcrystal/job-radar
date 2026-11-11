#!/usr/bin/env python3
"""Job Radar v2: company career sites first.

Usage: python radar.py [--dry-run] [--only fast,workday,wide,topup] [--max-boards N]
"""
import hashlib, json, re, sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from jr import filters, notify, platforms, sources, wide
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
        self.jobs = {j["id"]: j for j in load(JOBS, {}).get("jobs", []) if j.get("v") == 2}
        self.desc = load(DESC, {})
        self.report, self.cands, self.present = [], [], {}
        self.max_boards = int(arg("--max-boards", 0) or 0)
        self.now_et = NOW.astimezone(ET)

    # ---------- stage 1: read boards ----------
    def _read(self, ats, board):
        try:
            if ats == "workday":
                cs, ids = sources.workday(board, self.cfg["workday_terms"], self.titles.ok)
            else:
                cs, ids = sources.SIMPLE[ats](board)
            return ats, board, "ok", [c for c in cs if self.titles.ok(c["title"])], ids, len(cs)
        except NotFound:
            return ats, board, "404", [], None, 0
        except Exception as ex:
            return ats, board, f"{type(ex).__name__}: {str(ex)[:40]}", [], None, 0

    def scan(self, ats, boards, workers, total=None):
        boards = [b for b in boards if self.state["dead"].get(f"{ats}/{b}", 0) < 3]
        if self.max_boards:
            boards = boards[: self.max_boards]
        st = Counter()
        with ThreadPoolExecutor(workers) as ex:
            for a, b, status, cs, ids, n in ex.map(lambda b: self._read(ats, b), boards):
                key = f"{a}/{b}"
                if status == "ok":
                    st["ok"] += 1; st["jobs"] += n; st["match"] += len(cs)
                    self.state["dead"].pop(key, None)
                    if cs and cs[0].get("nodate"):          # undated system: on a company's first read, age is unknown
                        known = self.state.setdefault("nodate_boards", [])
                        if key not in known:
                            known.append(key)
                            for c in cs:
                                c["newboard"] = True
                    self.cands += cs
                    if ids is not None:
                        self.present[key] = ids
                elif status == "404":
                    st["gone"] += 1
                    self.state["dead"][key] = self.state["dead"].get(key, 0) + 1
                else:
                    st["err"] += 1; st["e:" + status.split(":")[0]] += 1
        errs = ", ".join(f"{k[2:]}×{v}" for k, v in st.items() if k.startswith("e:"))
        self.report.append({"source": ats, "companies": total or len(boards), "scanned": len(boards), "ok": st["ok"], "gone": st["gone"],
                            "errors": st["err"], "error_types": errs, "postings": st["jobs"], "title_match": st["match"]})

    def fast(self):
        run = self.state["run"]
        for ats, n in self.cfg["rotation"].items():
            watch = set(read_list(ROOT / f"data/watch/{ats}.txt"))
            allb = read_list(ROOT / f"data/boards/{ats}.txt")
            pick = sorted(watch | {b for b in allb if bucket(b, n) == run % n})
            self.scan(ats, pick, 16, total=len(set(allb) | watch))
        if run % self.cfg.get("hourly_every_runs", 4) == 0 or "--all" in ARGS:
            for ats in ("smartrecruiters", "breezy", "rippling", "recruitee"):
                self.scan(ats, read_list(ROOT / f"data/watch/{ats}.txt"), 8)
            try:
                cs, _ = sources.amazon(self.cfg["amazon_terms"])
                keep = [c for c in cs if self.titles.ok(c["title"])]
                self.cands += keep
                self.report.append({"source": "amazon", "companies": 1, "scanned": 1, "ok": 1, "postings": len(cs), "title_match": len(keep)})
            except Exception as ex:
                self.report.append({"source": "amazon", "companies": 1, "scanned": 1, "ok": 0, "errors": 1, "error_types": type(ex).__name__})

    def workday(self):
        self.scan("workday", read_list(ROOT / "data/watch/workday.txt"), 5)
        gone = 0
        for j in [j for j in self.jobs.values() if j["ats"] == "workday"]:
            tenant, wd, site = j["board"].split("/", 1)[1].split("|")
            path = j["url"].split(f".myworkdayjobs.com/{site}", 1)[-1]
            if sources.workday_open(f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}", path) is False:
                self.drop(j["id"]); gone += 1
        self.report[-1]["closed"] = gone
        self.state["workday_last"] = STAMP

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

    def wide(self):
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
        if not filters.software_role(self.titles.is_strong(c["title"]), text):
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
        keys = {(norm(j["title"]), norm(j["company"])) for j in self.jobs.values()}
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
        with ThreadPoolExecutor(8) as ex:
            for c, res in zip(todo, ex.map(lambda c: self.judge(c, platform), todo)):
                if isinstance(res, str):
                    stats[res] += 1
                    if c.get("_detailed") or res == "degree":
                        self.state["seen"][c["id"]] = STAMP[:10]
                    continue
                k, u = (norm(res["title"]), norm(res["company"])), res["url"].split("?")[0].rstrip("/").lower()
                if k in keys or u in urls:
                    stats["duplicate"] += 1
                    continue
                keys.add(k); urls.add(u)
                self.desc[res["id"]] = res.pop("_text")
                self.jobs[res["id"]] = res
                stats["accepted"] += 1
        return stats

    def drop(self, jid):
        self.jobs.pop(jid, None)
        self.desc.pop(jid, None)

    def prune(self):
        closed = 0
        for j in list(self.jobs.values()):
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
    def topup(self):
        today = self.now_et.date()
        boot = self.state.get("boot_done", "")
        have = sum(1 for j in self.jobs.values() if j["kind"] != "platform" and j["first_seen"] > boot
                   and datetime.fromisoformat(j["first_seen"]).astimezone(ET).date() == today)
        sent = sum(1 for j in self.jobs.values() if j["kind"] == "platform" and j["notify"] in ("sent", "pending")
                   and datetime.fromisoformat(j["first_seen"]).astimezone(ET).date() == today)
        need = max(0, self.cfg["daily_target"] - have - sent)
        got = []
        for site in self.cfg["platform_order"]:
            try:
                cs = [c for c in platforms.SITES[site](self.cfg) if self.titles.ok(c["title"])]
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

    # ---------- run ----------
    def run(self):
        only = set((arg("--only") or "").split(",")) - {""}
        dry = "--dry-run" in ARGS
        want = lambda t, due: (t in only) if only else due
        if want("wide", True):
            self.wide()
        if want("fast", True):
            self.fast()
        if want("workday", slot_due(self.cfg["workday_times"], self.state.get("workday_last"), self.now_et) or not self.state.get("workday_last")):
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
        for j in self.jobs.values():
            if j.get("stale") and j["notify"] == "pending" and not j.get("force"):
                j["notify"] = "skip"
        tg = notify.process(list(self.jobs.values()), self.state, self.cfg, dry=dry)
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
