# QHora-CLI

[English](README.en.md)

QHora-CLI 是供 QHora-301W 使用的唯讀 CLI 與 stdio MCP Server。它把 QuRouter Web API、固定 SSH 診斷命令與 Uptime Kuma 公開 Status Page 整合到同一組指令與 MCP tools。程式應執行在可信任的管理主機或 NAS；不安裝到路由器韌體中。

## 功能與限制

| 來源 | 功能 | 條件與目前限制 |
|---|---|---|
| QuRouter Web API | Overview、韌體、CPU、記憶體、運作時間；Ports 與 WAN 區塊逐項回報 | 登入後讀固定 endpoint，再登出。已測試韌體 2.7.2.121 的 Ports/WAN API 回 HTTP 519、`-2`，故會顯示 unavailable，不會猜測資料 |
| SSH | uptime、記憶體、介面、IP、路由、鄰居、Wi-Fi、listener、檔案系統與 mounts 摘要 | 需 OpenSSH client、key 與 pinned `known_hosts`。`admin` 無權讀取 iptables |
| Uptime Kuma | 公開 Status Page 的 monitor 分組、狀態、延遲與檢查時間 | 不需 Kuma 管理帳密或 SSH；只讀取已發布頁面，不建立或修改 monitors |
| 第三方 API 狀態 | 讀取 Kuma 中以 HTTP monitor 設定的第三方 API 可用狀態 | Kuma monitor 是健康探測，不是即時任意 API proxy；詳細資料須由專用唯讀整合直接讀取 |

程式不提供任意 shell、任意 URL fetch、路由器設定修改、重開機或 Kuma 管理操作。QuRouter Web API 登入使用 `force=false`，不會取代現有管理工作階段。

## 快速開始

需求：Python 3.11 以上。執行 CLI/MCP 核心程式不需要第三方 Python runtime 套件；SSH 模式另需系統 OpenSSH client。

```powershell
cd E:\QHora-CLI
python -m qrouter_cli.cli --help
```

安裝命令列入口（選用）：

```powershell
python -m pip install -e .
qurouter --help
```

### 只用 Web API：不裝 Kuma、不啟用 SSH

這是最少依賴的使用方式。只需路由器 Web API 帳號與密碼檔；不必設定 `KUMA_*` 或 `QROUTER_HOST`／SSH key。

```powershell
$env:QROUTER_WEB_BASE_URL = "https://192.168.100.1/miro/api"
$env:QROUTER_WEB_USERNAME = "monitor"
$env:QROUTER_WEB_PASSWORD_FILE = "C:\secrets\qhora_web_password"
$env:QROUTER_WEB_CA_FILE = "C:\secrets\qhora_ca.pem"
python -m qrouter_cli.cli router web-status
```

輸出會逐項顯示 API 區塊狀態。來源成功但某些韌體 endpoint 失敗時，整體狀態會是 `partial`。MCP 對應工具為 `qrouter_web_status`。

### 讀取 Uptime Kuma

Kuma 必須啟用並發布 Status Page。此 collector 不需要 Kuma 管理帳密，也不依賴 SSH。

```powershell
$env:KUMA_BASE_URL = "http://uptime-kuma:3001"
$env:KUMA_STATUS_SLUG = "home-network"
python -m qrouter_cli.cli kuma status
python -m qrouter_cli.cli kuma monitor --name "QuRouter Web"
```

預設快取 15 秒；上游失敗時，在 stale 上限內回傳最近成功資料並標示 `stale`。可用 `KUMA_CACHE_TTL`（1–300 秒）及 `KUMA_STALE_MAX_AGE`（1–3600 秒）調整。

### SSH 診斷

SSH 只接受系統 OpenSSH client 的 key authentication 與 pinned host key。請先建立最低權限帳號、可信任的 `known_hosts` 與專用私鑰。

```powershell
$env:QROUTER_HOST = "192.168.100.1"
$env:QROUTER_PORT = "22200"
$env:QROUTER_USER = "monitor"
$env:QROUTER_KEY_FILE = "C:\secrets\qhora_ed25519"
$env:QROUTER_KNOWN_HOSTS = "C:\secrets\known_hosts"
python -m qrouter_cli.cli router status
python -m qrouter_cli.cli router interfaces
python -m qrouter_cli.cli router wifi
```

完整子命令可用 `python -m qrouter_cli.cli router --help` 檢視。指令固定在程式 allowlist 中；呼叫端不能傳任意遠端命令。

## CLI 指令

