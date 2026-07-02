#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# One-off: backfill the past week's Telegram digest papers into Zotero (claude mcp inbox).
import json, re, ssl, sys, time, urllib.request, urllib.parse, urllib.error
sys.stdout.reconfigure(encoding="utf-8")
import os as _os, json as _json
def _load_cfg():
    _d=_os.path.dirname(_os.path.abspath(__file__))
    for _c in (_os.environ.get("DIGEST_CONFIG"), _os.path.join(_d,"config.json"), _os.path.join(_d,"..","config.json")):
        if _c and _os.path.exists(_c): return _json.load(open(_c,encoding="utf-8"))
    raise FileNotFoundError("config.json not found (set DIGEST_CONFIG, or place beside the script / at repo root)")
_CFG=_load_cfg()
# relaxed TLS for non-Zotero hosts (Crossref metadata); no API key sent over these
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
# verified TLS reserved for api.zotero.org, which carries the write-scoped API key
ctx_z=ssl.create_default_context()
KEY=_CFG["zotero_api_key"]; LIB=_CFG["zotero_library_id"]; ZBASE=f"https://api.zotero.org/users/{LIB}"
CLAUDE_MCP=_CFG.get("zotero_inbox_collection",""); MAILTO=_CFG.get("mailto","")
UA={"User-Agent":f"digest/1.0 (mailto:{MAILTO})"}
ZH={"Zotero-API-Key":KEY,"Zotero-API-Version":"3"}

def http(url, headers=None, method="GET", body=None):
    h=dict(UA); h.update(headers or {})
    data=json.dumps(body).encode() if body is not None else None
    if body is not None: h["Content-Type"]="application/json"
    req=urllib.request.Request(url, data=data, headers=h, method=method)
    _c=ctx_z if (urllib.parse.urlparse(url).hostname or "").endswith("api.zotero.org") else ctx
    try:
        with urllib.request.urlopen(req,timeout=40,context=_c) as r:
            raw=r.read().decode("utf-8","replace")
            return r.status, dict(r.headers), (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        return e.code, {}, {"_err":e.read().decode("utf-8","replace")[:150]}

def cr(path):
    return http("https://api.crossref.org"+path)

# (themes, doi_or_None, title, author_surname, year)
# 填你自己要回填的 DOI/標題;每列格式為 (主題標籤清單, DOI 或 None, 標題, 作者姓氏, 年份)。
# 有 DOI 時標題/作者/年份可留空(None);沒 DOI 時用標題+作者+年份讓 Crossref 解析。
# 通用主題標籤:Geochronology / Tectonics / Petrology / Sedimentology / Geochemistry / Frontier
P=[
(["Tectonics"],"10.1000/example","Regional geochronology and tectonic evolution of an orogenic belt","Doe","2025"),
(["Geochronology"],None,"Radiometric age constraints on a regional metamorphic terrane","Author","2025"),
(["Geochemistry","Frontier"],None,"Isotope geochemistry of fluid-rock interaction in a collisional belt","Author","2025"),
]

STOP={"the","of","a","and","in","from","by","for","on","at","to"}
def toks(s): return set(re.findall(r"[a-z0-9]+",(s or "").lower()))-STOP

def resolve(title, author, year):
    qs="query.bibliographic="+urllib.parse.quote(title+" "+(author or ""))
    if year:
        qs+=f"&filter=from-pub-date:{int(year)-1}-01-01,until-pub-date:{int(year)+1}-12-31"
    qs+="&rows=3&mailto="+MAILTO
    st,_,d=cr("/works?"+qs)
    if st!=200 or not d: return None,None
    want=toks(title)
    for it in ((d.get("message") or {}).get("items") or []):   # L2: no hard index on crossref shape
        ct=" ".join(it.get("title",[]) or [])
        if want and len(want & toks(ct))/len(want)>=0.45:
            return it.get("DOI"), ct[:65]
    return None,None

# template
_,_,TPL=http("https://api.zotero.org/items/new?itemType=journalArticle",ZH)
def build(doi, themes):
    st,_,d=cr("/works/"+urllib.parse.quote(doi)+"?mailto="+MAILTO)
    if st!=200 or not d: return None
    m=d["message"]; it=json.loads(json.dumps(TPL))
    it["title"]=" ".join(m.get("title",[]) or ["(no title)"])
    cs=[]
    for a in m.get("author",[]) or []:
        fam=a.get("family") or a.get("name") or ""
        if fam: cs.append({"creatorType":"author","firstName":a.get("given",""),"lastName":fam})
    it["creators"]=cs
    ct=m.get("container-title") or []; it["publicationTitle"]=ct[0] if ct else ""
    dp=((m.get("published") or m.get("issued") or {}).get("date-parts") or [[None]])[0]
    if dp and dp[0]: it["date"]="-".join((f"{x:02d}" if i else str(x)) for i,x in enumerate(dp))
    it["DOI"]=m.get("DOI",""); it["url"]="https://doi.org/"+m.get("DOI","")
    if m.get("volume"): it["volume"]=str(m["volume"])
    it["tags"]=[{"tag":t} for t in themes]+[{"tag":"daily-digest"},{"tag":"digest-backfill"}]
    it["collections"]=[CLAUDE_MCP]
    return it

# dedup vs existing library
have=set(); start=0
while True:
    st,h,items=http(f"{ZBASE}/items?limit=100&start={start}",ZH)
    if st!=200 or not items: break
    for it in items:
        doi=(it.get("data",{}).get("DOI") or "").lower().strip()
        if doi: have.add(doi)
    if len(items)<100: break
    start+=100
print(f"現有庫含 DOI 項目: {len(have)}")

items=[]; seen=set(); unresolved=[]; dup=0; matched=[]
for themes,doi,title,auth,year in P:
    if not doi:
        doi,mt=resolve(title,auth,year)
        if not doi: unresolved.append(f"{auth} {year} {title[:50]}"); continue
        matched.append(f"{auth}->{mt}")
    dl=doi.lower()
    if dl in seen: continue
    seen.add(dl)
    if dl in have: dup+=1; continue
    bi=build(doi,themes)
    if bi: items.append(bi)
    time.sleep(0.12)

print(f"解析成功 {len(matched)} | 待匯入(新) {len(items)} | 已在庫跳過 {dup} | 解析失敗 {len(unresolved)}")
created=0; failed=0
for i in range(0,len(items),50):
    st,h,res=http(f"{ZBASE}/items",ZH,"POST",items[i:i+50])
    if isinstance(res,dict):
        created+=len(res.get("successful",{})); failed+=len(res.get("failed",{}))
        if res.get("failed"): print("  失敗:",list(res["failed"].values())[:2])
    time.sleep(0.3)
_,h,_=http(f"{ZBASE}/items?limit=1",ZH)
print(f"\n✅ 寫入 {created} 篇 | 失敗 {failed} | 庫內總數 {h.get('Total-Results')}")
if unresolved:
    print("\n⚠️ 沒解析到 DOI:")
    for u in unresolved: print("  -",u)
