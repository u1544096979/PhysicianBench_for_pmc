# Oncology Task 3 质量加固设计

## 目标

加固诊断任务导出与批量恢复边界，避免诊断片段泄漏、半成品任务被误判为成功，以及生成失败后缺少可追溯状态。

## 答案泄漏检测

新增集中 helper，供 `validate_state` 与 exporter 共用。helper 对 instruction 和目标 value 使用 `casefold()`；将 value 按中英文逗号、分号、句号、冒号、换行及常见列表分隔符拆分；反复去除“病理提示”“诊断为”“考虑”“符合”等开头及其后空白/标点。

候选片段至少包含 3 个中文字符，或至少 4 个 ASCII 字母/数字。过滤以“结合临床”“建议”“请”“进一步”“待”开头的非诊断说明。保留原始 value 用于错误报告。该规则会从“病理提示肺腺癌，结合临床”提取“肺腺癌”，但忽略“癌”“考虑”“结合临床”等短词或说明性片段。

## 原子导出与恢复

exporter 在 `output_root` 下创建隐藏临时目录，完整写入并验证四项任务契约后，以同文件系统 rename 发布为最终 task 目录。任意异常都清理临时目录，最终目录不可见。

resume 仅在任务目录恰好包含 `instruction.md`、`task.toml`、`ground_truth.json`、`tests/`，测试入口存在，instruction 非空，TOML/JSON 可解析且 case_id 一致时跳过。残缺目录进入正常生成流程，并因不可覆盖现有目录而进入 review queue，不计 exported。

## 输入与失败边界

tags 必须是非空或空的 `list[str]`，其中每项都是字符串；非法类型在创建临时目录前拒绝。case_id 必须是单个安全目录名，拒绝空值、`.`、`..`、路径分隔符以及 resolve 后逃逸 `output_root` 的值。

batch 捕获任何 case 级异常后，先写入真实存在的 `generated/<case_id>/state.json`，至少包含 `case_id`、`error` 和 `review_status=needs_revision`，再将该 state 文件路径写入 review queue。

## 测试

所有测试使用 `tmp_path`。覆盖诊断片段提取和短词忽略、临时目录失败清理、完整/残缺 resume、early failure state、非法 tags、TOML 可解析及 case_id 边界，并运行 Task 3 focused tests 与 `tests/oncology_generation` 全套。
