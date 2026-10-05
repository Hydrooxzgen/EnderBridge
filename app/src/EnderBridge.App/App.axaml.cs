using System;
using System.IO;
using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using Avalonia.Threading;
using OnePointUI.Avalonia.Style.Core;
using EnderBridge.App.Views;

namespace EnderBridge.App;

public class App : Application
{
    private static void LogErr(Exception? ex, string src)
    {
        try
        {
            var logPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "app_error.log");
            File.AppendAllText(logPath, $"[{DateTime.Now}] [{src}] {ex}\n\n");
            File.AppendAllText(@"H:\Projects\EnderBridge\app_error.log", $"[{DateTime.Now}] [{src}] {ex}\n\n");
        }
        catch {}
    }

    public override void Initialize()
    {
        AppDomain.CurrentDomain.UnhandledException += (s, e) => LogErr(e.ExceptionObject as Exception, "AppDomain");
        Dispatcher.UIThread.UnhandledException += (s, e) => { LogErr(e.Exception, "UIThread"); e.Handled = true; };
        try
        {
            ThemeManager.Initialize(this);
            AvaloniaXamlLoader.Load(this);
        }
        catch (Exception ex)
        {
            LogErr(ex, "Initialize_Load");
            throw;
        }
    }

    public override void OnFrameworkInitializationCompleted()
    {
        try
        {
            if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
            {
                desktop.MainWindow = new MainWindow();
                desktop.Exit += (s, e) =>
                {
                    if (desktop.MainWindow?.Content is MainView mv)
                    {
                        mv.KillServer();
                    }
                };
            }
            else if (ApplicationLifetime is ISingleViewApplicationLifetime singleView)
            {
                singleView.MainView = new MainView();
            }
        }
        catch (Exception ex)
        {
            LogErr(ex, "OnFrameworkInitializationCompleted");
            throw;
        }

        base.OnFrameworkInitializationCompleted();
    }
}
