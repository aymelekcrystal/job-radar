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


LAST_ERROR = [""]


def send(text, tok, chat):
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok.strip()}/sendMessage", timeout=20,
                          data={"chat_id": chat.strip(), "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": "true"})
        if r.status_code == 429:
            time.sleep(int(r.json().get("parameters", {}).get("retry_after", 5)) + 1)
            return False
        if not r.ok:
            try:
                LAST_ERROR[0] = f"{r.status_code} {r.json().get('description', '')}"[:120]
            except Exception:
                LAST_ERROR[0] = f"HTTP {r.status_code}"
        return r.ok
    except Exception as ex:
        LAST_ERROR[0] = type(ex).__name__
        return False


def diagnose(tok):
    """Why can't we send? Looks at the bot itself, never prints ids."""
    try:
        me = requests.get(f"https://api.telegram.org/bot{tok.strip()}/getMe", timeout=20)
        if not me.ok:
            return "token rejected by Telegram"
        up = requests.get(f"https://api.telegram.org/bot{tok.strip()}/getUpdates", timeout=20).json().get("result", [])
        chats = {str((u.get("message") or u.get("my_chat_member") or {}).get("chat", {}).get("id")) for u in up} - {"None"}
        return f"token ok; bot has received messages from {len(chats)} chat(s)"
    except Exception as ex:
        return f"diagnose failed: {type(ex).__name__}"


def send_all(text, tok, chats):
    ok = [send(text, tok, c) for c in chats]
    return any(ok)


def greet_new_chats(tok, chats):
    """A chat or channel the bot was just added to gets a message with its own ID, so it can be added to the settings."""
    try:
        base = f"https://api.telegram.org/bot{tok.strip()}"
        ups = requests.get(base + "/getUpdates", timeout=20, params={"timeout": 0}).json().get("result", [])
        seen, last = set(), None
        for u in ups:
            last = u["update_id"]
            m = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
            cid = str((m.get("chat") or {}).get("id") or "")
            if not cid or cid in chats or cid in seen:
                continue
            seen.add(cid)
            send(f"👋 This chat's ID is <code>{cid}</code>\nTo receive Job Radar postings here, add it to the "
                 f"TELEGRAM_CHAT_ID setting (several IDs are separated by commas).", tok, cid)
        if last is not None:
            requests.get(base + "/getUpdates", timeout=20, params={"offset": last + 1, "timeout": 0})
    except Exception:
        pass


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
    chats = [c.strip() for c in chat.replace(";", ",").split(",") if c.strip()]
    greet_new_chats(tok, chats)
    for c in chats:                                  # a newly added chat gets a welcome once
        w = state.setdefault("tg_welcomed", [])
        if "*" in w:                                 # setup before multi-chat support: the first chat was already welcomed
            w.remove("*"); w.append(chats[0][-4:])
        if c[-4:] not in w and state.get("tg_hello"):
            if send("✅ Job Radar is connected. New postings will arrive here as they are found.", tok, c):
                state["tg_welcomed"].append(c[-4:])
    chat = chats
    if not state.get("tg_hello"):
        if send_all("✅ Job Radar is connected. New postings will arrive here as they are found.", tok, chat):
            state["tg_hello"] = True
            state["tg_welcomed"] = [c[-4:] for c in chats]
        else:
            return f"TELEGRAM ERROR: {LAST_ERROR[0]} | {diagnose(tok)} ({len(pend)} waiting)"
    if quiet(now_et, cfg):
        state["held"] = True
        return f"quiet hours ({len(pend)} held)"
    if state.pop("held", None) and len(pend) > 1:
        send_all(f"☀️ Good morning — {len(pend)} postings found overnight:", tok, chat)
    cap = cfg.get("max_messages_per_run", 45)
    if len(pend) > cap:                      # a backlog (first wide scan): keep the newest, do not flood
        keep = {j["id"] for j in sorted(pend, key=lambda j: j["posted"], reverse=True)[:cap]}
        for j in pend:
            if j["id"] not in keep:
                j["notify"] = "skip"
        pend = [j for j in pend if j["id"] in keep]
    sent = 0
    for j in pend:
        if send_all(fmt(j), tok, chat):
            j["notify"], sent = "sent", sent + 1
        else:
            j["tries"] = j.get("tries", 0) + 1
            if j["tries"] >= 5:
                j["notify"] = "failed"
        time.sleep(1.1)
    return f"sent {sent} of {len(pend)}" + (f" (last error: {LAST_ERROR[0]})" if sent < len(pend) and LAST_ERROR[0] else "")
