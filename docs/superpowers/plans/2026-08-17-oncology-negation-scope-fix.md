# Oncology Diagnosis Negation Scope Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct clause-local negation handling for deterministic oncology diagnosis matching.

**Architecture:** Split text into independent clauses, locate whitespace-tolerant literal diagnosis phrases, and inspect bounded context around each match for explicit negative patterns. Keep the evaluator API and output schema unchanged.

**Tech Stack:** Python 3.10+, `re`, `unicodedata`, pytest.

## Global Constraints

- Do not infer medical synonyms.
- Negation must not cross clause boundaries.
- Preserve explicit positive diagnosis matches.

---

### Task 1: Add clause-local negation matching

**Files:**
- Modify: `utils/diagnosis_eval.py`
- Test: `tests/oncology_runtime/test_diagnosis_eval.py`

**Interfaces:**
- Consumes: `evaluate_diagnosis_rules(agent_text, target_events)` existing inputs.
- Produces: The existing `label`, `score`, `matched`, and `missing` result schema.

- [x] **Step 1: Write failing regression tests**

Add the three required negative sentences and assert `incorrect`, score `0.0`,
and no matches. Add a cross-clause negative-then-positive case that must remain
`correct`.

- [x] **Step 2: Verify the regression tests fail**

Run: `pytest tests/oncology_runtime/test_diagnosis_eval.py -q`

Expected: the three new negative examples fail because they are currently
classified as `correct`.

- [x] **Step 3: Implement bounded clause-local matching**

Add clause splitting, whitespace-tolerant phrase matching, and bounded prefix
and suffix negative-pattern checks. Keep `_diagnostic_targets` and the public
result contract unchanged.

- [x] **Step 4: Verify focused tests pass**

Run: `pytest tests/oncology_runtime/test_diagnosis_eval.py -q`

Expected: all diagnosis evaluator tests pass.

- [x] **Step 5: Run the full oncology suite**

Run: `pytest tests/oncology_data tests/oncology_tools tests/oncology_generation tests/oncology_runtime -q`

Expected: all tests pass.

- [x] **Step 6: Commit the fix**

```bash
git add docs/superpowers/specs/2026-08-17-oncology-negation-scope-design.md docs/superpowers/plans/2026-08-17-oncology-negation-scope-fix.md utils/diagnosis_eval.py tests/oncology_runtime/test_diagnosis_eval.py
git commit -m "fix(eval): 修正诊断否定作用域"
```
