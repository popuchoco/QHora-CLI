# QuRouter-CLI and MCP integration

本專案用來規劃 QHora-301W 的本機管理整合。MCP Server 建議跑在 NAS 或可信任的管理主機，路由器只接受它發起的 SSH/API 查詢。不要把 MCP Server 安裝到 QHora 韌體內。

## 已知設備能力

目前已從 QHora-301W 的 SSH shell 實測到 Linux 4.4.60、Buildroot、BusyBox 1.27.2，以及一般 `admin` 使用者。以下查詢可用：

| 用途 | 固定命令 | 權限情況 |
|---|---|---|
| 系統負載 | `uptime` | 可讀 |
| 記憶體 | `free` | 可讀 |
| 介面狀態 | `/sbin/ip -br link` | 可讀，需補 `/sbin` 到 PATH 或用絕對路徑 |
| Wi-Fi 狀態 | `/usr/bin/iw dev` | 可讀 |
| 監聽 socket | `/sbin/ss -H -lntu` | 可讀 |
| 磁碟空間 | `/bin/df -kP` | 可讀 |
| 掛載選項 | `/usr/bin/findmnt -n -o TARGET,FSTYPE,OPTIONS` | 可讀 |
| 防火牆規則 | `/sbin/iptables -S` | admin 權限不足，拒絕讀取 |

SSH shell 的 PATH 預設不含 `/sbin`。`admin` 不是 root，collector 不應依賴 sudo、iptables 或可寫系統分區。`/usr` 是唯讀 SquashFS，且當時 `/tmp` 空間用盡，所以不建議在路由器上安裝常駐 MCP daemon。

## 建議架構

```text
MCP Host
  └─ stdio MCP Server（NAS/管理主機）
       ├─ qrouter_web_status        → QuRouter 固定唯讀 HTTP API
       ├─ qrouter_router_status     → SSH 固定唯讀命令 → QHora-301W
       ├─ qrouter_kuma_status       → Uptime Kuma Status Page API
       └─ qrouter_integrated_status → QuRouter Web API + Kuma monitor 交叉檢查
```

MCP tool 應提供語意明確的動作，例如 `qhora_read_status`、`kuma_status_page`、`kuma_monitor_status`。不要提供 `run_shell(command)`、任意 URL fetch 或通用 HTTP proxy。使用者可透過 MCP Host 的操作權限決定是否允許呼叫工具，Server 端再以固定 allowlist 限制實際能力。

SSH 使用專用帳號與 key。Known hosts 必須釘選並驗證設備 host key。每次收集加總逾時、限制輸出大小，將解析後摘要回傳 MCP，避免暴露完整命令輸出、區網 client 清單或憑證。先前提供的路由器實驗帳密不要寫入設定檔、環境範例或 MCP tool 結果；部署時先在 QuRouter 建立具最低權限的帳號，確認允許 public key 登入，並輪替實驗密碼。

## Uptime Kuma 與第三方 API

### 可行：監測第三方 API

Uptime Kuma 的 HTTP(s) monitor 可以對第三方 API endpoint 發送請求，依 HTTP 狀態碼、關鍵字或回應時間判斷可用性。MCP Server 讀取已發布 Status Page 的唯讀資料即可呈現這些 monitor 結果，避免自己重複 probe。可將名稱固定為 `QHora Ping`、`QuRouter Web`、`AdGuard DNS`、`NAS Web`、`Third-party API` 等。

可讀的 Status Page endpoint 常見為 `GET /api/status-page/{slug}` 與 `GET /api/status-page/heartbeat/{slug}`。需以實際安裝的 Kuma 版本驗證，因相關 API 文件標註屬於內部介面，可能隨版本改變。公開 Status Page 不應含敏感資訊。

### 不適合：拿 Kuma 當第三方 API 的通用代理

一般 HTTP monitor 主要用於探測與狀態呈現，不能作為 MCP 即時任意查詢外部 API 的穩定通用代理，也不應透過未文件化的 Kuma 管理 Socket.IO API 轉發任意動作。若需求是讀取外部 API 的結構化資料，MCP Server 應直接呼叫該服務的窄化、唯讀 endpoint，使用各自的 secret，設定允許的 hostname、method、path、timeout、response cap 與 cache。

若第三方系統提供 webhook，可由第三方直接送到 Uptime Kuma Push Monitor URL，以回報 heartbeat。Push token 是寫入型憑證，需視為 secret，不要回傳給模型或 UI。此方法適合上報可用性，不適合查詢詳細資料。

## QuRouter Web API

CLI/MCP 使用固定 endpoint，不提供通用 URL 或任意 HTTP tool：

| 動作 | Endpoint | 實測狀態 |
|---|---|---|
| 登入 | `POST /v1/login` | 可用；`force=false`，不搶現有管理工作階段 |
| Overview | `GET /v1/debugmode/information` | 可讀韌體、CPU、記憶體、運作時間摘要 |
| Ports | `GET /v2/network/ports_status` | 目前韌體回 HTTP 519／API `-2` |
| WAN | `GET /v2/network/wan/status` | 目前韌體回 HTTP 519／API `-2` |
| 登出 | `POST /v1/logout` | 查詢結束後清除短期 token |

