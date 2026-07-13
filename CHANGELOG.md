# Changelog

本檔記錄 endnote-daily-digest 的版本變更,對齊 GitHub Releases。格式:最新在上。

## v1.1.0 — 2026-07-13 · 蓄水池模式(發現/推播解耦)

新增候選緩衝池,把「發現」(貴、批次、~每週)與「推播」(便宜、每天)拆開。動機:每日搜尋會快速耗盡搜尋 API 月額度,且對學術文獻沒有必要(晚幾天推無妨)。

### 新功能
- **`scripts/reservoir.py`** — 四個 subcommand:
  - `harvest [--theme T] [--window N]` — 用 OpenAlex(免費/無限)關鍵字搜 + `_kept-seeds.md` 及固定窄種子引用鏈補水;前緣走 Nature-family filter。harvest 當下就 enrich(日期/作者/摘要/期刊/OA-pdf)並算好 `affinity`(引用鏈 +3、關鍵字命中 +≤3、高影響期刊 +2、有摘要 +1),去重 vs recommended-log + 現有池子,擋 preprint/dataset 雜訊。
  - `draw --date D` — 依 affinity→發表日撈 5 主題各 1 + 前緣 2,標 used、寫回池子 + dedup log,>90 天未用自動 expired,某主題見底自動 mini-harvest,吐 JSON。
  - `add <DOI> --theme T` — 手動注入(月度品質補水的 hand-pick 走這條)。
  - `status` — 印各主題水位,unused < 4 標 LOW。
- 池子檔 `<state_dir>/_reservoir.json`(gitignored 的 state);config 讀取沿用 `DIGEST_CONFIG → ./config.json → ../config.json`。

### 行為變更
- **`digest/SKILL.md`**:每日流程從「10–14 查詢搜尋」改為 Step 3 看 `status`(LOW 才 harvest)、Step 4 `draw` 撈 7 篇、Step 5 只寫中文摘要、Step 6 只補 RIS/PDF。平常日不再呼叫搜尋 MCP;付費搜尋額度只留月初品質補水。

## v1.0.2 — 2026-07-02 · 穩健性強化(安全 / queue / 影音 pipeline)

對整條 pipeline 六面向複審 + 對抗式驗證,修掉會「靜默壞掉」的問題。無新功能,行為更可靠。

### 安全 / HIGH
- **H1** Zotero write-scoped API key 過去經「關閉憑證驗證」的 TLS 送出(MITM 可竊 key)。改成 `api.zotero.org` 走**驗證 TLS**,放寬憑證僅留給不帶金鑰的 OA 下載。(`scripts/attach_pdfs.py`, `scripts/backfill_zotero.py`)
- **H2/H3** daemon `send_*` 改三態(ok/retry/drop):永久失敗(>50MB、檔不存在、HTTP 4xx)記 log 後跳過前進,不再每 2s 重試同一筆卡死整條 queue;`sendAudio` 補 50MB 上限防護。(`telegram-daemon/notify-daemon.py`)
- **H4** 影片 >50MB 不再只 print 就 return(當天靜默無片),改推一則帶本機路徑的文字說明。(`scripts/make_video.py`)
- **H5** 把含 `sendVideo` 的 daemon 回拷 repo(先前 repo 缺、與 docs 矛盾)。

### 穩定性 / MEDIUM
- **M4** NotebookLM(create/source/generate/download)與 ffmpeg(encode/probe)加 timeout。
- **M5** NotebookLM 失敗(如登入過期)推一則 Telegram 提醒,不再靜默 `SystemExit`。
- **M7** 下載前先刪舊 mp3,避免 notebooklm 自動改名(`(2)`)害影片任務等不到。
- **M1** 影片末幀補時長,`-shortest` 不再截掉 podcast 尾段。
- **M2** 向量圖 PDF 無嵌入點陣圖時,退回整頁 render。
- **M3** 影片 caption 用「實際入鏡篇數」而非總篇數。
- **M6** 語音完成寫 `{DATE}.done` sentinel,08:15 影片任務等它才動。
- **M8** `process_keeps` 於 inbox 縮短時從 0 重掃(冪等),不再靜默漏 keep。
- **M9** SKILL.md RIS 敘述統一為「每篇一檔」(修 3 處矛盾)。
- **M10** config 註記 `telegram_inbox` 必須 = `<live_daemon_dir>/inbox.jsonl`。

### 清理 / LOW
- **L1** `.gitignore` 補 `inbox.jsonl` / `notify-queue.jsonl`(私人訊息資料)。
- **L2** `backfill_zotero` 不再硬索引 Crossref `message.items`。
- **L3** keep 編號解析用 `\b\d{1,2}\b`,年份/時間不再被拆成假編號。
- **L6** `process_keeps` 的 Crossref UA 改讀 config `mailto`。
- **L7/L8/L9** 文件與 config 一致性:影片歸 `make_video.py`、步數 0–12、`keepers/` 每篇一檔、token 註記、config 補 `sd_work_dir`/`paper_scraper_dir` 佔位鍵。

> 驗證:`py_compile` 全檔 + daemon 三態單元測試 + `make_video` 實跑 + `make_podcast --dry-run`。刻意保留 L4(風格 nit)、L5(僅丟確認回覆;eager offset 為防重播的刻意設計)。
> 套用:scripts 下次排程自動生效;daemon 已重啟套用 H2/H3/H5。

## v1.0.1 — 2026-07-02 · NotebookLM 說書規範 + 影片規範文件化

- README 新增「🎧🎬 語音 / 影片規範」節:podcast 逐篇 6 段說書骨架(問題 → 方法 → 結果〔具體數字〕→ 意義 → 與研究關聯 → 帶走)+ 跨篇串連;影片「只用文章 PDF 原圖、不做 AI 生成視覺、>50MB 不推」。
- `docs/podcast.md`:加「說書骨架」節(對應 `NARRATION_GUIDE`)、修正來源材料說明(摘要一律納入 + 全文 PDF 預設自動餵)、補 `--dry-run`、新增 🎬 影片節。

## v1.0.0 — 2026-07-02 · 首發

以 EndNote 館藏為種子的每日文獻雷達,四路輸出 + 閉環回饋,執行於 Claude Code 排程。

- 🎯 **館藏錨定探索** — Tier 1 引用鏈 + 作者追蹤;Tier 2 館藏親和度排序,非泛關鍵字。
- 📲 **Telegram** 每天 2 則 HTML 推播(publish 日期 + 加長中文摘要 + 可點 OA PDF)。
- 📚 **Zotero** 新知收件匣自動匯入 + OA PDF 附檔。
- 🗂️ **Obsidian** 原子筆記 + Dataview 儀表板;`keep` → 隔天種子(閉環)。
- 🎧 **NotebookLM 中文 podcast**(`make_podcast.py`)+ 🎬 **文章原圖影片**(`make_video.py`,08:15 排程)。
- 修正:podcast 讀不到原子筆記(檔名缺 `.md`)、自動餵當天全文 PDF、新增 `make_video.py`。
