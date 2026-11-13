"""Direct readers for company career systems (ATS). Each returns (candidates, all_ids).

A candidate is a dict: id, ats, board, title, company, locs [(text, country)], remote (True/False/None),
url, posted (ISO or ''), date_est (bool), salary, desc (HTML/plain or ''), detail (callable or None).
"""
import re
from datetime import datetime, timedelta

from .common import NOW, NotFound, http, iso, money, ld_jobposting

LABEL = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "workday": "Workday",
         "smartrecruiters": "SmartRecruiters", "breezy": "Breezy", "rippling": "Rippling", "recruitee": "Recruitee",
         "amazon": "Amazon Jobs", "bamboohr": "BambooHR", "workable": "Workable", "pinpoint": "Pinpoint",
         "recruiterbox": "Recruiterbox", "teamtailor": "Teamtailor", "gem": "Gem", "oracle": "Oracle Cloud",
         "ukg": "UKG", "jibe": "Jibe", "icims": "iCIMS", "adp": "ADP", "paycom": "Paycom", "dayforce": "Dayforce",
         "paylocity": "Paylocity", "successfactors": "SuccessFactors", "personio": "Personio", "jobvite": "Jobvite", "jazzhr": "JazzHR"}


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
    org = jp.get("hiringOrganization")
    if c.get("weak_company") and isinstance(org, dict) and org.get("name") and len(str(org["name"])) < 60:
        c["company"] = str(org["name"]).strip()
    if len(jp.get("description") or "") > 300:
        c["desc"] = jp["description"]
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
_RIP_KEYS = []


def rippling(board):
    out = []
    for j in http(f"https://api.rippling.com/platform/api/ats/v1/board/{board}/jobs").json():
        wl = (j.get("workLocation") or {}).get("label") or ""

        def detail(c, uuid=j.get("uuid")):
            try:
                d = http(f"https://api.rippling.com/platform/api/ats/v1/board/{board}/jobs/{uuid}", retries=1).json()
            except Exception:
                return page_detail(c)
            if not _RIP_KEYS:
                _RIP_KEYS.append(1)
                print("rippling detail keys:", sorted(d.keys()), {k: sorted(v.keys()) for k, v in d.items() if isinstance(v, dict)})
            ds = d.get("description")
            c["desc"] = "".join(str(v) for v in ds.values() if v) if isinstance(ds, dict) else str(ds or "")
            for k in ("createdOn", "createdAt", "created_on", "publishedAt", "postedAt", "datePosted"):
                if d.get(k) and iso(d[k]):
                    c["posted"], c["date_est"] = iso(d[k]), False
                    break
            for l in d.get("workLocations") or []:
                c["locs"].append((l if isinstance(l, str) else (l.get("label") or l.get("name") or ""), ""))
            if d.get("companyName"):
                c["company"] = d["companyName"]
            if not c["desc"]:
                page_detail(c)

        out.append(cand("rippling", board, j.get("uuid"), j.get("name"), pretty(board), [(wl, "")], j.get("url"), "",
                        date_est=True, detail=detail))
        out[-1]["nodate"] = True
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


