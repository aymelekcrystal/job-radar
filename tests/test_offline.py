"""Offline tests: rules and parsers, no network. Run: python tests/test_offline.py"""
import json, pathlib, sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import yaml
from jr import filters as F, notify, sources, wide
from jr.common import to_lines, iso, money, ld_jobposting, NOW, ET
import radar

cfg = yaml.safe_load(open(pathlib.Path(__file__).parent.parent / "config.yaml"))
T = F.Titles(cfg)
fails = []
def eq(name, got, exp):
    if got != exp: fails.append(f"{name}: got {got!r}, expected {exp!r}")

# ---- titles ----
for _t in ("Cloud Validation & Release Engineer", "UAT Analyst", "Release Engineer", "AI Trainer", "Accessibility Specialist", "Test Lead"):
    assert T.ok(_t), _t
for _t in ("Technical Support Engineer", "Solutions Engineer", "Business Analyst", "Product Owner", "Technical Program Manager",
           "Design Verification Engineer", "Process Validation Engineer", "Software Engineer", "Clinical Quality Specialist"):
    assert not T.ok(_t), _t
_fit = lambda *b: F.ece_fit(["Requirements"] + ["• " + x for x in b])
assert _fit("3+ years in QA / validation / release engineering", "Test-automation skills (Python, CI / CD)", "Experience with regression testing", "Detail-oriented")
assert not _fit("7+ years of experience in customer support", "Experience with Kubernetes", "Debugging code in Java, Python", "Write test cases", "Regression testing")
assert not _fit("Proficient in front-end development using React", "Proficient in testing and debugging techniques", "Write test plans", "Python")
assert not _fit("Gather business requirements", "Stakeholder interviews", "Strong communication", "Support UAT")
assert F.testing_text("Write test cases and test plans, build Selenium and Playwright suites, own regression") and not F.testing_text("Build React apps and write unit tests")
assert T.maybe("Software Engineer II") and not T.maybe("Software Engineer Intern")
assert not F.ece_fit(["Requirements", "• Write test cases", "• Regression testing", "• Python", "• AWS", "• Communication", "• Docker"], strict=True)
assert F.ece_fit(["Requirements", "• Write test cases", "• Regression testing", "• Selenium or Playwright", "• Python", "• Communication"], strict=True)
assert T.qa("QA Engineer") and T.qa("Product Validation Lead")

for t, exp in [("Senior SDET", True), ("QA Automation Engineer", True), ("Software Engineer in Test", True), ("Junior QA Engineer", True),
               ("LLM Evaluation Engineer", True), ("AI Model Evaluator", True), ("API Test Engineer", True), ("UAT Tester", True),
               ("Manual Tester", True), ("Software Quality Engineer II", True), ("Staff Quality Engineer, AI Platform", True),
               ("Automation Test Developer", True), ("Agent Evaluation Engineer", True), ("Evaluation Specialist", True),
               ("QA Intern", False), ("Director of Quality Engineering", False), ("Hardware Test Engineer", False),
               ("Supplier Quality Engineer", False), ("GCP QA Auditor III", False), ("QA and Compliance Manager", False),
               ("Quality Assurance Supervisor (Workforce Compliance)", False), ("Data Quality Engineer", False),
               ("Air Quality Engineer", False), ("Software Engineer", False), ("Manufacturing Quality Engineer", False),
               ("Localization QA Tester - Norwegian", False), ("Clinical Quality Assurance Specialist", False),
               ("Medical Device Software QA Engineer", True), ("Call Center QA Analyst", False), ("QA Analyst", True),
               ("Offensive Cybersecurity Engineers: Build RL Environments", False), ("Sr. QA Manager", True)]:
    eq("title " + t, T.ok(t), exp)

