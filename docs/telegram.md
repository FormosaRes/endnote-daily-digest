# Telegram 輸出格式

Telegram = **手機閱讀層 + 一鍵收藏**。每天推 **2 則**訊息:訊息1 放 5 個主題各 1 篇,訊息2 放 2 篇 Nature 前緣 + 結尾操作區。使用者面向文字用**繁體中文**;標題 / 作者 / 期刊 / DOI 維持英文。

## 設計原則

- **訊息要短**:連結一律用 HTML 文字超連結(`<a href>`),不貼長網址。Telegram 4096 上限算的是「解析後可見字數」,超連結的網址不計入 → 又短又能點。
- **閱讀內容在訊息裡講完**:不叫使用者去開 `.md`/檔案(路徑類資訊只在結尾一行提 EndNote 匯入位置)。
- **每篇要有 publish 日期 + 2–3 句加長中文摘要**。

## 每篇區塊(HTML)

```
{①} <b>{Title}</b>
{Authors}, {Year}｜{Journal}｜📅 {YYYY-MM-DD}
📝 {2–3 句中文摘要;扣回聽眾自己的研究方法與主題(方法學校準、與既有框架的對照);主題6 額外點「✨ 新在哪」}
{連結行}
```

**連結行**:
- 有 OA PDF → `<a href="{pdf}">📄 PDF</a> · <a href="https://doi.org/{DOI}">🔗 原文</a>`
- 沒有 → `<a href="https://doi.org/{DOI}">🔗 原文(PDF 需校內網路)</a>`
- **不要**放 RIS 超連結(在瀏覽器會變網頁);RIS 走每日資料夾的合成檔。

## 兩則訊息結構

**訊息 1** — 標題 `📚 文獻推播 {DATE}`,其下依序 5 篇,每篇用主題 emoji 當小標:

| 小標 | 主題 |
|------|------|
| 🧭【地質年代學】 | ① 地質年代學 Geochronology |
| 🗺️【大地構造】 | ② 大地構造 Tectonics |
| 🪨【岩石學】 | ③ 岩石學 Petrology |
| 🌊【沉積地層】 | ④ 沉積與地層 Sedimentology & Stratigraphy |
| 🧪【地球化學】 | ⑤ 地球化學 Geochemistry |

**訊息 2** — 標題 `🌟 文獻推播 {DATE}(前緣)· Nature 系新穎研究`,放前緣 2 篇(⑥⑦)+ 結尾操作區:

```
─────
⭐ 收藏:回覆「keep 編號」(可多個,如 keep 3 9)→ 進你的種子庫＋EndNote 待匯入
📥 EndNote:每篇一個 RIS 在 Daily Paper Digest\{DATE}\;你收藏的另存 keepers\ 待匯入
📄 PDF:已抓 N 篇存同資料夾;付費篇點「📄 PDF」用校內網路(或 EndNote Find Full Text)
🔢 tokens:約 in {tin}/out {tout}
```

> 某主題今日無夠好的新篇 → 略過該篇並在訊息註明「⚠️ {主題}今日 0 篇」,**絕不杜撰**。

## 渲染後範例(訊息 1 的一個 block)

> 🗺️【大地構造】
> ② **Regional geochronology and tectonic evolution of an orogenic belt**
> Doe et al., 2026｜Journal of Structural Geology｜📅 2026-06-18
> 📝 以區域構造與定年資料重建造山帶變形歷史,可與你自己的研究方法與既有框架對照。
> 📄 PDF · 🔗 原文

## HTML 規則(重要)

- 可見文字裡的 `&` `<` `>` 必須轉義成 `&amp;` `&lt;` `&gt;`,否則 Telegram 回 **400**(daemon 會自動退回純文字送出,但就沒超連結了)。`href` 內的 `&` 也要寫成 `&amp;`。
- **只用 `<b>` 和 `<a href="URL">文字</a>`**,不要其他標籤。

## 投遞:寫入 daemon queue

不直接呼叫 Telegram API——每則訊息 **append 一行 JSON** 到 daemon 的 `notify-queue.jsonl`,daemon 輪詢送出:

```json
{"message": "…HTML…", "parse_mode": "HTML"}
```

Python 寫法:`open(path, "a", encoding="utf-8")` + `json.dumps(obj, ensure_ascii=False)`。
語音 / 影片(NotebookLM podcast)由 daemon 的 `sendAudio` / `sendVideo` 另外推,見 [podcast.md](podcast.md)。

> daemon 常駐本機(已脫離 iCloud),你不需要動它,照常 append queue 即可。