# ---------- BambooHR ----------
def bamboohr(board):
    base = f"https://{board}.bamboohr.com"
    rows = []
    try:
        d = http(base + "/careers/list", retries=1).json()
        for j in d.get("result") or []:
            l, a = j.get("location") or {}, j.get("atsLocation") or {}
            rows.append((j.get("id"), j.get("jobOpeningName"), ", ".join(x for x in (l.get("city") or a.get("city"), l.get("state") or a.get("state")) if x),
                         a.get("country") or "", j.get("locationType"), j.get("isRemote")))
    except (NotFound, ValueError):                 # older tenants: no JSON list, only the embedded widget
        txt = http(base + "/jobs/embed2.php", retries=1).text.strip()
        if txt.startswith("{"):
            import json as _json
            for dep in _json.loads(txt).get("departments") or []:
                for p_ in dep.get("positions") or []:
                    loc = p_.get("location")
                    loc = loc if isinstance(loc, str) else ", ".join(str(v) for v in (loc or {}).values() if isinstance(v, str) and v)
                    rows.append((p_.get("id"), p_.get("name") or p_.get("title"), loc, "", p_.get("locationType"), None))
        else:
            for m in re.finditer(r'bhrPositionID_(\d+)"[^>]*>\s*<a[^>]*>([^<]+)</a>\s*(?:<span[^>]*BambooHR-ATS-Location[^>]*>([^<]*)</span>)?', txt):
                rows.append((m.group(1), m.group(2).strip(), (m.group(3) or "").strip(), "", None, None))
    out = []
    for jid, title, loc, ctry, ltype, isrem in rows:
        if not jid:
            continue

        def detail(c, jid=jid):
            o = (http(f"{base}/careers/{jid}/detail", retries=1).json().get("result") or {}).get("jobOpening") or {}
            c["desc"] = o.get("description") or ""
            if o.get("datePosted") and iso(o["datePosted"]):
                c["posted"], c["date_est"] = iso(o["datePosted"]), False
            l = o.get("location") or {}
            if isinstance(l, dict) and (l.get("city") or l.get("state")):
                c["locs"].append((", ".join(x for x in (l.get("city"), l.get("state")) if x), l.get("addressCountry") or l.get("country") or ""))
            lt = str(o.get("locationType") or "")
            if lt == "1":
                c["remote"] = True
            comp = o.get("compensation")
            if isinstance(comp, str) and comp and not c["salary"]:
                c["salary"] = comp[:60]

        lt = str(ltype) if ltype is not None else ""
        out.append(cand("bamboohr", board, jid, title, pretty(board), [(loc, ctry)], f"{base}/careers/{jid}", "",
                        remote=True if (lt == "1" or isrem is True) else False if lt in ("0", "2") else None, date_est=True, detail=detail))
        out[-1]["nodate"] = True
    return out, {c["id"] for c in out}


# ---------- Workable ----------
def workable(board):
    d = http(f"https://apply.workable.com/api/v1/widget/accounts/{board}?details=true", retries=1).json()
    out = []
    for j in d.get("jobs") or []:
        locs = [(", ".join(x for x in (l.get("city"), l.get("region")) if x), "United States" if (l.get("countryCode") or "").upper() == "US" else (l.get("country") or ""))
                for l in j.get("locations") or [] if isinstance(l, dict)]
        if not locs:
            locs = [(", ".join(x for x in (j.get("city"), j.get("state")) if x), j.get("country") or "")]
        code = j.get("shortcode") or j.get("code") or j.get("id")

        def detail(c, code=code):
            try:
                c["desc"] = http(f"https://apply.workable.com/{board}/jobs/view/{code}.md", retries=1).text
            except Exception:
                page_detail(c)

        out.append(cand("workable", board, code, j.get("title"), d.get("name") or pretty(board), locs,
                        j.get("url") or j.get("application_url") or f"https://apply.workable.com/{board}/j/{code}/",
                        j.get("published_on") or j.get("created_at"), remote=True if j.get("telecommuting") or j.get("remote") else None,
                        desc=j.get("description") or "", detail=detail))
    return out, {c["id"] for c in out}


# ---------- Pinpoint ----------
def pinpoint(board):
    out = []
    for j in http(f"https://{board}.pinpointhq.com/postings.json", retries=1).json().get("data") or []:
        l = j.get("location") or {}
        wt = (j.get("workplace_type") or "").lower()
        sal = money(j.get("compensation_minimum"), j.get("compensation_maximum")) \
            if j.get("compensation_visible") and (j.get("compensation_currency") or "USD") == "USD" else ""
        desc = (j.get("description") or "") + "".join(f"<h3>{h}</h3>{j.get(k) or ''}" for k, h in (
            ("key_responsibilities", "Responsibilities"), ("skills_knowledge_expertise", "Requirements")) if j.get(k))
        out.append(cand("pinpoint", board, j.get("id"), j.get("title"), pretty(board),
                        [(l.get("name") or ", ".join(x for x in (l.get("city"), l.get("province")) if x), "")], j.get("url"),
                        j.get("first_published_at"), remote=True if wt == "remote" else False if wt in ("onsite", "hybrid") else None,
                        salary=sal, desc=desc, date_est=not j.get("first_published_at")))
    return out, {c["id"] for c in out}


