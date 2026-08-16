# Oncology 最终审查 P1 修复计划

## 目标

修复 CSV-only 批处理终态、Agent 失败语义、workspace 写入边界和 cleaned 数据原子发布四个阻塞问题。

## 实施

1. 删除 shell 中残留的 FHIR summary 变量，并用静态 grep 与 `bash -n` 回归。
2. 每次 Agent 执行前清理当前 job 的旧 stdout/stderr；Agent 失败立即停止，不运行 evaluator。
3. `register_all_tools` 显式接收 `workspace_root`，将 `write_file` 绑定到该目录并拒绝相对路径、目录逃逸和 symlink 逃逸。
4. cleaned CSV 写入同目录唯一临时文件；确定性校验通过且最终文件不存在时原子发布，否则删除临时文件并保留已有 cleaned 数据。

## 验证

运行 oncology generation、runtime、tools、data 完整 focused suite，并执行 Python 编译、shell 语法和 `git diff --check`。
