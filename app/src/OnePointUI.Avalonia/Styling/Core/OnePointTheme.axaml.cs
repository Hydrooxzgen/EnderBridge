using System.Diagnostics;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Markup.Xaml;
using Avalonia.Media;
using Avalonia.Styling;

namespace OnePointUI.Avalonia.Style.Core;

public class OnePointTheme : Styles, IResourceProvider
{
    private Color _AccentColor = Colors.Orange;
    private ThemeVariant _ThemeVariant = ThemeVariant.Dark;

    public OnePointTheme()
    {
        // 加载XAML
        AvaloniaXamlLoader.Load(this);

        // 在应用程序初始化完成后注册主题资源
        Application.Current!.ResourcesChanged += OnApplicationResourcesChanged;
        ThemeManager.Instance.SetTheme(ThemeVariant);
    }

    public Color AccentColor
    {
        get => _AccentColor;
        set
        {
            _AccentColor = value;
            ThemeManager.Instance.SetAccentColor(_AccentColor);
        }
    }

    public ThemeVariant ThemeVariant
    {
        get => _ThemeVariant;
        set
        {
            _ThemeVariant = value;
            ThemeManager.Instance.SetTheme(_ThemeVariant);
        }
    }

    private void OnApplicationResourcesChanged(object? sender, ResourcesChangedEventArgs e)
    {
        if (sender is Application app && Application.Current != null)
            try
            {
                // 检查ThemeManager是否已初始化
                if (ThemeManager.IsInitialized)
                {
                    // 根据应用程序当前请求的主题设置初始主题
                    var initialTheme = Application.Current.RequestedThemeVariant ?? ThemeVariant.Default;
                    ThemeManager.Instance.SetTheme(initialTheme);
                }

                // 注册完成后取消事件订阅
                Application.Current.ResourcesChanged -= OnApplicationResourcesChanged;
            }
            catch (Exception ex)
            {
                // 处理异常
                Console.WriteLine($@"主题资源应用失败: {ex.Message}");
            }

        ThemeManager.Instance.SetAccentColor(AccentColor);
    }
}