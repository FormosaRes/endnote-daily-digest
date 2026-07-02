# Zotero 整合

Zotero 當「**每日新知 inbox**」:每天 7 篇自動匯入,你在裡面篩選;值得的再定期收進 EndNote 策展庫。

## API 設定
1. zotero.org 註冊、登入,**開 Sync**(才會同步到行動裝置)。
2. `zotero.org/settings/keys` → 建 private key,**勾「Allow write access」**(自動匯入文獻+PDF 必需);同頁顯示你的 **userID = library id**。
3. 填進 `config.json`:`zotero_api_key` / `zotero_library_id` / `zotero_library_type: user` / `zotero_inbox_collection`。

可用兩種介面:
- **Web API**(`https://api.zotero.org/users/{id}/…`)— 不依賴桌面開著,本 repo 腳本走這條。
- **[zotero-mcp](https://github.com/54yyyu/zotero-mcp)**(`zotero_add_by_doi` 等)— Claude 連上後可即時操作;`add_by_doi` 會自動串 Unpaywall/arXiv/S2/PMC 抓 OA PDF。

## 分類方案:「資料夾管狀態、標籤管主題」
一篇常跨多主題 → 用**標籤**分主題(可多標、pipeline 可靠自動打);**資料夾**只管「狀態/專案」。

**資料夾**
- `收件匣 collection`(`zotero_inbox_collection`)— 每天 7 篇自動進這裡。
- `⭐ 已篩選` — 你掃過要留的(= 之後匯進 EndNote 的候選)。
- 你的**專案/寫作**資料夾 — 自動匯入**不**進這裡;你篩選時手動拖。

**標籤**(pipeline 自動打)
- 主題:`Geochronology 地質年代學` / `Tectonics 大地構造` / `Petrology 岩石學` / `Sedimentology 沉積與地層` / `Geochemistry 地球化學` / `Frontier 前緣`
- 來源:`daily-digest`(跟手動加的區分)

**智慧搜尋**(動態「主題資料夾」)
- `📥 待篩` = `tag is daily-digest` AND `tag isNot keep`
- `🏷 {主題} 近90天` = `tag is {主題}` AND `dateAdded isInTheLast 90 days`

> API 建 saved search:`POST /searches`,conditions 省略 joinMode 預設 `all`(AND);dateAdded 用 `{"operator":"isInTheLast","value":"90 days"}`。

## 匯入文章
- `backfill_zotero.py` — 批次:標題/DOI → Crossref → 建 item(journalArticle) → 加進收件匣 collection + 主題標籤 + `daily-digest`。
- 每日 pipeline — 對選出的 7 篇做同樣的事(可走 Web API 或 `zotero_add_by_doi`)。

## PDF 與配額 ⚠️
**Zotero 免費儲存只有 300MB**。上傳檔案(imported_file)超過配額會回 `413 File would exceed quota`。

兩種附 PDF:
| 方式 | 佔配額 | 同步行動裝置 |
|------|--------|--------------|
| `imported_file`(上傳雲端,`attach_pdfs.py`) | ✅ 佔 | ✅ 會 |
| `linked_file`(連本機檔) | ❌ 不佔 | ❌ 不會(PC 限定) |

- 配額沒滿 → `imported_file`(`attach_pdfs.py`),全裝置同步。
- 配額滿 → 改 `linked_file`(以 `POST /items` 建 `linkMode=linked_file` 的 attachment,`path` 指本機 PDF):不佔配額但**別移動/刪那個 PDF 資料夾否則連結斷**。或升級 Zotero 儲存。

## 檔案上傳流程(Web API,`attach_pdfs.py`)
1. `POST /items` 建 attachment item(`linkMode=imported_file`,`parentItem`)。
2. `POST /items/{key}/file`(form: md5/filename/filesize/mtime,header `If-None-Match: *`)取得上傳授權。
3. `POST` 到回傳的 storage url(body = `prefix + 檔案bytes + suffix`)。
4. `POST /items/{key}/file`(`upload={uploadKey}`)註冊完成。
