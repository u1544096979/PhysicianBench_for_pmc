// OncoBench 轨迹浏览器 前端逻辑（零构建，原生 JS）
// spec: 2026-08-21-trajectory-viewer-design.md §4.2 前端
'use strict';

const state = { caseId: null, runId: null, task: null, run: null, activeTab: 'checkpoints' };
const $ = (id) => document.getElementById(id);

async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status} ${url}`);
  return r.json();
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function badgeClass(pass, total) {
  if (total == null || total === 0) return 'badge-empty';
  if (pass === total) return 'badge-good';
  if (pass === 0) return 'badge-bad';
  return 'badge-warn';
}

// -------------------- 侧边栏 --------------------
async function loadTasks() {
  const tasks = await fetchJSON('/api/tasks');
  const list = $('task-list');
  list.innerHTML = '';
  $('sidebar-empty').classList.toggle('hidden', tasks.length > 0);
  tasks.forEach(t => {
    const btn = document.createElement('button');
    btn.className = 'task-item' + (t.case_id === state.caseId ? ' active' : '');
    btn.innerHTML = `
      <span class="task-id">${esc(t.case_id.slice(0, 8))}</span>
      <span class="task-label">${esc(t.task_label || '')}</span>
      <span class="badge ${badgeClass(t.recent_passed, t.recent_total)}">
        ${t.recent_passed ?? '—'}/${t.recent_total ?? '—'} · ${t.run_count} run</span>`;
    btn.onclick = () => selectCase(t.case_id);
    list.appendChild(btn);
  });
}

// -------------------- 概览 + run 选择 --------------------
function overviewHTML(t) {
  const run = (t.runs || []).find(r => r.run_id === state.runId) || null;
  return `
    <div class="overview">
      <div class="ov-title">${esc(t.task_label || t.case_id)}
        <span class="mono">${esc(t.case_id.slice(0, 8))}</span></div>
      <div class="ov-grid">
        <div><label>task_type</label><span>${esc(t.task_type || '—')}</span></div>
        <div><label>target_date</label><span>${esc(t.target_date || '—')}</span></div>
        <div><label>模型</label><span>${run ? esc(run.agent_model ?? '—') : '—'}</span></div>
        <div><label>run 时间</label><span class="mono">${run ? esc(run.run_id) : '—'}</span></div>
        <div><label>总得分</label><span>${run && run.pass_count != null ? esc(run.pass_count) + '/' + esc(run.total_count) : '未完成'}</span></div>
        <div><label>工具调用</label><span>${run ? esc(run.tool_calls ?? '—') : '—'}</span></div>
        <div><label>耗时</label><span>${run && run.duration_seconds != null ? run.duration_seconds.toFixed(1) + 's' : '—'}</span></div>
        <div><label>状态</label><span>${run ? esc(run.status) : '—'}</span></div>
      </div>
      <details class="instruction"><summary>Instruction（题干全文）</summary>
        <div class="md">${t.instruction_html || esc(t.instruction_md)}</div>
      </details>
    </div>`;
}

function renderRunSelector(runs) {
  const sel = $('run-select');
  sel.innerHTML = '';
  sel.classList.toggle('hidden', runs.length === 0);
  runs.forEach(r => {
    const chip = document.createElement('button');
    chip.className = 'run-chip' + (r.run_id === state.runId ? ' active' : '');
    const score = r.pass_count != null ? `${r.pass_count}/${r.total_count}` : '未完成';
    chip.textContent = `${r.run_id} · ${r.agent_model || '—'} · ${score}`;
    chip.onclick = () => selectRun(state.caseId, r.run_id);
    sel.appendChild(chip);
  });
}

// -------------------- 标签页 --------------------
const TABS = [
  ['checkpoints', 'Checkpoint 情况'],
  ['trajectory', '完整轨迹'],
  ['report', '交付物'],
  ['groundtruth', '标准答案'],
  ['csv', '病例数据'],
  ['taskinfo', '任务信息'],
];

function renderTabs() {
  const bar = $('tab-bar');
  bar.innerHTML = '';
  TABS.forEach(([key, label]) => {
    const b = document.createElement('button');
    b.textContent = label;
    b.className = key === state.activeTab ? 'tab active' : 'tab';
    b.onclick = () => { state.activeTab = key; renderTabs(); renderActiveTab(); };
    bar.appendChild(b);
  });
}

function renderActiveTab() {
  const run = state.run;
  const sec = $('tab-content');
  switch (state.activeTab) {
    case 'checkpoints': sec.innerHTML = checkpointsHTML(run); break;
    case 'trajectory': sec.innerHTML = trajectoryHTML(run); break;
    case 'report': sec.innerHTML = reportHTML(run); break;
    case 'groundtruth': sec.innerHTML = groundTruthHTML(run); break;
    case 'csv': sec.innerHTML = csvHTML(run); break;
    case 'taskinfo': sec.innerHTML = taskInfoHTML(state.task); break;
  }
}

function checkpointsHTML(run) {
  const cps = (run && run.checkpoints) || [];
  if (!cps.length) return '<div class="empty">该 run 无 checkpoint 记录（可能未完成判分）。</div>';
  return `<div class="table-wrap"><table><thead><tr>
      <th>checkpoint_id</th><th>layer</th><th>description</th><th>verdict</th><th>judge</th><th>comment</th>
    </tr></thead><tbody>${cps.map(c => `
      <tr>
        <td class="mono">${esc(c.checkpoint_id)}</td>
        <td>${esc(c.layer)}</td>
        <td>${esc(c.description)}</td>
        <td><span class="verdict ${esc(c.verdict)}">${esc((c.verdict||'').toUpperCase())}</span></td>
        <td>${esc(c.judge)}</td>
        <td>${esc(c.comment)}</td>
      </tr>`).join('')}</tbody></table></div>`;
}

function trajectoryHTML(run) {
  if (!run || !run.events.length) return '<div class="empty">该 run 无轨迹事件。</div>';
  const metaParts = [];
  if (run.agent_model) metaParts.push(esc(run.agent_model));
  if (run.tool_calls != null) metaParts.push(`${run.tool_calls} tool calls`);
  if (run.duration_seconds != null) metaParts.push(run.duration_seconds.toFixed(1) + ' s');
  const meta = metaParts.length
    ? `<div class="tl-caption">Trajectory · ${metaParts.join(' · ')}</div>`
    : '';
  const items = [];
  let step = 0;
  run.events.forEach(ev => {
    switch (ev.type) {
      case 'instruction':
        items.push(tlItem('dot-instruction', 'Instruction', ev.content || '', true));
        break;
      case 'agent_initialized': {
        const m = ev.metadata || {};
        items.push(tlItem('dot-init', 'Agent 初始化', JSON.stringify(m, null, 2), false));
        break;
      }
      case 'llm_response': {
        step += 1;
        const m = ev.metadata || {};
        const tokens = m.completion_tokens != null ? `${m.prompt_tokens || 0}→${m.completion_tokens}` : '';
        const reasoning = (m.raw_message && m.raw_message.reasoning) || null;
        const sub = [];
        if (tokens) sub.push(`${esc(tokens)} tokens`);
        if (m.finish_reason) sub.push(esc(m.finish_reason));
        let inner = '';
        if (reasoning) inner += `<details class="reasoning"><summary>reasoning</summary><pre>${esc(reasoning)}</pre></details>`;
        inner += `<details class="llm-body"><summary>正文</summary><pre>${esc(ev.content)}</pre></details>`;
        items.push(tlItemRaw('dot-llm', `LLM 回复 <span class="chip">step ${step}</span>`, sub.join(' · '), inner));
        break;
      }
      case 'tool_call': {
        const m = ev.metadata || {};
        const input = m.input ? JSON.stringify(m.input, null, 2) : '';
        const output = String(m.output ?? '');
        const truncated = output.length > 800;
        let inner = '';
        if (input) inner += `<pre class="input">入参: ${esc(input)}</pre>`;
        inner += `<details class="output"><summary>返回内容${truncated ? `（截断，全长 ${output.length} 字符）` : ''}</summary><pre>${esc(truncated ? output.slice(0, 800) : output)}${truncated ? '…' : ''}</pre>${truncated ? `<details class="full"><summary>展开完整</summary><pre>${esc(output)}</pre></details>` : ''}</details>`;
        items.push(tlItemRaw('dot-tool', `🔧 ${esc(m.tool_name || 'tool')}`, '', inner));
        break;
      }
      case 'final_result':
        items.push(tlItem('dot-final', 'Final Result', ev.content || '', true));
        break;
      default:
        items.push(tlItem('dot-init', esc(ev.type), JSON.stringify(ev, null, 2), false));
    }
  });
  const warn = run.failed_lines > 0 ? `<div class="warn">⚠️ ${run.failed_lines} 行轨迹解析失败（已跳过）</div>` : '';
  return meta + warn + `<div class="timeline">${items.join('')}</div>`;
}

function tlItem(dot, title, body, open) {
  const inner = body ? `<details class="tle-detail" ${open ? 'open' : ''}><summary>正文</summary><pre>${esc(body)}</pre></details>` : '';
  return tlItemRaw(dot, title, '', inner);
}
function tlItemRaw(dot, titleHTML, subText, innerHTML) {
  return `<div class="tle"><span class="tle-dot ${dot}"></span><div class="tle-body"><div class="tle-hd">${titleHTML}${subText ? `<span class="tle-sub">· ${subText}</span>` : ''}</div>${innerHTML}</div></div>`;
}

function reportHTML(run) {
  if (!run || !run.report_html) return '<div class="empty">该 run 无可交付报告（output/*.md 缺失）。</div>';
  return `<div class="md report">${run.report_html}</div>`;
}

function groundTruthHTML(run) {
  if (!run || run.ground_truth == null) return '<div class="empty">该病例缺少 ground_truth.json。</div>';
  const pretty = JSON.stringify(run.ground_truth, null, 2);
  return `<details class="panel" open><summary class="panel-hd">Ground Truth <span class="chip">JSON</span></summary><pre class="json">${esc(pretty)}</pre></details>`;
}

function csvHTML(run) {
  if (!run || !run.cleaned_csv_html) return '<div class="empty">该病例缺少 cleaned_trajectory.csv。</div>';
  return run.cleaned_csv_html;
}

function taskInfoHTML(task) {
  const cps = (task && task.checkpoints) || [];
  if (!cps.length) return '<div class="empty">该病例无 checkpoint 定义（checkpoints.json 缺失或为空）。</div>';
  const paramsCell = (p) => {
    const empty = p == null || (typeof p === 'object' && Object.keys(p).length === 0);
    if (empty) return '<td class="mono">—</td>';
    const keyCount = Object.keys(p).length;
    const prettyParams = JSON.stringify(p, null, 2);
    return `<td><details class="params"><summary>params（${keyCount} 键）</summary><pre class="json">${esc(prettyParams)}</pre></details></td>`;
  };
  return `<div class="table-wrap"><table><thead><tr>
      <th>checkpoint_id</th><th>layer</th><th>description</th><th>eval_method</th><th>params</th>
    </tr></thead><tbody>${cps.map(c => `
      <tr>
        <td class="mono">${esc(c.checkpoint_id)}</td>
        <td>${esc(c.layer)}</td>
        <td>${esc(c.description)}</td>
        <td class="mono">${esc(c.eval_method ?? '—')}</td>
        ${paramsCell(c.params)}
      </tr>`).join('')}</tbody></table></div>`;
}

// -------------------- 流程 --------------------
async function selectRun(caseId, runId) {
  state.runId = runId;
  state.run = await fetchJSON(`/api/tasks/${caseId}/runs/${runId}`);
  $('overview').innerHTML = overviewHTML(state.task);
  renderRunSelector((state.task && state.task.runs) || []);
  renderTabs();
  renderActiveTab();
}

async function selectCase(caseId) {
  state.caseId = caseId;
  state.runId = null;
  state.run = null;
  await loadTasks(); // 更新侧边栏 active 高亮
  const task = await fetchJSON(`/api/tasks/${caseId}`);
  state.task = task;
  if (!task.runs.length) {
    $('overview').innerHTML = overviewHTML(task);
    renderRunSelector([]);
    $('tab-bar').innerHTML = '';
    $('tab-content').innerHTML = '<div class="empty">该病例暂无 run。运行评测后产物会出现在 runs/ 下。</div>';
    return;
  }
  await selectRun(caseId, task.runs[0].run_id);
}

async function refresh() {
  await loadTasks();
  if (!state.caseId) return;
  const task = await fetchJSON(`/api/tasks/${state.caseId}`);
  state.task = task;
  if (state.runId) await selectRun(state.caseId, state.runId);
  else if (task.runs.length) await selectRun(state.caseId, task.runs[0].run_id);
  else $('overview').innerHTML = overviewHTML(task);
}

document.addEventListener('DOMContentLoaded', () => {
  $('refresh-btn').addEventListener('click', () =>
    refresh().catch(e => { $('tab-content').innerHTML = `<div class="empty">刷新失败：${esc(e.message)}</div>`; }));
  loadTasks().catch(e => { $('sidebar-empty').textContent = '加载失败：' + e.message; });
});
