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
    u = lambda x: html.unescape(x or "").strip()
    return {"id": f"{src}:{jid}", "source": src, "title": u(title),
            "company": u(company), "location": u(loc),
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
    out, err = [], None
    for params in ({"count": 50, "geo": "usa", "industry": "qa"}, {"count": 50, "tag": "qa"},
                   {"count": 50, "tag": "sdet"}, {"count": 50, "geo": "usa"}):
        try:
            js = get("https://jobicy.com/api/v2/remote-jobs", params=params).json().get("jobs", [])
        except Exception as ex:
            err = ex
            continue
        for j in js:
            out.append(job("jobicy", j.get("id"), j.get("jobTitle"), j.get("companyName"),
                           j.get("jobGeo"), j.get("url"), j.get("pubDate"),
                           money(j.get("annualSalaryMin"), j.get("annualSalaryMax")), "", True))
        time.sleep(1)
    if not out and err:
        raise err
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


# ---------- anahtar isteyen kaynaklar (kotali; seyrek calisir) ----------
META = {}   # son calisma zamanlari, jobs.json icinde saklanir


class Skip(Exception):
    """Kaynak bu turda bilerek atlandi (anahtar yok ya da sirasi gelmedi)."""


def due(name, hours):
    last = META.get(name + "_last")
    if last and NOW - datetime.fromisoformat(last) < timedelta(hours=hours):
        raise Skip(f"sirasi gelmedi ({hours} saatte bir)")
    META[name + "_last"] = NOW.isoformat(timespec="seconds")


def adzuna(cfg):
    aid, key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not (aid and key):
        raise Skip("anahtar eklenmemis")
    due("adzuna", 2)                      # kota: gunde ~70 istek
    out = []
    for term in cfg.get("adzuna_titles", []):
        r = get("https://api.adzuna.com/v1/api/jobs/us/search/1",
                params={"app_id": aid, "app_key": key, "results_per_page": 50, "title_only": term,
                        "what": "remote", "max_days_old": 3, "sort_by": "date"}).json()
        for j in r.get("results", []):
            text = f"{j.get('title','')} {j.get('description','')}"
            if not re.search(r"\bremote\b|work from home", text, re.I):
                continue
            loc = (j.get("location") or {}).get("display_name") or ""
            out.append(job("adzuna", j.get("id"), re.sub(r"</?strong>", "", j.get("title") or ""),
                           (j.get("company") or {}).get("display_name"), f"Remote · {loc}, US" if loc else "Remote, US",
                           j.get("redirect_url"), j.get("created"),
                           "" if str(j.get("salary_is_predicted")) == "1" else money(j.get("salary_min"), j.get("salary_max")),
                           remote=True))
        time.sleep(2.5)
    return out


def _s(v, *keys):
    """Alan string de olabilir obje de; ilk dolu metni dondurur."""
    if isinstance(v, dict):
        for k in keys or ("name", "display_name", "raw", "text"):
            if v.get(k):
                return str(v[k])
        return ""
    if isinstance(v, list):
        return ", ".join(_s(x, *keys) for x in v if x)
    return str(v or "")


def jobspipe(cfg):
    key = os.getenv("JOBSPIPE_API_KEY")
    if not key:
        raise Skip("anahtar eklenmemis")
    due("jobspipe", cfg.get("jobspipe_every_hours", 6))
    r = requests.post("https://api.jobspipe.dev/v1/jobs/search", timeout=40,
                      headers={**UA, "Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                      json={"job_title_or": cfg.get("jobspipe_titles", []), "job_country_code_or": ["US"],
                            "remote": True, "posted_at_max_age_days": 2, "limit": cfg.get("jobspipe_limit", 25)})
    if r.status_code in (402, 403, 429):
        raise Skip(f"kredi/kota bitti olabilir (HTTP {r.status_code})")
    r.raise_for_status()
    data = r.json().get("data", [])
    if data:
        print("jobspipe alanlari:", sorted(data[0].keys()))
    out = []
    for j in data:
        sal = j.get("salary_string") or money(j.get("min_annual_salary_usd") or j.get("min_annual_salary"),
                                              j.get("max_annual_salary_usd") or j.get("max_annual_salary"))
        out.append(job("jobspipe", j.get("id"), j.get("job_title") or j.get("title"),
                       _s(j.get("company") or j.get("company_object")),
                       _s(j.get("short_location") or j.get("location") or j.get("long_location")) or "United States",
                       j.get("final_url") or j.get("url") or j.get("source_url"),
                       j.get("date_posted") or j.get("discovered_at"), sal, remote=True))
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


BOARDS = {f.__name__: f for f in (remotive, remoteok, himalayas, jobicy, weworkremotely, workingnomads,
                                   adzuna, jobspipe)}
ATS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}

