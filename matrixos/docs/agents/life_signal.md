# LifeSignal

**Status: Provisional — QC testing needed.**

LifeSignal watches user-configured sources for newly reported events and sends
attributed leads through a configured alert service role. A report is not proof;
the operator should open and verify the linked source before publishing.

## Deploy

Add LifeSignal and Oracle to the swarm. Configure an Oracle service role (the
default is `hive.oracle`), an alert relay advertising the desired alert role,
packet signing, and the `persistent_state` constraint for LifeSignal. Deploy
the updated Oracle source as well as LifeSignal and restart both agents. The
Phoenix panel requires the corresponding updated Phoenix code.

In the LifeSignal panel, add an HTTPS source, select its type, enter one keyword
or watched name per line, choose the alert role, and save. Wikipedia and GDELT
starters are supplied by agent metadata; complete the article name or replace
`YOUR_SEARCH`, respectively. GDELT's feed supplies matching titles and links;
verify its current limits and the original publisher's terms before use. RSS
and webpage sources are user supplied. Only use sources whose terms permit the
intended automated and AI-assisted use; source availability does not establish
permission. Feed items provide the text available in the feed, not necessarily
the full article. Webpages send the extracted page text and its changes to
Oracle; pages over the size limit are rejected rather than silently truncated.

For a webpage, select **Check page for CAPTCHA with Oracle** in the Analysis
field to inspect each successful page check rather than wait for a change. No
keywords are required for this mode. Oracle reports yes, no, or uncertain; a
yes pauses the host until the operator reviews and re-enables it. Detected
challenges are not solved or bypassed. The agent stops sending queued analyses
for a paused host. An inconclusive answer is shown but does not automatically
pause. The check sees extracted response text, not a rendered browser or an
image, so it cannot identify every visual or JavaScript-only CAPTCHA.

CAPTCHA mode can call Oracle once per successful check. At a 120-second
interval, a continuously available page has about 720 scheduled checks per day,
with possible additional calls from retries. API usage charges may apply.

In change-monitoring mode, the first successful page or feed read is a baseline
and does not alert on old content. CAPTCHA mode analyzes the first read. English
Wikipedia article sources use Wikimedia's recent-changes SSE
stream after a baseline read; other sources poll no faster than two minutes,
defaulting to an hour. Stream reconnects use a saved cursor where available,
but long outages or a lost/expired cursor may leave a gap. Neither source
coverage nor timeliness is guaranteed. Source errors and blocked hosts appear
after using Reload Saved in the panel. The source status shows the last
successful check in the Phoenix computer's local time, or indicates that the
first successful baseline is still pending. The status also shows when changes
are awaiting Oracle. Successful checks are recorded in the agent log.

If a CAPTCHA, access challenge, or HTTP 401/403 occurs, LifeSignal stops further
requests to that host and persists the pause across restarts. The operator can
review the access conditions and explicitly re-enable it from the panel. It
does not solve or bypass challenges. A 429 response delays polling based on
Retry-After. Robots rules and TLS certificate verification are enforced.
Redirects are not automatically followed; configure an appropriate direct URL.
Requests from this agent are spaced by at least five seconds per host. A missing
robots.txt (HTTP 404/410) is treated as having no published robot rules; other
errors are surfaced instead of assuming permission.

The agent stores source configuration, baselines, pending analysis, event
history and delivery queue state encrypted. Feed entries are deduplicated by
their IDs; matching death reports use Oracle's extracted name and event type
to suppress repeats, with a retained history of up to 10,000 identities. This
heuristic can miss duplicates or confuse people with the same name. Repeated
gossip events are not guaranteed to be deduplicated across different sources.
For each alert, successful relay queue attempts are retained per destination;
queueing does not confirm the final Telegram, Discord or email delivery.

Oracle defaults to 200,000 input characters, configurable from 1,000 to
1,000,000 in the workspace editor. This is a character bound, not a promise
that every model's context window can accept it. Oracle returns an explicit
error when the configured bound is exceeded; LifeSignal shows this in the panel
and provides Retry Analysis after the operator adjusts the limit. Model API
charges apply to actual requests; local unit tests use mocked responses.
LifeSignal divides larger prompts into bounded signed swarm packets. The updated
Oracle reassembles these only for a verified sender, so the normal packet-size
guards remain in place. Other Oracle callers must also use fragmentation if their
own transport enforces smaller packet limits.

## First end-to-end test

1. Choose a controlled HTTPS page or feed that allows the requested access.
   Add it with a keyword, save, and wait for the first baseline check.
2. Change the page or publish a new feed item containing a test report that
   matches the keyword. Wait for the configured interval, then reload the panel.
3. Confirm the source, title and link in Recent reported matches and check the
   configured relay. Restart the agent and check that the same item does not
   produce a second alert. Use a non-sensitive test page; its text goes to Oracle.
