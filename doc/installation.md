# 安裝教學

從零把 Dispatch 派令產生器部署到一台新機器上,包含 Flask 後端 + MariaDB preset 儲存 + systemd 自動啟動。

**適用情境:**
- 換機、重灌後重新部署
- 給同事/新環境安裝
- 系統升級後恢復服務

---

## 目錄

1. [系統需求](#系統需求)
2. [Step 1. 取得專案檔案](#step-1-取得專案檔案)
3. [Step 2. 安裝 Python 依賴](#step-2-安裝-python-依賴)
4. [Step 3. 設定資料庫](#step-3-設定資料庫)
5. [Step 4. 設定 config.ini](#step-4-設定-configini)
6. [Step 5. 啟動 Flask 後端](#step-5-啟動-flask-後端)
7. [Step 6. 從 Windows 連進來](#step-6-從-windows-連進來)
8. [Step 7. 驗證安裝](#step-7-驗證安裝)
9. [Step 8. 開機自動啟動 (systemd)](#step-8-開機自動啟動-systemd)
10. [備份 / 還原 preset DB](#備份--還原-preset-db)
11. [解除安裝 / 移除](#解除安裝--移除)

---

## 系統需求

| 項目 | 版本 / 需求 | 用途 |
|---|---|---|
| Linux | RHEL / CentOS / Ubuntu / 其他 | 主機 OS |
| Python | 3.6 以上 | Flask 後端 + CLI 版 |
| Flask | 0.12+ | Web 後端框架 |
| pymysql | 1.0+ | Python ↔ MariaDB 連線 |
| openpyxl (Python 套件) | 3.x | **只有 CLI 版**需要 (`generate.py`) |
| MariaDB / MySQL | 10.2+ (需 JSON 欄位支援) | Preset 儲存 |
| 瀏覽器 | Chrome / Edge / Firefox 現代版 | 前端 UI |
| 網路 | 首次載入 SheetJS CDN 需要 | 可離線化 (見末尾) |

**權限需求:**
- **Linux:** 一般使用者權限就能跑 (不需要 root)
- **DB:** 需要能建 database 和 table 的帳號 (通常 root 或給你一個獨立 DB user)
- **防火牆:** 若要外部電腦連進來,需要 sudo 開 port,或用 SSH tunnel (見 Step 6)

---

## Step 1. 取得專案檔案

### 方式 A:從其他機器 `scp` 複製 (最快)

在來源機器打包 (排除 output/ 和 config.ini — 目標機器要重新設):
```bash
cd /home/mcsadmin
tar czf dispatch_generator.tar.gz \
    --exclude='dispatch_generator/output/*' \
    --exclude='dispatch_generator/config.ini' \
    --exclude='dispatch_generator/__pycache__' \
    dispatch_generator/
```

`scp` 過去:
```bash
scp dispatch_generator.tar.gz mcsadmin@<新機器IP>:/home/mcsadmin/
```

在新機器解壓:
```bash
cd /home/mcsadmin
tar xzf dispatch_generator.tar.gz
mkdir -p dispatch_generator/output
```

### 方式 B:WinSCP / MobaXterm 手動拉

複製整個 `dispatch_generator/` 目錄。**應包含:**
```
dispatch_generator/
├── README.md
├── app.py                          Flask 後端
├── index.html                      前端
├── generate.py                     CLI 版
├── serve.sh                        前景啟動腳本
├── schema.sql                      DB schema
├── examples/
│   ├── Workstation_5F.xlsx
│   └── pools_example.json
└── doc/
    ├── installation.md
    └── troubleshooting-webserver.md
```

**不要複製:**
- `config.ini` — DB 密碼,新環境要重寫
- `output/*.csv` — 產出檔,新環境重新產

---

## Step 2. 安裝 Python 依賴

### 檢查 Python

```bash
python3 --version
```
需要 3.6 以上。若沒裝:
- RHEL/CentOS 8+: `sudo dnf install python3 python3-pip`
- Ubuntu/Debian: `sudo apt install python3 python3-pip`

### 安裝套件

```bash
pip3 install --user pymysql openpyxl
```
> Flask 通常系統已內建;若沒有: `pip3 install --user Flask`

### 驗證

```bash
python3 -c "import flask, pymysql, openpyxl; print('flask', flask.__version__); print('pymysql', pymysql.__version__); print('openpyxl', openpyxl.__version__)"
```
印三個版本號代表 OK。

### 給檔案執行權限

```bash
chmod +x /home/mcsadmin/dispatch_generator/serve.sh
chmod +x /home/mcsadmin/dispatch_generator/app.py
chmod +x /home/mcsadmin/dispatch_generator/generate.py
```

---

## Step 3. 設定資料庫

### 3-1. 確認 MariaDB / MySQL 有跑

```bash
systemctl status mariadb || systemctl status mysqld
ss -tln | grep :3306      # 有 3306 就 OK
```

若沒裝: `sudo dnf install mariadb-server && sudo systemctl enable --now mariadb`

### 3-2. 建立資料庫和 table

用你有權限的 DB 帳號執行 `schema.sql`:

```bash
mysql -u root -p < /home/mcsadmin/dispatch_generator/schema.sql
```

或手動建:
```bash
mysql -u root -p
```
```sql
CREATE DATABASE IF NOT EXISTS dispatch_generator
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE dispatch_generator;
CREATE TABLE presets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    config JSON NOT NULL,
    updated_by VARCHAR(50),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_name (name)
);
```

### 3-3. (選用) 建立獨立 DB 帳號

避免 app.py 直接用 root。建立 dedicated user:
```sql
CREATE USER 'dispatch_gen'@'localhost' IDENTIFIED BY '<你設的密碼>';
GRANT SELECT, INSERT, UPDATE, DELETE ON dispatch_generator.* TO 'dispatch_gen'@'localhost';
FLUSH PRIVILEGES;
```
之後 config.ini 用這個帳號,權限只夠讀寫這一個 DB。

### 3-4. 驗證

```bash
mysql -u root -p dispatch_generator -e "SHOW TABLES; DESC presets;"
```
應看到 `presets` table 和欄位定義。

---

## Step 4. 設定 config.ini

**這個檔案有 DB 密碼,權限要鎖住。**

建立 config.ini:
```bash
cat > /home/mcsadmin/dispatch_generator/config.ini <<'EOF'
[db]
host = 127.0.0.1
port = 3306
user = root
password = <你的DB密碼>
database = dispatch_generator

[server]
host = 0.0.0.0
port = 9000
EOF
chmod 600 /home/mcsadmin/dispatch_generator/config.ini
```

檢查:
```bash
ls -la /home/mcsadmin/dispatch_generator/config.ini
# 應顯示 -rw------- (600),只有你能讀
```

---

## Step 5. 啟動 Flask 後端

### 5-1. 前景測試

```bash
cd /home/mcsadmin/dispatch_generator
./serve.sh
```

看到 `* Running on http://0.0.0.0:9000/ (Press CTRL+C to quit)` 就是 OK。測完 Ctrl-C 停。

### 5-2. 背景常駐 (簡易版,不建議正式使用)

```bash
cd /home/mcsadmin/dispatch_generator
setsid python3 app.py > /tmp/flask.log 2>&1 < /dev/null &
```

正式建議跳到 [Step 8. 開機自動啟動](#step-8-開機自動啟動-systemd) 用 systemd 管理。

### 5-3. 驗證

```bash
ss -tln | grep :9000
curl -sS http://127.0.0.1:9000/api/health
# 應該印: {"db":"ok","ok":true}

curl -sS http://127.0.0.1:9000/api/presets
# 應該印: [] (空陣列,還沒建 preset)
```

### 5-4. 停止

```bash
pkill -f 'python3 app.py'
```

---

## Step 6. 從 Windows 連進來

**先確認 Linux IP 和 SSH 通不通:**
```bash
ip -4 -o addr show | awk '{print $2, $4}'
```
```powershell
# Windows PowerShell:
Test-NetConnection <Linux IP> -Port 22
```

### 方式 A:SSH Tunnel (推薦)

Windows 開新的 PowerShell:
```powershell
ssh -L 9000:localhost:9000 mcsadmin@<Linux IP>
```
登入後保持視窗開著,Windows 瀏覽器打 `http://localhost:9000/`。

### 方式 B:開防火牆

需要 sudo 密碼:
```bash
sudo firewall-cmd --add-port=9000/tcp --permanent
sudo firewall-cmd --reload
```
之後任何電腦可以直接 `http://<Linux IP>:9000/`。

詳細方案和 SSH client (PuTTY/MobaXterm/Xshell) 設定見 [troubleshooting-webserver.md](troubleshooting-webserver.md)。

---

## Step 7. 驗證安裝

Windows 瀏覽器打開網站,應看到:

- 標題 **Dispatch 派令產生器** (暗色主題)
- **Preset 管理** card (Author 欄位 + Preset 下拉 + 5 個按鈕)
- **Step 1. 上傳 Workstation xlsx**

**Preset 流程測試:**
1. Author 欄位填你的名字 (自動存到瀏覽器 localStorage)
2. 上傳 `examples/Workstation_5F.xlsx`
3. 看到 Step 2 出現 4 個 zone
4. 按 **Save As...**,命名 `test_5F`,按確認
5. 頁面下方應出現「已儲存 preset "test_5F" (by 你的名字)」
6. 按 F5 重新整理,Preset 下拉應該有 `test_5F`
7. 選 test_5F → 按 **Load** → Step 2 應該回到你剛才存的設定

**DB 端驗證:**
```bash
mysql -u root -p dispatch_generator -e "SELECT name, updated_by, updated_at FROM presets;"
```

**CLI 版驗證:**
```bash
cd /home/mcsadmin/dispatch_generator
python3 generate.py --max-rows 10 -o /tmp/test.csv
head /tmp/test.csv
```

---

## Step 8. 開機自動啟動 (systemd)

用 **systemd user service**,不需要 root。

### 8-1. 建 service 檔

```bash
mkdir -p ~/.config/systemd/user/
cat > ~/.config/systemd/user/dispatch-generator.service <<'EOF'
[Unit]
Description=Dispatch Generator Flask Web Server
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/mcsadmin/dispatch_generator
ExecStart=/usr/bin/python3 /home/mcsadmin/dispatch_generator/app.py
Restart=on-failure
RestartSec=5
StandardOutput=append:/tmp/dispatch-generator.log
StandardError=append:/tmp/dispatch-generator.log

[Install]
WantedBy=default.target
EOF
```

### 8-2. 啟用並啟動

先停掉手動啟的 Flask:
```bash
pkill -f 'python3 app.py'
```

啟用 systemd 管理:
```bash
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
systemctl --user daemon-reload
systemctl --user enable dispatch-generator.service
systemctl --user start dispatch-generator.service
systemctl --user status dispatch-generator.service     # active (running) 就 OK
```

### 8-3. 讓服務登出後仍常駐 (要 sudo)

預設 user service 只在你登入時活著,登出就停。要 24/7 常駐:
```bash
sudo loginctl enable-linger mcsadmin
```
驗證:
```bash
loginctl show-user mcsadmin -p Linger    # 應為 Linger=yes
```

### 8-4. 常用管理指令

```bash
systemctl --user restart dispatch-generator     # 重啟 (改 code/config 後)
systemctl --user stop dispatch-generator        # 停
systemctl --user disable dispatch-generator     # 取消開機啟動
journalctl --user -u dispatch-generator -f      # 看即時 log
tail -f /tmp/dispatch-generator.log             # 或看檔案 log
```

---

## 備份 / 還原 preset DB

### 備份

```bash
mysqldump -u root -p dispatch_generator > ~/backup/dispatch_gen_$(date +%Y%m%d).sql
```
建議加到 cron 每天自動備份:
```bash
crontab -e
# 加入:
0 2 * * * mysqldump -u root -p'<密碼>' dispatch_generator > /home/mcsadmin/backup/dispatch_gen_$(date +\%Y\%m\%d).sql
```

### 還原

```bash
mysql -u root -p dispatch_generator < ~/backup/dispatch_gen_20260911.sql
```

### 匯出/匯入單一 preset 給同事

從 DB 匯出:
```bash
curl -sS http://127.0.0.1:9000/api/presets/5F_default > 5F_default.json
```

在另一台匯入 (直接 POST):
```bash
NAME=5F_default
curl -sS -X POST http://<那台IP>:9000/api/presets \
  -H 'Content-Type: application/json' \
  --data @- <<EOF
{
  "name": "$NAME",
  "config": $(cat 5F_default.json | python3 -c 'import sys,json; print(json.dumps(json.load(sys.stdin)["config"]))'),
  "updated_by": "imported"
}
EOF
```

---

## 解除安裝 / 移除

### 停 systemd service
```bash
systemctl --user stop dispatch-generator
systemctl --user disable dispatch-generator
rm ~/.config/systemd/user/dispatch-generator.service
systemctl --user daemon-reload
sudo loginctl disable-linger mcsadmin      # 如果有開 linger
```

### 停手動 nohup server
```bash
pkill -f 'python3 app.py'
```

### 刪 DB (**警告:preset 資料全消失**)
```bash
mysql -u root -p -e "DROP DATABASE dispatch_generator;"
# (選用) 刪 dedicated user:
mysql -u root -p -e "DROP USER 'dispatch_gen'@'localhost';"
```

### 關防火牆 port
```bash
sudo firewall-cmd --remove-port=9000/tcp --permanent
sudo firewall-cmd --reload
```

### 刪檔
```bash
rm -rf /home/mcsadmin/dispatch_generator
```

### 移除 pip 套件
```bash
pip3 uninstall pymysql openpyxl
```

---

## 常見安裝問題

### Q1. `python3` 找不到
`which python3`。若沒有: RHEL `sudo dnf install python3`,Ubuntu `sudo apt install python3`。

### Q2. `pip3 install openpyxl` 沒權限
```bash
pip3 install --user openpyxl
```

### Q3. `./serve.sh: Permission denied`
```bash
chmod +x serve.sh app.py generate.py
```

### Q4. `Address already in use` (9000 佔用)
```bash
ss -tlnp | grep :9000       # 找出誰佔的
pkill -f 'python3 app.py'   # 若是自己起的舊 Flask
```

### Q5. Windows 連不到 → `TcpTestSucceeded : False`
99% 是防火牆問題,詳見 [troubleshooting-webserver.md](troubleshooting-webserver.md)。

### Q6. `pymysql.err.OperationalError: (1045, "Access denied")`
DB 帳號或密碼錯。確認 config.ini 的 user/password 能手動連上:
```bash
mysql -u <config裡的user> -p<config裡的password> -e "SELECT USER();"
```

### Q7. Flask 起來但 `/api/health` 回 500
DB 連線問題。看 log:
```bash
journalctl --user -u dispatch-generator -n 50
# 或
tail -30 /tmp/dispatch-generator.log
```
通常是 config.ini 打錯或 DB service 沒跑。

### Q8. Preset 存了但別人看不到
是不是連錯後端 (兩台 Flask 用不同 DB)?確認 config.ini 都指向同一個 DB host + database name。

### Q9. 網頁 SheetJS 沒載入 (Step 2 沒 zone 出現)
現場無外網。把 SheetJS 下載到本地:
```bash
cd /home/mcsadmin/dispatch_generator
curl -o xlsx.full.min.js https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js
```
改 `index.html`:
```html
<script src="xlsx.full.min.js"></script>
```

### Q10. systemd service `Failed to connect to bus`
需要設 XDG_RUNTIME_DIR:
```bash
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
```
加到 `~/.bashrc` 讓每次 SSH 進來自動設。

---

## 相關文件

- [README.md](../README.md) — 專案總覽與功能說明
- [troubleshooting-webserver.md](troubleshooting-webserver.md) — Web server 連不到的完整排錯
- [schema.sql](../schema.sql) — DB schema 定義