# ---- location ----
C = lambda locs, rem=None, title="", desc="": F.classify(locs, rem, title, desc)[0]
for name, got, exp in [
    ("remote US", C([("Remote - United States", "")]), "ok"), ("remote state", C([("Remote, TX", "")]), "ok"),
    ("any state", C([("Remote (Any State)", "")]), "ok"), ("flag+country", C([("New York", "United States")], True), "ok"),
    ("raleigh onsite", C([("Raleigh, NC", "")]), "ok"), ("durham hybrid", C([("Durham, NC", "")], False), "ok"),
    ("durham uk", C([("Darlington, County Durham, United Kingdom", "GB")]), "drop"),
    ("remote only", C([("Remote", "")]), "check"), ("remote intl", C([("Remote - International", "")]), "drop"),
    ("amer", C([("Remote in AMER", "")]), "drop"), ("latam", C([("LATAM Remote", "")]), "drop"),
    ("canada", C([("Remote, Canada", "")]), "drop"), ("us or canada", C([("Remote - US or Canada", "")]), "ok"),
    ("multi one us", C([("Remote (Canada)", "Canada"), ("Remote (US)", "United States")]), "ok"),
    ("sf onsite", C([("San Francisco, CA", "")], desc="We work from our office."), "drop"),
    ("sf strong remote desc", C([("San Francisco, CA", "")], desc="This is a fully remote role."), "check"),
    ("remote DE", C([("Remote,DE | München", "")]), "drop"), ("remote ambiguous DE", C([("Remote, DE", "")]), "drop"),
    ("india 3part", C([("Remote, KA, IN", "")]), "drop"), ("unknown place", C([("Cheltenham", "")], True), "drop"),
    ("thb", C([("Chiang Mai,Remote (THB)", "")]), "drop"), ("sg", C([("SG, 486018", "")], True), "drop"),
    ("mx", C([("MX Remote Work, MX", "")]), "drop"), ("mexico title", C([("Remote", "")], None, "FBS (Mexico) - Sr. QA Engineer"), "drop"),
    ("remote NY NY US", C([("Remote NY, NY, US", "")]), "ok"), ("virtual US", C([("Virtual, US", "")]), "ok"),
    ("select states", C([("Remote (select US states)", "")]), "ok"), ("zip", C([("Durham, NC, US, 27712", "")]), "ok"),
    ("city CA", C([("Saratoga, CA", "")], True), "ok"), ("not remote desc", C([("United States", "")], True, desc="THIS IS NOT A REMOTE POSITION Stafford"), "drop"),
    ("remote worker na", C([("Remote Worker - N/A", "")]), "check"), ("title US remote", C([("Remote", "")], None, "Senior QA Engineer - US Remote"), "ok"),
    ("title us lowercase word", C([("Remote", "")], None, "QA Engineer, join us"), "check"), ("remote kentucky", C([("Remote Kentucky", "")]), "ok"),
    ("us only no desc", C([("United States", "")]), "check"), ("us only desc no remote", C([("United States", "")], desc="Join us in the office."), "drop"),
    ("us only remote flag", C([("US", "")], True, desc="x"), "ok"), ("bogota flag", C([("Bogotá, Bogota, co", "")], True), "drop"),
    ("kyiv", C([("Kyiv, UA", "")], True), "drop"), ("title remote", C([("United States", "")], None, "QA Engineer (Remote)"), "ok"),
    ("empty", C([]), "drop"), ("poland code", C([("POL Remote - USVP", "")]), "drop"),
    ("no remote", C([("United States - no remote", "")], desc="x"), "drop"), ("india", C([("Remote", "India")]), "drop")]:
    eq("loc " + name, got, exp)

# ---- degree ----
D = lambda html: F.degree(to_lines(html))
eq("deg required", D("<h3>Requirements</h3><ul><li>Bachelor's degree in Computer Science</li><li>5 years QA</li></ul>"), "required")
eq("deg related field", D("<ul><li>BS in Computer Science or related field</li></ul>"), "required")
eq("deg equivalent", D("<ul><li>Bachelor's degree or equivalent experience</li></ul>"), "alt")
eq("deg or years", D("<ul><li>BS/BA in CS or 4+ years of relevant work experience</li></ul>"), "alt")
eq("deg or work exp", D("<p>Bachelor's degree in engineering or relevant work experience required.</p>"), "alt")
eq("deg preferred", D("<ul><li>Bachelor's degree preferred</li></ul>"), "alt")
eq("deg pref head", D("<h3>Nice to have</h3><ul><li>Master's degree in CS</li></ul><h3>Requirements</h3><ul><li>3 years testing</li></ul>"), "alt")
eq("deg none", D("<ul><li>5 years of test automation</li><li>High degree of ownership</li></ul>"), "none")
eq("deg ms office", D("<ul><li>Experience with MS Office</li><li>BA experience, writing test plans</li></ul>"), "none")
eq("deg unknown", F.degree([]), "unknown")
eq("deg next line or", D("<ul><li>Bachelor's degree in CS</li><li>or equivalent practical experience</li></ul>"), "alt")
eq("deg masters req", D("<ul><li>Master's degree in Statistics required</li></ul>"), "required")

