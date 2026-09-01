using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Windows.Forms.Integration;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;

// One native desktop window. WebView2 is an implementation detail: the
// product UI fills the client area and the system browser is only an explicit
// fallback from the diagnostics/tray menu.
internal sealed class DesktopShellForm : Form
{
    private readonly string root;
    private readonly Panel pageHost;
    private readonly NotifyIcon tray;
    private readonly System.Windows.Forms.Timer pollTimer;
    private bool checking;
    private bool allowExit;
    private bool initialPageShown;
    private bool webViewStarted;
    private bool navigationRetried;
    private bool backendStartAttempted;
    private bool startupFailureShown;
    private DateTime backendDeadline;
    private DateTime webViewDeadline;
    private Process backend;
    private ElementHost webViewHost;
    private WebView2 webView;
    private string pendingUrl;
    private Icon appIcon;

    private static readonly string StudioUrl = "http://127.0.0.1:" + (Environment.GetEnvironmentVariable("H3_STUDIO_PORT") ?? "8788");
    private static readonly string ComfyUrl = "http://127.0.0.1:" + (Environment.GetEnvironmentVariable("H3_COMFYUI_PORT") ?? "8189");
    private static readonly string HomeUrl = StudioUrl + "/index.html?new=1";
    private const int BackendTimeoutSeconds = 45;
    private const int WebViewTimeoutSeconds = 25;