# ---------- Recruiterbox ----------
def recruiterbox(board):
    d = http(f"https://jsapi.recruiterbox.com/v1/openings?client_name={board}&offset=0&limit=100", retries=1).json()
    out = []
    for j in d.get("objects") or []:
        l = j.get("location") or {}
        out.append(cand("recruiterbox", board, j.get("id"), j.get("title"), pretty(board),
                        [(", ".join(x for x in (l.get("city"), l.get("state")) if x), l.get("country") or "")], j.get("hosted_url") or j.get("url"),
                        j.get("created_on"), remote=True if j.get("allows_remote") else None, desc=j.get("description") or ""))
    return out, {c["id"] for c in out}


# ---------- Teamtailor ----------
def teamtailor(board):
    import xml.etree.ElementTree as ET
    root = ET.fromstring(http(f"https://{board}.teamtailor.com/jobs.rss", retries=1).content)
    out = []
    for it in root.iter("item"):
        locs, rem = [], None
        for el in it.iter():
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "location":
                parts = {c.tag.rsplit("}", 1)[-1]: (c.text or "").strip() for c in el}
                locs.append((", ".join(x for x in (parts.get("name") or parts.get("city"), ) if x), parts.get("country") or ""))
            elif tag == "remoteStatus":
                rem = True if (el.text or "").strip().lower() in ("fully", "remote") else None
        out.append(cand("teamtailor", board, it.findtext("guid") or it.findtext("link"), it.findtext("title"), pretty(board),
                        locs or [("", "")], it.findtext("link"), it.findtext("pubDate"), remote=rem, desc=it.findtext("description") or ""))
    return out, {c["id"] for c in out}


# ---------- Gem ----------
_GEM = "https://jobs.gem.com/api/public/graphql/batch"
_GEM_LIST = ("query JobBoardList($boardId: String!) { oatsExternalJobPostings(boardId: $boardId) { jobPostings { id extId title "
             "locations { id name city isoCountry isRemote } job { id locationType employmentType } } } }")
_GEM_ONE = ("query ExternalJobPostingQuery($boardId: String!, $extId: String!) { oatsExternalJobPosting(boardId: $boardId, extId: $extId) "
            "{ id title descriptionHtml extId firstPublishedTsSec compensationHtml } }")


def gem(board):
    r = http(_GEM, method="POST", retries=1, headers={"Content-Type": "application/json"},
             json=[{"operationName": "JobBoardList", "variables": {"boardId": board}, "query": _GEM_LIST}]).json()
    posts = ((((r[0] if isinstance(r, list) else r).get("data") or {}).get("oatsExternalJobPostings") or {}).get("jobPostings")) or []
    out = []
    for j in posts:
        ext = j.get("extId") or j.get("id")
        locs = [(l.get("name") or l.get("city") or "", "United States" if (l.get("isoCountry") or "").upper() in ("US", "USA") else (l.get("isoCountry") or ""))
                for l in j.get("locations") or []]
        lt = ((j.get("job") or {}).get("locationType") or "").lower()

        def detail(c, ext=ext):
            x = http(_GEM, method="POST", retries=1, headers={"Content-Type": "application/json"},
                     json=[{"operationName": "ExternalJobPostingQuery", "variables": {"boardId": board, "extId": ext}, "query": _GEM_ONE}]).json()
            o = (((x[0] if isinstance(x, list) else x).get("data") or {}).get("oatsExternalJobPosting")) or {}
            c["desc"] = (o.get("descriptionHtml") or "") + (o.get("compensationHtml") or "")
            if o.get("firstPublishedTsSec"):
                c["posted"], c["date_est"] = iso(o["firstPublishedTsSec"]), False

        out.append(cand("gem", board, ext, j.get("title"), pretty(board), locs or [("", "")], f"https://jobs.gem.com/{board}/{ext}", "",
                        remote=True if ("remote" in lt or any(l.get("isRemote") for l in j.get("locations") or [])) else None,
                        date_est=True, detail=detail))
        out[-1]["nodate"] = True
    return out, {c["id"] for c in out}


