# Job Radar

Personal job alert bot. It reads **company career sites first** and sends each new matching posting to Telegram.

Target: remote (US) and Raleigh-area QA / SDET / test automation / AI testing roles.

## How it works

| Tier | What | How often |
|---|---|---|
| Direct scan | Greenhouse, Lever, Ashby: every known company, rotating; companies that hire QA are read on every run | every 15 min (hourly overnight) |
| Direct scan | SmartRecruiters, Breezy, Rippling, Recruitee, Amazon | hourly |
| Direct scan | Workday (companies that hire QA) | 9:30, 15:00, 21:00 ET |
| Wide net | Two open datasets covering 60+ career systems (Oracle, iCIMS, SuccessFactors, Phenom, ADP, JazzHR, Paycom, BambooHR, Workable, Teamtailor, ...) | whenever they publish a new snapshot |
| Top-up | LinkedIn, Indeed and remote job boards, only if the day has fewer than 50 company postings | 17:00 ET |

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
