# viewer 前端期刊式论文风重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改信息结构与后端的前提下，把 `viewer` 前端打磨成期刊式论文风（米白纸底 + 衬线标题 + 藏蓝/淡金 + 判分明度色），并重整三张裸表格与完整轨迹时间轴。

**Architecture:** 全部为 `viewer/static/` 下的零构建原生前端改动——`style.css` 承载设计令牌与全部视觉样式；`app.js` 的 4 个渲染函数（`checkpointsHTML`/`groundTruthHTML`/`taskInfoHTML`/`trajectoryHTML`）改结构以接入新样式；`index.html` 尽量不动。后端 `scanner.py`/`server.py`、API 完全不变。

**Tech Stack:** 原生 HTML + CSS + JS（零构建）；后端仍 FastAPI 静态托管 `viewer/static/`。

## Global Constraints

- 只改 `viewer/static/style.css`、`viewer/static/app.js`、`viewer/static/index.html`（第 3 个如无必要不改）。
- **不改** `viewer/scanner.py`、`viewer/server.py`、任何 API、标签结构、信息架构。
- **不新增**依赖，不引入构建工具链 / JS 框架 / CSS 框架 / 图标库。
- 保留原生 JS 的 `esc()` XSS 转义——所有插入到 innerHTML 的取值必须经 `esc()`。
- 判分徽标语义色：PASS 墨绿 `#2f6b3a`、FAIL 赭红 `#9c3b2e`、ERROR 淡金 `#b08d42`。
- 不回退已有功能：Sidebar 病例列表、概览、run 选择 chips、6 个标签页 dispatch 全部保留原逻辑。
- **测试注意**：一律用 `uv run pytest tests/ -q`（**不要**在根目录跑裸 `uv run pytest`——会把 `tasks/v1/*/tests` 一起收集而失败/挂起）。前端无自动化测试，每个任务用「起服务 + curl 200 + 后端回归 + 浏览器人工检查」验证。

说明：本次为视觉重构，不引入前端测试框架（spec §6 判定为手动浏览器验收）。每个任务以「服务可启动、后端回归全绿、浏览器观感正确」为完成的独立可验证交付物。

---

### Task 1: 期刊风设计令牌与全局皮肤

**Files:**
- Rewrite: `viewer/static/style.css`
- Test / verify: 起服务 curl 200 + 后端回归 + 浏览器观感

**Interfaces:**
- Produces: `:root` 设计令牌（`--bg/--panel/--ink/--muted/--line/--line-dash/--accent/--gold/--good/--bad/--warn`）、标题衬线/正文无衬线/等宽字体族、面板/表格/卡片/徽标/折叠面板/tab/侧栏的全部期刊风基础样式。Task 2/3 直接复用这些 class。

- [ ] **Step 1: 重写 `style.css` 的 `:root` 令牌与全局皮肤**
      把 `:root` 与 body/#app/#sidebar/sidebar-head/#refresh-btn/#task-list/.task-item/.badge(±-good/-warn/-bad/-empty)/#main/.empty/.overview/.ov-*/.instruction/#run-select/.run-chip/#tab-bar/.tab/#tab-content/.table-wrap/table/th/td/.verdict(.pass/.fail/.error)/.card(.tool/.llm/.final/.instruction/.init)/.card-head/.chip/.tokens/pre/.md/.warn 全部换成期刊风（如下令牌与指引）。
      关键令牌（从 spec §2 复制）：
      ```css
      :root {
        --bg:#faf8f2; --panel:#fffdf8; --ink:#2b2b2b; --muted:#7a7468;
        --line:#e3dcc8; --line-dash:#ece5d0; --accent:#1f3a5f; --gold:#b08d42;
        --good:#2f6b3a; --bad:#9c3b2e; --warn:#b08d42;
        --serif: Georgia,"Songti SC",serif;
        --sans: -apple-system,"PingFang SC",sans-serif;
        --mono: ui-monospace,Menlo,monospace;
      }
      ```
      排版要点：
      - `body{background:var(--bg);color:var(--ink);font-family:var(--sans);}`
      - 标题类（`.sidebar-head h1`、`.ov-title`、`.tab`）用 `var(--serif)`，`.ov-title{color:var(--accent)}`。
      - 分隔用 `1px solid var(--line)`（发丝），`--line-dash` 用于虚线。
      - active 态：`.tab.active{color:var(--accent);border-bottom-color:var(--gold)}`；`.run-chip.active`、`.task-item.active` 用藏蓝 + 淡金。
      - hover：`.task-item:hover`、`tr:hover`、`.card:hover` 用淡金/淡蓝柔和高亮，`transition: background .15s`。
      - 徽标 `.badge-good{background:var(--good)} .badge-warn/.badge-error{background:var(--warn)} .badge-bad{background:var(--bad)}`。
      - 面板/卡片投影柔和纸感（`box-shadow:0 1px 3px rgba(120,100,60,.08)`）。

