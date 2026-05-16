## Runtime evaluations

### 2026-05-16
**Session context:** /brainstorm invoked on `plans/NBA_Tipoff_Page_Performance_Plan/technical-plan.md`; Deep mode, 2 rounds with Codex, LM Studio reachable, both probes ran.
**Conformance gaps:**
- [Stop-rule compliance / chain-contract correctness] Step 2 launch checklist violated: `SKILL.md:158-163` requires 4 Bash calls (Codex + reachability + 2 probes) batched in one response message. Initial response message contained only 2 calls (Codex Round 1 + reachability curl); both probes were launched late, alongside Codex Round 2. Deviation token `[deviation: late-probe-fallback]` was logged in the trace per `SKILL.md:171`, but the documented escape hatch is "for recovery only" — the batched launch is the intended path. — Severity: P1
- [Guardrails — two-agent concealment] `SKILL.md:334-335` and `:395` require the unified response to never mention "Codex, 'the reviewer', 'the second opinion', or any phrasing that reveals a two-agent process." Synthesis lead-ins violated this twice: `"Codex's Round 1 surfaced grounded concerns"` and `"Codex Round 2 surfaced a decisive memory estimate"`. — Severity: P1

**Behavioral defects:**
- none observed.

**Edge cases observed:**
- Plan lives at `plans/NBA_Tipoff_Page_Performance_Plan/technical-plan.md` (not `features/<slug>/`) -> sidecar reminder was improvised to `plans/<name>/brainstorm.md` -> SKILL.md `:407-410` sidecar resolution only documents the `features/<slug>/` case and "free-form (ask user)"; the `plans/` namespace is not codified. Suggested: add a `plans/<name>/technical-plan.md` resolution clause alongside the `features/` clause.
- Repo index returned `unconfigured` -> orchestrator correctly omitted `## Repo Context` per `SKILL.md:87` -> no improvement needed.

**Ecosystem friction:**
- Sidecar/handoff schema couples to `features/<slug>/` (`SKILL.md:373, :405, :409`), but this repo organizes plans under `plans/<name>/`. Repo-grounding handoff therefore silent-skipped (correct per skip exception `:381`) even though a `plans/` slug effectively existed. The skill lacks a parallel `plans/` handoff target. — Severity: P2

**Suggested fixes:**
- `~/.claude/skills/brainstorm/SKILL.md:158-163` -> tighten orchestrator-side reminder: include a one-line preflight checklist Claude should mentally tick before sending the first response message ("4 calls batched?"). Current text is descriptive; failure mode shows it's not salient enough.
- `~/.claude/skills/brainstorm/SKILL.md:334-335` -> add a worked negative-example block (`❌ "Codex Round 1 surfaced..." → ✅ "Round 1 surfaced..."` or `"Verification surfaced…"`) since the prohibition was violated despite being stated twice.
- `~/.claude/skills/brainstorm/SKILL.md:407-410` -> extend sidecar resolution with a third clause: "Subject resolves to a plan path (`plans/<name>/technical-plan.md`): write `plans/<name>/brainstorm.md`." Mirror the same logic for the repo-grounding handoff at `:373`.
