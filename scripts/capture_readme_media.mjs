// Captures README screenshots and animation frames from a running dashboard server.
// Usage: node scripts/capture_readme_media.mjs [baseUrl] [outDir]
// Needs Google Chrome; frames are stitched into GIF/MP4 with ffmpeg by scripts/build_readme_media.sh.
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { join } from 'node:path';

const BASE = process.argv[2] || 'http://127.0.0.1:3000';
const OUT = process.argv[3] || 'docs/media';
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORT = 9333;
const W = 1440, H = 900;
const sleep = ms => new Promise(r => setTimeout(r, ms));

mkdirSync(OUT, { recursive: true });
const profile = join(OUT, '.chrome-profile');
const chrome = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  `--window-size=${W},${H}`, '--hide-scrollbars', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--force-device-scale-factor=1', 'about:blank'], { stdio: 'ignore' });

let ws, id = 0;
const pending = new Map();
const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); });

async function connect() {
  for (let i = 0; i < 50; i++) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
      const page = targets.find(t => t.type === 'page');
      if (page) {
        ws = new WebSocket(page.webSocketDebuggerUrl);
        await new Promise(r => ws.addEventListener('open', r, { once: true }));
        ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(m.error.message)) : p.res(m.result); } });
        return;
      }
    } catch {}
    await sleep(200);
  }
  throw new Error('Chrome did not start');
}

const evaluate = expr => send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }).then(r => r.result.value);
async function shot(file, opts = {}) {
  const { data } = await send('Page.captureScreenshot', { format: opts.format || 'png', quality: opts.quality, captureBeyondViewport: false });
  writeFileSync(join(OUT, file), Buffer.from(data, 'base64'));
}
async function open(path, wait = 4500) {
  await send('Page.navigate', { url: BASE + path });
  await sleep(wait);
}
async function frames(dir, count, step) {
  rmSync(join(OUT, dir), { recursive: true, force: true }); mkdirSync(join(OUT, dir), { recursive: true });
  for (let i = 0; i < count; i++) {
    await step(i);
    await sleep(60);
    const { data } = await send('Page.captureScreenshot', { format: 'jpeg', quality: 85 });
    writeFileSync(join(OUT, dir, `f${String(i).padStart(4, '0')}.jpg`), Buffer.from(data, 'base64'));
  }
}

try {
  await connect();
  await send('Page.enable'); await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false });

  // Homepage: logo assembly intro, then hero still, then a scroll-through.
  await send('Page.navigate', { url: BASE + '/home.html' });
  await frames('frames-intro', 40, async () => { await sleep(40); });
  await sleep(1500);
  await shot('home-hero.png');
  const homeH = await evaluate('document.documentElement.scrollHeight - innerHeight');
  await frames('frames-scroll', 120, async i => { await evaluate(`window.scrollTo(0, ${Math.round(homeH * (i / 119) ** 1.1)})`); });
  for (const [id, file] of [['how', 'home-how.png'], ['guardrails', 'home-guardrails.png']]) {
    await evaluate(`document.getElementById('${id}').scrollIntoView()`); await sleep(1400); await shot(file);
  }

  // Dashboard sections.
  await open('/dashboard.html');
  await shot('dashboard-overview.png');
  for (const [id, file] of [['workers', 'dashboard-workers.png'], ['tasks', 'dashboard-tasks.png'], ['activity', 'dashboard-activity.png'], ['settings', 'dashboard-settings.png']]) {
    await evaluate(`document.getElementById('${id}').scrollIntoView()`); await sleep(1600); await shot(file);
  }
  const dashH = await evaluate('document.documentElement.scrollHeight - innerHeight');
  await evaluate('window.scrollTo(0,0)'); await sleep(1200);
  await frames('frames-dashboard', 100, async i => { await evaluate(`window.scrollTo(0, ${Math.round(dashH * i / 99)})`); });
  console.log('captured to', OUT);
} finally {
  try { ws?.close(); } catch {}
  chrome.kill();
  await sleep(300);
  rmSync(profile, { recursive: true, force: true });
}
