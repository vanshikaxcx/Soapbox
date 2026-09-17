"""Long-lived browser processes shared across search tasks.

Launching a full browser per search call is the dominant latency cost,
regardless of engine. Both engines below are started once per container and
reused for every task; per-task isolation still comes from a fresh
BrowserContext (see PlaywrightMerchant), not from a fresh Browser process.

Playwright's *sync* API is not safe to call from more than one OS thread:
every object derived from a `sync_playwright()` driver is bound to whichever
thread started that driver, and calling into it from another thread raises
`greenlet.error: Cannot switch to a different thread`. FastAPI runs sync
route handlers across a thread pool, so two genuinely concurrent search
tasks would hit this today — confirmed live, not hypothetical (reproduced
with two threads calling BlinkitMerchant.search() at once).

The fix here is one Playwright driver + one dedicated worker thread *per
engine*, not one global thread: Chromium and Lightpanda are independent
drivers, so a Blinkit (chromium) task and a Zepto (lightpanda) task can
still run genuinely concurrently — each confined to its own thread — which
is what the spec's SEARCH_CONCURRENCY=2 (searching two merchants in
parallel) actually needs. Two tasks for the *same* engine still serialize
on that engine's one thread; that's an acceptable, narrower constraint than
losing cross-engine concurrency entirely.
"""
from __future__ import annotations

import atexit
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

from playwright.sync_api import Browser, Playwright, sync_playwright

LIGHTPANDA_HOST = "127.0.0.1"
LIGHTPANDA_PORT = 9222
_LIGHTPANDA_CONNECT_RETRIES = 10
_LIGHTPANDA_CONNECT_RETRY_DELAY_SECONDS = 0.3

T = TypeVar("T")

# One single-worker executor per engine == one dedicated thread per engine.
# Everything that touches that engine's Playwright objects must run inside
# it; see run_on_engine_thread().
_executors: dict[str, ThreadPoolExecutor] = {
    "chromium": ThreadPoolExecutor(max_workers=1, thread_name_prefix="pw-chromium"),
    "lightpanda": ThreadPoolExecutor(max_workers=1, thread_name_prefix="pw-lightpanda"),
}

# All state below is only ever touched from inside its own engine's thread
# (via run_on_engine_thread), so it needs no lock despite being shared.
_playwright: dict[str, Playwright] = {}
_browsers: dict[str, Browser] = {}
_lightpanda_process: subprocess.Popen | None = None


def run_on_engine_thread(engine: str, fn: Callable[[], T]) -> T:
    """Run `fn` on the single thread that owns `engine`'s Playwright driver.

    Blocks the calling thread until `fn` completes. Any exception raised by
    `fn` propagates to the caller as normal, from `.result()`.
    """
    executor = _executors.get(engine)
    if executor is None:
        raise ValueError(f"unknown browser engine: {engine}")
    return executor.submit(fn).result()


def _playwright_instance(engine: str) -> Playwright:
    """Must only be called from inside run_on_engine_thread(engine, ...) — see module docstring."""
    pw = _playwright.get(engine)
    if pw is None:
        pw = sync_playwright().start()
        _playwright[engine] = pw
        # pw.stop() is itself a Playwright call and must run on the same
        # thread that started it, not atexit's default (the main thread).
        # Best-effort: Python's own executor-shutdown atexit hook can run
        # first depending on registration order, in which case there's
        # nothing left to submit to — the process is exiting either way.
        def _stop() -> None:
            try:
                run_on_engine_thread(engine, pw.stop)
            except RuntimeError:
                pass

        atexit.register(_stop)
    return pw


def _start_lightpanda_process() -> None:
    global _lightpanda_process
    binary = shutil.which("lightpanda") or "/usr/local/bin/lightpanda"
    _lightpanda_process = subprocess.Popen(
        [
            binary,
            "serve",
            "--host",
            LIGHTPANDA_HOST,
            "--port",
            str(LIGHTPANDA_PORT),
            "--log-level",
            "warn",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    atexit.register(_lightpanda_process.terminate)


def _connect_lightpanda(pw: Playwright) -> Browser:
    if _lightpanda_process is None or _lightpanda_process.poll() is not None:
        _start_lightpanda_process()

    endpoint = f"http://{LIGHTPANDA_HOST}:{LIGHTPANDA_PORT}"
    last_error: Exception | None = None
    for _ in range(_LIGHTPANDA_CONNECT_RETRIES):
        try:
            return pw.chromium.connect_over_cdp(endpoint)
        except Exception as exc:  # noqa: BLE001 - retry until the CDP server is ready
            last_error = exc
            time.sleep(_LIGHTPANDA_CONNECT_RETRY_DELAY_SECONDS)
    raise RuntimeError(f"lightpanda CDP server never became reachable at {endpoint}") from last_error


def get_browser(engine: str) -> Browser:
    """Return the shared Browser for `engine`, starting it on first use.

    Must only be called from inside run_on_engine_thread(engine, ...) —
    like every other Playwright object, the Browser it returns is bound to
    that thread. get_browser() alone being "safe" doesn't help if the
    caller then calls .new_context() on the result from a different
    thread; the whole per-task body needs to run inside the same
    run_on_engine_thread() call, which is what PlaywrightMerchant._with_page
    does.
    """
    browser = _browsers.get(engine)
    if browser is not None and browser.is_connected():
        return browser

    pw = _playwright_instance(engine)
    if engine == "chromium":
        browser = pw.chromium.launch(headless=True)
    elif engine == "lightpanda":
        browser = _connect_lightpanda(pw)
    else:
        raise ValueError(f"unknown browser engine: {engine}")
    _browsers[engine] = browser
    return browser
