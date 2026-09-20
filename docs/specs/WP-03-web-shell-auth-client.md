# WP-03 — Web shell, identity, typed API client, and shared async states

Owner: P1 — Vanshika — @vanshikaxcx
Reviewers: P3 — Aarushi — @a-for-aarushi (primary reviewer, per the approval matrix); specialist: P4 — Sparsh Jain — @SparshJain769 (auth/upload/presigned-URL changes)
Status: Draft
Depends on: WP-00

> Written after implementation, to unblock spec review without discarding working code (POA §3 permits the approved spec to remain on the implementation branch when review latency makes a separate docs PR impractical; it still requires an explicit spec review before merge, which this document requests). Nothing here should be read as already `Approved` — that requires P3's review.

## Outcome and user value

A mobile-first, authenticated web shell renders every shopper-facing route from typed, deterministic data, using one shared set of cards and one shared async-state model. This is the surface every later work package (WP-05 conversation/voice, WP-06 comparison, WP-08 approval, WP-09/10 checkout/recovery, WP-11 integrated journey) plugs into instead of inventing its own routing, auth, or loading/error handling.

## In scope

- Route hierarchy: `/`, `/searches/:id`, `/purchases/:id/approve`, `/purchases/:id`, `/cases/:id`, `/demo`, and a 404/not-found fallback.
- Cognito authorization-code PKCE lifecycle: login redirect, callback exchange, token refresh, logout, and a distinct `expired` (refresh failed) vs `unauthenticated` (never signed in) status.
- Typed API client integration: wraps WP-00's `ApiClient`/`ApiError`/idempotency/polling primitives into route-level state; does not change their contracts.
- One `AsyncState<T>` union and an `AsyncStateView` dispatcher covering loading/empty/partial/success/stale/expired/error, backed by a `useAsyncResource` hook.
- Shared card primitives: conversation, basket, quote (with the sole `Approve simulated ₹X` control), progress, evidence, recovery, notice (incl. the mandatory simulated-checkout label), error, and purchase-status.
- Diagnostic mode (`?diagnostic=1`) surfacing `request_id` traces from the client.
- Mobile-first responsive layout, keyboard/focus/a11y baseline (skip link, landmarks, visible focus, `aria-live`/`role="alert"`).
- A deterministic component harness at `/demo` (fixture data + an async-state picker) standing in for Storybook.

## Out of scope

