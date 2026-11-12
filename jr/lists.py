"""Company lists per career system: where they come from and how they stay complete.

Sources (all open):
- stapply-ai/ats-scrapers  ats-companies/*.csv          (MIT)
- Feashliaa/job-board-aggregator  data/*_companies.json  (MIT code)
- LastRound AI ATS company directory (CC BY 4.0) and ConorsCode/open-jobs-data companies.json (MIT)
- every company that appears in the stapply jobs dataset (all ~60 career systems)
- companies seen on job platforms (LinkedIn/Indeed links and names), added by radar.discover

sync() runs once a day and only ever adds companies; a company that stops answering is skipped after 3 failures.
"""
import csv, io, json, re
from pathlib import Path

from .common import http

ROOT = Path(__file__).resolve().parent.parent
BOARDS = ROOT / "data/boards"
STAPPLY = "https://raw.githubusercontent.com/stapply-ai/ats-scrapers/main/ats-companies/"
FEASH = "https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/main/data/"
OK = re.compile(r"[A-Za-z0-9_.|\-]+")

# system -> regex that pulls the company identifier out of any text (url or slug column)
PAT = {
    "greenhouse": r"greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_.\-]+)",
    "lever": r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_.\-]+)",
    "ashby": r"jobs\.ashbyhq\.com/([^/?#,\s]+)",
    "smartrecruiters": r"smartrecruiters\.com/([^/?#,\s]+)",
    "rippling": r"ats\.rippling\.com/([^/?#,\s]+)",
    "breezy": r"https?://([a-z0-9\-]+)\.breezy\.hr",
    "recruitee": r"https?://([a-z0-9\-]+)\.recruitee\.com",
    "bamboohr": r"https?://([a-z0-9\-]+)\.bamboohr\.com",
    "workable": r"apply\.workable\.com/([^/?#,\s]+)",
    "pinpoint": r"https?://([a-z0-9\-]+)\.pinpointhq\.com",
    "recruiterbox": r"https?://([a-z0-9\-]+)\.recruiterbox\.com",
    "teamtailor": r"https?://([a-z0-9\-]+)\.teamtailor\.com",
    "gem": r"jobs\.gem\.com/([^/?#,\s]+)",
    "icims": r"https?://([a-z0-9.\-]+\.icims\.com)",
    "personio": r"https?://([a-z0-9\-]+)\.jobs\.personio\.(?:com|de)",
    "jobvite": r"jobs\.jobvite\.com/([A-Za-z0-9_\-]+)",
    "paycom": r"portal/([0-9a-fA-F]{32})",
    "paylocity": r"Jobs/All/([0-9a-fA-F\-]{36})",
}
CASE = {"smartrecruiters", "jobvite"}            # identifiers where upper/lower case matters
NOT_BOARD = {"www", "api", "app", "jobs", "careers", "embed", "job-boards", "boards"}


def parse(ats, text, slug=""):
    """One row of a list -> company identifier for that system, or None."""
    if ats == "workday":
        m = re.search(r"https://([^.]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#,\s]+)", text)
        return "|".join(m.groups()) if m else None
    if ats == "oracle":
        m = re.search(r"https://([a-z0-9.\-]+oraclecloud\.com)/hcmUI/CandidateExperience/[A-Za-z_\-]+/sites/([A-Za-z0-9_\-]+)", text)
        return f"{m.group(1).lower()}|{m.group(2)}" if m else None
    if ats == "ukg":
        m = re.search(r"https://([a-z0-9.\-]+)/([A-Za-z0-9]+)/JobBoard/([0-9a-fA-F\-]{36})", text)
        return f"{m.group(1).lower()}|{m.group(2)}|{m.group(3).lower()}" if m else None
    if ats == "adp":
        m = re.search(r"cid=([0-9a-fA-F\-]{36}).*?ccId=([0-9_]+)", text) or re.search(r"([0-9a-fA-F\-]{36})/([0-9_]{10,})", text)
        return f"{m.group(1).lower()}|{m.group(2)}" if m else None
    if ats == "dayforce":
        m = re.search(r"dayforcehcm\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_\-]+)/([A-Za-z0-9_\-]+)", text)
        return f"{m.group(1).lower()}|{m.group(2)}" if m else None
    if ats == "jibe":
        h = slug.strip().lower()
        return h if re.fullmatch(r"[a-z0-9.\-]+\.[a-z]{2,}", h) else None
    if ats == "successfactors":
        m = re.search(r"https?://([a-z0-9.\-]+\.[a-z]{2,})", text.lower())
        return m.group(1) if m and "successfactors.com" not in m.group(1) else None
    m = re.search(PAT[ats], text, re.I) if ats in PAT else None
    v = (m.group(1) if m else slug).strip()
    if ats == "icims" and v and "." not in v:
        v = f"careers-{v.lstrip('-')}.icims.com" if not v.startswith("-") else f"{v.lstrip('-')}.icims.com"
    v = v if ats in CASE else v.lower()
    return v if v and OK.fullmatch(v) and v not in NOT_BOARD else None