# ---- flattened dataset text ----
flat = ("NTT DATA strives to hire exceptional people. We are seeking a Mobile Test Engineer to join our team in Durham. Job Responsibilities Include: "
        "Use your knowledge of testing to influence better software design. Collaborate with team members on test coverage. Basic Qualifications: "
        "5+ years of testing experience in test automation with Rest Assured and JUnit. Bachelor's degree in Computer Science. Preferred Skills: "
        "Experience in crafting robust QA strategies. Master's degree is a plus. About Us We are a global company with many offices around the world.")
fl = to_lines(flat)
eq("flat degree", F.degree(fl), "required")
eq("flat reqs", F.requirements(fl)[:1], ["5+ years of testing experience in test automation with Rest Assured and JUnit"])
eq("flat alt", F.degree(to_lines(flat.replace("Bachelor's degree in Computer Science.", "Bachelor's degree in Computer Science or equivalent experience."))), "alt")
eq("software generic no", F.software_role(False, "Ensure GMP compliance in our manufacturing plant. Use Minitab software."), False)
eq("software generic yes", F.software_role(False, "Lead software quality assurance and testing strategies for platforms."), True)
eq("software strong", F.software_role(True, "GMP manufacturing"), True)
eq("automation engineer devops", F.testing_role("Platform Automation Engineer", "Terraform, Kubernetes, CI/CD pipelines, Python"), False)
eq("automation engineer testing", F.testing_role("Automation Engineer", "Build Selenium and Playwright test automation; write test cases; regression"), True)
eq("automation engineer qa title", F.testing_role("QA Automation Engineer", ""), True)
eq("tidy salary", [F.tidy_salary("71600.00 to 116550.00"), F.tidy_salary("$150K – $180K"), F.tidy_salary("EUR 50000"), F.tidy_salary("")], ["$71,600 – $116,550", "$150K – $180K", "", ""])
for t, exp in [("Quality Engineer (Chemical)", False), ("QA Engineer, Drug Product - Second Shift", False), ("QA Automation Engineer (m/f/d)", False),
               ("Sterilization Assurance Quality Engineer", False), ("Acoustic and Audio Test Engineer", False)]:
    eq("title " + t, T.ok(t), exp)

# ---- requirements + salary ----
html = ("<p>About us: we build things.</p><h3>What you'll do</h3><ul><li>Write automated tests for the platform</li></ul>"
        "<p><strong>Requirements:</strong></p><ul><li>5+ years of test automation with Playwright or Selenium</li><li>API testing with Postman</li>"
        "<li>CI/CD experience (Jenkins, GitHub Actions)</li><li>Bachelor's degree or equivalent experience</li><li>Strong SQL</li></ul>"
        "<h3>Nice to have</h3><ul><li>Experience with LLM evaluation</li></ul><p>The salary range is $105,000 - $130,000 per year.</p>")
r = F.requirements(to_lines(html))
eq("reqs", r, ["5+ years of test automation with Playwright or Selenium", "API testing with Postman", "CI/CD experience (Jenkins, GitHub Actions)",
               "Bachelor's degree or equivalent experience"])
eq("reqs fallback", F.requirements(["Intro text here.", "• 3+ years experience with Cypress", "• Free lunch"]), ["3+ years experience with Cypress"])
eq("salary", F.salary_from(" ".join(to_lines(html))), "$105,000 – $130,000")
eq("salary k", F.salary_from("Pay: $120k-$150K base"), "$120,000 – $150,000")
eq("salary hourly", F.salary_from("$50.00 - $70.00 per hour"), "$50.00 – $70.00 / hour")
eq("salary none", F.salary_from("We raised $50 million"), "")
eq("greenhouse double-encoded", to_lines("&lt;p&gt;Hello&lt;/p&gt;&lt;ul&gt;&lt;li&gt;One&lt;/li&gt;&lt;/ul&gt;"), ["Hello", "• One"])