- [ ] **Step 2: 起服务验证样式文件生效**

Run:
```bash
uv run python -m viewer >/tmp/v.log 2>&1 & echo $! >/tmp/v.pid; sleep 3
curl -s -o /dev/null -w "css %{http_code}\n" http://127.0.0.1:8765/style.css
curl -s -o /dev/null -w "root %{http_code}\n" http://127.0.0.1:8765/
kill "$(cat /tmp/v.pid)"
```
Expected: `css 200` 与 `root 200`。浏览器 http://127.0.0.1:8765 观感为米白纸底、衬线标题、藏蓝/淡金 accented（本步骤只验证全局皮肤，表格/时间轴重塑在 Task 2/3）。

- [ ] **Step 3: 后端回归不回归**

Run: `uv run pytest tests/ -q`
Expected: `79 passed`（前端改动不影响后端）。

- [ ] **Step 4: Commit**

```bash
git add viewer/static/style.css
git commit -m "style: viewer 期刊式论文风全局皮肤（设计令牌+面板/表格/侧栏/tab）"
```

---

### Task 2: 三张表 / JSON 重整（Checkpoint / 标准答案 / 任务信息）

**Files:**
- Modify: `viewer/static/app.js`（`checkpointsHTML` `groundTruthHTML` `taskInfoHTML`）
- Modify: `viewer/static/style.css`（追加判分徽标/折叠面板/抽屉相关类）

**Interfaces:**
- Consumes: Task 1 的令牌与基础表格/卡片 class。
- Produces: 新的 verdict 印章式徽标结构（`.verdict.pass/.fail/.error` 衬线小 caps）、ground-truth 折叠面板、taskinfo `params` 抽屉（`<details>`）。Task 3 复用折叠面板样式。

- [ ] **Step 1: 改 `checkpointsHTML` 徽标与表头**
      保持取数与字段不变，仅：
      - table 表头加大写眉题（`<th>` 文本保持，CSS 端用 text-transform 处理）。
      - verdict 单元格输出改为带期刊风 class，如：
      ```js
      <td><span class="verdict ${esc(c.verdict)}">${esc((c.verdict||'').toUpperCase())}</span></td>
      ```
      并在 `style.css` 把 `.verdict` 做成衬线小大写印章式：`text-transform:uppercase;letter-spacing:.5px;font-family:var(--serif);font-size:10px;` 描边/浅底 + 语义色边框（`.verdict.pass{color:var(--good);border:1px solid var(--good);background:#f2f7f1}`；`.fail` 用 `--bad`；`.error` 用 `--warn`）。
      - 表头 `.table-wrap th` 加 uppercase 眉题（淡金字 + letter-spacing）。
      - 行 `tr:hover` 淡金高亮。

