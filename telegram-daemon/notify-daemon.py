#!/usr/bin/env python3
"""
Cowork Telegram Notify Daemon  (cross-platform: Windows / macOS / Linux)
=======================================================================
雙向版：
  發送 (outbound)：監聽 notify-queue.jsonl → 發 Telegram 通知到手機
  接收 (inbound) ：getUpdates 收你在 Telegram 對 bot 打的訊息
      - 內建指令 (/ping /status /queue /help) → daemon 直接回覆
      - 其他訊息 → 寫進 inbox.jsonl，等 Cowork 下次開 session 讀取處理

在「本機」執行一次即可（不要跑在 Cowork sandbox 內）：
    python  notify-daemon.py        # Windows
    python3 notify-daemon.py        # macOS / Linux
需要 Python 3.6+，不需額外套件。

注意：
- getUpdates 與「手動 getUpdates」會互搶 update，只能由 daemon 獨佔 poll。
- 只回應 config.json 裡 chat_id 本人的訊息（防陌生人對 bot 下指令）。
- 同一時間只開一台 daemon。
"""

import json
import os
import sys
import time
import socket
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta, date

# Windows 終端機預設 cp950(Big5)，印 emoji 會 UnicodeEncodeError 導致 daemon crash。
# 強制 stdout/stderr 用 UTF-8，errors=replace 確保印任何字元都不會炸。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))  # script + data both local, off iCloud (no sync eviction / conflict-renames)
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
QUEUE_FILE = os.path.join(SCRIPT_DIR, "notify-queue.jsonl")
INBOX_FILE = os.path.join(SCRIPT_DIR, "inbox.jsonl")

_HOST = "".join(c for c in socket.gethostname() if c.isalnum()) or "host"
PROCESSED_FILE = os.path.join(SCRIPT_DIR, ".notify-processed.{}.pos".format(_HOST))
OFFSET_FILE = os.path.join(SCRIPT_DIR, ".update-offset.{}.pos".format(_HOST))

# Daily-paper-digest data files (in the Obsidian vault, NOT in SCRIPT_DIR).
# These back the /today /want /seeds commands. Path is user-specific.
DIGEST_DIR = r"C:\Users\<USERNAME>\path\to\ObsidianVault\Daily Paper Digest"
RECLOG_FILE = os.path.join(DIGEST_DIR, "_recommended-log.md")
REQUESTS_FILE = os.path.join(DIGEST_DIR, "_requests.md")
KEPTSEEDS_FILE = os.path.join(DIGEST_DIR, "_kept-seeds.md")

# Thesis monograph deadline (for /countdown). Adjust if the date changes.
DEADLINE = date(2026, 8, 31)
DEADLINE_LABEL = "專書 deadline (2026-08)"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("  {} {}".format(ts, msg), flush=True)


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# send_* return one of: "ok" (sent) | "retry" (transient, keep in queue) |
# "drop" (permanent, skip past it so one bad entry never blocks the queue).
def _perm_from_httperror(e):
    """urlopen OSError → permanent if HTTP 4xx client error (except 429 rate-limit)."""
    code = getattr(e, "code", None)
    return code is not None and 400 <= code < 500 and code != 429


def _perm_from_result(result):
    """Telegram 200-but-ok:false → permanent if error_code is a 4xx (except 429)."""
    ec = result.get("error_code")
    return isinstance(ec, int) and 400 <= ec < 500 and ec != 429


# ---------------- outbound (queue → Telegram) ----------------

def send_telegram(bot_token, chat_id, text, parse_mode=None, disable_preview=True):
    url = "https://api.telegram.org/bot{}/sendMessage".format(bot_token)
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if disable_preview:
        payload["disable_web_page_preview"] = True
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            if not result.get("ok", False):
                log("[ERROR] Telegram not-ok: {}".format(result.get("description", "?")))
                return "drop" if _perm_from_result(result) else "retry"
            return "ok"
    except OSError as e:
        # OSError 涵蓋 URLError / HTTPError / TimeoutError / socket.timeout /
        # ConnectionError —— 任何網路抖動都只記 log，不讓它往上拋殺死 daemon。
        log("[ERROR] sendMessage error: {}".format(e))
        return "drop" if _perm_from_httperror(e) else "retry"


