# Dispatch 派令產生器

依 Workstation xlsx 產生 MCS 派令 CSV。派令按 Zone 分池,同池 device 兩兩配對產生 Source → Dest 排列。

**兩種介面:**
- **網頁版** — Flask + MariaDB 後端,支援 **多人共用 preset** (存/取/命名/切換),適合現場同仁
- **CLI 版** (`generate.py`) — 適合自動化 / 批次 / CI

**新版重點 (v2):**
- 加入 Flask 後端 (取代 `python3 -m http.server`)
- 加入 **MariaDB preset 儲存** (Save / Save As / Load / Delete,含作者/時間)
- 加入 systemd 服務化 (開機自動啟動)

首次安裝請看 [doc/installation.md](doc/installation.md)。

---

## 目錄結構

```
dispatch_generator/
├── README.md                       專案總覽 (本文件)
├── app.py                          Flask 後端 (serves index.html + /api/presets)
├── index.html                      前端 (含 Preset UI)
├── generate.py                     CLI 版產生器
├── serve.sh                        前景啟動腳本
├── schema.sql                      MariaDB schema
├── config.ini                      DB 連線資訊 (chmod 600,不進版控)
├── examples/
│   ├── Workstation_5F.xlsx         範例 Workstation 檔
│   └── pools_example.json          自訂 Pool 設定範例 (CLI 版用)
├── output/                         CSV 產出目錄
└── doc/
    ├── installation.md             完整安裝教學
    └── troubleshooting-webserver.md  Web server 排錯
```

---

## 前置需求

| 項目 | 網頁版 | CLI 版 |
|---|---|---|
| Python 3.6+ | 必要 | 必要 |
| Flask | 必要 | 不需要 |
| pymysql | 必要 | 不需要 |
| openpyxl | 不需要 | 必要 |
| MariaDB / MySQL 10.2+ | 必要 (preset 儲存) | 不需要 |
| 瀏覽器 (Chrome/Edge/Firefox) | 必要 | 不需要 |
| SheetJS CDN | 首次載入需要 (可離線化) | 不需要 |

一次裝完:
```bash
pip3 install --user flask pymysql openpyxl
```

---

## 快速開始

### 方式 A:網頁版 (推薦)

**首次部署:** 完整流程見 [doc/installation.md](doc/installation.md),含 DB 建立、config.ini 設定、systemd 服務化。

**已裝好後日常操作:**

若已裝 systemd service (`systemctl --user status dispatch-generator`),服務已在跑,直接開瀏覽器 `http://<Linux IP>:9000/`。若沒裝,前景手動起:
```bash
cd /home/mcsadmin/dispatch_generator
./serve.sh              # port 固定 9000 (改 config.ini 可換)
```

**服務管理 (已裝 systemd):**
```bash
systemctl --user restart dispatch-generator     # 改 config/code 後重啟
systemctl --user stop dispatch-generator        # 停
journalctl --user -u dispatch-generator -f      # 看即時 log
```

**操作流程:**

1. **(選) Author 欄位填名字** — 存 preset 時會記錄是誰改的
2. **(選) 選 Preset → Load** — 直接套用某個已存的 zone→type 對應設定
3. **上傳 xlsx** — 選擇 `examples/Workstation_5F.xlsx` 或你的 Workstation 檔
4. **檢查 Pool 分組** — 預設會把含 `MGZ` 字串的 Zone 併成 `MGZ_POOL`,含 `CST` 併成 `CST_POOL`;可手動改
5. **調整規則** — Trigger Time、CarrierID、其他欄位;需要的話填「排除 Device」清單
6. **(選) Save / Save As...** — 存回 DB 給下次或給同事用
7. **點「產生並下載 CSV」** — CSV 會存到瀏覽器下載目錄

> xlsx 只在瀏覽器內處理;preset 存到 Linux 端 MariaDB (dispatch_generator.presets)。

### 方式 B:CLI 版

```bash
cd /home/mcsadmin/dispatch_generator

# 用預設值產生 (5F 規則,輸出到 output/dispatch.csv)
python3 generate.py

# 指定輸入與輸出
python3 generate.py examples/Workstation_5F.xlsx -o output/my.csv

# 只產前 100 筆做 smoke test
python3 generate.py --max-rows 100

# CarrierID 遞增 (GY001, GY002, ...)
python3 generate.py --carrier-id-incr

# 使用自訂 Pool 定義
python3 generate.py --pools-json examples/pools_example.json

# 查看全部參數
python3 generate.py -h
```

---

## 派令規則

### Pool 分組 (Source / Dest 配對範圍)

同一 Pool 內的 device 才能互相配對。預設 5F 分組:

| Pool 名稱 | 包含 Zone | Carrier Type |
|---|---|---|
| `MGZ_POOL` | `zone_5F_AMR_MGZ`, `zone_5F_AMR_MGZ_OVEN`, `zone_5F_AMR_MGZ_WB` | `MAG1` |
| `CST_POOL` | `zone_5F_AMR_CST` | `F08` / `F12` / `FOUP08` / `FOUP12` (循環) |

