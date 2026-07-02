#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_video.py — build a figure-slideshow video from a day's digest PDFs + the podcast mp3.

Requirement (user): the video MUST use figures extracted FROM the article PDFs.
No AI-generated visuals (so NotebookLM 'generate video' is deliberately NOT used).

Flow:
  read manifest for DATE -> locate the day's downloaded PDFs ({digest_dir}/{DATE}/*.pdf)
    -> extract ALL figures (PyMuPDF, filter tiny logos/rules)
    -> normalize each to 1280x720 letterbox + burn a CJK caption "[n] title" (Pillow)
    -> concat frames synced to {state_dir}/podcast/{DATE}_digest.mp3 (bundled ffmpeg)
    -> write {state_dir}/video/{DATE}_digest.mp4
    -> (optional --push) enqueue a Telegram sendVideo entry for the daemon

Deps: PyMuPDF, Pillow, imageio-ffmpeg  (all pip-installable, no system installer).
Config-driven (same loader as make_podcast.py): $DIGEST_CONFIG -> ./config.json -> ../config.json
"""
import os, sys, re, json, argparse, subprocess, datetime, glob, tempfile, shutil

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

HERE = os.path.dirname(os.path.abspath(__file__))
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

W, H = 1280, 720
MIN_PX = 250          # skip images smaller than this on either side (logos/icons)
MAX_AR = 12.0         # skip extreme aspect ratios (rules/banners)
MIN_DUR, MAX_DUR = 2.0, 15.0   # per-frame = audio/n, clamped; fills the podcast length
CJK_FONT = next((p for p in (
    r"C:\Windows\Fonts\msjh.ttc", r"C:\Windows\Fonts\mingliu.ttc") if os.path.exists(p)), None)


def _load_cfg():
    for c in (os.environ.get("DIGEST_CONFIG"),
              os.path.join(HERE, "config.json"),
              os.path.join(HERE, "..", "config.json")):
        if c and os.path.exists(c):
            return json.load(open(c, encoding="utf-8"))
    raise FileNotFoundError("config.json not found")


CFG = _load_cfg()
PATHS = CFG.get("paths", {})
DIGEST_DIR = PATHS.get("digest_dir")
STATE_DIR = PATHS.get("state_dir") or "."
DAEMON_DIR = PATHS.get("live_daemon_dir")


def extract_figures(pdf_path, out_dir, tag):
    """Extract all sizable figures from a PDF, dedup by xref. Returns list of PNG paths."""
    saved, seen = [], set()
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print("  open fail {}: {}".format(os.path.basename(pdf_path), e))
        return saved
    idx = 0
    for pno in range(len(doc)):
        for img in doc.get_page_images(pno, full=True):
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                pix = fitz.Pixmap(doc, xref)
                if pix.width < MIN_PX or pix.height < MIN_PX:
                    continue
                ar = max(pix.width, pix.height) / max(1, min(pix.width, pix.height))
                if ar > MAX_AR:
                    continue
                if pix.n >= 5 or pix.alpha:            # CMYK / alpha -> RGB
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                idx += 1
                p = os.path.join(out_dir, "{}_{:03d}.png".format(tag, idx))
                pix.save(p)
                saved.append(p)
            except Exception as e:
                print("  fig skip (xref {}): {}".format(xref, e))
    if not saved:                                   # vector-only PDF: render pages as slides (M2)
        for pno in range(min(len(doc), 6)):
            try:
                pix = doc[pno].get_pixmap(dpi=150)
                idx += 1
                p = os.path.join(out_dir, "{}_pg{:03d}.png".format(tag, idx))
                pix.save(p)
                saved.append(p)
            except Exception as e:
                print("  page-render skip (p{}): {}".format(pno, e))
    doc.close()
    return saved


def normalize(src, dst, caption):
    """Letterbox src into WxH black canvas; burn a bottom caption bar."""
    canvas = Image.new("RGB", (W, H), (12, 12, 14))
    try:
        im = Image.open(src).convert("RGB")
    except Exception:
        return False
    im.thumbnail((W, H - 90), Image.LANCZOS)         # leave room for caption bar
    canvas.paste(im, ((W - im.width) // 2, (H - 90 - im.height) // 2))
    if caption and CJK_FONT:
        d = ImageDraw.Draw(canvas, "RGBA")
        d.rectangle([0, H - 64, W, H], fill=(0, 0, 0, 170))
        try:
            font = ImageFont.truetype(CJK_FONT, 26)
        except Exception:
            font = ImageFont.load_default()
        txt = caption
        while d.textlength(txt, font=font) > W - 40 and len(txt) > 4:
            txt = txt[:-2]
        d.text((20, H - 52), txt, fill=(240, 240, 240), font=font)
    canvas.save(dst)
    return True


def audio_seconds(mp3):
    try:
        r = subprocess.run([FFMPEG, "-i", mp3], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
    except subprocess.TimeoutExpired:
        return None
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", r.stderr or "")
    if not m:
        return None
    hh, mm, ss = m.groups()
    return int(hh) * 3600 + int(mm) * 60 + float(ss)


def main():
    ap = argparse.ArgumentParser(description="Build figure-slideshow video from a day's digest.")
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--push", action="store_true", help="enqueue Telegram sendVideo for the daemon")
    ap.add_argument("--max-mb", type=float, default=48.0, help="target max size (Telegram bot limit 50)")
    args = ap.parse_args()

    if not DIGEST_DIR:
        raise SystemExit("set paths.digest_dir in config.json")
    date = args.date
    manifest_path = os.path.join(DIGEST_DIR, "papers", "_manifest-{}.json".format(date))
    manifest = json.load(open(manifest_path, encoding="utf-8")) if os.path.exists(manifest_path) else {"papers": {}}
    papers = manifest.get("papers", {})

    day_dir = os.path.join(DIGEST_DIR, date)
    pdfs = sorted(glob.glob(os.path.join(day_dir, "*.pdf")))
    if not pdfs:
        raise SystemExit("no PDFs in {}".format(day_dir))

    mp3 = os.path.join(STATE_DIR, "podcast", "{}_digest.mp3".format(date))
    if not os.path.exists(mp3):
        raise SystemExit("podcast mp3 not found (run make_podcast.py first): {}".format(mp3))

    work = tempfile.mkdtemp(prefix="digestvid_")
    try:
        # title lookup by NN prefix (matches RIS/PDF naming {NN}_slug.pdf)
        title_by_nn = {str(int(k)): (v.get("title") or "") for k, v in papers.items()}

        frames = []
        covered = set()                            # distinct papers that actually contributed a frame (M3)
        for pdf in pdfs:
            base = os.path.basename(pdf)
            m = re.match(r"(\d+)", base)
            nn = str(int(m.group(1))) if m else "?"
            title = title_by_nn.get(nn, "") or base.rsplit(".", 1)[0]
            figs = extract_figures(pdf, work, "p{}".format(nn.zfill(2)))
            print("  {} -> {} figures".format(base, len(figs)))
            for i, f in enumerate(figs, 1):
                cap = "[{}] {}".format(nn, title)
                norm = f.rsplit(".", 1)[0] + "_n.png"
                if normalize(f, norm, cap):
                    frames.append(norm)
                    covered.add(nn)

        if not frames:
            raise SystemExit("no usable figures extracted from the day's PDFs")

        dur = audio_seconds(mp3) or (len(frames) * 4.0)
        per = min(MAX_DUR, max(MIN_DUR, dur / len(frames)))
        # last frame absorbs the remainder so the slideshow always covers the full
        # audio; otherwise -shortest would clip the podcast tail when frames are few (M1).
        last_dur = max(per, dur - per * (len(frames) - 1))
        print("{} frames, audio {:.0f}s, {:.2f}s/frame (last {:.2f}s)".format(
            len(frames), dur, per, last_dur))

        # concat demuxer list (repeat last frame per ffmpeg quirk)
        listf = os.path.join(work, "frames.txt")
        with open(listf, "w", encoding="utf-8") as f:
            for i, fr in enumerate(frames):
                f.write("file '{}'\n".format(fr.replace("\\", "/")))
                f.write("duration {:.3f}\n".format(last_dur if i == len(frames) - 1 else per))
            f.write("file '{}'\n".format(frames[-1].replace("\\", "/")))

        os.makedirs(os.path.join(STATE_DIR, "video"), exist_ok=True)
        out = os.path.join(STATE_DIR, "video", "{}_digest.mp4".format(date))
        cmd = [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", listf, "-i", mp3,
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", "-crf", "26",
               "-preset", "veryfast", "-c:a", "aac", "-b:a", "128k", "-shortest",
               "-movflags", "+faststart", out]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=900)     # guard against a hung ffmpeg (M4)
        except subprocess.TimeoutExpired:
            raise SystemExit("ffmpeg timed out after 900s")
        if r.returncode != 0:
            print(r.stderr[-1500:] if r.stderr else "")
            raise SystemExit("ffmpeg failed ({})".format(r.returncode))
        size_mb = os.path.getsize(out) / 1e6
        print("video -> {} ({:.1f} MB)".format(out, size_mb))

        if args.push:
            if not DAEMON_DIR:
                print("--push set but paths.live_daemon_dir missing; skipped")
                return
            queue = os.path.join(DAEMON_DIR, "notify-queue.jsonl")
            if size_mb > args.max_mb:
                # Too big for Telegram's 50 MB bot limit. Don't silently drop the
                # day's video: enqueue a text notice pointing at the local file so
                # the user still gets told (Drive upload can replace this later).
                notice = ("🎬 今日文獻影片 {:.0f}MB 超過 Telegram 50MB 上限,未推送。"
                          "已存本機:{}(可在 Obsidian 或本機查看)。".format(size_mb, out))
                with open(queue, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"message": notice, "parse_mode": "HTML"},
                                       ensure_ascii=False) + "\n")
                print("video {:.1f} MB > {} MB; enqueued text notice instead -> {}".format(
                    size_mb, args.max_mb, queue))
                return
            entry = {"type": "video", "video": out,
                     "caption": "🎬 每日文獻影片 · {}（{} 篇有全文原圖）".format(date, len(covered) or len(pdfs))}
            with open(queue, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            print("enqueued Telegram video -> {}".format(queue))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