# ---------- Oracle Recruiting Cloud (keyword search) ----------
def oracle(board, terms, title_ok):
    host, site = board.split("|")
    api = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    seen, out = set(), []
    for term in terms:
        d = http(api, retries=1, params={"onlyData": "true", "expand": "requisitionList.secondaryLocations",
                                         "finder": f'findReqs;siteNumber={site},keyword="{term}",limit=50,sortBy=POSTING_DATES_DESC'}).json()
        for blk in d.get("items") or []:
            for j in blk.get("requisitionList") or []:
                jid = str(j.get("Id") or "")
                if not jid or jid in seen or not title_ok(j.get("Title")):
                    continue
                seen.add(jid)
                locs = [(j.get("PrimaryLocation"), j.get("PrimaryLocationCountry") or "")]
                locs += [(s.get("Name"), s.get("CountryCode") or "") for s in j.get("secondaryLocations") or []]
                locs = [(t, "United States" if (c or "").upper() == "US" else c) for t, c in locs]
                wc = (j.get("WorkplaceTypeCode") or "").upper()

                def detail(c, jid=jid):
                    x = http(f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails", retries=1,
                             params={"expand": "all", "onlyData": "true", "finder": f'ById;Id="{jid}",siteNumber={site}'}).json()
                    it = (x.get("items") or [{}])[0]
                    c["desc"] = "".join(f"<h3>{h}</h3>{it.get(k)}" for k, h in (("ExternalDescriptionStr", "Description"),
                        ("ExternalResponsibilitiesStr", "Responsibilities"), ("ExternalQualificationsStr", "Qualifications")) if it.get(k))

                out.append(cand("oracle", board, jid, j.get("Title"), pretty(host.split(".")[0]), locs,
                                f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{jid}", j.get("PostedDate"),
                                remote=True if "REMOTE" in wc else False if wc else None, detail=detail))
    return out, None


# ---------- UKG Pro Recruiting (keyword search) ----------
def ukg(board, terms, title_ok):
    host, tenant, guid = board.split("|")
    base = f"https://{host}/{tenant}/JobBoard/{guid}"
    seen, out = set(), []
    for term in terms:
        d = http(base + "/JobBoardView/LoadSearchResults", method="POST", retries=1, headers={"Content-Type": "application/json"},
                 json={"opportunitySearch": {"Top": 50, "Skip": 0, "QueryString": term, "OrderBy": [
                     {"Value": "postedDateDesc", "PropertyName": "PostedDate", "Ascending": False}], "OrderByKey": None,
                     "Filters": [], "Coordinates": None, "Extent": None, "ProximitySearchType": 0}}).json()
        for j in d.get("opportunities") or []:
            jid = j.get("Id")
            if not jid or jid in seen or not title_ok(j.get("Title")):
                continue
            seen.add(jid)
            locs = []
            for l in j.get("Locations") or []:
                a = l.get("Address") or {}
                st, ct = (a.get("State") or {}).get("Code"), (a.get("Country") or {}).get("Name") or (a.get("Country") or {}).get("Code") or ""
                locs.append((", ".join(x for x in (l.get("LocalizedName"), a.get("City"), st) if x), ct))

            def detail(c, jid=jid):
                txt = http(f"{base}/OpportunityDetail?opportunityId={jid}", retries=1).text
                i = txt.find("new US.Opportunity.CandidateOpportunityDetail(")
                if i < 0:
                    return
                import json as _json
                try:
                    o, _ = _json.JSONDecoder().raw_decode(txt[i + len("new US.Opportunity.CandidateOpportunityDetail("):])
                except ValueError:
                    return
                c["desc"] = o.get("Description") or ""
                if o.get("IsRemote") or "remote" in str(o.get("JobLocationType", "")).lower():
                    c["remote"] = True

            out.append(cand("ukg", board, jid, j.get("Title"), pretty(tenant.rstrip("0123456789")), locs or [("", "")],
                            f"{base}/OpportunityDetail?opportunityId={jid}", j.get("PostedDate"), detail=detail))
    return out, None


