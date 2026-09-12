# Crypto Watches: quick start

1. Add `crypto_alert` to Swarm Workspace. Assign its `packet_signing` and
   `persistent_state` constraints, and include an alert relay plus the normal
   Phoenix RPC/WebSocket return path.
2. In Config, leave the public Bitcoin Esplora API or enter your own HTTPS API.
   Public explorers can see the Bitcoin addresses you query.
3. Deploy the updated MatrixOS source, connect Phoenix, select the crypto agent,
   and open **Crypto Watches**.
4. Choose **Price / Pair Watch** for `BTC/USDT`, `BTC/ETH`, etc. Choose the
   trigger and its threshold. A BTC/ETH value means ETH per BTC, derived from
   the two Phemex USDT spot prices.
5. Choose **Bitcoin Address** for a mainnet public address. The first lookup
   establishes a baseline; later confirmed changes can notify your relay.
6. Click **Save Changes** and wait for the saved revision acknowledgment.
   Deleting cards is also a draft until saved; saving an empty list deletes all
   watches for this agent.
7. Use **Reload Saved** after reconnecting or if another panel changed the list.
   Closing the panel does not stop remote watches.

Each watch has its own worker and state. Editing a watch resets its baseline and
hit count; unchanged watches retain theirs. A trigger limit of zero is unlimited.
Percentage changes are measured since the armed baseline, not over a fixed time
window. Cross-pair ratios are not executable trade quotes.

See the [full agent reference](agents/crypto_alert.md) for rule semantics,
persistence, privacy, dependencies, migration limitations, and troubleshooting.
