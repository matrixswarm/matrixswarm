# Crypto Alert: Phemex prices and Bitcoin watches

`crypto_alert` provides read-only market and Bitcoin-address alerts, with a Phoenix
CRUD panel. It never places orders, signs transactions, or requests seed phrases,
private keys, exchange credentials, or extended wallet keys.

## Deploy

1. Add `crypto_alert` in Swarm Workspace using the current agent metadata.
2. Resolve `packet_signing` and assign a dedicated `persistent_state` registry
   profile, just as for Forensic Detective. Keep that same profile for later
   redeployments. Do not share one profile between running crypto agents.
3. In the agent Config editor choose the Bitcoin Esplora HTTPS API and the alert
   delivery role (default `hive.alert`). Include a relay advertising that role and
   its appropriate handler. The normal RPC/WebSocket return path must be running.
4. Railgun-deploy the updated MatrixOS sources and updated Phoenix metadata.
   Existing workspaces need the new constraint added/resolved; a source replacement
   alone does not provision persistence.
5. Connect, select the agent, and open **Crypto Watches**.

Only the existing `requests`, `websocket-client`, and `cryptography` runtime
dependencies are used. There is no NumPy, pandas, blockchain SDK, or exchange
account dependency. No new privileged OS permissions are needed.

## Prices and pairs

One shared public connection to `wss://ws.phemex.com` subscribes to
`spot_market24h.subscribe`. Spot `lastEp` values have eight decimal places.
Heartbeat checks, bounded reconnect backoff, and stale-quote rejection keep old
prices from firing alerts while disconnected. Each active watch has its own
stoppable thread and independent baseline, cooldown, and hit counter (64 watches
maximum per agent).

- `BTC/USDT`: Phemex BTC spot price in USDT.
- `BTC/ETH`: BTC/USDT divided by ETH/USDT, yielding ETH per BTC.
- Other ratios work when both assets have fresh Phemex USDT spot prices.
- Cross-pairs are explicitly labeled **derived**: they are not direct order-book
  quotes, executable swap rates, or fee/slippage estimates.
- Unsupported or stale pairs display a waiting status; there is no fallback to
  fabricated prices or a different exchange.

The endpoint follows Phemex's [public endpoint migration notice](https://phemex.com/announcements/phemex-updates-api-entry-endpoints);
the [spot API reference](https://github.com/phemex/phemex-api-docs/blob/master/Public-Spot-API-en.md)
documents the ticker protocol but still contains the older WebSocket address.

## Rules

| Trigger | Behavior |
| --- | --- |
| `price_above` / `price_below` | At or beyond a threshold, once until the price returns to the other side. Can fire on the first fresh observation if already beyond the threshold. |
| `price_change_above` / `price_change_below` | Positive percentage magnitude up/down since this watch's armed baseline, not a rolling 24-hour change. |
| `price_delta_above` / `price_delta_below` | Positive absolute magnitude up/down in the pair's quote units since the armed baseline. |
| `asset_conversion` | Source amount × source USDT price ÷ target USDT price reaches the threshold in target units. Uses crossing/rearm behavior. |
| `wallet_change` | Confirmed Bitcoin address balance or confirmed transaction count changes. |

Percentage/delta baselines reset after a trigger. Every watch has an optional
label, active switch, notification switch, panel-stream switch, cooldown seconds,
and trigger limit (`0` means unlimited). Reaching the limit suppresses further
notifications, but leaves the watch visible. To rearm/reset it, edit and save it.

**Any saved edit to a watch resets its baseline, hit counter, and crossing state.**
Unchanged watches retain their state. Pausing stops the watch worker; turning
notifications off leaves observation running. Turning panel streaming off does
not stop remote monitoring.

## Bitcoin address watch and privacy

The default API is `https://blockstream.info/api`. Only
`GET /address/<public-address>` is used, with TLS verification, timeouts, a response
size limit, and no automatic redirect following. The panel shows confirmed BTC,
pending net BTC, confirmed transaction count, and USDT valuation when a fresh BTC
price is available. Confirmed-change detection continues without Phemex.

The initial lookup establishes a baseline without replaying historical activity.
Pending transactions do not trigger. Changes to the confirmed transaction count
can trigger even with no net balance movement. During cooldown, the next notice
reports the net confirmed change since the prior notice. Chain reorganizations
can also change these values. This is periodic address-state monitoring, not a
complete transaction ledger; intermediate changes between polls can be missed.
The default poll interval is 60 seconds (minimum 30).

This watches **individual Bitcoin mainnet addresses**, not an entire HD wallet or
all change addresses. Add each address you want watched. No Ethereum/ERC-20 wallet
indexing or xpub scanning is included.

A public explorer sees your queried addresses and network origin. For better
privacy, configure your own HTTPS [Esplora server](https://github.com/Blockstream/esplora/blob/master/API.md).
An explorer indexes blockchain data; it is not a wallet and cannot spend funds.
Your self-hosted server still needs a trusted TLS certificate or a correctly
configured CA bundle. Do not disable certificate verification.

Watch definitions and baselines are encrypted at rest. Matrix's crypto request
logging omits the payload, and requests route only to the named crypto instance.
Authorized Phoenix panels can display the full address. Alert text abbreviates
the address, but balances and labels reach your chosen relays; choose labels and
relay recipients accordingly.

## Save/load and delivery semantics

**Save Changes** commits the entire list, including deletions and an empty list.
The panel reports success only after the agent acknowledges an encrypted save.
A revision number prevents one panel silently overwriting another. **Reload Saved**
replaces the local draft with agent state; it asks before discarding unsaved edits.
A timeout means the outcome is unknown: reload before retrying.

The agent uses `EncryptedStateMixin`, namespace `crypto_alerts`, document
`watches`. With the same persistent-state profile, alerts and trigger history
survive restart, new agent IDs, and redeployment on that host/universe. They do
not survive deleting their static persistent-state directory. Back up both the
encrypted state files and the profile's key material securely.

Deployment `config.watch_list` seeds only a new store; it never overwrites saved
watches, even when the saved list is empty. Invalid or undecryptable state fails
closed rather than silently resetting. The former experimental AES watch file
and global Phoenix `crypto_alerts` vault field are not automatically migrated.

A trigger is persisted before sending a notification. Delivery status is
`pending`, `queued`, or `failed`; queued means handed to at least one swarm relay,
not confirmation of email/Discord delivery. A crash between persistence and
sending can leave a pending event; failed/interrupted events are not automatically
retried, avoiding duplicate alerts. This is best-effort alerting, not exactly-once
financial event delivery.

Panel subscriptions have a 60-second lease, renewed every 20 seconds while open.
Hiding the panel releases its subscription without stopping the agent's watches.
For threshold rules, enter the target in the dynamically labeled **Alert price**
or **Alert ratio** field. New price cards leave it blank so they cannot
accidentally fire against a placeholder value.

## Troubleshooting

- Waiting for prices: verify Phemex connectivity and that both USDT spot markets
  exist. The runtime clock must be accurate for quote freshness checks.
- Watch error: `SSLError`: check the MatrixOS host's CA trust/proxy configuration.
  Certificate checks deliberately remain enabled.
- Save fails: resolve the persistence constraint, check write access to the state
  directory, and reload if another panel changed the revision.
- Delivery failed: check the configured alert role and receiving relay. The agent
  does not perform unrelated public-IP lookups.
