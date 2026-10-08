// Capture UX screenshots only from an isolated loopback synthetic fixture.
// Usage: node capture_screenshots.mjs <mock_loopback_url> <out_dir> <fixture-project-a> <fixture-job-a> <fixture-project-b>

import { createRequire } from 'node:module';
import { randomUUID } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const [baseArg, outArg, projectAArg, jobAArg, projectBArg] = process.argv.slice(2);
let BASE;
let OUT;
let PROJ_A;
let JOB_A;
let PROJ_B;
const syntheticSystemEnvironment = {
  overall: 'SYNTHETIC AUDIT',
  installation_status: 'SYNTHETIC_ONLY',
  setup_completed: false,
  paths: {
    native_root: 'SYNTHETIC_RUNTIME_PATH_NOT_DISCLOSED',
    models_root: 'SYNTHETIC_MODELS_PATH_NOT_DISCLOSED',
    configured: false,
    runtime_role: 'SYNTHETIC_AUDIT',
  },
  environment_sources: {active: {source: 'synthetic-audit-fixture'}},
  production_gates: {synthetic_audit_only: true},
  gates: {comfyui_present: true, synthetic_audit_only: true},
  system: {
    os: 'Synthetic Windows',
    gpu_hardware: {status: 'NOT_TESTED', ready: false, name: 'Synthetic GPU (not probed)', vram_gb: null},
    driver: {status: 'NOT_TESTED', ready: false, version: 'synthetic'},
    runtime_cuda: {status: 'NOT_TESTED', ready: false, torch_imported: false},
    hardware_policy: {label: 'Synthetic audit fixture', status: 'EXPERIMENTAL', reason: 'Synthetic-only screen data.'},
    gpu_ready: false,
    gpu_detail: 'Synthetic-only audit data; host hardware was not queried.',
    deployment_profile: 'SYNTHETIC',
    profile_hardware_source: 'synthetic-fixture',
    free_commit: 0,
    free_commit_policy: {status: 'NOT_TESTED'},
    disk_free_gb: 0,
    environment_probe: {probe_status: 'NOT_TESTED', last_probe_finished: null},
  },
  runtime: {
    present: false, version: 'SYNTHETIC', frontend: 'SYNTHETIC',
    baseline_comparison: 'NOT_TESTED', pread: false, port: 'SYNTHETIC',
    path: 'SYNTHETIC_PATH_NOT_DISCLOSED',
  },
  models: {ready: 0, count: 0, status: 'SYNTHETIC_ONLY', items: [], h3_asset_status: {ready: false, status: 'NOT_TESTED'}},
  support: {},
  skill: {status: 'SYNTHETIC_ONLY', generation_allowed: false},
  workflows: {ready: 0, count: 0, items: []},
};
const syntheticInstallPlan = {
  components: ['comfyui_runtime', 'minimax_h3_nodes', 'video_helper_suite', 'dit', 'text_encoder', 'video_vae', 'audio_vae']
    .map((component_id) => ({
      component_id, name: 'Synthetic audit placeholder', version: 'SYNTHETIC',
      status: 'SYNTHETIC', type: component_id === 'comfyui_runtime' ? 'runtime' : 'fixture',
      source: 'SYNTHETIC_ONLY', source_status: 'SYNTHETIC_ONLY', target: 'NOT_APPLICABLE',
      expected_size: 0,
    })),
  blocked_reasons: ['SYNTHETIC_AUDIT_ONLY'],
  download_size_bytes: 0,
  required_disk_bytes: 0,
  available_disk_gb: null,
};
const syntheticSystemResponses = {
  '/api/system/environment': syntheticSystemEnvironment,
  '/api/system/install-plan': syntheticInstallPlan,
  '/api/system/desktop-settings': {startup_enabled: false, tray_minimized: false},
  '/api/system/runtime-update/status': {candidate_root: null, candidate_ready: false, active_root_exists: false, rollback_available: false},
  '/api/system/engine-status': {state: 'STOPPED'},
};
try {
  if (![baseArg, outArg, projectAArg, jobAArg, projectBArg].every(Boolean)) {
    throw new Error('explicit loopback mock URL, output directory, and fixture IDs are required');
  }
  const target = new URL(baseArg);
  if (target.protocol !== 'http:' ||
      !['127.0.0.1', 'localhost', '[::1]'].includes(target.hostname) ||
      target.port !== '10204' || target.username || target.password ||
      !['', '/'].includes(target.pathname) || target.search || target.hash) {
    throw new Error('target must be the isolated synthetic mock on loopback port 10204');
  }
  const fixtureId = /^(?:fixture|synthetic)-[A-Za-z0-9_-]{1,80}$/;
  const seededProjectId = /^proj-[a-f0-9]{12}$/;
  const seededJobId = /^job-[a-f0-9]{12}$/;
  if (![projectAArg, projectBArg].every((value) => fixtureId.test(value) || seededProjectId.test(value)) ||
      !(fixtureId.test(jobAArg) || seededJobId.test(jobAArg))) {
    throw new Error('project and Job identifiers must be synthetic fixture or isolated-seed IDs');
  }
  BASE = target.origin;
  OUT = outArg;
  PROJ_A = projectAArg;
  JOB_A = jobAArg;
  PROJ_B = projectBArg;
} catch (error) {
  console.error('UNSAFE_SCREENSHOT_TARGET', error.message);
  process.exit(2);
}

