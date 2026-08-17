// PATCH2.6-B - verify prototype pages rendered (DOM state, no error banners).
// Usage: node verify_pages.mjs <base_url> <project_a> <job_a> <project_b>

import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const BASE = process.argv[2] ?? 'http://127.0.0.1:8788';
const PROJ_A = process.argv[3];
const JOB_A = process.argv[4];
const PROJ_B = process.argv[5];
const CDP_PORT = 9455;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let chrome = null;

async function launch() {
  chrome = spawn(CHROME, [
    `--remote-debugging-port=${CDP_PORT}`, `--user-data-dir=${join(tmpdir(), `avs-verify-${Date.now()}`)}`,
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  ], { stdio: 'ignore' });
  for (let i = 0; i < 60; i++) {
    try { const r = await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`); if (r.ok) return; } catch {}
    await sleep(400);
  }
  throw new Error('cdp not ready');
}

async function main() {
  await launch();
  const version = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`)).json();
  const ws = new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej); });
  let id = 0;
  const pending = new Map();
  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg.result); pending.delete(msg.id); }
  });
  const send = (method, params = {}) => new Promise((res) => {
    pending.set(++id, res); ws.send(JSON.stringify({ id, method, params }));
  });
  const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
  await sleep(500);
  const targets = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)).json();
  const page = targets.find((t) => t.id === targetId);
  const pageWs = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { pageWs.addEventListener('open', res); pageWs.addEventListener('error', rej); });
  let pid = 0;
  const pp = new Map();
  pageWs.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pp.has(msg.id)) { pp.get(msg.id)(msg.result); pp.delete(msg.id); }
  });
  const psend = (method, params = {}) => new Promise((res) => {
    pp.set(++pid, res); pageWs.send(JSON.stringify({ id: pid, method, params }));
  });
  await psend('Page.enable');
  await psend('Runtime.enable');
  const evalJs = async (expr) => (await psend('Runtime.evaluate', { expression: expr, returnByValue: true })).result?.value;

  const checks = [
    ['home', `${BASE}/index.html`, `({title: document.title, heading: document.querySelector('h2').textContent, studyCards: document.querySelectorAll('.task-card').length, newStudy: document.getElementById('new-video-btn').textContent, errVisible: !!document.querySelector('#err') && document.getElementById('err').style.display !== 'none'})`],
    ['workspace_a', `${BASE}/workspace.html?project=${PROJ_A}`, `({title: document.title, refs: document.querySelectorAll('.ref-item').length, refDrawerCollapsed: document.getElementById('drawer-reference').classList.contains('collapsed'), intentCard: !!document.querySelector('.intent-card'), shelf: document.getElementById('param-shelf').style.display !== 'none', viewport: !!document.querySelector('.viewport'), chip: document.getElementById('v-mode-chip').textContent, paramsOverlay: document.getElementById('v-params').textContent, outputCardItems: document.querySelectorAll('.oc-item').length, cameraButtons: document.querySelectorAll('#camera-seg button').length, promptCollapsed: !document.getElementById('prompt-wrap').classList.contains('open'), advancedHidden: document.getElementById('adv-card').classList.contains('hidden'), generateDisabled: document.getElementById('generate-btn').disabled, errVisible: !!document.querySelector('#err') && document.getElementById('err').style.display !== 'none'})`],
    ['workspace_b', `${BASE}/workspace.html?project=${PROJ_B}`, `({title: document.title, refs: document.querySelectorAll('.ref-item').length, intentCard: !!document.querySelector('.intent-card'), shelf: document.getElementById('param-shelf').style.display !== 'none', promptLen: document.getElementById('prompt-preview').textContent.length, generateDisabled: document.getElementById('generate-btn').disabled, gateNote: document.getElementById('gate-note').textContent, strategies: document.querySelectorAll('.strategy').length, groups: document.querySelectorAll('.ctl-group').length})`],
    ['jobs', `${BASE}/jobs.html?project=${PROJ_A}`, `({title: document.title, rows: document.querySelectorAll('#jobs-body tr').length, errVisible: !!document.querySelector('#err') && document.getElementById('err').style.display !== 'none'})`],
    ['output', `${BASE}/output.html?job=${JOB_A}`, `({title: document.title, pkgTreeLen: document.getElementById('pkg-tree').textContent.length, errVisible: !!document.querySelector('#err') && document.getElementById('err').style.display !== 'none'})`],
  ];
  for (const [name, url, expr] of checks) {
    await psend('Page.navigate', { url });
    await sleep(1600);
    const state = await evalJs(expr);
    console.log(name, JSON.stringify(state));
  }
  ws.close(); pageWs.close(); chrome.kill();
}

main().catch((e) => { console.error('VERIFY_FAILED', e); if (chrome) chrome.kill(); process.exit(1); });
