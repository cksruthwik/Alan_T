# Integration — Tailscale

Milestone: **M2** (remote access, with Telegram) — but recommended from day one for any non-localhost use
Role: the entire remote-access story. No reverse proxy, no port forwarding, no public TLS — by design.

## Model

Tailscale (WireGuard mesh) runs on the **host**, not in a container. The API binds `127.0.0.1` plus the `tailscale0` interface ([INFRASTRUCTURE.md](../infra/INFRASTRUCTURE.md) §5). Result: Alan_T is reachable from exactly the user's own authorized devices, encrypted end-to-end, with zero public attack surface.

```
phone (tailnet) ──wireguard──▶ host:tailscale0 ──▶ api:8000
laptop (tailnet) ──────────────────────┘
internet ──▶ nothing listening. there is no door.
```

## Setup

1. `tailscale up` on host; authorize device in the admin console.
2. Install Tailscale on phone/laptop; same tailnet.
3. API base URL on remote devices: `http://<host-tailnet-name>:8000` (MagicDNS). Bearer token still required — Tailscale authenticates the *device*, the token authenticates the *request*; two layers, kept ([API_SPECIFICATION.md](../api/API_SPECIFICATION.md) §1).

Optional hardening (recommended as the tailnet grows beyond two devices):
- Tailscale ACLs restricting which tailnet devices may reach port 8000 at all.
- `tailscale serve` for HTTPS with tailnet-internal certs if a browser UI complains about http.

## What Tailscale Is NOT Used For

- Not a substitute for the API token (defense in depth).
- Not for exposing Postgres — it stays compose-internal, not even on tailscale0. Remote debugging of the database goes through `tailscale ssh` to the host, deliberately manual.
- Not Funnel (public exposure) — Funnel is the one Tailscale feature that must never be enabled on this node; it would invert the entire security posture ([SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md)). Worth a comment in the deploy checklist.

## Relationship to Telegram

Telegram (long-poll, outbound-only) works without Tailscale — they are independent remote channels. Tailscale carries the full API/UI experience; Telegram carries the lightweight conversational one. M2 delivers both; losing either leaves a working remote path.

## Failure Posture

Tailscale outage → remote API access lost, local + Telegram unaffected, nothing to do in Alan_T (it's host infrastructure). Health visibility: `tailscale status` is checked by the deploy checklist, not monitored by Alan_T itself — the assistant doesn't manage its own network layer.