def _audio_multipart(fields, filename, content):
    """Build a multipart/form-data body for sendAudio. Returns (boundary, body bytes)."""
    boundary = "----CoworkAudio{}".format(int(time.time() * 1000))
    crlf = b"\r\n"
    body = bytearray()
    for name, value in fields.items():
        if value is None:
            continue
        body += b"--" + boundary.encode() + crlf
        body += ('Content-Disposition: form-data; name="{}"'.format(name)).encode("utf-8") + crlf + crlf
        body += str(value).encode("utf-8") + crlf
    body += b"--" + boundary.encode() + crlf
    body += ('Content-Disposition: form-data; name="audio"; filename="{}"'.format(filename)).encode("utf-8") + crlf
    body += b"Content-Type: audio/mpeg" + crlf + crlf
    body += content + crlf
    body += b"--" + boundary.encode() + b"--" + crlf
    return boundary, bytes(body)


def send_telegram_audio(bot_token, chat_id, audio_path, caption=None,
                        parse_mode=None, title=None, performer=None):
    """Upload an audio file (mp3) to Telegram via sendAudio (multipart, stdlib only)."""
    if not audio_path or not os.path.exists(audio_path):
        log("[ERROR] sendAudio: file not found: {}".format(audio_path))
        return "drop"
    try:
        size = os.path.getsize(audio_path)
    except OSError:
        size = 0
    if size > 50 * 1024 * 1024:
        log("[ERROR] sendAudio: {} is {:.1f} MB (> 50 MB Telegram bot limit); "
            "skipping upload.".format(os.path.basename(audio_path), size / 1048576))
        return "drop"
    try:
        with open(audio_path, "rb") as f:
            content = f.read()
    except OSError as e:
        log("[ERROR] sendAudio: read failed: {}".format(e))
        return "drop"
    fields = {"chat_id": chat_id, "caption": caption,
              "parse_mode": parse_mode, "title": title, "performer": performer}
    boundary, body = _audio_multipart(fields, os.path.basename(audio_path), content)
    url = "https://api.telegram.org/bot{}/sendAudio".format(bot_token)
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "multipart/form-data; boundary={}".format(boundary)})
    try:
        # bigger timeout than text: audio uploads can be tens of MB
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read())
            if not result.get("ok", False):
                log("[ERROR] sendAudio not-ok: {}".format(result.get("description", "?")))
                return "drop" if _perm_from_result(result) else "retry"
            return "ok"
    except OSError as e:
        log("[ERROR] sendAudio error: {}".format(e))
        return "drop" if _perm_from_httperror(e) else "retry"


def _video_multipart(fields, filename, content):
    """Build a multipart/form-data body for sendVideo. Returns (boundary, body bytes)."""
    boundary = "----CoworkVideo{}".format(int(time.time() * 1000))
    crlf = b"\r\n"
    body = bytearray()
    for name, value in fields.items():
        if value is None:
            continue
        body += b"--" + boundary.encode() + crlf
        body += ('Content-Disposition: form-data; name="{}"'.format(name)).encode("utf-8") + crlf + crlf
        body += str(value).encode("utf-8") + crlf
    body += b"--" + boundary.encode() + crlf
    body += ('Content-Disposition: form-data; name="video"; filename="{}"'.format(filename)).encode("utf-8") + crlf
    body += b"Content-Type: video/mp4" + crlf + crlf
    body += content + crlf
    body += b"--" + boundary.encode() + b"--" + crlf
    return boundary, bytes(body)


def send_telegram_video(bot_token, chat_id, video_path, caption=None,
                        parse_mode=None, supports_streaming=True):
    """Upload a video file (mp4) to Telegram via sendVideo (multipart, stdlib only).

    Telegram's bot API caps multipart uploads at 50 MB. Files over that are
    rejected by Telegram (413); the digest handles large clips by delivering a
    link instead, so here we just log and report the failure without crashing.
    """
    if not video_path or not os.path.exists(video_path):
        log("[ERROR] sendVideo: file not found: {}".format(video_path))
        return "drop"
    try:
        size = os.path.getsize(video_path)
    except OSError:
        size = 0
    if size > 50 * 1024 * 1024:
        log("[ERROR] sendVideo: {} is {:.1f} MB (> 50 MB Telegram bot limit); "
            "skipping upload.".format(os.path.basename(video_path), size / 1048576))
        return "drop"
    try:
        with open(video_path, "rb") as f:
            content = f.read()
    except OSError as e:
        log("[ERROR] sendVideo: read failed: {}".format(e))
        return "drop"
    fields = {"chat_id": chat_id, "caption": caption, "parse_mode": parse_mode,
              "supports_streaming": "true" if supports_streaming else None}
    boundary, body = _video_multipart(fields, os.path.basename(video_path), content)
    url = "https://api.telegram.org/bot{}/sendVideo".format(bot_token)
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "multipart/form-data; boundary={}".format(boundary)})
    try:
        # bigger timeout than audio: video uploads can be tens of MB
        with urllib.request.urlopen(req, timeout=600) as resp:
            result = json.loads(resp.read())
            if not result.get("ok", False):
                log("[ERROR] sendVideo not-ok: {}".format(result.get("description", "?")))
                return "drop" if _perm_from_result(result) else "retry"
            return "ok"
    except OSError as e:
        log("[ERROR] sendVideo error: {}".format(e))
        return "drop" if _perm_from_httperror(e) else "retry"