# ---------- Jibe (Google) career sites (keyword search) ----------
def jibe(board, terms, title_ok):
    seen, out = set(), []
    for term in terms:
        d = http(f"https://{board}/api/jobs", retries=1, params={"keywords": term, "limit": 100, "page": 1, "internal": "false"}).json()
        for row in d.get("jobs") or []:
            j = row.get("data") or row
            jid = str(j.get("req_id") or j.get("slug") or "")
            if not jid or jid in seen or not title_ok(j.get("title")):
                continue
            seen.add(jid)
            ctry = j.get("country") or j.get("country_code") or ""
            loc = j.get("full_location") or j.get("location_name") or ", ".join(x for x in (j.get("city"), j.get("state")) if x)
            out.append(cand("jibe", board, jid, j.get("title"), j.get("hiring_organization") or pretty(board.split(".")[-2]),
                            [(loc, "United States" if str(ctry).upper() in ("US", "USA") else ctry)],
                            j.get("apply_url") or f"https://{board}/jobs/{j.get('slug') or jid}", j.get("posted_date") or j.get("create_date"),
                            remote=True if "remote" in str(j.get("location_type", "")).lower() or j.get("remote") else None,
                            desc=(j.get("description") or "") + (j.get("qualifications") or "") + (j.get("responsibilities") or "")))
    return out, None


# ---------- iCIMS (keyword search page + posting page) ----------
_ICIMS_CARD = re.compile(r'<li[^>]+class="[^"]*iCIMS_JobCardItem[^"]*"[^>]*>(.*?)</li>', re.S | re.I)
_ICIMS_A = re.compile(r'<a[^>]+href="(https?://[^"]*?/jobs/(\d+)/[^"]*?/job[^"]*)"', re.I)
_ICIMS_T = re.compile(r'<h3[^>]*>(.*?)</h3>', re.S | re.I)


def icims(board, terms, title_ok):
    seen, out = set(), []
    for term in terms:
        txt = http(f"https://{board}/jobs/search", retries=1, params={"ss": 1, "searchKeyword": term, "in_iframe": 1}).text
        for body in _ICIMS_CARD.findall(txt):
            a, t = _ICIMS_A.search(body), _ICIMS_T.search(body)
            if not a or not t:
                continue
            title = re.sub(r"<[^>]+>|\s+", " ", t.group(1)).strip()
            title = __import__("html").unescape(title)
            jid = a.group(2)
            if jid in seen or not title_ok(title):
                continue
            seen.add(jid)
            plain = re.sub(r"<[^>]+>", " ", body)
            m = re.search(r"(?i)location\s*:?\s*([^\n]{2,80}?)\s{2,}", plain)
            url = a.group(1).replace("?in_iframe=1", "").replace("&in_iframe=1", "")
            out.append(cand("icims", board, jid, title, pretty(board.split(".")[0].replace("careers-", "").replace("uscareers-", "")),
                            [((m.group(1) if m else "").strip(), "")], url, "", date_est=True, detail=page_detail))
            out[-1]["nodate"] = True
    return out, None


