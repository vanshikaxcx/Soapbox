# WP-05 (P2's slice) — Schema-bound text/image extraction contract

Owner: P2
Reviewers: P1 (extraction contract shape, since this is what their UI renders
as "here's what I understood"; P2 reviews P1's WP-05 UX contract changes in
return), P3 (domain schema usage), P4 (Bedrock model availability, WP-01)
Status: Implementing
Depends on: WP-02 (`Item`/`Flexibility`/`Quantity` schema, P3), WP-04
(`services.merchants.models.Mode`, live/fixture isolation pattern, P2's own
branch)

This document covers only P2's owned piece of WP-05, per POA line 516: "P2
supplies schema-bound text/image extraction callable through the agent
contract, on P2's own branch." The rest of WP-05 (mic/photo capture UI,
usual-basket UI, AWS Transcribe/S3/Polly adapters) is P1's and P4's scope and
is documented separately, if at all yet — `docs/STATUS.md` lists WP-05 as
`Draft`, owned by P1, with no spec file of its own.

## Outcome and user value

A shopper's spoken transcript or a photo of a list becomes a set of
schema-bound `Item`s — the same `Item` WP-02 defines and WP-06 already
consumes — so P1's UI can show "here's what I understood" for confirmation,
instead of inventing its own parsing. Anything the extractor can't
confidently resolve comes back as an honest, reasoned gap, never a guess.

## In scope

- `POST /tasks/extract` on the agent's FastAPI app (`services/agent/main.py`),
  the same auth/JSON shape as WP-06's `/tasks/search` and `/tasks/compare`.
- An `Extractor` port (`services/extraction/base.py`) with two operations —
  `extract_from_text`, `extract_from_image` — mirroring how
  `services.merchants.base.Merchant` is P2's WP-04 port.
- A fake/dev backend (`services/extraction/fake.py`): a regex heuristic over
  transcript text, and a content-hash-keyed fixture table for images, for
  local dev and tests where no live model call is available or wanted.
- A real backend (`services/extraction/bedrock.py`), gated on
  `services.agent.config.BEDROCK_MODEL_ID`.
- `run_extraction` orchestration (`services/agent/extract.py`): converts the
  port's raw candidates into WP-02 `Item`s (with a generated `item_id`, a
  canonical `Quantity`, and `Flexibility.EXACT_ONLY` as the domain's own
  default — never a guessed hard attribute or a guessed flexibility), applies
  the `MAX_ITEMS = 4` cap, and reports everything else as an honest
  `UnresolvedExtraction`.

## Out of scope

- Any UI: microphone capture, photo upload widget, or the "here's what I
  understood" confirmation screen itself (P1).
- AWS Transcribe (speech-to-text) and S3/Polly plumbing (P4) — this endpoint
  receives an already-transcribed string, never audio.
- Assembling a full `Intent`: `owner_id`, `location`, `budget_paise`, and
  `delivery_constraint` don't come from a transcript or a photo of a grocery
  list, and this endpoint never invents them. P1's UI supplies those.
