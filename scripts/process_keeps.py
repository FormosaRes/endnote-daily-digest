#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os as _os, json as _json
def _load_cfg():
    _d=_os.path.dirname(_os.path.abspath(__file__))
    for _c in (_os.environ.get("DIGEST_CONFIG"), _os.path.join(_d,"config.json"), _os.path.join(_d,"..","config.json")):
        if _c and _os.path.exists(_c): return _json.load(open(_c,encoding="utf-8"))
    raise FileNotFoundError("config.json not found (set DIGEST_CONFIG, or place beside the script / at repo root)")
_CFG=_load_cfg()
"""
process_keeps.py — closed-loop curation processor for daily-paper-digest.

Reads TWO "keep" signals and folds accepted papers back into the loop:
  1) Telegram replies in the daemon inbox.jsonl  (e.g. "keep 3 7 9", "留 2026-06-18 5")
  2) Obsidian atomic notes whose frontmatter `status:` was changed to `keep`

For every newly-kept paper it:
  - sets the atomic note's frontmatter `status: keep`
  - appends its DOI to _kept-seeds.md      (extra Tier-1 seeds for tomorrow's discovery)
  - writes its OWN per-paper RIS into keepers/{slug}.ris  (one file per paper, NOT merged)

Idempotent: a DOI already in _kept-seeds / a keepers RIS already on disk is skipped;
the inbox is consumed via a pointer file so replies are never double-processed.

Run standalone, or at the START of the daily digest run (Step 0).
"""
import json, re, ssl, sys, urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# ---- paths ----
BASE        = Path(_CFG["paths"]["digest_dir"])
PAPERS      = BASE / "papers"
KEPT        = BASE / "_kept-seeds.md"
KEEPERS_DIR = BASE / "keepers"          # one .ris per kept paper (NOT merged)
INBOX       = Path(_CFG["paths"]["telegram_inbox"])
POINTER     = Path(_os.path.join(_CFG["paths"]["state_dir"], ".keep-inbox.pos"))

ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s|]+", re.I)
_MAILTO = _CFG.get("mailto") or "your-email@example.com"   # Crossref polite-pool UA (L6)

def fetch_ris(doi):
    u = f"https://api.crossref.org/works/{doi}/transform/application/x-research-info-systems"
    req = urllib.request.Request(u, headers={"User-Agent": f"digest/1.0 (mailto:{_MAILTO})"})
    try:
        with urllib.request.urlopen(req, timeout=40, context=ctx) as r:
            t = r.read().decode("utf-8", "replace")
        return t.strip() if t.lstrip().startswith("TY") else None
    except Exception as e:
        print(f"   ! RIS fetch failed {doi}: {e}")
        return None

def read_frontmatter(p):
    txt = p.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", txt, re.S)
    fm = {}
    if m:
        for line in m.group(1).splitlines():
            mm = re.match(r"\s*([A-Za-z_]+):\s*(.*)$", line)
            if mm:
                fm[mm.group(1)] = mm.group(2).strip().strip('"')
    return fm, txt

def set_status_keep(p):
    txt = p.read_text(encoding="utf-8")
    new = re.sub(r"(?m)^(status:\s*).*$", r"\1keep", txt, count=1)
    if new != txt:
        p.write_text(new, encoding="utf-8")
        return True
    return False

# ---- load per-day manifests: {date: {"1": {doi, note}, ...}} ----
manifests = {}
for mf in sorted(PAPERS.glob("_manifest-*.json")) if PAPERS.exists() else []:
    try:
        d = json.loads(mf.read_text(encoding="utf-8"))
        manifests[d["date"]] = d["papers"]
    except Exception:
        pass
latest_date = max(manifests) if manifests else None

# ---- map doi -> note path (scan atomic notes once) ----
doi2note, note_status = {}, {}
if PAPERS.exists():
    for note in PAPERS.glob("*.md"):
        fm, _ = read_frontmatter(note)
        doi = (fm.get("doi") or "").lower()
        if doi:
            doi2note[doi] = note
            note_status[doi] = fm.get("status", "").lower()

kept = {}   # doi -> source label

