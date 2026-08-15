# Oncology CSV 工作流

先运行索引构建，再用 `scripts/generate_oncology_task.py` 生成并人工复核一个 case。确认任务、工具轨迹和 checkpoint 契约稳定后，再运行 `scripts/generate_all_oncology_tasks.py` 批量生成。

批量生成采用逐 case 隔离策略。模型调用失败或证据校验失败的 case 会写入 `data/oncology_complete_trajectory/generated/review_queue.jsonl`，不会阻塞其他 case，也不会被静默丢弃。
