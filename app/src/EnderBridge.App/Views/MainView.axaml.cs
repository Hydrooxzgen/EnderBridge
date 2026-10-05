using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Input.Platform;
using Avalonia.Interactivity;
using Avalonia.Platform.Storage;
using Avalonia.Threading;
using System.Text.Json.Nodes;
using OnePointUI.Avalonia.Styling.Controls.OnePointControls;
using OnePointUI.Avalonia.Styling.Controls.OnePointControls.Navigation.SelectBar;
using EnderBridge.App.Models;
using EnderBridge.App.Services;

namespace EnderBridge.App.Views;

public partial class MainView : UserControl
{
    private Process? _serverProcess;
    private readonly HttpClient _http = new();
    private readonly DispatcherTimer _pollTimer = new();
    private string _backendUrl = "http://127.0.0.1:18888/";

    private readonly VersionManagerService _versionService = new();
    private readonly EnderBridgeApiClient _apiClient = new();
    private JsonNode? _currentConfigNode;
    private LocalCoreInfo _localCore = new();
    private List<ReleaseItem> _releases = new();
    private bool _isDownloading = false;

    private static readonly Regex AnsiRegex = new(@"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", RegexOptions.Compiled);
    private static readonly Avalonia.Media.IBrush BrushOk = Avalonia.Media.Brush.Parse("#22C55E");
    private static readonly Avalonia.Media.IBrush BrushWarn = Avalonia.Media.Brush.Parse("#EAB308");
    private static readonly Avalonia.Media.IBrush BrushDanger = Avalonia.Media.Brush.Parse("#EF4444");

    public enum ToastType
    {
        Success,
        Error,
        Warning,
        Info
    }