# ---- signal 1: Telegram inbox "keep ..." ----
def parse_keep(text):
    if not re.search(r"keep|save|留|收|★|⭐", text.lower()):
        return None
    date_m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    body = re.sub(r"\d{4}-\d{2}-\d{2}", "", text)
    # \b...\b so a 3+ digit run (year 2026, time 14:30) is NOT split into fake
    # 1-2 digit paper numbers; invalid numbers are dropped later by manifest lookup (L3).
    nums = [int(x) for x in re.findall(r"\b\d{1,2}\b", body)]
    if not nums:
        return None
    return (date_m.group(1) if date_m else None, nums)

pointer = 0
if POINTER.exists():
    try: pointer = int(POINTER.read_text().strip())
    except Exception: pointer = 0
inbox_lines = [l for l in INBOX.read_text(encoding="utf-8").splitlines() if l.strip()] if INBOX.exists() else []
if pointer > len(inbox_lines):        # inbox truncated/rotated/iCloud-conflict — rescan from 0 (M8)
    print(f"   ! inbox shrank ({len(inbox_lines)} < pointer {pointer}) — rescanning from 0 (idempotent)")
    pointer = 0
for line in inbox_lines[pointer:]:
    try: e = json.loads(line)
    except Exception: continue
    pk = parse_keep(e.get("text", ""))
    if not pk: continue
    date, nums = pk
    date = date or latest_date
    papers = manifests.get(date, {})
    for n in nums:
        info = papers.get(str(n))
        if info and info.get("doi"):
            kept[info["doi"].lower()] = f"Telegram {date}#{n}"
POINTER.parent.mkdir(parents=True, exist_ok=True)
POINTER.write_text(str(len(inbox_lines)), encoding="utf-8")

# ---- signal 2: Obsidian notes already flipped to status: keep ----
for doi, st in note_status.items():
    if st == "keep":
        kept.setdefault(doi, "Obsidian status:keep")

if not kept:
    print("no new keeps. (_kept-seeds / keepers unchanged)")
    sys.exit(0)

# ---- apply ----
KEEPERS_DIR.mkdir(parents=True, exist_ok=True)
kept_text = KEPT.read_text(encoding="utf-8") if KEPT.exists() else \
    "# Kept seeds — DOIs you accepted from the daily digest.\n# Used as extra Tier-1 seeds (citation-chain) for future discovery.\n"
seen_seeds = {d.lower() for d in DOI_RE.findall(kept_text)}

def slug_for(doi):
    note = doi2note.get(doi)
    if note:
        return note.stem                       # e.g. 2026-06-18-hu-pingtung-doublet
    return re.sub(r"[^A-Za-z0-9._-]", "_", doi)  # fallback

new_seed_lines, ris_written, status_set = [], 0, 0
for doi, src in sorted(kept.items()):
    # 1) note status -> keep
    note = doi2note.get(doi)
    if note and note_status.get(doi) != "keep":
        if set_status_keep(note): status_set += 1
    # 2) kept-seeds (dedup)
    if doi not in seen_seeds:
        title = ""
        if note:
            fm, _ = read_frontmatter(note); title = fm.get("title", "")
        new_seed_lines.append(f"- {doi} | {title} | via {src}")
        seen_seeds.add(doi)
    # 3) per-paper RIS file (one per paper, NOT merged) — skip if already present
    ris_path = KEEPERS_DIR / f"{slug_for(doi)}.ris"
    if not ris_path.exists():
        ris = fetch_ris(doi)
        if ris:
            ris_path.write_text(ris + "\n", encoding="utf-8")
            ris_written += 1

if new_seed_lines:
    with KEPT.open("a", encoding="utf-8") as f:
        if not kept_text.endswith("\n"): f.write("\n")
        f.write("\n".join(new_seed_lines) + "\n")

print(f"kept {len(kept)} paper(s):")
for doi, src in sorted(kept.items()):
    print(f"  + {doi}  ({src})")
print(f"  note status->keep: {status_set} | new kept-seeds: {len(new_seed_lines)} | new RIS files: {ris_written}")
print(f"  per-paper RIS in: {KEEPERS_DIR}  (import these into EndNote when archiving)")
