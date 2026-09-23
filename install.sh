#!/bin/bash
# TSC TOOL 一鍵安裝腳本
#
# 執行順序:
#   1. 檢查 Python 3.6+ / pip3 / mysql client
#   2. 安裝 Python 套件 (flask, pymysql, openpyxl)
#   3. 檢查並啟動 MariaDB/MySQL 服務
#   4. 詢問 DB 連線資訊,執行 schema.sql
#   5. 產生 config.ini (chmod 600)
#   6. chmod +x 腳本
#   7. 建立 systemd --user service,啟用 + 啟動
#   8. (選) 開 firewall port 9000
#   9. (選) 開 loginctl linger 讓服務登出後仍活著
#
# 用法:
#   ./install.sh                # 互動模式 (問你每個選項)
#   DB_PASS=xxx ./install.sh -y # 全部用預設值 + 環境變數帶密碼
#
# 環境變數 (選):
#   DB_HOST         DB 主機 (預設 127.0.0.1)
#   DB_PORT         DB port (預設 3306)
#   DB_USER         DB 帳號 (預設 root)
#   DB_PASS         DB 密碼 (互動模式會問)
#   DB_NAME         Database 名稱 (預設 tsc_tool)
#   APP_PORT        Flask port (預設 9000)
#   ENABLE_LINGER   1 = 自動 sudo loginctl enable-linger (預設 0)
#   OPEN_FIREWALL   1 = 自動 sudo firewall-cmd 開 port (預設 0)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ---------- 顏色輸出 ----------
if [[ -t 1 ]]; then
    C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YLW=$'\033[33m'
    C_CYN=$'\033[36m'; C_BLD=$'\033[1m'; C_RST=$'\033[0m'
else
    C_RED=""; C_GRN=""; C_YLW=""; C_CYN=""; C_BLD=""; C_RST=""
fi
info()  { printf "${C_CYN}==>${C_RST} %s\n" "$*"; }
warn()  { printf "${C_YLW}[warn]${C_RST} %s\n" "$*"; }
error() { printf "${C_RED}[error]${C_RST} %s\n" "$*" >&2; }
ok()    { printf "${C_GRN}[ok]${C_RST} %s\n" "$*"; }
die()   { error "$*"; exit 1; }

# ---------- 參數 ----------
AUTO_YES=0
for arg in "$@"; do
    case "$arg" in
        -y|--yes) AUTO_YES=1 ;;
        -h|--help)
            sed -n '2,30p' "$0"; exit 0 ;;
        *) die "未知參數: $arg (用 -h 看說明)" ;;
    esac
done

ask() {
    # ask <prompt> <default> <var-name>
    local prompt="$1" default="$2" var="$3" reply
    if [[ $AUTO_YES -eq 1 ]]; then
        reply="$default"
    else
        read -r -p "$prompt [$default]: " reply || reply=""
        [[ -z "$reply" ]] && reply="$default"
    fi
    printf -v "$var" "%s" "$reply"
}

ask_secret() {
    # ask_secret <prompt> <var-name>
    local prompt="$1" var="$2" reply=""
    if [[ $AUTO_YES -eq 1 ]]; then
        reply="${!var-}"
    else
        read -r -s -p "$prompt: " reply; echo
    fi
    printf -v "$var" "%s" "$reply"
}

ask_yn() {
    # ask_yn <prompt> <default Y|N>
    local prompt="$1" default="$2" reply
    if [[ $AUTO_YES -eq 1 ]]; then
        [[ "$default" == "Y" ]]; return $?
    fi
    read -r -p "$prompt [$default]: " reply || reply=""
    [[ -z "$reply" ]] && reply="$default"
    [[ "$reply" =~ ^[Yy] ]]
}

# ---------- Step 0. Sanity ----------
[[ $EUID -eq 0 ]] && die "請不要用 root 執行 (systemd --user 需要一般使用者身份)"
[[ -f app.py && -f index.html && -f schema.sql ]] \
    || die "當前目錄不是 TSC_TOOL 專案根 (找不到 app.py / index.html / schema.sql)"

echo
info "TSC TOOL 安裝腳本 — 專案位置: $SCRIPT_DIR"
echo

