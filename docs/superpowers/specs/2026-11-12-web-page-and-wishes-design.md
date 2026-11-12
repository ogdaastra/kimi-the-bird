# Web page and "ask the human" (wishes) — design

## Intent

Kimi runs on the owner's Windows PC, often headless and 24/7 on low power.
The owner wants to (1) **see Kimi from anywhere, for free**, on a simple 2D
web page, and (2) let Kimi **occasionally ask them for something**: an
artefact added to its world, or information about a topic it cares about.

## Decisions (owner)

- 2D page is enough; access from anywhere; must be free.
- Kimi asks only when it genuinely wants something: `artefact` or
  `information`. At most once a day, twice at the very most.
- Artefact wishes are **not** built automatically. Approved wishes go on a
  **wishlist** the owner brings to a builder (Claude) later (option C).

## Proposals accepted (made in conversation, not objected to)

- No nagging: an unanswered request expires after 3 days; Kimi remembers it
  went unanswered and never asks twice in a row (one open request at a time).
- Requests appear in the desktop app and on the web page; answering from the
  web needs a passcode.
- Information the owner gives becomes a memory ("the human told me…"). It is
  information, never orders: the Python safety rules still apply.
- Kimi can never ask for anything outside Bramblewick (money, accounts,
  passwords/keys, files, personal details, real-world items); Python rejects
  such requests before they reach the owner.

## Approaches considered

- Remote access: **Tailscale `serve`** (free Personal plan, private to the
  owner's devices, HTTPS, no router changes) — chosen. Public tunnels
  (e.g. quick Cloudflare tunnels) are free but public, and their address
  changes on restart; a fixed address needs a paid domain. Port forwarding
  rejected (exposes the PC).
- Wishes: A ready-made gift catalogue / B generic parcel / **C wishlist for
  later** — owner chose C.

## Design

### Ask the human
- New allow-listed action `ask_human` with `request_kind` (`artefact` |
  `information`), `title` (short name/topic) and `content` (Kimi's words).
- Gates (validator): setting `ask_human_enabled` (default on);
  `ask_human_daily_limit` default 1, range 0–2; no other open request;
  at least 6 real hours since the last request; forbidden-topic filter.
- Table `human_requests`; statuses `open → answered | wishlisted | declined |
  expired`. Owner replies: information → free-text answer; artefact →
  "Add to wishlist" or "Not now", each with an optional note.
- Approved wishes are appended to `data/wishlist.md` (inside Kimi's data
  folder) with Kimi's words, the day and the owner's note.
- Kimi's decision context lists the open request and recent outcomes; the
  `<limits>` line says whether asking is available.

### Web page
- `kimi/web/server.py`: Python standard-library threaded HTTP server bound to
  **127.0.0.1 only** (default port 8765), started/stopped from settings
  (`web_enabled`, default off; `web_port`). Works with the GUI and headless.
- Passcode (≥ 8 characters) stored in **Windows Credential Manager** via
  keyring, never in SQLite/settings. Data endpoints require
  `Authorization: Bearer <passcode>` (no cookies, so no CSRF); constant-time
  compare; lockout after repeated failures. Without a passcode the page
  stays locked.
- Endpoints: `GET /` (static page, no data), `GET /api/state`,
  `GET /api/layout`, `GET /api/feed`, `POST /api/requests/<id>`.
  Strict security headers (CSP, no framing, no-store), 4 KB body limit.
- Single self-contained HTML file: canvas map (places, paths, curiosity
  markers, Kimi moving, day/night tint), thought, activity, needs, weather,
  recent events, diary, board, curiosity progress, today's spend, and the
  "Kimi asks" card with reply buttons.
- Remote access documented in `docs/REMOTE_ACCESS.md`:
  `tailscale serve --bg --https=443 8765`, then open
  `https://<pc>.<tailnet>.ts.net` on a phone signed into the same tailnet.

## Left to the builder
Exact page styling, polling interval (≈2 s), event/diary counts shown.
