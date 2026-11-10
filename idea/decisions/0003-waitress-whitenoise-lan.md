# ADR-0003: Waitress and WhiteNoise for LAN serving over plain HTTP

- **Status:** Proposed (2026-11-10)
- **Related:** plan.md §5, §12.2, §18, §19 · KT-005, KT-903

## Context

The host is usually a Windows laptop. Phones on the same network must reach it by IP. There's no internet, no domain name and no certificate authority. The development server (`runserver`) isn't meant for this, and Gunicorn doesn't run on Windows.

## Decision

- A `manage.py serve` command runs **Waitress** (a pure-Python, threaded WSGI server) on `0.0.0.0:<port>` with about 16 threads.
- **WhiteNoise** serves compressed, hashed static files with far-future cache headers. Media files (question images) are served by a small Django view with caching headers in LAN mode.
- **LAN discovery** with `ifaddr` prefers private IPv4 addresses and skips loopback, link-local and virtual adapters. The command prints every candidate URL and a **terminal QR code** (segno).
- **ALLOWED_HOSTS** is computed from the discovered IPs plus `localhost` and configured names. `KT_ALLOWED_HOSTS` overrides it.
- **Plain HTTP.** No TLS on the LAN. The app avoids browser APIs that require a secure context.

## Consequences

- **Easier:** one command and one process, with no nginx and nothing to install beyond Python packages. It behaves the same on Windows, Linux and macOS.
- **Harder:** no Service Workers or Clipboard API, so fallbacks are needed. Traffic on the LAN isn't encrypted, which is accepted for a classroom network and documented. The Windows firewall rule and the Private network profile must be explained to users (KT-009, KT-902).
- **Risk:** if the host's IP changes while it's running (a DHCP renewal), the share URL changes. A restart re-detects it, and the share screen always shows the current URL.

## Alternatives considered

- **Gunicorn or uWSGI:** don't run on Windows.
- **Uvicorn (ASGI):** works, but the app has no async needs, and Waitress is simpler for WSGI.
- **nginx in front:** extra install and configuration for no real gain at this scale.
- **Self-signed HTTPS:** certificate warnings on every student's phone would be worse than plain HTTP on a closed network.