配對邏輯: `permutations(devices, 2)` — 每個 device 都會當一次 Source,搭配池內所有其他 device 為 Dest。 N 個 device → N × (N-1) 筆。

### Carrier Type

- 若只填一個 (如 `MAG1`) → 該池所有派令都用它。
- 若填多個 (如 `F08,F12,FOUP08,FOUP12`) → 該池派令依照順序循環套用。

### Trigger Time

從 `00:00:00` 起,每 N 筆遞增 M 分鐘 (預設 `--rows-per-step=10 --min-step=5`)。

小時 mod 24 wrap:當累計時間超過 24 小時,小時會回到 `00`。若要保留累計時數 (`25:00:00`, `26:00:00`...):
- 網頁版:取消「小時 mod 24 wrap」勾選
- CLI:加 `--no-wrap`

### 排除清單

預設排除的 4 個 NG port:

```
MGZ_NG_PORT_02
MGZ_NG_PORT_03
MGZ_NG_PORT_04
CST_NG_PORT_02
```

- 網頁版:在 Step 3 的「排除 Device」欄位增減,支援 `*` 萬用字元 (如 `MGZ_NG_PORT_*`)
- CLI:`--exclude "id1,id2,id3"`

---

## 派令欄位格式

輸出 CSV 表頭 (與 MES 派令格式一致):

```
Group,Trigger Time,CarrierID,Lot ID,Lot Num,Carrier Type,Source,Dest,Priority,Replace,Back,BackCarrierID,Back Carrier Type,Execute Time
```

| 欄位 | 預設值 | 說明 |
|---|---|---|
| Group | `*` | 派令群組 |
| Trigger Time | `HH:MM:SS` | 依規則遞增 |
| CarrierID | `GY001` | 可切換遞增模式 → `GY001, GY002, ...` |
| Lot ID | 空格 | |
| Lot Num | `0` | |
| Carrier Type | 依 Pool 設定 | `MAG1` / `F08` / `F12` / `FOUP08` / `FOUP12` 等 |
| Source | 依 xlsx | 池內 device |
| Dest | 依 xlsx | 池內 device (≠ Source) |
| Priority | `0` | |
| Replace | `0` | |
| Back | `*` | |
| BackCarrierID | 空格 | |
| Back Carrier Type | 空格 | |
| Execute Time | `0` | |

範例輸出:
```csv
Group,Trigger Time,CarrierID,Lot ID,Lot Num,Carrier Type,Source,Dest,Priority,Replace,Back,BackCarrierID,Back Carrier Type,Execute Time
*,00:00:00,GY001, ,0,MAG1,MGZ_05_001,MGZ_05_002,0,0,*, , ,0
*,00:00:00,GY001, ,0,MAG1,MGZ_05_001,MGZ_05_003,0,0,*, , ,0
...
```

---

## 進階:自訂 Pool 配置 (CLI)

寫一個 JSON 檔 (參考 `examples/pools_example.json`):

```json
{
  "MGZ_POOL": {
    "zones": ["zone_5F_AMR_MGZ", "zone_5F_AMR_MGZ_OVEN", "zone_5F_AMR_MGZ_WB"],
    "carrier_types": ["MAG1"]
  },
  "CST_POOL": {
    "zones": ["zone_5F_AMR_CST"],
    "carrier_types": ["F08", "F12", "FOUP08", "FOUP12"]
  }
}
```

執行:
```bash
python3 generate.py --pools-json my_pools.json
```

- `zones`:此 Pool 涵蓋的 Zone_ID 清單。同一個 Pool 內的 device 全部混池互配。
- `carrier_types`:單一或多個。多個時依序循環套用。
- 未在任何 Pool 的 Zone → 該 Zone 的 device 不會被納入輸出。

---

## CLI 參數表

| 參數 | 預設 | 說明 |
|---|---|---|
| `input` (positional) | `examples/Workstation_5F.xlsx` | Workstation xlsx 檔路徑 |
| `-o`, `--output` | `output/dispatch.csv` | 輸出 CSV 路徑 |
| `--sheet` | `Workstation` | xlsx 內的 sheet 名稱 |
| `--pools-json` | (無) | 自訂 Pool 定義 JSON 路徑 |
| `--exclude` | 4 個 NG port | 排除的 Device_ID,逗號分隔 |
| `--rows-per-step` | `10` | 每 N 筆遞增一次 Trigger Time |
| `--min-step` | `5` | 每次遞增的分鐘數 |
| `--no-wrap` | (預設 wrap) | 不做 24h wrap,小時可 > 24 |
| `--carrier-id` | `GY001` | CarrierID 起始值 |
| `--carrier-id-incr` | (預設固定) | 開啟 CarrierID 遞增 |
| `--max-rows` | `0` | 限制產出筆數,`0` 表示不限 |

---

## 常見場景