# ---------- Step 1. 檢查 Python & pip ----------
info "[1/8] 檢查 Python 3.6+ 和 pip3"
command -v python3 >/dev/null || die "找不到 python3。RHEL: sudo dnf install python3 python3-pip"
PY_VER=$(python3 -c 'import sys; print("{}.{}".format(*sys.version_info[:2]))')
python3 -c 'import sys; sys.exit(0 if sys.version_info>=(3,6) else 1)' \
    || die "Python 版本 $PY_VER 太舊,需要 3.6+"
command -v pip3 >/dev/null || die "找不到 pip3。RHEL: sudo dnf install python3-pip"
ok "Python $PY_VER + pip3 OK"

# ---------- Step 2. 安裝 Python 套件 ----------
info "[2/8] 安裝 Python 套件 (flask, pymysql, openpyxl)"
pip3 install --user --quiet flask pymysql openpyxl
python3 -c 'import flask, pymysql, openpyxl' \
    || die "套件安裝完但 import 失敗,檢查 ~/.local/lib/python*/site-packages"
ok "flask $(python3 -c 'import flask; print(flask.__version__)') / pymysql $(python3 -c 'import pymysql; print(pymysql.__version__)') / openpyxl $(python3 -c 'import openpyxl; print(openpyxl.__version__)')"

# ---------- Step 3. DB 服務 ----------
info "[3/8] 檢查 MariaDB / MySQL 服務"
DB_SVC=""
for svc in mariadb mysqld mysql; do
    if systemctl list-unit-files "$svc.service" >/dev/null 2>&1; then
        DB_SVC="$svc"; break
    fi
done
[[ -n "$DB_SVC" ]] || die "找不到 mariadb / mysqld 服務。請先: sudo dnf install mariadb-server && sudo systemctl enable --now mariadb"

if ! systemctl is-active --quiet "$DB_SVC"; then
    warn "$DB_SVC 沒在跑,嘗試啟動 (需要 sudo)"
    sudo systemctl start "$DB_SVC" || die "啟動 $DB_SVC 失敗"
fi
ok "$DB_SVC is active"

command -v mysql >/dev/null || die "找不到 mysql client。RHEL: sudo dnf install mariadb (client)"

# ---------- Step 4. DB 連線資訊 + 建 schema ----------
info "[4/8] 設定 DB 連線並建立 schema"
ask "DB host"       "${DB_HOST:-127.0.0.1}"  DB_HOST
ask "DB port"       "${DB_PORT:-3306}"       DB_PORT
ask "DB user"       "${DB_USER:-root}"       DB_USER
if [[ -z "${DB_PASS:-}" && $AUTO_YES -eq 0 ]]; then
    ask_secret "DB password for $DB_USER (輸入時不顯示)" DB_PASS
fi
ask "Database name" "${DB_NAME:-tsc_tool}"   DB_NAME

# 測連線
info "  測試 DB 連線..."
if ! mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASS" -e "SELECT 1" >/dev/null 2>&1; then
    die "DB 連不上。檢查 host/port/user/password"
fi
ok "  DB 連線成功"

# 執行 schema.sql (內含 CREATE DATABASE IF NOT EXISTS)
info "  執行 schema.sql"
mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASS" < schema.sql
ok "  schema 建立完成 (database=$DB_NAME)"

# ---------- Step 5. config.ini ----------
info "[5/8] 產生 config.ini (chmod 600)"
ask "Flask 監聽 port" "${APP_PORT:-9000}" APP_PORT

if [[ -f config.ini ]]; then
    if ask_yn "config.ini 已存在,要覆蓋嗎?" "N"; then
        :
    else
        warn "  保留現有 config.ini,不覆蓋"
        SKIP_CONFIG=1
    fi
fi

if [[ "${SKIP_CONFIG:-0}" -ne 1 ]]; then
    cat > config.ini <<EOF
[db]
host = $DB_HOST
port = $DB_PORT
user = $DB_USER
password = $DB_PASS
database = $DB_NAME

[server]
host = 0.0.0.0
port = $APP_PORT
EOF
    chmod 600 config.ini
    ok "  config.ini 已建立"
