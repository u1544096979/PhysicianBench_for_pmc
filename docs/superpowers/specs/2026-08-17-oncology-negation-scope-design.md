# Oncology Diagnosis Negation Scope Design

## Goal

Prevent negated, excluded, or low-likelihood diagnoses from being counted as
literal diagnosis matches while preserving explicit positive diagnoses in a
later clause.

## Design

Split agent output into clauses at sentence punctuation, commas, newlines, and
Chinese or English contrast conjunctions. Match diagnosis phrases within each
clause while allowing whitespace differences. For each match, inspect only a
bounded prefix and suffix in that clause for Chinese and English negation,
exclusion, negative-result, and low-likelihood patterns.

This keeps negation local: a negative statement in one clause cannot suppress a
positive diagnosis in a later clause. The deterministic evaluator continues to
use literal target values and does not introduce medical synonym inference.

## Verification

Regression tests cover the required Chinese and English negative forms, suffix
low-likelihood forms, an explicit positive diagnosis after a negative clause,
and the existing positive diagnosis behavior. The full oncology suite remains
the completion gate.
