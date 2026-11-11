"""Direct readers for company career systems (ATS). Each returns (candidates, all_ids).

A candidate is a dict: id, ats, board, title, company, locs [(text, country)], remote (True/False/None),
url, posted (ISO or ''), date_est (bool), salary, desc (HTML/plain or ''), detail (callable or None).
"""
import re
from datetime import datetime, timedelta

from .common import NOW, NotFound, http, iso, money, ld_jobposting

LABEL = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "workday": "Workday",
         "smartrecruiters": "SmartRecruiters", "breezy": "Breezy", "rippling": "Rippling", "recruitee": "Recruitee",
         "amazon": "Amazon Jobs"}


def cand(ats, board, jid, title, company, locs, url, posted="", remote=None, salary="", desc="", date_est=False, detail=None):
    return {"id": f"{ats}:{board}:{jid}", "ats": ats, "board": f"{ats}/{board}", "title": (title or "").strip(),
            "company": (company or "").strip(), "locs": [(str(t or "").strip(), str(c or "").strip()) for t, c in locs],
            "remote": remote, "url": url or "", "posted": iso(posted), "date_est": date_est, "salary": salary or "",
            "desc": desc or "", "detail": detail}


def pretty(slug):
    return re.sub(r"[-_]+", " ", slug).strip().title()


