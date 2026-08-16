# Oncology complete trajectory CSV

标准目录是 `data/oncology_complete_trajectory/raw/csv/`，每个 CSV 文件对应一个
`case_id`。原始数据来自 `pmc_case_data_audit` 的 oncology complete trajectory
导出；原始 CSV 不提交到本仓库，也不会被索引脚本改写。

在本机接入数据（只读使用）可执行：

```bash
mkdir -p data/oncology_complete_trajectory/raw
ln -s /gpfs/flash/home/gwh/code/pmc_case_data_audit/data/oncology_complete_trajectory/csv \
  data/oncology_complete_trajectory/raw/csv
python -m data.oncology_complete_trajectory.index.build_index
```

索引脚本也可由 Python 调用 `build_index(Path("data/oncology_complete_trajectory"))`。
生成的 `index/manifest.json` 仅保存文件路径、行数、类别计数和 SHA-256。

## 诊断任务生成

病例数据与任务定义分开保存：

```text
data/oncology_complete_trajectory/
├── raw/csv/<case_id>.csv      # 完整原始病例，只读
├── cleaned/<case_id>.csv      # LangGraph 物化的 Agent 运行输入
└── generated/<case_id>/       # 生成状态与复核信息

tasks/oncology-v1/<case_id>/
├── instruction.md
├── task.toml
├── ground_truth.json
└── tests/test_outputs.py
```

任务目录不保存或复制病例 CSV。生成器从 `raw/csv` 读取完整病例，LangGraph 将目标诊断事件组及其后续事件移除后写入 `cleaned`；exporter 只校验并引用已经物化的 cleaned CSV，不会修改或覆盖 raw CSV。

默认批量生成以下 5 个 pilot case：

- `71af50c891bd0e80cd017c8beb2bb446`
- `15c35bb60e48e62f9beb9fd127248e03`
- `7df4bd9af484dcec897b2f2726e01db2`
- `01864b911256ca7332f7974165d7aeb8`
- `aca554ac1716cf2fb7e2b94d80590e52`

```bash
python scripts/generate_all_oncology_tasks.py
python scripts/generate_all_oncology_tasks.py --case-id <case_id> [<case_id> ...]
```

批量生成按 case 隔离失败并写入 `generated/review_queue.jsonl`；已存在的任务目录会在 resume 时跳过。