SYSTEMS = list(PAT) + ["workday", "oracle", "ukg", "adp", "dayforce", "jibe", "successfactors"]
FEASH_FILES = {"greenhouse": "greenhouse_companies.json", "lever": "lever_companies.json", "ashby": "ashby_companies.json",
               "workday": "workday_companies.json", "bamboohr": "bamboohr_companies.json", "icims": "icims_companies.json",
               "paylocity": "paylocity_companies_clean.json"}


def add(found):
    """found: {system: set(ids)} -> writes new ones into data/boards, returns {system: number added}."""
    added = {}
    for ats, ids in found.items():
        f = BOARDS / f"{ats}.txt"
        cur = set(f.read_text().split()) if f.exists() else set()
        low = {b.lower() for b in cur}
        new = {b for b in ids if b and OK.fullmatch(b) and b.lower() not in low}
        if new:
            f.write_text("\n".join(sorted(cur | new)) + "\n")
            added[ats] = len(new)
    return added


def from_open_lists():
    found = {}
    for ats in SYSTEMS:
        try:
            rows = list(csv.reader(io.StringIO(http(STAPPLY + ats + ".csv", retries=1).text)))[1:]
        except Exception:
            rows = []
        found[ats] = {parse(ats, " ".join(r), r[1] if len(r) > 1 else "") for r in rows} - {None}
    for ats, name in FEASH_FILES.items():
        try:
            for x in http(FEASH + name, retries=1, timeout=90).json():
                v = x.get("guid") if isinstance(x, dict) else x
                if ats == "workday":
                    v = v if isinstance(v, str) and v.count("|") == 2 else None
                else:
                    v = parse(ats, "", str(v or ""))
                if v:
                    found.setdefault(ats, set()).add(v)
        except Exception:
            pass
    return found


LASTROUND = "https://datahub.io/lastroundai-hiring-data/lastroundai-hiring-data/_r/-/ats-directory/lastroundai-ats-company-directory-2026-08.csv"
CONORS = "https://raw.githubusercontent.com/ConorsCode/open-jobs-data/main/companies.json"


def from_other_lists():
    found = {}
    try:
        for r in csv.DictReader(io.StringIO(http(LASTROUND, retries=1, timeout=60).text)):
            ats = (r.get("ats_vendor") or "").strip().lower()
            v = parse(ats, "", r.get("board_slug") or "") if ats in PAT else None
            if v:
                found.setdefault(ats, set()).add(v)
    except Exception:
        pass
    try:
        d = http(CONORS, retries=1).json()
        for c in d if isinstance(d, list) else d.get("companies", []):
            ats = str(c.get("platform") or "").lower()
            if ats == "workday" and c.get("tenant") and c.get("site"):
                shard = str(c.get("shard") or c.get("wd") or "wd1")
                found.setdefault("workday", set()).add(f"{c['tenant']}|{shard if shard.startswith('wd') else 'wd' + shard}|{c['site']}")
            elif ats in PAT and c.get("slug"):
                v = parse(ats, "", str(c["slug"]))
                if v:
                    found.setdefault(ats, set()).add(v)
    except Exception:
        pass
    return found


def from_dataset(manifest):
    """Every company that has any posting in the open dataset, for every system we read directly."""
    import duckdb
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    rows = con.execute("SELECT lower(ats_type), any_value(url), any_value(apply_url) FROM read_parquet(?) "
                       "GROUP BY 1, regexp_extract(url, '^https?://[^/]+(/[^/?#]+){0,3}')", [manifest["all"]["parquet"]]).fetchall()
    found = {}
    for ats, url, apply_url in rows:
        if ats in SYSTEMS:
            v = parse(ats, f"{url or ''} {apply_url or ''}")
            if v:
                found.setdefault(ats, set()).add(v)
    return found
