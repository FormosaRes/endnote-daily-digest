# 🎧 NotebookLM Podcast

把每天的 7 篇 digest 轉成一集**中文語音 podcast**（NotebookLM Audio Overview），下載成 mp3，並（可選）推到 Telegram 用手機聽。

## 為什麼用 NotebookLM
NotebookLM 的 Audio Overview 會把來源材料變成兩位主持人的對話式深入討論，適合通勤時聽。本專案透過 [`notebooklm-py`](https://github.com/teng-lin/notebooklm-py)（非官方 CLI，本身也是一個 Claude Code skill）以程式驅動它。

## 說書骨架（餵給 NotebookLM 的規範）

不讓它念摘要流水帳。`make_podcast.py` 把一套**逐篇 6 段骨架**寫進 source doc 開頭與 generate 指令,NotebookLM 依此逐篇講、最後跨篇串連:

| 段 | 講什麼 |
|---|---|
| ① 問題與背景 | 解決什麼問題、為何重要、前人卡在哪(gap) |
| ② 資料與方法 | 樣本/資料、關鍵技術、方法**限制**(模型假設、定年前提、反演前提、分析不確定度) |
| ③ 主要結果 | 關鍵觀察 + **具體數字**(年代、溫壓條件、關鍵比值、地溫梯度),對應哪張圖 |
| ④ 解釋與意義 | 作者怎麼解釋、對隱沒/造山/變質框架的意義、爭議或替代解釋 |
| ⑤ 與研究關聯 | 扣回聽眾自己的研究方法與主題(方法學校準、與既有框架的對照) |
| ⑥ 一句話帶走 | 每篇收束 |

七篇後做 2–3 分鐘跨篇串連。有全文 PDF 就引用細節;只有摘要的講明依摘要、**不編造數字**。骨架文字在 `make_podcast.py` 的 `NARRATION_GUIDE` 常數,要調語氣/結構改那裡即可。

## 安裝（一次）
```bash
uv tool install 'notebooklm-py[browser]'     # 安裝 notebooklm CLI + Playwright
notebooklm login                             # 開瀏覽器登入你的 Google 帳號（cookie 會存檔）
notebooklm auth check --test                 # 確認 session 有效
```
登入一次後 cookie 會留在 `~/.notebooklm/`，之後 cron 可 headless 跑；過期時 `notebooklm auth refresh --quiet` 或重跑 `login`。

## 用法
```bash
# 預設：今天、繁中、短版、deep-dive
python scripts/make_podcast.py

# 指定日期 / 長度 / 同時推到 Telegram
python scripts/make_podcast.py --date 2026-06-29 --length default --push

# 餵全文 PDF（更詳細：背景/方法/結果/討論），放一個資料夾
python scripts/make_podcast.py --pdf-dir C:/path/to/pdfs/2026-06-29
```

旗標：
| 旗標 | 預設 | 說明 |
|------|------|------|
| `--date` | 今天 | 讀 `<digest_dir>/papers/_manifest-<date>.json` |
| `--language` | `zh_Hant` | NotebookLM 語言碼（`notebooklm language list`） |
| `--length` | `short` | `short` ≈ 10–15 分；`default` ≈ 30–40 分；`long` 更長 |
| `--format` | `deep-dive` | 還有 `brief` / `critique` / `debate` |
| `--pdf-dir` | **當天資料夾** | 預設自動抓 `<digest_dir>/<date>/*.pdf` 全文上傳;可指定別的資料夾 |
| `--push` | 關 | 寫一筆 audio 進 `notify-queue.jsonl`，由 daemon 發到 Telegram |
| `--dry-run` | 關 | 只產生 source doc + 回報找到幾個 PDF,不呼叫 NotebookLM(除錯用) |

## 流程
```
manifest + 原子筆記(papers/*.md)
   -> build_source(): 組成一份合併中文來源文件 (<state_dir>/podcast/<date>_source.md)
   -> notebooklm create / source add (+ 可選 PDF)
   -> notebooklm generate audio --language zh_Hant --wait
   -> notebooklm download audio -> <state_dir>/podcast/<date>_digest.mp3
   -> (--push) notify-queue.jsonl 加一筆 {"type":"audio","audio":<mp3>,...}
```

## Telegram 投遞
daemon（`telegram-daemon/notify-daemon.py`）已支援 audio queue 項，用 `sendAudio` 多段上傳（純標準庫）：
```json
{"type":"audio","audio":"C:/.../2026-06-29_digest.mp3","caption":"🎧 每日文獻 Podcast","title":"...","performer":"EndNote Daily Digest"}
```
> Telegram bot `sendAudio` 上限 50MB；長版 mp3 可能逼近，必要時用 `--length short`。

## 來源材料：摘要 + 全文
- **每篇的中文摘要**(原子筆記裡的 📝 段)一律納入。⚠️ manifest 存的筆記名沒有 `.md`,腳本會自動補上再開檔(舊版漏了這步 → NotebookLM 只拿到標題+DOI,語音很空;現已修正)。
- **全文 PDF 預設自動餵**:`--pdf-dir` 不指定時,自動上傳當天 `<digest_dir>/<date>/*.pdf`,能講到背景/方法/結果/討論的細節。但**只有開放取用(OA)的能自動抓**(通常 7 篇裡 3–5 篇);付費牆全文靠機構權限自取(OA-only 立場見 [architecture.md](architecture.md))。上傳只到**你自己的 NotebookLM 帳號**,屬個人研究用途。

## 注意
- **語言**：NotebookLM 支援 50+ 語言；繁中用 `zh_Hant`、簡中 `zh_Hans`。
- **長度**：NotebookLM 不精確聽從「幾分鐘」，只能用 `--length` 三檔粗調。
- **認證脆弱性**：靠 Google session cookie，過期要重登；headless cron 失敗時讓 podcast 步驟「失敗只略過、不擋整個 digest」。

---

## 🎬 影片（`scripts/make_video.py`）

配套的影片**刻意不用 NotebookLM 的 video overview**（那是 AI 自generate 視覺）。規範:**只用文章 PDF 的原圖**。

- 安裝:`pip install PyMuPDF Pillow imageio-ffmpeg`(抽圖 / 字幕 / 內建 ffmpeg,免系統安裝 ffmpeg)。
- 流程:抽當天 `<digest_dir>/<date>/*.pdf` 的**所有圖**(PyMuPDF,濾掉 logo/細線)→ PIL letterbox 到 1280×720 + 燒中文字幕「[編號] 標題」→ ffmpeg 併成投影片、配 `<state_dir>/podcast/<date>_digest.mp3`(每張時長 = 語音長 ÷ 張數,填滿全程)→ 輸出 `<state_dir>/video/<date>_digest.mp4`。
- 用法:`python scripts/make_video.py --date <date> --push`(`--push` 寫 `{"type":"video","video":...}` 進 queue,daemon `sendVideo`)。
- 限制:影片豐富度受 **PDF 抓取率**限制(抓不到 PDF 的篇就沒圖);>50MB(Telegram bot 上限)不推。
- 排程:獨立於 08:15 任務 `daily-paper-video`,會輪詢等 podcast mp3 就緒再產片。
