#!/usr/bin/env python3
"""Job Radar: remote US QA/SDET/AI-testing ilanlarini toplar, docs/jobs.json'a yazar,
istege bagli Telegram'a bildirir. Kullanim: python radar.py [--dry-run]"""
import html, json, os, re, sys, time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests, yaml

ROOT = Path(__file__).parent
OUT = ROOT / "docs" / "jobs.json"
UA = {"User-Agent": "job-radar/1.0 (personal job alert bot)"}
NOW = datetime.now(timezone.utc)


def get(url, **kw):
    r = requests.get(url, headers=UA, timeout=30, **kw)
    r.raise_for_status()
    return r


def iso(v):
    """Her turlu tarihi (epoch, ISO, RFC822) UTC ISO stringe cevirir; olmazsa ''."""
    if v in (None, ""):
        return ""
    try:
        if isinstance(v, (int, float)) or str(v).isdigit():
            n = float(v)
            d = datetime.fromtimestamp(n / 1000 if n > 1e11 else n, timezone.utc)
        else:
            s = str(v).strip()
            try:
                d = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                d = parsedate_to_datetime(s)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return ""


def money(lo, hi, cur="$"):
    try:
        lo, hi = int(float(lo or 0)), int(float(hi or 0))
    except (TypeError, ValueError):
        return ""
    if not lo and not hi:
        return ""
    f = lambda n: f"{cur}{n:,}"
    return f"{f(lo)} – {f(hi)}" if lo and hi and lo != hi else f(lo or hi)


def job(src, jid, title, company, loc, url, posted="", salary="", tags="", remote=None):
    return {"id": f"{src}:{jid}", "source": src, "title": (title or "").strip(),
            "company": (company or "").strip(), "location": (loc or "").strip(),
            "url": url or "", "posted": iso(posted), "salary": salary or "",
            "tags": tags or "", "remote_flag": remote}


# ---------- remote is siteleri ----------
def remotive(_):
    out = []
    for cat in ("qa", "software-dev"):
        for j in get("https://remotive.com/api/remote-jobs", params={"category": cat}).json().get("jobs", []):
            out.append(job("remotive", j["id"], j.get("title"), j.get("company_name"),
                           j.get("candidate_required_location"), j.get("url"),
                           j.get("publication_date"), j.get("salary"), " ".join(j.get("tags") or []), True))
    return out


def remoteok(_):
    out = []
    for j in get("https://remoteok.com/api").json():
        if not isinstance(j, dict) or "position" not in j:
            continue
        out.append(job("remoteok", j.get("id"), j.get("position"), j.get("company"),
                       j.get("location"), j.get("url") or j.get("apply_url"), j.get("date"),
                       money(j.get("salary_min"), j.get("salary_max")), " ".join(j.get("tags") or []), True))
    return out


def himalayas(_):
    out, off = [], 0
    while off < 400:
        js = get("https://himalayas.app/jobs/api", params={"limit": 20, "offset": off}).json().get("jobs", [])
        if not js:
            break
        for j in js:
            out.append(job("himalayas", j.get("guid") or j.get("applicationLink"), j.get("title"),
                           j.get("companyName"), ", ".join(j.get("locationRestrictions") or []),
                           j.get("applicationLink") or j.get("guid"), j.get("pubDate"),
                           money(j.get("minSalary"), j.get("maxSalary")),
                           " ".join(j.get("categories") or []), True))
        off += len(js)
        time.sleep(0.3)
    return out


def jobicy(_):
    out = []
    for tag in ("qa", "test", "sdet"):
        js = get("https://jobicy.com/api/v2/remote-jobs", params={"count": 50, "geo": "usa", "tag": tag}).json().get("jobs", [])
        for j in js:
            out.append(job("jobicy", j.get("id"), j.get("jobTitle"), j.get("companyName"),
                           j.get("jobGeo"), j.get("url"), j.get("pubDate"),
                           money(j.get("annualSalaryMin"), j.get("annualSalaryMax")), "", True))
        time.sleep(1)
    return out