def _read_int(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def _write_int(path, n):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(str(n))
    os.replace(tmp, path)


def count_lines():
    if not os.path.exists(QUEUE_FILE):
        return 0
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        return sum(1 for ln in f if ln.strip())


def format_entry(entry):
    if entry.get("message"):
        return str(entry["message"])
    if entry.get("title") or entry.get("body"):
        title = str(entry.get("title", "")).strip()
        body = str(entry.get("body", "")).strip()
        if title and body:
            return "{}\n{}".format(title, body)
        return title or body
    return "[Cowork] 任務完成：{}".format(entry.get("summary", "任務完成"))


def process_queue(config, startup=False):
    if not os.path.exists(QUEUE_FILE):
        return 0
    total = count_lines()
    last = _read_int(PROCESSED_FILE)
    last = -1 if last is None else last

    if last == -1:
        _write_int(PROCESSED_FILE, total)
        if startup and total:
            log("No progress file — skipping {} historical line(s).".format(total))
        return 0
    if total < last:
        log("Queue shrank ({} < {}) — resetting.".format(total, last))
        last = 0
    if total <= last:
        return 0

    new_entries = []
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        idx = 0
        for ln in f:
            if not ln.strip():
                continue
            if idx >= last:
                new_entries.append(ln.strip())
            idx += 1

    count = 0
    processed_line = last
    _tag = {"ok": "[OK]", "drop": "[SKIP]"}
    for line in new_entries:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as e:
            log("[WARN] Invalid queue JSON, skipping: {}".format(e))
            processed_line += 1
            continue
        # video entries: {"type":"video","video":"<path>","caption":...}
        if entry.get("type") == "video" or entry.get("video"):
            cap = entry.get("caption") or entry.get("message")
            status = send_telegram_video(
                config["bot_token"], config["chat_id"], entry.get("video"),
                caption=cap, parse_mode=entry.get("parse_mode"))
            log("{} OUT VIDEO {}".format(_tag.get(status, "[XX]"),
                                         os.path.basename(str(entry.get("video", "")))))
        # audio entries: {"type":"audio","audio":"<path>","caption":...,"title":...}
        elif entry.get("type") == "audio" or entry.get("audio"):
            cap = entry.get("caption") or entry.get("message")
            status = send_telegram_audio(
                config["bot_token"], config["chat_id"], entry.get("audio"),
                caption=cap, parse_mode=entry.get("parse_mode"),
                title=entry.get("title"), performer=entry.get("performer"))
            log("{} OUT AUDIO {}".format(_tag.get(status, "[XX]"),
                                         os.path.basename(str(entry.get("audio", "")))))
        else:
            text = format_entry(entry)
            pm = entry.get("parse_mode")
            status = send_telegram(config["bot_token"], config["chat_id"], text, parse_mode=pm)
            if status != "ok" and pm:
                # parse_mode formatting may have been rejected (e.g. bad HTML);
                # retry as plain text so one bad entry never locks the queue.
                status = send_telegram(config["bot_token"], config["chat_id"], text)
            first = text.splitlines()[0] if text else "(empty)"
            log("{} OUT {}".format(_tag.get(status, "[XX]"), first))
        # transient failure → stop, keep pointer, retry next poll.
        # ok / drop(permanent) → advance so one bad entry never blocks the queue.
        if status == "retry":
            break
        if status == "ok":
            count += 1
        processed_line += 1
    _write_int(PROCESSED_FILE, processed_line)
    return count


# ---------------- inbound (Telegram → inbox / commands) ----------------

def get_updates(bot_token, offset, timeout=20):
    params = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    url = "https://api.telegram.org/bot{}/getUpdates?{}".format(
        bot_token, urllib.parse.urlencode(params))
    try:
        # urlopen timeout 要比 long-poll timeout 大，否則會先 timeout
        with urllib.request.urlopen(url, timeout=timeout + 10) as resp:
            return json.loads(resp.read())
    except OSError as e:
        # 見 send_telegram：讀取階段的 TimeoutError 不是 URLError 子類，
        # 必須用 OSError 才攔得到，否則 long-poll 逾時會直接崩潰整個 daemon。
        log("[ERROR] getUpdates error: {}".format(e))
        return None


def append_inbox(entry):
    with open(INBOX_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def handle_command(config, text):
    """回傳要回覆的字串；非指令回 None。"""
    cmd = text.strip().split()[0].lower().lstrip("/")
    if cmd == "ping":
        return "🟢 pong — daemon 活著 (host {})".format(_HOST)
    if cmd == "status":
        qn = count_lines()
        done = _read_int(PROCESSED_FILE)
        inbox_n = 0
        if os.path.exists(INBOX_FILE):
            with open(INBOX_FILE, encoding="utf-8") as f:
                inbox_n = sum(1 for ln in f if ln.strip())
        return ("📊 Daemon status\nhost: {}\nqueue: {} 筆 (已發 {})\ninbox: {} 筆未處理"
                .format(_HOST, qn, done, inbox_n))
    if cmd == "queue":
        if not os.path.exists(QUEUE_FILE):
            return "queue 空"
        lines = [l for l in open(QUEUE_FILE, encoding="utf-8") if l.strip()]
        tail = lines[-3:]
        out = ["🗂 最近 {} 筆 queue:".format(len(tail))]
        for l in tail:
            try:
                e = json.loads(l)
                out.append("· " + format_entry(e).splitlines()[0])
            except Exception:
                out.append("· (parse error)")
        return "\n".join(out)
    if cmd == "health":
        total = count_lines()
        done = _read_int(PROCESSED_FILE)
        done = 0 if done is None else done
        backlog = max(0, total - done)
        inbox_n = 0
        if os.path.exists(INBOX_FILE):
            with open(INBOX_FILE, encoding="utf-8") as f:
                inbox_n = sum(1 for ln in f if ln.strip())
        verdict = "🟢 正常，queue 已清空" if backlog == 0 else "🟡 有 {} 筆待送".format(backlog)
        return ("🩺 Health\nhost: {}\nqueue: {} / 已發 {} (backlog {})\ninbox: {} 筆未處理\n{}"
                .format(_HOST, total, done, backlog, inbox_n, verdict))
    if cmd == "today":
        if not os.path.exists(RECLOG_FILE):
            return "找不到推播紀錄檔。"
        today = datetime.now().strftime("%Y-%m-%d")
        rows = []
        with open(RECLOG_FILE, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln.startswith("- " + today + " "):
                    parts = [p.strip() for p in ln[2:].split("|")]
                    if len(parts) >= 3:
                        rows.append((parts[1], parts[2]))  # (url, title)
        if not rows:
            return "今天（{}）還沒有推播紀錄。".format(today)
        out = ["📚 今天推播（{}）共 {} 篇:".format(today, len(rows))]
        for i, (url, title) in enumerate(rows, 1):
            out.append("{}. {}\n{}".format(i, title, url))
        return "\n".join(out)
    if cmd == "want":
        parts = text.strip().split(maxsplit=1)
        arg = parts[1].strip() if len(parts) > 1 else ""
        if not arg:
            return "用法:/want <DOI 或網址>\n例:/want 10.1016/j.jsg.2026.105742"
        stamp = datetime.now().strftime("%m-%d %H:%M")
        newline = "- DATE=ANY | 手機 /want {} | {}\n".format(stamp, arg)
        try:
            if os.path.exists(REQUESTS_FILE):
                with open(REQUESTS_FILE, encoding="utf-8") as f:
                    content = f.read()
            else:
                content = "# 指定文獻需求 (requests)\n\n## 待處理\n\n## 已完成\n"
            marker = "## 待處理"
            if marker in content:
                hdr = content.index(marker)
                nl = content.index("\n", hdr)
                content = content[:nl + 1] + newline + content[nl + 1:]
            else:
                content = content.rstrip() + "\n\n## 待處理\n" + newline
            with open(REQUESTS_FILE, "w", encoding="utf-8") as f:
                f.write(content)
            return "✅ 已加入指定需求，下次推播會納入:\n{}".format(arg)
        except OSError as e:
            return "✗ 寫入失敗（iCloud 可能未同步）:{}".format(e)
    if cmd == "seeds":
        if not os.path.exists(KEPTSEEDS_FILE):
            return "還沒有 kept-seeds。"
        seeds = [l.strip() for l in open(KEPTSEEDS_FILE, encoding="utf-8")
                 if l.strip().startswith("- ")]
        if not seeds:
            return "kept-seeds 是空的。"
        tail = seeds[-5:]
        out = ["🌱 kept-seeds 共 {} 筆，最近 {} 筆:".format(len(seeds), len(tail))]
        for s in tail:
            p = [x.strip() for x in s[2:].split("|")]
            title = p[1] if len(p) > 1 else p[0]
            out.append("· " + title[:70])
        return "\n".join(out)
    if cmd == "countdown":
        days = (DEADLINE - date.today()).days
        if days > 0:
            return "⏳ 距 {} 還有 {} 天（{}）".format(DEADLINE_LABEL, days, DEADLINE.isoformat())
        if days == 0:
            return "🔥 今天就是 {}!".format(DEADLINE_LABEL)
        return "⚠️ {} 已過 {} 天（{}）".format(DEADLINE_LABEL, -days, DEADLINE.isoformat())
    if cmd == "help":
        return ("🤖 可用指令:\n"
                "/ping 確認 daemon 活著\n"
                "/status 看 queue/inbox 狀態\n"
                "/queue 看最近通知\n"
                "/health 健康檢查（backlog/inbox）\n"
                "/today 今天推播的文章清單\n"
                "/want <DOI或網址> 加入下次推播的指定文獻\n"
                "/seeds 看已收藏種子\n"
                "/countdown 距專書 deadline 倒數\n"
                "/help 這個說明\n\n"
                "其他訊息會存進 inbox，Cowork 下次開 session 會讀取處理。")
    return None


def process_updates(config):
    offset = _read_int(OFFSET_FILE)
    r = get_updates(config["bot_token"], offset)
    if not r or not r.get("ok"):
        return 0

    my_chat = str(config["chat_id"])
    handled = 0
    for u in r.get("result", []):
        uid = u.get("update_id", 0)
        # 先推進 offset 再處理：即使這筆處理時 crash，重啟也不會重播它，
        # 避免「處理→crash→重啟→重讀同一筆」的無限轟炸迴圈。
        _write_int(OFFSET_FILE, uid + 1)

        msg = u.get("message") or u.get("edited_message") or {}
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "")
        if not text:
            continue
        if chat_id != my_chat:
            log("[WARN] ignoring message from unknown chat_id")
            continue

        try:
            reply = handle_command(config, text)
            if reply is not None:
                send_telegram(config["bot_token"], my_chat, reply)
                log("[OK] CMD {} -> replied".format(text.split()[0]))
            else:
                append_inbox({
                    "ts": msg.get("date"),
                    "received": datetime.now().isoformat(timespec="seconds"),
                    "from": msg.get("from", {}).get("username")
                            or msg.get("from", {}).get("first_name"),
                    "text": text,
                    "processed": False,
                })
                send_telegram(config["bot_token"], my_chat,
                              "📥 已收進 inbox，Cowork 下次開 session 會處理。")
                log("[OK] IN  inbox <- {}".format(text[:40]))
            handled += 1
        except Exception as e:
            # 單筆處理失敗不該拖垮整個 daemon；offset 已推進，不會重播
            log("[ERROR] handling update {} failed: {}".format(uid, e))
    return handled


# ---------------- main loop ----------------

def main():
    print("=" * 50, flush=True)
    print("  Cowork Telegram Notify Daemon (雙向)", flush=True)
    print("  Queue: {}".format(QUEUE_FILE), flush=True)
    print("  Inbox: {}".format(INBOX_FILE), flush=True)
    print("  Host:  {}".format(_HOST), flush=True)

    if not os.path.exists(CONFIG_FILE):
        log("[ERROR] config.json not found at {}".format(CONFIG_FILE))
        sys.exit(1)

    config = load_config()
    interval = config.get("poll_interval_sec", 2)
    print("  Poll interval: {}s".format(interval), flush=True)
    print("  Commands: /ping /status /queue /help", flush=True)
    print("  Waiting... (Ctrl+C to stop)", flush=True)
    print("=" * 50, flush=True)

    sent = process_queue(config, startup=True)
    if sent:
        log("Sent {} pending notification(s) on startup.".format(sent))

    try:
        while True:
            try:
                process_queue(config)
                process_updates(config)  # 內含 long-poll，會自然 block ~20s
            except Exception as e:
                # 最後一道保險：任何未預期例外都只記 log 並繼續下一輪 poll，
                # 絕不讓單次迭代的錯誤終結整個 daemon。
                log("[ERROR] loop iteration failed, continuing: {}".format(e))
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n  Daemon stopped.", flush=True)


if __name__ == "__main__":
    main()
