# Obsidian 整合

Obsidian = **思考層**:每篇新文一個原子筆記,配 Dataview 儀表板做「待篩 → 已收藏」,並接你既有的文獻筆記/MinerU 流程。

> 這些原子筆記、每日索引與 `_manifest` 都由每日排程 `digest/SKILL.md` 自動寫入 `config.json` 裡 `paths.digest_dir` 指的資料夾——不用手動建,你只負責閱讀與標 `status: keep`。

## Vault 結構
```
{vault}/
├─ Daily Paper Digest/
│   ├─ _Digest 首頁.md          # 儀表板入口(Dataview 待篩/已收藏清單 + 用法)
│   ├─ {DATE}.md                # 每日索引(連到當天原子筆記)
│   ├─ papers/                  # 每篇一個原子筆記
│   │   ├─ {DATE}-{slug}.md
│   │   └─ _manifest-{DATE}.json
│   ├─ _kept-seeds.md           # 你收藏的 DOI(隔天種子)
│   ├─ _recommended-log.md      # 去重 log
│   └─ keepers/                 # 收藏文章的 RIS
└─ 文獻筆記/                      # (可選)你既有 literature 依主題分
```

## 原子筆記 frontmatter
```yaml
---
title: "…"
authors: "…"
year: 2026
journal: "…"
doi: 10.1038/…
url: https://doi.org/10.1038/…
pdf: https://…            # OA 連結,沒有則留空
ris: {DATE}/{NN}_{slug}.ris
themes: [大地構造]
source: daily-digest
date_suggested: 2026-06-22
digest_number: 3
affinity: …
status: suggested        # suggested → keep → archived
tags: [paper/suggested]
---
```

## 原子筆記正文格式

frontmatter 之後的內文(`digest/SKILL.md` Step 8 自動寫入):

```markdown
# {Title}

{Authors} · {Year} · {Journal} · 📅 {YYYY-MM-DD}

📝 {2–3 句中文摘要;扣回聽眾自己的研究方法與主題(方法學校準、與既有框架的對照)}

🔗 [原文](https://doi.org/{DOI}) · 📄 [PDF]({pdf})

---
收藏:把上面 frontmatter 的 `status: suggested` 改成 `status: keep`,或在 Telegram 回 `keep {編號}`。
```

> 與 Telegram 差異:Obsidian 用 Markdown(`# 標題`、`[文字](url)`),Telegram 用 HTML(`<b>`、`<a href>`);內容一致但語法不同。RIS 檔位置寫在 frontmatter 的 `ris:` 欄,不放內文連結。

### 渲染後範例

```markdown
---
title: "Regional geochronology and tectonic evolution of an orogenic belt"
authors: "Doe et al."
year: 2026
journal: "Journal of Structural Geology"
doi: 10.1000/example
url: https://doi.org/10.1000/example
pdf: https://example.org/articles/example.pdf
ris: 2026-06-18/03_doe-orogenic-belt-geochronology.ris
themes: [大地構造]
source: daily-digest
date_suggested: 2026-06-18
digest_number: 3
affinity: 0.82
status: suggested
tags: [paper/suggested]
---

# Regional geochronology and tectonic evolution of an orogenic belt

Doe et al. · 2026 · Journal of Structural Geology · 📅 2026-06-18

📝 以區域構造與定年資料重建造山帶變形歷史,可扣回你自己的研究方法與主題(方法學校準、與既有框架的對照)。

🔗 [原文](https://doi.org/10.1000/example) · 📄 [PDF](https://example.org/articles/example.pdf)

---
收藏:把上面 frontmatter 的 `status: suggested` 改成 `status: keep`,或在 Telegram 回 `keep 3`。
```

### 每日索引 `{DATE}.md`

同一天 7 篇的入口,分 6 主題用 wikilink 連到各原子筆記:

```markdown
🧭 地質年代學：[[2026-06-18-slug|①Title]]
🗺️ 大地構造：[[2026-06-18-doe-orogenic-belt-geochronology|③Regional geochronology and tectonic evolution…]]
…
```

`papers/_manifest-{DATE}.json` 則存「編號 → DOI/note/title」映射,供 `process_keeps.py` 把 Telegram 的 `keep {編號}` 對回 DOI。

## 收藏流程(雙閘門)
- **Obsidian**:打開原子筆記,把 `status: suggested` 改成 `status: keep`。
- **Telegram**:對 bot 回 `keep 3`(用每日索引/訊息的編號)。

兩者都由 `process_keeps.py` 處理 → 收藏 DOI 進 `_kept-seeds.md`(隔天 Tier 1 種子)+ `keepers/`(RIS)。

## Dataview 儀表板
裝 **Dataview** 外掛(設定 → 社群外掛 → 關閉限制模式 → 瀏覽 → Dataview → 安裝啟用)。`_Digest 首頁` 內:

````markdown
## 📥 待篩(suggested)
```dataview
TABLE WITHOUT ID file.link AS 論文, themes AS 主題, date_suggested AS 推薦日
FROM "Daily Paper Digest/papers"
WHERE status = "suggested"
SORT date_suggested DESC
```

## ⭐ 已收藏(keep)
```dataview
TABLE WITHOUT ID file.link AS 論文, themes AS 主題
FROM "Daily Paper Digest/papers"
WHERE status = "keep"
SORT date_suggested DESC
```
````

## ⚠️ iCloud 注意
若 vault 放 iCloud Drive:**iCloud 會還原「移動/改名」**(像把腳本改名成「xxx 2.py」),只「**新建檔 / 改內容**」會留(所以每日筆記、`status:keep` 編輯都正常)。
→ 重新整理資料夾**要在 Obsidian 裡面拖**(app 操作 iCloud 才不還原),別用外部腳本搬 iCloud 內的檔。