# ---- parsers (shapes taken from live responses) ----
class R:
    def __init__(self, d): self.d = d; self.text = d if isinstance(d, str) else ""
    def json(self): return self.d
def fake(mapping):
    def http(url, method="GET", **kw):
        for k, v in mapping.items():
            if k in url: return R(v)
        raise AssertionError("unexpected url " + url)
    return http

sources.http = fake({"/jobs/77": {"content": "&lt;ul&gt;&lt;li&gt;3 years QA&lt;/li&gt;&lt;/ul&gt;", "offices": [{"name": "US Remote", "location": "United States"}]},
                     "boards/acme/jobs": {"jobs": [{"id": 77, "title": "QA Engineer", "location": {"name": "Remote"}, "absolute_url": "https://acme.com/j/77",
                                                    "first_published": "2026-11-11T10:00:00-05:00", "company_name": "Acme"}]}})
cs, ids = sources.greenhouse("acme")
eq("gh id", cs[0]["id"], "greenhouse:acme:77"); eq("gh posted", cs[0]["posted"], "2026-11-11T15:00:00+00:00"); eq("gh ids", ids, {"greenhouse:acme:77"})
cs[0]["detail"](cs[0]); eq("gh detail locs", cs[0]["locs"][-1], ("US Remote United States", "")); eq("gh desc", to_lines(cs[0]["desc"]), ["• 3 years QA"])

sources.http = fake({"lever.co": [{"id": "a1", "text": "SDET", "categories": {"location": "Remote", "allLocations": ["Remote", "Austin, TX"]}, "country": "US",
                                    "workplaceType": "remote", "createdAt": 1786469891368, "hostedUrl": "https://jobs.lever.co/acme/a1", "description": "<p>Hi</p>",
                                    "lists": [{"text": "Requirements", "content": "<li>3+ years of Python test automation</li>"}], "salaryRange": {"min": 100000, "max": 140000, "currency": "USD", "interval": "per-year-salary"}}]})
c = sources.lever("acme")[0][0]
eq("lever", (c["remote"], c["locs"][0], c["salary"], F.requirements(to_lines(c["desc"]))), (True, ("Remote", "United States"), "$100,000 – $140,000", ["3+ years of Python test automation"]))
eq("lever class", F.classify(c["locs"], c["remote"])[0], "ok")

sources.http = fake({"ashbyhq": {"jobs": [{"id": "u1", "title": "Senior Quality Engineer", "location": "New York, NY (HQ)", "isListed": True, "workplaceType": "Remote",
    "address": {"postalAddress": {"addressCountry": "United States"}}, "secondaryLocations": [{"location": "Remote (Canada)", "address": {"postalAddress": {"addressCountry": "Canada"}}}],
    "publishedAt": "2026-11-10T12:00:00.000+00:00", "jobUrl": "https://jobs.ashbyhq.com/acme/u1", "descriptionHtml": "<p>x</p>",
    "compensation": {"compensationTierSummary": "$150K – $180K"}}, {"id": "u2", "title": "Hidden", "isListed": False}]}})
cs, ids = sources.ashby("acme")
eq("ashby", (len(cs), cs[0]["remote"], cs[0]["salary"], F.classify(cs[0]["locs"], cs[0]["remote"])[0]), (1, True, "$150K – $180K", "ok"))

eq("wd age", [sources.workday_age(x) for x in ("Posted Today", "Posted Yesterday", "Posted 3 Days Ago", "Posted 30+ Days Ago", "")], [0, 1, 3, 31, None])
sources.http = fake({"/job/Remote/QA_R1": {"jobPostingInfo": {"startDate": "2026-10-20", "location": "Remote - United States", "additionalLocations": ["Durham, NC"],
    "country": {"descriptor": "United States of America"}, "jobDescription": "<p>d</p>", "externalUrl": "https://t.wd1.myworkdayjobs.com/S/job/Remote/QA_R1", "canApply": True}},
    "/jobs": {"total": 2, "jobPostings": [{"title": "QA Engineer", "externalPath": "/job/Remote/QA_R1", "locationsText": "2 Locations", "postedOn": "Posted 3 Days Ago"},
                                          {"title": "Chef", "externalPath": "/job/x/Chef_R2", "locationsText": "Austin", "postedOn": "Posted Today"},
                                          {"title": "QA Lead", "externalPath": "/job/x/QA_R3", "locationsText": "Austin", "postedOn": "Posted 30+ Days Ago"}]}})
