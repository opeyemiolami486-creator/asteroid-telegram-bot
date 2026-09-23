# Asteroid Telegram Bot

Telegram-controlled asteroid-mining game runner for the hackathon. In the default **Demo Forge** mode, each player gets a deterministic play code and an offline session where the bot starts a scrap ship, shatters asteroids, harvests ore and metal, and forges upgrades. The game loop follows the reference site's public fantasy without contacting the reference site.

## Safety and scope

This repository must only be used against an isolated, authorized hackathon test harness. Do not point it at `planet-forge.com` or any real game, exchange, wallet, or account. Never commit `.env`, generated state, session cookies, private keys, or Telegram tokens. The generated wallet record is a local demo placeholder, not a Solana wallet and not suitable for real funds.

## Commands

- `/start` — create or display the user's bot profile and request a demo play code.
- `/play` — start the per-user mining loop.
- `/stop` — stop the loop gracefully.
- `/status` — show the latest score, resources, position, ship, rank, upgrades, and cooldown.

## Run locally

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# set TELEGRAM_BOT_TOKEN
python -m bot
```

## Game modes and adapter contract

Set `GAME_MODE=demo` (the default) for judging and local demos. The deterministic `DemoGameAdapter` is self-contained, so it works without a database, chain, or external game account. The demo provides a short, repeatable loop: fire to mine, collect metal and upgrade tokens, and automatically forge stronger ships when the controller can afford an upgrade.

The controller uses an explicit state/action model: request a play code, start a session, read state, submit one legal action, and upgrade when resources permit. Set another mode only when an isolated, authorized test harness has supplied a documented contract; the `ReferenceSiteAdapter` remains a fail-closed boundary and will not infer undocumented endpoints.

## Tests

```bash
pytest -q
```

The tests cover the conservative controller policy and the demo adapter's mining and forging behavior.