def weworkremotely(_):
    out = []
    root = ET.fromstring(get("https://weworkremotely.com/remote-jobs.rss").content)
    for it in root.iter("item"):
        t = it.findtext("title") or ""
        company, _, title = t.partition(": ")
        if not title:
            company, title = "", t
        out.append(job("wwr", it.findtext("guid") or it.findtext("link"), title, company,
                       it.findtext("region"), it.findtext("link"), it.findtext("pubDate"),
                       "", it.findtext("category"), True))
    return out


def workingnomads(_):
    out = []
    for j in get("https://www.workingnomads.com/api/exposed_jobs/").json():
        out.append(job("workingnomads", j.get("url"), j.get("title"), j.get("company_name"),
                       j.get("location"), j.get("url"), j.get("pub_date"), "", j.get("tags"), True))
    return out


# ---------- sirket kariyer sayfalari (ATS) ----------
def greenhouse(slug):
    js = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs").json().get("jobs", [])
    return [job("greenhouse", f"{slug}-{j['id']}", j.get("title"), j.get("company_name") or slug.title(),
                (j.get("location") or {}).get("name"), j.get("absolute_url"),
                j.get("first_published") or j.get("updated_at")) for j in js]


def lever(slug):
    js = get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}).json()
    out = []
    for j in js:
        c = j.get("categories") or {}
        sr = j.get("salaryRange") or {}
        out.append(job("lever", f"{slug}-{j['id']}", j.get("text"), slug.title(),
                       c.get("location") or ", ".join(c.get("allLocations") or []), j.get("hostedUrl"),
                       j.get("createdAt"), money(sr.get("min"), sr.get("max")),
                       remote=True if j.get("workplaceType") == "remote" else None))
    return out


def ashby(slug):
    d = get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", params={"includeCompensation": "true"}).json()
    out = []
    for j in d.get("jobs", []):
        comp = (j.get("compensation") or {}).get("scrapeableCompensationSalarySummary") or \
               (j.get("compensation") or {}).get("compensationTierSummary") or ""
        out.append(job("ashby", f"{slug}-{j['id']}", j.get("title"), slug.title(), j.get("location"),
                       j.get("jobUrl"), j.get("publishedAt"), comp,
                       remote=True if j.get("isRemote") else None))
    return out


BOARDS = {f.__name__: f for f in (remotive, remoteok, himalayas, jobicy, weworkremotely, workingnomads)}
ATS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}

# ---------- filtreler ----------
US = re.compile(r"\b(usa?|u\.s\.a?\.?|united states|america|americas|north america|worldwide|anywhere|global)\b", re.I)
US_STATE = re.compile(r",\s*(A[LKZR]|C[AOT]|DE|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY]|DC)\b")
FOREIGN = re.compile(r"\b(canada|uk|united kingdom|europe|emea|apac|latam|india|germany|france|spain|ireland|poland|"
                     r"brazil|mexico|australia|japan|singapore|israel|netherlands|portugal|argentina|colombia|philippines|"
                     r"london|berlin|paris|dublin|toronto|bangalore|bengaluru|tokyo|sydney|amsterdam)\b", re.I)


def us_remote(j):
    """True: US'ten remote calisilabilir gorunuyor. Emin olunamayan ilanlar elenir."""
    loc = j["location"]
    is_us = bool(US.search(loc) or US_STATE.search(loc))
    if j["remote_flag"]:                       # remote sitesi ya da ATS 'remote' isareti
        return is_us or not loc or not FOREIGN.search(loc)
    if not re.search(r"remote", loc, re.I):    # ATS: konumda 'remote' yazmali
        return False
    return is_us or not FOREIGN.search(loc)


def matches(j, cfg):
    t = j["title"]
    if any(re.search(p, t, re.I) for p in cfg["exclude"]):
        return False
    return any(re.search(p, t, re.I) for p in cfg["include"])