# ---------- Greenhouse ----------
def greenhouse(board):
    jobs = http(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs").json().get("jobs", [])
    out = []
    for j in jobs:
        def detail(c, jid=j["id"]):
            d = http(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{jid}").json()
            c["desc"] = d.get("content") or ""
            for o in d.get("offices") or []:
                if o.get("name"):
                    c["locs"].append((f"{o.get('name')} {o.get('location') or ''}".strip(), ""))
        out.append(cand("greenhouse", board, j["id"], j.get("title"), j.get("company_name") or pretty(board),
                        [((j.get("location") or {}).get("name"), "")], j.get("absolute_url"),
                        j.get("first_published") or j.get("updated_at"), date_est=not j.get("first_published"), detail=detail))
    return out, {c["id"] for c in out}


# ---------- Lever ----------
def lever(board):
    out = []
    for j in http(f"https://api.lever.co/v0/postings/{board}?mode=json").json():
        cat = j.get("categories") or {}
        ctry = j.get("country") or ""
        ctry = "United States" if ctry.upper() == "US" else ctry
        locs = [(t, ctry) for t in (cat.get("allLocations") or [cat.get("location")]) if t] or [("", ctry)]
        wt = (j.get("workplaceType") or "").lower()
        sr = j.get("salaryRange") or {}
        sal = money(sr.get("min"), sr.get("max"), per="" if (sr.get("interval") or "").startswith("per-year") else (sr.get("interval") or "").replace("per-", "").replace("-wage", ""))
        desc = (j.get("description") or j.get("descriptionPlain") or "")
        for l in j.get("lists") or []:
            desc += f"<h3>{l.get('text','')}</h3><ul>{l.get('content','')}</ul>"
        desc += j.get("additional") or ""
        out.append(cand("lever", board, j["id"], j.get("text"), pretty(board), locs, j.get("hostedUrl"), j.get("createdAt"),
                        remote=True if wt == "remote" else False if wt in ("on-site", "onsite", "hybrid") else None,
                        salary=sal if sr.get("currency", "USD") == "USD" else "", desc=desc))
    return out, {c["id"] for c in out}


# ---------- Ashby ----------
def ashby(board):
    d = http(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true").json()
    out = []
    for j in d.get("jobs", []):
        if j.get("isListed") is False:
            continue
        ac = lambda a: (((a or {}).get("postalAddress") or {}).get("addressCountry") or "")
        locs = [(j.get("location"), ac(j.get("address")))]
        locs += [(s.get("location"), ac(s.get("address"))) for s in j.get("secondaryLocations") or []]
        wt = (j.get("workplaceType") or "").lower()
        comp = j.get("compensation") or {}
        out.append(cand("ashby", board, j["id"], j.get("title"), pretty(board), locs, j.get("jobUrl"), j.get("publishedAt"),
                        remote=True if wt == "remote" else False if wt in ("onsite", "hybrid") else (True if j.get("isRemote") and not wt else None),
                        salary=comp.get("scrapeableCompensationSalarySummary") or comp.get("compensationTierSummary") or "",
                        desc=j.get("descriptionHtml") or j.get("descriptionPlain") or ""))
    return out, {c["id"] for c in out}


# ---------- Workday ----------
_POSTED = re.compile(r"(?i)posted\s+(today|yesterday|(\d+)\+?\s+days?\s+ago)")


def workday_age(text):
    """'Posted Today' -> 0, 'Posted 3 Days Ago' -> 3, 'Posted 30+ Days Ago' -> 31, unknown -> None."""
    m = _POSTED.search(text or "")
    if not m:
        return None
    w = m.group(1).lower()
    if w == "today":
        return 0
    if w == "yesterday":
        return 1
    return int(m.group(2)) + (1 if "+" in w else 0)


def workday(board, terms, title_ok):
    tenant, wd, site = board.split("|")
    base = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
    seen, out = {}, []
    for term in terms:
        r = http(base + "/jobs", method="POST", headers={"Content-Type": "application/json"},
                 json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": term}, retries=1)
        for p in r.json().get("jobPostings", []):
            path = p.get("externalPath")
            if path and path not in seen:
                seen[path] = p
    for path, p in seen.items():
        if not title_ok(p.get("title")):
            continue
        age = workday_age(p.get("postedOn"))
        if age is not None and age > 30:
            continue

        def detail(c, path=path):
            i = http(base + path).json().get("jobPostingInfo") or {}
            ctry = (i.get("country") or {}).get("descriptor") or ""
            locs = [i.get("location")] + list(i.get("additionalLocations") or [])
            c["locs"] = [(t, ctry) for t in locs if t] or c["locs"]
            rt = (i.get("remoteType") or "").lower()
            c["remote"] = True if "remote" in rt and "hybrid" not in rt else False if rt else c["remote"]
            c["desc"] = i.get("jobDescription") or ""
            c["url"] = i.get("externalUrl") or c["url"]
            if i.get("startDate"):
                sd = iso(i["startDate"])
                # date only: if it started today/yesterday keep our own first-seen time as the estimate
                if sd and (NOW - datetime.fromisoformat(sd)) > timedelta(hours=48):
                    c["posted"], c["date_est"] = sd, False
            if i.get("canApply") is False:
                c["closed"] = True

        est = iso(NOW - timedelta(days=age)) if age else ""
        out.append(cand("workday", board, path.rsplit("/", 1)[-1], p.get("title"), pretty(tenant), [(p.get("locationsText"), "")],
                        f"https://{tenant}.{wd}.myworkdayjobs.com/{site}{path}", est, date_est=True, detail=detail))
        out[-1]["multi"] = bool(re.match(r"^\d+ Locations$", p.get("locationsText") or ""))
    return out, None        # search-based: cannot prove a job closed from the list


def workday_open(url_board, jid_path):
    """True/False/None: is this Workday posting still open?"""
    try:
        i = http(url_board + jid_path, retries=0).json().get("jobPostingInfo") or {}
        return i.get("canApply") is not False
    except NotFound:
        return False
    except Exception:
        return None


# ---------- SmartRecruiters ----------
def smartrecruiters(board):
    out, off = [], 0
    while off < 500:
        d = http(f"https://api.smartrecruiters.com/v1/companies/{board}/postings?limit=100&offset={off}").json()
        for j in d.get("content", []):
            l = j.get("location") or {}

            def detail(c, ref=j.get("ref"), jid=j.get("id")):
                x = http(ref or f"https://api.smartrecruiters.com/v1/companies/{board}/postings/{jid}").json()
                sec = (x.get("jobAd") or {}).get("sections") or {}
                c["desc"] = "".join(f"<h3>{(sec.get(k) or {}).get('title','')}</h3>{(sec.get(k) or {}).get('text','')}"
                                    for k in ("jobDescription", "qualifications", "additionalInformation") if sec.get(k))
                c["url"] = x.get("postingUrl") or x.get("applyUrl") or c["url"]

            out.append(cand("smartrecruiters", board, j.get("id"), j.get("name"), (j.get("company") or {}).get("name") or pretty(board),
                            [(l.get("fullLocation") or ", ".join(x for x in (l.get("city"), l.get("region")) if x), (l.get("country") or "").upper().replace("US", "United States"))],
                            f"https://jobs.smartrecruiters.com/{board}/{j.get('id')}", j.get("releasedDate"),
                            remote=True if l.get("remote") else False if l.get("hybrid") else None, detail=detail))
        off += 100
        if off >= (d.get("totalFound") or 0):
            break
    return out, {c["id"] for c in out}


# ---------- generic: description from the posting page's JobPosting markup ----------
def page_detail(c):
    jp = ld_jobposting(http(c["url"], retries=1).text)
    if not jp:
        return
    c["desc"] = jp.get("description") or c["desc"]
    if jp.get("datePosted") and (not c["posted"] or c["date_est"]):
        d = iso(jp["datePosted"])
        if d:
            c["posted"], c["date_est"] = d, False
    if "TELECOMMUTE" in str(jp.get("jobLocationType", "")).upper():
        c["remote"] = True
        req = jp.get("applicantLocationRequirements")
        for r in (req if isinstance(req, list) else [req] if req else []):
            if isinstance(r, dict) and r.get("name"):
                c["locs"].append(("Remote", r["name"]))
    bs = jp.get("baseSalary") or {}
    v = bs.get("value") or {} if isinstance(bs, dict) else {}
    if isinstance(v, dict) and (v.get("minValue") or v.get("maxValue")) and not c["salary"] and bs.get("currency", "USD") == "USD":
        unit = (v.get("unitText") or "").lower()
        c["salary"] = money(v.get("minValue"), v.get("maxValue"), per="hour" if unit.startswith("hour") else "")


# ---------- Breezy ----------
def breezy(board):
    out = []
    for j in http(f"https://{board}.breezy.hr/json").json():
        locs = []
        for l in [j.get("location")] + list(j.get("locations") or []):
            if isinstance(l, dict):
                ctry = (l.get("country") or {}).get("name") or ""
                txt = l.get("name") or ", ".join(x for x in (l.get("city"), (l.get("state") or {}).get("id")) if x)
                locs.append((("Remote " if l.get("is_remote") else "") + (txt or ""), ctry))
        rem = any(isinstance(l, dict) and l.get("is_remote") for l in [j.get("location")] + list(j.get("locations") or []))
        co = j.get("company") or {}
        out.append(cand("breezy", board, j.get("id"), j.get("name"), co.get("name") if isinstance(co, dict) else pretty(board),
                        locs, j.get("url"), j.get("published_date"), remote=True if rem else None,
                        salary=j.get("salary") if isinstance(j.get("salary"), str) else "", detail=page_detail))
    return out, {c["id"] for c in out}


# ---------- Rippling ----------
def rippling(board):
    out = []
    for j in http(f"https://api.rippling.com/platform/api/ats/v1/board/{board}/jobs").json():
        wl = (j.get("workLocation") or {}).get("label") or ""
        out.append(cand("rippling", board, j.get("uuid"), j.get("name"), pretty(board), [(wl, "")], j.get("url"), "",
                        date_est=True, detail=page_detail))
    return out, {c["id"] for c in out}


# ---------- Recruitee ----------
def recruitee(board):
    out = []
    for j in http(f"https://{board}.recruitee.com/api/offers/").json().get("offers", []):
        cc = (j.get("country_code") or "").upper()
        locs = [(j.get("location") or j.get("city"), "United States" if cc == "US" else (j.get("country") or cc))]
        sal = j.get("salary") or {}
        out.append(cand("recruitee", board, j.get("id"), j.get("title"), j.get("company_name") or pretty(board), locs,
                        j.get("careers_url"), j.get("published_at") or j.get("created_at"),
                        remote=True if j.get("remote") else False if (j.get("hybrid") or j.get("on_site")) else None,
                        salary=money(sal.get("min"), sal.get("max")) if (sal.get("currency") or "USD") == "USD" else "",
                        desc=(j.get("description") or "") + "<h3>Requirements</h3>" + (j.get("requirements") or "")))
    return out, {c["id"] for c in out}


# ---------- Amazon ----------
def amazon(terms):
    out, seen = [], set()
    for term in terms:
        d = http("https://www.amazon.jobs/en/search.json", params={"offset": 0, "result_limit": 100, "sort": "recent",
                                                                     "base_query": term, "country": "USA"}).json()
        for j in d.get("jobs", []):
            jid = j.get("id_icims") or j.get("id")
            if jid in seen:
                continue
            seen.add(jid)
            desc = f"{j.get('description') or ''}<h3>Basic Qualifications</h3>{j.get('basic_qualifications') or ''}" \
                   f"<h3>Preferred Qualifications</h3>{j.get('preferred_qualifications') or ''}"
            out.append(cand("amazon", "amazon", jid, j.get("title"), j.get("company_name") or "Amazon",
                            [(j.get("normalized_location") or j.get("location"), "United States" if j.get("country_code") in ("USA", "US") else j.get("country_code"))],
                            "https://www.amazon.jobs" + (j.get("job_path") or ""), j.get("posted_date"), desc=desc))
    return out, None


SIMPLE = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "smartrecruiters": smartrecruiters,
          "breezy": breezy, "rippling": rippling, "recruitee": recruitee}