- Real Search/Purchase/Case/Quote data and endpoints — those schemas belong to WP-02/WP-06/WP-08/WP-09/WP-10 and aren't approved yet. This package uses local, clearly-labelled fixture types (`components/cards/types.ts`) that a later WP maps its real contract onto; the card components themselves don't change when that happens.
- Voice, photo, and usual-basket intake (WP-05) — that package's independent slice (conversation state, mic/photo/usual-basket UI skeletons) has since landed on its own branch (`feat/wp-05-conversation-voice-p1`), built on top of this one; it is not part of this PR.
- Real merchant search/comparison/repair logic (WP-06).
- Real quote approval side effects (WP-08) — the approve control exists and is the only call site, but it doesn't yet call a contracted endpoint.
- Real checkout/callback/recovery data (WP-09/WP-10).
- Operator scenario controls on `/demo` (WP-11 extends this route; here it's only the component harness).
- An actual deployed Cognito user pool (WP-01) — this package only implements the client-side PKCE flow against whatever pool/client WP-01 provisions.
- A public marketing/landing page. `/` behaves like every other route: unauthenticated, it redirects to the Cognito hosted UI via `AuthBoundary`, same as `/searches/:id` or `/demo` — no separate signed-out page exists.
- A dev-only auth bypass. There is no environment flag that skips Cognito; every path exercises the real PKCE flow (against injected deps in tests, and against the real hosted-UI domain manually — see Test plan).

## User flow and UI states

- **Unauthenticated visitor:** any route — including `/` — redirects to the Cognito hosted UI (`AuthBoundary`); on return, the original path is restored.
- **Expired session:** distinguished from a fresh unauthenticated visit (`status: "expired"` vs `"unauthenticated"`) so a later WP can show "your session ended" copy before the same redirect.
- **Every async surface:** loading (spinner + `aria-live="polite"`), empty, partial (some but not all sources reported — e.g. one merchant missing), success, stale (last-known data shown with a refresh notice, for a 409 stale_version/conflict), expired (410, no retry offered), error (retry offered only when `ApiError.retryable`).
- **Approval:** the quote card's button is the only element that can invoke approval; it disables itself and shows "Approving…" for the duration of the call so a double-tap cannot fire twice.
- **Purchase status:** payment/order/refund rendered as three independent fields, never collapsed into one status; an ambiguous combination (payment succeeded, order unknown) links to the case page.
- **Recovery:** read-only card; no button on it can create a payment, order, or refund.

## API and event contracts

No new contract. Consumes WP-00's `contracts/openapi.yaml` (`/health`, error envelope, `JobStatus` shape) unchanged via the already-committed `ApiClient`. `ServerErrorCode` is typed as the open, pattern-constrained string the real contract declares (`^[a-z][a-z0-9_]*$`), not a closed enum — an unrecognized code falls back to `kindForFailure`'s status-based mapping rather than a type error, since each later WP mints its own codes independently. Adds no paths/schemas of its own — Search/Purchase/Case/Quote will be added by their owning WPs and mapped onto the existing card props at that point.

## Data model and state transitions

Owns no persisted state. Client-side only:

- `AuthStatus`: `loading | unauthenticated | expired | authenticated` (see `auth/AuthContext.tsx`).
- `AsyncState<T>`: `idle | loading | empty | partial | success | stale | expired | error` (see `state/asyncState.ts`).
- Session tokens (`StoredTokens`) live in `sessionStorage`, not `localStorage`, for the same reason as the WP-00 idempotency-key store: must survive a reload mid-session, must not leak into a later session.

## Components, ports, and dependency direction

```
route (page component) → useAsyncResource/useAuth → ApiClient/AuthContext → transport/Cognito token endpoint
```

- `auth/` — PKCE primitives, Cognito token/authorize/logout URL builders, `AuthContext`/`AuthProvider`/`AuthBoundary`. All network/crypto/storage/redirect calls are injectable (`AuthProviderDeps`) so tests never touch real Cognito or `window.location`.
- `api/ApiProvider.tsx` — the single `ApiClient` instance for the app; feeds it the auth token getter, collects diagnostic traces. No route constructs its own client.
- `state/` — `AsyncState` type + `useAsyncResource`, the one bridge from the typed client/poller to route state.
- `components/cards/` — presentation only; typed against local fixture shapes (`cards/types.ts`), not against any specific WP's contract, so swapping fixtures for real data later doesn't touch the components.
- `components/async/AsyncStateView.tsx` — the single dispatch point every route uses instead of ad hoc loading/error booleans.
- `pages/` — one page component per route (named `pages/`, not `routes/`, matching WP-00's own scaffold placeholder — `pages/README.md` — rather than inventing a second convention); each wires fixtures (or, for `/`, a real `/health` call) through `AsyncStateView` into cards.
- `fixtures/` — deterministic data and a `useFixtureAsyncState` hook standing in for a second backend.

No route imports Cognito or `fetch` directly; everything goes through `useAuth()`/`useApiClient()`.

## Security, privacy, and authorization

- Server derives owner identity from the access token; this package never invents or trusts a client-supplied owner ID.
- Tokens live in `sessionStorage`, cleared on logout and on an unrecoverable refresh failure.
- PKCE `state` is single-use (`consumePendingAuthorization` deletes it on read) and checked against the callback's `state` param before any token exchange — a callback with a non-matching or missing pending record fails closed to `unauthenticated` without calling the token endpoint.
- The approval control is the sole call site for approval; no conversational, voice, or model-driven path in this package can reach it (there is no such path in this package at all — WP-05/WP-08 must preserve this when they integrate; WP-05's own `useConversation` hook, now built on top of this branch, confirms this by construction — it has no import of anything approval-related).
- No secrets, tokens, or PII are logged; diagnostic mode surfaces only `method`, `path`, `status`, `request_id`, `durationMs`.
- No dev-only bypass exists anywhere in this package — every authenticated path is reachable only through the real Cognito PKCE flow.

## Idempotency, concurrency, timeout, and retry behavior

- `useAsyncResource` cancels the previous fetch on route change/retry (`AbortController`), so a superseded response can't overwrite a newer one.
- Token refresh is de-duplicated: concurrent `getAccessToken()` calls share one in-flight refresh rather than issuing parallel refresh-token requests.
- Retry is only offered for `ApiError.retryable` kinds (network/timeout/rate_limited/server); `expired`/`forbidden`/etc. render without a retry action.
- The approve control disables itself for the duration of its call, preventing a double-submit from this UI (the actual idempotency-key/expected-version enforcement is WP-08's server-side job).

## Failure modes and user-visible errors

Mapped once in `ErrorCard`'s `MESSAGE_BY_KIND`, covering every `ApiErrorKind` (validation, conflict, stale_version, expired, not_found, unauthorized, forbidden, rate_limited, server, network, timeout, canceled, malformed) with plain-language copy. `NotFoundPage` deliberately uses the same copy for "doesn't exist" and "exists but not yours," matching the server's concealment of that distinction.

## Observability and cost limits

Diagnostic mode is opt-in via `?diagnostic=1` and shown to nobody by default. No cost-bearing calls beyond the existing `/health` check on `/`.

## Test plan

### Unit
- `auth/pkce.test.ts` — verifier/challenge determinism and URL-safety, pending-authorization single-use semantics.
- `auth/tokens.test.ts` — expiry-skew boundary behavior.
- `state` — covered indirectly through `AsyncStateView.test.tsx` (all seven states render their contracted output).

### Contract
- N/A — no new API contract in this package.

### Integration
- `auth/AuthContext.test.tsx` — unauthenticated-by-default, valid-session-resumes-authenticated, expired-refresh-fails-to-`expired`-not-`unauthenticated`, successful callback exchange navigates to the original `returnTo`, mismatched-state callback fails closed without calling the token endpoint, `login()` redirects to the real Cognito URL shape with PKCE params, `logout()` clears the session and redirects to the real Cognito logout URL.
- `auth/AuthBoundary.test.tsx` — redirects instead of rendering protected content when unauthenticated; renders children once authenticated.
- `pages/router.test.tsx` — unmatched route renders `NotFoundPage`; `/demo` and `/cases/:id` render independent of shopper routes.
- `components/cards/QuoteCard.test.tsx` — button labelled with the exact simulated total, calls `onApprove` exactly once even under a double-click, always shows the simulated-checkout label.
- `App.test.tsx` — authenticated shell renders skip link/nav/heading; diagnostic bar absent by default; unauthenticated visit — including `/` — redirects instead of rendering shopper routes.

### End-to-end/manual
Manually verified in a running dev server with a real, seeded authenticated session (real Cognito redirect confirmed separately against the real hosted-UI domain, which returned a real "Invalid client id" error — proving the PKCE URL construction is correct against an actual Cognito endpoint):
- Every route renders its intended card(s); `/purchases/:id/approve` → click approve → navigates to `/purchases/:id` → link to `/cases/:id` all work.
- `ErrorCard` renders with a working retry when the (fixture) API base URL is unreachable.
- `/demo`'s state picker correctly re-renders the stale/error/etc. states via real keyboard interaction (arrow keys + Enter on the `<select>`), including the visible focus ring.
- Mobile viewport (375×812): progress/basket cards stack in one column, badges and text remain legible.
- Keyboard-only: first `Tab` reveals the skip link with a visible focus outline.
- Unauthenticated `/` redirects to the real Cognito hosted-UI domain — confirmed there is no signed-out landing state to fall through to.

Not yet run: a real Cognito login (no user pool deployed — WP-01), and anything requiring a real backend for `/health` beyond the unreachable-fixture-URL error path.

## Acceptance criteria

- [x] Routes `/`, `/searches/:id`, `/purchases/:id/approve`, `/purchases/:id`, `/cases/:id`, `/demo` all render.
- [x] Cognito PKCE login/callback/refresh/logout implemented and unit/integration tested against injected deps.
- [x] `expired` is distinguished from `unauthenticated`.
- [x] Typed client wired through one `ApiProvider`; no route constructs its own client or copies server state into a second store.
- [x] Every async surface implements loading/empty/partial/error/stale/expired via one shared dispatcher.
- [x] Shared cards (conversation/basket/quote/progress/evidence/recovery/notice/error) exist and are reused across routes.
- [x] Keyboard-only path, visible focus, and a responsive mobile layout are manually verified.
- [x] Deterministic fixtures/component harness exist; no second backend was invented.
- [x] `npm run typecheck`, `npm run lint`, `npm test` all pass (10 files / 65 tests).
- [x] No dev-only auth bypass and no public landing page exist in this package — `/` is authenticated-or-redirect like every other route.
- [x] Toolchain matches the real WP-00 baseline exactly (React 19.2.8, Vite 8.3.0, ESLint 10.10.0, Vitest 4.1.11, TypeScript 5.9.3) and carries no known-vulnerable dependency (`npm audit`: 0 vulnerabilities).
- [ ] Authenticated health call against the **deployed** API — blocked on WP-01 provisioning a real Cognito pool; verified instead against a real Cognito domain's authorize/error response and against the fixture-unreachable error path.

## Rollout, rollback, and fixture strategy

No deployment in this package. `web/.env.example` documents the Cognito/API env vars WP-01's real values will fill in; nothing here hardcodes an environment. If WP-02/06/08/09/10 land contracts that don't match this package's fixture shapes, the mapping change is localized to each route's data-fetching call, not to the shared cards.

## Open questions and decisions

- Whether to add a real Storybook: **decision — skipped in favor of the `/demo` component harness**, to avoid a second build/tooling surface in a three-day window; revisit if `/demo` stops being sufficient for review.
- Exact Cognito scopes/claims: deferred to WP-01's actual user-pool configuration; `cognitoConfig.ts` defaults to `openid email` and reads everything else from env.
- Whether to add a public marketing/landing page and a local dev-only auth bypass: **decision — neither is part of WP-03.** Both were explored on an earlier draft of this branch and explicitly removed after review, to keep this package's scope to exactly what the spec above lists; a landing page, if wanted, is a separate, explicitly-scoped follow-up.
