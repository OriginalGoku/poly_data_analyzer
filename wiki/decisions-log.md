# Decisions Log
<!-- Auto-maintained by /execute-plan and /retrospective. Do not edit manually. -->

## [retrospective: Plotly add_vline fails on datetime subplot axes] 2026-04-09
**Salience:** HIGH
**Session:** freeform
**Modules:** charts.py
**Corrections:** none
**Reversals:** none
**Discoveries:** Plotly's `add_vline` with `annotation_text` silently fails or mispositions on subplots with datetime x-axes. Had to replace with explicit `add_shape` (vertical line) + `add_annotation` (label) calls to get correct placement.
**Lesson:** When drawing vertical reference lines on Plotly subplots with datetime axes, skip `add_vline`/`add_hline` convenience methods and use `add_shape` + `add_annotation` directly — the convenience wrappers have known issues with datetime positioning on multi-row subplot figures.

---

## [plan_file: NBA_Game_Visualizer_Plan.md] Executed 2026-04-09
**Mode:** sequential (3 waves) | **Result:** All 3 steps completed
**PRs:** N/A (sequential)
**Notable:** Plotly `add_vline` with `annotation_text` crashes on datetime subplot axes — switched to `add_shape` + `add_annotation`. Otherwise execution matched plan.

---