API 密碼以 Base64 編碼傳送，Base64 不是加密；程式因此要求 HTTPS，或由操作者明確以 `QROUTER_WEB_ALLOW_INSECURE_HTTP=1` 接受可信任隔離 LAN 上的明文風險。TLS 預設驗證憑證，可用 `QROUTER_WEB_CA_FILE` 指定私有 CA。

## MCP tool 建議契約

| Tool | 後端 | 輸入 | 回傳 |
|---|---|---|---|
| `qrouter_web_status` | QuRouter Web API | 無 | Overview、port、WAN 各自成功或失敗狀態 |
| `qrouter_router_status` | SSH 固定命令 allowlist | 無 | uptime、memory、interface、Wi-Fi、listeners、filesystem |
| `qrouter_kuma_status` | Kuma Status Page API | 設定好的 slug | 群組、monitor 名稱、UP/DOWN、延遲、檢查時間 |
| `qrouter_kuma_monitor` | 同一份快取 heartbeat | exact monitor name | 單一 monitor 的可用性與延遲 |
| `qrouter_integrated_status` | QuRouter Web API + Kuma | 無 | 直接 API 摘要及 `QuRouter Web` heartbeat 交叉檢查 |

每個來源有獨立 timeout、TTL、錯誤狀態和 last-known-good snapshot。錯誤時回傳 `unavailable` 或 `stale`，不能用空資料冒充健康。MCP 透過 stdio 給本機 host 使用即可。只有必須遠端共用時才開 Streamable HTTP，並配置 TLS、認證與網路 ACL。

## MCP host 設定草案

以下是概念設定。先完成 MCP Server 實作並安裝依賴後再啟用，不要把 SSH 密碼放在此檔。

```json
{
  "mcpServers": {
    "qhora-301w": {
      "command": "uv",
      "args": ["run", "--directory", "E:/QHora-CLI", "python", "-m", "qrouter_cli.mcp_server"],
      "env": {
        "QROUTER_HOST": "192.168.100.1",
        "QROUTER_PORT": "22200",
        "QROUTER_USER": "monitor",
        "QROUTER_KEY_FILE": "C:/path/to/qhora_ed25519",
        "QROUTER_KNOWN_HOSTS": "C:/path/to/known_hosts",
        "QROUTER_WEB_BASE_URL": "https://192.168.100.1/miro/api",
        "QROUTER_WEB_USERNAME": "monitor",
        "QROUTER_WEB_PASSWORD_FILE": "C:/path/to/qhora_web_password",
        "QROUTER_WEB_CA_FILE": "C:/path/to/qhora_ca.pem",
        "KUMA_BASE_URL": "http://uptime-kuma:3001",
        "KUMA_STATUS_SLUG": "home-network"
      }
    }
  }
}
```

已提供唯讀 CLI 與 stdio MCP Server。CLI 支援：

```text
qurouter router web-status
qurouter router integrated-status
qurouter router status|interfaces|addresses|routes|neighbors|wifi|listeners|filesystems
qurouter kuma status
qurouter kuma monitor --name "QuRouter Web"
```

MCP tools 包含 `qrouter_web_status`、`qrouter_integrated_status`、`qrouter_router_status`、`qrouter_router_read`、`qrouter_kuma_status` 與 `qrouter_kuma_monitor`。QuRouter HTTP API 使用登入後短期 Bearer token；永遠送 `force=false`，遇到既有管理工作階段就停止，不會踢除目前登入者。HTTP 明文傳送密碼預設禁止；只有在隔離的可信任 LAN 才以 `QROUTER_WEB_ALLOW_INSECURE_HTTP=1` 明確啟用，優先使用 HTTPS 和受信任 CA。密碼可從 secret file 讀取，不寫入 MCP 回應。

Uptime Kuma 只讀取已發布的 status page 與 heartbeat。把第三方 HTTP API 設成 Kuma 的 HTTP monitor 後，MCP 可依 monitor 名稱讀取它的可用狀態；Kuma 不是第三方 API 通用 proxy，MCP 不會替使用者新增或修改 monitors。

實機唯讀驗證：目前 QHora-301W 的 `overview` API 可回傳韌體與系統摘要；`ports_status` 與 `wan/status` 在此韌體回傳 HTTP 519、API error `-2`（QSH JSON unmarshal failure），工具會標示個別區塊 `unavailable`，不會偽造資料。設定的 Kuma status page 五個 monitors 均能讀取 heartbeat，`QuRouter Web` 顯示 UP。API 支援度依 QuRouter 韌體而異。

## 參考

- [MCP 官方 Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Uptime Kuma internal API 說明](https://github.com/louislam/uptime-kuma-wiki/wiki/Internal-API)
- [Uptime Kuma Status Page API 說明](https://github.com/louislam/uptime-kuma/wiki/API-Documentation)