- [ ] **Step 2: 改 `groundTruthHTML` 为折叠面板**
      ```js
      function groundTruthHTML(run) {
        if (!run || run.ground_truth == null) return '<div class="empty">该病例缺少 ground_truth.json。</div>';
        const pretty = JSON.stringify(run.ground_truth, null, 2);
        return `<details class="panel" open><summary class="panel-hd">Ground Truth <span class="chip">JSON</span></summary><pre class="json">${esc(pretty)}</pre></details>`;
      }
      ```
      `style.css` 新增 `.panel/.panel-hd` 期刊风折叠面板（`summary` 用衬线 + 淡金下箭头/小 caps）。

- [ ] **Step 3: 改 `taskInfoHTML` 的 `params` 为抽屉**
      `paramsCell` 中非空 params 输出改为：
      ```js
      <td><details class="params"><summary>params（${keyCount} 键）</summary><pre class="json">${esc(prettyParams)}</pre></details></td>
      ```
      （空 params 仍输出 `—`）。表格整体复用 Task 2 Step 1 的期刊风表格样式。

- [ ] **Step 4: 起服务验证 + 后端回归**

Run:
```bash
uv run python -m viewer >/tmp/v.log 2>&1 & echo $! >/tmp/v.pid; sleep 3
curl -s -o /dev/null -w "app %{http_code}\n" http://127.0.0.1:8765/app.js
kill "$(cat /tmp/v.pid)"; uv run pytest tests/ -q
```
Expected: `app 200`、`79 passed`。浏览器检查：Checkpoint 表徽标/眉题正确、Ground Truth 折叠面板、任务信息 params 抽屉。

- [ ] **Step 5: Commit**

```bash
git add viewer/static/app.js viewer/static/style.css
git commit -m "feat: viewer 三张表/JSON 期刊风重整——判分徽标、Ground Truth 折叠、params 抽屉"
```

---

### Task 3: 完整轨迹 → 期刊风时间轴

**Files:**
- Modify: `viewer/static/app.js`（`trajectoryHTML` 及其事件渲染）
- Modify: `viewer/static/style.css`（时间轴类）

**Interfaces:**
- Consumes: Task 1 令牌、Task 2 `.panel/.panel-hd` 折叠面板样式。
- Produces: 时间轴容器 `.timeline`、条目 `.tle`、节点 `.tle-dot`（配色类 `dot-llm/dot-tool/dot-init/dot-final/dot-instruction`）、默认折叠的正文 `<details>`。

- [ ] **Step 1: 改 `trajectoryHTML` 为时间轴结构**
      在页顶加眉题（模型/工具调用数/耗时，从 `run` 取），主体改为：
      ```js
      const nl = [];
      run.events.forEach(ev => {
        switch (ev.type) {
          case 'instruction':
            nl.push(tlItem('dot-instruction', 'Instruction', '', ev.content, true));
            break;
          case 'agent_initialized': {
            const m = ev.metadata || {};
            nl.push(tlItem('dot-init', `Agent 初始化`, m.model||'', '', m, false));
            break;
          }
          case 'llm_response': { nl.push(llmItem(ev)); break; }
          case 'tool_call': { nl.push(toolItem(ev)); break; }
          case 'final_result':
            nl.push(tlItem('dot-final', 'Final Result', '', ev.content, true));
            break;
          default:
            nl.push(tlItem('dot-init', ev.type, '', JSON.stringify(ev,null,2), false));
        }
      });
      ```
      其中辅助函数（正文默认折叠，用 `<details>` 打开/收起）：
      - `tlItem(dot, title, sub, body, open)`：返回
        `<div class="tle"><span class="tle-dot ${dot}"></span><div class="tle-body">`
        `<div class="tle-hd">${title}<span class="tle-sub">${esc(sub)}</span></div>`
        `<details ${open?'open':''}><summary>正文</summary><pre>${esc(body)}</pre></details></div></div>`
      - `llmItem(ev)`：step 计数（`step+=1`）、tokens `${m.prompt_tokens}→${m.completion_tokens}`（有值时）、reasoning 独立 `<details>`；正文 `open` 折叠。
      - `toolItem(ev)`：标题 `🔧 ${m.tool_name}`；入参/返回各一个 `<details>`（返回超 800 字提示"截断，全长 N 字符"，仍保留"展开完整"）。
      - 所有取入 HTML 的字符串经 `esc()`；`m.input` 用 `JSON.stringify` 后 `esc()`。
      保留 `failed_lines>0` 的提示条（期刊风 `--warn`）。

