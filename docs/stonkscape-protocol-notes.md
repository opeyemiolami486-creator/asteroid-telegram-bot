# StonkScape protocol and mechanics notes

## Scope

These notes come from the authorized hackathon test account and the public client at `https://play.stonkscape.com/rs2.cgi`. Credentials and full packet payloads are intentionally excluded.

## Confirmed transport

The browser client loads a WebAssembly/JavaScript RuneScape-style client and connects to:

```text
wss://play.stonkscape.com
```

The WebSocket subprotocol is:

```text
binary
```

The client uses raw binary frames rather than JSON REST calls. The page itself exposes a single canvas, so DOM scraping is not a viable state interface.

## Login handshake observations

The client opens the WebSocket only after the Existing User Login action. The initial traffic observed was:

| Direction | Length | First bytes | Interpretation |
|---|---:|---|---|
| client → server | 2 | `14, 22` | initial handshake/version/world packet; exact field semantics still need decoding |
| client → server | 107 | `16, 105, 255, 1, ...` | encrypted login packet containing the account credentials and session values |

The JavaScript client shows the following sequence:

1. Hash the username to select the world/login value.
2. Send opcode `14` plus the derived world value.
3. Read eight bytes and a one-byte server response.
4. Generate four random 32-bit values and combine them with the server key.
5. Build opcode `10` with the random values, client constant `1337`, username, password, and RSA encryption.
6. Wrap that payload in the outer login frame beginning with opcode `16` for a normal login or `18` for a reconnect.
7. A response code of `2` transitions the client into the game; code `3` displays “Invalid username or password.”

The public client contains the RSA exponent/modulus and packet writer implementation, so a protocol adapter can reproduce the handshake without browser automation. The remaining work is implementing the exact integer/string encodings and server response parser from the client source.

## Authenticated game view

The authorized login succeeded. The visible post-login game contained:

- A player character and world scene.
- Minimap and compass.
- Health/status orbs.
- Inventory with item stacks.
- Skill/action tabs.
- Public chat, private chat, trade/duel, and abuse-report controls.
- A “Play to Earn” panel with a live reward value and live records.

The client began sending short binary gameplay frames after login. Metadata-only capture showed one-byte and multi-byte opcodes such as `81`, `75`, `183`, `23`, `55`, `9`, `64`, `233`, `177`, `168`, `228`, `24`, `159`, `205`, `231`, `247`, and `192`. These are not yet assigned to actions because the client’s packet dispatch table must be decoded alongside the associated payload lengths.

## Mechanics visible in the client

The client is based on an Old School RuneScape-like interaction model. Its menu and configuration strings include item actions such as:

- Walk or move to a location.
- Pick up, use, drop, and examine items.
- Inventory, bank, trade, and duel interactions.
- Combat and target interactions.
- Skill panels including strength, hitpoints, ranged, prayer, magic, cooking, woodcutting, fletching, fishing, firemaking, crafting, and smithing.
- StonkScape-specific activities including the Stonk Rat, arena/duel content, challenges, and reward records.

This is enough to define a high-level bot policy, but not enough to safely automate combat or resource grinding until state packets and action opcodes are decoded and tested against the organizer’s rules.

## Recommended bridge architecture

The reliable implementation path is a small browser worker or native protocol client with a typed boundary:

```text
Telegram bot
  → authenticated bridge session
  → login/session manager
  → binary WebSocket codec
  → state reducer (player, NPCs, inventory, skills, map, interfaces)
  → policy engine (safe movement, resource loop, combat, banking, upgrades)
```

The bridge should expose structured operations such as:

```text
login(username, password)
read_state()
walk_to(x, y)
interact_entity(entity_id, action)
interact_item(slot, action)
select_interface(interface_id, option)
stop()
```

The Telegram bot should not receive raw credentials again after login. It should receive only a bridge session identifier and sanitized state summaries. The bridge should enforce a stop flag and rate-limit actions.

## Remaining protocol work

1. Decode the client’s packet buffer methods (`p1`, `p2`, `p4`, string encoders, RSA block writer).
2. Map the inbound opcode dispatch table in `QE()` to typed state updates.
3. Map outbound action methods to packet opcodes and payload schemas.
4. Capture controlled actions one at a time in the browser and compare frame metadata.
5. Build a replay fixture from sanitized packet traces.
6. Implement state reducer and policy against replay fixtures before enabling live actions.

Do not send credentials to arbitrary URLs. The bridge URL must be an organizer-approved endpoint or a local process under the hackathon operator’s control.