mkdirSync(OUT, { recursive: true });
let browser = null;
const captures = [];
async function capture(name, page) {
  const path = join(OUT, `${name}.png`);
  await page.screenshot({ path, fullPage: false, animations: 'disabled' });
  const metrics = await page.evaluate(() => ({
    title: document.title,
    viewportWidth: innerWidth,
    viewportHeight: innerHeight,
    documentWidth: document.documentElement.scrollWidth,
    documentHeight: document.documentElement.scrollHeight,
    horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  }));
  captures.push({name, path, ...metrics});
  console.log('shot:', name);
}

async function open(url, page, waitMs = 1800) {
  const target = new URL(url);
  target.searchParams.set('__avs_audit', randomUUID());
  await page.goto(target.href, { waitUntil: 'domcontentloaded', timeout: 15000 });
  await page.waitForTimeout(waitMs);
}

async function main() {
  browser = await chromium.launch({
    executablePath: EDGE,
    headless: true,
    args: ['--disable-background-networking', '--disable-extensions', '--disable-gpu'],
  });

  const pages = [
    ['home', `${BASE}/index.html`],
    ['workspace_a_completed', `${BASE}/workspace.html?project=${PROJ_A}`],
    ['job_center', `${BASE}/jobs.html?project=${PROJ_A}`],
    ['output_review', `${BASE}/output.html?job=${JOB_A}`],
    ['environment', `${BASE}/setup.html`],
  ];
  const viewports = [
    { id: 'mobile_375x812', width: 375, height: 812 },
    { id: 'tablet_768x1024', width: 768, height: 1024 },
    { id: 'desktop_1280x800', width: 1280, height: 800 },
  ];
  for (const viewport of viewports) {
    const context = await browser.newContext({
      viewport: { width: viewport.width, height: viewport.height },
      deviceScaleFactor: 1,
      isMobile: viewport.width < 500,
    });
    await context.route('**/*', async (route) => {
      const requestUrl = new URL(route.request().url());
      if (requestUrl.origin !== BASE) return route.abort();
      if (requestUrl.pathname.startsWith('/api/system/')) {
        const value = syntheticSystemResponses[requestUrl.pathname]
          || {ok: true, applied: false, state: 'SYNTHETIC_ONLY', message: 'Synthetic audit only; no host operation.'};
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ok: true, data: value}),
        });
      }
      return route.continue();
    });
    const page = await context.newPage();
    for (const [name, url] of pages) {
      await open(url, page);
      if (name === 'home' && viewport.id === 'desktop_1280x800') {
        console.log('home-status:', JSON.stringify(await page.evaluate(() => ({
          environment: document.getElementById('sys-status')?.innerText,
          service: document.querySelector('.engine-label')?.innerText,
        }))));
      }
      await capture(`${name}_${viewport.id}`, page);
    }
    await context.close();
  }
  writeFileSync(join(OUT, 'responsive_manifest.json'), JSON.stringify({syntheticOnly: true, viewports, captures}, null, 2));
  console.log('DONE');
}

async function cleanup() {
  if (browser) await browser.close().catch((error) => console.error('BROWSER_CLEANUP_FAILED', error?.message ?? 'UNKNOWN'));
}

main().catch((error) => {
  console.error('CAPTURE_FAILED', error);
  process.exitCode = 1;
}).finally(cleanup);
