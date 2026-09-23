# StonkScape Telegram Pilot

A Telegram-controlled game pilot for the hackathon. It requests a **unique play code**, starts a per-user session, reads structured game state, chooses the next action, collects resources, upgrades progression, and keeps playing until the user sends `/stop`.

## Important reference-site finding

The supplied [StonkScape reference site](https://play.stonkscape.com/rs2.cgi) is a browser-rendered WebAssembly client. The page exposes a canvas and the client connects to the game server using a binary WebSocket protocol; it does **not** expose documented `/play-code`, `/state`, or `/action` JSON endpoints. This repository therefore does not fake those endpoints or scrape credentials.

The bot includes a `StonkScapeBridgeAdapter` with a small JSON contract. An organizer-authorized browser worker or test harness can implement the bridge while the Telegram bot handles user sessions, policy, persistence, and notifications. This separation makes the implementation honest, testable, and easy to connect to the hackathon's approved game interface.

## Telegram commands

- `/login <game_username> <game_password>` — authenticate an Existing User account in a private chat.
- `/start` — request or reuse the user's unique play code and initialize a session after login.
- `/play` — start the autonomous loop.
- `/stop` — cancel the user's loop safely.
- `/status` — show score, resources, ship, rank, upgrades, and target.
- `/target demo` — use the offline deterministic game for judging and local development.
- `/target https://...` — select an authorized bridge-backed target.

Each Telegram user has an independent persisted state. The loop is cancellable, errors pause the user rather than crashing the whole bot, and no payment or wallet secret is sent to Telegram.

Planet Forge preview runs are treated as disposable: if the service returns `Preview branch not found` while completing a run, the bot marks that run finished and advances to a fresh sector instead of pausing. When the target provides a target bearing, the controller turns toward it within an 8-degree deadband before firing. Heartbeats and completion payloads also include `shots`, `hits`, and `accuracy` telemetry. The public Planet Forge endpoint does not expose a documented REST endpoint for rendering or physically firing at canvas asteroids, so authoritative score increases still depend on the target accepting and applying that telemetry; the bot does not fabricate local score.

## Local demo

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
# set TELEGRAM_BOT_TOKEN
python -m bot
```

The default `GAME_MODE=demo` works without a game account or external service. It is the safest way to demonstrate the complete `/start` → `/play` → `/status` → `/stop` flow.

In StonkScape mode, the flow mirrors the reference client's visible **Existing User** path: send `/login username password` in a private Telegram chat, then `/start` to obtain a unique play code, then `/play` to begin autonomous play. The bot attempts to delete the login message, sends the password only to the authorized bridge, and discards it immediately after authentication; it is not echoed, logged, or written to `data/state.json`. Use a private chat because Telegram command messages are visible to the chat participants.

## Authorized StonkScape bridge mode

Set these variables only when the hackathon organizer provides an authorized bridge:

```text
TELEGRAM_BOT_TOKEN=<BotFather token>
GAME_MODE=stonkscape
GAME_BASE_URL=https://play.stonkscape.com/rs2.cgi
STONKSCAPE_BRIDGE_URL=https://your-authorized-bridge.example
STATE_FILE=./data/state.json
POLL_SECONDS=2
```

The bridge contract is:

| Request | JSON body or query | Response |
|---|---|---|
| `POST /login` | `telegram_user_id`, `reference_url`, `username`, `password` | `{ "authenticated": true }` |
| `POST /play-code` | `telegram_user_id`, `reference_url` | `{ "play_code": "..." }` |
| `POST /session` | above plus `play_code` | `{ "session_id": "..." }` |
| `GET /state` | above plus `play_code`, `session_id` | `GameState` or `{ "state": GameState }` |
| `POST /action` | above plus `action` | `GameState` or `{ "state": GameState }` |
| `POST /upgrade` | above plus `play_code`, `session_id` | `GameState` or `{ "state": GameState }` |

`GameState` contains `score`, `resources`, `position`, `ship`, `rank`, `upgrades`, `cooldown_seconds`, `alive`, and `game_over`. The bridge must enforce the organizer's authorization and must never accept Telegram-supplied credentials as a substitute for its own game authentication.

## Deployment

This is a long-running Telegram polling worker. Deploy it as a worker on Railway, Render, Fly.io, or another service that keeps a process online. Do not expose a public HTTP port for polling. Mount persistent storage for `STATE_FILE` if user sessions must survive redeployments.

For a free, simple hackathon demo, run the offline mode locally or on a worker with `GAME_MODE=demo`. For 24/7 hosting, use an always-on worker; the exact cost depends on the provider and plan. Keep `TELEGRAM_BOT_TOKEN`, bridge credentials, and any game credentials in server-side secrets, never in Git.

## Tests

```bash
python -m pytest -q
python -m compileall -q bot scripts tests
```

The tests cover target validation, the controller policy, deterministic demo progression, legacy adapter planning, and StonkScape bridge response parsing.
