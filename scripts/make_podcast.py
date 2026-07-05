#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_podcast.py — turn a day's digest into a NotebookLM audio overview (podcast).

Flow:
  read manifest + atomic notes for DATE (from the Obsidian digest dir)
    -> build a combined Mandarin source doc (+ optional full-text PDFs)
    -> notebooklm: create notebook, add source(s), generate audio (--language zh_Hant)
    -> download mp3 to <state_dir>/podcast/<DATE>_digest.mp3
    -> (optional --push) enqueue a Telegram sendAudio entry for the daemon to deliver

Prereqs:
  uv tool install 'notebooklm-py[browser]'   # the `notebooklm` CLI
  notebooklm login                            # one-time Google login (cookies persist)

Auth is self-healing: each run calls ensure_auth() -> `notebooklm auth refresh`
first, which rotates Google's short-lived *SIDTS/*SIDCC/GAPSTS cookies from the
~394-day master SID. So a daily run keeps auth alive on its own; you only ever
need to re-login again near the master expiry or after a Google-forced reset.
Recovery if `auth refresh` ever fails:
  notebooklm login                              # interactive browser login, or
  notebooklm login --browser-cookies chrome     # re-import from logged-in Chrome
                                                # (needs: uv tool install 'notebooklm-py[browser,cookies]')

Config-driven: paths come from config.json (see config.example.json). No secrets here.
  loader order: $DIGEST_CONFIG -> ./config.json -> ../config.json
"""
import os, sys, re, json, argparse, subprocess, datetime, glob

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_cfg():
    for c in (os.environ.get("DIGEST_CONFIG"),
              os.path.join(HERE, "config.json"),
              os.path.join(HERE, "..", "config.json")):
        if c and os.path.exists(c):
            return json.load(open(c, encoding="utf-8"))
    raise FileNotFoundError(
        "config.json not found (set DIGEST_CONFIG, or place beside the script / at repo root)")


CFG = _load_cfg()
PATHS = CFG.get("paths", {})
DIGEST_DIR = PATHS.get("digest_dir")
STATE_DIR = PATHS.get("state_dir") or "."
DAEMON_DIR = PATHS.get("live_daemon_dir")
NB_CLI = os.environ.get("NOTEBOOKLM_CLI", "notebooklm")

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


NARRATION_GUIDE = (
    "【說書骨架 — 請務必照這個方式講】用繁體中文、兩位主持人一來一往,做一集給構造地質與定年"
    "研究者聽的深度討論。**逐篇按下列章節順序走**,不要只念摘要、不要流水帳:\n"
    "① 問題與背景:這篇想解決什麼問題、為什麼重要、前人卡在哪(gap)。\n"
    "② 資料與方法:用什麼樣本/資料、關鍵方法或技術、方法的亮點與限制(如模型假設、定年前提、"
    "分析或反演方法的適用範圍等)。\n"
    "③ 主要結果:最關鍵的觀察與**具體數字**(P–T、年代 Ma、應力方向、地溫梯度…),對應哪張圖說了什麼。\n"
    "④ 解釋與意義:作者怎麼解釋、對更大的隱沒/造山/折返框架有何意義、有沒有爭議或替代解釋。\n"
    "⑤ 與聽眾研究的關聯:扣回聽眾自己的研究方法與主題(方法學校準、與既有框架的對照)——"
    "這篇能用在他哪一塊。\n"
    "⑥ 一句話帶走。\n"
    "七篇都講完後,用 2–3 分鐘做**跨篇串連**:哪些主題互相呼應、今天的共同線索是什麼。\n"
    "語氣專業但口語、彼此追問、避免空泛客套與冗長開場白。有全文 PDF 的篇盡量引用具體細節;"
    "只有摘要的就講明是依摘要,不要編造數字。"
)


def parse_note(path):
    """Pull title/authors/journal/doi + the 📝 summary paragraph out of an atomic note."""
    meta, summary = {}, []
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return meta, ""
    if lines and lines[0].strip() == "---":          # YAML frontmatter
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            m = re.match(r'^([a-zA-Z_]+):\s*(.*)$', lines[i])
            if m:
                meta[m.group(1)] = m.group(2).strip().strip('"')
            i += 1
        lines = lines[i + 1:]
    grab = False                                      # summary starts at the 📝 line
    for ln in lines:
        s = ln.strip()
        if s.startswith("📝"):
            grab = True
            summary.append(s.lstrip("📝").strip())
            continue
        if grab:
            if s.startswith("✨"):                     # keep the "what's new" line
                summary.append(s)
                continue
            if not s or s.startswith("🔗") or s.startswith("---"):
                break
            summary.append(s)
    return meta, " ".join(summary).strip()


def build_source(date, manifest):
    papers = manifest.get("papers", {})
    out = ["# {} 每日文獻精選（{} 篇）\n".format(date, len(papers)),
           NARRATION_GUIDE + "\n\n---\n以下為今天的 {} 篇文獻(標題、作者、期刊、摘要;有全文者另附 PDF):\n".format(len(papers))]
    notes_dir = os.path.join(DIGEST_DIR, "papers")
    for num in sorted(papers, key=lambda x: int(x)):
        p = papers[num]
        note_fn = p.get("note", "")
        if note_fn and not note_fn.lower().endswith(".md"):   # manifest stores stem w/o .md
            note_fn += ".md"
        meta, summary = parse_note(os.path.join(notes_dir, note_fn))
        title = meta.get("title") or p.get("title", "")
        doi = meta.get("doi") or p.get("doi", "")
        out.append("\n## {}. {}".format(num, title))
        if meta.get("authors"):
            out.append("作者：{}".format(meta["authors"]))
        meta_line = " ｜ ".join(x for x in [meta.get("journal", ""), str(meta.get("year", "")),
                                            ("DOI: " + doi) if doi else ""] if x)
        if meta_line:
            out.append(meta_line)
        if summary:
            out.append("\n" + summary)
    return "\n".join(out) + "\n"


def run(cmd, timeout=180):
    """Run the notebooklm CLI; echo stdout, raise SystemExit on failure/timeout.

    timeout guards against a hung NotebookLM backend / expired cookie / stuck
    upload silently eating the whole scheduled run (see M4)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SystemExit("timed out after {}s: {}".format(timeout, " ".join(cmd[:3])))
    if r.stdout:
        print(r.stdout.rstrip())
    if r.returncode != 0:
        if r.stderr:
            print(r.stderr.rstrip())
        raise SystemExit("command failed ({}): {}".format(r.returncode, " ".join(cmd[:3])))
    return r.stdout or ""


