# ProofPath agent instructions

This repository's full agent operating manual lives in [`CLAUDE.md`](CLAUDE.md): project context, the source-of-truth hierarchy, work-package workflow, ownership boundaries, architecture rules, coding/contract standards, non-negotiable transaction-safety invariants, security/privacy requirements, testing discipline, git/change discipline, scope-control procedure, and the task completion checklist.

Any AI coding agent operating in this repository (Claude Code, Codex, or otherwise) must read and follow `CLAUDE.md` in full before making any change. This file exists only so tools that specifically look for `AGENTS.md` by convention find a pointer to the single authoritative manual, avoiding two documents that could drift out of sync.
