export const SPECIALTIES = [
  { key: "cardio", label: "Cardiology", n: 6 },
  { key: "endo", label: "Endocrinology", n: 13 },
  { key: "gi", label: "GI & Hepatology", n: 14 },
  { key: "id", label: "Immunol & ID", n: 12 },
  { key: "psych", label: "Psych / Neuro", n: 16 },
  { key: "heme", label: "Hem / Onc", n: 13 },
  { key: "neph", label: "Neph / Urol", n: 8 },
  { key: "pulm", label: "Pulm & Other", n: 18 },
];

export const TASK_TYPES = [
  { key: "diag", label: "Diagnosis & Interpretation", n: 13 },
  { key: "med", label: "Medication Prescribing", n: 26 },
  { key: "treat", label: "Treatment Planning", n: 27 },
  { key: "workup", label: "Workup & Risk Stratification", n: 34 },
];

/** Pass@1 (%) by model x specialty */
export const SPECIALTY_BREAKDOWN: Record<string, Record<string, number>> = {
  "GPT-5.6-sol":    { cardio: 66.7, endo: 69.2, gi: 50.0, id: 50.0, psych: 41.7, heme: 48.7, neph: 33.3, pulm: 46.3 },
  "GPT-5.5":        { cardio: 55.6, endo: 59.0, gi: 57.1, id: 38.9, psych: 33.3, heme: 48.7, neph: 29.2, pulm: 48.1 },
  "Claude Opus 4.6": { cardio: 27.8, endo: 35.9, gi: 35.7, id: 38.9, psych: 27.1, heme: 30.8, neph: 33.3, pulm: 25.9 },
  "Claude Opus 4.7": { cardio: 38.9, endo: 28.2, gi: 28.6, id: 22.2, psych: 18.8, heme: 30.8, neph: 33.3, pulm: 38.9 },
  "GPT-5.4":        { cardio: 27.8, endo: 30.8, gi: 21.4, id: 27.8, psych: 22.9, heme: 38.5, neph: 20.8, pulm: 29.6 },
  "Claude Sonnet 4.6": { cardio: 33.3, endo: 10.3, gi: 26.2, id: 27.8, psych: 25.0, heme: 25.6, neph: 33.3, pulm: 14.8 },
  "Kimi-K2.6":      { cardio: 27.8, endo: 12.8, gi: 21.4, id: 16.7, psych: 14.6, heme: 17.9, neph: 12.5, pulm: 16.7 },
  "MiMo-v2.5-Pro":  { cardio: 11.1, endo: 10.3, gi: 23.8, id: 16.7, psych: 27.1, heme: 17.9, neph: 4.2,  pulm: 13.0 },
  "Qwen3.6-Plus":   { cardio: 5.6,  endo: 12.8, gi: 9.5,  id: 16.7, psych: 20.8, heme: 10.3, neph: 12.5, pulm: 14.8 },
  "MiniMax M2.7":   { cardio: 0.0,  endo: 5.1,  gi: 11.9, id: 11.1, psych: 8.3,  heme: 7.7,  neph: 4.2,  pulm: 13.0 },
  "DeepSeek V4-Pro":{ cardio: 16.7, endo: 7.7,  gi: 33.3, id: 19.4, psych: 14.6, heme: 15.4, neph: 12.5, pulm: 24.1 },
  "Gemini Pro 3.1": { cardio: 5.6,  endo: 10.3, gi: 7.1,  id: 0.0,  psych: 8.3,  heme: 5.1,  neph: 0.0,  pulm: 7.4 },
  "Grok-4.20":      { cardio: 5.6,  endo: 5.1,  gi: 9.5,  id: 2.8,  psych: 10.4, heme: 2.6,  neph: 4.2,  pulm: 1.9 },
};

/** Pass@1 (%) by model x task type */
export const TASKTYPE_BREAKDOWN: Record<string, Record<string, number>> = {
  "GPT-5.6-sol":     { diag: 59.0, med: 46.2, treat: 46.9, workup: 52.0 },
  "GPT-5.5":         { diag: 46.2, med: 41.0, treat: 40.7, workup: 54.9 },
  "Claude Opus 4.6": { diag: 43.6, med: 28.2, treat: 21.0, workup: 38.2 },
  "Claude Opus 4.7": { diag: 41.0, med: 26.9, treat: 22.2, workup: 32.4 },
  "GPT-5.4":         { diag: 35.9, med: 26.9, treat: 23.5, workup: 28.4 },
  "Claude Sonnet 4.6": { diag: 35.9, med: 24.4, treat: 12.3, workup: 25.5 },
  "Kimi-K2.6":       { diag: 23.1, med: 10.3, treat: 16.0, workup: 20.6 },
  "MiMo-v2.5-Pro":   { diag: 20.5, med: 14.1, treat: 14.8, workup: 18.6 },
  "Qwen3.6-Plus":    { diag: 15.4, med: 12.8, treat: 18.5, workup: 9.8 },
  "MiniMax M2.7":    { diag: 7.7,  med: 11.5, treat: 6.2,  workup: 8.8 },
  "DeepSeek V4-Pro": { diag: 12.8, med: 14.1, treat: 14.8, workup: 27.5 },
  "Gemini Pro 3.1":  { diag: 5.1,  med: 5.1,  treat: 4.9,  workup: 7.8 },
  "Grok-4.20":       { diag: 2.6,  med: 7.7,  treat: 2.5,  workup: 6.9 },
};

/** % of failed checkpoints per category, pooled over 3 runs (2010 checkpoints each).
 *  Recomputed 2026-08-12 after fixing a regex in scripts/score_failure_breakdown.py
 *  that matched pytest's summary section as well as its progress lines, counting
 *  every checkpoint twice and mis-attributing the neighbouring test's status. */
export const FAILURE_BREAKDOWN: Record<string, { dr: number; cr: number; ae: number; doc: number }> = {
  "GPT-5.6-sol":        { dr: 12.3, cr: 56.1, ae: 14.6, doc: 16.9 },
  "GPT-5.5":            { dr: 11.9, cr: 50.4, ae: 19.8, doc: 18.0 },
  "Claude Opus 4.6":    { dr: 10.7, cr: 48.5, ae: 15.2, doc: 25.6 },
  "Claude Opus 4.7":    { dr: 16.3, cr: 49.0, ae: 11.4, doc: 23.3 },
  "GPT-5.4":            { dr: 11.0, cr: 46.5, ae: 21.0, doc: 21.5 },
  "Claude Sonnet 4.6":  { dr: 11.5, cr: 47.5, ae: 17.1, doc: 23.9 },
  "Kimi-K2.6":          { dr: 12.0, cr: 46.3, ae: 18.5, doc: 23.2 },
  "Qwen3.6-Plus":       { dr: 9.4,  cr: 49.8, ae: 19.6, doc: 21.2 },
  "MiniMax M2.7":       { dr: 13.2, cr: 43.8, ae: 18.5, doc: 24.5 },
  "MiMo-v2.5-Pro":      { dr: 12.0, cr: 49.3, ae: 15.4, doc: 23.3 },
  "DeepSeek V4-Pro":    { dr: 10.3, cr: 55.8, ae: 14.0, doc: 20.0 },
  "Gemini Pro 3.1":     { dr: 14.2, cr: 45.5, ae: 18.3, doc: 22.0 },
  "Grok-4.20":          { dr: 11.8, cr: 50.8, ae: 17.8, doc: 19.5 },
};