### 只跑 smoke test (少量派令驗證)
```bash
python3 generate.py --max-rows 50 -o output/smoke.csv
```

### 換別層樓的 Workstation
只要 xlsx 的欄位排列一樣 (Device_ID 在第 4 欄、Zone_ID 在第 7 欄、Enabled 在第 21 欄),直接指定新檔:
```bash
python3 generate.py path/to/Workstation_3F.xlsx --pools-json path/to/3f_pools.json
```

### CarrierID 想要唯一
```bash
python3 generate.py --carrier-id-incr --carrier-id "TEST0001"
```
→ `TEST0001, TEST0002, TEST0003, ...`

### 排除更多 device
```bash
python3 generate.py --exclude "MGZ_NG_PORT_02,MGZ_NG_PORT_03,MGZ_NG_PORT_04,CST_NG_PORT_02,MGZ_05_050"
```

網頁版支援 `*` 萬用字元 (如 `MGZ_NG_PORT_*`),CLI 版目前只吃精確比對。

### Trigger Time 想要一直遞增不 wrap
```bash
python3 generate.py --no-wrap
```

---

## 離線使用網頁版

`index.html` 依賴 CDN 上的 SheetJS。若現場網路無法連外:

```bash
cd /home/mcsadmin/dispatch_generator
curl -o xlsx.full.min.js https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js
```

然後把 `index.html` 內的:
```html
<script src="https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js"></script>
```
改成:
```html
<script src="xlsx.full.min.js"></script>
```

---

## 排錯

### CLI 提示 `openpyxl not installed`
```bash
pip install --user openpyxl
```

### 網頁版上傳很慢或當機
xlsx 過大時瀏覽器解析會慢。可以用 CLI 版跑,或先在 Excel 篩掉 `Enabled=False` 減少行數。

### 產生的 CSV 有奇怪字元 / MES 讀不進去
CSV 用 UTF-8 無 BOM 儲存。若 MES 要求特定編碼 (如 Big5) 用 `iconv` 轉:
```bash
iconv -f UTF-8 -t BIG5 output/dispatch.csv > output/dispatch_big5.csv
```

### Trigger Time 需要不同格式 (例如日期時間戳)
目前寫死 `HH:MM:SS`。需要改的話直接改 `generate.py` 的 `fmt_time()` 或 `index.html` 的 `fmtTime()`,兩邊邏輯要一致。

### 產出量太大 (30 萬筆) MES 吃不下
用 `--max-rows` 縮量,或在 xlsx 內先把不需要測的 Zone 的 `Enabled` 改 `FALSE`。

---

## 修改與維護

網頁版和 CLI 版的**產生邏輯目前分別實作** (JS in `index.html`、Python in `generate.py`),改規則時兩邊都要改。核心對應:

| 功能 | index.html | generate.py |
|---|---|---|
| 讀 xlsx | `handleFile()` | `load_devices()` |
| Trigger Time | `fmtTime()` | `fmt_time()` |
| CarrierID 遞增 | `incrementCID()` | `_increment_cid()` |
| 產生列 | `doGenerate()` | `build_rows()` |
| 預設 Pool | `renderPoolConfig()` | `DEFAULT_POOLS` |
| 預設排除 | 網頁的 excludeDevices `value` | `DEFAULT_EXCLUDE` |

**Preset (只在網頁版):**

| 元件 | 檔案 | 說明 |
|---|---|---|
| API endpoint | `app.py` | Flask routes `/api/presets` (GET/POST/DELETE) 和 `/api/presets/<name>` |
| DB schema | `schema.sql` | `dispatch_generator.presets` table |
| 前端 UI | `index.html` | `refreshPresets/loadPreset/savePresetAs/deletePreset` |
| Config 格式 | `index.html` | `collectFullConfig()` / `applyConfig()` — JSON 結構 `{pools_by_zone, step3}` |

---

## Preset API

網頁 UI 呼叫的後端 REST API,也可以自己用 curl / Python 直接叫。

| Method | Path | 說明 |
|---|---|---|
| `GET` | `/api/presets` | 列所有 preset (name, updated_by, updated_at) |
| `GET` | `/api/presets/<name>` | 取單一 preset (含 config JSON) |
| `POST` | `/api/presets` | 新增或更新 (upsert),body `{name, config, updated_by}` |
| `DELETE` | `/api/presets/<name>` | 刪除 |
| `GET` | `/api/health` | 健康檢查 (含 DB 連線狀態) |

範例 (curl):
```bash
# 列 preset
curl -sS http://<Linux IP>:9000/api/presets

# 取某個 preset
curl -sS http://<Linux IP>:9000/api/presets/5F_default

# 存/更新 preset
curl -sS -X POST http://<Linux IP>:9000/api/presets \
  -H 'Content-Type: application/json' \
  -d '{"name":"my_preset","config":{...},"updated_by":"cyy"}'

# 刪除
curl -sS -X DELETE http://<Linux IP>:9000/api/presets/my_preset
```
