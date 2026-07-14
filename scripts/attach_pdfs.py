#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Attach OA PDFs to existing Zotero items (in claude mcp collection) that lack a PDF.
# Uses Zotero Web API full file-upload flow. OA sources: Unpaywall + OpenAlex + Semantic Scholar.
# For a more robust route ladder (adds PMC/Europe PMC, publisher TDM APIs, %PDF validation,
# institutional proxy + holdings checks) see the reference submodule external/paper-fetch.
import json, re, ssl, sys, time, hashlib, urllib.request, urllib.parse, urllib.error
sys.stdout.reconfigure(encoding="utf-8")
import os as _os, json as _json
def _load_cfg():
    _d=_os.path.dirname(_os.path.abspath(__file__))
    for _c in (_os.environ.get("DIGEST_CONFIG"), _os.path.join(_d,"config.json"), _os.path.join(_d,"..","config.json")):
        if _c and _os.path.exists(_c): return _json.load(open(_c,encoding="utf-8"))
    raise FileNotFoundError("config.json not found (set DIGEST_CONFIG, or place beside the script / at repo root)")
_CFG=_load_cfg()
# relaxed TLS for OA PDF mirrors / metadata APIs (no API key ever sent over these)
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
# verified TLS reserved for api.zotero.org, which carries the write-scoped API key
ctx_z=ssl.create_default_context()
KEY=_CFG["zotero_api_key"]; LIB=_CFG["zotero_library_id"]; ZBASE=f"https://api.zotero.org/users/{LIB}"
COLL=_CFG.get("zotero_inbox_collection",""); MAIL=_CFG.get("mailto","")
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
ZH={"Zotero-API-Key":KEY,"Zotero-API-Version":"3"}
LIMIT=int(sys.argv[1]) if len(sys.argv)>1 else 9999

def raw(url, headers=None, method="GET", body=None, timeout=60):
    req=urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    _c=ctx_z if (urllib.parse.urlparse(url).hostname or "").endswith("api.zotero.org") else ctx
    try:
        with urllib.request.urlopen(req,timeout=timeout,context=_c) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()

def jget(url, headers=None):
    st,h,b=raw(url, headers)
    try: return st,h,json.loads(b.decode("utf-8","replace")) if b else None
    except: return st,h,None

def dl(url):
    try:
        st,h,b=raw(url, {"User-Agent":UA,"Accept":"application/pdf,*/*"}, timeout=90)
        if st==200 and b[:5]==b"%PDF-": return b
    except Exception: pass
    return None

def oa_pdf(doi):
    # 1) Unpaywall
    try:
        st,_,d=jget(f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={MAIL}",{"User-Agent":UA})
        if st==200 and d:
            loc=d.get("best_oa_location") or {}
            for u in [loc.get("url_for_pdf")]+[ (l or {}).get("url_for_pdf") for l in (d.get("oa_locations") or [])]:
                if u:
                    b=dl(u)
                    if b: return b,"unpaywall"
    except Exception: pass
    # 2) OpenAlex
    try:
        st,_,d=jget(f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(doi)}?mailto={MAIL}",{"User-Agent":UA})
        if st==200 and d:
            u=((d.get("best_oa_location") or {}).get("pdf_url")) or ((d.get("primary_location") or {}).get("pdf_url"))
            if u:
                b=dl(u)
                if b: return b,"openalex"
    except Exception: pass
    # 3) Semantic Scholar
    try:
        st,_,d=jget(f"https://api.semanticscholar.org/graph/v1/paper/DOI:{urllib.parse.quote(doi)}?fields=openAccessPdf",{"User-Agent":UA})
        if st==200 and d and d.get("openAccessPdf"):
            u=d["openAccessPdf"].get("url")
            if u:
                b=dl(u)
                if b: return b,"s2"
    except Exception: pass
    # 4) nature OA pattern
    if doi.lower().startswith("10.1038/"):
        b=dl(f"https://www.nature.com/articles/{doi.split('/',1)[1]}.pdf")
        if b: return b,"nature"
    return None,None

def has_pdf(key):
    st,_,kids=jget(f"{ZBASE}/items/{key}/children",ZH)
    if st==200 and kids:
        for k in kids:
            if (k.get("data",{}).get("contentType")=="application/pdf"): return True
    return False

# attachment template
_,_,ATPL=jget(f"https://api.zotero.org/items/new?itemType=attachment&linkMode=imported_file",ZH)

def attach(parent, pdf, fname):
    # 1) create attachment item
    a=json.loads(json.dumps(ATPL))
    a["parentItem"]=parent; a["title"]="Full Text PDF"; a["filename"]=fname; a["contentType"]="application/pdf"
    st,h,b=raw(f"{ZBASE}/items", {**ZH,"Content-Type":"application/json"}, "POST", json.dumps([a]).encode())
    res=json.loads(b.decode("utf-8","replace"))
    if not res.get("successful"): return f"create-attach-fail {res.get('failed')}"
    ak=res["successful"]["0"]["key"]
    # 2) upload authorization
    md5=hashlib.md5(pdf).hexdigest(); mtime=int(time.time()*1000)
    form=urllib.parse.urlencode({"md5":md5,"filename":fname,"filesize":len(pdf),"mtime":mtime,"contentType":"application/pdf","charset":""}).encode()
    st,h,b=raw(f"{ZBASE}/items/{ak}/file", {**ZH,"Content-Type":"application/x-www-form-urlencoded","If-None-Match":"*"}, "POST", form)
    if st!=200: return f"auth-fail {st} {b[:120]}"
    auth=json.loads(b.decode("utf-8","replace"))
    if auth.get("exists"): return "exists(md5)"
    # 3) upload to storage
    body=auth["prefix"].encode("utf-8")+pdf+auth["suffix"].encode("utf-8")
    st,h,b=raw(auth["url"], {"Content-Type":auth["contentType"]}, "POST", body, timeout=180)
    if st not in (200,201): return f"upload-fail {st}"
    # 4) register
    st,h,b=raw(f"{ZBASE}/items/{ak}/file", {**ZH,"Content-Type":"application/x-www-form-urlencoded","If-None-Match":"*"}, "POST", f"upload={auth['uploadKey']}".encode())
    if st!=204: return f"register-fail {st}"
    return "OK"

# gather top-level items in collection
items=[]; start=0
while True:
    st,h,batch=jget(f"{ZBASE}/collections/{COLL}/items/top?limit=100&start={start}",ZH)
    if st!=200 or not batch: break
    items+=batch
    if len(batch)<100: break
    start+=100
print(f"claude mcp 收件匣 top-level 項目: {len(items)}")

done=skip=nooa=fail=0; processed=0
for it in items:
    if processed>=LIMIT: break
    d=it["data"]; key=d["key"]; doi=(d.get("DOI") or "").strip()
    title=(d.get("title") or "")[:50]
    if not doi: continue
    if has_pdf(key): skip+=1; continue
    processed+=1
    pdf,src=oa_pdf(doi)
    if not pdf:
        nooa+=1; print(f"  ✗ 無OA {doi} | {title}"); continue
    fn=re.sub(r"[^A-Za-z0-9._-]","_",doi)+".pdf"
    r=attach(key,pdf,fn)
    if r=="OK": done+=1; print(f"  ✓ 附上 ({src},{len(pdf)//1024}KB) {doi}")
    else: fail+=1; print(f"  ! {r} {doi}")
    time.sleep(0.3)

print(f"\n附上 {done} | 已有PDF跳過 {skip} | 無OA(需校內) {nooa} | 失敗 {fail} | 本次處理 {processed}")
