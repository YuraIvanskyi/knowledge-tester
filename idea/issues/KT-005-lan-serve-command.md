---
id: KT-005
title: Add LAN serve command (Waitress, WhiteNoise, IP discovery, terminal QR)
phase: 0
type: feature
status: ready
priority: must
size: M
depends_on: [KT-002, KT-004]
created: 2026-11-10
updated: 2026-11-10
---

# KT-005: Add LAN serve command (Waitress, WhiteNoise, IP discovery, terminal QR)

## Context
Phones on the same network must reach the host without internet. See [ADR-0003](../decisions/0003-waitress-whitenoise-lan.md), [plan.md §12.2](../plan.md#122-links-and-qr-codes) and [plan.md §19](../plan.md#19-operations).

## Scope
- `manage.py serve [--host 0.0.0.0] [--port 8000] [--threads 16]`, which:
  - runs Waitress with `config.settings.lan`
  - runs `collectstatic` automatically if the manifest is missing or stale
- WhiteNoise with compressed, hashed storage and far-future cache headers.
- `core.network`: interface discovery through `ifaddr`, which:
  - prefers private IPv4 addresses
  - skips loopback, link-local `169.254.x.x` and virtual adapters (names matching vEthernet, Hyper-V, WSL, VirtualBox, VMware, Docker)
  - ranks the results
- On startup, print every candidate URL plus a **terminal QR code** (segno) for the best one, and the data folder path.
- ALLOWED_HOSTS computed from the discovered IPs plus `localhost`, `127.0.0.1` and `KT_ALLOWED_HOSTS`.
- On Windows, print the one-time firewall command when the port isn't reachable, or always as a hint:
  `New-NetFirewallRule -DisplayName "Knowledge Tester" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private`
- A media-serving view for LAN mode (WhiteNoise doesn't serve media). `/healthz` returns 200 with the version.

## Acceptance criteria
- [ ] Manual check: a phone on the same Wi-Fi scans the terminal QR code and opens the login page
- [ ] Static files are served gzipped, with immutable cache headers
- [ ] A request with an unknown `Host` header gets a 400
- [ ] Unit tests cover interface filtering and ranking with mocked adapters
- [ ] Ctrl+C shuts the server down cleanly

## Log
- 2026-11-10: created from the plan.