    public void ShowToast(string message, ToastType type = ToastType.Info, int durationMs = 3500)
    {
        Dispatcher.UIThread.Post(() =>
        {
            if (ToastContainer == null) return;

            while (ToastContainer.Children.Count >= 4)
            {
                ToastContainer.Children.RemoveAt(0);
            }

            var (icon, borderBrush, bgBrush) = type switch
            {
                ToastType.Success => ("✅", Avalonia.Media.Brush.Parse("#264532"), Avalonia.Media.Brush.Parse("#1A2B22")),
                ToastType.Error => ("❌", Avalonia.Media.Brush.Parse("#4E2222"), Avalonia.Media.Brush.Parse("#2E1818")),
                ToastType.Warning => ("⚠️", Avalonia.Media.Brush.Parse("#4A3F1F"), Avalonia.Media.Brush.Parse("#2B2516")),
                _ => ("ℹ️", Avalonia.Media.Brush.Parse("#2A374D"), Avalonia.Media.Brush.Parse("#1A2230"))
            };

            var toastCard = new Border
            {
                Classes = { "ToastCard" },
                Background = bgBrush,
                BorderBrush = borderBrush,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(8),
                Padding = new Thickness(14, 10),
                BoxShadow = Avalonia.Media.BoxShadows.Parse("0 4 16 0 #50000000"),
                Cursor = new Cursor(StandardCursorType.Hand),
                Opacity = 0,
                Margin = new Thickness(0, 20, 0, -20)
            };

            var stack = new StackPanel
            {
                Orientation = Avalonia.Layout.Orientation.Horizontal,
                Spacing = 10,
                VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center
            };

            var iconText = new TextBlock
            {
                Text = icon,
                FontSize = 14,
                VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center
            };

            var msgText = new TextBlock
            {
                Text = message,
                FontSize = 13,
                FontWeight = Avalonia.Media.FontWeight.Medium,
                Foreground = Avalonia.Media.Brushes.White,
                VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center,
                TextWrapping = Avalonia.Media.TextWrapping.Wrap,
                MaxWidth = 450
            };

            stack.Children.Add(iconText);
            stack.Children.Add(msgText);
            toastCard.Child = stack;

            bool isClosing = false;
            async void DismissToast()
            {
                if (isClosing) return;
                isClosing = true;
                toastCard.Opacity = 0;
                toastCard.Margin = new Thickness(0, 15, 0, -15);
                await Task.Delay(350);
                ToastContainer.Children.Remove(toastCard);
            }

            toastCard.PointerPressed += (s, e) => DismissToast();

            ToastContainer.Children.Add(toastCard);

            Dispatcher.UIThread.Post(() =>
            {
                toastCard.Opacity = 1;
                toastCard.Margin = new Thickness(0);
            }, DispatcherPriority.Render);

            var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(durationMs) };
            timer.Tick += (s, e) =>
            {
                timer.Stop();
                DismissToast();
            };
            timer.Start();
        });
    }

    public MainView()
    {
        InitializeComponent();

        // 规范初始化所有页面状态，防止多页面重叠卡主页
        _currentView = DashboardScrollViewer;
        DashboardScrollViewer.IsVisible = true;
        DashboardScrollViewer.Opacity = 1;
        DashboardScrollViewer.Margin = new Thickness(0);
        foreach (var v in GetAllPageViews())
        {
            if (v != DashboardScrollViewer)
            {
                v.IsVisible = false;
                v.Opacity = 0;
                v.Margin = new Thickness(0);
            }
        }

        _apiClient.SetBaseUrl(_backendUrl);
        LoadSavedSession();

        RefreshLocalCoreStatus();
        var isFirstRun = CheckIsFirstRun();

        if (!_localCore.Exists)
        {
            CoreMissingBanner.IsVisible = true;
            AppendLog("[GUI 提示] 本地未检测到 main.py 核心服务端文件。");
            AppendLog("[GUI 提示] 您可前往 [📦 版本管理] 页面或点击上方横幅一键自动下载并部署最新版！");
        }
        else
        {
            AppendLog($"[GUI] 发现主入口: {_localCore.MainPyPath} (版本: {_localCore.Version})");
        }

        // 首次运行检查
        if (isFirstRun)
        {
            AppendLog("[GUI 首次运行] 检测到 EnderBridge 尚未配置。点击主界面 [▶ 启动服务端] 或前往 [⚙️ 系统配置] 即可开始设置。");
        }

        _pollTimer.Interval = TimeSpan.FromSeconds(2);
        _pollTimer.Tick += async (s, e) =>
        {
            try
            {
                await CheckHealthAsync();

                // 实时同步内置浏览器地址栏 (当用户未聚焦输入框且网页已加载时)
                if (BrowserContainer.IsVisible && !BrowserUrlTextBox.IsFocused && InAppWebView.Source != null)
                {
                    var cur = InAppWebView.Source.ToString();
                    if (!string.IsNullOrEmpty(cur) && BrowserUrlTextBox.Text != cur)
                    {
                        BrowserUrlTextBox.Text = cur;
                    }
                }
            }
            catch {}
        };
        _pollTimer.Start();

        InitInAppBrowser();

        AppDomain.CurrentDomain.ProcessExit += (s, e) => KillServer();
    }

    private bool CheckIsFirstRun()
    {
        try
        {
            if (!_localCore.Exists || string.IsNullOrEmpty(_localCore.RootDirectory))
            {
                return false;
            }

            var cfgPath = Path.Combine(_localCore.RootDirectory, "config", "config.json");
            if (!File.Exists(cfgPath))
            {
                cfgPath = Path.Combine(_localCore.RootDirectory, "config.json");
            }

            if (!File.Exists(cfgPath))
            {
                return true;
            }

            var text = File.ReadAllText(cfgPath);
            using var doc = JsonDocument.Parse(text);
            if (doc.RootElement.TryGetProperty("is_first_run", out var prop))
            {
                return prop.ValueKind == JsonValueKind.True;
            }
        }
        catch {}
        return false;
    }

    private void UpdateCorePathTextBoxes(string? path)
    {
        var val = path ?? "";
        if (CustomCorePathTextBox != null) CustomCorePathTextBox.Text = val;
        if (ConfigCorePathTextBox != null) ConfigCorePathTextBox.Text = val;
        if (SettingsCorePathTextBox != null) SettingsCorePathTextBox.Text = val;
    }

    private void RefreshLocalCoreStatus()
    {
        _localCore = _versionService.CheckLocalCore();
        UpdateCorePathTextBoxes(_versionService.GetCustomCorePath());

        if (_localCore.Exists)
        {
            VerLocalStatusText.Text = $"● 核心已就绪 (当前版本: {_localCore.Version})";
            VerLocalStatusText.Foreground = BrushOk;
            VerLocalPathText.Text = $"主入口路径: {_localCore.MainPyPath}";
            CoreMissingBanner.IsVisible = false;
            BottomVerText.Text = $"EnderBridge {_localCore.Version}";
        }
        else
        {
            VerLocalStatusText.Text = "○ 未安装 / 核心文件缺失 (未找到 main.py 或 app.py)";
            VerLocalStatusText.Foreground = BrushDanger;
            VerLocalPathText.Text = !string.IsNullOrEmpty(_localCore.RootDirectory)
                ? $"目标工作/安装目录: {_localCore.RootDirectory}"
                : "建议点击下方 [下载最新版] 自动部署到当前运行目录。";
            CoreMissingBanner.IsVisible = true;
            BottomVerText.Text = "EnderBridge (核心未就绪)";
        }
    }

    private string GetSelectedMirror()
    {
        var idx = MirrorComboBox?.SelectedIndex ?? 0;
        return idx switch
        {
            1 => "https://ghproxy.net/",
            2 => "https://mirror.ghproxy.com/",
            _ => ""
        };
    }

    private async Task FetchAndRenderReleasesAsync()
    {
        try
        {
            ReleasesListContainer.Children.Clear();
            ReleasesListContainer.Children.Add(new TextBlock
            {
                Text = "正在从 GitHub 获取版本列表...",
                Foreground = Avalonia.Media.Brush.Parse("#888888"),
                HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Center,
                Margin = new Avalonia.Thickness(0, 20)
            });

            var mirror = GetSelectedMirror();
            _releases = await _versionService.FetchReleasesAsync(mirror);

            ReleasesListContainer.Children.Clear();
            if (_releases.Count == 0)
            {
                ReleasesListContainer.Children.Add(new TextBlock
                {
                    Text = "未能获取到 Releases 列表，请检查网络连接或尝试切换国内加速镜像。",
                    Foreground = BrushWarn,
                    HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Center,
                    Margin = new Avalonia.Thickness(0, 20)
                });
                return;
            }

            foreach (var rel in _releases)
            {
                var card = new Border
                {
                    Background = Avalonia.Media.Brush.Parse("#16181D"),
                    BorderBrush = Avalonia.Media.Brush.Parse("#2A2E39"),
                    BorderThickness = new Avalonia.Thickness(1),
                    CornerRadius = new Avalonia.CornerRadius(8),
                    Padding = new Avalonia.Thickness(14)
                };

                var grid = new Grid
                {
                    ColumnDefinitions = new ColumnDefinitions("*,Auto")
                };

                var leftStack = new StackPanel { Spacing = 6 };
                var headerStack = new StackPanel { Orientation = Avalonia.Layout.Orientation.Horizontal, Spacing = 8 };

                headerStack.Children.Add(new TextBlock
                {
                    Text = rel.TagName,
                    FontWeight = Avalonia.Media.FontWeight.Bold,
                    FontSize = 15,
                    Foreground = Avalonia.Media.Brushes.White,
                    VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center
                });

                if (rel.IsPrerelease)
                {
                    var preBadge = new Border
                    {
                        Background = Avalonia.Media.Brush.Parse("#3D3010"),
                        BorderBrush = Avalonia.Media.Brush.Parse("#785010"),
                        BorderThickness = new Avalonia.Thickness(1),
                        CornerRadius = new Avalonia.CornerRadius(4),
                        Padding = new Avalonia.Thickness(6, 2),
                        Child = new TextBlock { Text = "预发布", FontSize = 10, Foreground = Avalonia.Media.Brush.Parse("#F59E0B") }
                    };
                    headerStack.Children.Add(preBadge);
                }

                headerStack.Children.Add(new TextBlock
                {
                    Text = $"发布于: {rel.PublishedAt}",
                    FontSize = 11,
                    Foreground = Avalonia.Media.Brush.Parse("#888888"),
                    VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center
                });

                leftStack.Children.Add(headerStack);

                var sizeStr = rel.SizeBytes > 0 ? $"({rel.SizeBytes / 1024.0 / 1024.0:F2} MB)" : "";
                var assetStr = !string.IsNullOrEmpty(rel.AssetName) ? $"资源包: {rel.AssetName} {sizeStr}" : "Release 源码包";
                leftStack.Children.Add(new TextBlock
                {
                    Text = assetStr,
                    FontSize = 12,
                    Foreground = Avalonia.Media.Brush.Parse("#38BDF8")
                });

                if (!string.IsNullOrWhiteSpace(rel.Body))
                {
                    var bodyPreview = rel.Body.Trim();
                    if (bodyPreview.Length > 200) bodyPreview = bodyPreview.Substring(0, 200) + "...";
                    leftStack.Children.Add(new TextBlock
                    {
                        Text = bodyPreview,
                        FontSize = 11,
                        Foreground = Avalonia.Media.Brush.Parse("#AAAAAA"),
                        TextWrapping = Avalonia.Media.TextWrapping.Wrap,
                        LineHeight = 16
                    });
                }

                grid.Children.Add(leftStack);
                Grid.SetColumn(leftStack, 0);

                var rightStack = new StackPanel
                {
                    Orientation = Avalonia.Layout.Orientation.Horizontal,
                    Spacing = 8,
                    VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center
                };

                var installBtn = new Button
                {
                    Content = "📥 安装此版本",
                    Background = Avalonia.Media.Brush.Parse("#3B82F6"),
                    Foreground = Avalonia.Media.Brushes.White,
                    Padding = new Avalonia.Thickness(12, 6),
                    CornerRadius = new Avalonia.CornerRadius(6),
                    FontSize = 12
                };
                var targetRelease = rel;
                installBtn.Click += async (s, e) =>
                {
                    if (_serverProcess != null && !_serverProcess.HasExited)
                    {
                        if (string.IsNullOrEmpty(_apiClient.Token) || _currentUserRole == "guest" || _currentUserRole == "viewer")
                        {
                            var noPerm = "无权限: 需要管理员或 update 权限方可在服务端运行时安装新版本！";
                            AppendLog($"[GUI 权限拦截] ❌ {noPerm}");
                            ShowToast($"❌ {noPerm}", ToastType.Error);
                            return;
                        }
                    }
                    await DownloadAndInstallReleaseAsync(targetRelease);
                };
                rightStack.Children.Add(installBtn);

                if (!string.IsNullOrEmpty(rel.HtmlUrl))
                {
                    var ghBtn = new Button
                    {
                        Content = "🌐 GitHub",
                        Background = Avalonia.Media.Brush.Parse("#1F2937"),
                        Foreground = Avalonia.Media.Brush.Parse("#E5E7EB"),
                        Padding = new Avalonia.Thickness(10, 6),
                        CornerRadius = new Avalonia.CornerRadius(6),
                        FontSize = 12
                    };
                    ghBtn.Click += (s, e) =>
                    {
                        try
                        {
                            Process.Start(new ProcessStartInfo { FileName = targetRelease.HtmlUrl, UseShellExecute = true });
                        }
                        catch {}
                    };
                    rightStack.Children.Add(ghBtn);
                }

                grid.Children.Add(rightStack);
                Grid.SetColumn(rightStack, 1);

                card.Child = grid;
                ReleasesListContainer.Children.Add(card);
            }
        }
        catch (Exception ex)
        {
            ReleasesListContainer.Children.Clear();
            ReleasesListContainer.Children.Add(new TextBlock
            {
                Text = $"加载失败: {ex.Message}",
                Foreground = BrushDanger,
                HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Center,
                Margin = new Avalonia.Thickness(0, 20)
            });
        }
    }

    private async Task DownloadAndInstallReleaseAsync(ReleaseItem rel)
    {
        if (_isDownloading)
        {
            AppendLog("[GUI] 当前已有正在下载中的任务，请稍候...");
            ShowToast("当前已有正在进行的下载任务，请稍候", ToastType.Warning);
            return;
        }

        // 1. 权限拦截：如果服务端正在运行，必须具备管理员或 update 权限方可通过接口更新
        if (_serverProcess != null && !_serverProcess.HasExited)
        {
            if (string.IsNullOrEmpty(_apiClient.Token) || _currentUserRole == "guest" || _currentUserRole == "viewer")
            {
                var noPerm = "无权限: 需要管理员或 update 权限方可在服务端运行时安装新版本！";
                AppendLog($"[GUI 权限拦截] ❌ {noPerm}");
                ShowToast($"❌ {noPerm}", ToastType.Error);
                return;
            }

            _isDownloading = true;
            VerProgressCard.IsVisible = true;
            VerProgressBar.Value = 35;
            VerProgressPercent.Text = "35%";
            VerProgressMessage.Text = $"正在通过后端触发在线更新与重启 ({rel.TagName})...";

            try
            {
                AppendLog($"[GUI 核心更新] 正在通过后端接口 (/api/update/install) 安全升级至 {rel.TagName} ...");
                var (ok, updateMsg) = await _apiClient.InstallUpdateAsync(rel.TagName);
                if (!ok)
                {
                    AppendLog($"[GUI 核心更新] ❌ 后端更新失败: {updateMsg}");
                    ShowToast($"❌ 更新失败: {updateMsg}", ToastType.Error);
                }
                else
                {
                    AppendLog($"[GUI 核心更新] ✅ {updateMsg}");
                    ShowToast($"✅ 服务器正在执行更新与重启...", ToastType.Success);
                }
            }
            catch (Exception ex)
            {
                AppendLog($"[GUI 核心更新] ❌ 接口请求异常: {ex.Message}");
                ShowToast($"❌ 更新异常: {ex.Message}", ToastType.Error);
            }
            finally
            {
                _isDownloading = false;
                await Task.Delay(2000);
                VerProgressCard.IsVisible = false;
            }
            return;
        }

        // 2. 离线/未启动时的本地下载解压：提示用户选择目标下载与安装目录
        var customPath = _versionService.GetCustomCorePath();
        var defaultTargetDir = _localCore.Exists && !string.IsNullOrEmpty(_localCore.RootDirectory)
            ? _localCore.RootDirectory
            : (!string.IsNullOrWhiteSpace(customPath) && Directory.Exists(customPath)
                ? customPath
                : (!string.IsNullOrWhiteSpace(customPath) && File.Exists(customPath)
                    ? (Path.GetDirectoryName(customPath) ?? Environment.CurrentDirectory)
                    : (!AppContext.BaseDirectory.Contains(".net", StringComparison.OrdinalIgnoreCase) && !AppContext.BaseDirectory.Contains("temp", StringComparison.OrdinalIgnoreCase)
                        ? AppContext.BaseDirectory
                        : Environment.CurrentDirectory)));

        var targetDir = defaultTargetDir;

        try
        {
            var topLevel = TopLevel.GetTopLevel(this);
            if (topLevel?.StorageProvider != null)
            {
                Avalonia.Platform.Storage.IStorageFolder? startLocation = null;
                try
                {
                    if (Directory.Exists(defaultTargetDir))
                    {
                        startLocation = await topLevel.StorageProvider.TryGetFolderFromPathAsync(defaultTargetDir);
                    }
                }
                catch {}

                var folders = await topLevel.StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions
                {
                    Title = $"选择 {rel.TagName} 服务端下载与解压安装目录",
                    AllowMultiple = false,
                    SuggestedStartLocation = startLocation
                });

                if (folders == null || folders.Count == 0)
                {
                    AppendLog("[GUI 核心下载] 用户已取消选择下载安装目录，下载已终止。");
                    ShowToast("已取消下载安装", ToastType.Info);
                    return;
                }

                var pickedPath = folders[0].Path.LocalPath;
                if (string.IsNullOrWhiteSpace(pickedPath))
                {
                    ShowToast("选择的目录路径无效", ToastType.Error);
                    return;
                }

                targetDir = pickedPath;
                _versionService.SetCustomCorePath(targetDir);
                UpdateCorePathTextBoxes(targetDir);
                RefreshLocalCoreStatus();
            }
        }
        catch (Exception ex)
        {
            AppendLog($"[GUI 核心下载] 路径选择器异常: {ex.Message}，继续使用目标目录: {targetDir}");
        }

        // 本地磁盘写入权限探测检查
        try
        {
            var testFile = Path.Combine(targetDir, $".perm_test_{Guid.NewGuid():N}");
            await File.WriteAllTextAsync(testFile, "eb_perm_test");
            File.Delete(testFile);
        }
        catch (Exception ex)
        {
            var permMsg = $"无文件写入权限: 目标目录无法写入文件 ({ex.Message})";
            AppendLog($"[GUI 权限拦截] ❌ {permMsg}");
            ShowToast($"❌ {permMsg}", ToastType.Error);
            return;
        }

        _isDownloading = true;
        VerProgressCard.IsVisible = true;
        VerProgressBar.Value = 0;
        VerProgressPercent.Text = "0%";
        VerProgressMessage.Text = $"准备下载 {rel.TagName}...";

        try
        {
            AppendLog($"[GUI 核心安装] 准备下载 {rel.TagName} ({rel.AssetName}) 至目录: {targetDir}");

            var (success, msg) = await _versionService.DownloadAndInstallAsync(rel, targetDir, (pct, status) =>
            {
                Dispatcher.UIThread.Post(() =>
                {
                    VerProgressBar.Value = pct;
                    VerProgressPercent.Text = $"{pct}%";
                    VerProgressMessage.Text = status;
                });
            });

            if (success)
            {
                AppendLog($"[GUI 成功] {msg}");
                ShowToast($"✅ 已成功安装 EnderBridge {rel.TagName}！", ToastType.Success);
                RefreshLocalCoreStatus();
                AppendLog($"[GUI 提示] EnderBridge 核心已安装就绪 (路径: {_localCore.MainPyPath})，点击 [▶ 启动] 即可拉起！");

                if (CheckIsFirstRun())
                {
                    AppendLog("[GUI 首次运行] 检测到 EnderBridge 处于未配置状态，点击主界面 [▶ 启动] 即可拉起并开启配置向导。");
                }
            }
            else
            {
                AppendLog($"[GUI 失败] {msg}");
                ShowToast($"❌ {msg}", ToastType.Error);
            }
        }
        catch (Exception ex)
        {
            AppendLog($"[GUI 异常] 安装过程发生异常: {ex.Message}");
            ShowToast($"❌ 安装异常: {ex.Message}", ToastType.Error);
        }
        finally
        {
            _isDownloading = false;
            await Task.Delay(2000);
            VerProgressCard.IsVisible = false;
        }
    }

    private async void AutoDownloadLatest_Click(object? sender, RoutedEventArgs e)
    {
        if (_isDownloading)
        {
            AppendLog("[GUI] 当前正在下载中，请稍候...");
            ShowToast("当前已有正在进行的下载任务，请稍候", ToastType.Warning);
            return;
        }

        if (_serverProcess != null && !_serverProcess.HasExited)
        {
            if (string.IsNullOrEmpty(_apiClient.Token) || _currentUserRole == "guest" || _currentUserRole == "viewer")
            {
                var noPerm = "无权限: 需要管理员或 update 权限方可在服务端运行时安装新版本！";
                AppendLog($"[GUI 权限拦截] ❌ {noPerm}");
                ShowToast($"❌ {noPerm}", ToastType.Error);
                return;
            }
        }

        AppendLog("[GUI] 正在检索云端最新发布版本...");
        if (_releases.Count == 0)
        {
            var mirror = GetSelectedMirror();
            _releases = await _versionService.FetchReleasesAsync(mirror);
        }

        var latest = _releases.FirstOrDefault();
        if (latest == null)
        {
            AppendLog("[GUI 错误] 未能获取到云端版本，请检查网络连接后重试！");
            return;
        }

        AppendLog($"[GUI] 锁定最新版本: {latest.TagName}，开始自动下载并安装...");
        await DownloadAndInstallReleaseAsync(latest);
    }

    private void VerScanLocal_Click(object? sender, RoutedEventArgs e)
    {
        RefreshLocalCoreStatus();
        AppendLog("[GUI] 本地扫描完成: " + (_localCore.Exists ? $"已就绪 (入口: {_localCore.MainPyPath}, 版本: {_localCore.Version})" : "未找到 main.py 或 app.py"));
    }

    private async void BrowseCustomCoreFile_Click(object? sender, RoutedEventArgs e)
    {
        try
        {
            var topLevel = TopLevel.GetTopLevel(this);
            if (topLevel?.StorageProvider == null) return;

            var files = await topLevel.StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
            {
                Title = "选择 EnderBridge 服务端主入口 (main.py 或 app.py)",
                AllowMultiple = false,
                FileTypeFilter = new[]
                {
                    new FilePickerFileType("Python Files (*.py)") { Patterns = new[] { "*.py" } },
                    new FilePickerFileType("All Files (*.*)") { Patterns = new[] { "*.*" } }
                }
            });

            if (files.Count > 0)
            {
                var localPath = files[0].Path.LocalPath;
                if (!string.IsNullOrEmpty(localPath))
                {
                    UpdateCorePathTextBoxes(localPath);
                    _versionService.SetCustomCorePath(localPath);
                    RefreshLocalCoreStatus();
                    AppendLog($"[GUI 核心路径] 已手动指定服务端主文件: {localPath}");
                    ShowToast("✅ 已成功设置服务端文件路径", ToastType.Success);
                }
            }
        }
        catch (Exception ex)
        {
            AppendLog($"[GUI 核心路径] 选择文件异常: {ex.Message}");
        }
    }

    private async void BrowseCustomCoreDir_Click(object? sender, RoutedEventArgs e)
    {
        try
        {
            var topLevel = TopLevel.GetTopLevel(this);
            if (topLevel?.StorageProvider == null) return;

            var folders = await topLevel.StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions
            {
                Title = "选择 EnderBridge 服务端项目根目录"
            });

            if (folders.Count > 0)
            {
                var localPath = folders[0].Path.LocalPath;
                if (!string.IsNullOrEmpty(localPath))
                {
                    UpdateCorePathTextBoxes(localPath);
                    _versionService.SetCustomCorePath(localPath);
                    RefreshLocalCoreStatus();
                    AppendLog($"[GUI 核心路径] 已手动指定服务端工作目录: {localPath}");
                    ShowToast("✅ 已成功设置服务端根目录", ToastType.Success);
                }
            }
        }
        catch (Exception ex)
        {
            AppendLog($"[GUI 核心路径] 选择目录异常: {ex.Message}");
        }
    }

    private void SaveCustomCorePath_Click(object? sender, RoutedEventArgs e)
    {
        ApplyCorePath(CustomCorePathTextBox?.Text);
    }

    private void SaveConfigCorePath_Click(object? sender, RoutedEventArgs e)
    {
        ApplyCorePath(ConfigCorePathTextBox?.Text);
    }

    private void SaveSettingsCorePath_Click(object? sender, RoutedEventArgs e)
    {
        ApplyCorePath(SettingsCorePathTextBox?.Text);
    }

    private void ApplyCorePath(string? rawPath)
    {
        var path = rawPath?.Trim();
        if (string.IsNullOrEmpty(path))
        {
            _versionService.SetCustomCorePath(null);
            UpdateCorePathTextBoxes("");
            RefreshLocalCoreStatus();
            AppendLog("[GUI 核心路径] 已清空自定义路径，恢复默认自动探测。");
            ShowToast("已恢复为默认自动探测", ToastType.Info);
        }
        else
        {
            _versionService.SetCustomCorePath(path);
            UpdateCorePathTextBoxes(path);
            RefreshLocalCoreStatus();
            AppendLog($"[GUI 核心路径] 已保存自定义路径: {path}");
            ShowToast("✅ 服务端路径已更新并保存", ToastType.Success);
        }
    }

    private void ResetCustomCorePath_Click(object? sender, RoutedEventArgs e)
    {
        UpdateCorePathTextBoxes("");
        _versionService.SetCustomCorePath(null);
        RefreshLocalCoreStatus();
        AppendLog("[GUI 核心路径] 已恢复默认自动探测模式。");
        ShowToast("已恢复为默认自动探测模式", ToastType.Info);
    }

    private async void VerRefreshReleases_Click(object? sender, RoutedEventArgs e)
    {
        await FetchAndRenderReleasesAsync();
    }

    public void ShowEmbeddedBrowser(string? url = null)
    {
        EnsureServerRunningAndShowUrl(url ?? _backendUrl);
    }

    private string GetFullUrl(string subPath)
    {
        var baseU = _backendUrl.TrimEnd('/') + "/";
        return baseU + subPath.TrimStart('/');
    }

    private void EnsureServerRunningAndShowUrl(string url)
    {
        BrowserUrlTextBox.Text = url;
        BrowserContainer.IsVisible = true;

        if (_serverProcess == null || _serverProcess.HasExited)
        {
            RefreshLocalCoreStatus();
            if (_localCore.Exists)
            {
                AppendLog($"[GUI] 正在启动 EnderBridge 核心服务以加载 {url} ...");
                StartServer_Click(this, new RoutedEventArgs());
            }
            else
            {
                AppendLog("[GUI] 本地未找到核心服务，请先在 [📦 版本管理] 下载安装核心。");
            }
        }

        NavigateWebView(url);
    }

    private void InitInAppBrowser()
    {
        try
        {
            // 1. 监听导航开始事件: 实时同步目标地址到地址栏
            InAppWebView.NavigationStarted += (s, e) =>
            {
                if (e.Request != null)
                {
                    UpdateBrowserUrlBar(e.Request.ToString());
                }
            };

            // 2. 监听导航完成事件: 更新地址栏并尝试获取最终真实页面 URL (如经过重定向或前端 SPA 路由)
            InAppWebView.NavigationCompleted += async (s, e) =>
            {
                if (e.Request != null)
                {
                    UpdateBrowserUrlBar(e.Request.ToString());
                }

                // 针对 SPA 单页路由或重定向，尝试从 JS 获取 window.location.href
                try
                {
                    var realUrl = await InAppWebView.InvokeScript("window.location.href");
                    if (!string.IsNullOrWhiteSpace(realUrl) && realUrl != "null" && realUrl != "undefined")
                    {
                        realUrl = realUrl.Trim('"', '\'', ' ');
                        UpdateBrowserUrlBar(realUrl);
                    }
                }
                catch {}
            };

            // 3. 监听 Source 依赖属性变化
            InAppWebView.PropertyChanged += (s, e) =>
            {
                if (e.Property == Avalonia.Controls.NativeWebView.SourceProperty && InAppWebView.Source != null)
                {
                    UpdateBrowserUrlBar(InAppWebView.Source.ToString());
                }
            };
        }
        catch (Exception ex)
        {
            AppendLog($"[GUI 内置浏览器] 初始化事件监听异常: {ex.Message}");
        }
    }

    private void UpdateBrowserUrlBar(string? url)
    {
        if (string.IsNullOrWhiteSpace(url)) return;
        Dispatcher.UIThread.Post(() =>
        {
            if (!BrowserUrlTextBox.IsFocused)
            {
                BrowserUrlTextBox.Text = url;
            }
        });
    }

    private void NavigateWebView(string url)
    {
        try
        {
            var uri = new Uri(url);
            InAppWebView.Navigate(uri);
            InAppWebView.Source = uri;
            UpdateBrowserUrlBar(url);
        }
        catch (Exception ex)
        {
            AppendLog($"[GUI 内置浏览器] 无法加载页面: {ex.Message}");
        }
    }

    private string _browserReturnTag = "Dashboard";

    private void BrowserBackToDashboard_Click(object? sender, RoutedEventArgs e)
    {
        SelectTab(_browserReturnTag ?? "Dashboard");
    }

    private void BrowserGoBack_Click(object? sender, RoutedEventArgs e)
    {
        try
        {
            if (InAppWebView.CanGoBack)
            {
                InAppWebView.GoBack();
            }
        }
        catch {}
    }

    private void BrowserGoForward_Click(object? sender, RoutedEventArgs e)
    {
        try
        {
            if (InAppWebView.CanGoForward)
            {
                InAppWebView.GoForward();
            }
        }
        catch {}
    }

    private void BrowserRefresh_Click(object? sender, RoutedEventArgs e)
    {
        try
        {
            if (InAppWebView.Source != null)
            {
                InAppWebView.Refresh();
                AppendLog("[GUI 内置浏览器] 正在刷新网页...");
                return;
            }
        }
        catch (Exception ex)
        {
            AppendLog($"[GUI 内置浏览器] 原生刷新失败: {ex.Message}，尝试使用当前地址重新载入");
        }

        var url = BrowserUrlTextBox.Text?.Trim();
        if (string.IsNullOrEmpty(url)) url = _backendUrl;
        NavigateWebView(url);
    }

    private void BrowserUrl_KeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter)
        {
            BrowserNavigate_Click(sender, e);
        }
    }

    private void BrowserNavigate_Click(object? sender, RoutedEventArgs e)
    {
        var url = BrowserUrlTextBox.Text?.Trim();
        if (!string.IsNullOrEmpty(url))
        {
            if (!url.StartsWith("http://", StringComparison.OrdinalIgnoreCase) &&
                !url.StartsWith("https://", StringComparison.OrdinalIgnoreCase) &&
                !url.StartsWith("file://", StringComparison.OrdinalIgnoreCase))
            {
                url = "http://" + url;
                BrowserUrlTextBox.Text = url;
            }
            NavigateWebView(url);
        }
    }

    private void OpenExternalBrowser_Click(object? sender, RoutedEventArgs e)
    {
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = BrowserUrlTextBox.Text ?? _backendUrl,
                UseShellExecute = true
            });
        }
        catch (Exception ex)
        {
            AppendLog($"[GUI] 外部浏览器打开失败: {ex.Message}");
        }
    }

    private IEnumerable<Control> GetAllPageViews()
    {
        yield return DashboardScrollViewer;
        yield return VersionsScrollViewer;
        yield return ConsoleContainer;
        yield return ModsScrollViewer;
        yield return ConfigScrollViewer;
        yield return StudioScrollViewer;
        yield return SettingsScrollViewer;
        yield return BrowserContainer;
    }

    public void SelectTab(string tag)
    {
        if (SelTag != null)
        {
            for (int i = 0; i < SelTag.ItemCount; i++)
            {
                if (SelTag.Items[i] is SelectBarItem item && item.Tag?.ToString() == tag)
                {
                    SelTag.SelectedIndex = i;
                    return;
                }
            }
        }
        SwitchView(tag);
    }

    private void SelTag_OnSelectionChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (SelTag?.SelectedItem is SelectBarItem item && item.Tag is string tag)
        {
            SwitchView(tag);
        }
    }

    private Control? _currentView = null;
    private CancellationTokenSource? _navCts;

    private async void AnimateSwitchView(Control nextView, string title)
    {
        if (_currentView == nextView && nextView.IsVisible) return;

        _navCts?.Cancel();
        _navCts = new CancellationTokenSource();
        var token = _navCts.Token;

        var prevView = _currentView;
        _currentView = nextView;

        // 动画前先强制隐藏所有与当前切换无关的其他视图，杜绝页面叠底重影
        foreach (var view in GetAllPageViews())
        {
            if (view != prevView && view != nextView)
            {
                view.IsVisible = false;
                view.Opacity = 0;
                view.Margin = new Thickness(0);
            }
        }

        // 1. 顶部标题平滑淡入滑行动画 (BedrockBoot HeaderContent 风格)
        try
        {
            PageTitleText.Opacity = 0;
            PageTitleText.Margin = new Thickness(24, 0, -24, 0);
            PageTitleText.Text = title;
            Dispatcher.UIThread.Post(() =>
            {
                PageTitleText.Opacity = 1;
                PageTitleText.Margin = new Thickness(0);
            }, DispatcherPriority.Render);
        }
        catch {}

        // 2. 如果是首次加载 (无上一页面)，直接平滑显示
        if (prevView == null || prevView == nextView)
        {
            nextView.Opacity = 0;
            nextView.Margin = new Thickness(0, 40, 0, -40);
            nextView.IsVisible = true;
            Dispatcher.UIThread.Post(() =>
            {
                nextView.Opacity = 1;
                nextView.Margin = new Thickness(0);
            }, DispatcherPriority.Render);
            return;
        }

        // 3. 上一视图平滑滑出并淡出 (BedrockBoot 0.38s ExponentialEaseOut)
        prevView.Opacity = 0;
        prevView.Margin = new Thickness(0, -35, 0, 35);

        // 4. 新视图准备：重置初始偏移并显示
        nextView.Opacity = 0;
        nextView.Margin = new Thickness(0, 45, 0, -45);
        nextView.IsVisible = true;

        // 下一渲染帧触发平滑滑入
        Dispatcher.UIThread.Post(() =>
        {
            nextView.Opacity = 1;
            nextView.Margin = new Thickness(0);
        }, DispatcherPriority.Render);

        // 5. 动画完成或被中途打断时，保证除了 _currentView 以外的所有视图全部隐藏
        try
        {
            await Task.Delay(380, token);
        }
        catch (TaskCanceledException) {}
        finally
        {
            foreach (var view in GetAllPageViews())
            {
                if (view != _currentView)
                {
                    view.IsVisible = false;
                    view.Opacity = 0;
                    view.Margin = new Thickness(0);
                }
            }
        }
    }

    private void SwitchView(string tag)
    {
        Control nextView;
        string title;

        switch (tag)
        {
            case "Dashboard":
                title = "📊 运行仪表盘";
                nextView = DashboardScrollViewer;
                break;
            case "Versions":
                title = "📦 版本管理与在线安装";
                nextView = VersionsScrollViewer;
                RefreshLocalCoreStatus();
                if (_releases.Count == 0)
                {
                    _ = FetchAndRenderReleasesAsync();
                }
                break;
            case "Console":
                title = "💻 独立终端控制台 (Terminal)";
                nextView = ConsoleContainer;
                break;
            case "Mods":
                title = "🧩 模组管理中心 (Native API)";
                nextView = ModsScrollViewer;
                _ = FetchAndRenderModsAsync();
                break;
            case "Config":
                title = "⚙️ 系统与互联配置 (Native API)";
                nextView = ConfigScrollViewer;
                _ = FetchAndRenderConfigAsync();
                break;
            case "Studio":
                title = "🎨 创意工坊与蓝图资产 (Native API)";
                nextView = StudioScrollViewer;
                _ = FetchAndRenderStudioAsync();
                break;
            case "Settings":
                title = "🛡️ 备份快照与权限矩阵 (Native API)";
                nextView = SettingsScrollViewer;
                _ = FetchAndRenderBackupsAndPermissionsAsync();
                break;
            case "WebUI":
                title = "🌐 Web 网页管理端";
                nextView = BrowserContainer;
                EnsureServerRunningAndShowUrl(_backendUrl);
                break;
            default:
                title = "📊 运行仪表盘";
                nextView = DashboardScrollViewer;
                break;
        }

        AnimateSwitchView(nextView, title);
    }

    // ==========================================
    // 1. 原生模组管理 API 交互 (/api/mods)
    // ==========================================
    private async Task FetchAndRenderModsAsync()
    {
        ServerModsContainer.Children.Clear();
        ClientModsContainer.Children.Clear();
        DisabledModsContainer.Children.Clear();

        ServerModsContainer.Children.Add(new TextBlock { Text = "正在从后端 API (/api/mods) 检索加载模组...", Foreground = BrushWarn, Margin = new Thickness(6) });

        var data = await _apiClient.GetModsAsync();
        ServerModsContainer.Children.Clear();

        if (data == null)
        {
            var rootDir = _localCore.RootDirectory ?? AppContext.BaseDirectory;
            var cfgJsonPath = Path.Combine(rootDir, "config", "config.json");
            if (!File.Exists(cfgJsonPath)) cfgJsonPath = Path.Combine(rootDir, "config.json");

            JsonObject? offlineServerMods = null;
            JsonObject? offlineClientMods = null;

            if (File.Exists(cfgJsonPath))
            {
                try
                {
                    var text = await File.ReadAllTextAsync(cfgJsonPath);
                    var cfgNode = JsonNode.Parse(text);
                    offlineServerMods = cfgNode?["mods"]?["server"]?.AsObject();
                    offlineClientMods = cfgNode?["mods"]?["client"]?.AsObject();
                }
                catch {}
            }

            var modDir = Directory.Exists(Path.Combine(rootDir, "mod")) 
                ? Path.Combine(rootDir, "mod") 
                : Path.Combine(rootDir, "mods");

            int sCount = offlineServerMods?.Count ?? 0;
            int cCount = offlineClientMods?.Count ?? 0;

            if (sCount > 0 || cCount > 0)
            {
                ModsSummaryText.Text = $"本地配置文件已挂载：服务端 {sCount} 个，客户端 {cCount} 个 (离线模式 - 服务端未启动)";

                if (offlineServerMods != null)
                {
                    foreach (var kv in offlineServerMods)
                    {
                        var name = kv.Key;
                        var modPath = kv.Value?.ToString() ?? "";
                        var card = CreateSettingCard(name, $"目标模块: {modPath}", "\xE74C", new TextBlock { Text = "○ 离线就绪", Foreground = BrushWarn, VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center });
                        ServerModsContainer.Children.Add(card);
                    }
                }

                if (offlineClientMods != null)
                {
                    foreach (var kv in offlineClientMods)
                    {
                        var name = kv.Key;
                        var modPath = kv.Value?.ToString() ?? "";
                        var card = CreateSettingCard(name, $"目标模块: {modPath}", "\xE74C", new TextBlock { Text = "○ 离线就绪", Foreground = BrushWarn, VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center });
                        ClientModsContainer.Children.Add(card);
                    }
                }
            }
            else if (Directory.Exists(modDir))
            {
                var files = Directory.GetFiles(modDir, "*.py").Concat(Directory.GetDirectories(modDir)).ToList();
                ModsSummaryText.Text = $"本地目录已发现 {files.Count} 个插件/模组 (服务端未运行)";
                foreach (var f in files)
                {
                    var name = Path.GetFileName(f);
                    var card = CreateSettingCard(name, $"本地文件: {f}", "\xE74C", new TextBlock { Text = "○ 离线检测", Foreground = BrushWarn, VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center });
                    ServerModsContainer.Children.Add(card);
                }
            }
            else
            {
                ServerModsContainer.Children.Add(new TextBlock { Text = "⚠️ 服务端未运行且本地 mod 目录为空。请启动服务或在 mod 文件夹放置模组。", Foreground = BrushWarn, Margin = new Thickness(6) });
            }
            return;
        }

        // 解析 API 返回结构：{"ok": true, "mods": {"client": {...}, "server": {...}, "disabled": {"client": {...}, "server": {...}}}, "safeMode": false}
        var modsNode = data["mods"]?.AsObject() ?? data.AsObject();
        var serverMods = modsNode["server"]?.AsObject();
        var clientMods = modsNode["client"]?.AsObject();
        var disabledNode = modsNode["disabled"]?.AsObject();
        var disabledServer = disabledNode?["server"]?.AsObject();
        var disabledClient = disabledNode?["client"]?.AsObject();

        int sActiveCount = serverMods?.Count ?? 0;
        int cActiveCount = clientMods?.Count ?? 0;
        int sDisCount = disabledServer?.Count ?? 0;
        int cDisCount = disabledClient?.Count ?? 0;
        int totalDisabled = sDisCount + cDisCount;

        bool isSafeMode = data["safeMode"]?.GetValue<bool>() ?? false;
        var safeModeText = isSafeMode ? " [⚠️ 已处于安全排障模式]" : "";

        ModsSummaryText.Text = $"当前已挂载模组：服务端 {sActiveCount} 个活跃，客户端 {cActiveCount} 个活跃，共 {totalDisabled} 个已禁用{safeModeText} (实时 API 响应)";

        // 1. 渲染服务端活跃模组
        if (serverMods != null && serverMods.Count > 0)
        {
            foreach (var kv in serverMods)
            {
                var name = kv.Key;
                var info = kv.Value;
                var path = info?["path"]?.ToString() ?? "";
                var status = info?["status"]?.ToString() ?? "ready";
                var statusLabel = info?["statusLabel"]?.ToString() ?? "就绪";
                var error = info?["error"]?.ToString();
                var desc = $"Python 模块: {path} | 状态: {statusLabel}" + (!string.IsNullOrEmpty(error) ? $" | 错误: {error}" : "");

                var actionPanel = new StackPanel { Orientation = Avalonia.Layout.Orientation.Horizontal, Spacing = 6 };

                // 禁用按钮
                var toggleBtn = new Button
                {
                    Content = "🟢 已启用",
                    Background = Avalonia.Media.Brush.Parse("#163820"),
                    Foreground = BrushOk,
                    BorderBrush = BrushOk,
                    BorderThickness = new Thickness(1),
                    CornerRadius = new CornerRadius(6),
                    Padding = new Thickness(8, 4),
                    FontSize = 11
                };
                toggleBtn.Click += async (s, e) =>
                {
                    AppendLog($"[GUI 模组] 正在禁用服务端模组: {name} ...");
                    var (ok, msg) = await _apiClient.ToggleModAsync(name, "server", false);
                    AppendLog(ok ? $"[GUI 模组] ✅ {msg}" : $"[GUI 模组] ❌ {msg}");
                    _ = FetchAndRenderModsAsync();
                };
                actionPanel.Children.Add(toggleBtn);

                // 重载按钮
                var reloadBtn = new Button
                {
                    Content = "⚡ 重载",
                    Background = (Avalonia.Media.IBrush)this.FindResource("PrimaryBorderBrush")!,
                    Foreground = Avalonia.Media.Brushes.White,
                    CornerRadius = new CornerRadius(6),
                    Padding = new Thickness(10, 4),
                    FontSize = 11
                };
                reloadBtn.Click += async (s, e) =>
                {
                    AppendLog($"[GUI 模组 API] 正在热重载服务端模组: {name} ...");
                    var (ok, msg) = await _apiClient.ReloadModAsync(name, "server");
                    AppendLog(ok ? $"[GUI 模组 API] ✅ {msg}" : $"[GUI 模组 API] ❌ {msg}");
                    _ = FetchAndRenderModsAsync();
                };
                actionPanel.Children.Add(reloadBtn);

                var card = CreateSettingCard(name, desc, "\xE74C", actionPanel);
                ServerModsContainer.Children.Add(card);
            }
        }
        else
        {
            ServerModsContainer.Children.Add(new TextBlock { Text = "未检测到已挂载的服务端模组", Foreground = Avalonia.Media.Brushes.Gray, Margin = new Thickness(6) });
        }

        // 2. 渲染客户端活跃模组
        if (clientMods != null && clientMods.Count > 0)
        {
            foreach (var kv in clientMods)
            {
                var name = kv.Key;
                var info = kv.Value;
                var path = info?["path"]?.ToString() ?? "";
                var status = info?["status"]?.ToString() ?? "ready";
                var statusLabel = info?["statusLabel"]?.ToString() ?? "就绪";
                var error = info?["error"]?.ToString();
                var desc = $"WS 扩展模块: {path} | 状态: {statusLabel}" + (!string.IsNullOrEmpty(error) ? $" | 错误: {error}" : "");

                var actionPanel = new StackPanel { Orientation = Avalonia.Layout.Orientation.Horizontal, Spacing = 6 };

                var toggleBtn = new Button
                {
                    Content = "🟢 已启用",
                    Background = Avalonia.Media.Brush.Parse("#163820"),
                    Foreground = BrushOk,
                    BorderBrush = BrushOk,
                    BorderThickness = new Thickness(1),
                    CornerRadius = new CornerRadius(6),
                    Padding = new Thickness(8, 4),
                    FontSize = 11
                };
                toggleBtn.Click += async (s, e) =>
                {
                    AppendLog($"[GUI 模组] 正在禁用客户端模组: {name} ...");
                    var (ok, msg) = await _apiClient.ToggleModAsync(name, "client", false);
                    AppendLog(ok ? $"[GUI 模组] ✅ {msg}" : $"[GUI 模组] ❌ {msg}");
                    _ = FetchAndRenderModsAsync();
                };
                actionPanel.Children.Add(toggleBtn);

                var card = CreateSettingCard(name, desc, "\xE74C", actionPanel);
                ClientModsContainer.Children.Add(card);
            }
        }
        else
        {
            ClientModsContainer.Children.Add(new TextBlock { Text = "未检测到客户端模组", Foreground = Avalonia.Media.Brushes.Gray, Margin = new Thickness(6) });
        }

        // 3. 渲染已禁用的模组
        bool hasDisabled = (disabledServer != null && disabledServer.Count > 0) || (disabledClient != null && disabledClient.Count > 0);
        DisabledModsTitle.IsVisible = hasDisabled;
        DisabledModsContainer.IsVisible = hasDisabled;

        if (hasDisabled)
        {
            if (disabledServer != null)
            {
                foreach (var kv in disabledServer)
                {
                    var name = kv.Key;
                    var info = kv.Value;
                    var path = info?["path"]?.ToString() ?? "";
                    var desc = $"[服务端] Python 模块: {path} (已被禁用)";

                    var enableBtn = new Button
                    {
                        Content = "○ 重新启用",
                        Background = Avalonia.Media.Brush.Parse("#262930"),
                        Foreground = Avalonia.Media.Brushes.LightGray,
                        CornerRadius = new CornerRadius(6),
                        Padding = new Thickness(10, 4),
                        FontSize = 11
                    };
                    enableBtn.Click += async (s, e) =>
                    {
                        AppendLog($"[GUI 模组] 正在重新启用服务端模组: {name} ...");
                        var (ok, msg) = await _apiClient.ToggleModAsync(name, "server", true);
                        AppendLog(ok ? $"[GUI 模组] ✅ {msg}" : $"[GUI 模组] ❌ {msg}");
                        _ = FetchAndRenderModsAsync();
                    };
                    var card = CreateSettingCard(name, desc, "\xE74C", enableBtn);
                    DisabledModsContainer.Children.Add(card);
                }
            }

            if (disabledClient != null)
            {
                foreach (var kv in disabledClient)
                {
                    var name = kv.Key;
                    var info = kv.Value;
                    var path = info?["path"]?.ToString() ?? "";
                    var desc = $"[客户端] WS 模块: {path} (已被禁用)";

                    var enableBtn = new Button
                    {
                        Content = "○ 重新启用",
                        Background = Avalonia.Media.Brush.Parse("#262930"),
                        Foreground = Avalonia.Media.Brushes.LightGray,
                        CornerRadius = new CornerRadius(6),
                        Padding = new Thickness(10, 4),
                        FontSize = 11
                    };
                    enableBtn.Click += async (s, e) =>
                    {
                        AppendLog($"[GUI 模组] 正在重新启用客户端模组: {name} ...");
                        var (ok, msg) = await _apiClient.ToggleModAsync(name, "client", true);
                        AppendLog(ok ? $"[GUI 模组] ✅ {msg}" : $"[GUI 模组] ❌ {msg}");
                        _ = FetchAndRenderModsAsync();
                    };
                    var card = CreateSettingCard(name, desc, "\xE74C", enableBtn);
                    DisabledModsContainer.Children.Add(card);
                }
            }
        }
    }

    private async void ModsRefresh_Click(object? sender, RoutedEventArgs e)
    {
        await FetchAndRenderModsAsync();
    }

    private async void ModsReloadAll_Click(object? sender, RoutedEventArgs e)
    {
        if (string.IsNullOrEmpty(_apiClient.Token) || _currentUserRole != "admin")
        {
            var noPerm = "无权限: 重载全部模组属于管理员权限！请先登录管理员账号。";
            AppendLog($"[GUI 权限拦截] ❌ {noPerm}");
            ShowToast($"❌ {noPerm}", ToastType.Error);
            LoginUsernameBox.Text = "admin";
            LoginOverlay.IsVisible = true;
            return;
        }

        AppendLog("[GUI 模组 API] 正在发起全量模组热重载 (POST /api/mods/reload-all) ...");
        var (ok, msg) = await _apiClient.ReloadAllModsAsync();
        AppendLog(ok ? $"[GUI 模组 API] ✅ {msg}" : $"[GUI 模组 API] ❌ {msg}");
        await FetchAndRenderModsAsync();
    }

    private void ModsOpenFolder_Click(object? sender, RoutedEventArgs e)
    {
        var rootDir = _localCore.RootDirectory ?? AppContext.BaseDirectory;
        var dir = Directory.Exists(Path.Combine(rootDir, "mod"))
            ? Path.Combine(rootDir, "mod")
            : Path.Combine(rootDir, "mods");
        if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);
        try
        {
            Process.Start(new ProcessStartInfo { FileName = dir, UseShellExecute = true });
        }
        catch {}
    }

    // ==========================================
    // 2. 原生系统配置 API 交互 (GET/PUT /api/config)
    // ==========================================
    private async Task FetchAndRenderConfigAsync()
    {
        var rootDir = _localCore.RootDirectory ?? AppContext.BaseDirectory;
        var cfgJsonPath = Path.Combine(rootDir, "config", "config.json");
        if (!File.Exists(cfgJsonPath)) cfgJsonPath = Path.Combine(rootDir, "config.json");

        JsonNode? config = await _apiClient.GetConfigAsync();
        if (config == null && File.Exists(cfgJsonPath))
        {
            try
            {
                var localText = await File.ReadAllTextAsync(cfgJsonPath);
                config = JsonNode.Parse(localText);
            }
            catch {}
        }

        if (config != null)
        {
            _currentConfigNode = config["config"] ?? config;
            var wsCfg = _currentConfigNode?["wsConfig"] ?? _currentConfigNode?["ws"] ?? _currentConfigNode;
            var webCfg = _currentConfigNode?["webuiConfig"] ?? _currentConfigNode?["webui"] ?? _currentConfigNode;
            var qqCfg = _currentConfigNode?["features"]?["qq"] ?? _currentConfigNode?["onebot"] ?? _currentConfigNode?["qq"];
            var dogCfg = _currentConfigNode?["watchdog"] ?? _currentConfigNode;

            CfgServerNameBox.Text = wsCfg?["name"]?.ToString() ?? "EnderBridge";
            CfgWsPortBox.Text = wsCfg?["port"]?.ToString() ?? "8800";
            CfgWebPortBox.Text = webCfg?["port"]?.ToString() ?? "18888";
            
            var qqHost = qqCfg?["host"]?.ToString() ?? "127.0.0.1";
            var qqPort = qqCfg?["port"]?.ToString() ?? "3001";
            CfgOneBotUrlBox.Text = qqCfg?["ws_url"]?.ToString() ?? $"ws://{qqHost}:{qqPort}";
            CfgOneBotGroupBox.Text = qqCfg?["groupId"]?.ToString() ?? qqCfg?["group_id"]?.ToString() ?? "0";
            
            CfgWatchdogToggle.IsChecked = dogCfg?["auto_restart"]?.GetValue<bool>() ?? true;
            CfgLocalOnlyToggle.IsChecked = webCfg?["localOnly"]?.GetValue<bool>() ?? false;
        }
    }

    private async void ConfigSave_Click(object? sender, RoutedEventArgs e)
    {
        // 权限校验：未登录或非管理员身份，严禁修改配置！
        if (string.IsNullOrEmpty(_apiClient.Token) || _currentUserRole != "admin")
        {
            var noPerm = "无权限: 修改系统配置属于高危管理操作，必须以管理员(admin)身份登录！请先登录管理员账号。";
            AppendLog($"[GUI 权限拦截] ❌ {noPerm}");
            ShowToast($"❌ {noPerm}", ToastType.Error);
            LoginUsernameBox.Text = "admin";
            LoginOverlay.IsVisible = true;
            return;
        }

        var rootDir = _localCore.RootDirectory ?? AppContext.BaseDirectory;
        var configDir = Path.Combine(rootDir, "config");
        if (!Directory.Exists(configDir)) Directory.CreateDirectory(configDir);
        var cfgPath = Path.Combine(configDir, "config.json");

        JsonObject targetConfig;
        if (File.Exists(cfgPath))
        {
            try
            {
                var existingText = await File.ReadAllTextAsync(cfgPath);
                var node = JsonNode.Parse(existingText);
                targetConfig = node as JsonObject ?? new JsonObject();
            }
            catch
            {
                targetConfig = (_currentConfigNode as JsonObject)?.DeepClone() as JsonObject ?? new JsonObject();
            }
        }
        else
        {
            targetConfig = (_currentConfigNode as JsonObject)?.DeepClone() as JsonObject ?? new JsonObject();
        }

        // 更新 wsConfig
        var ws = targetConfig["wsConfig"] as JsonObject ?? new JsonObject();
        ws["name"] = CfgServerNameBox.Text ?? "EnderBridge";
        if (int.TryParse(CfgWsPortBox.Text, out var wsP)) ws["port"] = wsP;
        targetConfig["wsConfig"] = ws;

        // 更新 webuiConfig
        var web = targetConfig["webuiConfig"] as JsonObject ?? new JsonObject();
        if (int.TryParse(CfgWebPortBox.Text, out var webP)) web["port"] = webP;
        web["localOnly"] = CfgLocalOnlyToggle.IsChecked ?? false;
        targetConfig["webuiConfig"] = web;

        // 更新 features.qq
        if (targetConfig["features"] is not JsonObject features)
        {
            features = new JsonObject();
            targetConfig["features"] = features;
        }
        var qq = features["qq"] as JsonObject ?? new JsonObject();
        var rawUrl = CfgOneBotUrlBox.Text?.Trim() ?? "";
        if (Uri.TryCreate(rawUrl, UriKind.Absolute, out var uri))
        {
            qq["host"] = uri.Host;
            if (uri.Port > 0) qq["port"] = uri.Port;
        }
        else if (rawUrl.Contains(':'))
        {
            var parts = rawUrl.Replace("ws://", "").Replace("http://", "").Split(':');
            qq["host"] = parts[0];
            if (int.TryParse(parts[1], out var p)) qq["port"] = p;
        }
        if (long.TryParse(CfgOneBotGroupBox.Text, out var grp)) qq["groupId"] = grp;
        qq["enabled"] = true;
        features["qq"] = qq;

        // 更新 watchdog
        var dog = targetConfig["watchdog"] as JsonObject ?? new JsonObject();
        dog["auto_restart"] = CfgWatchdogToggle.IsChecked ?? true;
        targetConfig["watchdog"] = dog;

        // 明确复位首次运行状态
        targetConfig["is_first_run"] = false;

        // 同步顶层兼容字段
        targetConfig["name"] = ws["name"]?.ToString();
        targetConfig["port"] = ws["port"]?.GetValue<int>() ?? 8800;
        targetConfig["webui"] = new JsonObject
        {
            ["port"] = web["port"]?.GetValue<int>() ?? 18888,
            ["localOnly"] = web["localOnly"]?.GetValue<bool>() ?? false
        };

        // 1. 如果后端服务正在运行，强制通过 API 热更新校验（由后端验证 token 和权限后落盘并审计）
        if (_serverProcess != null && !_serverProcess.HasExited)
        {
            try
            {
                AppendLog("[GUI 配置 API] 正在向后端提交配置热更新 (PUT /api/config) ...");
                var (ok, msg) = await _apiClient.SaveConfigAsync(targetConfig);
                if (ok)
                {
                    _currentConfigNode = targetConfig;
                    AppendLog($"[GUI 配置 API] ✅ 后端运行时已成功更新配置并热重载: {msg}");
                    ShowToast("✅ 配置已保存(部分设置需重启生效)", ToastType.Success);
                }
                else
                {
                    AppendLog($"[GUI 配置 API] ❌ 后端拒绝保存配置: {msg}");
                    ShowToast($"❌ 保存配置失败: {msg}", ToastType.Error);
                }
            }
            catch (Exception ex)
            {
                AppendLog($"[GUI 配置 API] ❌ 请求异常: {ex.Message}");
                ShowToast($"❌ 保存配置异常: {ex.Message}", ToastType.Error);
            }
            return;
        }

        // 2. 服务端未运行时的离线写入（已严格验证管理员身份）
        try
        {
            var jsonStr = targetConfig.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
            var tempFile = Path.Combine(configDir, $"config.json.tmp_{Guid.NewGuid():N}");
            await File.WriteAllTextAsync(tempFile, jsonStr);
            File.Move(tempFile, cfgPath, overwrite: true);
            _currentConfigNode = targetConfig;
            AppendLog("[GUI 配置] ✅ 本地 config/config.json 已更新保存！");
            ShowToast("✅ 本地配置已保存(下次启动生效)", ToastType.Success);
        }
        catch (Exception ex)
        {
            AppendLog($"[GUI 配置] ❌ 写入本地配置失败: {ex.Message}");
            ShowToast($"❌ 写入本地配置失败: {ex.Message}", ToastType.Error);
        }
    }

    private async void ConfigReload_Click(object? sender, RoutedEventArgs e)
    {
        await FetchAndRenderConfigAsync();
        AppendLog("[GUI 配置 API] 配置已重新加载。");
    }

    // ==========================================
    // 3. 原生创意工坊 API 交互 (/api/studio/assets)
    // ==========================================
    private async Task FetchAndRenderStudioAsync()
    {
        StudioBlueprintsContainer.Children.Clear();
        StudioMidiContainer.Children.Clear();
        StudioImagesContainer.Children.Clear();

        StudioBlueprintsContainer.Children.Add(new TextBlock { Text = "正在从后端 API (/api/studio/assets) 检索资产...", Foreground = BrushWarn, Margin = new Thickness(6) });

        var data = await _apiClient.GetStudioAssetsAsync();
        StudioBlueprintsContainer.Children.Clear();

        var rootDir = _localCore.RootDirectory ?? AppContext.BaseDirectory;
        var ezmaticDir = Path.Combine(rootDir, "resources", "ezmatic");
        var structuresDir = Path.Combine(rootDir, "structures");
        var midiDir = Path.Combine(rootDir, "resources", "midi");
        var picturesDir = Path.Combine(rootDir, "resources", "pictures");

        int bpCount = 0;
        int midiCount = 0;
        int imgCount = 0;

        // 1. 如果 API 返回了资产字典或列表
        if (data != null && data["ok"]?.GetValue<bool>() == true)
        {
            var assetsNode = data["assets"];
            if (assetsNode is JsonObject assetsObj)
            {
                // A. 蓝图结构 (ezmatic)
                if (assetsObj["ezmatic"] is JsonArray ezArr)
                {
                    foreach (var item in ezArr)
                    {
                        bpCount++;
                        var name = item?["name"]?.ToString() ?? "";
                        var sz = item?["size_formatted"]?.ToString() ?? "";
                        var mtime = item?["mtime"]?.ToString() ?? "";
                        var meta = item?["metadata"]?.AsObject();
                        string dims = "";
                        if (meta != null && meta["dimensions"] is JsonObject d)
                        {
                            dims = $" | 尺寸: {d["x"]}×{d["y"]}×{d["z"]}";
                        }
                        var desc = $"体素蓝图 | 大小: {sz}{dims} | 修改: {mtime}";

                        var previewBtn = new Button
                        {
                            Content = "👓 3D 预览",
                            Background = (Avalonia.Media.IBrush)this.FindResource("AccentBackgroundBrush")!,
                            Foreground = Avalonia.Media.Brushes.White,
                            CornerRadius = new CornerRadius(6),
                            Padding = new Thickness(10, 4),
                            FontSize = 11
                        };
                        previewBtn.Click += (s, e) =>
                        {
                            OpenBlueprintPreview(name);
                        };

                        var card = CreateSettingCard(name, desc, "\xE790", previewBtn);
                        StudioBlueprintsContainer.Children.Add(card);
                    }
                }

                // B. 音乐曲库 (midi)
                if (assetsObj["midi"] is JsonArray midiArr)
                {
                    foreach (var item in midiArr)
                    {
                        midiCount++;
                        var name = item?["name"]?.ToString() ?? "";
                        var sz = item?["size_formatted"]?.ToString() ?? "";
                        var mtime = item?["mtime"]?.ToString() ?? "";
                        var desc = $"MIDI 音频曲目 | 大小: {sz} | 修改: {mtime}";

                        var copyBtn = new Button
                        {
                            Content = "📋 复制曲名",
                            Background = (Avalonia.Media.IBrush)this.FindResource("PrimaryBorderBrush")!,
                            Foreground = Avalonia.Media.Brushes.White,
                            CornerRadius = new CornerRadius(6),
                            Padding = new Thickness(10, 4),
                            FontSize = 11
                        };
                        copyBtn.Click += async (s, e) =>
                        {
                            try
                            {
                                var topLevel = TopLevel.GetTopLevel(this);
                                if (topLevel?.Clipboard != null)
                                {
                                    await topLevel.Clipboard.SetTextAsync(name);
                                    AppendLog($"[GUI 创意工坊] 已复制曲名到剪贴板: {name}");
                                }
                            }
                            catch {}
                        };

                        var card = CreateSettingCard(name, desc, "\xEC4F", copyBtn);
                        StudioMidiContainer.Children.Add(card);
                    }
                }

                // C. 像素画图像 (image)
                if (assetsObj["image"] is JsonArray imgArr)
                {
                    foreach (var item in imgArr)
                    {
                        imgCount++;
                        var name = item?["name"]?.ToString() ?? "";
                        var sz = item?["size_formatted"]?.ToString() ?? "";
                        var mtime = item?["mtime"]?.ToString() ?? "";
                        var meta = item?["metadata"]?.AsObject();
                        string dims = "";
                        if (meta != null && meta["width"] != null && meta["height"] != null)
                        {
                            dims = $" | 分辨率: {meta["width"]}×{meta["height"]}";
                        }
                        var desc = $"像素画图像 | 大小: {sz}{dims} | 修改: {mtime}";

                        var btnPanel = new StackPanel { Orientation = Avalonia.Layout.Orientation.Horizontal, Spacing = 6 };
                        var viewBtn = new Button
                        {
                            Content = "🖼️ 查看",
                            Background = (Avalonia.Media.IBrush)this.FindResource("PrimaryBorderBrush")!,
                            Foreground = Avalonia.Media.Brushes.White,
                            CornerRadius = new CornerRadius(6),
                            Padding = new Thickness(10, 4),
                            FontSize = 11
                        };
                        viewBtn.Click += (s, e) =>
                        {
                            var imgPath = Path.Combine(picturesDir, name);
                            if (File.Exists(imgPath))
                            {
                                try { Process.Start(new ProcessStartInfo { FileName = imgPath, UseShellExecute = true }); } catch {}
                            }
                        };
                        var simBtn = new Button
                        {
                            Content = "🎨 像素画工坊",
                            Background = (Avalonia.Media.IBrush)this.FindResource("PrimaryBorderBrush")!,
                            Foreground = Avalonia.Media.Brushes.White,
                            CornerRadius = new CornerRadius(6),
                            Padding = new Thickness(10, 4),
                            FontSize = 11
                        };
                        simBtn.Click += (s, e) =>
                        {
                            try { Process.Start(new ProcessStartInfo { FileName = $"{_backendUrl}/studio?tab=image&gui=1", UseShellExecute = true }); } catch {}
                        };
                        btnPanel.Children.Add(viewBtn);
                        btnPanel.Children.Add(simBtn);

                        var card = CreateSettingCard(name, desc, "\xEB9F", btnPanel);
                        StudioImagesContainer.Children.Add(card);
                    }
                }
            }
        }

        // 2. 离线本地目录降级扫描 (服务端未启动或 API 无返回时)
        if (bpCount == 0)
        {
            var bpFiles = new List<string>();
            if (Directory.Exists(ezmaticDir)) bpFiles.AddRange(Directory.GetFiles(ezmaticDir, "*.*").Where(f => f.EndsWith(".litematic") || f.EndsWith(".schematic") || f.EndsWith(".mcstructure")));
            if (Directory.Exists(structuresDir)) bpFiles.AddRange(Directory.GetFiles(structuresDir, "*.*").Where(f => f.EndsWith(".mcstructure") || f.EndsWith(".json")));

            foreach (var f in bpFiles)
            {
                bpCount++;
                var fi = new FileInfo(f);
                var previewBtn = new Button
                {
                    Content = "👓 3D 预览",
                    Background = (Avalonia.Media.IBrush)this.FindResource("AccentBackgroundBrush")!,
                    Foreground = Avalonia.Media.Brushes.White,
                    CornerRadius = new CornerRadius(6),
                    Padding = new Thickness(10, 4),
                    FontSize = 11
                };
                previewBtn.Click += (s, e) => OpenBlueprintPreview(fi.Name);

                var card = CreateSettingCard(fi.Name, $"本地蓝图 | {fi.Length / 1024.0:F1} KB | {fi.LastWriteTime:yyyy-MM-dd}", "\xE790", previewBtn);
                StudioBlueprintsContainer.Children.Add(card);
            }
        }

        if (midiCount == 0 && Directory.Exists(midiDir))
        {
            var files = Directory.GetFiles(midiDir, "*.mid").Concat(Directory.GetFiles(midiDir, "*.midi")).ToList();
            foreach (var f in files)
            {
                midiCount++;
                var fi = new FileInfo(f);
                var card = CreateSettingCard(fi.Name, $"本地 MIDI 音乐 | {fi.Length / 1024.0:F1} KB | {fi.LastWriteTime:yyyy-MM-dd}", "\xEC4F");
                StudioMidiContainer.Children.Add(card);
            }
        }

        if (imgCount == 0 && Directory.Exists(picturesDir))
        {
            var files = Directory.GetFiles(picturesDir, "*.*").Where(f => f.EndsWith(".png") || f.EndsWith(".jpg") || f.EndsWith(".jpeg") || f.EndsWith(".webp")).ToList();
            foreach (var f in files)
            {
                imgCount++;
                var fi = new FileInfo(f);
                var viewBtn = new Button
                {
                    Content = "🖼️ 查看",
                    Background = (Avalonia.Media.IBrush)this.FindResource("PrimaryBorderBrush")!,
                    Foreground = Avalonia.Media.Brushes.White,
                    CornerRadius = new CornerRadius(6),
                    Padding = new Thickness(10, 4),
                    FontSize = 11
                };
                var localPath = f;
                viewBtn.Click += (s, e) =>
                {
                    if (File.Exists(localPath))
                    {
                        try { Process.Start(new ProcessStartInfo { FileName = localPath, UseShellExecute = true }); } catch {}
                    }
                };
                var card = CreateSettingCard(fi.Name, $"本地图像资产 | {fi.Length / 1024.0:F1} KB | {fi.LastWriteTime:yyyy-MM-dd}", "\xEB9F", viewBtn);
                StudioImagesContainer.Children.Add(card);
            }
        }

        // 3. 空资产提示
        if (bpCount == 0)
        {
            StudioBlueprintsContainer.Children.Add(new TextBlock { Text = "当前蓝图库为空。您可以将 .litematic / .schematic / .mcstructure 放入 resources/ezmatic 目录。", Foreground = Avalonia.Media.Brushes.Gray, Margin = new Thickness(6) });
        }
        if (midiCount == 0)
        {
            StudioMidiContainer.Children.Add(new TextBlock { Text = "当前 MIDI 曲库为空。您可以将 .mid / .midi 音乐放入 resources/midi 目录。", Foreground = Avalonia.Media.Brushes.Gray, Margin = new Thickness(6) });
        }
        if (imgCount == 0)
        {
            StudioImagesContainer.Children.Add(new TextBlock { Text = "当前像素画图库为空。您可以将 .png / .jpg 图像放入 resources/pictures 目录。", Foreground = Avalonia.Media.Brushes.Gray, Margin = new Thickness(6) });
        }

        StudioSummaryText.Text = $"创意工坊资产库就绪：建筑蓝图 {bpCount} 个，MIDI 音轨 {midiCount} 首，图像素材 {imgCount} 张";
    }

    private async void OpenBlueprintPreview(string filename)
    {
        AppendLog($"[GUI 创意工坊] 正在加载体素蓝图 3D 交互预览: {filename} ...");
        try
        {
            _browserReturnTag = "Studio";
            string targetUrl;

            if (_serverProcess != null && !_serverProcess.HasExited)
            {
                targetUrl = $"{_backendUrl}/api/studio/blueprint-html?category=ezmatic&file={Uri.EscapeDataString(filename)}&gui=1";
                if (!string.IsNullOrEmpty(_apiClient.Token))
                {
                    targetUrl += $"&token={Uri.EscapeDataString(_apiClient.Token)}";
                }
            }
            else
            {
                var rootDir = _localCore.RootDirectory ?? AppContext.BaseDirectory;
                var logsDir = Path.Combine(rootDir, "logs");
                if (!Directory.Exists(logsDir)) Directory.CreateDirectory(logsDir);
                var outHtml = Path.Combine(logsDir, $"blueprint_preview_{Path.GetFileNameWithoutExtension(filename)}.html");

                var psi = new ProcessStartInfo
                {
                    FileName = "python",
                    Arguments = $"main.py preview \"{filename}\" --export \"{outHtml}\" --no-browser",
                    WorkingDirectory = rootDir,
                    UseShellExecute = false,
                    CreateNoWindow = true
                };

                using var proc = Process.Start(psi);
                if (proc != null)
                {
                    await proc.WaitForExitAsync();
                }

                if (File.Exists(outHtml))
                {
                    targetUrl = new Uri(outHtml).AbsoluteUri;
                }
                else
                {
                    targetUrl = $"{_backendUrl}/api/studio/blueprint-html?category=ezmatic&file={Uri.EscapeDataString(filename)}&gui=1";
                    EnsureServerRunningAndShowUrl(targetUrl);
                    return;
                }
            }

            BrowserUrlTextBox.Text = targetUrl;
            NavigateWebView(targetUrl);
            SelectTab("WebUI");
            PageTitleText.Text = $"👓 3D 蓝图预览 - {filename}";
        }
        catch (Exception ex)
        {
            AppendLog($"[GUI 创意工坊] ❌ 3D 预览启动失败: {ex.Message}");
        }
    }

    private async void StudioRefresh_Click(object? sender, RoutedEventArgs e)
    {
        await FetchAndRenderStudioAsync();
    }

    private void StudioOpenFolder_Click(object? sender, RoutedEventArgs e)
    {
        var rootDir = _localCore.RootDirectory ?? AppContext.BaseDirectory;
        var dir = Path.Combine(rootDir, "resources");
        if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);
        try { Process.Start(new ProcessStartInfo { FileName = dir, UseShellExecute = true }); } catch {}
    }

    private void StudioOpenBlueprints_Click(object? sender, RoutedEventArgs e)
    {
        var rootDir = _localCore.RootDirectory ?? AppContext.BaseDirectory;
        var dir = Path.Combine(rootDir, "resources", "ezmatic");
        if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);
        try { Process.Start(new ProcessStartInfo { FileName = dir, UseShellExecute = true }); } catch {}
    }

    private void StudioOpenMidi_Click(object? sender, RoutedEventArgs e)
    {
        var rootDir = _localCore.RootDirectory ?? AppContext.BaseDirectory;
        var dir = Path.Combine(rootDir, "resources", "midi");
        if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);
        try { Process.Start(new ProcessStartInfo { FileName = dir, UseShellExecute = true }); } catch {}
    }

    // ==========================================
    // 4. 原生备份与权限 API 交互 (/api/backups, /api/permissions)
    // ==========================================
    private async Task FetchAndRenderBackupsAndPermissionsAsync()
    {
        BackupsListContainer.Children.Clear();
        PermissionsListContainer.Children.Clear();

        BackupsListContainer.Children.Add(new TextBlock { Text = "正在从后端 API (/api/backups) 检索快照记录...", Foreground = BrushWarn, Margin = new Thickness(6) });

        var data = await _apiClient.GetBackupsAsync();
        BackupsListContainer.Children.Clear();

        var rootDir = _localCore.RootDirectory ?? AppContext.BaseDirectory;
        var backupsDir = Path.Combine(rootDir, "backups");
        int count = 0;

        if (data != null && data["backups"] is JsonArray arr && arr.Count > 0)
        {
            foreach (var b in arr)
            {
                count++;
                var fn = b?["filename"]?.ToString() ?? b?["path"]?.ToString() ?? "backup.zip";
                var sz = b?["size"]?.ToString() ?? "";
                var desc = b?["description"]?.ToString() ?? "系统完整快照";
                var stamp = b?["stamp"]?.ToString() ?? b?["mtime"]?.ToString() ?? "";

                var card = CreateSettingCard(fn, $"备注: {desc} | 大小: {sz} 字节 | 时间: {stamp}", "\xE77C");
                BackupsListContainer.Children.Add(card);
            }
        }
        else if (Directory.Exists(backupsDir))
        {
            var files = Directory.GetFiles(backupsDir, "*.zip");
            foreach (var f in files)
            {
                count++;
                var fi = new FileInfo(f);
                var card = CreateSettingCard(fi.Name, $"本地快照 | {fi.Length / 1024.0 / 1024.0:F2} MB | 创建时间: {fi.LastWriteTime:yyyy-MM-dd HH:mm}", "\xE77C");
                BackupsListContainer.Children.Add(card);
            }
        }

        if (count == 0)
        {
            BackupsListContainer.Children.Add(new TextBlock { Text = "当前暂无快照备份。点击 [💾 立即创建快照] 可立即打包当前服务器状态。", Foreground = Avalonia.Media.Brushes.Gray, Margin = new Thickness(6) });
        }

        BackupSummaryText.Text = $"快照归档正常：已有备份 {count} 份，支持随时还原";

        // 渲染权限矩阵
        var roles = new[]
        {
            ("Owner (服主拥有者)", "最高控制权，拥有全部命令、配置及模组管控权限", "\xE7EF", BrushOk),
            ("OP (管理运维)", "拥有游戏内核心管理权限、踢人/封禁与热重载权限", "\xE724", BrushWarn),
            ("User (普通玩家)", "允许基岩版互联、聊天互通、查询游戏内公有信息", "\xE77B", Avalonia.Media.Brushes.White),
            ("Blocker (受限黑名单)", "禁止连接中继、禁止触发任何机器人指令", "\xE711", BrushDanger)
        };

        foreach (var (roleTitle, roleDesc, glyph, color) in roles)
        {
            var badge = new TextBlock { Text = "● 生效中", Foreground = color, VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center };
            var card = CreateSettingCard(roleTitle, roleDesc, glyph, badge);
            PermissionsListContainer.Children.Add(card);
        }
    }

    private async void BackupCreate_Click(object? sender, RoutedEventArgs e)
    {
        if (string.IsNullOrEmpty(_apiClient.Token) || _currentUserRole != "admin")
        {
            var noPerm = "无权限: 创建快照属于管理员权限！请先登录管理员账号。";
            AppendLog($"[GUI 权限拦截] ❌ {noPerm}");
            ShowToast($"❌ {noPerm}", ToastType.Error);
            LoginUsernameBox.Text = "admin";
            LoginOverlay.IsVisible = true;
            return;
        }

        AppendLog("[GUI 备份 API] 正在创建系统完整快照 (POST /api/backups) ...");
        var (ok, msg) = await _apiClient.CreateBackupAsync($"GUI 手动快照 ({DateTime.Now:yyyyMMdd_HHmmss})");
        AppendLog(ok ? $"[GUI 备份 API] ✅ {msg}" : $"[GUI 备份 API] 提示: {msg}");
        ShowToast(ok ? $"✅ {msg}" : $"❌ {msg}", ok ? ToastType.Success : ToastType.Error);
        await FetchAndRenderBackupsAndPermissionsAsync();
    }

    private async void BackupRefresh_Click(object? sender, RoutedEventArgs e)
    {
        await FetchAndRenderBackupsAndPermissionsAsync();
    }

    private void BackupOpenFolder_Click(object? sender, RoutedEventArgs e)
    {
        var rootDir = _localCore.RootDirectory ?? AppContext.BaseDirectory;
        var dir = Path.Combine(rootDir, "backups");
        if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);
        try
        {
            Process.Start(new ProcessStartInfo { FileName = dir, UseShellExecute = true });
        }
        catch {}
    }

    private static OnePointUI.Avalonia.Styling.Controls.OnePointControls.SettingCard CreateSettingCard(string header, string desc, string glyph, Control? rightContent = null)
    {
        var card = new OnePointUI.Avalonia.Styling.Controls.OnePointControls.SettingCard
        {
            Header = header,
            Description = desc,
            Glyph = glyph,
            Margin = new Thickness(0, 2)
        };
        if (rightContent != null)
        {
            card.Content = rightContent;
        }
        return card;
    }

    private string FindPythonExecutable(string rootDir)
    {
        string[] candidates = OperatingSystem.IsWindows()
            ? [
                Path.Combine(rootDir, ".venv", "Scripts", "python.exe"),
                Path.Combine(rootDir, "venv", "Scripts", "python.exe"),
                Path.Combine(rootDir, "env", "Scripts", "python.exe"),
                Path.Combine(rootDir, ".env", "Scripts", "python.exe"),
              ]
            : [
                Path.Combine(rootDir, ".venv", "bin", "python"),
                Path.Combine(rootDir, "venv", "bin", "python"),
                Path.Combine(rootDir, "env", "bin", "python"),
                Path.Combine(rootDir, ".env", "bin", "python"),
              ];

        foreach (var c in candidates)
        {
            if (File.Exists(c))
            {
                AppendLog($"[GUI 环境] 自动锁定虚拟环境 Python: {c}");
                return c;
            }
        }

        return OperatingSystem.IsWindows() ? "python" : "python3";
    }

    private void StartServer_Click(object? sender, RoutedEventArgs e)
    {
        if (_serverProcess != null && !_serverProcess.HasExited)
        {
            AppendLog("[GUI] 服务器已经在运行中。");
            return;
        }

        RefreshLocalCoreStatus();
        if (!_localCore.Exists)
        {
            AppendLog("[GUI 错误] 未能找到 main.py，请确认将 EnderBridge 程序放在项目同级目录下！");
            AppendLog("[GUI 引导] 正在为您自动拉取并安装最新版 EnderBridge...");
            AutoDownloadLatest_Click(sender, e);
            return;
        }

        // 启动前先确保旧残留进程与目标端口释放
        int wsP = 8800;
        int webP = 18888;
        if (CfgWsPortBox != null && int.TryParse(CfgWsPortBox.Text, out var parsedWs)) wsP = parsedWs;
        if (CfgWebPortBox != null && int.TryParse(CfgWebPortBox.Text, out var parsedWeb)) webP = parsedWeb;
        CleanupLingeringServerProcesses(wsP, webP);

        try
        {
            var mainPyPath = _localCore.MainPyPath!;
            var rootDir = _localCore.RootDirectory!;
            AppendLog($"[GUI] 发现主入口: {mainPyPath}");
            AppendLog($"[GUI] 启动工作目录: {rootDir}");

            var pythonExe = FindPythonExecutable(rootDir);
            var psi = new ProcessStartInfo
            {
                FileName = pythonExe,
                Arguments = "main.py --no-supervisor",
                WorkingDirectory = rootDir,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                RedirectStandardInput = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
                UseShellExecute = false,
                CreateNoWindow = true
            };

            // 如果使用虚拟环境，注入 PATH 和 VIRTUAL_ENV 环境变量确保子进程完全隔离
            var venvScripts = Path.GetDirectoryName(pythonExe);
            if (!string.IsNullOrEmpty(venvScripts) && Directory.Exists(venvScripts) && pythonExe.Contains("venv", StringComparison.OrdinalIgnoreCase))
            {
                var existingPath = Environment.GetEnvironmentVariable("PATH") ?? "";
                psi.EnvironmentVariables["PATH"] = venvScripts + Path.PathSeparator + existingPath;
                var venvRoot = Path.GetDirectoryName(venvScripts);
                if (!string.IsNullOrEmpty(venvRoot))
                {
                    psi.EnvironmentVariables["VIRTUAL_ENV"] = venvRoot;
                }
            }

            // 禁用 supervisor 守护(由 GUI 进程树接管), 禁用 ANSI 颜色转义与控制码
            psi.EnvironmentVariables["EB_NO_SUPERVISOR"] = "1";
            psi.EnvironmentVariables["NO_COLOR"] = "1";
            psi.EnvironmentVariables["EB_GUI"] = "1";
            psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";

            _serverProcess = new Process { StartInfo = psi };
            _serverProcess.OutputDataReceived += (s, args) =>
            {
                if (args.Data != null)
                {
                    Dispatcher.UIThread.Post(() => AppendLog(args.Data));
                }
            };
            _serverProcess.ErrorDataReceived += (s, args) =>
            {
                if (args.Data != null)
                {
                    Dispatcher.UIThread.Post(() => AppendLog("[STDERR] " + args.Data));
                }
            };

            _serverProcess.Start();
            _serverProcess.BeginOutputReadLine();
            _serverProcess.BeginErrorReadLine();

            // 绑定到 Windows Job Object: 当父进程关闭/崩溃/强杀时，操作系统自动清理子进程
            JobObjectManager.AttachProcess(_serverProcess);

            StatusValueText.Text = "● 运行中";
            StatusValueText.Foreground = BrushOk;
            UptimeText.Text = $"PID: {_serverProcess.Id} (守护中)";
            ConsolePidText.Text = $"● 运行中 (PID: {_serverProcess.Id})";
            ConsolePidText.Foreground = BrushOk;
            MainServerIconText.Text = "⏹";
            MainServerStatusText.Text = $"停止 ({_serverProcess.Id})";
            BottomStatusText.Text = $"● 运行中 (PID: {_serverProcess.Id})";
            BottomStatusText.Foreground = BrushOk;
            AppendLog($"[GUI] 成功拉起 EnderBridge 核心服务 (PID: {_serverProcess.Id})");
        }
        catch (Exception ex)
        {
            AppendLog($"[GUI 启动失败] {ex.Message}");
        }
    }

    public void KillServer()
    {
        if (_serverProcess != null)
        {
            try
            {
                if (!_serverProcess.HasExited)
                {
                    try
                    {
                        _serverProcess.StandardInput.WriteLine("stop");
                        _serverProcess.StandardInput.Flush();
                    }
                    catch {}

                    if (!_serverProcess.WaitForExit(1500))
                    {
                        _serverProcess.Kill(entireProcessTree: true);
                        _serverProcess.WaitForExit(1000);
                    }
                }
            }
            catch {}
            finally
            {
                _serverProcess = null;
            }
        }

        // 端口安全网兜底清理
        int wsP = 8800;
        int webP = 18888;
        if (CfgWsPortBox != null && int.TryParse(CfgWsPortBox.Text, out var parsedWs)) wsP = parsedWs;
        if (CfgWebPortBox != null && int.TryParse(CfgWebPortBox.Text, out var parsedWeb)) webP = parsedWeb;
        CleanupLingeringServerProcesses(wsP, webP);
    }

    private void CleanupLingeringServerProcesses(int wsPort, int webPort)
    {
        if (!OperatingSystem.IsWindows()) return;
        try
        {
            var ports = new[] { wsPort, webPort };
            var currentPid = Process.GetCurrentProcess().Id;
            var pidsToKill = new HashSet<int>();

            var psi = new ProcessStartInfo
            {
                FileName = "cmd.exe",
                Arguments = "/c netstat -ano -p tcp",
                CreateNoWindow = true,
                UseShellExecute = false,
                RedirectStandardOutput = true
            };
            using var proc = Process.Start(psi);
            if (proc != null)
            {
                var output = proc.StandardOutput.ReadToEnd();
                proc.WaitForExit(1000);

                var lines = output.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
                foreach (var line in lines)
                {
                    if (!line.Contains("LISTENING", StringComparison.OrdinalIgnoreCase)) continue;
                    foreach (var port in ports)
                    {
                        if (port > 0 && line.Contains($":{port} "))
                        {
                            var parts = line.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
                            if (parts.Length >= 5 && int.TryParse(parts[^1], out var pid))
                            {
                                if (pid > 0 && pid != currentPid && pid != 4)
                                {
                                    pidsToKill.Add(pid);
                                }
                            }
                        }
                    }
                }
            }

            foreach (var pid in pidsToKill)
            {
                try
                {
                    var target = Process.GetProcessById(pid);
                    var pName = target.ProcessName.ToLowerInvariant();
                    if (pName.Contains("python") || pName.Contains("main"))
                    {
                        AppendLog($"[GUI 端口清理] 释放被残留 Python 进程占用的端口 (PID: {pid})...");
                        target.Kill(entireProcessTree: true);
                        target.WaitForExit(1000);
                    }
                }
                catch {}
            }
        }
        catch {}
    }

    private void StopServer_Click(object? sender, RoutedEventArgs e)
    {
        if (_serverProcess == null || _serverProcess.HasExited)
        {
            AppendLog("[GUI] 服务未在运行。");
            return;
        }

        try
        {
            AppendLog("[GUI] 正在发送安全停止指令...");
            KillServer();
            StatusValueText.Text = "○ 已停止";
            StatusValueText.Foreground = BrushDanger;
            UptimeText.Text = "服务器已关闭";
            ConsolePidText.Text = "○ 服务已停止";
            ConsolePidText.Foreground = BrushDanger;
            MainServerIconText.Text = "▶";
            MainServerStatusText.Text = "启动服务端";
            BottomStatusText.Text = "○ 准备就绪";
            BottomStatusText.Foreground = BrushWarn;
            AppendLog("[GUI] 服务器已停止。");
        }
        catch (Exception ex)
        {
            AppendLog($"[GUI 停止失败] {ex.Message}");
        }
    }

    private async Task CheckHealthAsync()
    {
        try
        {
            var res = await _http.GetStringAsync($"{_backendUrl.TrimEnd('/')}/api/health");
            using var doc = JsonDocument.Parse(res);
            var root = doc.RootElement;
            if (root.TryGetProperty("ok", out var okProp) && okProp.GetBoolean())
            {
                ConnectionStatusText.Text = "在线服务连接正常";
                StatusValueText.Text = "● 正常运行";
                StatusValueText.Foreground = BrushOk;

                if (root.TryGetProperty("loop_latency_ms", out var latProp))
                {
                    WatchdogLatencyText.Text = $"{latProp.GetDouble():F1} ms";
                }

                if (root.TryGetProperty("version", out var vProp) && vProp.GetString() is string sVer && !string.IsNullOrWhiteSpace(sVer))
                {
                    BottomVerText.Text = $"EnderBridge {sVer}";
                }
                else if (_localCore.Exists && !string.IsNullOrWhiteSpace(_localCore.Version))
                {
                    BottomVerText.Text = $"EnderBridge {_localCore.Version}";
                }
            }
        }
        catch
        {
            if (_serverProcess == null || _serverProcess.HasExited)
            {
                ConnectionStatusText.Text = "本地未启动 (点击启动拉起)";
                StatusValueText.Text = "○ 空闲等待";
                StatusValueText.Foreground = BrushWarn;
            }
        }
    }

    private void ExecuteCommand(string cmd)
    {
        AppendLog($"> {cmd}");
        if (_serverProcess != null && !_serverProcess.HasExited)
        {
            try
            {
                _serverProcess.StandardInput.WriteLine(cmd);
                _serverProcess.StandardInput.Flush();
            }
            catch {}
        }

        if (cmd.Equals("stop", StringComparison.OrdinalIgnoreCase))
        {
            StopServer_Click(this, new RoutedEventArgs());
        }
    }

    private void SendCommand_Click(object? sender, RoutedEventArgs e)
    {
        var cmd = CommandInputBox.Text?.Trim();
        if (string.IsNullOrEmpty(cmd)) return;

        CommandInputBox.Text = "";
        ExecuteCommand(cmd);
    }

    private void CommandInput_KeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter)
        {
            SendCommand_Click(sender, e);
        }
    }

    private void SendFullCommand_Click(object? sender, RoutedEventArgs e)
    {
        var cmd = FullCommandInputBox.Text?.Trim();
        if (string.IsNullOrEmpty(cmd)) return;

        FullCommandInputBox.Text = "";
        ExecuteCommand(cmd);
    }

    private void FullCommandInput_KeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter)
        {
            SendFullCommand_Click(sender, e);
        }
    }

    private void QuickCmd_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.Tag is string cmd)
        {
            ExecuteCommand(cmd);
        }
    }

    private void ClearConsoleLog_Click(object? sender, RoutedEventArgs e)
    {
        FullLogStreamTextBlock.Text = "[EnderBridge Console] 日志已清空。";
        LogStreamTextBlock.Text = "[EnderBridge GUI] 日志已清空。";
    }

    private async void CopyConsoleLog_Click(object? sender, RoutedEventArgs e)
    {
        try
        {
            var topLevel = TopLevel.GetTopLevel(this);
            if (topLevel?.Clipboard != null)
            {
                await topLevel.Clipboard.SetTextAsync(FullLogStreamTextBlock.Text ?? "");
                AppendLog("[GUI] 控制台完整日志已复制到剪贴板！");
            }
        }
        catch {}
    }

    private void AppendLog(string message)
    {
        if (string.IsNullOrEmpty(message)) return;

        // 过滤清理 ANSI 颜色代码 (\x1b[32m 等) 以及清屏代码 (\r\x1b[K 等)
        var clean = AnsiRegex.Replace(message, "").Replace("\x1b", "").Replace("\r", "");
        var trimmed = clean.Trim();
        if (string.IsNullOrEmpty(trimmed) || trimmed == "EnderBridge>") return;

        LogStreamTextBlock.Text += $"\n{clean}";
        LogScrollViewer.ScrollToEnd();

        FullLogStreamTextBlock.Text += $"\n{clean}";
        FullLogScrollViewer.ScrollToEnd();

        CheckLogForWebUrl(clean);
    }

    private void CheckLogForWebUrl(string line)
    {
        var match = Regex.Match(line, @"https?://127\.0\.0\.1:\d+");
        if (match.Success)
        {
            var url = match.Value;
            if (!url.EndsWith("/")) url += "/";
            _backendUrl = url;
            _apiClient.SetBaseUrl(_backendUrl);
            Dispatcher.UIThread.Post(() =>
            {
                BrowserUrlTextBox.Text = _backendUrl;
                if (BrowserContainer.IsVisible)
                {
                    NavigateWebView(_backendUrl);
                }
            });
        }
    }

    private void SafeMode_Click(object? sender, RoutedEventArgs e)
    {
        AppendLog("[GUI] 出厂排障模式: 即将使用 --safe-mode 参数拉起核心服务 (跳过第三方Mod)");
    }

    private void OpenWebUI_Click(object? sender, RoutedEventArgs e)
    {
        SelectTab("WebUI");
    }

    private void CloseBetaNotice_Click(object? sender, RoutedEventArgs e)
    {
        BetaNoticeBanner.IsVisible = false;
    }

    private void QuickAction_Mods(object? sender, RoutedEventArgs e) => SelectTab("Mods");
    private void QuickAction_QQ(object? sender, RoutedEventArgs e) => SelectTab("Config");
    private void QuickAction_Backup(object? sender, RoutedEventArgs e) => SelectTab("Settings");
    private void QuickAction_Studio(object? sender, RoutedEventArgs e) => SelectTab("Studio");

    private void VersionCard_PointerPressed(object? sender, PointerPressedEventArgs e)
    {
        SelectTab("Versions");
    }

    private void MainServerToggle_Click(object? sender, RoutedEventArgs e)
    {
        if (_serverProcess != null && !_serverProcess.HasExited)
        {
            StopServer_Click(sender, e);
        }
        else
        {
            StartServer_Click(sender, e);
        }
    }

    // ==========================================
    // 5. 鉴权与 APP 登录功能 (/api/auth)
    // ==========================================
    private string? _currentUsername;
    private string? _currentUserRole;

    private void UserAuthBadge_Click(object? sender, RoutedEventArgs e)
    {
        if (!string.IsNullOrEmpty(_apiClient.Token))
        {
            AppendLog($"[GUI 认证] 当前已登录为 {_currentUsername} ({_currentUserRole})。正在执行登出...");
            _ = LogoutUserAsync();
        }
        else
        {
            LoginUsernameBox.Text = "admin";
            LoginPasswordBox.Text = "";
            LoginErrorText.IsVisible = false;
            LoginOverlay.IsVisible = true;
        }
    }

    private void CloseLoginOverlay_Click(object? sender, RoutedEventArgs e)
    {
        LoginOverlay.IsVisible = false;
    }

    private void LoginPassword_KeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter)
        {
            e.Handled = true;
            LoginSubmit_Click(sender, e);
        }
    }

    private async void LoginSubmit_Click(object? sender, RoutedEventArgs e)
    {
        var user = LoginUsernameBox.Text?.Trim() ?? "";
        var pass = (LoginPasswordBox.Text ?? "").Trim('\r', '\n');

        if (string.IsNullOrEmpty(user))
        {
            LoginErrorText.Text = "请输入用户名";
            LoginErrorText.IsVisible = true;
            return;
        }

        if (string.IsNullOrEmpty(pass))
        {
            LoginErrorText.Text = "请输入密码（支持明文密码或 users.json 中的密文哈希）";
            LoginErrorText.IsVisible = true;
            return;
        }

        // 检查服务端是否在运行，未运行则直接友好拦截并提示
        if (_serverProcess == null || _serverProcess.HasExited)
        {
            bool isResponding = false;
            try
            {
                using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(1));
                var ping = await _http.GetAsync($"{_backendUrl.TrimEnd('/')}/api/health", cts.Token);
                isResponding = ping.IsSuccessStatusCode;
            }
            catch {}

            if (!isResponding)
            {
                // 服务端离线状态下，尝试使用本地 config/users.json 进行离线管理员鉴权
                var rootDir = _localCore.RootDirectory ?? AppContext.BaseDirectory;
                var usersFile = Path.Combine(rootDir, "config", "users.json");
                if (!File.Exists(usersFile)) usersFile = Path.Combine(rootDir, "users.json");

                bool offlineOk = false;
                string? offlineRole = null;

                if (File.Exists(usersFile))
                {
                    try
                    {
                        var usersJson = await File.ReadAllTextAsync(usersFile);
                        using var doc = JsonDocument.Parse(usersJson);
                        if (doc.RootElement.TryGetProperty("users", out var usersObj) &&
                            usersObj.TryGetProperty(user, out var userElem))
                        {
                            var userRole = userElem.TryGetProperty("role", out var roleProp) ? roleProp.GetString() ?? "viewer" : "viewer";
                            var hash = userElem.TryGetProperty("password_hash", out var hashProp) ? hashProp.GetString() ?? "" : "";

                            if (pass == hash || pass.Trim() == hash.Trim())
                            {
                                offlineOk = true;
                                offlineRole = userRole;
                            }
                            else
                            {
                                var pythonExe = FindPythonExecutable(rootDir);
                                var escapedPass = pass.Replace("\\", "\\\\").Replace("\"", "\\\"");
                                var escapedHash = hash.Replace("\\", "\\\\").Replace("\"", "\\\"");
                                var psi = new ProcessStartInfo
                                {
                                    FileName = pythonExe,
                                    Arguments = $"-c \"import sys; from lib.users import verify_password; sys.exit(0 if verify_password(\\\"\"\"{escapedPass}\\\"\"\", \\\"\"\"{escapedHash}\\\"\"\") else 1)\"",
                                    WorkingDirectory = rootDir,
                                    UseShellExecute = false,
                                    CreateNoWindow = true
                                };
                                using var p = Process.Start(psi);
                                if (p != null)
                                {
                                    await p.WaitForExitAsync();
                                    if (p.ExitCode == 0)
                                    {
                                        offlineOk = true;
                                        offlineRole = userRole;
                                    }
                                }
                            }
                        }
                    }
                    catch (Exception ex)
                    {
                        AppendLog($"[GUI 离线认证] 校验过程异常: {ex.Message}");
                    }
                }

                if (offlineOk && !string.IsNullOrEmpty(offlineRole))
                {
                    var offlineToken = $"offline_{Guid.NewGuid():N}";
                    _apiClient.SetToken(offlineToken);
                    _currentUsername = user;
                    _currentUserRole = offlineRole;
                    UserAuthBadgeBtn.Content = $"🛡️ {user} ({offlineRole}) [点击退出]";
                    UserAuthBadgeBtn.Foreground = BrushOk;
                    LoginOverlay.IsVisible = false;
                    AppendLog($"[GUI 离线认证] ✅ 离线身份验证通过！当前身份: {user} (角色: {offlineRole})");
                    ShowToast($"✅ 离线登录成功！欢迎，{user} ({offlineRole})", ToastType.Success);
                    SaveSessionLocally(offlineToken, user, offlineRole);
                    RefreshActiveView();
                    return;
                }

                LoginErrorText.Text = "核心服务端未启动且离线管理员凭据验证未通过！请启动服务或检查账号密码。";
                LoginErrorText.IsVisible = true;
                AppendLog("[GUI 认证] ❌ 服务端未运行且离线凭据错误");
                ShowToast("❌ 登录失败：凭据错误或服务端未启动", ToastType.Error);
                return;
            }
        }

        LoginSubmitBtn.IsEnabled = false;
        LoginErrorText.IsVisible = false;

        AppendLog($"[GUI 认证] 正在向服务端提交凭据验证: 用户名 [{user}] ...");
        var (ok, msg, token, uname, role) = await _apiClient.LoginAsync(user, pass);
        LoginSubmitBtn.IsEnabled = true;

        if (ok && !string.IsNullOrEmpty(token))
        {
            _currentUsername = uname;
            _currentUserRole = role;
            UserAuthBadgeBtn.Content = $"🛡️ {uname} ({role}) [点击退出]";
            UserAuthBadgeBtn.Foreground = BrushOk;
            LoginOverlay.IsVisible = false;
            AppendLog($"[GUI 认证] ✅ 登录成功！当前身份: {uname} (角色: {role})");
            ShowToast($"✅ 登录成功！欢迎，{uname} ({role})", ToastType.Success);
            SaveSessionLocally(token, uname, role);
            RefreshActiveView();
        }
        else
        {
            LoginErrorText.Text = $"登录失败: {msg}";
            LoginErrorText.IsVisible = true;
            AppendLog($"[GUI 认证] ❌ 登录失败: {msg}");
            ShowToast($"❌ 登录失败: {msg}", ToastType.Error);
        }
    }

    private void LoginAsGuest_Click(object? sender, RoutedEventArgs e)
    {
        _ = LogoutUserAsync();
        LoginOverlay.IsVisible = false;
    }

    private async Task LogoutUserAsync()
    {
        await _apiClient.LogoutAsync();
        _currentUsername = null;
        _currentUserRole = null;
        UserAuthBadgeBtn.Content = "👤 访客模式 (点击登录)";
        UserAuthBadgeBtn.Foreground = BrushWarn;
        try
        {
            var sessionFile = Path.Combine(AppContext.BaseDirectory, "auth_session.json");
            if (File.Exists(sessionFile)) File.Delete(sessionFile);
        }
        catch {}
        AppendLog("[GUI 认证] 已退出登录");
        ShowToast("已退出登录", ToastType.Info);
        RefreshActiveView();
    }

    private void SaveSessionLocally(string? token, string? uname, string? role)
    {
        try
        {
            var sessionFile = Path.Combine(AppContext.BaseDirectory, "auth_session.json");
            var json = JsonSerializer.Serialize(new { token, username = uname, role });
            File.WriteAllText(sessionFile, json);
        }
        catch {}
    }

    private void LoadSavedSession()
    {
        try
        {
            var sessionFile = Path.Combine(AppContext.BaseDirectory, "auth_session.json");
            if (File.Exists(sessionFile))
            {
                var text = File.ReadAllText(sessionFile);
                var node = JsonNode.Parse(text);
                var token = node?["token"]?.GetValue<string>();
                var uname = node?["username"]?.GetValue<string>();
                var role = node?["role"]?.GetValue<string>();
                if (!string.IsNullOrEmpty(token))
                {
                    _apiClient.SetToken(token);
                    _currentUsername = uname;
                    _currentUserRole = role;
                    UserAuthBadgeBtn.Content = $"🛡️ {uname} ({role}) [点击退出]";
                    UserAuthBadgeBtn.Foreground = BrushOk;
                    AppendLog($"[GUI 认证] 已自动载入本地凭证: {uname} ({role})");
                }
            }
        }
        catch {}
    }

    private void RefreshActiveView()
    {
        if (ModsScrollViewer.IsVisible) _ = FetchAndRenderModsAsync();
        if (ConfigScrollViewer.IsVisible) _ = FetchAndRenderConfigAsync();
        if (StudioScrollViewer.IsVisible) _ = FetchAndRenderStudioAsync();
        if (SettingsScrollViewer.IsVisible) _ = FetchAndRenderBackupsAndPermissionsAsync();
    }
}