cs, ids = sources.workday("t|wd1|S", ["QA"], T.ok)
eq("wd list", (len(cs), cs[0]["multi"], ids, cs[0]["id"]), (1, True, None, "workday:t|wd1|S:QA_R1"))
cs[0]["detail"](cs[0])
eq("wd detail", (cs[0]["locs"], cs[0]["posted"][:10], cs[0]["date_est"]), ([("Remote - United States", "United States of America"), ("Durham, NC", "United States of America")], "2026-10-20", False))

sources.http = fake({"/careers/5/detail": {"result": {"jobOpening": {"description": "<ul><li>4 years of QA automation</li></ul>", "datePosted": "2026-11-09", "locationType": "1"}}},
                     "/careers/list": {"result": [{"id": 5, "jobOpeningName": "QA Engineer", "location": {"city": "Austin", "state": "Texas"}, "atsLocation": {"country": "United States"}, "locationType": "1"}]}})
c = sources.bamboohr("acme")[0][0]; c["detail"](c)
eq("bamboo", (c["id"], c["remote"], c["locs"][0], c["posted"][:10], c["date_est"]), ("bamboohr:acme:5", True, ("Austin, Texas", "United States"), "2026-11-09", False))
sources.http = fake({"widget/accounts/acme": {"name": "Acme Inc", "jobs": [{"title": "SDET", "shortcode": "AB12", "url": "https://apply.workable.com/acme/j/AB12/", "published_on": "2026-11-10",
    "telecommuting": True, "locations": [{"country": "United States", "countryCode": "US", "city": "Denver", "region": "Colorado"}], "description": "<p>d</p>"}]}})
c = sources.workable("acme")[0][0]
eq("workable", (c["company"], c["remote"], c["locs"], F.classify(c["locs"], c["remote"])[0]), ("Acme Inc", True, [("Denver, Colorado", "United States")], "ok"))
sources.http = fake({"postings.json": {"data": [{"id": 9, "title": "Test Engineer", "description": "<p>x</p>", "skills_knowledge_expertise": "<ul><li>3 years of software testing</li></ul>",
    "location": {"name": "Remote - US"}, "workplace_type": "remote", "url": "https://acme.pinpointhq.com/postings/9", "first_published_at": "2026-11-10T10:00:00Z"}]}})
c = sources.pinpoint("acme")[0][0]
eq("pinpoint", (c["remote"], c["date_est"], F.requirements(to_lines(c["desc"]))), (True, False, ["3 years of software testing"]))
class RC:
    content = b'<rss xmlns:tt="https://teamtailor.com/locations"><channel><item><title>QA Lead</title><link>https://a.teamtailor.com/jobs/1</link><guid>g1</guid><pubDate>Tue, 10 Nov 2026 12:00:00 +0000</pubDate><description>d</description><remoteStatus>fully</remoteStatus><tt:locations><tt:location><tt:name>New York</tt:name><tt:country>United States</tt:country></tt:location></tt:locations></item></channel></rss>'
sources.http = lambda url, **kw: RC()
c = sources.teamtailor("a")[0][0]
eq("teamtailor", (c["title"], c["remote"], c["locs"], c["posted"][:10]), ("QA Lead", True, [("New York", "United States")], "2026-11-10"))
sources.http = fake({"graphql": [{"data": {"oatsExternalJobPostings": {"jobPostings": [{"id": "i", "extId": "e1", "title": "QA Engineer", "locations": [{"name": "Remote", "isoCountry": "US", "isRemote": True}], "job": {"locationType": "REMOTE"}}]}}}]})
c = sources.gem("acme")[0][0]
eq("gem", (c["id"], c["remote"], c["locs"], c["url"]), ("gem:acme:e1", True, [("Remote", "United States")], "https://jobs.gem.com/acme/e1"))

jp = ld_jobposting('<html><script type="application/ld+json">{"@context":"http://schema.org","@type":"JobPosting","description":"<p>desc</p>","datePosted":"2026-11-09","jobLocationType":"TELECOMMUTE","applicantLocationRequirements":{"@type":"Country","name":"USA"}}</script></html>')
eq("ldjson", (jp or {}).get("datePosted"), "2026-11-09")

