"""Wide nets: two open datasets built from company career pages.

- stapply "jobhive" (MIT): ~60 career systems, millions of postings, with descriptions and dates.
- Feashliaa job-board-aggregator (code MIT, data CC BY-NC 4.0): ~28k companies, daily.
They also tell us which companies hire for these roles, so the direct scanner can watch them closely.
"""
import gzip, json, re
from collections import defaultdict

import requests

from .common import UA, http, iso
from .sources import cand, page_detail, pretty

MANIFEST = "https://storage.stapply.ai/jobhive/v1/manifest.json"
FEASH = "https://raw.githubusercontent.com/Feashliaa/job-board-data/main/data/"
# sources inside the dataset that are job boards / public feeds, not a company's own career site
NOT_COMPANY = {"eures", "bundesagentur", "arbetsformedlingen", "welcometothejungle", "jobbankca", "jobsch", "wanted",
               "programathor", "getonbrd", "ycombinator", "wellfound", "weworkremotely", "builtin", "mercor", "manfred",
               "join_com", "infojobs_es", "jobs_cz", "seek", "thehub", "remoteok", "usajobs"}
WATCHED = ("greenhouse", "lever", "ashby", "workday", "smartrecruiters", "breezy", "rippling", "recruitee",
           "bamboohr", "workable", "pinpoint", "recruiterbox", "teamtailor", "gem", "oracle", "icims", "ukg",
           "paycom", "dayforce", "paylocity", "personio", "jobvite", "jazzhr")
