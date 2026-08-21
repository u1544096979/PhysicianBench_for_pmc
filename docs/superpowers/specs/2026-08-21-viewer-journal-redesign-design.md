# viewer 前端视觉优化：期刊式论文风 (Journal Redesign)

**状态**: Draft → Approved  
**日期**: 2026-08-21  
**范围**: `viewer/static/` 前端三个静态文件（`index.html` / `app.js` / `style.css`）的视觉与排版优化
**前置**: 依赖已合并进 `main` 的轨迹浏览器（spec `2026-08-21-trajectory-viewer-design.md`，merge `5be8351`）

## 1. 背景与目标

轨迹浏览器功能已完备（侧边栏病例列表 + 概览 + run 选择 + 6 标签页），但视觉偏"工程工具"：
白底卡片 + 细边框表格堆叠、缺少层级与留白、Checkpoint/标准答案/任务信息三处直接抛裸表格/裸 JSON、
完整轨迹是一长列无结构的卡片。

目标：在不改变信息结构与后端的情况下，把观感打磨成**期刊式论文风**——米白纸底、衬线标题、
细墨线分隔、藏蓝+淡金语义色、判分精致化，并顺手重整最丑的几处（三张裸表格 + 完整轨迹时间轴）。

**已与用户对齐的三个决定**：
1. 方向 = 视觉精致度优先（非信息架构重构）
2. 风格 = 期刊式论文风（Journal / Paper）
3. 完整轨迹 = 时间轴 + 默认折叠

## 2. 设计令牌（Design Tokens）

统一在 `:root` 定义，供 `style.css` 复用：

| 令牌 | 值 | 用途 |
|---|---|---|
| `--bg` | `#faf8f2` | 米白纸底（页面背景） |
| `--panel` | `#fffdf8` | 面板/卡片背景 |
| `--ink` | `#2b2b2b` | 正文墨色 |
| `--muted` | `#7a7468` | 次要文字 |
| `--line` | `#e3dcc8` | 发丝分隔线 |
| `--line-dash` | `#ece5d0` | 虚线/内部分隔 |
| `--accent` | `#1f3a5f` | 藏蓝（标题/active/强调） |
| `--gold` | `#b08d42` | 淡金（眉题/装饰/时间轴工具节点） |
| `--good` | `#2f6b3a` | 判分 PASS 墨绿 |
| `--bad` | `#9c3b2e` | 判分 FAIL 赭红 |
| `--warn` | `#b08d42` | 判分 ERROR 淡金 |
| 标题字体 | `Georgia, "Songti SC", serif` | 标题/眉题衬线 |
| 正文字体 | `-apple-system, "PingFang SC", sans-serif` | 正文无衬线 |
| 等宽字体 | `ui-monospace, Menlo, monospace` | ID/数字/JSON |

语义说明：`--good/--bad/--warn` 从原亮色（#16a34a/#dc2626/#d97706）替换为明度更低的**墨绿/赭红/淡金**，
以贴合纸张氛围；判分徽标样式见 §3。

## 3. 改造点

### 3.1 整体皮肤（`style.css`，换皮）
- 页面背景切为米白纸底；面板、卡片、表格用 `--panel`，投影改"柔和纸感阴影"。
- 标题（`.ov-title`、`.sidebar-head h1`、tab）改衬线字体；正文保持无衬线。
- 分隔用发丝线 `--line`/`--line-dash`，替代粗边框。
- 侧边栏 active、tab active 统一为藏蓝字 + 淡金下划线。
- 有 hover 的元素（行、卡片、按钮、run-chip）统一淡金/淡蓝高亮，过渡柔和。

### 3.2 Checkpoint 判分表（`checkpointsHTML` + CSS）
- verdict 改"印章式"徽标：衬线小大写（small-caps）+ 语义色描边/浅底（PASS 墨绿、FAIL 赭红、ERROR 淡金）。
- 表头加大写眉题（uppercase + letter-spacing + 淡金字）。
- 行 hover 淡金高亮；保持 `table-wrap` 横向滚动。

### 3.3 标准答案 ground_truth（`groundTruthHTML` + CSS）
- 不再整块裸 JSON 抛满屏：保留内容完整可读，但用期刊风折叠面板承载，
  眉题「Ground Truth」+ 折叠开关；内部用等宽字体 + 更好行距（`pre.json` 优化）。
- 不做 JSON 着色（保持轻量，避免依赖），仅层次与间距优化。

### 3.4 任务信息（`taskInfoHTML` + CSS）
- 表格整体用 §3.2 的期刊风表格样式。
- `params` 列从"整块塞进单元格"改为**抽屉式展开**（summary/details），默认收起，点开展开为格式化的 JSON。

### 3.5 完整轨迹 → 时间轴（`trajectoryHTML` + CSS）
- 左测细时刻轴竖线 + 节点圆点；节点按事件类型着色：
  LLM 藏蓝、工具淡金、初始化灰、final 墨绿、instruction 同墨绿。
- 每个事件为时间轴上的一个条目：标题栏（类型 + step + tokens + 元信息）+ **默认折叠**的正文区。
- LLM 正文、工具入参/返回、reasoning 均可用折叠面板点击展开（复用原 `<details>`，仅换样式）。
- 保留 `failed_lines` 提示条（若有），样式与该页一致。
- 元信息（耗时、工具调用数、模型）以眉题形式置顶于轨迹页。

## 4. 不做（Scope Cut）
- **不改**信息结构与布局：侧边栏、概览、run 选择、标签栏、6 个标签页结构全部保持。
- **不改**后端 `viewer/scanner.py` / `viewer/server.py`，不改任何 API。
- **不新增**依赖、不引入构建工具链（保持零构建原生 JS + 纯 CSS）。
- 不做整体响应式/移动端适配（本工具面向桌面本地使用）。
- 不引入 JS 框架、图标库或 CSS 框架。

## 5. 文件与改动面
- `viewer/static/style.css`：重写色调/字体/面板/表格/卡片/timeline 样式（改动最大）。
- `viewer/static/index.html`：如无必要不改；仅在需要加画布容器/眉题钩子时最小改动。
- `viewer/static/app.js`：改 `checkpointsHTML` / `groundTruthHTML` / `taskInfoHTML` /
  `trajectoryHTML` 四个渲染函数的相关 class/结构；逻辑（取数、折叠交互）不变。

## 6. 回归与验收
- 现有 79 个测试全为后端/Python，不受前端改动影响；跑 `uv run pytest tests/ -q` 应仍全绿。
- 验收为**手动浏览器**：`uv run python -m viewer` → http://127.0.0.1:8765，选择
  `00151e6a` → run `20260820-210036`，检查 6 个标签页在期刊风下的观感、三张表重整、
  轨迹时间轴折叠/展开是否正常。（对应原 spec §6 的人工验收门）
- 前端改动是纯静态文件，git 版本可随时还原，无迁移风险。

## 7. 交付物
- 更新后的 `viewer/static/style.css`（期刊风皮肤 + 各组件样式）。
- 更新后的 `viewer/static/app.js`（四个渲染函数重构 + 时间轴结构）。
- （可选）`viewer/static/index.html` 最小编排。