# ---------- ADP Workforce Now ----------
def adp(board):
    cid, cc = board.split("|")
    root = "https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions"
    q = {"cid": cid, "ccId": cc, "lang": "en_US", "locale": "en_US"}
    d = http(root, retries=1, params=dict(q, **{"$top": 100, "$skip": 0})).json()
    out = []
    for j in d.get("jobRequisitions") or []:
        iid = j.get("itemID")
        locs = []
        for l in j.get("requisitionLocations") or []:
            a = l.get("address") or {}
            locs.append((", ".join(x for x in ((l.get("nameCode") or {}).get("shortName"), a.get("cityName"),
                                               (a.get("countrySubdivisionLevel1") or {}).get("codeValue")) if x),
                         "United States" if (a.get("country") or {}).get("codeValue") in ("US", "USA") else (a.get("country") or {}).get("codeValue") or ""))

        def detail(c, iid=iid):
            x = http(f"{root}/{iid}", retries=1, params=q).json()
            c["desc"] = x.get("requisitionDescription") or ""

        out.append(cand("adp", board, iid, j.get("requisitionTitle"), pretty(j.get("organizationName") or "") or "ADP employer", locs or [("", "")],
                        f"https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid={cid}&ccId={cc}&jobId={iid}&lang=en_US",
                        j.get("postDate"), detail=detail))
    return out, {c["id"] for c in out}


# ---------- Paycom (session from the portal page, then keyword search) ----------
def paycom(board, terms, title_ok):
    import base64, json as _json
    portal = f"https://www.paycomonline.net/v4/ats/web.php/portal/{board}/career-page"
    m = re.search(r"var configsFromHost = (\{.*?\});\s*var Mountable", http(portal, retries=1).text, re.S)
    if not m:
        raise RuntimeError("no portal config")
    cfgp = _json.loads(m.group(1))
    lib = _json.loads(cfgp.get("libConfig") or "{}")
    svc = (lib.get("atsPortalMantleServiceUrl") or "").rstrip("/")
    if not re.match(r"^https://[a-z0-9.\-]+\.paycomonline\.(net|com)(/|$)", svc):
        raise RuntimeError("unexpected service address")
    hdr = {"Authorization": cfgp.get("sessionJWT") or "", "Locale": lib.get("locale") or "en-US", "Translation-Highlights": "false",
           "Portal-Host-Referrer": portal, "Content-Type": "application/json"}
    seen, out = set(), []
    for term in terms:
        d = http(svc + "/api/ats/job-posting-previews/search", method="POST", retries=1, headers=hdr,
                 json={"skip": 0, "take": 50, "filtersForQuery": {"distanceFrom": 0, "workEnvironments": [], "positionTypes": [],
                       "educationLevels": [], "categories": [], "travelTypes": [], "shiftTypes": [], "otherFilters": [],
                       "keywordSearchText": term, "location": "", "sortOption": ""}}).json()
        for j in d.get("jobPostingPreviews") or d.get("jobs") or d.get("results") or []:
            jid = str(j.get("jobId") or "")
            if not jid or jid in seen or not title_ok(j.get("jobTitle")):
                continue
            seen.add(jid)
            loc = j.get("locations") if isinstance(j.get("locations"), str) else ", ".join(map(str, j.get("locations") or []))
            env = str(j.get("workEnvironment") or j.get("remoteType") or "").lower()
            out.append(cand("paycom", board, jid, j.get("jobTitle"), j.get("companyName") or "Paycom employer", [(loc, "")],
                            f"https://www.paycomonline.net/v4/ats/web.php/portal/{board}/jobs/{jid}", j.get("postedOn"),
                            remote=True if "remote" in env else None, desc=j.get("description") or "", detail=page_detail))
            out[-1]["weak_company"] = True
    return out, None


SEARCH = {"paycom": paycom, "oracle": oracle, "ukg": ukg, "jibe": jibe, "icims": icims}   # readers that take search terms

