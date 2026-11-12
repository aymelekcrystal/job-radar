#!/usr/bin/env python3
"""Telegram listener that runs beside the scanner: handles the "Mark as applied" button, /applied,
greets new chats with their ID and remembers tabs created by hand.

Usage: python poll.py <unix time to stop at>
"""
import hashlib, html, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).parent
TG, APPLIED, JOBS = ROOT / "data/tg.json", ROOT / "docs/applied.json", ROOT / "docs/jobs.json"
TOK = (os.getenv("TELEGRAM_TOKEN") or "").strip()
CHATS = [c.strip() for c in (os.getenv("TELEGRAM_CHAT_ID") or "").replace(";", ",").split(",") if c.strip()]
BASE = f"https://api.telegram.org/bot{TOK}"


def load(p, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def dump(p, obj):
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False))
    tmp.replace(p)                                   # atomic: the scanner never reads half a file


def call(method, **params):
    try:
        return requests.post(f"{BASE}/{method}", data=params, timeout=30).json()
    except Exception:
        return {}


def hid(job_id):
    return hashlib.md5(job_id.encode()).hexdigest()[:16]


def button(h, applied):
    return json.dumps({"inline_keyboard": [[{"text": "✅ Applied · tap to undo" if applied else "☐ Mark as applied",
                                              "callback_data": f"ap:{h}"}]]})


def on_button(q):
    h = (q.get("data") or "")[3:]
    msg = q.get("message") or {}
    applied = load(APPLIED, [])
    mine = next((a for a in applied if a.get("hid") == h), None)
    if mine:
        applied.remove(mine)
        note, now_applied = "Unmarked", False
    else:
        job = next((j for j in load(JOBS, {}).get("jobs", []) if hid(j["id"]) == h), None)
        lines = [l for l in (msg.get("text") or "").split("\n") if l.strip()]
        rec = {"hid": h, "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if job:
            rec.update({k: job.get(k) for k in ("id", "title", "company", "url", "src", "location", "posted")})
        else:                                        # posting already closed: keep what the message says
            rec.update(title=lines[1] if len(lines) > 1 else "", company=(lines[2].split(" · ")[0] if len(lines) > 2 else ""),
                       url=next((l[7:] for l in lines if l.startswith("Apply: ")), ""))
        applied.append(rec)
        note, now_applied = "Marked as applied ✅", True
    dump(APPLIED, applied)
    call("answerCallbackQuery", callback_query_id=q["id"], text=note)
    if msg:
        call("editMessageReplyMarkup", chat_id=msg["chat"]["id"], message_id=msg["message_id"], reply_markup=button(h, now_applied))


def on_message(m, tg):
    cid = str((m.get("chat") or {}).get("id") or "")
    if not cid:
        return
    made = m.get("forum_topic_created")
    if made and m.get("message_thread_id"):
        tg.setdefault("named", {}).setdefault(cid[-6:], {})[str(made.get("name", "")).lower()] = m["message_thread_id"]
    if cid not in CHATS and cid not in tg.setdefault("greeted", []):
        tg["greeted"].append(cid)
        call("sendMessage", chat_id=cid, parse_mode="HTML",
             text=f"👋 This chat's ID is <code>{cid}</code>\nTo receive Job Radar postings here, add it to the TELEGRAM_CHAT_ID setting.")
    text = (m.get("text") or "").strip().lower()
    if text.startswith("/applied"):
        applied = sorted(load(APPLIED, []), key=lambda a: a.get("applied_at", ""), reverse=True)
        week = [a for a in applied if a.get("applied_at", "") >= datetime.fromtimestamp(time.time() - 7 * 86400, timezone.utc).isoformat()]
        rows = [f"• {html.escape(a.get('title') or '?')} — {html.escape(a.get('company') or '?')} ({a.get('applied_at', '')[:10]})" for a in applied[:25]]
        call("sendMessage", chat_id=cid, parse_mode="HTML", disable_web_page_preview="true",
             message_thread_id=m.get("message_thread_id") or "",
             text=f"<b>Applied: {len(applied)} total, {len(week)} in the last 7 days</b>\n" + ("\n".join(rows) or "Nothing marked yet."))


def main():
    until = float(sys.argv[1]) if len(sys.argv) > 1 else time.time() + 600
    if not TOK:
        time.sleep(max(0, until - time.time()))
        return
    tg = load(TG, {})
    allowed = json.dumps(["message", "callback_query", "channel_post"])
    while time.time() < until - 10:
        wait = int(min(50, until - time.time() - 10))
        try:
            r = requests.get(f"{BASE}/getUpdates", timeout=wait + 20,
                             params={"offset": tg.get("offset", 0), "timeout": wait, "allowed_updates": allowed}).json()
        except Exception:
            time.sleep(5)
            continue
        if not r.get("ok"):
            time.sleep(15)
            continue
        for u in r.get("result", []):
            tg["offset"] = u["update_id"] + 1
            try:
                if u.get("callback_query", {}).get("data", "").startswith("ap:"):
                    on_button(u["callback_query"])
                elif u.get("message") or u.get("channel_post"):
                    on_message(u.get("message") or u.get("channel_post"), tg)
            except Exception as ex:
                print("poll: update failed:", type(ex).__name__, flush=True)
        dump(TG, tg)


if __name__ == "__main__":
    main()
