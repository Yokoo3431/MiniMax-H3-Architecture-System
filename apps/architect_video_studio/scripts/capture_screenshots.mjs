// Capture UX screenshots only from an isolated loopback synthetic fixture.
// Usage: node capture_screenshots.mjs <mock_loopback_url> <out_dir> <fixture-project-a> <fixture-job-a> <fixture-project-b>

import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const [baseArg, outArg, projectAArg, jobAArg, projectBArg] = process.argv.slice(2);
let BASE;
let OUT;
let PROJ_A;
let JOB_A;
let PROJ_B;
try {
  if (![baseArg, outArg, projectAArg, jobAArg, projectBArg].every(Boolean)) {
    throw new Error('explicit loopback mock URL, output directory, and fixture IDs are required');
  }
  const target = new URL(baseArg);
  if (target.protocol !== 'http:' ||
      !['127.0.0.1', 'localhost', '[::1]'].includes(target.hostname) ||
      !target.port || target.port === '8788' || target.username || target.password ||
      !['', '/'].includes(target.pathname) || target.search || target.hash) {
    throw new Error('target must be an isolated loopback mock server, not the Studio service');
  }
  const fixtureId = /^(?:fixture|synthetic)-[A-Za-z0-9_-]{1,80}$/;
  if (![projectAArg, jobAArg, projectBArg].every((value) => fixtureId.test(value))) {
    throw new Error('project and Job identifiers must be synthetic fixture IDs');
  }
  BASE = target.origin;
  OUT = outArg;
  PROJ_A = projectAArg;
  JOB_A = jobAArg;
  PROJ_B = projectBArg;
} catch (e) {
  console.error('UNSAFE_SCREENSHOT_TARGET', e.message);
  process.exit(2);
}
const CDP_PORT = 9444;

mkdirSync(OUT, { recursive: true });
const profileDir = join(tmpdir(), `avs-shot-${randomUUID()}`);
let chrome = null;
let browserWs = null;
let cdp = null;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function launchChrome() {
  const args = [
    `--remote-debugging-port=${CDP_PORT}`,
    `--user-data-dir=${profileDir}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-background-networking',
    '--window-size=1680,1000',
    '--hide-scrollbars',
    '--headless=new',
    '--disable-extensions',
    '--disable-gpu',
  ];
  chrome = spawn(CHROME, [...args, 'about:blank'], { stdio: 'ignore' });
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`);
      if (r.ok) return await r.json();
    } catch {}
    await sleep(500);
  }
  throw new Error('chrome cdp not ready');
}

class CDP {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
      }
    });
  }
  static async connect(wsUrl) {
    const ws = new WebSocket(wsUrl);
    await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej); });
    return new CDP(ws);
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  close() { try { this.ws.close(); } catch {} }
}

async function evalJs(cdp, expression) {
  const r = await cdp.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  return r.result?.value;
}

async function shot(cdp, name) {
  // Full-page capture so below-fold panels (Generation Panel etc.) are visible.
  const r = await cdp.send('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: true,
    fromSurface: true,
  });
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(r.data, 'base64'));
  console.log('shot:', name);
}

async function open(cdp, url, waitMs = 1800) {
  await cdp.send('Page.navigate', { url });
  await sleep(waitMs);
}

async function main() {
  const version = await launchChrome();
  browserWs = await CDP.connect(version.webSocketDebuggerUrl);
  const { targetId } = await browserWs.send('Target.createTarget', { url: 'about:blank' });
  await sleep(500);
  const targets = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)).json();
  const page = targets.find((t) => t.id === targetId) ?? targets.find((t) => t.type === 'page');
  cdp = await CDP.connect(page.webSocketDebuggerUrl);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');

  const pages = [
    ['home', `${BASE}/index.html`],
    ['workspace_a_completed', `${BASE}/workspace.html?project=${PROJ_A}`],
    ['workspace_b_gate', `${BASE}/workspace.html?project=${PROJ_B}`],
    ['job_center', `${BASE}/jobs.html?project=${PROJ_A}`],
    ['output_review', `${BASE}/output.html?job=${JOB_A}`],
  ];
  for (const [name, url] of pages) {
    await open(cdp, url);
    if (name === 'workspace_b_gate') {
      // Demonstrate the risk-review gate: checkbox unchecked -> Generate disabled.
      await evalJs(cdp, `document.getElementById('risk-check').checked = false; updateGate(); 'ok'`);
      await sleep(300);
    }
    await shot(cdp, name);
  }

  // Show the enabled Generate state after risk review on project B.
  await open(cdp, `${BASE}/workspace.html?project=${PROJ_B}`);
  await evalJs(cdp, `document.getElementById('risk-check').checked = true; updateGate(); 'ok'`);
  await sleep(300);
  await shot(cdp, 'workspace_b_risk_reviewed');

  console.log('DONE');
}

async function cleanup() {
  if (cdp) cdp.close();
  if (browserWs) browserWs.close();
  if (chrome && chrome.exitCode === null) {
    await new Promise((resolve) => {
      const timer = setTimeout(resolve, 5000);
      chrome.once('exit', () => {
        clearTimeout(timer);
        resolve();
      });
      chrome.kill();
    });
  }
  try {
    // This directory is unique to this invocation and contains only its
    // temporary Chrome profile/cache; screenshots remain in OUT.
    rmSync(profileDir, { recursive: true, force: true });
  } catch (e) {
    console.error('PROFILE_CLEANUP_FAILED', e?.code ?? 'UNKNOWN');
  }
}

main().catch((e) => {
  console.error('CAPTURE_FAILED', e);
  process.exitCode = 1;
}).finally(cleanup);