def ensure_auth():
    """Pre-flight: rotate the short-lived Google auth cookies right before use.

    NotebookLM auth is a Playwright storage_state.json. The master SID cookies
    live ~394 days, but Google's rotating *SIDTS / *SIDCC / GAPSTS cookies are
    short-lived; if they go stale the backend bounces the request to
    accounts.google.com ('Authentication expired'). That is what makes the 08:00
    cron fail intermittently even though the login is still fundamentally valid.
    `auth refresh` re-derives the rotating cookies from the master SID and writes
    them back, so the run that follows uses fresh cookies. Because it derives
    from the long-lived master, a daily refresh keeps auth alive until the ~394d
    master expiry (or a Google-forced reset). Returns True if auth is usable."""
    try:
        r = subprocess.run([NB_CLI, "auth", "refresh"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
    except (subprocess.TimeoutExpired, OSError):
        return False
    if r.stdout:
        print(r.stdout.rstrip())
    if r.returncode == 0:
        return True
    if r.stderr:
        print(r.stderr.rstrip())
    # refresh failed -> confirm whether cookies are truly dead (real re-login needed)
    try:
        r2 = subprocess.run([NB_CLI, "auth", "check", "--test"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=120)
        return r2.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _enqueue_text(msg):
    """Best-effort Telegram text notice via the daemon queue (used to report a
    podcast failure so an unattended run does not fail silently — see M5)."""
    if not DAEMON_DIR:
        return
    try:
        with open(os.path.join(DAEMON_DIR, "notify-queue.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"message": msg, "parse_mode": "HTML"}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser(description="Generate a NotebookLM podcast from a day's digest.")
    ap.add_argument("--date", default=datetime.date.today().isoformat(), help="YYYY-MM-DD (default: today)")
    ap.add_argument("--language", default="zh_Hant", help="NotebookLM language code (default: zh_Hant)")
    ap.add_argument("--length", default="short", choices=["short", "default", "long"])
    ap.add_argument("--format", default="deep-dive", choices=["deep-dive", "brief", "critique", "debate"])
    ap.add_argument("--pdf-dir", default=None, help="folder of full-text PDFs to also upload (optional)")
    ap.add_argument("--push", action="store_true", help="enqueue a Telegram sendAudio for the daemon")
    ap.add_argument("--dry-run", action="store_true", help="write source doc + report, skip NotebookLM")
    args = ap.parse_args()

    if not DIGEST_DIR:
        raise SystemExit("set paths.digest_dir in config.json")
    date = args.date
    if not args.pdf_dir:                                   # default: feed the day's downloaded PDFs
        cand = os.path.join(DIGEST_DIR, date)
        if os.path.isdir(cand):
            args.pdf_dir = cand
    manifest_path = os.path.join(DIGEST_DIR, "papers", "_manifest-{}.json".format(date))
    if not os.path.exists(manifest_path):
        raise SystemExit("manifest not found: {}".format(manifest_path))
    manifest = json.load(open(manifest_path, encoding="utf-8"))

    podcast_dir = os.path.join(STATE_DIR, "podcast")
    os.makedirs(podcast_dir, exist_ok=True)
    src_path = os.path.join(podcast_dir, "{}_source.md".format(date))
    with open(src_path, "w", encoding="utf-8") as f:
        f.write(build_source(date, manifest))
    print("source doc -> {} ({} bytes)".format(src_path, os.path.getsize(src_path)))

    if args.dry_run:
        npdf = len(glob.glob(os.path.join(args.pdf_dir, "*.pdf"))) if args.pdf_dir and os.path.isdir(args.pdf_dir) else 0
        print("[dry-run] pdf-dir = {} ({} PDFs). skipping NotebookLM.".format(args.pdf_dir, npdf))
        return

    mp3 = os.path.join(podcast_dir, "{}_digest.mp3".format(date))
    try:
        if not ensure_auth():                          # rotate stale cookies before use (see ensure_auth)
            raise SystemExit("NotebookLM 認證需重新登入:auth refresh 失敗,master SID 可能已過期或被 Google 重置")
        out = run([NB_CLI, "create", "每日文獻 Podcast · {}".format(date)], timeout=180)
        m = UUID_RE.search(out)
        if not m:
            raise SystemExit("could not parse notebook id from create output")
        nb = m.group(0)
        print("notebook = {}".format(nb))

        run([NB_CLI, "source", "add", src_path, "-n", nb, "--type", "file",
             "--title", "{} 每日文獻摘要".format(date)], timeout=300)
        if args.pdf_dir and os.path.isdir(args.pdf_dir):
            for pdf in sorted(glob.glob(os.path.join(args.pdf_dir, "*.pdf"))):
                try:
                    run([NB_CLI, "source", "add", pdf, "-n", nb, "--type", "file"], timeout=300)
                except SystemExit as e:
                    print("  skip {}: {}".format(os.path.basename(pdf), e))

        run([NB_CLI, "generate", "audio", NARRATION_GUIDE, "-n", nb, "--language", args.language,
             "--format", args.format, "--length", args.length, "--wait"], timeout=1200)
        if os.path.exists(mp3):                        # delete first so notebooklm can't auto-rename to "(2)" on re-run (M7)
            try:
                os.remove(mp3)
            except OSError:
                pass
        run([NB_CLI, "download", "audio", mp3, "-n", nb], timeout=300)
    except SystemExit as e:
        _enqueue_text("🎧 今日 podcast 生成失敗:{}。\n"
                      "多數情況是 NotebookLM 短期 cookie 過期——本機跑 "
                      "<code>notebooklm auth refresh</code> 通常即可修好,再手動補跑 make_podcast.py。\n"
                      "若 refresh 也失敗(master SID 真的過期),改跑 "
                      "<code>notebooklm login --browser-cookies chrome</code> 從已登入的 Chrome 重新匯入。"
                      .format(str(e)[:180]))
        raise
    print("mp3 -> {}".format(mp3))

    # sentinel: podcast mp3 is fully downloaded — the 08:15 video task waits on this
    # (event handshake instead of blindly polling the mp3 mid-write) (M6).
    try:
        open(os.path.join(podcast_dir, "{}.done".format(date)), "w").close()
    except OSError:
        pass

    if args.push:
        if not DAEMON_DIR:
            print("--push set but paths.live_daemon_dir missing; skipped")
            return
        queue = os.path.join(DAEMON_DIR, "notify-queue.jsonl")
        n = len(manifest.get("papers", {}))
        entry = {"type": "audio", "audio": mp3,
                 "caption": "🎧 每日文獻 Podcast · {}（{} 篇）".format(date, n),
                 "title": "每日文獻 Podcast {}".format(date),
                 "performer": "EndNote Daily Digest"}
        with open(queue, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print("enqueued Telegram audio -> {}".format(queue))


if __name__ == "__main__":
    main()
