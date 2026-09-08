/* Architect Video Studio H3 handoff bridge.
 *
 * This runs as a normal ComfyUI extension. DesktopShell only navigates to the
 * query URL; this bridge waits for the persisted workflow/tab restore, then
 * creates and opens a real ComfyWorkflow target before loading the graph.
 */
(() => {
  "use strict";

  const BRIDGE_NAME = "ArchitectVideoStudio.H3WorkflowBridge";
  const STUDIO_ORIGIN = "http://127.0.0.1:8788";
  const TARGET_PREFIX = "workflows/Architect Video Studio/";
  const META_KEY = "architect_video_studio_h3";

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function queryTarget() {
    const params = new URL(location.href).searchParams;
    return {
      jobId: params.get("h3_job") || "",
      snapshotId: params.get("h3_snapshot") || "",
    };
  }

  function showStatus(text, ok) {
    const id = "architect-video-studio-h3-status";
    let node = document.getElementById(id);
    if (!node) {
      node = document.createElement("div");
      node.id = id;
      document.body.appendChild(node);
    }
    node.textContent = text;
    node.style.cssText = [
      "position:fixed", "z-index:2147483647", "right:18px", "top:14px",
      "max-width:560px", "padding:7px 10px", "border-radius:4px",
      `background:${ok ? "#1f7a4d" : "#8a3030"}`,
      "color:#fff", "font:12px Segoe UI,sans-serif",
      "box-shadow:0 1px 5px rgba(0,0,0,.28)", "white-space:pre-wrap",
    ].join(";");
  }

  function ensureReturnButton() {
    const id = "architect-video-studio-return";
    if (document.getElementById(id) || !document.body) return;
    const button = document.createElement("button");
    button.id = id;
    button.textContent = "返回 Studio";
    button.style.cssText = [
      "position:fixed", "z-index:2147483647", "right:12px", "top:42px",
      "height:24px", "padding:0 8px", "border:1px solid rgba(255,255,255,.35)",
      "border-radius:4px", "background:rgba(36,105,180,.82)", "color:#fff",
      "font:12px Segoe UI,sans-serif", "box-shadow:0 1px 5px rgba(0,0,0,.28)",
      "cursor:pointer", "opacity:.86",
    ].join(";");
    button.onclick = () => { location.href = `${STUDIO_ORIGIN}/index.html?new=1`; };
    document.body.appendChild(button);
  }

  function frontendModuleUrl() {
    const resources = performance.getEntriesByType("resource")
      .map((entry) => entry.name)
      .filter((name) => /\/assets\/settingStore-[^/]+\.js(?:\?|$)/.test(name));
    return resources[0] || "";
  }

  async function loadWorkflowServices() {
    const url = frontendModuleUrl();
    if (!url) throw new Error("ComfyUI setting store module is not loaded");
    const module = await import(url);
    // 1.48.7 exports the workflow store as A (useWorkflowStore) and the
    // workflow service as K. `nt` is the workspace store in this build and is
    // intentionally not accepted as a workflow-store fallback. The named
    // fallback keeps this bridge readable against an unminified dev build,
    // while the duck-typing check below protects against export drift.
    const storeFactory = module.A || module.useWorkflowStore;
    const serviceFactory = module.K || module.useWorkflowService;
    if (typeof storeFactory !== "function" || typeof serviceFactory !== "function") {
      throw new Error("ComfyUI workflow store/service exports are unavailable");
    }
    const store = storeFactory();
    const service = serviceFactory();
    if (!store || typeof store.createTemporary !== "function" ||
        typeof store.getWorkflowByPath !== "function" ||
        typeof service.openWorkflow !== "function") {
      throw new Error("ComfyUI workflow store contract is incompatible");
    }
    return { store, service };
  }

  async function waitForRestore(app, store) {
    let previous = "";
    let stable = 0;
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const active = store.activeWorkflow;
      const signature = active ? `${active.path}|${active.activeState?.id || ""}` : "";
      const graphReady = typeof app.isGraphReady === "boolean"
        ? app.isGraphReady
        : !!app.graph;
      if (app.vueAppReady && graphReady && !app.configuringGraph && signature) {
        stable = signature === previous ? stable + 1 : 0;
        previous = signature;
        if (stable >= 3) return;
      } else {
        stable = 0;
        previous = "";
      }
      await sleep(250);
    }
    throw new Error("ComfyUI workflow persistence restore did not become idle");
  }

  async function waitForComfyReady(app) {
    let stable = 0;
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const graphReady = typeof app.isGraphReady === "boolean"
        ? app.isGraphReady
        : !!app.graph;
      if (app.vueAppReady && graphReady && !app.configuringGraph) {
        stable += 1;
        if (stable >= 3) return;
      } else {
        stable = 0;
      }
      await sleep(250);
    }
    throw new Error("ComfyUI app did not become ready for H3 handoff");
  }

  async function fetchHandoff(target) {
    const endpoint = `${STUDIO_ORIGIN}/api/system/current-workflow?job_id=${encodeURIComponent(target.jobId)}`;
    const response = await fetch(endpoint, { cache: "no-store" });
    if (!response.ok) throw new Error(`AVS workflow fetch failed: HTTP ${response.status}`);
    const envelope = await response.json();
    const data = envelope.data || {};
    if (data.job_id !== target.jobId || data.snapshot_id !== target.snapshotId) {
      throw new Error("AVS handoff identity does not match the URL query");
    }
    if (!data.ui_workflow || !Array.isArray(data.ui_workflow.nodes)) {
      throw new Error("AVS handoff has no UI workflow graph");
    }
    return data;
  }

  function targetPath(data, target) {
    return `${TARGET_PREFIX}${target.jobId} — ${data.workflow_id}.json`;
  }

  function activeIdentity(store) {
    const active = store.activeWorkflow;
    return active?.activeState?.extra?.[META_KEY] || active?.initialState?.extra?.[META_KEY] || null;
  }

  async function verifyActive(app, store, target, data) {
    await waitForRestore(app, store);
    const active = store.activeWorkflow;
    const identity = activeIdentity(store);
    if (!active || !identity || identity.job_id !== target.jobId ||
        identity.snapshot_id !== target.snapshotId ||
        identity.workflow_id !== data.workflow_id) {
      throw new Error("active workflow identity is not the requested H3 Job");
    }
    const prompt = await app.graphToPrompt();
    const apiWorkflow = prompt?.output || prompt;
    if (!apiWorkflow || Array.isArray(apiWorkflow) || typeof apiWorkflow !== "object") {
      throw new Error("ComfyUI did not serialize an API workflow");
    }
    const response = await fetch(`${STUDIO_ORIGIN}/api/system/verify-workflow`, {
      method: "POST",
      headers: { "Content-Type": "text/plain;charset=UTF-8" },
      body: JSON.stringify({
        job_id: target.jobId,
        snapshot_id: target.snapshotId,
        workflow: apiWorkflow,
      }),
    });
    if (!response.ok) throw new Error(`AVS workflow verification failed: HTTP ${response.status}`);
    const envelope = await response.json();
    const result = envelope.data || {};
    if (!result.verified) {
      const details = (result.differences?.inputs || []).slice(0, 4).map((item) => {
        const describe = (value) => {
          if (!value || value.kind === "missing") return "missing";
          if (value.kind === "link") return `link(${value.node_id},${value.slot})`;
          if (value.kind === "string") return `string(${value.length},${value.sha256})`;
          return `${value.kind}:${String(value.value ?? value.sha256 ?? "?")}`;
        };
        return `${item.node_id}.${item.input} ${describe(item.expected)}→${describe(item.actual)}`;
      }).join("; ");
      throw new Error(`CURRENT ✕: ${result.reason || "WORKFLOW_IDENTITY_MISMATCH"} ` +
        `(nodes ${result.node_count ?? "?"}/${result.expected_node_count ?? "?"}, ` +
        `SHA ${(result.workflow_hash || "").slice(0, 12)}/${(result.expected_workflow_hash || "").slice(0, 12)}` +
        `${details ? `; diff ${details}` : ""})`);
    }
    return result;
  }

  async function bindExactWorkflow() {
    const target = queryTarget();
    if (!target.jobId || !target.snapshotId) return;
    const app = window.comfyAPI?.app?.app || window.app;
    if (!app || typeof app.registerExtension !== "function") {
      throw new Error("ComfyUI app API is unavailable");
    }
    const { store, service } = await loadWorkflowServices();
    await waitForComfyReady(app);
    const data = await fetchHandoff(target);
    const path = targetPath(data, target);
    const current = activeIdentity(store);
    if (current?.job_id === target.jobId && current?.snapshot_id === target.snapshotId) {
      const verified = await verifyActive(app, store, target, data);
      showStatus(`已绑定：${data.workflow_id} · ${verified.node_count} nodes · SHA ${verified.workflow_hash.slice(0, 12)} · CURRENT ✓`, true);
      return;
    }

    const existing = store.getWorkflowByPath(path);
    if (existing) await service.closeWorkflow(existing, { warnIfUnsaved: false });
    const workflow = store.createTemporary(path.slice("workflows/".length), data.ui_workflow);
    await service.openWorkflow(workflow, { force: true });
    await app.loadGraphData(data.ui_workflow, true, true, workflow, {
      openSource: "architect_video_studio_h3_job",
      deferWarnings: true,
      skipAssetScans: true,
      silentAssetErrors: true,
    });
    const verified = await verifyActive(app, store, target, data);
    showStatus(`已绑定：${data.workflow_id} · ${verified.node_count} nodes · SHA ${verified.workflow_hash.slice(0, 12)} · CURRENT ✓`, true);
  }

  function setup() {
    ensureReturnButton();
    const target = queryTarget();
    if (!target.jobId || !target.snapshotId) return;
    if (window.__avsH3BridgeScheduled || window.__avsH3BridgePromise) return;
    window.__avsH3BridgeScheduled = true;
    // ComfyUI invokes extension setup from app.setup(), before GraphCanvas
    // restores workflow tabs. Do not await the handoff here or startup can
    // deadlock until waitForRestore times out.
    setTimeout(() => {
      window.__avsH3BridgePromise = bindExactWorkflow().catch((error) => {
        console.error(`[${BRIDGE_NAME}]`, error);
        showStatus(`H3 工作流加载失败：${error.message}`, false);
      });
    }, 0);
  }

  const app = window.comfyAPI?.app?.app || window.app;
  if (app && typeof app.registerExtension === "function") {
    app.registerExtension({ name: BRIDGE_NAME, setup });
  }
})();