- Usual-basket construction/persistence (P1/WP-07).
- Pinning the real `BEDROCK_MODEL_ID` value (WP-01's cloud checkpoint).
- Structured hard-attribute extraction beyond what a shopper's own words
  state explicitly (e.g. "organic milk" → `hard_attributes={"type": "organic"}`
  is in scope; inferring an attribute the shopper never said is not — same
  absence-is-never-assent rule WP-02/WP-06 already apply).

## Components, ports, and dependency direction

```
FastAPI /tasks/extract -> run_extraction (services.agent.extract)
    -> services.extraction.registry.build_extractor(mode)  (P2's own port)
    -> services.domain.{intent,units,ids}  (WP-02 schema, called only)
```

Lives in `services.agent`, same reasoning as WP-06's `compare.py`:
`services.application` may depend on nothing but the domain and the standard
library (`application/boundaries_test.py`), and this module calls P2's own
extraction backends directly.

`services/extraction/` is a new top-level package, structured like
`services/merchants/`: `base.py` (port), one file per backend
(`fake.py`, `bedrock.py`), `registry.py` (`build_extractor(Mode)`). It reuses
`services.merchants.models.Mode` rather than defining a second live/fixture
enum — extraction backend selection is exactly the same choice WP-04 already
modeled.

`UnresolvedExtraction` and `ExtractionOutcome` are agent-owned response
Records defined in `services/agent/extract.py`, not `services.domain` — same
precedent as WP-06's `UnresolvedItem`/`MerchantResult`/`ComparisonOutcome`:
these are this endpoint's own contract shape, not a WP-02 domain rule.

## API and event contracts

`POST /tasks/extract`
```
{
  "transcript": str | null,
  "image_base64": str | null,
  "image_mime_type": str | null,
  "mode": "live" | "fixture"
}
-> {
  "items": [<Item, as Item.model_dump(mode="json") produces it>, ...],
  "unresolved": [<UnresolvedExtraction, ...>]
}
```
Exactly one of `transcript` / `image_base64` must be set — `400` otherwise.
`image_mime_type` is required whenever `image_base64` is set.

`UnresolvedExtraction`: `raw_fragment: str, reason_code: str, reason_detail:
str | None`. `reason_code` is one of:

| `reason_code` | When |
|---|---|
| `no_quantity_detected` | An item name was recognised but no parsable quantity/unit accompanied it. |
| `ambiguous_item` | More than one plausible reading exists and none is more likely than another. |
| `item_limit_exceeded` | The item was recognised (and would otherwise resolve) but the request already has `MAX_ITEMS = 4` resolved items. |
| `extraction_unavailable` | `mode="live"` was requested but `BEDROCK_MODEL_ID` is unset (WP-01 not yet run), or `mode="fixture"` and the image doesn't match any known fixture. |
| `no_items_detected` | Nothing resembling a shopping item was found in the input at all. |

Deliberately a plain string, not a raw exception — `UnresolvedExtraction` is
a pydantic `Record` and must round-trip to JSON, same reasoning as WP-06's
`UnresolvedItem`.

Response `items` never carry a guessed `hard_attributes` entry or a guessed
`flexibility` beyond the domain's own `EXACT_ONLY` default — a wrong guess
here would let a shopper's confirmation screen show a fabricated constraint
they never stated.

## Idempotency, concurrency, timeout, and retry behavior

- Single-shot: one request, one extraction call, no retry loop and no
  idempotency key (this package has no durable store; same reasoning as
  WP-06).
- The real backend is subject to a per-request deadline
  (`ITEM_FETCH_DEADLINE_SECONDS`, reused from `services.agent.config` —
  extraction is a single call, not per-item, so no new constant is needed).
- No concurrency: one transcript or one image per call, unlike WP-06's
  per-(merchant,item) fan-out — there's exactly one input to interpret.

## Failure modes and user-visible errors

- Malformed request (neither or both of `transcript`/`image_base64` set, or
  `image_base64` set without `image_mime_type`): `400`, request rejected
  before calling the extractor.
- Backend unavailable (`mode="live"` with no `BEDROCK_MODEL_ID`, or an
  unmatched fixture image): never a `5xx` — the whole request still
  succeeds, reported as a single `unresolved` entry with
  `reason_code="extraction_unavailable"`. Mirrors WP-06's rule that a
  merchant/backend failure is partial coverage, not a failed run.
- Over-limit items: never dropped silently — reported as `unresolved` with
  `reason_code="item_limit_exceeded"`.

## Observability and cost limits

- No AWS calls from the fake backend. The real backend is a single Bedrock
  invocation per request once `BEDROCK_MODEL_ID` is set (WP-01) — cost is one
  model call per shopper request, not per item.
- No persistence: the response lives only in the HTTP round-trip, same as
  WP-06's `ComparisonOutcome` today (WP-07 owns durable storage for both).

## Test plan

### Unit
`services/extraction/fake_test.py` — the heuristic text extractor against a
table of transcripts (quantity+unit+name parsed correctly; a bare item name
alone yields `no_quantity_detected`; an unparseable transcript yields
`no_items_detected`), and the fixture-keyed image backend (a known fixture's
hash resolves; any other image yields `extraction_unavailable`).

`services/agent/extract_test.py` — orchestration against the fake backend:
correct `Item` construction (canonical `Quantity`, generated `item_id`,
`EXACT_ONLY` default), the `MAX_ITEMS` overflow case, `mode="live"` with no
`BEDROCK_MODEL_ID` set surfacing `extraction_unavailable` rather than
raising, and the malformed-request `400` cases.

### Contract/integration
`services/agent/main_test.py` additions — `/tasks/extract` via the real
FastAPI app and `TestClient`, fixture mode, bearer-token auth gating (same
pattern as the other two task endpoints).

### Not yet run
Against a real Bedrock call (blocked on WP-01 setting `BEDROCK_MODEL_ID`) —
same "not yet run" honesty note WP-06 gave for live Blinkit/Zepto
verification. Expected to work once wired, since `bedrock.py` implements the
same `Extractor` port the fake backend already satisfies and is exercised
against.

## Acceptance criteria

- [x] `POST /tasks/extract` accepts a transcript or an image and returns
      `items`/`unresolved` in the shape above.
- [x] Extraction never invents a `hard_attributes` entry or a `flexibility`
      beyond the domain default.
- [x] `MAX_ITEMS` overflow is reported, never silently dropped.
- [x] A missing `BEDROCK_MODEL_ID` (live mode) or an unmatched fixture image
      degrades to a reported `unresolved` entry, never a failed request.
- [x] Auth-gated the same way as `/tasks/search` and `/tasks/compare`.
- [ ] Verified against a real Bedrock call (blocked on WP-01).
- [ ] Consumed by P1's WP-05 UI (P1's scope, not started as of this writing).

## Open questions and decisions

- **The fake text extractor is a regex heuristic**, not a real NLU model —
  good enough to prove the contract shape and unblock P1's UI work, not a
  substitute for the real backend. Revisit only if the demo specifically
  needs the fake backend to handle harder phrasing than the current test
  table covers.
- **No cross-checking against WP-02's `check_substitution`/hard-attribute
  rules happens at extraction time** — an extracted `hard_attributes` entry
  is exactly what the shopper said, unvalidated against any catalog. WP-06's
  matching is what discovers whether that attribute is satisfiable; this
  endpoint's job stops at "what did the shopper ask for," not "can it be
  bought."
- **`BEDROCK_MODEL_ID` timing** — this package is ready to use it the moment
  WP-01 sets it, with no code change, but that also means P1's UI can only
  demo the *fake*-backend path until then. Flagging for whoever scripts the
  WP-05 demo, same as WP-06's live-comparison-language flag.
