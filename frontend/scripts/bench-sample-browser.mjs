/**
 * Time `sample()` in a real browser, not in Node.
 *
 *     node frontend/scripts/bench-sample-browser.mjs [path-to-calibration.json]
 *
 * **Why this exists.** `docs/RESEARCH_calibration_cost.md` measured a calibration at 1.67 s
 * in Node and could not rule out that a browser — where users actually are — is several times
 * slower. `RESEARCH_gcsim_embed.md` had recorded a large browser penalty on `simulate`, which
 * made the worry concrete. That question blocked A.3 (parallel calibration in Web Workers):
 * if a browser were much slower, a full run returns to minutes and workers matter.
 *
 * **Not wired into CI.** It needs a Chrome binary, and a timing measurement is not a pass/fail
 * gate — a slow machine would fail it for being slow. It is here so the number can be
 * re-derived rather than trusted, which is the standing rule for every measurement in this
 * repo.
 *
 * Driven over CDP with Node's built-in `WebSocket`, so it adds no dependency. It looks for
 * Playwright's cached `chrome-headless-shell`; point `CHROME_HEADLESS_SHELL` at another
 * binary if yours lives elsewhere.
 */

import { spawn } from 'node:child_process';
import { copyFileSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { dirname, extname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const GCSIM = join(HERE, '..', 'gcsim');
const PORT = 8099;
const CDP_PORT = 9333;

const SHELL = process.env.CHROME_HEADLESS_SHELL
  ?? '/root/.cache/ms-playwright/chromium_headless_shell-1208/chrome-headless-shell-linux64'
     + '/chrome-headless-shell';

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/** A calibration pair. Falls back to the committed rotation fixture so it runs with no args. */
function configs() {
  const path = process.argv[2];
  if (path) {
    const parsed = JSON.parse(readFileSync(path, 'utf8'));
    return { baseline: parsed.baseline, probe: parsed.probe };
  }
  const text = readFileSync(join(GCSIM, 'emitted', 'rotation_calibrated.txt'), 'utf8');
  // No probe fixture is committed; the probe differs from the baseline by one stat, and for a
  // *timing* run the second config only needs to be the same shape.
  return { baseline: text, probe: text };
}

const PAGE = `<!doctype html><meta charset="utf-8"><body><pre id="out">running…</pre>
<script src="wasm_exec.js"></script>
<script>
window.__done = false;
(async () => {
  const t0 = performance.now();
  const go = new Go();
  const bytes = await (await fetch('gcsim.wasm')).arrayBuffer();
  const { instance } = await WebAssembly.instantiate(bytes, go.importObject);
  go.run(instance);
  await new Promise(r => setTimeout(r, 50));
  const load = performance.now() - t0;
  const cfg = await (await fetch('configs.json')).json();
  const t = { baseline: [], probe: [] };
  sample(cfg.baseline, '12345');                       // warm-up, as in the Node table
  for (let i = 0; i < 5; i++) {
    let a = performance.now(); sample(cfg.baseline, '12345'); t.baseline.push(performance.now() - a);
    a = performance.now(); sample(cfg.probe, '12345');    t.probe.push(performance.now() - a);
  }
  const mean = (xs) => xs.reduce((s, x) => s + x, 0) / xs.length;
  window.__result = {
    wasmLoadMs: Math.round(load),
    baselineMs: Math.round(mean(t.baseline)),
    probeMs: Math.round(mean(t.probe)),
    calibrationMs: Math.round(mean(t.baseline) + mean(t.probe)),
    cores: navigator.hardwareConcurrency,
    ua: navigator.userAgent,
  };
  document.getElementById('out').textContent = JSON.stringify(window.__result);
  window.__done = true;
})().catch((e) => { window.__result = { error: String(e) }; window.__done = true; });
</script>`;

const root = mkdtempSync(join(tmpdir(), 'gcsim-bench-'));
copyFileSync(join(GCSIM, 'wasm_exec.js'), join(root, 'wasm_exec.js'));
copyFileSync(join(GCSIM, 'gcsim.wasm'), join(root, 'gcsim.wasm'));
writeFileSync(join(root, 'configs.json'), JSON.stringify(configs()));
writeFileSync(join(root, 'index.html'), PAGE);

const TYPES = { '.js': 'text/javascript', '.wasm': 'application/wasm',
  '.json': 'application/json', '.html': 'text/html' };
const server = createServer((req, res) => {
  const name = req.url === '/' ? '/index.html' : req.url.split('?')[0];
  try {
    const body = readFileSync(join(root, name));
    res.writeHead(200, { 'content-type': TYPES[extname(name)] ?? 'application/octet-stream' });
    res.end(body);
  } catch {
    res.writeHead(404).end();
  }
});
await new Promise((r) => server.listen(PORT, '127.0.0.1', r));

const chrome = spawn(SHELL, [
  '--headless', '--no-sandbox', '--disable-gpu',
  `--remote-debugging-port=${CDP_PORT}`,
  `--user-data-dir=${join(root, 'profile')}`,
  'about:blank',
], { stdio: 'ignore' });

let ws;
try {
  let target;
  for (let i = 0; i < 60 && !target; i += 1) {
    await wait(500);
    try {
      const list = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)).json();
      target = list.find((t) => t.type === 'page')?.webSocketDebuggerUrl;
    } catch { /* not up yet */ }
  }
  if (!target) throw new Error(`no page target; is ${SHELL} present?`);

  ws = new WebSocket(target);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let id = 0;
  const pending = new Map();
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  };
  const send = (method, params = {}) => new Promise((res) => {
    const mine = id += 1;
    pending.set(mine, res);
    ws.send(JSON.stringify({ id: mine, method, params }));
  });

  await send('Runtime.enable');
  await send('Page.navigate', { url: `http://127.0.0.1:${PORT}/index.html` });
  // 41 MB of wasm and eleven samples: polled rather than given a guessed timeout.
  for (let i = 0; i < 240; i += 1) {
    await wait(1000);
    const done = await send('Runtime.evaluate', { expression: 'window.__done === true' });
    if (done.result?.result?.value === true) break;
  }
  const out = await send('Runtime.evaluate', {
    expression: 'JSON.stringify(window.__result)', returnByValue: true,
  });
  console.log(out.result?.result?.value ?? 'no result');
} finally {
  ws?.close();
  chrome.kill();
  server.close();
}