# ---------- Dayforce ----------
def dayforce(board):
    tenant, code = board.split("|")
    rows = http(f"https://www.dayforcehcm.com/api/{tenant}/V1/JobFeeds", retries=1,
                params={"includeActivePostingOnly": "true", "internalJobBoardCode": code}).json()
    out, seen = [], set()
    for j in rows if isinstance(rows, list) else []:
        ref = str(j.get("ReferenceNumber") or j.get("JobPostingId") or "")
        if not ref or ref in seen:
            continue
        seen.add(ref)
        posted = next((j[k] for k in ("PostingStartTimestampUTC", "PostingStartDate", "DatePosted", "PostedDate", "StartDate") if j.get(k)), "")
        out.append(cand("dayforce", board, ref, j.get("Title"), j.get("CompanyName") or j.get("ParentCompanyName") or pretty(tenant),
                        [(", ".join(x for x in (j.get("City"), j.get("State")) if x), "United States" if str(j.get("Country", "")).upper() in ("US", "USA") else j.get("Country") or "")],
                        f"https://jobs.dayforcehcm.com/{j.get('CultureCode') or 'en-US'}/{tenant}/{code}/jobs/{ref}", posted,
                        remote=True if j.get("IsVirtualLocation") else None, desc=j.get("Description") or "", date_est=not posted))
    return out, {c["id"] for c in out}


# ---------- Paylocity ----------
def paylocity(board):
    import json as _json
    txt = http(f"https://recruiting.paylocity.com/Recruiting/Jobs/All/{board}", retries=1).text
    m = re.search(r"\bwindow\.pageData\s*=\s*", txt)
    if not m:
        raise RuntimeError("no page data")
    data, _ = _json.JSONDecoder().raw_decode(txt[m.end():])
    out = []
    for j in data.get("Jobs") or []:
        if j.get("IsInternal"):
            continue
        jid = j.get("JobId")
        out.append(cand("paylocity", board, jid, j.get("JobTitle"), data.get("CompanyName") or "Paylocity employer",
                        [(j.get("LocationName") or "", "")], f"https://recruiting.paylocity.com/Recruiting/Jobs/Details/{jid}",
                        j.get("PublishedDate"), remote=True if j.get("IsRemote") else None, detail=page_detail))
    return out, {c["id"] for c in out}


# ---------- SuccessFactors (Recruiting Marketing RSS feed) ----------
def successfactors(board):
    import xml.etree.ElementTree as ET
    G = "{http://base.google.com/ns/1.0}"
    root = ET.fromstring(http(f"https://{board}/sitemal.xml", retries=1).content)
    out = []
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        jid = it.findtext(G + "id") or it.findtext("guid") or link
        title = re.sub(r"\s*\([^)]*\)\s*$", "", (it.findtext("title") or "").strip())
        out.append(cand("successfactors", board, jid, title, it.findtext(G + "employer") or pretty(board.split(".")[0]),
                        [(it.findtext(G + "location") or "", "")], link, it.findtext("pubDate"), desc=it.findtext("description") or ""))
    return out, {c["id"] for c in out}


# ---------- Personio ----------
def personio(board):
    rows = http(f"https://{board}.jobs.personio.com/search.json", retries=1).json()
    out = []
    for j in rows if isinstance(rows, list) else rows.get("jobs") or []:
        jid = j.get("id")
        office = j.get("office") if isinstance(j.get("office"), str) else (j.get("office") or {}).get("name", "")
        out.append(cand("personio", board, jid, j.get("name") or j.get("title"), j.get("subcompany") or pretty(board), [(office, "")],
                        f"https://{board}.jobs.personio.com/job/{jid}", j.get("createdAt") or j.get("created_at"),
                        desc="".join(f"<h3>{d.get('name','')}</h3>{d.get('value','')}" for d in j.get("jobDescriptions") or [] if isinstance(d, dict)),
                        detail=page_detail))
    return out, {c["id"] for c in out}