eq("board_of", [wide.board_of("workday", "https://availity.wd1.myworkdayjobs.com/en-US/Availity_Careers_US/job/x"), wide.board_of("greenhouse", "https://job-boards.greenhouse.io/covar/jobs/5"),
                wide.board_of("smartrecruiters", "https://jobs.smartrecruiters.com/CrownInnovationsInc/744"), wide.board_of("breezy", "https://zact-inc.breezy.hr/p/ad4"),
                wide.board_of("rippling", "https://ats.rippling.com/rovia/jobs/c8"), wide.board_of("ashby", "https://jobs.ashbyhq.com/credo.ai/37")],
   ["availity|wd1|Availity_Careers_US", "covar", "CrownInnovationsInc", "zact-inc", "rovia", "credo.ai"])
eq("host_company", [wide.host_company("jobs.thermofisher.com"), wide.host_company("Zact Inc.")], ["Thermofisher", "Zact Inc."])

# ---- schedule ----
et = lambda h, m: datetime(2026, 11, 11, h, m, tzinfo=ET)
eq("slot before", radar.slot_due(["09:30", "15:00"], None, et(9, 0)), False)
eq("slot first", radar.slot_due(["09:30", "15:00"], None, et(9, 45)), True)
eq("slot done", radar.slot_due(["09:30", "15:00"], et(9, 40).isoformat(), et(11, 0)), False)
eq("slot second", radar.slot_due(["09:30", "15:00"], et(9, 40).isoformat(), et(15, 5)), True)
eq("slot yesterday", radar.slot_due(["09:30"], (et(9, 40) - timedelta(days=1)).isoformat(), et(9, 31)), True)
eq("quiet", [notify.quiet(et(h, 0), cfg) for h in (22, 23, 3, 6, 7)], [False, True, True, True, False])

# ---- message ----
j = {"kind": "ok", "src": "Workday", "title": "Senior QA Automation Engineer", "company": "Availity", "location": "Remote - United States", "why": "",
     "salary": "$105,000 – $130,000", "reqs": ["5+ years test automation", "API testing"], "url": "https://x/y", "posted": iso(NOW - timedelta(minutes=40)),
     "first_seen": iso(NOW), "date_est": False}
m = notify.fmt(j)
assert "🟢 NEW · posted 40 min ago" in m and "<b>Senior QA Automation Engineer</b>" in m and "Availity · Company site (Workday)" in m and "• API testing" in m and "Apply: https://x/y" in m, m
m2 = notify.fmt(dict(j, kind="check", why="Remote, but country not stated", date_est=True, salary="", reqs=[]))
assert "🟡 CHECK LOCATION · first seen" in m2 and "⚠️ Remote, but country not stated" in m2 and "Requirements" not in m2, m2
m3 = notify.fmt(dict(j, kind="platform", src="Indeed", direct_link=True))
assert "🔵 FROM INDEED" in m3 and "Indeed → company link" in m3, m3

# ---- several chats ----
calls = []
notify.send = lambda text, tok, c, thread=None, markup=None: (calls.append((c, thread)), True)[1]
notify.api = lambda tok, method, **p: ({"ok": True, "result": {"is_forum": p.get("chat_id") == "-100222"}} if method == "getChat"
                                         else {"ok": True, "result": {"message_thread_id": {"🟢": 5, "🟡": 6, "🔵": 7}[p["name"][0]]}})