def fresh(j, days):
    if not j["posted"]:
        return True
    return NOW - datetime.fromisoformat(j["posted"]) <= timedelta(days=days)


# ---------- bildirim ----------
def telegram(j):
    tok, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return
    e = html.escape
    lines = [f"<b>{e(j['title'])}</b>", f"@ {e(j['company'])}", f"📍 {e(j['location'] or 'Remote')}"]
    if j["salary"]:
        lines.append(f"💰 {e(j['salary'])}")
    if j.get("ai"):
        lines.append("🤖 AI")
    lines.append(f"{e(j['source'])} · {j['url']}")
    try:
        requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", timeout=20,
                      data={"chat_id": chat, "text": "\n".join(lines), "parse_mode": "HTML",
                            "disable_web_page_preview": "true"})
        time.sleep(0.4)
    except Exception as ex:
        print("telegram error:", ex)


# ---------- ana akis ----------
def collect(cfg):
    jobs, report = [], []
    tasks = [(n, BOARDS[n], None) for n in cfg.get("boards", []) if n in BOARDS]
    for kind, fn in ATS.items():
        tasks += [(f"{kind}/{s}", fn, s) for s in cfg.get(kind, [])]
    for name, fn, arg in tasks:
        try:
            got = fn(arg)
            jobs += got
            report.append({"source": name, "ok": True, "fetched": len(got)})
        except Exception as ex:
            report.append({"source": name, "ok": False, "error": f"{type(ex).__name__}: {str(ex)[:120]}"})
        time.sleep(0.2)
    return jobs, report


def select(raw, cfg):
    seen, out = set(), []
    for j in raw:
        key = (re.sub(r"\W+", "", j["title"].lower()), re.sub(r"\W+", "", j["company"].lower()))
        if not j["url"] or j["id"] in seen or key in seen:
            continue
        if matches(j, cfg) and us_remote(j) and fresh(j, cfg.get("max_age_days", 21)):
            seen.update((j["id"], key))
            j["ai"] = any(re.search(p, j["title"] + " " + j["tags"], re.I) for p in cfg.get("ai_terms", []))
            j.pop("remote_flag"); j.pop("tags")
            out.append(j)
    return out


def main():
    dry = "--dry-run" in sys.argv
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    old = json.loads(OUT.read_text()) if OUT.exists() else {"jobs": []}
    known = {j["id"]: j for j in old.get("jobs", [])}
    first_run = not known

    raw, report = collect(cfg)
    picked = select(raw, cfg)
    stamp = NOW.isoformat(timespec="seconds")
    new = []
    for j in picked:
        if j["id"] in known:
            j["first_seen"] = known[j["id"]].get("first_seen", stamp)
        else:
            j["first_seen"] = stamp
            new.append(j)
    # kaynagi o an hata veren ilanlari kaybetme
    failed = {r["source"].split("/")[0] for r in report if not r["ok"]}
    ids = {j["id"] for j in picked}
    keep = [j for j in known.values() if j["id"] not in ids and j["source"] in failed
            and fresh(j, cfg.get("max_age_days", 21))]
    alljobs = sorted(picked + keep, key=lambda j: j["posted"] or j["first_seen"], reverse=True)

    for r in report:
        print(("ok  " if r["ok"] else "FAIL"), r["source"].ljust(28), r.get("fetched", r.get("error")))
    print(f"toplam {len(raw)} ilan tarandi · {len(alljobs)} uygun · {len(new)} yeni")
    if dry:
        for j in new[:40]:
            print(" -", j["title"], "@", j["company"], "|", j["location"], "|", j["url"])
        return
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"updated": stamp, "report": report, "jobs": alljobs}, indent=1, ensure_ascii=False))
    if not first_run:          # ilk calismada eski ilan yagmuru gonderme
        for j in new:
            telegram(j)
    if report and not any(r["ok"] for r in report):
        sys.exit("hicbir kaynak cevap vermedi")


if __name__ == "__main__":
    main()
