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

    def test_all_primary_pages_have_shared_shell_and_navigation(self):
        for name, body_class in PAGES.items():
            source = self.read(name)
            self.assertIn('data-ux2="on"', source, name)
            self.assertIn('js/ux2_shell.js', source, name)
            self.assertIn(f'class="app-shell {body_class}"', source, name)
            self.assertIn('id="main-content"', source, name)
            for label in ("Home", "Study", "Jobs", "Outputs", "Environment"):
                self.assertRegex(source, rf">{label}</a>", name)

    def test_study_preserves_legacy_ids_and_adds_p1_frame(self):
        source = self.read("workspace.html")
        for element_id in ("task-name", "task-state", "v-body", "v-progress", "current-job-strip"):
            self.assertIn(f'id="{element_id}"', source)
        jobs_css = self.read("css/studio.css")
        self.assertIn(".jobs-table", jobs_css)
        self.assertIn("data-label", jobs_css)
        self.assertIn("study-identity", source)
        self.assertIn("ux2-viewport-frame", source)
        self.assertIn("ux2-tool-drawer", source)

    def test_semantic_tokens_and_responsive_hooks_exist(self):
        source = self.read("css/studio.css")
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
        self.assertIn("withProject", source)
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
        jobs_css = self.read("css/studio.css")
        self.assertIn(".jobs-table", jobs_css)
        self.assertIn("data-label", jobs_css)
    def test_no_new_backend_surface_in_p1_test_scope(self):
        changed = {
            p.relative_to(ROOT).as_posix()
            for p in ROOT.glob("apps/architect_video_studio/frontend/*")
            if p.is_file()
        }
        self.assertTrue(changed)
        self.assertFalse(any("runtime" in p or "workflows" in p for p in changed))


if __name__ == "__main__":
    unittest.main()
