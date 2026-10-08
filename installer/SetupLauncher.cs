using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Text;
using System.Windows.Forms;

internal static class SetupLauncher
{
    private static string RememberedInstallRootFile
    {
        get
        {
            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "ArchitectVideoStudio",
                "last-install-root.txt");
        }
    }

    private static string GetInitialInstallRoot()
    {
        try
        {
            if (File.Exists(RememberedInstallRootFile))
            {
                var remembered = File.ReadAllText(RememberedInstallRootFile).Trim().Trim('"');
                if (!String.IsNullOrWhiteSpace(remembered)) return remembered;
            }
        }
        catch
        {
            // A damaged or unreadable preference must never prevent setup.
        }

        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "ArchitectVideoStudio");
    }

    private static void RememberInstallRoot(string value)
    {
        try
        {
            var parent = Path.GetDirectoryName(RememberedInstallRootFile);
            if (!String.IsNullOrEmpty(parent)) Directory.CreateDirectory(parent);
            File.WriteAllText(RememberedInstallRootFile, value.Trim().Trim('"'));
        }
        catch
        {
            // Remembering the path is helpful, but is not a reason to fail setup.
        }
    }

    private static string Quote(string value)
    {
        var result = new StringBuilder();
        result.Append('"');
        var slashes = 0;
        foreach (var character in value)
        {
            if (character == '\\')
            {
                slashes++;
                continue;
            }
            if (character == '"')
            {
                result.Append('\\', slashes * 2 + 1);
                result.Append('"');
            }
            else
            {
                result.Append('\\', slashes);
                result.Append(character);
            }
            slashes = 0;
        }
        result.Append('\\', slashes * 2);
        result.Append('"');
        return result.ToString();
    }

    private static void ExtractResource(string name, string destination)
    {
        using (var input = Assembly.GetExecutingAssembly().GetManifestResourceStream(name))
        {
            if (input == null) throw new InvalidOperationException("Installer resource is missing: " + name);
            using (var output = File.Create(destination)) input.CopyTo(output);
        }
    }

    private sealed class InstallerForm : Form
    {
        private readonly TextBox pathBox;
        private readonly CheckBox appOnlyCheck;
        private readonly TextBox bootstrapPythonBox;
        private readonly Button pythonBrowseButton;
        private readonly Button installButton;
        private readonly Button browseButton;
        private readonly Button typePathButton;
        private readonly ProgressBar progress;
        private readonly TextBox log;
        private readonly Label status;
        private Process process;
        private string workRoot;
        private bool browseInProgress;
        private System.Windows.Forms.Timer closeTimer;

        public InstallerForm(bool appOnly, string initialRoot, string bootstrapPython)
        {
            Text = "Architect Video Studio Setup";
            Width = 720;
            Height = 560;
            MinimumSize = new Size(620, 520);
            StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;

            var title = new Label {
                Text = "Install Architect Video Studio",
                Font = new Font(Font, FontStyle.Bold),
                AutoSize = true,
                Location = new Point(18, 16)
            };
            Controls.Add(title);

            var description = new Label {
                Text = "Install the application. Runtime setup is separate; App-only mode never downloads or modifies ComfyUI or models.",
                AutoSize = false,
                Width = 660,
                Height = 46,
                Location = new Point(18, 48)
            };
            Controls.Add(description);

            Controls.Add(new Label {
                Text = "Installation folder:",
                AutoSize = true,
                Location = new Point(18, 105)
            });

            pathBox = new TextBox {
                Text = String.IsNullOrWhiteSpace(initialRoot) ? GetInitialInstallRoot() : initialRoot,
                Location = new Point(18, 128),
                Width = 430,
                Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right
            };
            Controls.Add(pathBox);

            browseButton = new Button {
                Text = "Browse...",
                Location = new Point(460, 126),
                Width = 100,
                Anchor = AnchorStyles.Top | AnchorStyles.Right
            };
            browseButton.Click += BrowseClicked;
            Controls.Add(browseButton);

            typePathButton = new Button {
                Text = "Type path...",
                Location = new Point(570, 126),
                Width = 105,
                Anchor = AnchorStyles.Top | AnchorStyles.Right
            };
            typePathButton.Click += TypePathClicked;
            Controls.Add(typePathButton);

            appOnlyCheck = new CheckBox {
                Text = "App-only: do not install, download, or modify ComfyUI or model files",
                AutoSize = true,
                Checked = appOnly,
                Location = new Point(18, 165)
            };
            appOnlyCheck.CheckedChanged += AppOnlyChanged;
            Controls.Add(appOnlyCheck);

            Controls.Add(new Label {
                Text = "Existing Python 3.10+ interpreter (required for App-only):",
                AutoSize = true,
                Location = new Point(18, 195)
            });
            bootstrapPythonBox = new TextBox {
                Text = String.IsNullOrWhiteSpace(bootstrapPython)
                    ? (Environment.GetEnvironmentVariable("H3_BOOTSTRAP_PYTHON") ?? FindPythonOnPath())
                    : bootstrapPython,
                Location = new Point(18, 216),
                Width = 540,
                Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right
            };
            Controls.Add(bootstrapPythonBox);
            pythonBrowseButton = new Button {
                Text = "Browse...",
                Location = new Point(570, 214),
                Width = 105,
                Anchor = AnchorStyles.Top | AnchorStyles.Right
            };
            pythonBrowseButton.Click += PythonBrowseClicked;
            Controls.Add(pythonBrowseButton);

            status = new Label {
                Text = "Ready",
                AutoSize = true,
                Location = new Point(18, 252)
            };
            Controls.Add(status);

            progress = new ProgressBar {
                Style = ProgressBarStyle.Marquee,
                MarqueeAnimationSpeed = 30,
                Location = new Point(18, 276),
                Width = 657,
                Height = 18,
                Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right,
                Visible = false
            };
            Controls.Add(progress);

            log = new TextBox {
                Multiline = true,
                ReadOnly = true,
                ScrollBars = ScrollBars.Vertical,
                BackColor = Color.White,
                Location = new Point(18, 305),
                Width = 657,
                Height = 160,
                Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right
            };
            Controls.Add(log);

            installButton = new Button {
                Text = "Install",
                Location = new Point(570, 482),
                Width = 105,
                Anchor = AnchorStyles.Bottom | AnchorStyles.Right
            };
            installButton.Click += InstallClicked;
            Controls.Add(installButton);
            AcceptButton = installButton;
            UpdateAppOnlyControls();
        }

        private static string FindPythonOnPath()
        {
            var path = Environment.GetEnvironmentVariable("PATH") ?? "";
            foreach (var directory in path.Split(Path.PathSeparator))
            {
                if (String.IsNullOrWhiteSpace(directory)) continue;
                var candidate = Path.Combine(directory.Trim().Trim('"'), "python.exe");
                if (candidate.IndexOf("\\WindowsApps\\", StringComparison.OrdinalIgnoreCase) >= 0) continue;
                if (File.Exists(candidate)) return candidate;
            }
            return "";
        }

        private void AppOnlyChanged(object sender, EventArgs args)
        {
            UpdateAppOnlyControls();
        }

        private void UpdateAppOnlyControls()
        {
            var enabled = appOnlyCheck != null && appOnlyCheck.Checked;
            if (bootstrapPythonBox != null) bootstrapPythonBox.Enabled = enabled;
            if (pythonBrowseButton != null) pythonBrowseButton.Enabled = enabled;
            if (status != null && enabled) status.Text = "App-only mode: no ComfyUI or model provisioning";
        }

        private void PythonBrowseClicked(object sender, EventArgs args)
        {
            using (var dialog = new OpenFileDialog())
            {
                dialog.Title = "Select an existing Python interpreter";
                dialog.Filter = "Python interpreter (python.exe)|python.exe|Executable files (*.exe)|*.exe";
                dialog.CheckFileExists = true;
                dialog.Multiselect = false;
                if (!String.IsNullOrWhiteSpace(bootstrapPythonBox.Text))
                {
                    try { dialog.InitialDirectory = Path.GetDirectoryName(bootstrapPythonBox.Text); }
                    catch { }
                }
                if (dialog.ShowDialog(this) == DialogResult.OK)
                    bootstrapPythonBox.Text = dialog.FileName;
            }
        }

        private void BrowseClicked(object sender, EventArgs args)
        {
            if (browseInProgress) return;
            browseInProgress = true;
            browseButton.Enabled = false;
            typePathButton.Enabled = false;
            status.Text = "Opening folder picker...";

            var currentPath = pathBox.Text.Trim().Trim('"');
            var pickerThread = new Thread(() => {
                string selected = null;
                string error = null;
                try
                {
                    using (var dialog = new FolderBrowserDialog())
                    {
                        dialog.Description = "Choose the folder where Architect Video Studio will be installed";
                        dialog.ShowNewFolderButton = true;
                        var parent = Path.GetDirectoryName(currentPath);
                        if (!String.IsNullOrEmpty(parent) && Directory.Exists(parent))
                            dialog.SelectedPath = parent;
                        if (dialog.ShowDialog() == DialogResult.OK)
                            selected = dialog.SelectedPath;
                    }
                }
                catch (Exception pickerError)
                {
                    error = pickerError.Message;
                }

                try
                {
                    BeginInvoke((Action)(() => {
                        browseInProgress = false;
                        browseButton.Enabled = true;
                        typePathButton.Enabled = true;
                        if (!String.IsNullOrEmpty(error))
                        {
                            status.Text = "Ready";
                            AppendLog("Folder picker failed: " + error);
                            MessageBox.Show(this, error, "Architect Video Studio Setup", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                        }
                        else if (!String.IsNullOrEmpty(selected))
                        {
                            pathBox.Text = selected;
                            status.Text = "Installation folder selected";
                            AppendLog("Selected installation folder: " + selected);
                        }
                        else
                        {
                            status.Text = "Ready";
                        }
                    }));
                }
                catch (InvalidOperationException)
                {
                    // The installer window was closed while the shell picker
                    // was open. There is no UI left to update.
                }
            });
            pickerThread.IsBackground = true;
            pickerThread.SetApartmentState(ApartmentState.STA);
            pickerThread.Start();
        }

        private void TypePathClicked(object sender, EventArgs args)
        {
            using (var dialog = new Form())
            {
                dialog.Text = "Choose installation folder";
                dialog.Width = 620;
                dialog.Height = 190;
                dialog.StartPosition = FormStartPosition.CenterParent;
                dialog.FormBorderStyle = FormBorderStyle.FixedDialog;
                dialog.MaximizeBox = false;
                dialog.MinimizeBox = false;

                var label = new Label {
                    Text = "Type or paste the installation path (for example: D:\\ProgramFilesNormal\\ArchitectVideoStudio RC TEST)",
                    AutoSize = false,
                    Width = 560,
                    Height = 38,
                    Location = new Point(18, 16)
                };
                dialog.Controls.Add(label);
                var input = new TextBox {
                    Text = pathBox.Text,
                    Location = new Point(18, 62),
                    Width = 560
                };
                dialog.Controls.Add(input);
                var ok = new Button {
                    Text = "Use this folder",
                    DialogResult = DialogResult.OK,
                    Location = new Point(360, 105),
                    Width = 125
                };
                dialog.Controls.Add(ok);
                var cancel = new Button {
                    Text = "Cancel",
                    DialogResult = DialogResult.Cancel,
                    Location = new Point(495, 105),
                    Width = 85
                };
                dialog.Controls.Add(cancel);
                dialog.AcceptButton = ok;
                dialog.CancelButton = cancel;
                dialog.Shown += (s, e) => { input.Focus(); input.SelectAll(); };
                if (dialog.ShowDialog(this) == DialogResult.OK && !String.IsNullOrWhiteSpace(input.Text))
                {
                    pathBox.Text = input.Text.Trim().Trim('"');
                    status.Text = "Installation folder selected";
                    AppendLog("Selected installation folder: " + pathBox.Text);
                }
            }
        }

        private void InstallClicked(object sender, EventArgs args)
        {
            if (process != null && !process.HasExited) return;
            var selected = pathBox.Text.Trim().Trim('"');
            if (String.IsNullOrEmpty(selected))
            {
                MessageBox.Show(this, "Please choose an installation folder.", "Architect Video Studio", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            var selectedPython = bootstrapPythonBox.Text.Trim().Trim('"');
            if (appOnlyCheck.Checked && String.IsNullOrWhiteSpace(selectedPython))
            {
                MessageBox.Show(this, "App-only mode requires an existing Python 3.10+ interpreter. No software will be downloaded.", "Architect Video Studio", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            var powershell = Path.Combine(Environment.SystemDirectory, "WindowsPowerShell\\v1.0\\powershell.exe");
            if (!File.Exists(powershell)) powershell = "powershell.exe";
            try
            {
                // Persist the user's choice before launching the worker so the
                // next setup invocation opens at the same location even if a
                // repair is needed.
                RememberInstallRoot(selected);
                workRoot = Path.Combine(Path.GetTempPath(), "ArchitectVideoStudio-" + Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(workRoot);
                var script = Path.Combine(workRoot, "Setup.ps1");
                ExtractResource("Setup.ps1", script);
                ExtractResource("payload.zip", Path.Combine(workRoot, "payload.zip"));

                pathBox.Enabled = false;
                browseButton.Enabled = false;
                typePathButton.Enabled = false;
                installButton.Enabled = false;
                progress.Visible = true;
                status.Text = appOnlyCheck.Checked ? "Installing application only..." : "Installing and checking existing components...";
                AppendLog((appOnlyCheck.Checked ? "Installing application only to " : "Installing Architect Video Studio to ") + selected);

                var arguments = "-NoLogo -NoProfile -File " + Quote(script) + " -TargetRoot " + Quote(selected);
                if (appOnlyCheck.Checked)
                    arguments += " -AppOnly -BootstrapPythonPath " + Quote(selectedPython);
                var info = new ProcessStartInfo {
                    FileName = powershell,
                    Arguments = arguments,
                    WorkingDirectory = workRoot,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                };
                info.EnvironmentVariables["ARCHITECT_VIDEO_STUDIO_INSTALL_ROOT"] = selected;
                process = new Process { StartInfo = info, EnableRaisingEvents = true };
                process.OutputDataReceived += OutputReceived;
                process.ErrorDataReceived += OutputReceived;
                process.Exited += ProcessExited;
                process.Start();
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
            }
            catch (Exception error)
            {
                AppendLog(error.ToString());
                status.Text = "Installer startup failed";
                progress.Visible = false;
                pathBox.Enabled = true;
                browseButton.Enabled = true;
                typePathButton.Enabled = true;
                installButton.Enabled = true;
                MessageBox.Show(this, error.Message, "Architect Video Studio Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private void OutputReceived(object sender, DataReceivedEventArgs args)
        {
            if (!String.IsNullOrEmpty(args.Data) && !IsDisposed)
                BeginInvoke((Action)(() => AppendLog(args.Data)));
        }

        private static void DeleteTemporaryTreeWithoutFollowingLinks(string path)
        {
            foreach (var entry in Directory.EnumerateFileSystemEntries(path))
            {
                var attributes = File.GetAttributes(entry);
                if ((attributes & FileAttributes.ReparsePoint) != 0)
                {
                    if ((attributes & FileAttributes.Directory) != 0) Directory.Delete(entry, false);
                    else File.Delete(entry);
                    continue;
                }

                if ((attributes & FileAttributes.Directory) != 0)
                {
                    DeleteTemporaryTreeWithoutFollowingLinks(entry);
                    Directory.Delete(entry, false);
                }
                else
                {
                    File.Delete(entry);
                }
            }
            Directory.Delete(path, false);
        }

        public static void CleanupSetupPayload(string path)
        {
            if (String.IsNullOrWhiteSpace(path)) return;
            var fullPath = Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            var tempPath = Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            var directory = new DirectoryInfo(fullPath);
            const string prefix = "ArchitectVideoStudio-";
            Guid ignored;
            if (directory.Parent == null ||
                !String.Equals(Path.GetFullPath(directory.Parent.FullName).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar),
                    tempPath, StringComparison.OrdinalIgnoreCase) ||
                !directory.Name.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) ||
                !Guid.TryParseExact(directory.Name.Substring(prefix.Length), "N", out ignored) ||
                !directory.Exists || (directory.Attributes & FileAttributes.ReparsePoint) != 0)
            {
                throw new IOException("Refusing to clean a setup folder outside its generated temporary location.");
            }
            DeleteTemporaryTreeWithoutFollowingLinks(fullPath);
        }

        private void ProcessExited(object sender, EventArgs args)
        {
            if (IsDisposed) return;
            BeginInvoke((Action)(() => {
                var code = process == null ? -1 : process.ExitCode;
                progress.Visible = false;
                installButton.Enabled = true;
                pathBox.Enabled = true;
                browseButton.Enabled = true;
                typePathButton.Enabled = true;
                if (code == 0)
                {
                    RememberInstallRoot(pathBox.Text.Trim().Trim('"'));
                    try
                    {
                        if (!String.IsNullOrWhiteSpace(workRoot) && Directory.Exists(workRoot))
                        {
                            CleanupSetupPayload(workRoot);
                            AppendLog("Temporary setup payload cleaned.");
                        }
                    }
                    catch
                    {
                        // A successful install must not be reported as failed
                        // just because Windows temporarily holds a setup file.
                        AppendLog("Temporary setup files could not be fully cleaned; the application installed successfully.");
                    }
                    status.Text = "Installation complete";
                    AppendLog("Setup complete. Environment Center is launching without a console window.");
                    closeTimer = new System.Windows.Forms.Timer { Interval = 1200 };
                    closeTimer.Tick += (s, e) => {
                        closeTimer.Stop();
                        closeTimer.Dispose();
                        Close();
                    };
                    closeTimer.Start();
                }
                else
                {
                    status.Text = "Installation failed";
                    AppendLog("Setup failed with exit code " + code + ".");
                    MessageBox.Show(this, "Installation failed. Review the log above for details.", "Architect Video Studio", MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
            }));
        }

        private void AppendLog(string value)
        {
            if (log.TextLength > 0) log.AppendText(Environment.NewLine);
            log.AppendText(value);
            log.SelectionStart = log.TextLength;
            log.ScrollToCaret();
        }
    }

    private static bool HasOption(string[] args, string option)
    {
        foreach (var value in args)
            if (String.Equals(value, option, StringComparison.OrdinalIgnoreCase)) return true;
        return false;
    }

    private static string GetOption(string[] args, string option)
    {
        for (var index = 0; index + 1 < args.Length; index++)
            if (String.Equals(args[index], option, StringComparison.OrdinalIgnoreCase)) return args[index + 1];
        return "";
    }

    private static int RunSilentAppOnly(string[] args)
    {
        if (!HasOption(args, "--app-only") || !HasOption(args, "--silent")) return 2;
        var target = GetOption(args, "--install-root");
        var python = GetOption(args, "--bootstrap-python");
        if (String.IsNullOrWhiteSpace(target) || String.IsNullOrWhiteSpace(python)) return 2;
        var powershell = Path.Combine(Environment.SystemDirectory, "WindowsPowerShell\\v1.0\\powershell.exe");
        if (!File.Exists(powershell)) powershell = "powershell.exe";
        var workRoot = Path.Combine(Path.GetTempPath(), "ArchitectVideoStudio-" + Guid.NewGuid().ToString("N"));
        try
        {
            Directory.CreateDirectory(workRoot);
            var script = Path.Combine(workRoot, "Setup.ps1");
            ExtractResource("Setup.ps1", script);
            ExtractResource("payload.zip", Path.Combine(workRoot, "payload.zip"));
            var info = new ProcessStartInfo {
                FileName = powershell,
                Arguments = "-NoLogo -NoProfile -File " + Quote(script) +
                    " -AppOnly -TargetRoot " + Quote(target) +
                    " -BootstrapPythonPath " + Quote(python),
                WorkingDirectory = workRoot,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            using (var process = Process.Start(info))
            {
                if (process == null) return 3;
                process.WaitForExit();
                if (process.ExitCode == 0) RememberInstallRoot(target);
                return process.ExitCode;
            }
        }
        catch
        {
            return 4;
        }
        finally
        {
            try { if (Directory.Exists(workRoot)) InstallerForm.CleanupSetupPayload(workRoot); }
            catch { }
        }
    }

    public static int Main(string[] args)
    {
        var appOnly = HasOption(args, "--app-only");
        if (HasOption(args, "--silent")) return RunSilentAppOnly(args);
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new InstallerForm(appOnly, GetOption(args, "--install-root"),
            GetOption(args, "--bootstrap-python")));
        return 0;
    }
}
