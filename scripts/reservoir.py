#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reservoir.py -- candidate buffer ("water tank") for the daily paper digest.

Decouples DISCOVERY (expensive, batched ~weekly) from DELIVERY (cheap, daily),
so normal days need NO search-API calls at all.

  harvest  : refill the pool via OpenAlex (free/unlimited) + kept-seed citation
             chains + a Nature-family filter for the frontier theme. Dedup vs the
             recommended-log AND the existing pool. Enrich (date/authors/abstract/
             journal/OA-pdf) and score affinity at harvest time.
  draw     : pick today's 7 (1 x 5 themes + 2 frontier) from the pool, ranked by
             affinity then recency; mark them used; emit fully-enriched JSON.
  add      : manually inject a DOI (e.g. a hand-pick from a monthly quality pass)
             into a theme -- feeds the pool without a search API.
  status   : print water levels per theme.

Config-driven: paths come from config.json (see config.example.json). No secrets.
  loader order: $DIGEST_CONFIG -> ./config.json -> ../config.json
Reservoir lives at  <state_dir>/_reservoir.json .
"""
import sys, os, json, re, ssl, time, argparse, urllib.request, urllib.parse
from datetime import date, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
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
STATE_DIR = PATHS.get("state_dir") or HERE
MAILTO = CFG.get("mailto", "you@example.com")
UA = f"daily-digest-reservoir (mailto:{MAILTO})"

RESERVOIR = os.path.join(STATE_DIR, "_reservoir.json")
LOG = os.path.join(DIGEST_DIR, "_recommended-log.md")
KEPT = os.path.join(DIGEST_DIR, "_kept-seeds.md")

STALE_DAYS = 90          # unused entries older than this are expired, never delivered
DEFAULT_PER = 25         # OpenAlex results per query
DEFAULT_WINDOW = 100     # harvest look-back window (days)
LOW_WATER = 4            # themes with fewer unused than this should be re-harvested

# five single-slot themes; Frontier fills 2 slots. Keep these in sync with digest/SKILL.md.
THEMES = ["Geochron", "Tectonics", "Petrology", "SedStrat", "Geochem"]
THEME_META = {
    "Geochron":  {"emoji": "🧭", "label": "地質年代學 Geochronology"},
    "Tectonics": {"emoji": "🗺️", "label": "大地構造 Tectonics"},
    "Petrology": {"emoji": "🪨", "label": "岩石學 Petrology"},
    "SedStrat":  {"emoji": "🌊", "label": "沉積與地層 Sedimentology & Stratigraphy"},
    "Geochem":   {"emoji": "🧪", "label": "地球化學 Geochemistry"},
    "Frontier":  {"emoji": "🌟", "label": "前緣(Nature 系)"},
}

# OpenAlex title_and_abstract.search terms per theme (broad recall). Tune to your fields.
SEARCH_TERMS = {
    "Geochron":  ["radiometric dating", "thermochronology", "geochronology", "isotopic age"],
    "Tectonics": ["orogeny", "plate boundary tectonics", "structural evolution", "regional tectonics"],
    "Petrology": ["metamorphic petrology", "igneous petrology", "phase equilibria", "mineral chemistry"],
    "SedStrat":  ["sedimentary provenance", "basin analysis", "stratigraphy", "depositional system"],
    "Geochem":   ["isotope geochemistry", "fluid-rock interaction", "trace element geochemistry",
                  "elemental geochemistry"],
}
# relevance keywords (lowercased substrings) for junk filtering + affinity scoring
REL_KW = {
    "Geochron":  ["dating", "geochronolog", "thermochron", "isotop", "age model", "radiometric",
                  "closure temp", "diffusion", "cooling age"],
    "Tectonics": ["tectonic", "orogen", "plate", "fault", "structural", "deformation",
                  "collision", "subduction", "shear zone"],
    "Petrology": ["petrolog", "metamorph", "igneous", "mineral", "phase equilibr",
                  "pressure-temperature", "p-t", "facies", "thermobarometr"],
    "SedStrat":  ["sediment", "provenance", "basin", "stratigraph", "deposition", "detrital",
                  "turbidite", "facies", "sequence"],
    "Geochem":   ["geochem", "isotop", "trace element", "fluid", "rock interaction", "elemental",
                  "major element", "metasomat", "ratio"],
    "Frontier":  ["subduction", "tectonic", "orogen", "mantle", "fault", "earthquake",
                  "metamorph", "plate", "collision", "rift", "slab", "magma", "crust"],
}
# Optional: narrow, specific citation seeds per theme (DOIs). Kept empty in the public template;
# _kept-seeds.md (your accepted DOIs, gitignored) is always used as citation seeds too.
FIXED_SEEDS = {}  # e.g. {"Geochron": ["10.xxxx/..."]}

HIGH_IMPACT = ["nature", "geology", "earth and planetary science letters", "tectonics",
               "geochimica", "journal of geophysical research", "lithos",
               "geological society of america bulletin", "journal of structural geology",
               "tectonophysics", "contributions to mineralogy", "communications earth",
               "journal of metamorphic geology", "geochemistry geophysics geosystems",
               "chemical geology", "earth-science reviews"]
NATURE_FAMILY = ["Nature", "Nature Geoscience", "Nature Communications",
                 "Communications Earth", "Nature Reviews Earth"]
JUNK_SRC = ["zenodo", "figshare", "research square", "doaj", "swisstopo", "ssrn",
            "preprint", "open mind", "cern", "researchgate"]
# Frontier is a broad Nature-family net; block off-topic surface/eco/climate-only papers
FRONTIER_BLOCK = ["vegetation", "biodiversity", "species", "ecosystem", "wildfire", "crop",
                  "carbon capture", "air quality", "urban", "pandemic", "covid", "health",
                  "coral reef", "fishery", "agricultur"]
# Frontier must contain at least two hard solid-earth terms
FRONTIER_CORE = ["subduction", "orogen", "tectonic", "fault", "earthquake", "seismic",
                 "mantle", "slab", "metamorph", "rift", "spreading", "magma",
                 "crust", "lithospher", "plate boundary"]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=45) as r:
                return json.load(r)
        except Exception as e:
            last = e; time.sleep(2)
    print("  ERR", url[:90], last, file=sys.stderr); return None


def deinv(idx):
    if not idx: return ""
    pos = {}
    for w, ps in idx.items():
        for p in ps: pos[p] = w
    return " ".join(pos[k] for k in sorted(pos))


def norm_doi(doi):
    if not doi: return ""
    return doi.replace("https://doi.org/", "").lower().strip().rstrip("/")


def load_seen():
    """DOIs already recommended (dedup log)."""
    seen = set()
    if LOG and os.path.exists(LOG):
        for line in open(LOG, encoding="utf-8"):
            m = re.search(r"doi\.org/([^ |]+)", line)
            if m: seen.add(norm_doi(m.group(1)))
    return seen


def load_kept_seeds():
    seeds = []
    if KEPT and os.path.exists(KEPT):
        for line in open(KEPT, encoding="utf-8"):
            m = re.match(r"\s*-\s*([0-9][^ |]+)", line)
            if m: seeds.append(m.group(1).strip())
    return seeds


def load_reservoir():
    if os.path.exists(RESERVOIR):
        return json.load(open(RESERVOIR, encoding="utf-8"))
    return {"themes": {t: [] for t in list(THEME_META)}, "last_harvest": {}}


def save_reservoir(r):
    tmp = RESERVOIR + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    os.replace(tmp, RESERVOIR)


def pool_dois(r):
    out = set()
    for lst in r["themes"].values():
        for e in lst: out.add(e["doi"])
    return out


def enrich_work(w):
    doi = norm_doi(w.get("doi"))
    if not doi: return None
    pl = w.get("primary_location") or {}
    src = (pl.get("source") or {}).get("display_name") or ""
    au = [a["author"]["display_name"] for a in w.get("authorships", [])]
    bl = w.get("best_oa_location") or {}
    return {
        "doi": doi,
        "title": w.get("title") or "",
        "journal": src,
        "date": w.get("publication_date") or "",
        "authors": au,
        "abstract": deinv(w.get("abstract_inverted_index")),
        "oa_pdf": bl.get("pdf_url") or "",
        "source": src,
    }


def relevant(entry, theme):
    """Junk filter + require a theme keyword hit somewhere."""
    src = (entry["source"] or "").lower()
    if any(j in src for j in JUNK_SRC): return False
    if not entry["title"]: return False
    blob = (entry["title"] + " " + entry["abstract"]).lower()
    if theme == "Frontier":
        if any(b in blob for b in FRONTIER_BLOCK): return False
        return sum(1 for kw in FRONTIER_CORE if kw in blob) >= 2
    return any(kw in blob for kw in REL_KW[theme])


def affinity(entry, theme, from_chain):
    a = 0
    if from_chain: a += 3
    blob = (entry["title"] + " " + entry["abstract"]).lower()
    a += min(sum(1 for kw in REL_KW[theme] if kw in blob), 3)
    if any(h in (entry["source"] or "").lower() for h in HIGH_IMPACT): a += 2
    if entry["abstract"]: a += 1
    return a


def harvest(themes, per, window, verbose=True):
    r = load_reservoir()
    seen = load_seen()
    have = pool_dois(r)
    kept = load_kept_seeds()
    frm = (date.today() - timedelta(days=window)).isoformat()
    today = date.today().isoformat()
    added_total = 0

    for theme in themes:
        pending = {}

        def consider(w, from_chain):
            doi = norm_doi(w.get("doi"))
            if not doi or doi in seen or doi in have or doi in pending: return
            pending[doi] = (w, from_chain)

        if theme == "Frontier":
            for q in ["subduction", "tectonic orogen", "mantle fault earthquake", "crust rifting"]:
                d = get(f"https://api.openalex.org/works?search={urllib.parse.quote(q)}"
                        f"&filter=from_publication_date:{frm}&sort=publication_date:desc&per_page={per}")
                if not d: continue
                for x in d.get("results", []):
                    src = ((x.get("primary_location") or {}).get("source") or {}).get("display_name", "") or ""
                    if any(n in src for n in NATURE_FAMILY) and "Scientific Reports" not in src:
                        consider(x, False)
        else:
            for term in SEARCH_TERMS[theme]:
                d = get(f"https://api.openalex.org/works?filter=title_and_abstract.search:"
                        f"{urllib.parse.quote(term)},from_publication_date:{frm}"
                        f"&sort=publication_date:desc&per_page={per}")
                if d:
                    for x in d.get("results", []): consider(x, False)
            for s in (kept + FIXED_SEEDS.get(theme, [])):
                sw = get("https://api.openalex.org/works/https://doi.org/" + s)
                if not sw: continue
                wid = (sw.get("id") or "").split("/")[-1]
                cw = get(f"https://api.openalex.org/works?filter=cites:{wid},"
                         f"from_publication_date:{frm}&sort=publication_date:desc&per_page=8")
                if cw:
                    for x in cw.get("results", []): consider(x, True)

        added = 0
        for doi, (w, from_chain) in pending.items():
            e = enrich_work(w)
            if not e or not relevant(e, theme): continue
            e["affinity"] = affinity(e, theme, from_chain)
            e["reason"] = "chain" if from_chain else "search"
            e["harvested_on"] = today
            e["status"] = "unused"
            r["themes"].setdefault(theme, []).append(e)
            have.add(doi); added += 1
        r["last_harvest"][theme] = today
        added_total += added
        if verbose:
            un = sum(1 for x in r["themes"].get(theme, []) if x["status"] == "unused")
            print(f"  {theme:10s} +{added:2d}  (pool unused now {un})")

    save_reservoir(r)
    if verbose: print(f"harvest done: +{added_total} new candidates")
    return added_total


def expire_stale(r):
    cutoff = (date.today() - timedelta(days=STALE_DAYS)).isoformat()
    n = 0
    for lst in r["themes"].values():
        for e in lst:
            if e["status"] == "unused" and (e.get("harvested_on") or "") < cutoff:
                e["status"] = "expired"; n += 1
    return n


def draw(drawdate, fallback=True):
    r = load_reservoir()
    exp = expire_stale(r)
    picks, empties, used_dois = [], [], set()
    n = 0
    for theme in THEMES + ["Frontier", "Frontier"]:
        cands = [x for x in r["themes"].get(theme, [])
                 if x["status"] == "unused" and x["doi"] not in used_dois]
        cands.sort(key=lambda x: (x.get("affinity", 0), x.get("date", "")), reverse=True)
        e = cands[0] if cands else None
        if e is None and fallback:
            print(f"  [fallback] {theme} dry, mini-harvest...", file=sys.stderr)
            harvest([theme], per=15, window=180, verbose=False)
            r = load_reservoir(); expire_stale(r)
            cands = [x for x in r["themes"].get(theme, [])
                     if x["status"] == "unused" and x["doi"] not in used_dois]
            cands.sort(key=lambda x: (x.get("affinity", 0), x.get("date", "")), reverse=True)
            e = cands[0] if cands else None
        n += 1
        if e is None:
            empties.append(theme)
            picks.append({"n": n, "theme": theme, "empty": True})
            continue
        e["status"] = "used"; e["used_on"] = drawdate
        used_dois.add(e["doi"])
        rec = dict(e); rec["n"] = n; rec["theme"] = theme
        rec["emoji"] = THEME_META[theme]["emoji"]; rec["theme_label"] = THEME_META[theme]["label"]
        picks.append(rec)
    save_reservoir(r)
    out = {"date": drawdate, "expired": exp, "empties": empties, "papers": picks}
    with open(os.path.join(STATE_DIR, f"_draw-{drawdate}.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def add_doi(doi, theme):
    doi = norm_doi(doi)
    r = load_reservoir()
    if doi in pool_dois(r):
        print(f"already in pool: {doi}"); return
    w = get("https://api.openalex.org/works/https://doi.org/" + doi)
    if not w:
        print(f"fetch failed: {doi}"); return
    e = enrich_work(w)
    if not e:
        print(f"unusable: {doi}"); return
    e["affinity"] = affinity(e, theme, from_chain=True) + 1  # hand-picks rank high
    e["reason"] = "manual"; e["harvested_on"] = date.today().isoformat(); e["status"] = "unused"
    r["themes"].setdefault(theme, []).append(e)
    save_reservoir(r)
    print(f"added [{theme}] {doi}  ({e['title'][:70]})")


def status():
    r = load_reservoir()
    print(f"reservoir: {RESERVOIR}")
    low = []
    for t in list(THEME_META):
        lst = r["themes"].get(t, [])
        un = sum(1 for e in lst if e["status"] == "unused")
        us = sum(1 for e in lst if e["status"] == "used")
        ex = sum(1 for e in lst if e["status"] == "expired")
        lh = r.get("last_harvest", {}).get(t, "-")
        flag = "  <-- LOW" if un < LOW_WATER else ""
        if un < LOW_WATER: low.append(t)
        print(f"  {t:10s} unused={un:3d}  used={us:3d}  expired={ex:3d}  last_harvest={lh}{flag}")
    if low:
        print("\nLOW themes -> run:  python reservoir.py harvest --theme " + " --theme ".join(low))
    else:
        print("\nall themes above low-water; no harvest needed.")


def main():
    ap = argparse.ArgumentParser(description="candidate buffer for the daily digest")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ph = sub.add_parser("harvest"); ph.add_argument("--theme", action="append")
    ph.add_argument("--per", type=int, default=DEFAULT_PER)
    ph.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    pd = sub.add_parser("draw"); pd.add_argument("--date", default=date.today().isoformat())
    pd.add_argument("--no-fallback", action="store_true")
    pa = sub.add_parser("add"); pa.add_argument("doi"); pa.add_argument("--theme", required=True)
    sub.add_parser("status")
    a = ap.parse_args()
    if a.cmd == "harvest":
        harvest(a.theme or list(THEME_META), a.per, a.window)
    elif a.cmd == "draw":
        draw(a.date, fallback=not a.no_fallback)
    elif a.cmd == "add":
        add_doi(a.doi, a.theme)
    elif a.cmd == "status":
        status()


if __name__ == "__main__":
    main()