fi

# ---------- Step 6. 檔案權限 ----------
info "[6/8] 設定執行權限"
chmod +x serve.sh app.py generate.py 2>/dev/null || true
[[ -f install.sh ]] && chmod +x install.sh
ok "  chmod +x 完成"

# ---------- Step 7. systemd --user service ----------
info "[7/8] 設定 systemd --user service"

SVC_DIR="$HOME/.config/systemd/user"
SVC_FILE="$SVC_DIR/tsc-tool.service"
mkdir -p "$SVC_DIR"

cat > "$SVC_FILE" <<EOF
[Unit]
Description=TSC TOOL Flask Web Server
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=/usr/bin/python3 $SCRIPT_DIR/app.py
Restart=on-failure
RestartSec=5
StandardOutput=append:/tmp/tsc-tool.log
StandardError=append:/tmp/tsc-tool.log

[Install]
WantedBy=default.target
EOF
ok "  service 檔已寫入 $SVC_FILE"

# 停舊手動 process
if pgrep -f 'python3.*app\.py' >/dev/null 2>&1; then
    warn "  發現舊的 app.py process,先 kill 掉"
    pkill -f 'python3.*app\.py' || true
    sleep 1
fi

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
systemctl --user daemon-reload
systemctl --user enable tsc-tool.service >/dev/null 2>&1
systemctl --user restart tsc-tool.service

sleep 2
if systemctl --user is-active --quiet tsc-tool.service; then
    ok "  tsc-tool.service is active"
else
    warn "  tsc-tool.service 沒起來,看 log:"
    journalctl --user -u tsc-tool -n 20 --no-pager || true
    die "  service 啟動失敗"
fi

# ---------- Step 8. Linger + firewall (選) ----------
info "[8/8] 選項設定"

# Linger — 讓 user service 在你登出後仍活著
LINGER_ON=$(loginctl show-user "$USER" -p Linger --value 2>/dev/null || echo "no")
if [[ "$LINGER_ON" == "yes" ]]; then
    ok "  loginctl linger 已開 (登出後 service 會繼續跑)"
elif [[ "${ENABLE_LINGER:-0}" == "1" ]] || ask_yn "  要開 loginctl linger 嗎? (登出後 service 仍常駐,需 sudo)" "Y"; then
    if sudo loginctl enable-linger "$USER"; then
        ok "  loginctl linger 已開"
    else
        warn "  loginctl enable-linger 失敗 (可能沒 sudo 權限);登出後 service 會停"
    fi
fi

# Firewall — 開 port 給外部連
if command -v firewall-cmd >/dev/null 2>&1; then
    if sudo firewall-cmd --list-ports 2>/dev/null | grep -qw "$APP_PORT/tcp"; then
        ok "  firewalld: port $APP_PORT/tcp 已開放"
    elif [[ "${OPEN_FIREWALL:-0}" == "1" ]] || ask_yn "  要 sudo 開 firewall port $APP_PORT/tcp 讓外部連進來嗎?" "N"; then
        if sudo firewall-cmd --add-port="$APP_PORT/tcp" --permanent && sudo firewall-cmd --reload; then
            ok "  firewall port $APP_PORT/tcp 已開"
        else
            warn "  開 firewall 失敗;可用 SSH tunnel 代替: ssh -L $APP_PORT:localhost:$APP_PORT user@this-host"
        fi
    fi
fi

# ---------- 完成 ----------
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo
printf "${C_GRN}${C_BLD}✔ 安裝完成${C_RST}\n"
echo
echo "  網址:       http://${IP:-<Linux IP>}:$APP_PORT/"
echo "  健康檢查:   curl -sS http://127.0.0.1:$APP_PORT/api/health"
echo
echo "  服務管理:"
echo "    systemctl --user status tsc-tool"
echo "    systemctl --user restart tsc-tool"
echo "    journalctl --user -u tsc-tool -f"
echo
echo "  設定檔:"
echo "    config.ini              (chmod 600, 含 DB 密碼)"
echo "    ~/.config/systemd/user/tsc-tool.service"
echo
