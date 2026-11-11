"""Tek seferlik kesif: acik veri setlerinin ve ATS uclarinin gercek yapisini yazdirir."""
import json, re, sys, time, traceback
import requests

UA = {"User-Agent": "job-radar/2.0 (personal job alert bot)"}
TITLE = r"(?i)\b(sdet|qa|quality (assurance|engineer|engineering)|test (automation|engineer|developer|architect|lead|analyst)|(engineer|developer) in test|(software|automation|api|integration|functional|uat) test(er|ing)?|(ai|llm|ml|model|genai|agent) (evals?|evaluation|evaluator|quality|test|testing|qa)|evaluation (engineer|specialist|analyst))\b"


def step(name, fn):
    print(f"\n===== {name} =====", flush=True)
    t = time.time()
    try:
        fn()
    except Exception:
        traceback.print_exc(limit=3, file=sys.stdout)
    print(f"-- {time.time()-t:.1f}s", flush=True)


def keys(o, n=40):
    return sorted(o.keys())[:n] if isinstance(o, dict) else type(o).__name__


MAN = {}


def manifest():
    m = requests.get("https://storage.stapply.ai/jobhive/v1/manifest.json", headers=UA, timeout=60).json()
    MAN.update(m)
    print("version", m.get("version"), "generated_at", m.get("generated_at"), "stats", m.get("stats"))
    print("all:", m.get("all"))
    print("companies:", m.get("companies"))
    for k, v in sorted(m.get("by_ats", {}).items(), key=lambda kv: -kv[1].get("rows", 0)):
        print(f"  {k:22} rows={v.get('rows'):>9} size={v.get('size_bytes',0)/1e6:8.1f}MB pq={'y' if v.get('parquet') else 'n'} csv={'y' if v.get('csv') else 'n'}")
    bd = m.get("by_date", {})
    print("by_date keys:", sorted(bd)[-6:], {k: (bd[k].get("rows"), round(bd[k].get("size_bytes", 0)/1e6, 1)) for k in sorted(bd)[-3:]})
    print("sample urls:", m.get("all", {}).get("parquet"), "|", next(iter(m.get("by_ats", {}).values()), {}).get("parquet"))


