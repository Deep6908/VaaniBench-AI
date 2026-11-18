'use strict';
const $ = id => document.getElementById(id);
let data, selected = new Set(), records = {baseline: {}, candidate: {}}, running = false, activeIds = [], jobId, completed = 0;
let resultFilter = 'all';
const element = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
const score = c => { const values = (c?.metrics || []).filter(m => m.score !== null).map(m => m.score); return c?.status === 'ok' && values.length ? values.reduce((a,b) => a+b,0)/values.length : null; };
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function request(url, options) { const response = await fetch(url, options); const value = await response.json(); if (!response.ok) throw new Error(value.error || 'Request failed'); return value; }
function error(message) { $('error').textContent = message || ''; $('error').hidden = !message; }
function refreshControls() {
  const live = $('mode').value !== 'mock';
  $('selected-count').textContent = `${selected.size} / 6`;
  $('run').disabled = running || selected.size < 1 || selected.size > 6 || (live && (!$('confirm-live').checked || data.live_runs_remaining < 2));
  $('mode-pill').textContent = $('mode').value.toUpperCase();
  $('live-options').hidden = !live;
  $('judge').disabled = !live || running;
  $('mock-presets').hidden = live;
  $('run-label').textContent = running ? 'Evaluating…' : selected.size === 0 ? 'Choose a conversation' : 'Run comparison';
  $('run').classList.toggle('is-running', running);
  $('run').setAttribute('aria-busy', String(running));
  document.querySelectorAll('.scenario input').forEach(check => { check.disabled = running || (selected.size >= 6 && !check.checked); });
  $('run-note').textContent = live ? `Two separate runs. Up to $0.20 estimated combined; ${data.live_runs_remaining} live runs remain in this server session. No paid fallback.` : 'Mock events use presentation pacing. Reported request latency excludes that delay.';
}
function renderSelection() {
  const container = $('scenarios'); container.replaceChildren();
  for (const c of data.scenarios) {
    const query = $('case-search').value.trim().toLowerCase();
    if (query && !`${c.id} ${c.language} ${c.category} ${c.prompt}`.toLowerCase().includes(query)) continue;
    const row = element('label', undefined, 'scenario'); const check = element('input'); check.type = 'checkbox'; check.checked = selected.has(c.id); check.disabled = running;
    check.addEventListener('change', () => { if (check.checked && selected.size < 6) selected.add(c.id); else { selected.delete(c.id); check.checked = false; } row.classList.toggle('selected', check.checked); refreshControls(); });
    row.classList.toggle('selected', check.checked);
    const copy = element('span'); copy.append(element('span', `${c.id} · ${c.language} · ${c.category}`, 'label'), element('span', c.prompt, 'description')); row.append(check, copy); container.append(row);
  } refreshControls();
}
function configPrompts() {
  for (const side of ['baseline','candidate']) $(''+side+'-prompt').textContent = data.configs.find(c => c.id === $(side).value)?.system_prompt || '';
  $('preset-regression').setAttribute('aria-pressed', String($('baseline').value === 'mock-baseline' && $('candidate').value === 'mock-degraded'));
  $('preset-repeat').setAttribute('aria-pressed', String($('baseline').value === 'mock-baseline' && $('candidate').value === 'mock-baseline'));
}
function modeChanged() {
  const mode = $('mode').value;
  $('case-search').value = '';
  selected = new Set(mode === 'mock' ? data.default_ids : [data.scenarios[0].id]);
  for (const side of ['baseline','candidate']) {
    $(side).replaceChildren();
    const configs = data.configs.filter(c => c.provider === mode);
    for (const c of configs) { const option = element('option', c.name); option.value = c.id; $(side).append(option); }
    $(side).selectedIndex = side === 'candidate' ? Math.min(1, configs.length-1) : 0;
  }
  $('judge').checked = false; $('confirm-live').checked = false; configPrompts(); renderSelection();
}
function responseCard(c, side) {
  const node = element('div', undefined, 'response'); node.append(element('p', side.toUpperCase(), 'eyebrow'));
  node.append(element('pre', c?.response?.text || (c?.status === 'running' ? 'Generating response…' : c?.error_code || 'Waiting for this case…')));
  if (c?.status && c.status !== 'running') {
    const s = score(c); node.append(element('p', `${c.status} · ${Number(c.latency_ms).toFixed(2)} ms · ${s === null ? 'not deterministically scored' : 'check score '+s.toFixed(2)}`, 'metric'));
    for (const m of c.metrics || []) node.append(element('p', `${m.name}: ${m.score === null ? 'not evaluated' : m.score} — ${m.reason}`, 'metric'));
    if (c.judge) { const {rationale, ...dimensions} = c.judge; node.append(element('p', 'Uncalibrated judge · '+Object.entries(dimensions).map(([k,v]) => `${k}: ${v}/5`).join(' · '), 'metric'), element('p', rationale, 'metric')); }
    if (c.judge_error) node.append(element('p', 'Judge: '+c.judge_error, 'metric'));
    if (c.trace_id) node.append(element('p', 'Trace '+c.trace_id, 'metric'));
  } return node;
}
function renderCases() {
  const open = new Set([...$('case-results').querySelectorAll('details[open]')].map(n => n.dataset.id));
  $('case-results').replaceChildren();
  for (const id of activeIds) {
    const c = data.scenarios.find(c => c.id === id); const detail = element('details', undefined, 'casecard'); detail.dataset.id = id; detail.open = open.has(id);
    const heading = element('summary'); const title = element('div'); title.append(element('span', `${id} / ${c.language} / ${c.category}`, 'caseid'), element('span', c.prompt, 'caseprompt'));
    const a = records.baseline[id], b = records.candidate[id]; heading.append(title, element('span', `${a?.status || 'waiting'} → ${b?.status || 'waiting'}  +`, 'casebadge'));
    const changed = a?.response && b?.response && a.response.text !== b.response.text;
    const review = [a,b].some(c => c && c.status !== 'running' && (score(c) === null || c.status !== 'ok' || c.judge_error));
    if (resultFilter === 'changed' && !changed || resultFilter === 'review' && !review) continue;
    const responses = element('div', undefined, 'responses'); responses.append(responseCard(a,'baseline'),responseCard(b,'candidate'));
    detail.append(heading, element('p', 'Rubric: '+c.rubric, 'rubric'), responses); $('case-results').append(detail);
  }
  $('no-results').hidden = $('case-results').childElementCount > 0;
}
function updateScore(side) {
  const cases = Object.values(records[side]).filter(c => c.status !== 'running'); const scores = cases.map(score).filter(s => s !== null);
  $(side+'-score').textContent = scores.length ? `${scores.filter(s => s === 1).length} / ${scores.length}` : '—';
  $(side+'-meta').textContent = `${cases.length} responses · ${cases.filter(c => c.status === 'error').length} errors · ${cases.length-scores.length} unscored`;
}
async function start() {
  resultFilter = 'all'; document.querySelectorAll('[data-filter]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.filter === 'all')));
  error(); running = true; activeIds = data.scenarios.filter(c => selected.has(c.id)).map(c => c.id); completed = 0; records = {baseline:{},candidate:{}};
  $('empty').hidden = true; $('results').hidden = false; $('downloads').replaceChildren(); $('decision').textContent = 'Running'; $('decision-card').className = ''; $('delta').textContent = 'Waiting for both runs';
  $('progress').max = activeIds.length*2; $('progress').value = 0; $('progress-count').textContent = `0 / ${activeIds.length*2}`; $('session-state').textContent = 'Evaluation in progress';
  $('result-note').textContent = $('mode').value === 'mock' ? 'Mock fixture: injected degradation demonstrates the gate. These scores are not evidence of real-model quality.' : 'Live run: token-based USD estimates are not invoices. Judge ratings remain subjective and uncalibrated.';
  for (const id of ['mode','baseline','candidate','confirm-live','reset-cases','clear-cases','case-search','preset-regression','preset-repeat']) $(id).disabled = true;
  renderSelection(); renderCases(); updateScore('baseline'); updateScore('candidate');
  if (window.innerWidth < 760) $('experiment').scrollIntoView({behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block:'start'});
  try {
    const response = await request('/api/runs', {method:'POST',headers:{'Content-Type':'application/json','X-VaaniBench-Token':data.token}, body:JSON.stringify({baseline:$('baseline').value,candidate:$('candidate').value,case_ids:activeIds,judge:$('judge').checked,confirm_live:$('confirm-live').checked})});
    jobId = response.job_id; let cursor = 0;
    while (true) {
      const snapshot = await request(`/api/jobs/${jobId}?after=${cursor}`); cursor = snapshot.cursor;
      for (const event of snapshot.events) {
        if (event.event === 'case_started') { records[event.side][event.scenario_id] = {status:'running'}; $('status-label').textContent = `${event.side === 'baseline' ? 'A / Baseline' : 'B / Candidate'} · ${event.scenario_id}`; }
        if (event.event === 'case_completed') { records[event.side][event.result.scenario_id] = event.result; completed++; $('progress').value = completed; $('progress-count').textContent = `${completed} / ${activeIds.length*2}`; updateScore(event.side); }
      } renderCases();
      if (snapshot.status === 'failed') throw new Error(snapshot.error);
      if (snapshot.status === 'completed') { finish(snapshot.result); break; }
      await wait(250);
    }
  } catch (e) { error(e.message); $('status-label').textContent = 'Run did not finish'; $('decision').textContent = 'Incomplete'; $('session-state').textContent = 'Attention required'; }
  finally {
    running = false; for (const id of ['mode','baseline','candidate','confirm-live','reset-cases','clear-cases','case-search','preset-regression','preset-repeat']) $(id).disabled = false;
    try { const fresh = await request('/api/bootstrap'); data.live_runs_remaining = fresh.live_runs_remaining; } catch (_) {}
    renderSelection(); refreshControls();
  }
}
function finish(result) {
  const decision = result.comparison;
  for (const side of ['baseline','candidate']) {
    const s = result.runs[side].summary;
    $(side+'-meta').textContent = `${s.successful}/${s.total} successful · ${s.not_scored} unscored · p95 ${s.latency_ms.p95?.toFixed(2)} ms · USD ${s.cost_usd ?? 'unknown'}`;
  }
  $('status-label').textContent = 'Both configurations evaluated'; $('session-state').textContent = 'Results saved';
  const incomplete = Object.values(result.runs).some(run => run.summary.errors || run.summary.skipped || run.summary.judge_errors || run.summary.stop_reason);
  $('decision').textContent = incomplete ? 'Incomplete' : decision.paired_cases === 0 ? 'Review' : decision.passed ? 'Pass' : 'Blocked';
  $('decision-card').className = decision.passed ? 'pass' : 'fail';
  $('delta').textContent = `${decision.paired_cases} paired · delta ${decision.mean_paired_delta === null ? 'n/a' : decision.mean_paired_delta.toFixed(3)}`;
  if (decision.failures.length) $('result-note').textContent += ' Gate: '+decision.failures.join('; ')+'.';
  const firstChanged = activeIds.find(id => records.baseline[id]?.response?.text !== records.candidate[id]?.response?.text) || activeIds[0];
  const firstDetail = [...$('case-results').children].find(n => n.dataset.id === firstChanged); if (firstDetail) firstDetail.open = true;
  for (const name of result.downloads) { const link = element('a',name); link.href = `/api/jobs/${jobId}/download/${name}`; link.download = name; $('downloads').append(link); }
}
async function init() {
  try {
    data = await request('/api/bootstrap'); selected = new Set(data.default_ids); $('dataset-version').textContent = 'DATASET v'+data.dataset_version;
    for (const provider of ['groq','openai']) { const option = $('mode').querySelector(`[value="${provider}"]`); option.disabled = !data.providers[provider]; option.textContent = provider === 'groq' ? `Groq · ${data.providers.groq ? 'live available' : 'unavailable'}` : `OpenAI · ${data.providers.openai ? 'live available' : 'unavailable'}`; }
    $('mode').addEventListener('change', modeChanged); for (const side of ['baseline','candidate']) $(side).addEventListener('change',configPrompts);
    $('confirm-live').addEventListener('change',refreshControls); $('run').addEventListener('click',start);
    $('reset-cases').addEventListener('click',() => { selected = new Set(data.default_ids); $('case-search').value = ''; renderSelection(); });
    $('clear-cases').addEventListener('click',() => { selected.clear(); renderSelection(); });
    $('case-search').addEventListener('input',renderSelection);
    for (const [id,candidate] of [['preset-regression','mock-degraded'],['preset-repeat','mock-baseline']]) $(id).addEventListener('click',() => { $('baseline').value='mock-baseline'; $('candidate').value=candidate; configPrompts(); refreshControls(); });
    document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click',() => { resultFilter=button.dataset.filter; document.querySelectorAll('[data-filter]').forEach(b => b.setAttribute('aria-pressed', String(b===button))); renderCases(); }));
    modeChanged(); renderSelection();
  } catch (e) { error('Cannot load the local demo. '+e.message); }
}
init();