```text
qurouter router web-status
qurouter router integrated-status
qurouter router status
qurouter router interfaces|addresses|routes|neighbors|wifi|listeners|filesystems
qurouter kuma status
qurouter kuma monitor --name "QuRouter Web"
```

`router integrated-status` 將 QuRouter Web API 與 Kuma 的 `QuRouter Web` heartbeat 合併；若沒有設定 Kuma，請用 `router web-status`。`router status` 和 `router <section>` 使用 SSH。

## MCP Server

Server 使用 stdio JSON-RPC，提供下列唯讀 tools：

| Tool | 依賴 | 用途 |
|---|---|---|
| `qrouter_web_status` | QuRouter Web 帳密 | 直接讀路由器 Overview／Ports／WAN API |
| `qrouter_integrated_status` | QuRouter Web 帳密 + Kuma Status Page | 交叉檢查 Web API 與 `QuRouter Web` heartbeat |
| `qrouter_router_status` | SSH key + pinned host key | 收集固定命令的系統摘要 |
| `qrouter_router_read` | SSH key + pinned host key | 讀取 allowlist 中的單一診斷區塊 |
| `qrouter_kuma_status` | Kuma Status Page | 列出 monitor 狀態 |
| `qrouter_kuma_monitor` | Kuma Status Page | 依完全相符的名稱篩選 monitor |

無 Kuma、無 SSH 的 MCP Host 範例：

```json
{
  "mcpServers": {
    "qhora-web-only": {
      "command": "uv",
      "args": ["run", "--directory", "E:/QHora-CLI", "python", "-m", "qrouter_cli.mcp_server"],
      "env": {
        "QROUTER_WEB_BASE_URL": "https://192.168.100.1/miro/api",
        "QROUTER_WEB_USERNAME": "monitor",
        "QROUTER_WEB_PASSWORD_FILE": "C:/secrets/qhora_web_password",
        "QROUTER_WEB_CA_FILE": "C:/secrets/qhora_ca.pem"
      }
    }
  }
}
```

完整設定請只提供實際啟用的來源。不要把密碼、API token 或私鑰直接寫進 MCP 設定檔。

## 安全與傳輸

QuRouter API 將密碼以 Base64 放入登入請求；Base64 不是加密。程式預設拒絕 HTTP，HTTPS 會驗證憑證，可用 `QROUTER_WEB_CA_FILE` 指定私有 CA。只有在可信任且隔離的管理 LAN 上，才以 `QROUTER_WEB_ALLOW_INSECURE_HTTP=1` 明確允許 HTTP；這會讓密碼以明文傳送。此設備 HTTPS 憑證若未受主機信任，請先部署／信任正確 CA，不要關閉驗證。

`QROUTER_WEB_BASE_URL` 必須明確設定，程式不會套用任何 HTTP 預設網址。請優先用 `QROUTER_WEB_PASSWORD_FILE` 搭配作業系統 ACL 或 secret manager；避免設定 `QROUTER_WEB_PASSWORD`，因為環境變數可能被同機具權限的程序檢視。可設定 `QROUTER_LOG_LEVEL=INFO`（或 `DEBUG`、`WARNING`、`ERROR`）啟用 stderr JSON 日誌；預設關閉。記錄固定包含 `timestamp`、`level`、`event`，可選欄位僅有 `component`、`operation`、`source`、`status`、`error_type`、`error_code`、`http_status`、`duration_ms`；MCP 成功耗時只在 DEBUG 級別記錄。整合狀態預設查找 Kuma monitor `QuRouter Web`，可用 `QROUTER_KUMA_MONITOR_NAME` 覆寫。SSH 原始解析診斷預設關閉；設 `QROUTER_INCLUDE_RAW_ON_PARSE_ERROR=1` 才會回傳最多 10 行、每行 200 字元的片段，其中可能含 SSID、IP 或 MAC。

細節見 [Security Policy](SECURITY.md) 與 [docs/SECURITY.md](docs/SECURITY.md)。

## 文件

- [產品架構](docs/PRODUCT_ARCHITECTURE.md)
- [Software Design（SD）](docs/SD.md)
- [安全性設計](docs/SECURITY.md)
- [English README](README.en.md)

## 開發與驗證

```powershell
python -m unittest discover -v
python -m compileall -q qrouter_cli tests
```

可用 `python -m qrouter_cli.mcp_server` 啟動 MCP stdio server。CLI/MCP 不會修改路由器或 Kuma 設定；登入與登出會建立並清除短期 Web API session。

## License

本專案採用 MIT License，詳見 [LICENSE](LICENSE)。
