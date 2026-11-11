"""Telegram notifications (English). One message per posting."""
import html, os, time
from datetime import datetime

import requests

from .common import NOW, ET

ICON = {"ok": "🟢", "check": "🟡", "platform": "🔵"}


def ago(iso_s, now=None):
    m = ((now or NOW) - datetime.fromisoformat(iso_s)).total_seconds() / 60
    if m < 90:
        return f"{max(1, round(m))} min ago"
    if m < 36 * 60:
        return f"{round(m / 60)} h ago"
    return f"{round(m / 1440)} days ago"


def fmt(j, now=None):
    e = html.escape
    when = f"first seen {ago(j['first_seen'], now)} (post date unknown)" if j.get("date_est") else f"posted {ago(j['posted'], now)}"
    head = {"ok": "NEW", "check": "CHECK LOCATION", "platform": "FROM " + j["src"].upper()}[j["kind"]]
    src = f"Company site ({e(j['src'])})" if j["kind"] != "platform" else (f"{e(j['src'])} → company link" if j.get("direct_link") else e(j["src"]))
    out = [f"{ICON[j['kind']]} {head} · {when}", "", f"<b>{e(j['title'])}</b>", f"{e(j['company'])} · {src}", "",
           f"📍 {e(j['location'] or 'Not stated')}"]
    if j.get("why"):
        out.append(f"⚠️ {e(j['why'])}")
    if j.get("salary"):
        out.append(f"💰 {e(j['salary'])}")
    if j.get("reqs"):
        out += ["", "Requirements:"] + [f"• {e(r)}" for r in j["reqs"]]
    out += ["", f"Apply: {j['url']}"]
    return "\n".join(out)


def send(text, tok, chat):
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", timeout=20,
                          data={"chat_id": chat, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": "true"})
        if r.status_code == 429:
            time.sleep(int(r.json().get("parameters", {}).get("retry_after", 5)) + 1)
            return False
        return r.ok
    except Exception:
        return False


def quiet(now_et, cfg):
    q0, q1 = cfg.get("quiet_hours", [23, 7])
    return now_et.hour >= q0 or now_et.hour < q1 if q0 > q1 else q0 <= now_et.hour < q1


def process(jobs, state, cfg, dry=False):
    """Sends pending notifications. Returns a short status string for the run log."""
    tok, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    now_et = NOW.astimezone(ET)
    pend = sorted((j for j in jobs if j.get("notify") == "pending"), key=lambda j: (j["kind"] == "platform", j["posted"]))
    if not (tok and chat):
        for j in pend:
            j["notify"] = "skip"            # no backlog flood on the day Telegram gets connected
        return f"telegram not configured ({len(pend)} not sent)"
    if dry:
        return f"dry run ({len(pend)} pending)"
    if not state.get("tg_hello"):
        if send("✅ Job Radar is connected. New postings will arrive here as they are found.", tok, chat):
            state["tg_hello"] = True
    if quiet(now_et, cfg):
        state["held"] = True
        return f"quiet hours ({len(pend)} held)"
    if state.pop("held", None) and len(pend) > 1:
        send(f"☀️ Good morning — {len(pend)} postings found overnight:", tok, chat)
    cap = cfg.get("max_messages_per_run", 45)
    if len(pend) > cap:                      # a backlog (first wide scan): keep the newest, do not flood
        keep = {j["id"] for j in sorted(pend, key=lambda j: j["posted"], reverse=True)[:cap]}
        for j in pend:
            if j["id"] not in keep:
                j["notify"] = "skip"
        pend = [j for j in pend if j["id"] in keep]
    sent = 0
    for j in pend:
        if send(fmt(j), tok, chat):
            j["notify"], sent = "sent", sent + 1
        else:
            j["tries"] = j.get("tries", 0) + 1
            if j["tries"] >= 5:
                j["notify"] = "failed"
        time.sleep(1.1)
    return f"sent {sent} of {len(pend)}"