notify.TG_FILE = pathlib.Path("/nonexistent/tg.json")
import os
os.environ["TELEGRAM_TOKEN"], os.environ["TELEGRAM_CHAT_ID"] = "t", "111, -100222"
stt = {"tg_hello": True, "tg_welcomed": ["*"]}
jj = [dict(j, id="x1", notify="pending")]
old_quiet = notify.quiet; notify.quiet = lambda *a: False; old_sleep = notify.time.sleep; notify.time.sleep = lambda s: None
res = notify.process(jj, stt, cfg)
eq("multi chat status", res, "sent 1 of 1")
eq("multi chat calls", calls, [("-100222", None), ("111", None), ("-100222", 5)])
calls.clear()
pj = [dict(j, id="p1", kind="platform", src="LinkedIn", notify="hold"), dict(j, id="c1", kind="check", why="x", notify="pending")]
eq("topics status", notify.process(pj, stt, cfg), "sent 2 of 2")
eq("topics routing", calls, [("111", None), ("-100222", 6), ("-100222", 7)])
stt2 = {"tg_hello": True, "tg_welcomed": ["111", "0222"], "tg_named": {"100222": {"linkedin": 42}}}
eq("named tab new", notify.topics_for("t", "-100222", stt2), {"ok": 5, "check": 6, "platform": 42})
deny = notify.api
notify.api = lambda tok, method, **p: {"ok": True, "result": {"is_forum": True}} if method == "getChat" else {"ok": False, "description": "not enough rights"}
stt3 = {"tg_named": {"100333": {"linkedin": 111}}}
eq("tabs denied -> only own tab", notify.topics_for("t", "-100333", stt3), {"platform": 111})
calls.clear(); os.environ["TELEGRAM_CHAT_ID"] = "-100333"; stt3.update(tg_hello=True, tg_welcomed=["0333"])
pj3 = [dict(j, id="p3", kind="platform", src="LinkedIn", notify="hold"), dict(j, id="c3", notify="pending")]
notify.process(pj3, stt3, cfg); eq("denied routing", calls, [("-100333", None), ("-100333", 111)])
notify.api = deny; os.environ["TELEGRAM_CHAT_ID"] = "111, -100222"
stt["tg_named"] = {"100222": {"linkedin": 42}}
eq("named tab override", notify.topics_for("t", "-100222", stt)["platform"], 42)
stt.pop("tg_named")
eq("button", json.loads(notify.button("x"))["inline_keyboard"][0][0]["callback_data"], "ap:" + notify.hid("x"))
os.environ["TELEGRAM_CHAT_ID"] = "111"
pj2 = [dict(j, id="p2", kind="platform", src="LinkedIn", notify="pending")]
notify.process(pj2, stt, cfg); eq("platform held without tabs", pj2[0]["notify"], "hold")
os.environ["TELEGRAM_CHAT_ID"] = "111, -100222"
eq("multi chat welcomed", stt["tg_welcomed"], ["111", "0222"])
notify.quiet, notify.time.sleep = old_quiet, old_sleep
del os.environ["TELEGRAM_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]

# ---- end-to-end decision ----
rd = radar.Radar.__new__(radar.Radar)
rd.cfg, rd.titles, rd.state, rd.jobs, rd.desc, rd.present = cfg, T, {"seen": {}, "dead": {}}, {}, {}, {}
mk = lambda i, title, locs, desc, **kw: dict(sources.cand("lever", "acme", i, title, "Acme", locs, f"https://jobs.lever.co/acme/{i}", iso(NOW - timedelta(hours=5)), desc=desc), **kw)
st = rd.decide([mk("1", "QA Engineer", [("Remote", "United States")], "<h3>Requirements</h3><ul><li>3 years of QA experience</li></ul>", remote=True),
                mk("2", "QA Engineer II", [("Remote", "United States")], "<ul><li>Bachelor's degree in CS required</li></ul>", remote=True),
                mk("3", "SDET", [("Berlin", "Germany")], "<p>x</p>"), mk("4", "Test Engineer", [("Remote", "")], "<p>Test our software from anywhere.</p>"),
                mk("5", "QA Engineer", [("Remote", "United States")], "<p>dup</p>", remote=True), mk("6", "Senior SDET", [("Raleigh, NC", "")], "")])
eq("decide stats", dict(st), {"accepted": 3, "degree": 1, "location": 1, "duplicate": 1})
eq("decide kinds", {k.split(":")[-1]: v["kind"] for k, v in rd.jobs.items()}, {"1": "ok", "4": "check", "6": "check"})
eq("decide why", rd.jobs["lever:acme:6"]["why"], "Description could not be read")
eq("decide seen", list(rd.state["seen"]), ["lever:acme:2"])
rd.present = {"lever/acme": {"lever:acme:4"}}
for v in rd.jobs.values(): v["first_seen"] = "2026-01-01T00:00:00+00:00"
eq("prune closed", (rd.prune(), sorted(rd.jobs)), (2, ["lever:acme:4"]))

print("FAILED:\n  " + "\n  ".join(fails) if fails else "offline tests ok")
sys.exit(1 if fails else 0)
