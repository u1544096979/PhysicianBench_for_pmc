# PhysicianBench: Evaluating LLM Agents in Real-World EHR Environments

[![Website](https://img.shields.io/badge/Website-000000?style=for-the-badge&logo=googlechrome&logoColor=white&color=105864)](https://healthrex.github.io/PhysicianBench/)
[![Paper](https://img.shields.io/badge/Paper-000000?style=for-the-badge&logo=arxiv&logoColor=white&color=B31B1B)](https://arxiv.org/abs/2605.02240)
[![Trajectory](https://img.shields.io/badge/Trajectory-000000?style=for-the-badge&logo=githubpages&logoColor=white&color=4f46e5)](https://healthrex.github.io/PhysicianBench/#trajectory)
[![Data](https://img.shields.io/badge/Data-000000?style=for-the-badge&logo=databricks&logoColor=white&color=059669)](https://stanford.redivis.com/datasets/a0ek-0ad8tjsw9)

---

## Overview

PhysicianBench is a benchmark for evaluating LLM agents on physician tasks grounded in real clinical workflows. The upstream benchmark contains 100 long-horizon FHIR tasks. This repository copy implements the oncology diagnosis-generation workflow as local, read-only CSV tasks backed exclusively by `data/oncology_complete_trajectory/cleaned/`; it does not include the Docker/FHIR compatibility layer required by upstream `tasks/v1`.

## Main Results

![Model performance ranked by pass@1 success rate](assets/model_comparison.png)

*Overall model performance on PhysicianBench, ranked by pass@1 success rate.*

## Trajectory Example

![Agent stepping through a PhysicianBench task](assets/trajectory.gif)

*An agent working through a PhysicianBench task (2× speed). Explore the full interactive viewer on the [website](https://healthrex.github.io/PhysicianBench/#trajectory).*

## Setup

### 1. Install Python dependencies

PhysicianBench uses [`uv`](https://docs.astral.sh/uv/) for environment management. If you don't have it yet:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then install project dependencies:

```bash
uv sync
```

### 2. Prepare oncology CSV data

Local task execution requires a generated task and its matching cleaned case:

```text
tasks/oncology-v1/<case_id>/task.toml
data/oncology_complete_trajectory/cleaned/<case_id>.csv
```

The runner never reads `raw/csv` and rejects cleaned files that resolve outside the cleaned directory. See [the oncology data guide](data/oncology_complete_trajectory/README.md) for raw data setup and task generation.

### 3. Configure the two model environments

Copy `.env.example` to `.env` and set separate generation and evaluation credentials:

```bash
GENERATION_MODEL=your-generation-model
GENERATION_API_KEY=your-generation-api-key
GENERATION_BASE_URL=https://your-generation-provider.example/v1

AGENT_EVAL_MODEL=your-agent-eval-model
AGENT_EVAL_API_KEY=your-agent-eval-api-key
AGENT_EVAL_BASE_URL=https://your-agent-eval-provider.example/v1
```

`--model` overrides `AGENT_EVAL_MODEL` for a local run. `API_KEY` and `BASE_URL`
must be configured together for each stage. When both stage-specific credential
fields are unset, the existing OpenRouter, Anthropic, or OpenAI backend environment
variables remain available as fallback.

## Quick Start

### Run a single task

```bash
uv run python scripts/run_task.py tasks/oncology-v1/<case_id> \
    --data-root data/oncology_complete_trajectory \
    --reasoning-effort high
```

This will:
1. Validate `task.toml` contains an oncology `case_id` and cleaned-data contract.
2. Open only `cleaned/<case_id>.csv` through the read-only CSV tools.
3. Run the agent and pytest verifier.
4. Write trajectory, workspace, verifier logs, and metadata to `jobs/<batch>/<task>/`.

Evaluation succeeds only when pytest passes and both the deterministic diagnosis
rule and model judge return `correct`. Partial/incorrect results and evaluator
errors are preserved in `logs/verifier/diagnosis_eval.json` and produce a non-zero
runner exit code.

The legacy `tasks/v1` commands, `--fhir-image`, and `--port` are intentionally unsupported in this copy. Use an upstream FHIR-enabled checkout for those tasks.

### Run all generated oncology tasks

```bash
bash scripts/run_batch_task.sh \
    --data-root data/oncology_complete_trajectory \
    --reasoning-effort high
```

Available parameters:

| Flag | Default | Description |
| --- | --- | --- |
| `--model`, `-m` | `openai/gpt-5.5` | Model ID. Format depends on backend (see [Configure model API keys](#3-configure-model-api-keys)). |
| `--reasoning-effort` | `high` | One of `low`, `medium`, `high`. Forwarded to reasoning-capable models. |
| `--temperature` | api-default | Sampling temperature (omit to use the API default). |
| `--n_runs` | `1` | Number of independent runs per task — enables `pass@3` / `pass^3` scoring. |
| `--max-tasks` | `0` (all) | Cap the number of tasks to run, useful for smoke tests. |
| `--max-steps` | `100` | Max LLM ↔ tool steps per task before the agent is force-stopped. |
| `--resume` | — | Path to an existing batch job dir; skips already-completed tasks and continues. |
| `--task-dir` | `tasks/oncology-v1` | Root directory of generated oncology task folders. |
| `--data-root` | `data/oncology_complete_trajectory` | Dataset root containing `cleaned/<case_id>.csv`. |
| *(positional args)* | — | Specific oncology `case_id` task directories. If omitted, all tasks under `--task-dir` are run. |

Examples:

```bash
# Specific cases only
bash scripts/run_batch_task.sh <case_id> [<case_id> ...]

# Multiple runs per task (for pass@k)
bash scripts/run_batch_task.sh --model anthropic/claude-opus-4.7 --n_runs 3

# Resume an interrupted batch
bash scripts/run_batch_task.sh --resume jobs/2026-04-29__03-57-03__openai_gpt-5.5__high__t0
```

## Citation

```bibtex
@article{physicianbench2026,
  title         = {PhysicianBench: Evaluating LLM Agents on Physician Tasks in Real-World EHR Environments},
  author        = {Ruoqi Liu and Imran Q. Mohiuddin and Austin J. Schoeffler and Kavita Renduchintala and Ashwin Nayak and Prasantha L. Vemu and Shivam C. Vedak and Kameron C. Black and John L. Havlik and Isaac Ogunmola and Stephen P. Ma and Roopa Dhatt and Jonathan H. Chen},
  year          = {2026},
  eprint        = {2605.02240},
  archivePrefix = {arXiv},
  url           = {https://arxiv.org/abs/2605.02240}
}
```

## License

See [LICENSE](LICENSE).
