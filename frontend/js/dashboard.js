/* Mission Control dashboard: live /api/status polling, controls, task drawer, log filter and settings.
   The shared particle field (field.js) morphs to whichever section is in view. */
(() => {
  'use strict';
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const field = window.AgentField || {};
  let data = null;

  /* ---------- Navigation: active section drives the nav highlight and the field shape ---------- */
  const sections = [...document.querySelectorAll('main section')];
  const navLinks = [...document.querySelectorAll('.nav a')];
  const setActive = i => {
    navLinks.forEach(a => a.classList.toggle('active', +a.dataset.i === i));
    $('crumb').textContent = navLinks[i]?.textContent.replace(/\d+$/, '').trim() || 'Overview';
    field.progress = i;
  };
  const onScroll = () => {
    const y = innerHeight * .35;
    let idx = 0;
    sections.forEach((s, i) => { if (s.getBoundingClientRect().top <= y) idx = i; });
    if (innerHeight + scrollY >= document.documentElement.scrollHeight - 4) idx = sections.length - 1;
    setActive(idx);
  };
  addEventListener('scroll', onScroll, { passive: true }); onScroll();
  const side = $('side');
  $('menuBtn').addEventListener('click', () => { const open = side.classList.toggle('open'); $('menuBtn').setAttribute('aria-expanded', open); });
  navLinks.forEach(a => a.addEventListener('click', () => side.classList.remove('open')));

  if (!reduce && 'IntersectionObserver' in window) {
    const io = new IntersectionObserver(es => es.forEach(e => {
      if (!e.isIntersecting) return;
      [...e.target.children].forEach((c, i) => c.animate([{ transform: 'translateY(24px)', opacity: .2 }, { transform: 'none', opacity: 1 }],
        { duration: 700, delay: i * 60, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'backwards' }));
      io.unobserve(e.target);
    }), { threshold: .12 });
    sections.slice(1).forEach(s => io.observe(s));
  }

  /* ---------- Helpers ---------- */
  const shown = {};
  const countTo = (id, value, fmt = v => Math.round(v).toLocaleString()) => {
    const el = $(id), from = shown[id] ?? 0; shown[id] = value;
    if (reduce || from === value) { el.textContent = fmt(value); return; }
    const t0 = performance.now();
    const step = now => { const p = Math.min((now - t0) / 1000, 1); el.textContent = fmt(from + (value - from) * (1 - Math.pow(1 - p, 3))); if (p < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  };
  const toDate = v => { if (!v) return null; const d = typeof v === 'number' ? new Date(v * (v < 1e12 ? 1000 : 1)) : new Date(v); return isNaN(d) ? null : d; };
  const rel = v => {
    const d = toDate(v); if (!d) return v ? esc(v) : '—';
    const diff = (Date.now() - d) / 1000, a = Math.abs(diff);
    const s = a < 60 ? `${Math.round(a)}s` : a < 3600 ? `${Math.round(a / 60)}m` : a < 86400 ? `${Math.round(a / 3600)}h` : `${Math.round(a / 86400)}d`;
    return diff >= 0 ? `${s} ago` : `in ${s}`;
  };
  const abs = v => { const d = toDate(v); return d ? d.toLocaleString() : '—'; };
  const uptime = s => { s = Math.round(s); const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`; };
  const repoUrl = t => {
    if (t.pr_url && /^https:\/\//.test(t.pr_url)) return t.pr_url;
    const api = t.target_url || '';
    const m = api.match(/^https:\/\/api\.github\.com\/repos\/(.+)$/);
    if (m) return 'https://github.com/' + m[1].replace(/\/pulls\//, '/pull/');
    if (/^https:\/\/github\.com\//.test(api)) return api;
    return t.target && /^[\w.-]+\/[\w.-]+$/.test(t.target) ? `https://github.com/${t.target}` : null;
  };
  const isFailed = s => s === 'failed' || s === 'rejected';
  const toast = (msg, bad) => { const t = $('toast'); t.textContent = msg; t.className = 'toast' + (bad ? ' bad' : ''); t.hidden = false; clearTimeout(toast.h); toast.h = setTimeout(() => t.hidden = true, 5000); };

  /* ---------- Controls ---------- */
  async function post(path, body = {}) {
    const res = await fetch('/api/' + path, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-Agent-Control': '1' }, body: JSON.stringify(body), signal: AbortSignal.timeout(45000) });
    const d = await res.json().catch(() => ({}));
    if (!res.ok || d.status === 'error') throw new Error(d.error || `HTTP ${res.status}`);
    return d;
  }
  const labels = { 'pause-resume': 'Pause/resume', 'trigger-inbox': 'Inbox pass', 'trigger-hunt': 'Issue hunt', 'trigger-solve': 'Solve pass', stop: 'Stop' };
  async function control(act) {
    const btns = document.querySelectorAll('#controls .btn'); btns.forEach(b => b.disabled = true);
    try { const d = await post(act); toast(`${labels[act]}: ${d.message || 'done'}`); }
    catch (e) { toast(`${labels[act]} failed: ${e.message}`, true); }
    finally { btns.forEach(b => b.disabled = false); refresh(); }
  }
  let pending = null;
  const ask = (text, fn) => { pending = fn; $('confirmText').textContent = text; $('confirm').hidden = false; $('confirmYes').focus(); };
  $('confirmYes').addEventListener('click', () => { $('confirm').hidden = true; const f = pending; pending = null; f && f(); });
  $('confirmNo').addEventListener('click', () => { $('confirm').hidden = true; pending = null; });
  const runMenu = $('runMenu'), runBtn = $('runBtn');
  runBtn.addEventListener('click', e => { e.stopPropagation(); runMenu.hidden = !runMenu.hidden; runBtn.setAttribute('aria-expanded', !runMenu.hidden); });
  document.addEventListener('click', () => { runMenu.hidden = true; runBtn.setAttribute('aria-expanded', 'false'); });
  document.querySelectorAll('[data-act]').forEach(b => b.addEventListener('click', () => {
    const act = b.dataset.act; runMenu.hidden = true;
    if (act === 'stop') ask('Stop the agent? Workers shut down until you start it again from the terminal.', () => control('stop'));
    else control(act);
  }));

  /* ---------- Overview ---------- */
  function renderChart(tasks) {
    const W = 600, H = 200, P = { l: 28, r: 6, t: 10, b: 22 }, hours = 24, now = Date.now();
    const bins = Array.from({ length: hours }, () => ({ ok: 0, bad: 0, other: 0 }));
    tasks.forEach(t => {
      const d = toDate(t.created_at || t.started_at); if (!d) return;
      const h = Math.floor((now - d) / 3600000); if (h < 0 || h >= hours) return;
      const b = bins[hours - 1 - h];
      if (t.status === 'completed') b.ok++; else if (isFailed(t.status)) b.bad++; else b.other++;
    });
    const max = Math.max(4, ...bins.map(b => b.ok + b.bad + b.other));
    const step = Math.ceil(max / 4), top = step * 4;
    const iw = W - P.l - P.r, ih = H - P.t - P.b, bw = iw / hours;
    const y = v => P.t + ih - v / top * ih;
    let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">`;
    for (let v = 0; v <= top; v += step) svg += `<line class="gridline" x1="${P.l}" x2="${W - P.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${P.l - 6}" y="${y(v) + 3}" text-anchor="end">${v}</text>`;
    bins.forEach((b, i) => {
      const x = P.l + i * bw + bw * .18, w = bw * .64; let base = 0;
      svg += `<g class="col"><title>${hours - 1 - i === 0 ? 'This hour' : `${hours - 1 - i}h ago`}: ${b.ok} completed, ${b.bad} failed, ${b.other} other</title>`;
      [['ok', '#38bdf8'], ['bad', '#f43f5e'], ['other', '#6366f1']].forEach(([k, c]) => {
        if (!b[k]) return; const h = b[k] / top * ih;
        svg += `<rect class="b" x="${x}" y="${y(base) - h}" width="${w}" height="${Math.max(h - 1, 1)}" rx="2" fill="${c}"/>`; base += b[k];
      });
      svg += `<rect x="${P.l + i * bw}" y="${P.t}" width="${bw}" height="${ih}" fill="transparent"/></g>`;
      if (i % 6 === 0 || i === hours - 1) svg += `<text x="${x + w / 2}" y="${H - 6}" text-anchor="middle">${i === hours - 1 ? 'now' : `-${hours - 1 - i}h`}</text>`;
    });
    $('chart').innerHTML = svg + '</svg>';
  }

  function renderCats(tasks) {
    const by = {};
    tasks.forEach(t => { const k = t.category || t.type || 'other'; (by[k] ||= { ok: 0, bad: 0, other: 0, n: 0 }); by[k].n++; by[k][t.status === 'completed' ? 'ok' : isFailed(t.status) ? 'bad' : 'other']++; });
    const rows = Object.entries(by).sort((a, b) => b[1].n - a[1].n), max = Math.max(1, ...rows.map(r => r[1].n));
    $('cat-total').textContent = `${tasks.length} recent tasks`;
    $('cats').innerHTML = rows.length ? rows.map(([k, v]) => `<div class="cat"><span>${esc(k)}</span><div class="track" style="width:${v.n / max * 100}%">
      <i style="flex:${v.ok};background:var(--cyan)"></i><i style="flex:${v.bad};background:var(--rose)"></i><i style="flex:${v.other};background:var(--indigo)"></i></div><b>${v.n}</b></div>`).join('')
      : '<span class="muted">No tasks recorded yet.</span>';
  }

  /* ---------- Workers ---------- */
  function renderWorkers(workers) {
    $('workerList').innerHTML = workers.map(w => `
      <article class="worker" data-s="${esc(w.status)}">
        <span class="chip s-${esc(w.status)}">${esc(w.status)}</span>
        <h3>${esc(w.name)}</h3>
        <p>${esc(w.role)}</p>
        <div class="now">› ${esc(w.current_task || 'Idle')}</div>
        <dl><dt>Iterations</dt><dd>${(w.iteration ?? 0).toLocaleString()}</dd><dt>Last run</dt><dd>${rel(w.last_run)}</dd><dt>Next run</dt><dd>${rel(w.next_run)}</dd></dl>
      </article>`).join('');
  }

  /* ---------- Tasks ---------- */
  let filter = 'all', query = '', tasks = [];
  $('filters').addEventListener('click', e => {
    const b = e.target.closest('.filter'); if (!b) return; filter = b.dataset.f;
    $('filters').querySelectorAll('.filter').forEach(x => x.classList.toggle('active', x === b)); renderTasks();
  });
  $('taskSearch').addEventListener('input', e => { query = e.target.value.trim().toLowerCase(); renderTasks(); });
  function renderTasks() {
    const counts = { all: tasks.length, running: 0, completed: 0, failed: 0 };
    tasks.forEach(t => { if (t.status === 'running') counts.running++; if (t.status === 'completed') counts.completed++; if (isFailed(t.status)) counts.failed++; });
    Object.entries(counts).forEach(([k, v]) => $('f-' + k).textContent = v);
    const rows = tasks.filter(t => (filter === 'all' || t.status === filter || (filter === 'failed' && isFailed(t.status))) &&
      (!query || [t.title, t.target, t.target_repo, t.outcome, t.type, t.error].join(' ').toLowerCase().includes(query)));
    $('taskRows').innerHTML = rows.length ? rows.slice(0, 300).map(t => {
      const pr = t.pr_url && /^https:\/\//.test(t.pr_url) ? t.pr_url : null;
      const out = pr ? `<a href="${esc(pr)}" target="_blank" rel="noopener">${esc(pr.replace('https://github.com/', ''))}</a>`
        : isFailed(t.status) ? `<span class="err">${esc((t.error || t.outcome || 'Failed').slice(0, 120))}</span>` : esc((t.outcome || '—').slice(0, 120));
      return `<tr tabindex="0" data-id="${esc(t.id)}"><td><span class="chip s-${esc(t.status)}">${esc(t.status)}</span></td>
        <td><span class="title">${esc(t.title || t.type)}</span><span class="type">${esc(t.type)}</span></td>
        <td class="repo">${esc(t.target_repo || t.target)}</td><td class="time">${rel(t.created_at || t.started_at)}</td><td class="out">${out}</td></tr>`;
    }).join('') : `<tr><td colspan="5" class="empty">${tasks.length ? 'No tasks match this filter.' : 'No tasks yet. The hunter queues work on its next pass.'}</td></tr>`;
  }
  const openRow = e => { if (e.target.closest('a')) return; const tr = e.target.closest('tr[data-id]'); if (tr) openDrawer(tr.dataset.id); };
  $('taskRows').addEventListener('click', openRow);
  $('taskRows').addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openRow(e); } });

  /* ---------- Task drawer ---------- */
  let lastFocus = null;
  function openDrawer(id) {
    const t = tasks.find(x => x.id === id); if (!t) return;
    lastFocus = document.activeElement;
    $('d-status').textContent = t.status; $('d-status').className = 'chip s-' + t.status;
    $('d-title').textContent = t.title || t.type;
    const link = repoUrl(t), ev = t.details?.evaluation;
    const dur = toDate(t.started_at) && toDate(t.completed_at) ? `${((toDate(t.completed_at) - toDate(t.started_at)) / 1000).toFixed(1)}s` : '—';
    let html = `<dl>
      <dt>Repository</dt><dd>${link ? `<a href="${esc(link)}" target="_blank" rel="noopener">${esc(t.target_repo || t.target)}</a>` : esc(t.target_repo || t.target || '—')}</dd>
      <dt>Type</dt><dd>${esc(t.type)}${t.details?.subject_type ? ` · ${esc(t.details.subject_type)}` : ''}</dd>
      <dt>Started</dt><dd>${abs(t.started_at || t.created_at)}</dd>
      <dt>Duration</dt><dd>${dur}</dd>
      <dt>Mode</dt><dd>${t.details?.dry_run ? 'Dry run' : 'Live'}</dd>
      ${t.pr_url ? `<dt>Pull request</dt><dd><a href="${esc(t.pr_url)}" target="_blank" rel="noopener">${esc(t.pr_url)}</a></dd>` : ''}
    </dl>`;
    if (t.outcome) html += `<h4>Outcome</h4><div class="box">${esc(t.outcome)}</div>`;
    if (t.error && t.error !== t.outcome) html += `<h4>Error</h4><div class="box" style="color:var(--rose)">${esc(t.error)}</div>`;
    if (ev) {
      const c = Math.round((ev.confidence ?? 0) * 100);
      html += `<h4>AI evaluation</h4><div class="conf">${ev.should_respond ? 'Respond' : 'No reply needed'} · ${c}%<div class="bar-track"><i style="width:${c}%"></i></div></div>`;
      if (ev.rationale) html += `<div class="box">${esc(ev.rationale)}</div>`;
      if (ev.draft_response || ev.response) html += `<h4>Draft reply</h4><div class="box">${esc(ev.draft_response || ev.response)}</div>`;
    }
    if (t.diff_preview) html += `<h4>Diff</h4><pre>${esc(t.diff_preview).split('\n').map(l => `<span class="${l.startsWith('+') ? 'add' : l.startsWith('-') ? 'del' : l.startsWith('@@') ? 'hunk' : ''}">${l}</span>`).join('\n')}</pre>`;
    const rest = { ...t.details }; delete rest.evaluation;
    if (Object.keys(rest).length) html += `<h4>Details</h4><pre>${esc(JSON.stringify(rest, null, 2))}</pre>`;
    html += `<div class="muted">${esc(t.id)}</div>`;
    $('d-body').innerHTML = html;
    $('drawer').hidden = false; $('scrim').hidden = false; $('drawerClose').focus();
  }
  const closeDrawer = () => { $('drawer').hidden = true; $('scrim').hidden = true; lastFocus?.focus?.(); };
  $('drawerClose').addEventListener('click', closeDrawer); $('scrim').addEventListener('click', closeDrawer);
  addEventListener('keydown', e => { if (e.key === 'Escape') { closeDrawer(); side.classList.remove('open'); runMenu.hidden = true; } });

  /* ---------- Activity log ---------- */
  let level = 'all', logQuery = '', logs = [], lastLogKey = '';
  $('logFilters').addEventListener('click', e => { const b = e.target.closest('.filter'); if (!b) return; level = b.dataset.l; $('logFilters').querySelectorAll('.filter').forEach(x => x.classList.toggle('active', x === b)); lastLogKey = ''; renderLogs(); });
  $('logSearch').addEventListener('input', e => { logQuery = e.target.value.trim().toLowerCase(); lastLogKey = ''; renderLogs(); });
  function renderLogs() {
    const key = level + logQuery + logs.join('\n'); if (key === lastLogKey) return; lastLogKey = key;
    const parsed = logs.map(l => { const m = l.match(/^(\S*)\s*\[(\w+)\]\s*([^:]+):\s*(.*)$/); return m ? { time: m[1], lvl: m[2], comp: m[3], msg: m[4], raw: l } : { time: '', lvl: 'INFO', comp: '', msg: l, raw: l }; });
    const errs = parsed.filter(p => p.lvl === 'ERROR').length;
    $('n-errors').textContent = errs; $('n-errors').hidden = !errs;
    const rows = parsed.filter(p => (level === 'all' || p.lvl === 'ERROR') && (!logQuery || p.raw.toLowerCase().includes(logQuery)));
    const hl = s => { const e = esc(s); if (!logQuery) return e; const q = esc(logQuery).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); return e.replace(new RegExp(q, 'gi'), m => `<mark>${m}</mark>`); };
    const term = $('logs');
    term.innerHTML = rows.length ? rows.slice(-200).map(p => {
      const cls = p.lvl === 'ERROR' ? 'r' : /SUCCESS|PR|MERGE|COMPLETE/i.test(p.comp) ? 'g' : 'c';
      return `<div class="line"><span class="k">${esc(p.time.replace('T', ' ').slice(0, 19))}</span> <span class="${cls}">${hl(p.comp)}</span> ${hl(p.msg)}</div>`;
    }).join('') : `<span class="k">${logs.length ? 'No events match.' : 'No events recorded yet.'}</span>`;
    if ($('follow').checked) term.scrollTop = term.scrollHeight;
  }

  /* ---------- Settings ---------- */
  let dirty = false;
  const form = $('settingsForm');
  form.addEventListener('input', () => { dirty = true; $('formMsg').textContent = 'Unsaved changes'; $('formMsg').className = 'form-msg'; });
  function fillSettings(force) {
    if (!data || (dirty && !force)) return;
    const c = data.config || {};
    $(c.dry_run ? 'mode-dry' : 'mode-live').checked = true;
    const models = c.allowed_models || [c.model]; const sel = $('set-model');
    sel.innerHTML = models.map(m => `<option value="${esc(m)}"${m === c.model ? ' selected' : ''}>${esc(m)}</option>`).join('');
    $('set-concurrency').value = c.max_concurrent_tasks ?? ''; $('set-inbox').value = c.polling_interval_inbox ?? ''; $('set-hunt').value = c.polling_interval_issues ?? '';
    const ro = [['Provider', c.ai_provider], ['Max PRs/day', data.max_prs_per_day], ['Languages', (data.target_languages || []).join(', ')], ['Labels', (data.target_labels || []).join(', ')]].filter(r => r[1]);
    $('readonly').innerHTML = ro.map(([k, v]) => `<span>${esc(k)}: <b>${esc(v)}</b></span>`).join('');
    dirty = false;
  }
  $('resetBtn').addEventListener('click', () => { fillSettings(true); $('formMsg').textContent = ''; });
  form.addEventListener('submit', e => {
    e.preventDefault();
    if (!form.checkValidity()) { form.reportValidity(); return; }
    const c = data?.config || {}, live = $('mode-live').checked;
    const body = { model: $('set-model').value, max_concurrent_tasks: +$('set-concurrency').value, polling_interval_inbox: +$('set-inbox').value, polling_interval_issues: +$('set-hunt').value, dry_run: !live };
    const save = async () => {
      $('saveBtn').disabled = true;
      try { const d = await post('settings', body); dirty = false; $('formMsg').textContent = d.message || 'Settings saved'; $('formMsg').className = 'form-msg'; toast('Settings saved'); refresh(); }
      catch (err) { $('formMsg').textContent = err.message; $('formMsg').className = 'form-msg bad'; }
      finally { $('saveBtn').disabled = false; }
    };
    if (live && c.dry_run) ask('Switch to LIVE? The agent will post replies and open real pull requests under your account.', save); else save();
  });

  /* ---------- Render + poll ---------- */
  function render(d) {
    data = d;
    const status = String(d.status || 'UNKNOWN').toUpperCase(), m = d.metrics || {}, workers = Object.values(d.workers || {});
    const ok = ['RUNNING', 'INITIALIZING'].includes(status), bad = ['DISCONNECTED', 'ERROR', 'STOPPED'].includes(status);
    tasks = d.tasks || []; logs = d.recent_logs || [];

    $('statusDot').className = 'dot ' + (ok ? 'ok' : bad ? 'bad' : 'warn');
    $('statusText').textContent = status.charAt(0) + status.slice(1).toLowerCase();
    $('agentMeta').textContent = `${d.account || '—'} · ${d.model || '—'}`;
    $('modeChip').textContent = d.mode === 'LIVE' ? 'LIVE' : 'DRY RUN'; $('modeChip').className = 'chip ' + (d.mode === 'LIVE' ? 'live' : 'dry');
    const paused = ['PAUSED', 'STOPPED', 'STOPPING', 'DISCONNECTED'].includes(status);
    $('btnPause').textContent = paused ? 'Resume' : 'Pause';
    $('barSub').textContent = `${d.account || 'agent'} · updated ${new Date().toLocaleTimeString()}`;
    const running = tasks.filter(t => t.status === 'running').length;
    $('lede').textContent = `${d.account || 'The agent'} is ${status.toLowerCase()} in ${d.mode === 'LIVE' ? 'live' : 'dry-run'} mode. ${m.active_workers ?? 0} of ${workers.length} workers active, ${running} task${running === 1 ? '' : 's'} running.`;
    $('n-workers').textContent = m.active_workers ?? 0; $('n-tasks').textContent = tasks.length;

    const failed = tasks.filter(t => isFailed(t.status)).length;
    const day = tasks.filter(t => { const dt = toDate(t.created_at); return dt && Date.now() - dt < 86400000; });
    countTo('k-done', m.tasks_completed || 0); $('k-done-sub').textContent = `${day.filter(t => t.status === 'completed').length} in last 24h`;
    countTo('k-inbox', m.inbox_processed || 0); $('k-inbox-sub').textContent = `${tasks.filter(t => t.type === 'inbox_notification').length} notifications seen`;
    countTo('k-prs', m.prs_opened || 0); $('k-prs-sub').textContent = `${tasks.filter(t => t.pr_url && t.details?.dry_run).length} dry-run drafts`;
    countTo('k-fail', failed); $('k-fail-sub').textContent = tasks.length ? `${Math.round(failed / tasks.length * 100)}% of recent tasks` : '—';

    const rem = m.rate_limit_remaining, lim = m.rate_limit_limit;
    if (rem != null && lim) { const p = Math.max(0, Math.min(1, rem / lim)); $('rl-text').textContent = `${rem.toLocaleString()} / ${lim.toLocaleString()}`; $('rl-bar').style.width = `${p * 100}%`; $('rl-bar').classList.toggle('low', p < .1); }
    else { $('rl-text').textContent = 'Not reported yet'; $('rl-bar').style.width = '0'; }
    const ai = d.ai_health || {};
    const aiOk = /^(ok|healthy|ready|verified)$/i.test(ai.state || '');
    $('ai-state').innerHTML = `<span class="${aiOk ? 's-running' : ai.configured === false ? 's-error' : 's-pending'}">${esc(ai.state || 'unknown')}</span>`;
    $('ai-model').textContent = `${ai.provider || '—'} · ${ai.model || d.model || '—'}${ai.last_error ? ` · ${ai.last_error}` : ''}`;
    $('k-uptime').textContent = m.uptime_seconds ? uptime(m.uptime_seconds) : 'Not running';
    const it = d.iterations || {}; $('k-iter').textContent = `inbox ${it.inbox ?? 0} · hunter ${it.hunter ?? 0} passes`;

    renderChart(tasks); renderCats(tasks); renderWorkers(workers); renderTasks(); renderLogs(); fillSettings();
    field.energy = .1 + Math.min((m.active_workers || 0) / 3, 1) * .9;
    field.error = workers.some(w => w.status === 'error') ? 1 : 0;
  }

  let timer;
  const refresh = () => { clearTimeout(timer); poll(); };
  async function poll() {
    try {
      const res = await fetch('/api/status', { credentials: 'same-origin', headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(15000) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      render(await res.json()); $('error').hidden = true;
    } catch (e) {
      $('error').hidden = false; $('error').textContent = `Can't reach the agent (${e.message}). Start it with ./run.sh, then this page reconnects on its own.`;
      $('statusDot').className = 'dot bad'; $('statusText').textContent = 'Offline'; field.error = 1;
    } finally { timer = setTimeout(poll, document.hidden ? 15000 : 3000); }
  }
  poll();
})();
