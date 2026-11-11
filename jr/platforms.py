"""Job platforms, used only to top the day up to the target when company sites give fewer postings."""
import re

from .common import http, iso, money
from .sources import cand

ORDER = ["linkedin", "indeed", "remotive", "himalayas", "remoteok", "jobicy", "wwr", "workingnomads"]


def _val(r, k):
    v = r.get(k)
    return "" if v is None or str(v) in ("nan", "NaT", "None") else v


def jobspy_site(site, cfg):
    from jobspy import scrape_jobs
    out, errs = [], []
    for term in cfg.get("platform_terms", []):
        kw = dict(site_name=[site], search_term=term, results_wanted=cfg.get("platform_results", 40), hours_old=24,
                  country_indeed="USA", verbose=0)
        kw.update({"location": "Remote"} if site == "indeed" else {"location": "United States", "is_remote": True})
        try:
            df = scrape_jobs(**kw)
        except Exception as ex:
            errs.append(f"{type(ex).__name__}: {str(ex)[:50]}")
            break
        for r in df.to_dict("records"):
            loc = str(_val(r, "location"))
            per = _val(r, "interval")
            sal = money(_val(r, "min_amount"), _val(r, "max_amount"), per="" if per in ("yearly", "") else str(per).replace("ly", ""))
            direct = str(_val(r, "job_url_direct"))
            c = cand(site, site, _val(r, "id") or _val(r, "job_url"), str(_val(r, "title")), str(_val(r, "company")),
                     [(loc, "")], direct or str(_val(r, "job_url")), str(_val(r, "date_posted")), remote=True, salary=sal,
                     desc=str(_val(r, "description")), date_est=True)
            c["direct_link"] = bool(direct)
            out.append(c)
    if not out and errs:
        raise RuntimeError("; ".join(errs))
    return out


def remotive(_):
    return [cand("remotive", "remotive", j["id"], j.get("title"), j.get("company_name"), [(j.get("candidate_required_location"), "")],
                 j.get("url"), j.get("publication_date"), remote=True, salary=j.get("salary") or "", desc=j.get("description") or "")
            for j in http("https://remotive.com/api/remote-jobs", params={"category": "qa"}).json().get("jobs", [])]


def remoteok(_):
    return [cand("remoteok", "remoteok", j.get("id"), j.get("position"), j.get("company"), [(j.get("location"), "")],
                 j.get("url") or j.get("apply_url"), j.get("date"), remote=True, salary=money(j.get("salary_min"), j.get("salary_max")),
                 desc=j.get("description") or "")
            for j in http("https://remoteok.com/api").json() if isinstance(j, dict) and "position" in j]


def himalayas(_):
    out, off = [], 0
    while off < 300:
        js = http("https://himalayas.app/jobs/api", params={"limit": 20, "offset": off}).json().get("jobs", [])
        if not js:
            break
        out += [cand("himalayas", "himalayas", j.get("guid") or j.get("applicationLink"), j.get("title"), j.get("companyName"),
                     [(", ".join(j.get("locationRestrictions") or []), "")], j.get("applicationLink") or j.get("guid"), j.get("pubDate"),
                     remote=True, salary=money(j.get("minSalary"), j.get("maxSalary")), desc=j.get("description") or "") for j in js]
        off += len(js)
    return out


def jobicy(_):
    js = http("https://jobicy.com/api/v2/remote-jobs", params={"count": 50, "geo": "usa", "tag": "qa"}).json().get("jobs", [])
    return [cand("jobicy", "jobicy", j.get("id"), j.get("jobTitle"), j.get("companyName"), [(j.get("jobGeo"), "")], j.get("url"),
                 j.get("pubDate"), remote=True, salary=money(j.get("annualSalaryMin"), j.get("annualSalaryMax")),
                 desc=j.get("jobDescription") or "") for j in js]


def wwr(_):
    import xml.etree.ElementTree as ET
    out = []
    for it in ET.fromstring(http("https://weworkremotely.com/remote-jobs.rss").content).iter("item"):
        company, _, title = (it.findtext("title") or "").partition(": ")
        out.append(cand("wwr", "wwr", it.findtext("guid") or it.findtext("link"), title or company, company if title else "",
                        [(it.findtext("region"), "")], it.findtext("link"), it.findtext("pubDate"), remote=True,
                        desc=it.findtext("description") or ""))
    return out


def workingnomads(_):
    return [cand("workingnomads", "workingnomads", j.get("url"), j.get("title"), j.get("company_name"), [(j.get("location"), "")],
                 j.get("url"), j.get("pub_date"), remote=True, desc=j.get("description") or "")
            for j in http("https://www.workingnomads.com/api/exposed_jobs/").json()]


SITES = {"linkedin": lambda cfg: jobspy_site("linkedin", cfg), "indeed": lambda cfg: jobspy_site("indeed", cfg),
         "remotive": remotive, "himalayas": himalayas, "remoteok": remoteok, "jobicy": jobicy, "wwr": wwr,
         "workingnomads": workingnomads}
NAMES = {"linkedin": "LinkedIn", "indeed": "Indeed", "remotive": "Remotive", "himalayas": "Himalayas", "remoteok": "RemoteOK",
         "jobicy": "Jobicy", "wwr": "We Work Remotely", "workingnomads": "Working Nomads"}