def duck():
    import duckdb
    url = MAN["all"]["parquet"]
    if not url.startswith("http"):
        url = "https://storage.stapply.ai/" + url.lstrip("/")
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    print([c[0] for c in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{url}')").fetchall()])
    print("all size MB:", MAN["all"].get("parquet_size_bytes", MAN["all"].get("size_bytes", 0)) / 1e6)
    t = time.time()
    con.execute(f"""CREATE TABLE m AS SELECT url,apply_url,title,company,ats_type,location,country_iso,is_remote,
        salary_summary,salary_min,salary_max,posted_at,length(description) AS dlen
        FROM read_parquet('{url}') WHERE regexp_matches(title, '{TITLE}')""")
    print("title-match rows:", con.execute("SELECT count(*) FROM m").fetchone(), f"{time.time()-t:.1f}s")
    import collections
    from datetime import datetime, timezone, timedelta
    cols = [d[0] for d in con.execute("SELECT * FROM m LIMIT 0").description]
    rows = [dict(zip(cols, r)) for r in con.execute("SELECT * FROM m").fetchall()]
    print("types:", {k: type(v).__name__ for k, v in rows[0].items()})
    print("is_remote values:", collections.Counter(str(r["is_remote"]) for r in rows).most_common(5))
    print("posted_at samples:", [str(r["posted_at"]) for r in rows[:5]])
    now = datetime.now(timezone.utc)
    def age(r):
        v = r["posted_at"]
        if v in (None, ""): return None
        try:
            d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
            return (now - d).total_seconds() / 86400
        except Exception: return None
    st = collections.defaultdict(lambda: collections.Counter())
    US = re.compile(r"(?i)united states|\busa?\b|, [A-Z]{2}\b|any state")
    RAL = re.compile(r"(?i)raleigh|durham|\bcary\b|morrisville|chapel hill|research triangle")
    hits = []
    for r in rows:
        a = r["ats_type"]; c = st[a]; c["n"] += 1; g = age(r); loc = r["location"] or ""
        c["dated"] += g is not None; c["desc"] += (r["dlen"] or 0) > 200; c["ctry"] += bool(r["country_iso"]); c["sal"] += bool(r["salary_summary"] or r["salary_min"])
        us = r["country_iso"] == "US" or bool(US.search(loc)); rem = str(r["is_remote"]).lower() == "true" or "remote" in loc.lower()
        ok = (us and rem) or bool(RAL.search(loc))
        if ok:
            c["us_ok"] += 1
            for d in (1, 3, 7, 30):
                if g is not None and g <= d: c[f"d{d}"] += 1
            if g is None: c["nodate"] += 1
            if g is not None and g <= 3: hits.append((round(g, 1), a, r["title"], r["company"], loc, r["country_iso"], r["is_remote"], r["salary_summary"], r["url"]))
    tot = collections.Counter()
    for a, c in sorted(st.items(), key=lambda kv: -kv[1]["n"]):
        tot.update(c)
        print(f"  {a:18} n={c['n']:5} dated={c['dated']/c['n']:.2f} desc={c['desc']/c['n']:.2f} ctry={c['ctry']/c['n']:.2f} sal={c['sal']/c['n']:.2f} | us_ok={c['us_ok']:4} 1d={c['d1']:3} 3d={c['d3']:3} 7d={c['d7']:3} 30d={c['d30']:4} nodate={c['nodate']}")
    print("TOTAL", dict(tot))
    for h in sorted(hits)[:60]:
        print("  ", [str(x)[:58] for x in h])


def get(url, **kw):
    r = requests.get(url, headers=UA, timeout=30, **kw)
    print("GET", url[:110], r.status_code, r.headers.get("content-type", "")[:30], len(r.content))
    return r


def ats():
    r = requests.post("https://availity.wd1.myworkdayjobs.com/wday/cxs/availity/Availity_Careers_US/jobs", headers={**UA, "Content-Type": "application/json"},
                      json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "quality"}, timeout=30)
    print("workday", r.status_code, r.text[:200] if r.status_code != 200 else "")
    if r.ok:
        d = r.json(); print(" total", d.get("total"), keys(d)); p = d.get("jobPostings", [])
        print(" posting:", json.dumps(p[0])[:400] if p else None)
        if p:
            x = get("https://availity.wd1.myworkdayjobs.com/wday/cxs/availity/Availity_Careers_US" + p[0]["externalPath"]).json()
            i = x.get("jobPostingInfo", {}); print(" detail keys:", keys(i)); print(" ", {k: str(i.get(k))[:90] for k in ("startDate", "postedOn", "location", "additionalLocations", "remoteType", "timeType", "country", "externalUrl")})
    tests = {
        "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/Visa/postings?limit=3",
        "workable_widget": "https://apply.workable.com/api/v1/widget/accounts/zapier?details=true",
        "recruitee": "https://bunq.recruitee.com/api/offers/",
        "teamtailor": "https://spotify.teamtailor.com/jobs.json",
        "breezy": "https://10-4-truck-recruiting.breezy.hr/json",
        "rippling": "https://api.rippling.com/platform/api/ats/v1/board/rippling/jobs",
        "bamboohr": "https://10web.bamboohr.com/careers/list",
        "amazon": "https://www.amazon.jobs/en/search.json?offset=0&result_limit=3&sort=recent&base_query=quality%20assurance%20engineer&country=USA",
        "gh_list": "https://boards-api.greenhouse.io/v1/boards/gitlab/jobs",
        "ashby": "https://api.ashbyhq.com/posting-api/job-board/ramp?includeCompensation=true",
        "lever": "https://api.lever.co/v0/postings/palantir?mode=json&limit=2",
    }
    for name, u in tests.items():
        try:
            r = get(u)
            if "json" not in r.headers.get("content-type", ""):
                print(" ", name, "non-json:", r.text[:120].replace("\n", " ")); continue
            d = r.json()
            lst = d if isinstance(d, list) else next((v for v in d.values() if isinstance(v, list) and v), [])
            print(" ", name, "top:", keys(d, 15), "| n:", len(lst))
            if lst:
                j = lst[0]; print("   job keys:", keys(j, 45)); print("   sample:", json.dumps({k: v for k, v in j.items() if not isinstance(v, str) or len(v) < 120})[:500])
        except Exception as ex:
            print(" ", name, "ERR", type(ex).__name__, str(ex)[:100])
    r = requests.post("https://apply.workable.com/api/v3/accounts/zapier/jobs", headers={**UA, "Content-Type": "application/json"},
                      json={"query": "", "location": [], "department": [], "worktype": [], "remote": []}, timeout=30)
    print("workable v3", r.status_code, r.text[:300])
    r = get("https://boards-api.greenhouse.io/v1/boards/gitlab/jobs")
    if r.ok and r.json().get("jobs"):
        j = r.json()["jobs"][0]; x = get(f"https://boards-api.greenhouse.io/v1/boards/gitlab/jobs/{j['id']}").json()
        print(" gh detail keys:", keys(x), "| list job keys:", keys(j))


step("stapply manifest", manifest)
step("stapply duckdb", duck)
