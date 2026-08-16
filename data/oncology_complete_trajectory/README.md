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
