# Promise Keeper

**Status: Provisional — QC testing needed.**

Watch public offers, price, warranties, return policies, and terms for material changes. Alerts summarize reported before/after changes; a public page does not establish the terms of a particular contract.

Deploy this agent with Oracle and a listener for the chosen alert role. In its Phoenix panel, add an HTTPS page and keywords, then save. The first successful check establishes a baseline. Later changed page text and keywords are sent to Oracle for analysis, which can incur API charges. Polling is periodic; the interval controls how quickly changes can be noticed and does not guarantee immediate notification.

The agent stores private encrypted page snapshots and a bounded history. Select a recent snapshot in the panel to view it, or explicitly clear a source's history. Collection stops when history is full until space is cleared. Sources showing a CAPTCHA or access challenge are paused for operator review; the panel lets the operator re-enable them after review. Respect each site's access rules and use an appropriate interval. Alerts are attributed reports to verify, not confirmation of delivery or authoritative facts.

The `life_signal` and `world_watch` agent packages must be available alongside this agent on MatrixOS. Live source, Oracle, alert relay, and restart-persistence testing are still needed.