_WD = re.compile(r"https://([^./]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+)")
_URL = {
    "greenhouse": re.compile(r"greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_.\-]+)"),
    "lever": re.compile(r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_.\-]+)"),
    "ashby": re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)"),
    "smartrecruiters": re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([^/?#]+)"),
    "breezy": re.compile(r"https?://([A-Za-z0-9\-]+)\.breezy\.hr"),
    "rippling": re.compile(r"ats\.rippling\.com/([^/?#]+)/jobs"),
    "recruitee": re.compile(r"https?://([A-Za-z0-9\-]+)\.recruitee\.com"),
    "bamboohr": re.compile(r"https?://([A-Za-z0-9\-]+)\.bamboohr\.com"),
    "workable": re.compile(r"apply\.workable\.com/([^/?#]+)"),
    "pinpoint": re.compile(r"https?://([A-Za-z0-9\-]+)\.pinpointhq\.com"),
    "recruiterbox": re.compile(r"https?://([A-Za-z0-9\-]+)\.recruiterbox\.com"),
    "teamtailor": re.compile(r"https?://([A-Za-z0-9\-]+)\.teamtailor\.com"),
    "gem": re.compile(r"jobs\.gem\.com/([^/?#]+)"),
    "jibe": re.compile(r"https?://([a-z0-9.\-]+)/jobs/\d"),
    "paycom": re.compile(r"paycomonline\.(?:net|com)/v4/ats/web\.php/portal/([0-9A-Fa-f]{32})"),
    "paylocity": re.compile(r"recruiting\.paylocity\.com/Recruiting/Jobs/All/([0-9A-Fa-f\-]{36})"),
    "personio": re.compile(r"https?://([a-z0-9\-]+)\.jobs\.personio\.(?:com|de)"),
    "jobvite": re.compile(r"jobs\.jobvite\.com/([A-Za-z0-9_\-]+)"),
    "jazzhr": re.compile(r"https?://([A-Za-z0-9\-]+)\.applytojob\.com"),
}


_ORA = re.compile(r"https://([a-z0-9.\-]+oraclecloud\.com)/hcmUI/CandidateExperience/[A-Za-z_\-]+/sites/([A-Za-z0-9_\-]+)")
_ICI = re.compile(r"https?://([a-z0-9.\-]+\.icims\.com)", re.I)
_UKG = re.compile(r"https://([a-z0-9.\-]+)/([A-Za-z0-9]+)/JobBoard/([0-9a-fA-F\-]{36})")


PROVEN = set(WATCHED) - {"oracle", "icims", "ukg", "paycom", "dayforce", "paylocity", "personio", "jobvite", "jazzhr"}    # direct readers that replace the dataset copy entirely


def board_of(ats, url):
    url = url or ""
    if ats == "oracle":
        m = _ORA.search(url)
        return f"{m.group(1).lower()}|{m.group(2)}" if m else None
    if ats == "icims":
        m = _ICI.search(url)
        return m.group(1).lower() if m else None
    if ats == "ukg":
        m = _UKG.search(url)
        return f"{m.group(1).lower()}|{m.group(2)}|{m.group(3).lower()}" if m else None
    if ats == "jibe":
        return None
    if ats == "dayforce":
        m = re.search(r"dayforcehcm\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_\-]+)/([A-Za-z0-9_\-]+)", url)
        return f"{m.group(1).lower()}|{m.group(2)}" if m else None
    if ats == "workday":
        m = _WD.match(url)
        return "|".join(m.groups()) if m else None
    m = _URL[ats].search(url) if ats in _URL else None
    if not m:
        return None
    b = requests.utils.unquote(m.group(1))
    return b if ats in ("smartrecruiters", "jobvite") else b.lower()


def host_company(name):
    n = (name or "").strip()
    if n and n == n.lower() and " " not in n and "." not in n:
        return pretty(n)
    if "." in n and " " not in n:
        n = re.sub(r"^(jobs|careers|career|www|apply)\.", "", n.lower())
        n = n.split(".")[0]
        return pretty(n)
    return n


def stapply_generated():
    return http(MANIFEST).json()


def stapply(manifest, cfg, titles):
    """Returns (candidates, promote {ats: set(boards)}, ids of all title matches, per-ATS counts)."""
    import duckdb
    url = manifest["all"]["parquet"]
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    pat = "(?i)" + "|".join(f"(?:{p})" for p in cfg["include"] + (cfg.get("ece_include") or []))
    rows = con.execute(
        "SELECT url,title,company,ats_type,ats_id,location,country_iso,is_remote,salary_summary,posted_at,apply_url,description "
        "FROM read_parquet(?) WHERE regexp_matches(title, ?)", [url, pat]).fetchall()
    cands, promote, ids, counts = [], defaultdict(set), set(), defaultdict(int)
    for u, title, company, ats, ats_id, loc, ctry, rem, sal, posted, apply_url, desc in rows:
        ats = (ats or "").lower()
        if ats in NOT_COMPANY or not titles.ok(title):
            continue
        counts[ats] += 1
        if ats in WATCHED:
            b = board_of(ats, u) or board_of(ats, apply_url)
            if b:
                if titles.qa(title):
                    promote[ats].add(b)
                if ats in PROVEN:
                    continue                       # the direct scanner reads this company itself
        if ats == "amazon":
            continue
        c = cand(ats, host_company(company) or "x", ats_id or u, title, host_company(company),
                 [(loc, "United States" if (ctry or "").upper() == "US" else (ctry or ""))], u or apply_url, posted,
                 remote=True if str(rem).lower() == "true" else None, salary=sal or "", desc=desc or "",
                 date_est=not posted)
        c["id"] = f"{ats}:{ats_id or u}"
        c["via"] = "stapply"
        c["refine"] = page_detail
        c["weak_company"] = " " not in (company or "").strip()
        ids.add(c["id"])
        cands.append(c)
    return cands, promote, ids, dict(counts)


def feashliaa_updated():
    return http(FEASH + "metadata.json").json().get("last_updated")


def feashliaa(titles):
    cands, promote, ids = [], defaultdict(set), set()
    names = http(FEASH + "chunks/jobs_manifest.json").json().get("chunks", [])
    for name in names:
        for j in json.loads(gzip.decompress(http(FEASH + "chunks/" + name, timeout=180).content)):
            title = j.get("title") or ""
            if j.get("is_recruiter") or not titles.ok(title):
                continue
            ats, u = (j.get("ats") or "").lower(), j.get("url") or ""
            if ats in WATCHED:
                b = board_of(ats, u) or (j.get("company") or "").lower() if ats != "workday" else board_of(ats, u)
                if b:
                    promote[ats].add(b)
                continue
            c = cand(ats, (j.get("company") or "x"), u, title, pretty(j.get("company") or ""), [(j.get("location"), "")], u,
                     j.get("first_seen"), date_est=True, detail=page_detail)
            c["id"] = f"{ats}:{u}"
            c["via"] = "feashliaa"
            ids.add(c["id"])
            cands.append(c)
    return cands, promote, ids
