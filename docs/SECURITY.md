# Security Policy and Design

## Supported version

Security fixes target the latest version on the default branch. There is no promise of security backports for older commits or untagged builds.

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's **Report a vulnerability** flow for `popuchoco/QHora-CLI` when private vulnerability reporting is available. If it is unavailable, contact the repository maintainer privately through GitHub. Do not include real passwords, private keys, access tokens, public WAN addresses, or unredacted client/event data in a public issue.

The project is maintained on a best-effort basis and does not currently publish a response-time SLA or bug-bounty program.

## Security objectives

- Limit the application to read-only diagnostics and published monitor status.
- Keep credentials and session tokens out of output and committed files.
- Prevent callers from supplying arbitrary shell commands, URLs, or HTTP methods.
- Verify router TLS certificates by default and pin SSH host keys.
- Bound network timeouts and response sizes.
- Preserve partial/unavailable status instead of manufacturing healthy results.

## Threat model

The program is intended to run on a trusted management host or NAS. It connects to a router and optionally a Kuma Status Page. It assumes that the host operating system, Python runtime, secret-file ACLs, DNS/network path, and configured destination addresses are controlled by the operator.

It is not a network firewall, secret manager, sandbox, router hardening system, or defense against a compromised MCP host. MCP clients may display returned network and firmware status to a model or operator; configure tools only for trusted clients.

## Credential and session handling

### QuRouter Web API

- Prefer `QROUTER_WEB_PASSWORD_FILE` with host ACLs or a secret manager. Do not commit it or place the password in MCP JSON configuration.
- HTTPS is required by default. TLS certificate verification remains enabled; configure `QROUTER_WEB_CA_FILE` for a private CA.
- The API requires Base64-encoded password data. Base64 is reversible encoding, not encryption.
- HTTP is available only after the operator sets `QROUTER_WEB_ALLOW_INSECURE_HTTP=1`. Use that only on an isolated trusted management LAN; credentials travel in clear text.
- Login always requests `force=false`. The collector will not evict another management session.
- The access token exists only for one collection, is not returned, and is cleared after a logout attempt.
- Redirects are rejected. Calls use a static endpoint allowlist, request timeout, and 1 MiB response cap.
- Overview output is projected through an explicit field allowlist and omits site and WAN identity fields. The client-list and event-log endpoints are not called.

### SSH

- SSH password authentication is not implemented. Use a dedicated key and a pinned `known_hosts` file.
- `StrictHostKeyChecking=yes`, `BatchMode=yes`, an explicit identity file, fixed command mapping, per-command timeout, and a 256 KiB stdout cap are used.
- The router account is non-root. Do not assume access to firewall rules, sudo, or writable firmware partitions.
- Never enable arbitrary command strings or disable host-key verification to work around connection errors.

### Uptime Kuma

- Only the configured public Status Page and heartbeat APIs are used; Kuma admin credentials are not needed.
- Status Page monitor names and health states may be public. Do not publish sensitive hostnames, internal identifiers, or secrets on the page.
- A third-party API monitor reports availability only. Do not put API credentials or response bodies in a public monitor name, keyword, or status page.
- The collector uses a bounded response size, request timeout, process-local TTL cache, and stale age limit.

## Data returned

The program can return firmware version, CPU/memory summary, uptime, interface names/states, Wi-Fi metadata, filesystem summaries, selected port/WAN fields, and monitor names/status/ping. SSH address/route/neighbor sections can include private network addresses and MAC addresses. Treat MCP output and logs as operational data; share only with trusted recipients.

QuRouter firmware errors are returned as bounded error text and numeric codes, not as full raw HTTP response bodies. Passwords, bearer tokens, and private keys must not be logged or included in diagnostics.

## Operational guidance

1. Run on a trusted host and restrict who can invoke the MCP tools.
2. Create a least-privilege QuRouter account and dedicated SSH account/key where supported.
3. Use HTTPS with a verified certificate; avoid the explicit HTTP opt-in unless the network is isolated and trusted.
4. Protect secret files with OS permissions; rotate credentials if they appear in logs or public repositories.
5. Keep the Kuma page limited to information intended for its audience.
6. Review endpoint behavior after QuRouter/Kuma firmware upgrades; endpoint compatibility is not guaranteed across versions.

## Scope and limitations

The project does not configure router ACLs, rotate credentials, protect the MCP host, create or edit Kuma monitors, or provide write-capable router controls. The current tested QuRouter firmware returns HTTP 519/API `-2` for Ports and WAN sections; this is reported as unavailable. A read-only label does not remove the risk of exposing network metadata or sending credentials over an unencrypted transport.
