using System;
using System.IO;
using Avalonia;
using EnderBridge.App;

namespace EnderBridge.App.Desktop;

internal sealed class Program
{
    [STAThread]
    public static void Main(string[] args)
    {
        try
        {
            Console.WriteLine("[DEBUG] Starting EnderBridge Avalonia App...");
            BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
        }
        catch (Exception ex)
        {
            File.WriteAllText("crash.log", ex.ToString());
            Console.ForegroundColor = ConsoleColor.Red;
            Console.WriteLine($"[CRASH] {ex}");
            Console.ResetColor();
        }
    }

    public static AppBuilder BuildAvaloniaApp()
    {
        return AppBuilder.Configure<App>()
            .UsePlatformDetect()
            .WithInterFont()
            .LogToTrace();
    }
}
