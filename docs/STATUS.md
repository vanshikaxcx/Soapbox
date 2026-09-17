# ProofPath package status

This is the canonical work-package status ledger. Update it only through the approved package workflow; links to implementation PRs/commits and verification evidence are added when available.

| WP | Owner | Dependency state | Specification | Package status | Implementation PR/commit | Verification | Blockers |
| --- | --- | --- | --- | --- | --- | --- | --- |
| WP-00 | P4 | None | [SPEC APPROVED](specs/WP-00-repository-toolchain-contract-baseline.md) | Implementing — Stage 7 | — | Stages 1–5 approved. Stage 6 implementation complete and locally verified: `security` command (Gitleaks, `pip-audit` ×2, `npm audit`) passes with zero findings; `.github/workflows/checks.yml` added with six required jobs, pinned action SHAs independently verified; Stage 6 reviewer sign-off and a real GitHub Actions run are still outstanding. Stage 7 command implementation complete: `verify-gate-a` (composes every non-mutating check, then asserts no tracked-file changes) and `verify-clean-clone` (rejects an already-dirty checkout, then runs `setup`+`verify-gate-a`) are implemented and PowerShell-syntax-verified; a smoke invocation in this environment correctly fail-fast'd on a Node version mismatch, confirming composition order works. Actual Windows/macOS clean-clone evidence runs (AC-00-08, AC-00-09) are queued (Windows: self; macOS: teammate) pending the first push of this branch. A pre-push skeleton audit against the WP-00 spec's required tree found and fixed 7 missing entries not caught by earlier stage sign-offs: root `AGENTS.md`, `workflows/`, `policies/`, `guidance/`, `web/src/pages/`, `web/src/components/`, `tests/live/`. This is the first commit/push of any WP-00 work. | Windows and macOS clean-clone evidence runs not yet performed (queued after this push); Stage 6 reviewer sign-off and first real CI run still pending; Stage 8 not yet started |
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
