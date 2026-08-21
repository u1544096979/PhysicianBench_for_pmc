# PhysicianBench 论文、源码与数据导读

## 1. 本地材料

- 源码：仓库根目录。
- 论文：<https://arxiv.org/abs/2605.02240>。
- FHIR 数据镜像：`~/data/physical_benchmark_data/physicianbench-fhir-v1.tar.gz`。
- 数据校验：配套 `.sha256` 已验证通过。
- 数据形态：OCI/Docker image archive，镜像标签为 `fhir-full:v1`，不是可直接浏览的 JSON 文件夹。

## 2. 论文主线

PhysicianBench 要测的不是静态医学问答，而是一个代理在 EHR 中完成长流程工作的能力：

`任务指令 → FHIR 检索 → 跨资源临床推理 → 创建医嘱/转诊等操作 → 写临床文档 → checkpoint 评测`

论文报告的基准规模：100 个任务、670 个 checkpoint、21 个专科，平均每任务约 27 次工具调用。任务来自去标识化 STARR EHR 的真实 e-consult 案例，并经过医生多轮审核；论文描述的数据额外做过日期、人口学和数值扰动，以保持临床含义并保护隐私。

重点结论是：最强模型的 pass@1 也只有 46.3%，三次运行全部成功的 pass^3 为 28.0%；失败主要集中在临床推理，其次是文档、动作执行和数据检索。这说明“能回答医学问题”与“能可靠完成 EHR 工作流”是不同能力。

## 3. 论文到源码的映射

| 论文概念 | 本地实现 |
| --- | --- |
| 任务指令与交付物 | `tasks/v1/*/instruction.md` |
| 任务元数据与分类 | `tasks/v1/*/task.toml` |
| checkpoint 与 rubric | `tasks/v1/*/tests/test_outputs.py` |
| 14 个工具的 function-calling schema | `agent/tool_registry.py` |
| FHIR GET/POST 具体实现 | `tools/fhir_api_functions.py` |
| 文件交付物写入 | `tools/file_tools.py` |
| 最小 agent loop | `agent/mini_agent.py`、`agent/llm_client.py` |
| 系统提示词 | `agent/prompts.py` |
| 单任务生命周期、评测（legacy：v1 已删，现为 eval/runner.py） | `scripts/run_task.py`（已删） |
| 批量运行（legacy：v1 已删，无现行对应） | `scripts/run_batch_task.sh`（已删） |
| checkpoint 辅助验证 | `utils/eval_helpers.py` |
| 结果汇总 / 轨迹浏览（现为 viewer，`uv run python -m viewer`） | `scripts/score_jobs.py`（已删） |

源码侧共有 100 个任务目录和 100 个 `test_outputs.py`；checkpoint 函数总数为 670。论文中的 14 个工具对应 13 个 FHIR 工具加 1 个 `write_file` 工具。读操作查询患者、Condition、Observation、MedicationRequest、Procedure、DocumentReference、ServiceRequest 和 social history；写操作创建 MedicationRequest、ServiceRequest、Appointment、Communication，并写工作区文件。

## 4. 数据如何进入运行流程

数据镜像由 Docker archive 包装，README 的预期流程是：

```bash
sha256sum -c ~/data/physical_benchmark_data/physicianbench-fhir-v1.tar.gz.sha256
gunzip -c ~/data/physical_benchmark_data/physicianbench-fhir-v1.tar.gz | docker load
```

载入后，`run_task.py` 对每个任务启动一个新的 `fhir-full:v1` 容器，把容器的 `8080` 映射到本机端口，并访问 `/fhir`。容器内是预加载患者记录的 HAPI FHIR JPA server/H2 数据库；任务结束后容器被删除，因此不同任务或不同运行之间不会共享写入状态。

当前执行环境没有 `docker` 命令，所以这里仅完成了源码缓存、数据校验和静态梳理，没有声称已经完成 EHR 实跑。

## 5. 推荐熟悉顺序

1. 先读一个完整任务：`tasks/v1/aortic_aneurysm_cad/`，同时看其 `instruction.md` 与 `tests/test_outputs.py`。
2. 再读 `agent/mini_agent.py`，明确每一轮的消息、工具调用、工具结果、轨迹日志和终止条件。
3. 读 `agent/tool_registry.py` 与 `tools/fhir_api_functions.py`，把 schema 参数对应到 FHIR R4 resource/search 参数。
4. 读 `utils/eval_helpers.py`，区分“查轨迹/查文件”的混合 grader 与“直接查 FHIR 状态”的 code grader。
5. 有 Docker 后先只跑一个任务，再跑小批量。结果查看用现行入口 `uv run python -m viewer`。（本仓库的 v2 评测闭环入口见 `eval/runner.py`。）

最适合的第一条实验路径：`aortic_aneurysm_cad`。它同时覆盖患者资料检索、影像/实验室综合判断、ServiceRequest 转诊与 CTA、文档写入，能够把论文 Figure 2 的完整链路串起来。

## 6. 评测时要特别留意

- “在笔记里写了要下医嘱”不等于“在 FHIR 中创建了 ServiceRequest/MedicationRequest”；动作 checkpoint 会直接查环境状态。
- 任务测试通常按任务时间过滤 agent 新建资源，避免把预置患者数据误判为 agent 动作。
- 文档 checkpoint 不只看文件是否存在，还会按 rubric 检查数值、临床理由、计划完整性和前后一致性。
- 轨迹日志是主要的失败分析材料：它可以区分没查到、查到了但没提取、推理遗漏、动作没执行和文档级联失败。
- 不要把 `pass@3` 与 `pass^3` 混为一谈：前者表示多次尝试至少成功一次，后者表示多次都成功，分别对应“可被重试挽救”和“稳定可靠”。

## 7. 下一步

当前机器补齐 Docker 后，优先验证：

```bash
cd /gpfs/flash/home/gwh/code/PhysicianBench
uv sync
# legacy：v1 单任务 runner 已删，仅作历史记录
uv run python scripts/run_task.py tasks/v1/aortic_aneurysm_cad \
  --model openai/gpt-5.5 --reasoning-effort high --max-steps 30
```

正式批量实验前应先确认模型 API key、Docker 镜像标签、端口可用，并保留每个任务的 `jobs/` 目录作为可复核的 trajectory、workspace、pytest 和 metadata 证据。
