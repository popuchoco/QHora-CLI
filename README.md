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
       ├─ qhora_read_status → SSH 固定唯讀命令 → QHora-301W
       ├─ kuma_status       → Uptime Kuma Status Page API
       └─ kuma_probe        → 由 Kuma monitor 顯示外部服務可用性
```

MCP tool 應提供語意明確的動作，例如 `qhora_read_status`、`kuma_status_page`、`kuma_monitor_status`。不要提供 `run_shell(command)`、任意 URL fetch 或通用 HTTP proxy。使用者可透過 MCP Host 的操作權限決定是否允許呼叫工具，Server 端再以固定 allowlist 限制實際能力。

SSH 使用專用帳號與 key。Known hosts 必須釘選並驗證設備 host key。每次收集加總逾時、限制輸出大小，將解析後摘要回傳 MCP，避免暴露完整命令輸出、區網 client 清單或憑證。現有 `admin/admin123` 僅為實驗帳密，不要寫入設定檔、環境範例或 MCP tool 結果。部署時先在 QuRouter 建立具最低權限的帳號，確認允許 public key 登入，並輪替實驗密碼。

## Uptime Kuma 與第三方 API

### 可行：監測第三方 API

Uptime Kuma 的 HTTP(s) monitor 可以對第三方 API endpoint 發送請求，依 HTTP 狀態碼、關鍵字或回應時間判斷可用性。MCP Server 讀取已發布 Status Page 的唯讀資料即可呈現這些 monitor 結果，避免自己重複 probe。可將名稱固定為 `QHora Ping`、`QuRouter Web`、`AdGuard DNS`、`NAS Web`、`Third-party API` 等。

可讀的 Status Page endpoint 常見為 `GET /api/status-page/{slug}` 與 `GET /api/status-page/heartbeat/{slug}`。需以實際安裝的 Kuma 版本驗證，因相關 API 文件標註屬於內部介面，可能隨版本改變。公開 Status Page 不應含敏感資訊。

### 不適合：拿 Kuma 當第三方 API 的通用代理

一般 HTTP monitor 主要用於探測與狀態呈現，不能作為 MCP 即時任意查詢外部 API 的穩定通用代理，也不應透過未文件化的 Kuma 管理 Socket.IO API 轉發任意動作。若需求是讀取外部 API 的結構化資料，MCP Server 應直接呼叫該服務的窄化、唯讀 endpoint，使用各自的 secret，設定允許的 hostname、method、path、timeout、response cap 與 cache。

若第三方系統提供 webhook，可由第三方直接送到 Uptime Kuma Push Monitor URL，以回報 heartbeat。Push token 是寫入型憑證，需視為 secret，不要回傳給模型或 UI。此方法適合上報可用性，不適合查詢詳細資料。

## MCP tool 建議契約

| Tool | 後端 | 輸入 | 回傳 |
|---|---|---|---|
| `qhora_read_status` | SSH 固定命令 allowlist | 無 | uptime、load、memory、interface、Wi-Fi channel、listener count、filesystem、limitations、observed_at |
| `kuma_status_page` | Kuma Status Page API | 固定 slug | 群組、monitor 名稱與狀態 |
| `kuma_monitor_status` | 同一份 heartbeat snapshot | 固定 allowlisted monitor name | UP/DOWN/pending、延遲、檢查時間 |
| `third_party_api_status` | 建議直接讀第三方唯讀 API | enum 型 service key | 正規化摘要、來源時間、資料年齡 |

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
        "QHORA_HOST": "192.168.100.1",
        "QHORA_PORT": "22200",
        "QHORA_USER": "monitor",
        "QHORA_KEY_FILE": "C:/path/to/qhora_ed25519",
        "QHORA_KNOWN_HOSTS": "C:/path/to/known_hosts",
        "KUMA_BASE_URL": "http://uptime-kuma:3001",
        "KUMA_STATUS_SLUG": "home-network"
      }
    }
  }
}
```

已提供唯讀 CLI 與 stdio MCP Server。CLI 支援 `qurouter router status|interfaces|addresses|routes|neighbors|wifi|listeners|filesystems` 和 `qurouter kuma status`。MCP tools 為 `qrouter_router_status`、`qrouter_router_read`、`qrouter_kuma_status`。SSH 只接受 pinned known_hosts 與 key，不接受密碼。部署前仍需用專用帳號及實際 Kuma 版本確認上游。

## 參考

- [MCP 官方 Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Uptime Kuma internal API 說明](https://github.com/louislam/uptime-kuma-wiki/wiki/Internal-API)
- [Uptime Kuma Status Page API 說明](https://github.com/louislam/uptime-kuma/wiki/API-Documentation)
