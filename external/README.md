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

> **Note on `paper-scraper/sd_scraper.py`:** scraping ScienceDirect with institutional
> cookies may violate the publisher's terms of service and the institution's license
> agreement. Kept here as a reference pointer only; do not run against paywalled content
> without authorization.
