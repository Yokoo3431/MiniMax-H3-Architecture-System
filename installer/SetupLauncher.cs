using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Threading;
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
        return "\"" + value.Replace("\"", "\\\"") + "\"";
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

        public InstallerForm()
        {
            Text = "Architect Video Studio Setup";
            Width = 720;
            Height = 480;
            MinimumSize = new Size(620, 400);
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
                Text = "Choose an installation folder. Existing ComfyUI, H3 nodes and model roots will be detected and reused when compatible.",
                AutoSize = false,
                Width = 660,
                Height = 42,
                Location = new Point(18, 48)
            };
            Controls.Add(description);

            Controls.Add(new Label {
                Text = "Installation folder:",
                AutoSize = true,
                Location = new Point(18, 105)
            });

            pathBox = new TextBox {
                Text = GetInitialInstallRoot(),
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

            status = new Label {
                Text = "Ready",
                AutoSize = true,
                Location = new Point(18, 170)
            };
            Controls.Add(status);

            progress = new ProgressBar {
                Style = ProgressBarStyle.Marquee,
                MarqueeAnimationSpeed = 30,
                Location = new Point(18, 195),
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
                Location = new Point(18, 228),
                Width = 657,
                Height = 145,
                Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right
            };
            Controls.Add(log);

            installButton = new Button {
                Text = "Install",
                Location = new Point(570, 390),
                Width = 105,
                Anchor = AnchorStyles.Bottom | AnchorStyles.Right
            };
            installButton.Click += InstallClicked;
            Controls.Add(installButton);
            AcceptButton = installButton;
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
                status.Text = "Installing and scanning for existing components...";
                AppendLog("Installing Architect Video Studio to " + selected);

                var info = new ProcessStartInfo {
                    FileName = powershell,
                    Arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File " + Quote(script),
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

    public static int Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new InstallerForm());
        return 0;
    }
}
