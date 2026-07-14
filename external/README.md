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

> **Note on `paper-fetch`:** this is the reference implementation of the "download end" of
> a paper pipeline — the same route-ladder idea that `scripts/attach_pdfs.py` applies for
> OA-only fetching (Unpaywall → OpenAlex → Semantic Scholar → publisher pattern), but done
> more robustly: it adds PubMed Central / Europe PMC, official publisher text-mining (TDM)
> APIs, `%PDF` magic-byte validation, and holdings/entitlement checks. Layer 1 (open access)
> works with only an email; layers 2–4 require **your own** registered keys and institutional
> login. It is not a paywall bypass and ships no institution's access — kept here as a
> reference pointer only. See its [`AGENTS.md`](https://github.com/drpwchen/paper-fetch/blob/main/AGENTS.md)
> and [`DISCLAIMER.md`](https://github.com/drpwchen/paper-fetch/blob/main/DISCLAIMER.md).
