# WP-04 — Agent container and two live merchant connectors

Owner: P2
Reviewers: P1 (result explainability), P4 (container/cloud limits)
Status: Implementing
Depends on: WP-00 (unmerged into this branch as of writing); checkpoint access (WP-01, not yet started)

## Outcome and user value

A shopper's item query returns honest, location-verified prices from two real quick-commerce merchants (Blinkit, Zepto) in the tested locality (pincode 110001), fast enough that a 45-second per-item fetch deadline is comfortably met, with live and fixture results never mixed in one response.

## In scope

- `Merchant` port (`search`, `refresh`, `assess_fees`) and typed models (`Observation`, `Location`, `ItemQuery`, `MerchantError`, `FeeAssessment`).
- Live connectors for Blinkit and Zepto, plus a deterministic fixture connector for CI/demo fallback.
- Registry enforcing live/fixture isolation.
- FastAPI agent entrypoint (`/health`, `/tasks/search`) with bearer-token auth.
- Per-connector browser engine selection and the shared browser/context lifecycle.
- Evidence capture (screenshot, falling back to raw HTML).
- Domain allowlist enforcement before any navigation.

## Out of scope

- Basket-level comparison, repair, ranking (WP-06).
- Durable job/workflow wrapping of a search call (WP-07).
- S3 evidence storage (local disk only; port is ready, adapter isn't written).
- Real (live-cart) fee data on either connector (see "Open questions" — requires live cart mutation, deliberately not attempted; a published-fee-schedule *estimate* is implemented instead, see below).
- Automated test suite (blocked on WP-00's pytest/lint config not being merged into this branch).
- BigBasket, Swiggy Instamart (`swiggy.com/instamart`) as a third/alternative live merchant — evaluated and rejected, see "Open questions."
- Any AWS deployment or Fargate cloud-trace proof (WP-01, not started by P4 as of writing).

## User flow and UI states

N/A — this package has no direct UI. Callers are the search workflow (WP-06/WP-07) and, during development, direct HTTP calls to `/tasks/search`.

## API and event contracts

`POST /tasks/search`
```
{ "location": {"locality": str, "pincode": str}, "item": {"name": str, "quantity": float, "unit": str}, "mode": "live" | "fixture" }
-> { "observations": [Observation, ...] }
```
`Observation`: `merchant, sku, url, product_name, pack_size, unit, price_paise, in_stock, verified_location, fetch_time, evidence_key, extraction_status, mode`.

`MerchantError`: `merchant, code (timeout|captcha|blocked|location_unsupported|not_found|layout_changed|unknown), message, occurred_at`. Dropped (not surfaced) by `search_merchants`; the caller is responsible for partial-result coverage.

## Data model and state transitions

None owned here beyond the `Observation`/`MerchantError`/`FeeAssessment` shapes above — pure Pydantic models, no persistence.

## Components, ports, and dependency direction

```
FastAPI /tasks/search -> search_merchants (Strands tool) -> Merchant port -> {BlinkitMerchant, ZeptoMerchant, FixtureMerchant}
```

- `Merchant` (`base.py`): abstract port, three methods, no engine-specific code.
- `PlaywrightMerchant` (`playwright_base.py`): shared lifecycle (context creation, evidence capture, error classification, deadline handling) for both live connectors.
- `browser_pool.py`: one Playwright driver + one dedicated worker thread **per engine** (chromium, lightpanda), each holding one long-lived `Browser`. Confirmed live: Playwright's sync API is bound to whichever thread started its driver — two threads calling into the same driver crash with `greenlet.error: Cannot switch to a different thread`. FastAPI's sync route handlers run across a thread pool, so this isn't hypothetical; `run_on_engine_thread()` is how every Playwright-touching call is confined to the correct thread regardless of which thread called in.
- `parsing.py`: shared `parse_inr_to_paise` / `parse_pack_size`, used identically by both connectors.
- `registry.py`: `build_registry(mode)` returns either both live connectors or both fixture connectors, never a mix.

### Browser engine per connector

- **Zepto → Lightpanda.** Confirmed live: not behind Cloudflare-class bot management; Lightpanda (no CSS/image/font/GPU rendering) cuts a warm `search()` call to ~2-3s.
- **Blinkit → real Chromium.** Confirmed live: Lightpanda gets an immediate 403 from Blinkit's Cloudflare edge (Lightpanda's `--user-agent` flag explicitly refuses to contain "Mozilla", i.e. it won't impersonate a real browser — a deliberate design choice, not a gap). Bundled headless Chromium *also* 403'd initially: its default `navigator.userAgent` literally contains the string `"HeadlessChrome"`, which Cloudflare blocks on directly. A normal mobile Chrome UA string was the complete, sufficient fix — no headed browser, stealth plugins, or `navigator.webdriver` overrides were needed once this was isolated.

### Blinkit's location-selection and session cache

Confirmed live: no Blinkit catalog or search renders until a location is explicitly selected (unlike Zepto's silent IP-based default) — close an app-install banner (optional) → close a download-app slider (optional) → "Select manually" → type the pincode into `input[name="select-locality"]` → click the first suggestion. That flow's entire effect is cookie/localStorage state (`BrowserContext.storage_state()`); a fresh context seeded with a saved state shows the location already applied, and Blinkit then resolves search and PDP URLs directly (`blinkit.com/prn/x/prid/<id>` resolves correctly with a placeholder slug once a location is set).

`warm_location(pincode)` in `blinkit.py` makes this a one-time cost per pincode per container lifetime:
- Thread-safe, idempotent, keyed and locked per pincode — concurrent callers for the same pincode block on one flow rather than each running their own ~8s manual selection.
- Called from the agent's FastAPI startup hook (`main.py`) in a background thread, so `/health` responds immediately; a real request landing before warm-up finishes blocks on the same lock rather than racing it.
- Cache is process-lifetime, in-memory only — lost on container restart. Accepted for the single tested locality in scope; a stale/lost entry just re-pays the one-time cost, which is the same handled path as a cold start.

Measured, cold vs. warm, through the real connector:

| | Cold (builds cache) | Warm (cache hit) |
|---|---|---|
| Blinkit `search()` | ~8.3s | ~1.7s |
| Blinkit `refresh()` | ~9.1s | ~3.5-5.9s (PDP page is heavier; 1.5s hydration wait is still a blind timeout, not condition-based) |
| Zepto `search()` | ~6-9s (Lightpanda process boot, one-time per container) | ~2-3s |

### P3 integration: `P3MerchantPortAdapter`

P3's WP-08 depends on a `MerchantPort` with a different shape than the one this package built (compared directly against `services/application/ports.py` on `origin/p3`): `location: str` vs. our `Location`, `deadline_seconds: int` vs. our absolute `deadline`, and P3's own `Observation`/`DomainError`/`Charge` types vs. ours. `p3_merchant_port_adapter.py` translates between them, built and its logic verified against P3's real fetched class definitions (not guessed) — but it **cannot be import-checked in this repo yet**, since P3's `services.domain`/`services.application` don't exist in this tree (still on the unreconciled `origin/p3` layout). Verified by temporarily reconstructing P3's exact classes as local stubs and running the adapter against real Blinkit data: unit conversion, `Money`/`Mode`/`ExtractionStatus` mapping, and both `assess_fees` error paths all produced correct output. Three things in it are documented assumptions, not confirmed facts, and need a real answer from P3 before this is trusted in production — see the adapter's module docstring: what the bare `location: str` actually contains, the missing merchant-fetch-failure `DomainError` (P3's taxonomy has none — `InvalidRecord` is used as a labeled stand-in), and that `assess_fees`'s `line_hash`-only signature requires an injected line-lookup this package has no way to supply on its own (WP-07's store isn't built).

### Cross-merchant concurrency

`search_merchants` (the Strands tool) calls all registered merchants' `search()` concurrently via a small `ThreadPoolExecutor`, one submission per merchant. Because each connector's actual browser work is confined to its own engine thread, this genuinely overlaps Blinkit and Zepto rather than just launching them at the same time. Confirmed live: two-merchant search wall time dropped from 5.74s (sequential) to 3.87s (concurrent) — close to the slower merchant (Zepto) alone, not the sum.

### Out-of-stock detection (Blinkit)

Confirmed live (query "rare spice" surfaced a real example — "Rareamrit Kashmiri Mongra Saffron"): an out-of-stock card overlays the literal text `"Out of Stock"` on the product image. `in_stock` is computed as `"Out of Stock" not in card.inner_text()` rather than matching a specific badge class, so it's robust to layout/class changes as long as the text itself doesn't change. Verified against a real mixed in-stock/out-of-stock result set (8 in-stock + 1 out-of-stock correctly distinguished).

### Fee estimation (both connectors)

`assess_fees` cannot read a real, current fee without a live cart (see Security section). Both connectors instead apply each merchant's **published fee policy** (`fees.py`) to the already-known basket subtotal: Blinkit — free delivery above ₹199, else ₹30 delivery + ₹11 handling (upper bounds of the published ranges, so an estimate never understates cost); Zepto — ₹2 flat platform fee, free delivery above ₹99, else ₹28. Source: a dated (2026-06-04) industry article, checked 2026-09-17 — these numbers drift (Zepto's platform fee was introduced in 2024 and rolled back by 2025 per the same source) and have no live signal telling this code when they're stale; re-verify periodically. Every such assessment carries `completeness="estimated"`, never `"complete"`. `line_hash` uses a local placeholder hash (`fees.placeholder_line_hash`), not WP-02's canonical domain-separated hash — swap it once WP-02 lands in this tree.

## Security, privacy, and authorization

- Domain allowlist (`ALLOWED_DOMAINS`) checked via `_goto` (`playwright_base.py`) both before navigating and after — `page.goto()` follows redirects transparently, so checking only the requested URL would miss a server-side redirect landing off-allowlist mid-flight. Every navigation in both connectors goes through `_goto`, not a raw `page.goto()`; verified live that this doesn't change either connector's actual search behavior (10/10 results, both merchants) and that the post-navigation check does raise for an off-allowlist host.
- `/tasks/search` requires a bearer token (`AGENT_SERVICE_TOKEN`) in production; unset token is a local-dev-only bypass.
- No shopper credentials or CAPTCHA-bypass logic anywhere in either connector.
- `assess_fees` never reads a real, current fee: that requires adding items to a live cart, which mutates state on the merchant's actual servers. One attempt (Zepto, clicking "ADD" on a real product) was made during development and was correctly blocked by the harness's own permission system as a state-mutating action on a real third-party site. This is documented as a deliberate non-goal, not a forgotten one — a published-fee-schedule *estimate* is returned instead (see "Fee estimation" above), never fabricated as `"complete"`.

## Idempotency, concurrency, timeout, and retry behavior

- `search()`/`refresh()` take an explicit `deadline`; `_with_page` returns a typed `TIMEOUT` `MerchantError` immediately if the deadline has already passed, and clamps Playwright's own per-page timeout to whatever time remains.
- Concurrency is now genuinely safe across engines (see above) and serialized-but-correct within one engine (two Blinkit calls queue on Blinkit's one dedicated thread rather than crashing or racing).
- No retry logic in the connectors themselves; a failed fetch returns a typed `MerchantError` for the caller (search workflow, WP-06/WP-07) to decide on.

## Failure modes and user-visible errors

| Code | When |
|---|---|
| `TIMEOUT` | Deadline elapsed before or during the fetch. |
| `NOT_FOUND` | No results/product schema found for the query or SKU. |
| `LAYOUT_CHANGED` | Expected elements/JSON structure missing — the connector's markup assumptions are stale. |
| `CAPTCHA` / `BLOCKED` | Reserved for bot-challenge detection; not yet triggered/observed live on either merchant during development. |
| `UNKNOWN` | Any other exception, message truncated to 300 chars. |

A single malformed card is skipped (`continue`), not treated as a whole-search failure; a search only becomes `LAYOUT_CHANGED` if *no* card in the result set parsed.

## Observability and cost limits

- Evidence (`evidence_key`) is captured per search: a screenshot, falling back to raw HTML if screenshot capture fails (Lightpanda's CDP screenshot support is unverified).
- No AWS calls, no cost-bearing resources from this package alone.

## Test plan

### Unit
None yet committed on this branch — blocked on WP-00's pytest config landing here. All verification in this document was done via one-off scripts against the real, live sites and the real connector classes (not mocked), documented as "confirmed live" throughout.

### Contract
Not yet written: a connector contract suite that runs identically against Blinkit, Zepto, and the fixture connector (same assertions, parametrized by merchant) is still owed per the WP-04 POA entry.

### Integration
Not yet written: redirect/prompt-injection rejection tests, CAPTCHA/denial typed-error tests.

### End-to-end/manual
Every behavior claimed as "confirmed live" in this document was run against the real Blinkit/Zepto production sites during development (search, refresh, out-of-stock detection, concurrency, engine-thread-safety) — see git history on this branch for the exact verification commands.

## Acceptance criteria

- [x] Two live merchants return real, current prices for the tested locality.
- [x] Live and fixture results are never mixed in one registry/response.
- [x] A single merchant failure doesn't fail the whole search (partial results).
- [x] Domain allowlist enforced before navigation.
- [x] Deadline/timeout produces a typed error, not a hang or crash.
- [x] Concurrent search tasks (same or different merchant) don't crash the container.
- [x] `refresh()` implemented and correct on both connectors (Blinkit: fixed a real bug where the wrong product's data could be returned — the PDP's cart-item payload repeats for every "similar products" item in no guaranteed order, so matching must check the SKU, not take the first match).
- [x] `assess_fees()` returns a labeled `"estimated"` fee on both connectors, never `None`/silent.
- [x] Out-of-stock correctly detected on Blinkit (see above).
- [ ] Automated connector contract suite exists and passes.
- [ ] S3 evidence sink implemented.
- [ ] Cloud/Fargate trace proves both live sources work from the actual deployed environment (blocked on WP-01).
- [ ] Zepto's location is set to the requested pincode rather than its own IP-based default (open — see "Open questions").
- [x] `P3MerchantPortAdapter` written and its translation logic verified against P3's real fetched types (not import-checkable in this repo yet — see "P3 integration" above).

## Rollout, rollback, and fixture strategy

No deployment from this package alone. `build_registry(Mode.FIXTURE)` is the disclosed demo fallback if live connectors are blocked/broken at demo time; fixture and live are never selectable together and both paths share the same `Observation` shape.

## Open questions and decisions

- **Real (live-cart) fees on both connectors**: requires live cart mutation. Decision — never attempt it; return a labeled `"estimated"` fee from each merchant's published policy instead (see "Fee estimation"). Revisit only if accurate, current fees become a hard requirement.
- **Blinkit selector fragility**: extraction is scoped to `div[role="button"][id]` with Tailwind utility classes, since Blinkit ships no stable `data-testid` on search cards (Zepto does). More likely to break on a Blinkit frontend deploy than the Zepto connector. `scripts/spike_merchant.py` (or the ad-hoc scripts used during this work) should be re-run periodically to catch drift.
- **In-memory location cache survives only the container's lifetime.** Acceptable for one tested locality; would need externalizing (e.g., to the durable store WP-07 owns) if multiple localities or true cross-restart persistence become requirements.
- **Zepto's location is not explicitly set** — search results reflect Zepto's own IP-based default for the request's apparent location, not the requested `location.pincode`. Three real attempts to fix this were blocked, not two: Lightpanda can't click Zepto's location picker (it deliberately skips real CSS layout, so click targets have unreliable computed positions); investigating via real Chromium tripped Zepto's own bot defense (`x-amzn-waf-action: challenge`) on the very first request, confirmed **three separate times** across this project (most recently a single, deliberately non-repeated probe) — this is a persistent block on this traffic pattern, not a transient rate-limit that clears with time. The cross-engine cookie-transplant plan (do the click flow once on Chromium, feed the resulting cookies to Lightpanda) is not viable as a result: Chromium itself can't get past Zepto's homepage. Decision, 2026-09-17: **accept the gap for this demo's scope**, and stop further live probing against Zepto specifically rather than keep testing an actively-blocking site. The dev/test environment's own egress IP happens to geolocate to Delhi, postal 110001 — the exact tested locality — so the gap has been invisible in everything verified so far. This is dev-machine luck, not a fix: production (ECS Fargate, Mumbai-region egress) will not share this coincidence, so this must be revisited before the location claim can be trusted in a deployed environment. Solving it for real now looks like it needs either a paid unblocking vendor (discussed and set aside earlier) or a stealth-browser product (also discussed, with real skepticism about their actual effectiveness against production WAFs) — not something achievable with what's in this container today.
- **Evaluated and rejected as a third/alternative live merchant, 2026-09-17**:
  - **BigBasket** (`bigbasket.com`) — instant 403 "Access Denied" (Akamai Bot Manager) on the very first request, on both Lightpanda and real Chromium, across three URL variants and with an added referrer. No accumulated-traffic pattern needed, unlike Zepto — this is a harder block than anything else encountered in WP-04.
  - **Swiggy Instamart via `swiggy.com/instamart`** — instant AWS WAF challenge (`x-amzn-waf-action: challenge`) on the literal root domain, first request, both engines. Same conclusion as BigBasket.
  - **Swiggy Instamart via `instamart.in`** (a separate, dedicated domain — not the same as the swiggy.com path) — genuinely promising, no bot-defense wall encountered at all, and better-structured `data-testid` attributes than either Blinkit or Zepto. Got most of the way through the real location-selection flow on Chromium (typed a pincode, got real geocoded suggestions back), but the final confirm-click step was flaky/unresolved when work stopped. Lightpanda has the same click-layout limitation as everywhere else here, and Instamart hard-gates on location (no results at all without it, confirmed). **Decision: did not switch.** Instamart would require building an entire new connector from scratch and *still* solving the same unsolved interactive-location-click problem that's open on Zepto — no net time saved for a hackathon on a feature-freeze schedule. Worth revisiting later given the lack of a bot-defense wall, but not now.
