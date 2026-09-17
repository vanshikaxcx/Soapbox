# ProofPath package status

This is the canonical work-package status ledger. Update it only through the approved package workflow; links to implementation PRs/commits and verification evidence are added when available.

| WP | Owner | Dependency state | Specification | Package status | Implementation PR/commit | Verification | Blockers |
| --- | --- | --- | --- | --- | --- | --- | --- |
| WP-00 | P4 | None | [SPEC APPROVED](specs/WP-00-repository-toolchain-contract-baseline.md) | Implementing — Stage 7 complete | — | Stages 1–5 approved. Stage 6 implementation complete and locally verified (Stage 6 reviewer sign-off and a real GitHub Actions run still outstanding). Stage 7 fully complete: **AC-00-08 (Windows) and AC-00-09 (macOS) both PASSED** on 2026-09-17 — `verify-clean-clone` ran a full green Gate A pass from a genuinely fresh clone on both platforms (Windows: `2 passed (3.9m)`; macOS: `2 passed (3.2m)`, `EXIT_CODE=0`). Getting there surfaced and fixed 8 real defects invisible on the original development machine: CRLF/`.gitattributes` gap, missing AWS region scoping across 3 SAM call sites, a redundant `--` breaking 4 Prettier invocations, an operator-machine Docker credential-store issue, an under-provisioned cold-start timeout (raised to 20 minutes), a missing/broken python.org install path for Python 3.12.14 on every platform, and transient `public.ecr.aws` pull flakiness on both Windows and macOS (resolved by retry, not a code defect). One explicit decision recorded rather than silently resolved: the Lambda function's architecture stays at its implicit `x86_64` default for now; the real AWS deployment architecture is deferred to WP-01. Full detail in `docs/evidence/gate-a-clean-clone.md` and `LEARNING.md`. A pre-push skeleton audit also found and fixed 7 missing required-skeleton entries not caught by earlier stage sign-offs (`AGENTS.md`, `workflows/`, `policies/`, `guidance/`, `web/src/pages/`, `web/src/components/`, `tests/live/`). | Stage 6 reviewer sign-off and first real CI run still pending; Stage 8 (final scope/diff review) not yet started |
| WP-01 | P4 | Blocked by WP-00 | Not yet created | Draft | — | Not started | WP-00 |
| WP-02 | P3 | Blocked by WP-00 contracts | Not yet created | Draft | — | Not started | WP-00 |
| WP-03 | P1 | Blocked by WP-00 | Not yet created | Draft | — | Not started | WP-00 |
| WP-04 | P2 | Blocked by WP-00; checkpoint access | Not yet created | Draft | — | Not started | WP-00, WP-01 access gate |
| WP-05 | P1 | Blocked by WP-03; extraction contract | Not yet created | Draft | — | Not started | WP-03 |
| WP-06 | P2 | Blocked by WP-02, WP-04 | Not yet created | Draft | — | Not started | WP-02, WP-04 |
| WP-07 | P4 | Blocked by WP-01, WP-02 | Not yet created | Draft | — | Not started | WP-01, WP-02 |
| WP-08 | P3 | Blocked by WP-02, WP-06, WP-07 | Not yet created | Draft | — | Not started | WP-02, WP-06, WP-07 |
| WP-09 | P3 | Blocked by WP-07, WP-08 | Not yet created | Draft | — | Not started | WP-07, WP-08 |
| WP-10 | P4 | Blocked by WP-09 | Not yet created | Draft | — | Not started | WP-09 |
| WP-11 | P1 | Blocked by WP-05, WP-06, WP-08–10 | Not yet created | Draft | — | Not started | WP-05, WP-06, WP-08–10 |
| WP-12 | P4 | Blocked by all prior packages | Not yet created | Draft | — | Not started | Prior WPs |