    public DesktopShellForm()
    {
        root = Directory.GetParent(AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\', '/')).FullName;
        Text = "Architect Video Studio";
        Width = 1280;
        Height = 820;
        MinimumSize = new Size(960, 640);
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.Sizable;
        MaximizeBox = true;
        appIcon = LoadAppIcon();
        Icon = appIcon;

        pageHost = new Panel { Dock = DockStyle.Fill, BackColor = Color.White, BorderStyle = BorderStyle.None, Padding = new Padding(0) };
        Controls.Add(pageHost);

        var menu = new ContextMenuStrip();
        menu.Items.Add("打开 Architect Video Studio", null, (s, e) => { RestoreFromTray(); Navigate(HomeUrl); });
        menu.Items.Add("打开环境设置 / 修复", null, (s, e) => { RestoreFromTray(); Navigate(StudioUrl + "/setup.html"); });
        menu.Items.Add("打开 Native ComfyUI（高级）", null, (s, e) => { RestoreFromTray(); Navigate(ComfyUrl + "/?h3_refresh=" + DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()); });
        menu.Items.Add("浏览器备用入口", null, (s, e) => OpenUrl(HomeUrl));
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("打开日志文件夹", null, (s, e) => OpenLogs());
        menu.Items.Add("退出 Architect Video Studio", null, (s, e) => ExitShell());
        tray = new NotifyIcon { Icon = appIcon, Text = "Architect Video Studio - 正在启动", Visible = true, ContextMenuStrip = menu };
        tray.DoubleClick += (s, e) => RestoreFromTray();

        pollTimer = new System.Windows.Forms.Timer { Interval = 5000 };
        pollTimer.Tick += (s, e) => PollBackend();
        FormClosing += OnFormClosing;
        Resize += (s, e) => { if (WindowState == FormWindowState.Minimized) Hide(); };

        pendingUrl = HomeUrl;
        ShowLoading("正在启动 Architect Video Studio", "正在检查本地运行环境…");
        // Do not start async WebView2 work from the constructor. Shown runs
        // after Application.Run installed the WinForms synchronization context.
        Shown += (s, e) => BeginStartup();
    }

    private Icon LoadAppIcon()
    {
        var path = Path.Combine(root, "assets", "architect-video-studio.ico");
        try { if (File.Exists(path)) return new Icon(path); } catch { }
        return SystemIcons.Application;
    }

    private string LogPath { get { return Path.Combine(root, "Logs", "desktop-shell.log"); } }

    private void Log(string marker, string detail = "")
    {
        try {
            Directory.CreateDirectory(Path.GetDirectoryName(LogPath));
            var line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff") + " " + marker +
                       (String.IsNullOrEmpty(detail) ? "" : " " + detail) + Environment.NewLine;
            File.AppendAllText(LogPath, line, Encoding.UTF8);
        } catch { }
    }

    private void BeginStartup()
    {
        Log("APP-01", "desktop process started");
        backendDeadline = DateTime.UtcNow.AddSeconds(BackendTimeoutSeconds);
        webViewDeadline = DateTime.UtcNow.AddSeconds(WebViewTimeoutSeconds);
        startupFailureShown = false;
        BeginWebViewInitialization();
        StartBackendIfNeeded();
        pollTimer.Start();
    }

    private string FindPython()
    {
        var native = ReadPath(Path.Combine(root, "native_env.path"));
        var candidates = new[] { Path.Combine(root, "runtime", "bootstrap", "python.exe"), Path.Combine(root, "userdata", "cache", "runtime", "comfyui_runtime", "python_embeded", "python.exe"), String.IsNullOrEmpty(native) ? "" : Path.Combine(native, "python_embeded", "python.exe") };
        foreach (var item in candidates) if (!String.IsNullOrEmpty(item) && File.Exists(item)) return item;
        return null;
    }

    private static string ReadPath(string pathFile)
    {
        try { if (!File.Exists(pathFile)) return null; var value = File.ReadAllText(pathFile).Trim().Trim('"'); return String.IsNullOrWhiteSpace(value) ? null : value; } catch { return null; }
    }

    private void StartBackendIfNeeded()
    {
        ThreadPool.QueueUserWorkItem(delegate {
            if (GetUrl(StudioUrl + "/api/health") != null) { Log("APP-03", "backend health ready before launch HTTP 200"); return; }
            if (backendStartAttempted) return;
            backendStartAttempted = true;
            var python = FindPython();
            var script = Path.Combine(root, "launcher", "launcher.py");
            if (String.IsNullOrEmpty(python) || !File.Exists(script)) { Log("APP-02", "backend not started: managed Python or launcher missing"); BeginInvoke((Action)(() => ShowFailure("服务启动失败", "未找到托管运行环境，请点击“环境修复”检查安装。", true))); return; }
            try {
                var info = new ProcessStartInfo { FileName = python, Arguments = "\"" + script + "\" start --no-browser", WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden };
                info.EnvironmentVariables["H3_PROJECT_ROOT"] = root;
                info.EnvironmentVariables["H3_WINDOWS_SAFE_LOAD"] = "pread";
                var native = ReadPath(Path.Combine(root, "native_env.path"));
                var models = ReadPath(Path.Combine(root, "models_env.path"));
                if (!String.IsNullOrEmpty(native)) {
                    info.EnvironmentVariables["H3_NATIVE_ROOT"] = native;
                    // Keep the selected/adopted Runtime as the sole owner of
                    // ComfyUI input/output.  Distribution defaults are
                    // package-relative and must not override this pair.
                    info.EnvironmentVariables["H3_COMFY_INPUT"] = Path.Combine(native, "ComfyUI", "input");
                    info.EnvironmentVariables["H3_COMFY_OUTPUT"] = Path.Combine(native, "ComfyUI", "output");
                }
                if (!String.IsNullOrEmpty(models)) info.EnvironmentVariables["H3_MODELS_ROOT"] = models;
                info.EnvironmentVariables["H3_STUDIO_DATA"] = Path.Combine(root, "userdata", "studio");
                backend = Process.Start(info);
                if (backend != null) { backend.EnableRaisingEvents = true; backend.Exited += (s, e) => Log("APP-02", "backend process exited code=" + backend.ExitCode); Log("APP-02", "backend process started pid=" + backend.Id); }
            } catch (Exception error) { Log("APP-02", "backend process start exception=" + error); BeginInvoke((Action)(() => ShowFailure("服务启动失败", "本地服务没有启动成功，请点击“环境修复”或“打开日志”。", true))); }
        });
    }

    private void PollBackend()
    {
        if (checking) return;
        checking = true;
        ThreadPool.QueueUserWorkItem(delegate {
            var health = GetUrl(StudioUrl + "/api/health");
            try {
                BeginInvoke((Action)(() => {
                    checking = false;
                    if (webViewStarted && webView == null && DateTime.UtcNow >= webViewDeadline && !startupFailureShown) {
                        Log("APP-04", "WebView2 initialization timeout");
                        ShowFailure("桌面界面组件启动失败", "桌面页面组件没有在规定时间内启动，请点击“重试”或“打开日志”。", false);
                    }
                    if (health == null) { if (DateTime.UtcNow >= backendDeadline && !startupFailureShown) { Log("APP-03", "backend health timeout"); ShowFailure("服务启动失败", "本地服务未在规定时间内响应。", true); } return; }
                    // Log the successful startup edge once. Repeating a
                    // successful health line every poll creates noise and can
                    // hide the actual lifecycle events in owner diagnostics.
                    // A stopped/crashed ComfyUI child remains an engine
                    // condition, not proof that installation is missing.
                    if (!initialPageShown) {
                        Log("APP-03", "backend health ready HTTP 200");
                        initialPageShown = true;
                        Navigate(pendingUrl);
                    }
                }));
            } catch (InvalidOperationException) { checking = false; }
        });
    }

    private static string GetUrl(string url)
    {
        try { var request = (HttpWebRequest)WebRequest.Create(url); request.Timeout = 1800; request.ReadWriteTimeout = 1800; using (var response = (HttpWebResponse)request.GetResponse()) using (var stream = response.GetResponseStream()) using (var reader = new StreamReader(stream, Encoding.UTF8)) return reader.ReadToEnd(); } catch { return null; }
    }

    private async void BeginWebViewInitialization()
    {
        if (webViewStarted) return;
        webViewStarted = true;
        try {
            var available = CoreWebView2Environment.GetAvailableBrowserVersionString(null);
            if (String.IsNullOrWhiteSpace(available)) throw new InvalidOperationException("WebView2 Runtime is not installed.");
            Log("APP-04", "WebView2 runtime detected version=" + available);
            var profile = Path.Combine(root, "userdata", "desktop_webview");
            Directory.CreateDirectory(profile);
            var environment = await CoreWebView2Environment.CreateAsync(null, profile, null);
            Log("APP-05", "WebView2 environment created profile=" + profile);
            webView = new WebView2();
            webViewHost = new ElementHost { Dock = DockStyle.Fill, Visible = true, BackColor = Color.White };
            webViewHost.Child = webView;
            pageHost.Controls.Clear();
            pageHost.Controls.Add(webViewHost);
            webViewHost.BringToFront();
            await webView.EnsureCoreWebView2Async(environment);
            Log("APP-06", "CoreWebView2 created");
            startupFailureShown = false;
            webView.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
            webView.CoreWebView2.Settings.AreDevToolsEnabled = false;
            webView.CoreWebView2.Settings.IsStatusBarEnabled = false;
            webView.CoreWebView2.NavigationCompleted += OnNavigationCompleted;
            // Navigation is intentionally triggered by PollBackend only after
            // the local service health check succeeds. This prevents a race
            // that used to navigate once on WebView creation and again when
            // the backend became ready.
        } catch (Exception error) { Log("APP-04", "WebView2 initialization exception=" + error); ShowFailure("桌面界面组件启动失败", "桌面页面组件没有成功启动，请点击“重试”或“打开日志”。", false); }
    }

    private void OnNavigationCompleted(object sender, CoreWebView2NavigationCompletedEventArgs args)
    {
        UpdateComfyReturnVisibility(webView != null && webView.Source != null ? webView.Source.AbsoluteUri : pendingUrl);
        Log("APP-08", "navigation completed success=" + args.IsSuccess + " webError=" + args.WebErrorStatus);
        if (!args.IsSuccess) { if (!navigationRetried) { navigationRetried = true; Log("APP-07", "navigation retry url=" + pendingUrl); webView.CoreWebView2.Navigate(pendingUrl); } else ShowFailure("页面加载失败", "Architect Video Studio 页面没有加载成功，请点击“重试”或“打开日志”。", false); return; }
        SignalPageReadyAsync();
    }

    private async Task SignalPageReadyAsync()
    {
        try {
            var state = await webView.ExecuteScriptAsync("document.readyState");
            var currentUrl = webView != null && webView.Source != null ? webView.Source.AbsoluteUri : pendingUrl;
            UpdateComfyReturnVisibility(currentUrl);
            if (currentUrl.StartsWith(ComfyUrl, StringComparison.OrdinalIgnoreCase))
            {
                var returnUrl = (StudioUrl + "/index.html?new=1").Replace("'", "\\'");
                var studioEndpoint = (StudioUrl + "/api/system/current-workflow?job_id=" + Uri.EscapeDataString(GetQueryValue(currentUrl, "h3_job"))).Replace("'", "\\'");
                var script = "(() => { const token=new URL(location.href).searchParams.get('h3_refresh')||'default'; const reset='architect-video-studio-workflow-reset-v3:'+token; if (sessionStorage.getItem(reset)!=='1') { localStorage.clear(); sessionStorage.setItem(reset,'1'); location.reload(); return; } const id='architect-video-studio-return'; if (!document.getElementById(id)) { const b=document.createElement('button'); b.id=id; b.textContent='返回 Studio'; b.style.cssText='position:fixed;z-index:2147483647;right:12px;top:42px;height:24px;padding:0 8px;border:1px solid rgba(255,255,255,.35);border-radius:4px;background:rgba(36,105,180,.82);color:#fff;font:12px Segoe UI,sans-serif;box-shadow:0 1px 5px rgba(0,0,0,.28);cursor:pointer;opacity:.86;'; b.onclick=()=>{window.location.href='" + returnUrl + "';}; document.body.appendChild(b); } const endpoint='" + studioEndpoint + "'; fetch(endpoint,{cache:'no-store'}).then(r=>r.json()).then(x=>{ const d=x.data||{}; const wf=d.workflow; if (!wf) return; let attempts=0; const apply=()=>{ const a=window.app||globalThis.app; let ok=false; try { if (a && typeof a.loadGraphData==='function') { a.loadGraphData(wf); ok=true; } else if (a && a.graph && typeof a.graph.configure==='function') { a.graph.configure(wf); if (typeof a.graph.setDirtyCanvas==='function') a.graph.setDirtyCanvas(true,true); ok=true; } } catch(e) {} if (!ok && attempts++<8) return setTimeout(apply,750); const hash=(d.execution_workflow_sha256||d.workflow_hash||'').slice(0,12); const n=document.createElement('div'); n.textContent=ok ? ('已加载当前任务：'+(d.workflow_id||'')+' · SHA '+hash+' · CURRENT ✓') : ('当前任务工作流已准备：'+(d.file_name||'')); n.style.cssText='position:fixed;z-index:2147483647;right:18px;top:14px;padding:7px 10px;border-radius:4px;background:'+(ok?'#1f7a4d':'#8a5a00')+';color:#fff;font:12px Segoe UI,sans-serif;box-shadow:0 1px 5px rgba(0,0,0,.28);'; document.body.appendChild(n); setTimeout(()=>n.remove(),5000); }; apply(); }).catch(()=>{}); })();";
                await webView.ExecuteScriptAsync(script);
            }
            Log("APP-09", "page ready signal received readyState=" + state + " url=" + currentUrl);
        }
        catch (Exception error) { Log("APP-09", "page ready signal exception=" + error.Message); }
    }

    private void UpdateComfyReturnVisibility(string url) { }

    private static string GetQueryValue(string url, string key)
    {
        try {
            var query = new Uri(url).Query.TrimStart('?');
            foreach (var pair in query.Split('&')) {
                var parts = pair.Split(new[] { '=' }, 2);
                if (parts.Length == 2 && String.Equals(Uri.UnescapeDataString(parts[0]), key, StringComparison.OrdinalIgnoreCase))
                    return Uri.UnescapeDataString(parts[1]);
            }
        }
        catch { return ""; }
        return "";
    }

    private void Navigate(string url)
    {
        pendingUrl = url;
        navigationRetried = false;
        UpdateComfyReturnVisibility(url);
        Log("APP-07", "navigation requested url=" + url);
        if (webView != null && webView.CoreWebView2 != null) webView.CoreWebView2.Navigate(url);
        else if (!webViewStarted) BeginWebViewInitialization();
    }

    private void ShowLoading(string title, string detail)
    {
        pageHost.Controls.Clear();
        var box = new Panel { Dock = DockStyle.Fill, BackColor = Color.White };
        box.Controls.Add(new Label { Text = title, Font = new Font("Segoe UI", 18, FontStyle.Bold), AutoSize = true, Location = new Point(36, 36), ForeColor = Color.FromArgb(23, 34, 49) });
        box.Controls.Add(new Label { Text = detail, AutoSize = true, Location = new Point(38, 84), ForeColor = Color.FromArgb(104, 119, 137) });
        pageHost.Controls.Add(box);
    }

    private void ShowFailure(string title, string detail, bool includeRepair)
    {
        startupFailureShown = true;
        Log("APP-FAIL", title + " " + detail);
        pageHost.Controls.Clear();
        var box = new Panel { Dock = DockStyle.Fill, BackColor = Color.White, Padding = new Padding(42) };
        var heading = new Label { Text = title, Font = new Font("Segoe UI", 18, FontStyle.Bold), AutoSize = true, ForeColor = Color.FromArgb(178, 58, 46) };
        var text = new Label { Text = detail, AutoSize = false, Width = 760, Height = 54, Location = new Point(0, 52), ForeColor = Color.FromArgb(104, 119, 137) };
        var retry = new Button { Text = "重试", Location = new Point(0, 124), Width = 110, Height = 34 };
        retry.Click += (s, e) => { webViewStarted = false; initialPageShown = false; startupFailureShown = false; backendStartAttempted = false; backendDeadline = DateTime.UtcNow.AddSeconds(BackendTimeoutSeconds); webViewDeadline = DateTime.UtcNow.AddSeconds(WebViewTimeoutSeconds); ShowLoading("正在启动 Architect Video Studio", "正在重试本地服务…"); BeginWebViewInitialization(); StartBackendIfNeeded(); };
        var repair = new Button { Text = "环境修复", Location = new Point(122, 124), Width = 120, Height = 34, Visible = includeRepair };
        repair.Click += (s, e) => Navigate(StudioUrl + "/setup.html");
        var logs = new Button { Text = "打开日志", Location = new Point(includeRepair ? 254 : 122, 124), Width = 110, Height = 34 };
        logs.Click += (s, e) => OpenLogs();
        box.Controls.Add(heading); box.Controls.Add(text); box.Controls.Add(retry); box.Controls.Add(repair); box.Controls.Add(logs); pageHost.Controls.Add(box);
    }

    private void OpenLogs()
    {
        try { Directory.CreateDirectory(Path.Combine(root, "Logs")); Process.Start(new ProcessStartInfo(Path.Combine(root, "Logs")) { UseShellExecute = true }); } catch { }
    }

    private static void OpenUrl(string url) { try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); } catch { } }
    private void RestoreFromTray() { Show(); WindowState = FormWindowState.Normal; Activate(); }
    private void ExitShell() { allowExit = true; tray.Visible = false; Close(); }

    private void OnFormClosing(object sender, FormClosingEventArgs args)
    {
        if (!allowExit) { args.Cancel = true; Hide(); return; }
        pollTimer.Stop();
        try { if (webView != null) webView.Dispose(); } catch { }
        try { if (webViewHost != null) webViewHost.Dispose(); } catch { }
        try { tray.Visible = false; tray.Dispose(); } catch { }
        Log("APP-10", "desktop process closing");
    }
}

internal static class DesktopShell
{
    [STAThread]
    public static int Main()
    {
        bool created;
        var suffix = Environment.GetEnvironmentVariable("ARCHITECT_VIDEO_STUDIO_TEST_ID") ?? "";
        using (var mutex = new Mutex(true, "Local\\ArchitectVideoStudioDesktop" + suffix, out created)) {
            if (!created) return 0;
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new DesktopShellForm());
            return 0;
        }
    }
}
