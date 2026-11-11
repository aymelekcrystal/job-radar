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
    print(con.execute(f"DESCRIBE SELECT * FROM read_parquet('{url}')").fetchall())
    t = time.time()
    con.execute(f"""CREATE TABLE m AS SELECT global_id,url,apply_url,title,company,ats_type,location,country_iso,is_remote,
        salary_summary,salary_min,salary_max,posted_at,fetched_at,length(description) AS dlen
        FROM read_parquet('{url}') WHERE regexp_matches(title, '{TITLE}')""")
    print("title-match rows:", con.execute("SELECT count(*) FROM m").fetchone(), f"{time.time()-t:.1f}s")
    for r in con.execute("""SELECT ats_type,count(*) n, round(avg((posted_at IS NOT NULL)::int),2) dated,
        round(avg((dlen>200)::int),2) described, round(avg((country_iso IS NOT NULL)::int),2) ctry,
        round(avg((is_remote)::int),2) remote, count(DISTINCT company) cos, max(fetched_at) fresh
        FROM m GROUP BY 1 ORDER BY 2 DESC""").fetchall():
        print("  ", r)
    q = """FROM m WHERE (country_iso='US' OR regexp_matches(location,'(?i)united states|\\busa?\\b|, [A-Z]{2}\\b'))
           AND (is_remote OR regexp_matches(location,'(?i)remote|raleigh|durham|cary|morrisville|chapel hill'))"""
    for d in (1, 3, 7, 30):
        print(f"US remote/Raleigh, posted <= {d}d:", con.execute(f"SELECT count(*) {q} AND posted_at >= now() - INTERVAL {d} DAY").fetchone())
    print("US remote/Raleigh, no date:", con.execute(f"SELECT count(*) {q} AND posted_at IS NULL").fetchone())
    for r in con.execute(f"SELECT posted_at,ats_type,title,company,location,country_iso,is_remote,salary_summary,url {q} AND posted_at >= now() - INTERVAL 3 DAY ORDER BY posted_at DESC LIMIT 40").fetchall():
        print("  ", [str(x)[:60] for x in r])


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
step("ATS endpoints", ats)
step("stapply duckdb", duck)
