import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "apps" / "architect_video_studio" / "frontend"
PAGES = {
    "index.html": "app-home",
    "workspace.html": "app-study",
    "jobs.html": "app-jobs",
    "output.html": "app-output",
    "setup.html": "app-environment",
}


class StudioUX2P1Tests(unittest.TestCase):
    def read(self, name):
        return (FRONTEND / name).read_text(encoding="utf-8")

    def test_shell_switch_is_reversible_and_default_on(self):
        source = self.read("js/ux2_shell.js")
        self.assertIn("params.get('ux2') !== '0'", source)
        self.assertIn("dataset.ux2 = enabled ? 'on' : 'off'", source)
        self.assertIn("data-nav-study", source)
        self.assertIn("restoreLegacyContext", source)
        self.assertIn("ux2-legacy-crumb", source)
        theme = self.read("js/theme.js")
        self.assertIn("STORAGE_KEY = 'avs-theme'", theme)
        self.assertIn("localStorage", theme)

    def test_environment_group_navigation_binds_shoelace_hosts(self):
        setup_html = self.read("setup.html")
        setup_script = self.read("js/setup.js")
        self.assertIn('<sl-button data-g="runtime"', setup_html)
        self.assertIn("document.querySelectorAll('#group-nav sl-button[data-g]')", setup_script)
        self.assertEqual(setup_script.count("document.querySelectorAll('#group-nav sl-button[data-g]')"), 2)
        self.assertNotIn("document.querySelectorAll('#group-nav button')", setup_script)

    def test_all_primary_pages_have_shared_shell_and_navigation(self):
        viewport = '<meta name="viewport" content="width=device-width, initial-scale=1">'
        for name, body_class in PAGES.items():
            source = self.read(name)
            self.assertIn(viewport, source, name)
            self.assertIn('data-ux2="on"', source, name)
            self.assertIn('js/ux2_shell.js', source, name)
            self.assertIn(f'class="app-shell {body_class}"', source, name)
            self.assertIn('id="main-content"', source, name)
            self.assertRegex(source, r'<main id="main-content" tabindex="-1"', name)
            self.assertLess(source.index('class="skip-link"'), source.index('<header'), name)
            self.assertLess(source.index('<header'), source.index('id="main-content"'), name)
            for label in ("首页", "Study", "任务", "输出", "环境"):
                self.assertRegex(source, rf">{label}</a>", name)
        home = self.read("js/home.js")
        card = re.search(r'<article class="task-card">(?P<body>.*?)</article>`;', home, re.S)
        self.assertIsNotNone(card)
        body = card.group("body")
        self.assertIn('<a class="task-card-main"', body)
        self.assertIn('href="workspace.html?project=${encodeURIComponent(p.id)}"', body)
        self.assertIn("const studyName = String(p.name || '未命名 Study');", home)
        self.assertIn("function escAttr(text)", home)
        self.assertIn("replace(/\"/g, '&quot;').replace(/'/g, '&#39;')", home)
        self.assertIn('aria-label="打开 Study：${escAttr(studyName)}"', body)
        self.assertIn('<button type="button" class="btn small ghost" data-action="rename" data-project="${escAttr(p.id)}" aria-label="重命名 Study：${escAttr(studyName)}">', body)
        self.assertIn('<button type="button" class="btn small ghost" data-action="duplicate" data-project="${escAttr(p.id)}" aria-label="复制 Study：${escAttr(studyName)}">', body)
        self.assertIn('<button type="button" class="btn small ghost danger" data-action="delete" data-project="${escAttr(p.id)}" aria-label="删除 Study：${escAttr(studyName)}">', body)
        self.assertLess(body.index('</a>'), body.index('<div class="task-actions">'))
        self.assertNotIn("onclick=", body)
        self.assertIn(".app-home .task-card-main:focus-visible", self.read("css/studio.css"))
        focus_link_css = self.read("css/studio.css")
        self.assertIn(".skip-link:focus {", focus_link_css)
        self.assertIn("position:relative;", focus_link_css)
        self.assertIn("width:max-content;", focus_link_css)
        self.assertIn("margin:8px 12px;", focus_link_css)

        for name in PAGES:
            source = self.read(name)
            self.assertRegex(
                source,
                r'<div id="err" class="error-banner" role="alert" '
                r'aria-live="assertive" aria-atomic="true"',
                name,
            )
        for name in ("js/output.js", "js/setup.js"):
            source = self.read(name)
            self.assertIn("errEl.setAttribute('role', 'alert')", source)
            self.assertIn("errEl.setAttribute('aria-live', 'assertive')", source)
            self.assertIn("errEl.setAttribute('role', 'status')", source)
            self.assertIn("errEl.setAttribute('aria-live', 'polite')", source)

    def test_home_cards_wrap_unbroken_names_and_mobile_actions(self):
        global_css = self.read("css/avs_global_theme.css")
        self.assertIn(".app-home .task-card .ttl > span:first-child { overflow-wrap: anywhere; }", global_css)
        self.assertIn(".app-home .task-card-main,", global_css)
        self.assertIn(".app-home .task-actions {", global_css)
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr));", global_css)
        self.assertIn(".app-home .task-actions > sl-button { width: 100%; min-width: 0; }", global_css)

    def test_readonly_fields_follow_shared_light_and_dark_theme_tokens(self):
        global_css = self.read("css/avs_global_theme.css")
        self.assertIn(".app-shell .readonly-field {", global_css)
        self.assertIn("background: var(--avs-control-bg);", global_css)
        self.assertIn("color: var(--avs-text-secondary);", global_css)

    def test_ready_badge_does_not_claim_runtime_execution_is_available(self):
        for name in ("js/home.js", "js/workspace.js"):
            source = self.read(name)
            self.assertIn("READY_TO_GENERATE: '素材与提示词已就绪'", source)
            self.assertNotIn("READY_TO_GENERATE: '可以生成'", source)
        home = self.read("js/home.js")
        self.assertIn("REFERENCE_APPROVED: '参考图已批准'", home)
        self.assertIn("SUBMISSION_LOST: '提交状态待核验'", home)
        self.assertIn("labels[state] || '状态已更新'", home)
        self.assertNotIn("labels[state] || state", home)

    def test_study_hides_unhydrated_defaults_and_exposes_loading_or_failure_state(self):
        html = self.read("workspace.html")
        script = self.read("js/workspace.js")
        styles = self.read("css/studio.css")
        self.assertIn('class="wrap wrap-wide app-main studio-page is-loading" aria-busy="true"', html)
        self.assertIn('id="workspace-loading" class="workspace-loading panel" role="status" aria-live="polite"', html)
        self.assertIn("正在加载 Study", html)
        self.assertIn(".studio-page.is-loading > :not(#workspace-loading)", styles)
        self.assertIn(".studio-page.is-load-failed > :not(#err)", styles)
        self.assertIn("workspaceMain?.classList.remove('is-loading')", script)
        self.assertIn("workspaceMain?.classList.add('is-load-failed')", script)
        self.assertIn("workspaceMain?.setAttribute('aria-busy', 'false')", script)
        self.assertIn("document.getElementById('workspace-loading')?.remove()", script)

        home_html = self.read("index.html")
        home_script = self.read("js/home.js")
        self.assertIn('class="wrap app-main is-loading" aria-busy="true"', home_html)
        self.assertIn('id="home-loading" class="home-loading panel" role="status" aria-live="polite"', home_html)
        self.assertIn(".app-home .app-main.is-loading > :not(#home-loading)", styles)
        self.assertIn("Promise.all([loadTasks(), checkSystem()])", home_script)
        self.assertIn(".finally(() =>", home_script)
        self.assertIn("document.getElementById('home-loading')?.remove()", home_script)
        self.assertIn("Study 列表加载失败；请刷新页面重试。", home_script)
        self.assertIn("环境状态暂时无法读取；可打开环境中心重新检查。", home_script)
        self.assertIn("生成环境未就绪：请在环境中心查看需处理项目。", home_script)
        self.assertIn("ComfyUI 服务：${names[state] || '状态未知'}", self.read("js/engine_status.js"))
        self.assertIn("完整生成条件请查看环境状态", self.read("js/engine_status.js"))
        environment_script = self.read("js/setup.js")
        self.assertIn("probe.probe_status === 'READY' ? ' gate-note-ok' : ''", environment_script)
        self.assertIn(".app-shell .gate-note.gate-note-ok { color: var(--avs-success); }", styles)

    def test_study_preserves_legacy_ids_and_adds_p1_frame(self):
        source = self.read("workspace.html")
        for element_id in ("task-name", "task-state", "v-body", "v-progress", "current-job-strip"):
            self.assertIn(f'id="{element_id}"', source)
        jobs = self.read("js/jobs.js")
        jobs_markup = self.read("jobs.html")
        self.assertIn("let selected = projects.find((p) => p.id === initialProjectId)?.id || '';", jobs)
        self.assertIn("async function searchJobs({reset = false} = {})", jobs)
        self.assertNotIn('/api/projects//jobs', jobs)
        self.assertNotIn("|| projects[0]?.id || ''", jobs)
        self.assertIn('aria-labelledby="project-select-label"', jobs_markup)
        self.assertIn('class="project-selection-row"', jobs_markup)
        self.assertIn('id="selection-hint" class="selection-hint" role="status" aria-live="polite"', jobs_markup)
        self.assertIn('<a class="job-detail-link" href="jobs.html?project=${encodeURIComponent(j.project_id)}&job=${encodeURIComponent(j.id)}"', jobs)
        self.assertNotIn('class="job-row" data-job="${esc(j.id)}" tabindex="0"', jobs)
        self.assertNotIn("row.addEventListener('keydown'", jobs)
        self.assertNotIn("row.addEventListener('click', open)", jobs)
        self.assertIn("if (initialJobId && !initialDetailOpened)", jobs)
        self.assertNotIn('onclick="event.stopPropagation()"', jobs)
        self.assertIn("updateProjectHint()", jobs)
        self.assertIn("还没有 Study，请先在 Home 创建一个 Study。", jobs)
        self.assertNotIn("暂无可用 Study", jobs)
        workspace = self.read("js/workspace.js")
        self.assertIn("个分镜引导已通过检查 · 共 ${guideResolution.target_frame_count} 帧 · H3 原生 24 FPS", workspace)
        self.assertNotIn("guideResolution.rounding_policy}", workspace)
        workspace_html = self.read("workspace.html")
        self.assertIn('eyebrow">分镜导演</span>', workspace_html)
        self.assertNotIn("A7 · DIRECTOR", workspace_html)
        self.assertNotIn("17k+5", workspace_html)
        self.assertIn("每个镜头单独生成。镜头运动描述用于引导画面表达", workspace_html)
        self.assertNotIn("生产 8189", workspace)
        self.assertNotIn("隔离实验 8190", workspace)
        self.assertNotIn("PROMPT_CAMERA_INTENT</span>", workspace)
        self.assertIn("function longFormQueueSummary(queue)", workspace)
        self.assertIn("个镜头已完成", workspace)
        self.assertNotIn("shotText || '无镜头'", workspace)
        self.assertIn("<strong>长片合成</strong>", workspace_html)
        self.assertIn("只合成已完成的视频，不会自动重新生成镜头。", workspace_html)
        self.assertIn("输出尺寸使用 Lanczos 缩放/补边，不是 AI 超分。", workspace_html)
        self.assertIn("1080p · Lanczos 缩放（非 AI 超分）", workspace_html)
        self.assertIn("2K · Lanczos 缩放（非 AI 超分）", workspace_html)
        self.assertNotIn("CPU 装配", workspace_html)
        output = self.read("js/output.js")
        output_script = output
        self.assertIn('showContextState', output)
        self.assertNotIn('缺少 job 参数', output)
        output_html = self.read("output.html")
        self.assertIn('id="results-library"', output_html)
        self.assertIn('id="results-project"', output_html)
        self.assertIn('id="results-search"', output_html)
        self.assertIn('id="results-preview-video"', output_html)
        self.assertIn('<details id="output-technical-details" class="mt">', output_html)
        self.assertIn("生成记录与技术详情（可选）", output_html)
        self.assertIn('id="pkg-tree"', output_html)
        self.assertNotIn('Output Package 结构', output_html)
        self.assertIn("参考图审批", output_script)
        self.assertIn("function deliveryFailureMessage(error)", output_script)
        self.assertIn("function deliveryItemFailureMessage(code)", output_script)
        self.assertIn("缺少可验证的运行环境信息", output_script)
        self.assertIn("来源校验未通过，已停止处理", output_script)
        self.assertNotIn('<span class="k">Safe Load</span>', output_script)
        output_css = self.read("css/studio.css")
        self.assertIn(".app-output #record .kv > span { min-width: 0; overflow-wrap: anywhere; }", output_css)
        global_css = self.read("css/avs_global_theme.css")
        self.assertIn(".app-study .app-header { height: auto; min-height: 48px; flex-wrap: wrap; }", global_css)
        self.assertIn(".app-study .study-header-context { min-width: 0; }", global_css)
        api_script = self.read("js/api.js")
        self.assertIn('id="output-context-actions"', output_html)
        self.assertIn('id="output-download"', output_html)
        self.assertIn('<a id="output-download" class="btn small primary" hidden>', output_html)
        form = re.search(r'<form id="delivery-form"[^>]*>', output_html)
        self.assertIsNotNone(form)
        self.assertRegex(form.group(0), r"\shidden(?:\s|>)")
        self.assertIn("请先从 Jobs 打开一个已完成任务", output_html)
        no_job_branch = re.search(r"async function load\(\) \{(?P<body>.*?)\n  \}", output, re.S)
        self.assertIsNotNone(no_job_branch)
        self.assertIn("if (!jobId)", no_job_branch.group("body"))
        self.assertIn("resultsLibrary.hidden = false", no_job_branch.group("body"))
        self.assertIn("jobOutputView.hidden = true", no_job_branch.group("body"))
        self.assertIn("await loadResultsLibrary()", no_job_branch.group("body"))
        self.assertIn("return;", no_job_branch.group("body"))
        self.assertIn("async function loadResultsLibrary()", output)
        self.assertIn("/api/projects/${encodeURIComponent(project.id)}/jobs", output)
        self.assertIn("/api/projects/${encodeURIComponent(project.id)}/long-form", output)
        self.assertIn("/api/jobs/${encodeURIComponent(job.id)}/deliveries", output)
        self.assertIn("data-result-preview", output)
        self.assertIn("sameOriginMediaUrl(item.media_url)", output)
        self.assertIn("unavailable_reason", output)
        self.assertIn("任务记录显示已完成，但当前没有可验证的视频文件", output)
        self.assertIn("form.hidden = !state.available", output)
        self.assertIn("form.addEventListener('submit'", output)
        self.assertIn(".video-box video[hidden]", self.read("css/studio.css"))
        self.assertIn(".app-output [hidden]", self.read("css/studio.css"))
        self.assertIn('function sameOriginMediaUrl(value)', api_script)
        self.assertIn('function mediaDownloadName(...parts)', api_script)
        self.assertIn('download = mediaDownloadName', output_script)
        self.assertIn('sameOriginMediaUrl(media.media_url)', output_script)
        self.assertIn('下载交付视频', output_script)
        self.assertIn('id="a9-download"', source)
        study_script = self.read("js/workspace.js")
        self.assertIn('sameOriginMediaUrl(assembly.media_url)', study_script)
        self.assertIn("该任务当前状态", output_script)
        self.assertIn("function runtimeLabel(detail)", output_script)
        self.assertIn("identity.runtime_role || identity.target || detail?.runtime_target", output_script)
        self.assertIn("identity.comfyui_version", output_script)
        self.assertNotIn("Native v0.33.1", output_script)
        self.assertIn("完成的输出会显示在这里。", output_html)
        self.assertNotIn("Rendered output will appear here.", output_html)
        study_script = self.read("js/workspace.js")
        self.assertIn("function hasExperimentalPurpose()", study_script)
        self.assertGreaterEqual(study_script.count("const experimentPurposeAvailable = hasExperimentalPurpose();"), 2)
        self.assertIn("const created = await post(`/api/projects/${projectId}/jobs`", study_script)
        self.assertIn("job?.id", study_script)
        self.assertIn("if (progress == null) progressBar.style.removeProperty('width');", study_script)
        self.assertIn("function flowState(job = null)", study_script)
        self.assertIn("button.setAttribute('aria-describedby', 'gate-note preflight-result')", study_script)
        for state in ("QUEUED", "SUBMITTED", "RUNNING", "GENERATING", "RECONCILING", "COMPLETED", "FAILED", "CANCELLED", "SUBMISSION_LOST"):
            self.assertIn(state, jobs)
        self.assertIn("function friendlyError", self.read("js/api.js"))
        jobs_css = self.read("css/studio.css")
        self.assertIn(".jobs-table", jobs_css)
        self.assertIn("data-label", jobs_css)
        self.assertIn(".app-jobs .project-selection-row { flex-wrap: wrap; }", jobs_css)
        self.assertIn("white-space: nowrap", jobs_css)
        self.assertIn("study-identity", source)
        self.assertIn("ux2-viewport-frame", source)
        self.assertIn("ux2-tool-drawer", source)
        self.assertIn('id="current-job-output"', source)

    def test_semantic_tokens_and_responsive_hooks_exist(self):
        source = self.read("css/studio.css")
        global_css = self.read("css/avs_global_theme.css")
        theme = self.read("js/theme.js")
        for token in (
            "--surface-app", "--surface-tool", "--surface-viewport",
            "--text-primary", "--status-ready", "--status-error",
            "--interaction-focus", "--space-4", "--type-numeric",
            "--header-height", "--control-height", "--tool-panel-width",
        ):
            self.assertIn(token, source)
        self.assertIn("UX2-P1: viewport-first shell hooks", source)
        self.assertIn("max-width: 1365px", source)
        self.assertIn("prefers-reduced-motion", source)
        for token in (
            "--avs-bg", "--avs-surface-1", "--avs-surface-2", "--avs-control-bg",
            "--avs-text", "--avs-text-secondary", "--avs-text-muted",
            "--avs-accent", "--avs-success", "--avs-warning", "--avs-danger", "--avs-focus",
            "--avs-control-height-sm", "--avs-control-height-md", "--avs-control-height-lg",
        ):
            self.assertIn(token, global_css)
        self.assertIn('html[data-theme="light"]', global_css)
        self.assertIn("sl-theme-dark", theme)

    def test_environment_installer_grid_shrinks_and_stacks_on_mobile(self):
        source = self.read("css/studio.css")
        shared_shell = self.read("css/avs_global_theme.css")
        self.assertIn(".app-environment .install-plan { grid-template-columns: minmax(0, 1fr); }", source)
        self.assertIn(".app-environment .install-item-head { flex-wrap: wrap; }", source)
        self.assertIn(".app-environment .install-item-meta { overflow-wrap: anywhere; }", source)
        mobile = re.search(r"@media \(max-width: 760px\) \{(?P<body>.*?)\n\}", source, re.S)
        self.assertIsNotNone(mobile)
        self.assertIn(".app-environment .setup-shell { grid-template-columns: minmax(0, 1fr); }", mobile.group("body"))
        self.assertIn(".app-environment .group-nav { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }", mobile.group("body"))
        self.assertIn(".app-environment #inspector { min-width: 0; }", mobile.group("body"))
        self.assertIn(".app-shell .app-header { height: auto; min-height: 48px; gap: 6px; flex-wrap: wrap; align-content: center; }", shared_shell)
        self.assertIn(".app-shell .app-header > .spacer { display: none; }", shared_shell)

    def test_route_resolver_owns_active_navigation(self):
        source = self.read("js/ux2_shell.js")
        for token in ("const ROUTES", "function currentRoute", "function resolveNavigation", "link.classList.remove('active')", "link.classList.add('active')"):
            self.assertIn(token, source)
        for name in PAGES:
            page = self.read(name)
            nav = re.search(r"<nav class=\"nav app-nav\".*?</nav>", page, re.S)
            self.assertIsNotNone(nav, name)
            self.assertNotRegex(nav.group(0), r"class=\"active\"", name)
            self.assertNotRegex(nav.group(0), r"aria-current=\"page\"", name)
            self.assertEqual(len(re.findall(r'data-route=', nav.group(0))), 5, name)

    def test_navigation_context_and_polling_contract(self):
        source = self.read("js/ux2_shell.js")
        self.assertIn("params.get('project')", source)
        self.assertIn("workspace.html?project=", source)
        self.assertIn("withContext", source)
        self.assertIn(".studio-heading a[href=\"jobs.html\"], .current-job-strip a[href=\"jobs.html\"]", source)
        self.assertIn("link.href = withContext(link.getAttribute('href'))", source)
        self.assertIn("target.searchParams.set('project', project)", source)
        self.assertIn("target.searchParams.set('job', job)", source)
        engine = self.read("js/engine_status.js")
        self.assertNotRegex(engine, r"location\\.(href|assign|replace)")

    def test_minimal_study_workspace_keeps_existing_controls_reachable(self):
        source = self.read("workspace.html")
        for token in (
            "reference-panel", "ux2-reference-thumb", "ux2-viewport-frame",
            "ux2-tool-drawer", "ux2-inspector-section", "prompt-assistance",
            "primary-param-grid", "advanced-settings", "generate-btn",
        ):
            self.assertIn(token, source)
        for element_id in (
            "ref-file", "intent-text", "video-type", "param-duration",
            "param-quality", "prompt-engine", "analyze-btn", "generate-btn",
        ):
            self.assertIn(f'id="{element_id}"', source)
        jobs = self.read("js/jobs.js")
        self.assertIn("let selected = projects.find((p) => p.id === initialProjectId)?.id || '';", jobs)
        self.assertIn("async function searchJobs({reset = false} = {})", jobs)
        self.assertNotIn('/api/projects//jobs', jobs)
        output = self.read("js/output.js")
        self.assertIn('showContextState', output)
        self.assertNotIn('缺少 job 参数', output)
        jobs_css = self.read("css/studio.css")
        self.assertIn(".jobs-table", jobs_css)
        self.assertIn("data-label", jobs_css)

    def test_local_shoelace_kit_and_icon_contract(self):
        for name in PAGES:
            source = self.read(name)
            if name != "workspace.html":
                self.assertIn('vendor/shoelace/shoelace.js', source, name)
                self.assertIn('vendor/shoelace/dark.css', source, name)
                self.assertIn('js/shoelace_bridge.js', source, name)
            self.assertIn('class="sl-theme-dark"', source, name)
            self.assertNotRegex(source, r'https?://[^" ]*(cdn|unpkg)', name)
            for icon in ('home.svg', 'photo.svg', 'briefcase.svg', 'file-description.svg', 'settings.svg'):
                self.assertIn(f'vendor/tabler/{icon}', source, name)
        for path in (
            FRONTEND / 'vendor' / 'shoelace' / 'shoelace.js',
            FRONTEND / 'vendor' / 'shoelace' / 'dark.css',
            FRONTEND / 'vendor' / 'tabler' / 'LICENSE',
        ):
            self.assertTrue(path.is_file(), path)
        workspace = self.read('workspace.html')
        for element in ('button', 'select', 'option', 'textarea', 'details'):
            self.assertIn(f'<{element}', workspace)
        for element in ('sl-button', 'sl-select', 'sl-option', 'sl-textarea', 'sl-details', 'sl-badge'):
            self.assertNotIn(f'<{element}', workspace)

    def test_result_recovery_action_requires_strong_identity_and_never_retries(self):
        jobs = self.read("js/jobs.js")
        for marker in (
            "function hasStrongResultRecoveryIdentity(job)",
            "function hasResultPipelineRecoveryFailure(job)",
            "async function shouldOfferResultRecovery(job)",
            "job.runtime !== 'native'",
            "job.execution_workflow_sha256",
            "job.execution_trace?.runtime_identity",
            "identity.runtime_config_fingerprint",
            "identity.output_root_fingerprint",
            "identity.comfyui_git_sha === 'ee71d5c4993f29086b27fde1629a945ae48425bf'",
            "result?.output?.available === false",
            "OUTPUT_ERROR:",
            "恢复已有结果（不会重新生成）",
            "不会创建新任务或提交生成",
        ):
            self.assertIn(marker, jobs)
        recovery_action = jobs.split("document.getElementById('recover-result')?.addEventListener", 1)[1]
        recovery_action = recovery_action.split("document.getElementById('retry-job')?.addEventListener", 1)[0]
        self.assertIn("/recover-result", recovery_action)
        self.assertNotIn("/retry", recovery_action)
        self.assertNotIn("/prompt", recovery_action)

    def test_no_new_backend_surface_in_p1_test_scope(self):
        changed = {
            p.relative_to(ROOT).as_posix()
            for p in ROOT.glob("apps/architect_video_studio/frontend/*")
            if p.is_file()
        }
        self.assertTrue(changed)
        self.assertFalse(any("runtime" in p or "workflows" in p for p in changed))

        contract = (ROOT / "docs" / "STUDIO_UX2_P2_FLOW_CONTRACT.md").read_text(encoding="utf-8")
        for transition in ("Home → Study", "Study → Jobs", "Jobs → Output", "Output → Study", "Theme toggle"):
            self.assertIn(transition, contract)


if __name__ == "__main__":
    unittest.main()