# ---------- filtreler ----------
US = re.compile(r"\b(usa?|u\.s\.a?\.?|united states|america|americas|north america|worldwide|anywhere|global)\b", re.I)
US_STATE = re.compile(r",\s*(A[LKZR]|C[AOT]|DE|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY]|DC)\b")
FOREIGN = re.compile(r"\b(canada|uk|united kingdom|europe|emea|apac|latam|india|germany|france|spain|ireland|poland|"
                     r"brazil|mexico|australia|japan|singapore|israel|netherlands|portugal|argentina|colombia|philippines|cet|cest|gmt|"
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
    tasks = [(n, BOARDS[n], cfg) for n in cfg.get("boards", []) if n in BOARDS]
    for kind, fn in ATS.items():
        tasks += [(f"{kind}/{s}", fn, s) for s in cfg.get(kind, [])]
    for name, fn, arg in tasks:
        try:
            got = fn(arg)
            jobs += got
            report.append({"source": name, "ok": True, "fetched": len(got)})
        except Skip as ex:
            report.append({"source": name, "ok": True, "skipped": str(ex)})
        except Exception as ex:
            report.append({"source": name, "ok": False, "error": f"{type(ex).__name__}: {str(ex)[:120]}"})
        time.sleep(0.2)
    return jobs, report


NEAR = []  # basligi uyan ama konumu yuzunden elenenler (ayar yaparken bakmak icin)


def short_loc(loc):
    parts = [p.strip() for p in loc.split(",")]
    if len(parts) > 5 and len(loc) > 90:
        us = any(p.lower() in ("united states", "usa", "us") for p in parts)
        return f"United States + {len(parts) - 1} ulke" if us else f"{parts[0]} + {len(parts) - 1} ulke"
    return loc


def select(raw, cfg):
    seen, out = set(), []
    for j in raw:
        key = (re.sub(r"\W+", "", j["title"].lower()), re.sub(r"\W+", "", j["company"].lower()))
        if not j["url"] or j["id"] in seen or key in seen:
            continue
        if matches(j, cfg) and not us_remote(j) and fresh(j, cfg.get("max_age_days", 21)):
            NEAR.append(f"{j['source']} | {j['title']} | {j['company']} | {j['location'][:70]}")
        if matches(j, cfg) and us_remote(j) and fresh(j, cfg.get("max_age_days", 21)):
            seen.update((j["id"], key))
            j["ai"] = any(re.search(p, j["title"] + " " + j["tags"], re.I) for p in cfg.get("ai_terms", []))
            j.pop("remote_flag"); j.pop("tags")
            j["location"] = short_loc(j["location"])
            out.append(j)
    return out


def main():
    dry = "--dry-run" in sys.argv
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    old = json.loads(OUT.read_text()) if OUT.exists() else {"jobs": []}
    known = {j["id"]: j for j in old.get("jobs", [])}
    META.update(old.get("meta", {}))
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
    failed = {r["source"].split("/")[0] for r in report if not r["ok"] or r.get("skipped")}
    ids = {j["id"] for j in picked}
    keep = [j for j in known.values() if j["id"] not in ids and j["source"] in failed
            and fresh(j, cfg.get("max_age_days", 21)) and matches(j, cfg)]
    alljobs = sorted(picked + keep, key=lambda j: j["posted"] or j["first_seen"], reverse=True)

    for r in report:
        print(("skip" if r.get("skipped") else "ok  " if r["ok"] else "FAIL"), r["source"].ljust(28),
              r.get("fetched", r.get("skipped") or r.get("error")))
    print(f"toplam {len(raw)} ilan tarandi · {len(alljobs)} uygun · {len(new)} yeni")
    print(f"basligi uyup konumdan elenen: {len(NEAR)}")
    for n in NEAR[:150]:
        print("  near:", n)
    if dry:
        for j in new[:40]:
            print(" -", j["title"], "@", j["company"], "|", j["location"], "|", j["url"])
        return
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"updated": stamp, "meta": META, "report": report, "jobs": alljobs}, indent=1, ensure_ascii=False))
    if not first_run:          # ilk calismada eski ilan yagmuru gonderme
        for j in new:
            telegram(j)
    if report and not any(r["ok"] and not r.get("skipped") for r in report):
        sys.exit("hicbir kaynak cevap vermedi")


if __name__ == "__main__":
    main()
