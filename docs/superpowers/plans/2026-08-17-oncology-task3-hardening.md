# Oncology Task 3 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Task 3 的答案泄漏、原子导出、resume、失败状态、tags 和 case_id 边界。

**Architecture:** 在 `pipeline/oncology_generation/leakage.py` 集中诊断片段提取与泄漏判断，schemas 和 exporter 复用。exporter 使用同父目录 staging + rename 发布，batch 使用完整任务校验决定 resume，并在 review queue 前持久化失败状态。

**Tech Stack:** Python 3.10+, pathlib, tempfile, shutil, json, tomllib, pytest。

---

### Task 1: 集中诊断片段泄漏检测

**Files:**
- Create: `pipeline/oncology_generation/leakage.py`
- Modify: `pipeline/oncology_generation/schemas.py`
- Modify: `scripts/generate_oncology_task.py`
- Test: `tests/oncology_generation/test_graph_validation.py`
- Test: `tests/oncology_generation/test_export.py`

- [ ] 添加“病理提示肺腺癌，结合临床”对“肺腺癌”的失败测试及短词不误报测试。
- [ ] 运行聚焦测试，确认当前完整 value 比较无法捕获片段。
- [ ] 实现 `diagnostic_fragments` 和 `find_leaked_target_values`，并替换两处重复比较。
- [ ] 运行聚焦测试确认通过。

### Task 2: 原子导出与完整 resume

**Files:**
- Modify: `scripts/generate_oncology_task.py`
- Modify: `scripts/generate_all_oncology_tasks.py`
- Test: `tests/oncology_generation/test_export.py`
- Test: `tests/oncology_generation/test_batch_generation.py`

- [ ] 添加中途写入失败不留下最终/临时目录的测试。
- [ ] 添加完整任务可 resume、残缺或不可解析任务不计 exported 的测试。
- [ ] 实现 staging 写入、契约校验和 rename 发布。
- [ ] 实现 `is_complete_task_dir` 并用于 batch resume。

### Task 3: 失败状态、tags 与 case_id

**Files:**
- Modify: `scripts/generate_oncology_task.py`
- Modify: `scripts/generate_all_oncology_tasks.py`
- Test: `tests/oncology_generation/test_export.py`
- Test: `tests/oncology_generation/test_batch_generation.py`

- [ ] 添加 early failure state.json 存在且 review queue 引用该文件的测试。
- [ ] 添加 tags 非 `list[str]`、`.`、`..`、分隔符和 output_root 逃逸边界测试。
- [ ] 在 exporter 写入前完成 tags/case_id 校验。
- [ ] 在 batch 异常分支先原子写 state.json，再 append review queue。

### Task 4: 验证与提交

**Files:**
- Verify all files above.

- [ ] 运行 `pytest tests/oncology_generation/test_export.py tests/oncology_generation/test_batch_generation.py -q`。
- [ ] 运行 `pytest tests/oncology_generation -q`。
- [ ] 运行编译与 `git diff --check`。
- [ ] 使用中文 Conventional Commit 提交全部加固改动。
