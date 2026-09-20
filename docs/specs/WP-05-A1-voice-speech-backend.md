# WP-05-A1 — Real voice/speech backend: conversation, voice sessions, turn audio

Amendment to `docs/PROOFPATH-SPEC.md` sections 6/7 (data model, API) and the
WP-05 implementation split in `Final idea and archi/PROOFPATH-IMPLEMENTATION-POA.md`,
which assigns this specific slice to P4: *"P4 supplies presigned Transcribe/S3
and Polly adapter endpoints through reviewed ports... on P4's separate
supporting branch/PR if non-trivial."*

Owner: P4
Reviewers: P1 (consumes this contract from the web client), P3 (owns the
`Conversation`/`Turn`/`Question`/`VoiceSession` domain shapes and rules this
builds on, in `services/domain/conversation.py`)
Status: Implemented, tests green (application/domain/adapter layer only —
infra wiring is a deliberate follow-up, see "Rollout" below)
Depends on: WP-02 (merged — supplies the domain records/rules this uses
unchanged), WP-05 (merged — P1's UI currently runs against fixtures; this
gives it a real backend to call instead)

**Revision note (2026-09-20, during implementation):** WP-01's original
AC-01-02 adapters turned out to be the wrong shape to reuse, not just needing
a rebase. They were built for a one-shot liveness proof and discarded the
actual payload: `PollySynthesisAdapter` read `AudioStream` and reported only
its byte count, and `TranscribeStreamingAdapter` opened a real bidirectional
session but broke after one event, reporting only an event count — neither
returns anything a real feature could use. Worse, `TranscribeStreamingAdapter`
relays audio through this backend at all, which is not how the product spec's
own architecture works: section 4's "Browser <-> Transcribe" row has the
browser talking to AWS *directly* over a presigned WSS URL; this backend only
ever issues that URL. Built two new, narrower, correctly-shaped ports instead
(`TranscribeUrlSigner`, `SpeechSynthesizer` in
`services/application/ports/speech.py`) rather than force-fitting the
liveness-only ones. Consequence: **no `amazon-transcribe`/`awscrt` dependency
is needed at all** — presigning a WSS URL is the same `botocore` SigV4
query-signing primitive S3 presigned URLs already use, and Bedrock is out of
scope entirely (extraction is P2's `/tasks/extract`, unrelated to voice).

## Outcome and user value

Right now, WP-05's voice/photo/text UI is fully built and merged, but talks to
nothing real: it recorded 65 passing frontend tests against fixture data, and
the Bedrock/Polly/Transcribe adapter code that WP-01 wrote and proved
reachable against real AWS (real request IDs, real CloudTrail records — see
`docs/evidence/checkpoint.md`'s AC-01-02 section) was never actually merged
into `main`; it exists only on the stale `feat/wp-01-cloud-viability-checkpoint-p4`
branch. P1 flagged this exactly: *"Real voice transcription/synthesis — needs
P4's WP-01 adapters actually deployed and reachable, not just built/tested
locally."*

This package closes that gap: bring the three already-written, already-tested
adapters into `main`, and add the minimum real API surface — conversation
creation, turn recording, voice-session issuance/submission, and turn-audio
synthesis — for P1's existing UI to call instead of its fixtures.

## In scope

Implemented (`services/domain/errors.py`, `services/domain/canonical.py`,
`services/application/ports/speech.py`, `services/application/conversation.py`,
`services/adapters/aws/transcribe_presign.py`,
`services/adapters/aws/polly_synthesizer.py`, `services/adapters/audio_sink.py`,
plus fakes and unit tests):

- `ConversationUseCases`: create/read an owner-scoped `Conversation` (WP-02's
  shape, unchanged), record a `Turn` (text or a submitted voice session's
  final transcript). Does **not** call the extraction agent itself (that is
  WP-07's public route, tracked separately, out of scope here).
- `VoiceSessionUseCases`: open a session (validates owner + conversation
  version + active question via WP-02's binding rule, issues a real presigned
  Transcribe WSS URL), submit a transcript once (`may_submit` +
  `binding_is_current` gates, hashes the transcript with a new registered
  canonical tag `TAG_VOICE_TRANSCRIPT`), cancel. All against WP-02's
  `VoiceSession` shape and rules, unchanged.
- `TurnAudioService`: synthesize a turn's spoken caption via Polly once,
  cache the resulting `audio_key` on the `Turn`, serve a presigned playback
  URL on every subsequent call without re-synthesizing.
- `TranscribePresignAdapter`: real SigV4 query-signed presigned WSS URL for
  AWS Transcribe's streaming endpoint — no streaming client, no relay, no new
  dependency (`botocore.auth.SigV4QueryAuth`, already available via `boto3`).
- `PollySynthesizerAdapter`: real Polly `synthesize_speech`, returns the
  actual audio bytes.
- `LocalDiskAudioSink`/`S3AudioSink`: same dual local/S3 selection pattern as
  `services/merchants/evidence.py`'s `EvidenceSink`, plus a presigned GET URL
  for playback.
- Two new domain errors (`VoiceSessionExpired`, `VoiceSessionAlreadyResolved`)
  and their entries in `services/domain/api_test.py`'s public-API snapshot.

Not yet implemented, explicit next step: the `services/api/*` HTTP handler
class and its wiring into `contracts/openapi.yaml`/`infra/template.yaml` —
see "Rollout" below for why that's deliberately separate.

## Out of scope

- The extraction agent call itself (schema-bound text/image → structured
  list) — that is P2's `/tasks/extract` behind WP-07's still-missing public
  route. This package's `POST /conversations/{id}/turns` only records what
  it is given; it does not call the agent.
- `POST /conversations/{id}/questions/{qid}/answer` — question-answering
  flow; a separate, smaller follow-up once this lands, not blocking P1's
  immediate real-voice need.
- `POST /uploads` (photo intake) — same reasoning; photo extraction is
  already known-blocked on WP-07, so its upload endpoint is not urgent
  until that route exists.
- Any change to `services/domain/conversation.py`'s existing rules — WP-02
  owns them; this package only calls them.
- The `services/api/*` HTTP handler class and its `contracts/openapi.yaml`/
  `infra/template.yaml` wiring. Deliberately separate: `services/api/purchases.py`
  (WP-08/09) was already merged unwired for the same reason (it needs a real
  deployment cycle with P1's account to actually prove, not just more local
  code), and idempotency-key handling for these new mutations (a real,
  non-negotiable product rule per CLAUDE.md) deserves its own reviewed pass
  rather than being rushed in alongside this already-large application-layer
  change. Fast-follow, tracked here so it isn't lost.

## User flow and UI states

Unchanged from WP-05's existing UI states (loading/empty/partial/error while
recording, submitting, and awaiting synthesis) — P1's existing components
already implement these against the fixture client; this package's job is
only to give the typed API client something real to call so those same
states now reflect real latency/failure instead of a mock.

## API and event contracts

**Planned contract for the fast-follow HTTP handler** (see "Out of scope") —
not yet implemented; the application-use-case signatures already implemented
match this shape so the handler is a thin translation layer, not a redesign.
Response envelope, idempotency, and versioning follow the product spec's
existing conventions (`{data,request_id}` / `{error:{code,message,details},request_id}`,
`Idempotency-Key` + expected version on every mutation, `409`/`422`/`410`/`404`
per the standard rules already used by `services/api/purchases.py`).

```text
POST /conversations
  -> 202? No -- synchronous create, matches WP-02's Conversation shape (no
     job needed): {conversation_id, owner_id, version: 1}

GET /conversations/{id}
  -> {conversation_id, owner_id, active_question_id, version}

POST /conversations/{id}/turns
  body: {speaker, text, input_kind, reply_to_question_id?, audio_key?}
  -> {turn_id, conversation_id, ...} (Timestamped per WP-02's Turn)

POST /voice/sessions
  body: {conversation_id, conversation_version, question_id?, target_id?,
         target_version?, intent_id?, intent_revision?, language?}
  -> {voice_session_id, wss_url, expires_at}
  Owner-scoped; conversation_version must match the live Conversation's
  version at issuance time (stale binding rejected 409, matching WP-02's
  "cannot rebind to a newer question" rule).

POST /voice/sessions/{id}/submit
  body: {transcript}
  -> 200 {voice_session_id, status: "submitted"}
  -> 409 if already submitted/cancelled; 410 if expired (may_submit gate)

DELETE /voice/sessions/{id}
  -> 200 {voice_session_id, status: "cancelled"}

GET /conversations/{id}/turns/{tid}/audio
  -> 202 {job_id, status_url} if not yet synthesized
  -> 200 {playback_url} once ready (presigned GET, 5min per spec's existing
     S3 presigned-URL convention)
```

## Data model and state transitions

No new domain shapes. Uses `services/domain/conversation.py`'s `Conversation`,
`Turn`, `VoiceSession`, `VoiceSessionStatus` exactly as WP-02 defined them.
Persistence follows the existing single-table `AppTable` pattern:
`CONVERSATION#<id>` partition for `Conversation`/`Turn`/`Question` records,
`VOICE#<id>` for `VoiceSession` (per `docs/PROOFPATH-SPEC.md` section 6's
partition table). No schema change to `AppTable` itself.

## Components, ports, and dependency direction

`handler (services/api/conversations.py, voice.py) → application use case
(services/application/conversation.py) → domain (services/domain/conversation.py,
unchanged) → port (BedrockModel/TextToSpeech/TranscribeStreaming, StateStore)
→ adapter (services/adapters/aws/*, migrated from WP-01 unchanged)`.
Deterministic fake adapters for the three ports already exist as WP-01's
test doubles (migrated alongside); no new fixture-mode adapter needed beyond
what those tests already exercise.

## Security, privacy, and authorization

Owner derived from the validated Cognito access token, never from the
request body (matches `services/api/purchases.py`'s existing pattern via
`_reject_owner_in_body`-equivalent guard). Voice-session issuance requires a
real owner match on the target `Conversation`; cross-owner access is `404`,
not `403` (existing product rule). No raw audio, transcript content, or
Transcribe/Polly credentials in logs.

## Idempotency, concurrency, timeout, and retry behavior

`POST /conversations/{id}/turns` requires `Idempotency-Key`. Voice-session
submit is exactly-once by construction (`may_submit`'s status/hash guard, not
a separate idempotency key). Session expiry and conversation-version staleness
follow WP-02's existing `is_expired`/`binding_is_current` functions verbatim.

## Failure modes and user-visible errors

- Stale `conversation_version` at session issuance: `409`.
- Expired voice session on submit: `410`.
- Already-submitted/cancelled session resubmitted: `409`.
- Cross-owner conversation/turn access: `404`.
- Transcribe/Polly/Bedrock adapter failure: typed error surfaced through the
  existing `DomainError`→HTTP mapping (`services/api/responses.py`), not a
  bare 500 with no code.

## Observability and cost limits

Structured logs carry `request_id`, `conversation_id`, `voice_session_id`
(never transcript text or audio bytes). Bedrock/Polly/Transcribe IAM policies
scoped per AC-01-13's already-established pattern in `infra/template.yaml`
history (bare model ARN for Bedrock; documented `"*"` only for the two
Transcribe/Polly actions AWS does not support resource-level scoping on).

## Test plan

### Unit — implemented
- `tests/unit/test_transcribe_presign.py`: real SigV4 query-signed URL shape,
  scheme, host, path, and requested language/sample-rate — against
  hand-written fake credentials, no real AWS calls.
- `tests/unit/test_polly_synthesizer.py`: actual audio bytes/content-type
  returned (not a count), pinned voice/engine used, a `ClientError` recorded
  verbatim rather than raised.
- `tests/unit/test_audio_sink.py`: local-disk round trip, S3 `put_object`/
  `generate_presigned_url` call shape, and `build_audio_sink`'s bucket-env-var
  selection — same shape as the existing `test_evidence_sink.py` pair.
- `services/application/conversation_test.py`: conversation/turn ownership,
  session open/submit/cancel against every rule in "Failure modes" below,
  the conversation-moved-on rejection, and turn-audio's synthesize-once/
  cache-after behavior.

### Contract — deferred to the fast-follow HTTP handler
Owner derivation, cross-owner 404, stale-version 409, expired-session 410,
duplicate-submit 409, and idempotency-key replay/conflict are already
covered by the unit tests above at the use-case layer; a
`tests/contracts/test_conversation_voice_api_contract.py` exercising the same
behavior through the actual HTTP handler (once it exists) is part of that
follow-up PR, matching `test_checkpoint_api_contract.py`'s pattern.

### Integration
None beyond what the adapter unit tests already cover; a real deployed
invocation is Gate D evidence (see Acceptance criteria), not a CI-run
integration test (matches WP-01's own AC-01-02 approach — real AWS calls are
smoke-tested manually, not from CI).

### End-to-end/manual
P1 exercises the real voice flow from the deployed web app once P1 deploys
this package's Lambdas (see Rollout below) — replaces the fixture path she
is currently using, without any change to her component code beyond pointing
the typed client at the real base URL.

## Acceptance criteria

- AC-05-A1-01: **Met.** The two new real adapters (`TranscribePresignAdapter`,
  `PollySynthesizerAdapter`) and the audio sink pass their unit tests; the
  conversation/voice-session/turn-audio use cases pass theirs against every
  rule in "Failure modes" below. 1083/1083 tests pass repo-wide; mypy and
  ruff clean.
- AC-05-A1-02: **Deferred to the fast-follow PR** — `infra/template.yaml`
  Lambda wiring doesn't exist yet (see "Out of scope").
- AC-05-A1-03: **Deferred, needs P1's account** — a real deployed invocation
  producing a real Polly/Transcribe request ID, recorded in `docs/evidence/`.
  This is the actual fix for P1's blocker and can only happen once the
  fast-follow handler/infra PR lands and P1 deploys it.
- AC-05-A1-04: **Partially met** — every failure mode is covered at the
  use-case layer (unit tests); HTTP-layer contract tests land with the
  fast-follow handler.
- AC-05-A1-05: **Met.** No changes to `web/**`; WP-05's existing 65 frontend
  tests are untouched by this package.

## Rollout, rollback, and fixture strategy

P1's UI keeps its fixture-mode client as a fallback (`VITE_PROOFPATH_MODE`
per WP-01's precedent) until this package's real endpoints are confirmed
working end-to-end; switching the default is a follow-up, not part of this
package. Rollback: revert the PR; no destructive migration since `AppTable`'s
shape is unchanged.

## Open questions and decisions

- Should `POST /conversations/{id}/questions/{qid}/answer` land in this same
  package or a fast-follow? **Decision: fast-follow, out of scope here** —
  P1 did not flag question-answering as blocking her immediate need, and
  keeping this package small reduces review risk.
- Photo/text extraction and `POST /uploads` remain explicitly blocked on
  WP-07's public route, not on this package.
