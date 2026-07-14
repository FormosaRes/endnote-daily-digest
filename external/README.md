# External references (submodules)

These are **references only**, pinned as git submodules. Their source code is **not**
copied into this repository and their licenses do **not** apply to `endnote-daily-digest`.
Each remains the property of its original author under its own license.

To fetch them after cloning:

```bash
git submodule update --init --recursive
```

| Submodule | Purpose | Author | License |
|-----------|---------|--------|---------|
| [`endnote-mcp`](https://github.com/gokmengokhan/endnote-mcp) | EndNote → Claude MCP server (search / cite / read PDFs) | gokmengokhan | AGPL-3.0 |
| [`paper-scraper`](https://github.com/GAO-pooh/paper-scraper) | INFORMS / ScienceDirect full-text scrapers (institutional cookie) | GAO-pooh | MIT |
| [`paper-fetch`](https://github.com/drpwchen/paper-fetch) | DOI → full-text PDF via a legitimate **route ladder** (OA → publisher TDM API → your own institutional proxy → resolver link) | drpwchen | MIT |

> **Note on `paper-scraper/sd_scraper.py`:** scraping ScienceDirect with institutional
> cookies may violate the publisher's terms of service and the institution's license
> agreement. Kept here as a reference pointer only; do not run against paywalled content
> without authorization.

> **Note on `paper-fetch`:** this is the reference implementation of the "download end" of a
> paper pipeline. Its **OA route ladder** (`route_unpaywall`) is ported into
> `scripts/attach_pdfs.py` — traverse every Unpaywall `oa_location`, reroute PMC landings to
> the Europe PMC render endpoint, DOI→PMCID via NCBI idconv, and scrape landing-page
> `citation_pdf_url` — all free, no keys, no paywall bypass. The submodule additionally
> carries the routes this project does **not** wire in: official publisher text-mining (TDM)
> APIs and your **own** institutional proxy/login (layers 2–4, which need your registered
> keys), plus holdings/entitlement checks. It ships no institution's access. See its
> [`AGENTS.md`](https://github.com/drpwchen/paper-fetch/blob/main/AGENTS.md) and
> [`DISCLAIMER.md`](https://github.com/drpwchen/paper-fetch/blob/main/DISCLAIMER.md).
