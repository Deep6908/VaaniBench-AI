'use strict';
const $ = id => document.getElementById(id);
let data, selected = new Set(), records = {baseline: {}, candidate: {}}, running = false, activeIds = [], jobId, completed = 0;
let resultFilter = 'all';
const busyControls = ['mode','baseline','candidate','confirm-live','reset-cases','clear-cases','case-search','preset-regression','preset-repeat','owner-auth','recorded-evidence','history-search','history-status','history-refresh','history-baseline','history-candidate','history-compare'];
const element = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
const score = c => { const values = (c?.metrics || []).filter(m => m.score !== null).map(m => m.score); return c?.status === 'ok' && values.length ? values.reduce((a,b) => a+b,0)/values.length : null; };
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function request(url, options) { const response = await fetch(url, options); const value = await response.json(); if (!response.ok) throw new Error(value.error || 'Request failed'); return value; }
function error(message) { $('error').textContent = message || ''; $('error').hidden = !message; }
function refreshControls() {
  $('cancel-run').hidden = !data.hosted || !running || !jobId;
  document.querySelectorAll('#history-list button').forEach(button=>{button.disabled=running;});
  const live = $('mode').value !== 'mock';
  $('selected-count').textContent = `${selected.size} / 6`;
  $('run').disabled = running || selected.size < 1 || selected.size > 6 || (live && (!$('confirm-live').checked || data.live_runs_remaining < 2));
  $('mode-pill').textContent = $('mode').value.toUpperCase();
  $('live-options').hidden = !live;
  $('judge').disabled = !live || running;
  $('mock-presets').hidden = live;
  $('run-label').textContent = running ? 'Evaluating…' : selected.size === 0 ? 'Choose a conversation' : 'Run comparison';
  if (!running && live && data.live_runs_remaining < 2) $('run-label').textContent = data.hosted ? 'Daily limit reached' : 'Session limit reached';
  $('run').classList.toggle('is-running', running);
  $('run').setAttribute('aria-busy', String(running));
  document.querySelectorAll('.scenario input').forEach(check => { check.disabled = running || (selected.size >= 6 && !check.checked); });
  if (data.hosted && live) { $('run-note').textContent = `Two budgeted runs. Daily UTC limits: ${data.daily_usage?.calls ?? 0}/${data.daily_usage?.max_calls ?? 0} attempts; USD ${data.daily_usage?.accounted_usd ?? 'unknown'}/${data.daily_usage?.max_usd ?? 'unknown'} accounted. Estimates are not invoices.`; return; }
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
    const c = data.scenarios.find(c => c.id === id) || {language:records.baseline[id]?.language || 'unknown',category:records.baseline[id]?.category || 'unknown',prompt:'Scenario is absent from the current catalog; inspect its saved run.'}; const detail = element('details', undefined, 'casecard'); detail.dataset.id = id; detail.open = open.has(id);
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
  error(); running = true; jobId=null; activeIds = data.scenarios.filter(c => selected.has(c.id)).map(c => c.id); completed = 0; records = {baseline:{},candidate:{}};
  $('empty').hidden = true; $('results').hidden = false; $('downloads').replaceChildren(); $('decision').textContent = 'Running'; $('decision-card').className = ''; $('delta').textContent = 'Waiting for both runs';
  $('progress').max = activeIds.length*2; $('progress').value = 0; $('progress-count').textContent = `0 / ${activeIds.length*2}`; $('session-state').textContent = 'Evaluation in progress';
  $('result-note').textContent = $('mode').value === 'mock' ? 'Mock fixture: injected degradation demonstrates the gate. These scores are not evidence of real-model quality.' : 'Live run: token-based USD estimates are not invoices. Judge ratings remain subjective and uncalibrated.';
  for (const id of busyControls) $(id).disabled = true;
  renderSelection(); renderCases(); updateScore('baseline'); updateScore('candidate');
  if (window.innerWidth < 760) $('experiment').scrollIntoView({behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block:'start'});
  try {
    const body=JSON.stringify({baseline:$('baseline').value,candidate:$('candidate').value,case_ids:activeIds,judge:$('judge').checked,confirm_live:$('confirm-live').checked});
    let pending; try { pending=JSON.parse(sessionStorage.getItem('vaanibench_submission')); } catch (_) {}
    const key=pending?.body===body ? pending.key : crypto.randomUUID();
    if(data.hosted) sessionStorage.setItem('vaanibench_submission',JSON.stringify({body,key}));
    const response = await request('/api/runs', {method:'POST',headers:{'Content-Type':'application/json','X-VaaniBench-Token':data.token,'Idempotency-Key':key},body});
    jobId = response.job_id;
    sessionStorage.removeItem('vaanibench_submission'); refreshControls();
    if (data.hosted) sessionStorage.setItem('vaanibench_active_job',JSON.stringify({id:jobId,ids:activeIds,mode:$('mode').value,baseline:$('baseline').value,candidate:$('candidate').value,judge:$('judge').checked}));
    await watchJob();
  } catch (e) { error(e.message); $('status-label').textContent = 'Run did not finish'; $('decision').textContent = 'Incomplete'; $('session-state').textContent = 'Attention required'; }
  finally {
    running = false; for (const id of busyControls) $(id).disabled = false;
    try { const fresh = await request('/api/bootstrap'); data.live_runs_remaining = fresh.live_runs_remaining; data.daily_usage = fresh.daily_usage; } catch (_) {}
    renderSelection(); refreshControls();
  }
}
async function watchJob() {
    let cursor = 0;
    while (true) {
      const snapshot = await request(`/api/jobs/${jobId}?after=${cursor}`); cursor = snapshot.cursor;
      for (const event of snapshot.events) {
        if (event.event === 'case_started') { records[event.side][event.scenario_id] = {status:'running'}; $('status-label').textContent = `${event.side === 'baseline' ? 'A / Baseline' : 'B / Candidate'} · ${event.scenario_id}`; }
        if (event.event === 'case_completed') { records[event.side][event.result.scenario_id] = event.result; completed++; $('progress').value = completed; $('progress-count').textContent = `${completed} / ${activeIds.length*2}`; updateScore(event.side); }
      } renderCases();
      if (['failed','interrupted','cancelled'].includes(snapshot.status)) {
        if (data.hosted) sessionStorage.removeItem('vaanibench_active_job');
        throw new Error(snapshot.error || 'Evaluation was interrupted. Start a new comparison.');
      }
      if (snapshot.status === 'completed') { finish(snapshot.result); break; }
      await wait(250);
    }
    if (data.hosted) sessionStorage.removeItem('vaanibench_active_job');
}

