# 網站開不起來排錯紀錄

**環境:** Linux VM (VirtualBox) 上跑 `python3 -m http.server 9000`,從 Windows 瀏覽器連 `192.168.56.20:9000` 開不起來。

**結論:** firewalld 擋掉 9000 port。要嘛用 SSH tunnel 繞過,要嘛開防火牆。

---

## 症狀

```
[mcsadmin@localhost dispatch_generator]$ ./serve.sh 9000
Open: http://192.168.56.20:9000/index.html
Serving HTTP on 0.0.0.0 port 9000 (http://0.0.0.0:9000/) ...
```

Windows 瀏覽器打 `http://192.168.56.20:9000/index.html` → 無法連線。

---

## 兩個坑,依序踩

### 坑 1:`./serve.sh` 是前景執行,切走就死

`serve.sh` 內容就是 `python3 -m http.server`,在前景跑。只要:
- 關掉 terminal
- 切到別的 tab
- 按 Ctrl-C
- SSH 斷線

...這 process 就掛了。掛了之後再連 9000 一定 refused。

**檢查方式:**
```bash
ss -tln | grep :9000                                # 有沒有在 listen
pgrep -af http.server                               # 有沒有 process
curl -sI http://127.0.0.1:9000/index.html | head -1 # 本機打得通嗎
```

**解法:改用 `nohup` 背景執行**
```bash
cd /home/mcsadmin/dispatch_generator
nohup python3 -m http.server 9000 > /tmp/dispatch_server.log 2>&1 &
disown
```

**要停:**
```bash
pkill -f 'http.server 9000'
```

### 坑 2:server 起著但外部連不到 → firewalld 擋 9000

Server 本機驗證 OK (curl 127.0.0.1:9000 拿到 200)、`ss -tln` 也看得到 `0.0.0.0:9000` LISTEN,但 Windows 就是連不到。

**Windows 側驗證:**
```powershell
Test-NetConnection 192.168.56.20 -Port 22    # SSH → TcpTestSucceeded : True
Test-NetConnection 192.168.56.20 -Port 9000  # → TcpTestSucceeded : False
```
Ping 通、22 通、9000 不通 → 就是防火牆規則問題,不是路由/網卡問題。

**兩個解法:**

#### 解法 A:SSH tunnel (推薦,不改系統設定)

在 Windows 開新的 PowerShell / Terminal:
```powershell
ssh -L 9000:localhost:9000 mcsadmin@192.168.56.20
```
輸入密碼登入後**保持這個視窗開著**。然後 Windows 瀏覽器打:
```
http://localhost:9000/index.html
```
(注意是 Windows 自己的 `localhost`,不是 Linux 的 IP)

**原理:**
```
Windows 瀏覽器 → localhost:9000 (Windows 端 SSH client)
       │
       │ SSH 加密隧道走 port 22 進 Linux ← firewalld 只認 22
       ▼
Linux sshd → 127.0.0.1:9000 (Linux 內部連 http.server,不經防火牆)
```

其他 SSH client 的 tunnel 設定:
- **PuTTY:** Connection → SSH → Tunnels → Source port `9000`, Destination `localhost:9000`, Local → Add,重新連線
- **MobaXterm:** Tools → MobaSSHTunnel → New tunnel → Local port `9000`, Remote server `localhost` port `9000`
- **Xshell:** Session Properties → SSH → Tunneling → Add → Type=Local, Source port `9000`, Destination `localhost:9000`

#### 解法 B:開防火牆 (要 sudo 密碼,適合多人共用)

回 Linux session:
```bash
sudo firewall-cmd --add-port=9000/tcp --permanent
sudo firewall-cmd --reload
sudo firewall-cmd --list-ports        # 驗證有 9000/tcp
```

之後 Windows 瀏覽器可以直接 `http://192.168.56.20:9000/index.html`。

---

## 排除掉的假嫌疑犯:SELinux

一開始懷疑 SELinux Enforcing + `http_port_t` 只允許 80/443/488/5988/8008 會擋 python http.server。

**其實不會。** SELinux 的 `http_port_t` 規則只約束 **httpd/nginx 等 system daemon** (跑在 confined domain 例如 `httpd_t`)。使用者手動跑的 `python3 -m http.server` 是在 `unconfined_t` domain,SELinux 對這種 unconfined 使用者不限制綁 port。

**驗證方式:** 如果 SELinux 有擋,`/var/log/audit/audit.log` 會有 AVC denial;如果 curl 從本機 (`127.0.0.1:9000`) 就打得通,那 SELinux 一定沒擋。

---

## VirtualBox 網卡 IP 對應

這台 VM 有 3 個網段,搞清楚哪個從哪連得到:

| 網卡 | IP | 用途 | 誰能連到 |
|---|---|---|---|
| `enp0s3` | `192.168.56.20/24` | VBox host-only | 只有 VBox 宿主機 (Windows) |
| `enp0s9` | `10.0.4.15/24` | VBox NAT | 外部連不進來 |
| `virbr0` | `192.168.122.1/24` | libvirt bridge (給這台 VM 內部起的 KVM 用) | 忽略 |

同事電腦要連 → 沒辦法,除非改成 Bridged Adapter 或設 VBox port forwarding。

---

## 一鍵診斷指令 (下次先跑這串)

```bash
# 1. server 有沒有起
ss -tln | grep :9000
pgrep -af http.server

# 2. 本機打得通嗎 (排除 server 本身問題)
curl -sI http://127.0.0.1:9000/index.html | head -1

# 3. Windows 側:防火牆有沒有擋
# 在 Windows PowerShell:
# Test-NetConnection 192.168.56.20 -Port 9000

# 4. Server 沒起 → 重啟
cd /home/mcsadmin/dispatch_generator
nohup python3 -m http.server 9000 > /tmp/dispatch_server.log 2>&1 &
disown

# 5. Server 有起但 Windows 連不到 → 用 SSH tunnel
# 在 Windows 另開視窗:
# ssh -L 9000:localhost:9000 mcsadmin@192.168.56.20
# 瀏覽器打 http://localhost:9000/index.html
```
