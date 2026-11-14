# Job Radar

Personal job alert bot. It reads **company career sites first** and sends each new matching posting to Telegram.

Target: remote (US) and Raleigh-area QA / SDET / test automation / AI testing roles.

## How it works

| Tier | What | How often |
|---|---|---|
| Direct scan | Greenhouse, Lever, Ashby: every known company (about 19,000) | whole list every 2-3 hours; companies seen hiring QA every 15 min |
| Direct scan | SmartRecruiters, BambooHR, Workable, Rippling, Breezy, Recruitee, Teamtailor, Pinpoint, Gem, Recruiterbox (about 19,000 companies), Amazon | whole list every 2-4 hours; companies seen hiring QA hourly |
| Direct scan | Workday: companies seen hiring QA | hourly (a quarter of them every 15 min) |
| Direct scan | Workday: all ~12,000 companies | once a day, a slice every 15 min |
| Direct scan | Oracle Cloud, iCIMS, UKG, Jibe, ADP, Paycom, Dayforce, Paylocity, SuccessFactors, Personio, Jobvite, JazzHR (about 20,000 companies) | whole list every 1-12 hours; companies seen hiring QA hourly |
| Wide net | Two open datasets, for everything else (Phenom, Taleo, Cornerstone, Eightfold, Avature, ...) and as a safety net | daily |
| Platforms | LinkedIn, Indeed and remote job boards, kept separate (own tab) | hourly |

The "Ece" tab holds postings whose work is software testing under another title (validation, release, UAT, AI evaluation; `ece_include` in config.yaml). On top of the usual location, degree and age rules their requirements must be about testing, must not ask for years in another profession and must not be a development job (`filters.ece_fit`). They go to Telegram only if the group has a topic named "Ece".

Rules: US remote must be stated (unclear ones go to the "Check" tab), postings that require a degree with no
"or equivalent experience" are dropped, postings older than 30 days are dropped, closed postings are removed.

## Files

- `config.yaml` — titles, schedule, Telegram quiet hours. The only file you normally edit.
- `radar.py`, `jr/` — the program.
- `data/boards/` — company lists per career system; `data/watch/` — companies seen hiring for these roles.
- `docs/` — the web page (GitHub Pages) and its data.

## Run locally

    pip install -r requirements.txt
    python tests/test_offline.py
    python radar.py --dry-run --only fast --max-boards 50

## Data credits

- Company lists and open jobs dataset: [stapply-ai/ats-scrapers](https://github.com/stapply-ai/ats-scrapers) (MIT).
- Company lists and open jobs dataset: [Feashliaa/job-board-aggregator](https://github.com/Feashliaa/job-board-aggregator)
  (code MIT, data CC BY-NC 4.0 — used here for personal, non-commercial job search).
- LinkedIn / Indeed top-up: [JobSpy](https://github.com/speedyapply/JobSpy) (MIT).
