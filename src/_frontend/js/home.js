/* Homepage: scroll drives the particle field and section reveals; live numbers come from /api/status. */
(() => {
  'use strict';
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const $ = id => document.getElementById(id);
  const field = window.AgentField || {};

  // Hero: logo sits to the right of the copy on wide screens.
  const place = () => { field.offsetX = innerWidth > 1200 ? 3.8 : innerWidth > 900 ? 3 : 0; field.scale = innerWidth > 900 ? 1 : .8; };
  addEventListener('resize', place); place();

  const onScroll = () => {
    const max = document.documentElement.scrollHeight - innerHeight;
    const p = max > 0 ? Math.min(Math.max(scrollY / max, 0), 1) : 0;
    $('progress').style.transform = `scaleX(${p})`;
    const shapes = (field.names || [1, 2, 3, 4, 5]).length - 1;
    field.progress = p * shapes;
    // Ease the logo back to centre once you leave the hero.
    const heroOut = Math.min(scrollY / innerHeight, 1);
    field.offsetX = (innerWidth > 1200 ? 3.8 : innerWidth > 900 ? 3 : 0) * (1 - heroOut);
  };
  addEventListener('scroll', onScroll, { passive: true }); onScroll();

  if (!reduce && 'IntersectionObserver' in window) {
    const io = new IntersectionObserver(entries => entries.forEach(en => {
      if (!en.isIntersecting) return;
      en.target.querySelectorAll(':scope > *, .step-copy > *').forEach((c, i) => c.animate(
        [{ transform: 'translateY(32px)', opacity: .15, filter: 'blur(6px)' }, { transform: 'none', opacity: 1, filter: 'none' }],
        { duration: 900, delay: i * 60, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'backwards' }));
      io.unobserve(en.target);
    }), { threshold: .2 });
    document.querySelectorAll('main section:not(.hero)').forEach(s => io.observe(s));
    document.querySelectorAll('.hero-copy > *').forEach((c, i) => c.animate(
      [{ transform: 'translateY(24px)', opacity: 0 }, { transform: 'none', opacity: 1 }],
      { duration: 1000, delay: 300 + i * 90, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'backwards' }));
  }

  const countTo = (el, value) => {
    if (reduce) { el.textContent = value.toLocaleString(); return; }
    const start = performance.now();
    const step = now => { const p = Math.min((now - start) / 1400, 1); el.textContent = Math.round(value * (1 - Math.pow(1 - p, 3))).toLocaleString(); if (p < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  };

  fetch('/api/status', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
    .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
    .then(d => {
      const status = String(d.status || 'unknown').toUpperCase(), m = d.metrics || {};
      const ok = ['RUNNING', 'INITIALIZING'].includes(status);
      $('pillDot').className = 'dot ' + (ok ? 'ok' : status === 'PAUSED' ? 'warn' : 'bad');
      $('pillText').textContent = `${d.account || 'agent'} · ${status.toLowerCase()} · ${d.mode === 'LIVE' ? 'live' : 'dry run'}`;
      field.energy = .1 + Math.min((m.active_workers || 0) / 3, 1) * .9;
      const io = new IntersectionObserver(([e]) => {
        if (!e.isIntersecting) return; io.disconnect();
        countTo($('s-tasks'), m.tasks_completed || 0); countTo($('s-inbox'), m.inbox_processed || 0); countTo($('s-prs'), m.prs_opened || 0);
        if (m.rate_limit_remaining != null) countTo($('s-api'), m.rate_limit_remaining); else $('s-api').textContent = '—';
      });
      io.observe($('live'));
    })
    .catch(() => {
      $('pillDot').className = 'dot bad'; $('pillText').textContent = 'Agent offline · start it with ./run.sh';
      $('liveNote').textContent = 'The agent is not reachable right now, so live numbers are unavailable.';
    });
})();
