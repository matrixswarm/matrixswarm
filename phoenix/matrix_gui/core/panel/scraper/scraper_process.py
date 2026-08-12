# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals

# Runs in isolated subprocess — controlled by SessionWindow
# Sends logs + final results back through pipe
# Authored by Daniel F MacDonald & ChatGPT-5.1 aka The Generals
# Fully Hardened Playwright Scraper – Dual Mode (Headful/Headless)
# Drop-in replacement for scraper_process.py

import asyncio
import random
import traceback


from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

# ============================================================
# HARDEN WINDOWS EVENT LOOP
# ============================================================
try:
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
except Exception:
    pass


# ============================================================
# 👍 DUAL MODE SETTING (Commander Toggle)
# ============================================================
DEBUG_HEADFUL = True   # CHANGE TO False for silent/headless mode


# ============================================================
# 👍 STEALTH + YOUTUBE PATCH (EVASION)
# ============================================================
async def apply_stealth(page):
    await stealth_async(page)

    # Hide webdriver flag (YouTube & Google detect this)
    await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
    """)

    # Strong UA so Google/YouTube don’t downgrade or block
    await page.set_extra_http_headers({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    })


# ============================================================
# 👍 SAFE GET WRAPPER
# ============================================================
async def safe_get(page, url, log, timeout=20000):
    try:
        await page.goto(url, timeout=timeout)
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(random.uniform(1.2, 2.5))
        return True
    except Exception as e:
        log(f"[LOAD_FAIL] {url} → {type(e).__name__}: {e}")
        return False


# ============================================================
# YOUTUBE SCRAPER (HARDENED)
# ============================================================
async def scrape_youtube(page, log):
    log("Scraping YouTube Trending...")

    if not await safe_get(page, "https://www.youtube.com/feed/trending", log):
        return []

    try:
        # Scroll to trigger lazy loading
        await page.evaluate("window.scrollBy(0, 2500)")
        await page.wait_for_timeout(3000)

        # Wait for a real video tile
        await page.wait_for_selector("ytd-video-renderer", timeout=15000)

        titles = await page.eval_on_selector_all(
            "ytd-video-renderer #video-title",
            "els => els.map(e => e.textContent.trim())"
        )

        log(f"YouTube returned {len(titles)} items.")
        return [{"topic": t, "score": 30, "source": "youtube"} for t in titles[:20]]

    except Exception as e:
        log(f"[YT_FAIL] {e}")
        return []


# ============================================================
# X/TWITTER (NITTER MIRRORS)
# ============================================================
async def scrape_x(page, log):
    log("Scraping X (via Nitter)…")

    mirrors = [
        "https://nitter.net/trending",
        "https://nitter.cz/trending",
        "https://nitter.mint.lgbt/trending"
    ]

    for m in mirrors:
        if not await safe_get(page, m, log):
            continue

        try:
            await page.wait_for_selector("ol li", timeout=8000)
            raw = await page.eval_on_selector_all(
                "ol li",
                "els => els.map(e => e.textContent.trim())"
            )
            items = [t for t in raw if len(t) > 3 and not t.startswith("@")]

            if items:
                log(f"X returned {len(items)} items (mirror {m}).")
                return [{"topic": t, "score": 40, "source": "x"} for t in items[:20]]

        except Exception:
            pass

    log("X failed all mirrors.")
    return []


# ============================================================
# GOOGLE TRENDS (HARDENED)
# ============================================================
async def scrape_google(page, log):
    log("Scraping Google Trends…")

    if not await safe_get(
        page,
        "https://trends.google.com/trends/trendingsearches/daily?geo=US",
        log
    ):
        return []

    try:
        await page.wait_for_selector("div.feed-list-wrapper", timeout=15000)
        await page.wait_for_timeout(2000)

        items = await page.eval_on_selector_all(
            "div.details-top",
            "els => els.map(e => e.textContent.trim())"
        )

        log(f"Google Trends returned {len(items)} items.")
        return [{"topic": t, "score": 50, "source": "google_trends"} for t in items[:20]]

    except Exception as e:
        log(f"[GOOGLE_FAIL] {e}")
        return []


# ============================================================
# MAIN SCRAPE RUNNER
# ============================================================
async def run_all_sources(sources, filters, keepalive, pipe_send):

    async with async_playwright() as p:

        # 👍 HEADFUL/HEADLESS TOGGLE
        browser = await p.firefox.launch(

            headless=not DEBUG_HEADFUL,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-software-rasterizer",
                "--disable-gpu",
                "--disable-features=BlockInsecurePrivateNetworkRequests",
            ]
        )

        context = await browser.new_context()
        page = await context.new_page()

        # apply stealth
        await apply_stealth(page)

        # Attach network debug logs
        def log(msg: str):
            pipe_send({"type": "scrape_log", "line": msg})

        page.on("requestfailed", lambda req: log(f"[REQ_FAIL] {req.failure} {req.url}"))
        page.on("response", lambda res: log(f"[RES] {res.status} {res.url}"))

        out = {}
        log("====== SCRAPE STARTED ======")

        # Source map
        functions = {
            "youtube": scrape_youtube,
            "x": scrape_x,
            "google_trends": scrape_google,
        }

        # Execute sources
        for src in sources:
            func = functions.get(src)
            if not func:
                log(f"Unknown source: {src}")
                continue

            try:
                out[src] = await func(page, log)
            except Exception as e:
                log(f"[SCRAPER_ERROR:{src}] {e}")

        await browser.close()

        # Filtering
        filtered = apply_filters(out, filters, log)
        log("====== SCRAPE COMPLETE ======")
        return filtered


# ============================================================
# FILTER PIPELINE
# ============================================================
def apply_filters(data, filters, log):
    include = filters.get("include", "").lower().split(",")
    exclude = filters.get("exclude", "").lower().split(",")
    threshold = filters.get("score_threshold", 0)

    include = [t.strip() for t in include if t.strip()]
    exclude = [t.strip() for t in exclude if t.strip()]

    def ok(entry):
        topic = entry["topic"].lower()
        score = entry["score"]

        if include and not any(k in topic for k in include):
            return False
        if exclude and any(k in topic for k in exclude):
            return False
        if score < threshold:
            return False
        return True

    out = {}
    for src, items in data.items():
        filtered = [i for i in items if ok(i)]
        out[src] = filtered
        log(f"[FILTER] {src}: {len(items)} → {len(filtered)} after filters.")

    return out


# ============================================================
# PROCESS ENTRY (Phoenix GUI IPC Loop)
# ============================================================
def scraper_entry(conn):
    print("### SCRAPER ENTRY LOADED:", __file__)
    print("### scraper_entry starting")

    def send(obj):
        try:
            conn.send(obj)
        except Exception:
            print("### PIPE SEND FAILURE")
            pass

    while True:
        try:
            if conn.poll():
                msg = conn.recv()
                print("### RECEIVED:", msg)

                if msg.get("type") == "run":
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)

                        result = loop.run_until_complete(
                            run_all_sources(
                                msg.get("sources", []),
                                msg.get("filters", {}),
                                msg.get("keepalive", False),
                                send
                            )
                        )

                        send({"type": "scrape_results", "data": result})

                    except Exception as e:
                        send({"type": "scrape_error", "error": traceback.format_exc()})

                elif msg.get("type") == "exit":
                    send({"type": "scrape_log", "line": "Scraper shutting down."})
                    conn.close()
                    break

        except Exception as e:
            send({"type": "scrape_error", "error": traceback.format_exc()})



if __name__ == "__main__":
    pass