async function loadHistory() {
  const ops=await request('/api/operations');
  $('operations-summary').textContent=`Retained jobs: ${ops.retained_jobs}. Mock cases: ${ops.by_mode.mock}; live cases: ${ops.by_mode.live}. Daily API attempts: ${ops.daily_usage.calls}/${ops.daily_usage.max_calls}; accounted USD ${ops.daily_usage.accounted_usd}/${ops.daily_usage.max_usd}. ${ops.alerts.join(' ')}`;
  const result=await request('/api/history?q='+encodeURIComponent($('history-search').value)+'&status='+encodeURIComponent($('history-status').value));
  $('history-list').replaceChildren(); $('history-baseline').replaceChildren(); $('history-candidate').replaceChildren();
  for(const job of result.jobs) {
    const row=element('p'); row.append(element('span',`${new Date(job.created*1000).toLocaleString()} · ${job.status} · ${Object.values(job.configs).join(' / ')} `));
    const open=element('button','Open','auth-button'); open.type='button'; open.disabled=running;
    open.addEventListener('click',async()=>{try{
      const snapshot=await request('/api/jobs/'+job.id); if(!snapshot.result) throw new Error(snapshot.error || 'No completed results available');
      jobId=job.id; activeIds=snapshot.result.runs.baseline.cases.map(c=>c.scenario_id);
      records=Object.fromEntries(Object.entries(snapshot.result.runs).map(([side,run])=>[side,Object.fromEntries(run.cases.map(c=>[c.scenario_id,c]))]));
      resultFilter='all'; document.querySelectorAll('[data-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.filter==='all')));
      $('empty').hidden=true; $('results').hidden=false; $('downloads').replaceChildren();
      $('result-note').textContent='Saved evaluation · no new API calls. Review configuration and scoring coverage.';
      renderCases(); updateScore('baseline'); updateScore('candidate'); finish(snapshot.result);
    }catch(e){error(e.message);}}); row.append(open); $('history-list').append(row);
    if(job.status==='completed') for(const side of ['baseline','candidate']){const option=element('option',`${job.id.slice(0,8)} · ${job.configs.candidate}`);option.value=job.id;$('history-'+side).append(option);}
  }
  $('history-compare').disabled=!$('history-baseline').options.length;
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
  for (const name of result.downloads) { const link = element('a',name); link.href = `${result.download_base || '/api/jobs/'+jobId+'/download'}/${name}`; link.download = name; $('downloads').append(link); }
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
    $('session-label').textContent = data.hosted ? (data.authenticated ? 'Owner session' : 'Public demo') : 'Local session';
    $('owner-auth').hidden = !data.hosted || !data.login_available;
    $('owner-auth').textContent = data.authenticated ? 'Sign out' : 'Owner sign-in';
    $('recorded-evidence').hidden = !data.evidence_available;
    $('history-panel').hidden=!data.hosted || !data.authenticated;
    $('cancel-run').addEventListener('click',async()=>{try{
      $('cancel-run').disabled=true;
      await request('/api/jobs/'+jobId+'/cancel',{method:'POST',headers:{'X-VaaniBench-Token':data.token}});
      $('status-label').textContent='Cancellation requested; an active request may finish first.';
    }catch(e){error(e.message);}finally{$('cancel-run').disabled=false;}});
    $('history-refresh').addEventListener('click',()=>loadHistory().catch(e=>error(e.message)));
    $('history-compare').addEventListener('click',async()=>{try{
      const result=await request('/api/compare',{method:'POST',headers:{'Content-Type':'application/json','X-VaaniBench-Token':data.token},body:JSON.stringify({baseline_job:$('history-baseline').value,candidate_job:$('history-candidate').value,baseline_side:'candidate',candidate_side:'candidate'})});
      $('history-comparison').textContent=`${result.passed?'Pass':'Blocked'} · ${result.paired_cases} paired scored cases · delta ${result.mean_paired_delta ?? 'unknown'}. ${result.failures.join('; ')}`;
    }catch(e){$('history-comparison').textContent='Cannot compare: '+e.message+' (identical dataset, case selection and scoring settings are required).';}});
    if(data.hosted && data.authenticated) await loadHistory();
    $('owner-auth').addEventListener('click',async () => {
      if (!data.authenticated) { $('login-error').hidden=true; $('owner-dialog').showModal(); return; }
      try { await request('/api/logout',{method:'POST',headers:{'X-VaaniBench-Token':data.token}}); sessionStorage.removeItem('vaanibench_active_job'); location.reload(); } catch(e) { error(e.message); }
    });
    $('cancel-login').addEventListener('click',() => { $('owner-password').value=''; $('owner-dialog').close(); });
    $('owner-dialog').addEventListener('cancel',() => { $('owner-password').value=''; });
    $('owner-form').addEventListener('submit',async event => {
      event.preventDefault(); $('submit-login').disabled=true; $('login-error').hidden=true;
      try { await request('/api/login',{method:'POST',headers:{'Content-Type':'application/json','X-VaaniBench-Token':data.token},body:JSON.stringify({password:$('owner-password').value})}); sessionStorage.removeItem('vaanibench_active_job'); location.reload(); }
      catch(e) { $('login-error').textContent=e.message; $('login-error').hidden=false; }
      finally { $('owner-password').value=''; $('submit-login').disabled=false; }
    });
    $('recorded-evidence').addEventListener('click',async () => {
      try {
        const evidence=await request('/api/evidence'); activeIds=evidence.runs.baseline.cases.map(c=>c.scenario_id);
        records={baseline:Object.fromEntries(evidence.runs.baseline.cases.map(c=>[c.scenario_id,c])),candidate:Object.fromEntries(evidence.runs.candidate.cases.map(c=>[c.scenario_id,c]))};
        resultFilter='all'; document.querySelectorAll('[data-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.filter==='all')));
        $('empty').hidden=true; $('results').hidden=false; $('downloads').replaceChildren();
        $('result-note').textContent='Recorded real Groq run, not a new API call. Small synthetic sample; paid-equivalent estimates are not invoices.';
        renderCases(); updateScore('baseline'); updateScore('candidate'); finish(evidence);
        $('status-label').textContent='Recorded Groq benchmark · no new API calls';
      } catch(e) { error(e.message); }
    });
    modeChanged(); renderSelection();
    const saved=data.hosted && sessionStorage.getItem('vaanibench_active_job');
    if (saved) {
      try {
        const pending=JSON.parse(saved); jobId=pending.id; activeIds=pending.ids.filter(id=>data.scenarios.some(c=>c.id===id));
        if (!activeIds.length) throw new Error('No saved selection');
        if ([...$('mode').options].some(o=>o.value===pending.mode && !o.disabled)) { $('mode').value=pending.mode; modeChanged(); }
        selected=new Set(activeIds); for (const side of ['baseline','candidate']) if ([...$(side).options].some(o=>o.value===pending[side])) $(side).value=pending[side]; configPrompts();
        $('judge').checked=Boolean(pending.judge) && !$('judge').disabled;
        records={baseline:{},candidate:{}}; completed=0; running=true;
        $('empty').hidden=true; $('results').hidden=false; $('downloads').replaceChildren();
        $('progress').max=activeIds.length*2; $('progress').value=0; $('session-state').textContent='Resuming saved evaluation';
        $('result-note').textContent='Resumed evaluation. Inspect provider configuration and limitations before interpreting scores.';
        busyControls.forEach(id=>$(id).disabled=true); refreshControls();
        await watchJob();
      } catch(e) { sessionStorage.removeItem('vaanibench_active_job'); error('Could not resume: '+e.message); }
      finally { running=false; busyControls.forEach(id=>$(id).disabled=false); renderSelection(); refreshControls(); }
    }
  } catch (e) { error('Cannot load the local demo. '+e.message); }
}
init();