# ---------- Jobvite ----------
def jobvite(board):
    txt = http(f"https://jobs.jobvite.com/{board}/search", retries=1, params={"q": ""}).text
    out, seen = [], set()
    for m in re.finditer(r'<a[^>]+href="(/[^"]*/job/([A-Za-z0-9_-]+))[^"]*"[^>]*>(.*?)</a>', txt, re.S):
        jid = m.group(2)
        title = re.sub(r"<[^>]+>|\s+", " ", m.group(3)).strip()
        if jid in seen or not title:
            continue
        seen.add(jid)
        row = txt[m.end():m.end() + 600]
        loc = re.search(r'jv-job-list-location[^>]*>(.*?)</', row, re.S)
        out.append(cand("jobvite", board, jid, __import__("html").unescape(title), pretty(board),
                        [(re.sub(r"<[^>]+>|\s+", " ", loc.group(1)).strip() if loc else "", "")],
                        f"https://jobs.jobvite.com{m.group(1)}", "", date_est=True, detail=page_detail))
        out[-1]["nodate"] = True
    return out, {c["id"] for c in out}


# ---------- JazzHR (company.applytojob.com) ----------
def jazzhr(board):
    import html as _html
    txt = http(f"https://{board}.applytojob.com/apply", retries=1).text
    name = re.search(r"<title>(.*?)</title>", txt, re.S)
    company = re.sub(r"(?i)\s*[-|]\s*(career page|careers|jobs|job openings).*$", "", _html.unescape(name.group(1)).strip()) if name else ""
    out, seen = [], set()
    for m in re.finditer(r'<a[^>]+href="((?:https?://[^"/]+)?/apply/([A-Za-z0-9]{6,})/[^"?#]*)[^"]*"[^>]*>(.*?)</a>', txt, re.S):
        jid = m.group(2)
        title = _html.unescape(re.sub(r"<[^>]+>|\s+", " ", m.group(3))).strip()
        if jid in seen or not title or jid == "jobs":
            continue
        seen.add(jid)
        row = txt[m.end():m.end() + 700].split("<a ", 1)[0]
        loc = re.search(r"fa-map-marker[^>]*>\s*(?:</i>)?\s*([^<]+)", row)
        url = m.group(1) if m.group(1).startswith("http") else f"https://{board}.applytojob.com{m.group(1)}"
        out.append(cand("jazzhr", board, jid, title, company if 1 < len(company) < 60 else pretty(board),
                        [(_html.unescape(loc.group(1)).strip() if loc else "", "")], url, "", date_est=True, detail=jazzhr_detail))
        out[-1]["nodate"] = True
    return out, {c["id"] for c in out}


def jazzhr_detail(c):
    txt = http(c["url"], retries=1).text
    jp = ld_jobposting(txt)
    if jp:
        if len(jp.get("description") or "") > 300:
            c["desc"] = jp["description"]
        d = iso(jp.get("datePosted") or "")
        if d:
            c["posted"], c["date_est"] = d, False
        if "TELECOMMUTE" in str(jp.get("jobLocationType", "")).upper():
            c["remote"] = True
    if not c["desc"]:
        m = re.search(r'id="job-description"[^>]*>(.*?)(?:<div[^>]+id="(?:resumator-application|job-apply|resumator-buttons)|<form|</main>|<footer)', txt, re.S)
        if m and len(m.group(1)) > 300:
            c["desc"] = m.group(1)


SIMPLE = {"jazzhr": jazzhr, "dayforce": dayforce, "paylocity": paylocity, "successfactors": successfactors, "personio": personio, "jobvite": jobvite,
          "adp": adp, "bamboohr": bamboohr, "workable": workable, "pinpoint": pinpoint, "recruiterbox": recruiterbox,
          "teamtailor": teamtailor, "gem": gem, "greenhouse": greenhouse, "lever": lever, "ashby": ashby, "smartrecruiters": smartrecruiters,
          "breezy": breezy, "rippling": rippling, "recruitee": recruitee}