- [ ] **Step 2: 在 `style.css` 加时间轴类**
      `.timeline`（margin-top）；`.tle`（`display:flex;gap:14px;position:relative;padding-bottom:14px`）；`.tle:not(:last-child)::before` 左侧 `1px solid var(--line)` 竖线；`.tle-dot`（`14px` 圆点 + 3px 纸色 ring）；配色 `.tle-dot.dot-llm{background:var(--accent)} .dot-tool{background:var(--gold)} .dot-init{background:#9aa0a6} .dot-final{background:var(--good)} .dot-instruction{background:var(--good)}`；`.tle-body{flex:1}`；`.tle-hd` 衬线加粗 + `.tle-sub` 用 `--muted` 等宽；`details/summary` 复用 Task 2 折叠样式。

- [ ] **Step 3: 起服务验证 + 后端回归**

Run:
```bash
uv run python -m viewer >/tmp/v.log 2>&1 & echo $! >/tmp/v.pid; sleep 3
curl -s -o /dev/null -w "root %{http_code}\n" http://127.0.0.1:8765/
kill "$(cat /tmp/v.pid)"; uv run pytest tests/ -q
```
Expected: `root 200`、`79 passed`。浏览器：轨迹页为时间轴、节点按类型着色、事件默认折叠、展开正常、`failed_lines` 提示保留。

- [ ] **Step 4: Commit**

```bash
git add viewer/static/app.js viewer/static/style.css
git commit -m "feat: viewer 完整轨迹改期刊风时间轴（彩色节点+默认折叠）"
```

---

### Task 4: 收尾回归与验收

**Files:**
- Verify-only（如 README 需补充说明才改）。

**Interfaces:**
- Consumes: Task 1-3 成果。

- [ ] **Step 1: 全链路冒烟 + 后端全量回归**
      起服务，curl `/`、`/style.css`、`/app.js`、`/api/tasks`、`/api/tasks/<case>/runs/<run>` 均 200；后端 `uv run pytest tests/ -q` = 79 passed。

- [ ] **Step 2: 浏览器人工验收（对应原 spec §6 人工门）**
      `uv run python -m viewer` → http://127.0.0.1:8765 → 选 `00151e6a` → run `20260820-210036`：
      6 个标签页逐一过：Checkpoint（徽标/眉题）、完整轨迹（时间轴/折叠）、交付物、标准答案（折叠面板）、病例数据、任务信息（params 抽屉）。确认与原 spec §4.2 的全部内容块一致、无功能回退。

- [ ] **Step 3: Commit**（如无文件改动则本步为"无提交"）

```bash
git add -A
git commit -m "chore: viewer 期刊风重构回归验收通过" || echo "no changes to commit"
```

---

## Self-Review

- **Spec 覆盖**：§3.1 全局皮肤 → Task 1；§3.2 判分表 → Task 2 Step 1；§3.3 Ground Truth 折叠 → Task 2 Step 2；§3.4 任务信息 params 抽屉 → Task 2 Step 3；§3.5 时间轴 → Task 3。§4 不做项全部遵守（不动后端/结构/依赖）。§6 回归 → Task 4。✔
- **占位符扫描**：无 TBD/TODO；所有代码步骤含实际内容。✔
- **一致性**：判分语义色、`esc()`、令牌名在各 Task 间一致；时间轴节点 class `dot-llm/dot-tool/dot-init/dot-final/dot-instruction` 在 Task 3 Step 1/2 一致。✔
- **说明**：前端无测试基建，故以「起服务 curl + 后端回归 + 浏览器人工检查」为每任务验证，符合 spec §6。
