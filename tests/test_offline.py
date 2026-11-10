import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import yaml, radar
cfg = yaml.safe_load(open(pathlib.Path(radar.ROOT) / "config.yaml"))
J = lambda t, loc, rf=None, src="x", c="Acme", posted="": radar.job(src, t+loc, t, c, loc, "https://x/y", posted or radar.NOW.isoformat(), remote=rf)
cases = [
 (J("Senior SDET", "Remote - US"), True), (J("QA Automation Engineer", "United States", True), True),
 (J("Staff Software Engineer in Test", "Remote, USA"), True), (J("AI Evaluation Engineer", "", True), True),
 (J("Senior Quality Engineer, AI", "Remote (Raleigh, NC)"), True), (J("QA Engineer", "Worldwide", True), True),
 (J("Junior Software QA", "Remote US"), True), (J("Entry Level AI QA Engineer", "Remote US"), True), (J("Associate QA Engineer", "Remote, USA"), True), (J("QA Intern", "Remote US"), False), (J("QA Engineer", "San Francisco, CA"), False),
 (J("QA Engineer", "Remote - Germany"), False), (J("SDET", "Europe", True), False),
 (J("Software Engineer", "Remote US"), False), (J("Hardware Test Engineer", "Remote US"), False),
 (J("Director of Quality Engineering", "Remote US"), False), (J("Test Automation Lead", "Remote, Canada"), False),
 (J("SDET", "Remote US", posted="2026-01-01T00:00:00+00:00"), False), (J("LLM Evals Engineer", "Remote, United States"), True),
 (J("Quality Assurance Analyst", "USA", True), False), (J("Physician (MD/DO) - Medical AI Evaluation", "United States", True), False),
 (J("Automation Engineer - Patching", "United States", True), False), (J("Senior QA Automation Engineer", "Time zone: CET (+/- 3 hours)", True), False),
 (J("Senior AI Test Engineer", "United States", True), True), (J("Senior QA Engineer", "US or Canada", True), True),
]
bad = [(j["title"], j["location"], exp) for j, exp in cases if bool(radar.select([dict(j)], cfg)) != exp]
assert not bad, bad
assert radar.iso(1762800000) and radar.iso(1762800000000) and radar.iso("Tue, 10 Nov 2026 12:00:00 +0000") and radar.iso("2026-11-10T12:00:00Z")
assert radar.money(120000, 150000) == "$120,000 – $150,000" and radar.money(0, None) == ""
d = radar.select([dict(cases[0][0]), dict(cases[0][0], id="other:1")], cfg); assert len(d) == 1
print("offline tests ok:", len(cases), "cases")
