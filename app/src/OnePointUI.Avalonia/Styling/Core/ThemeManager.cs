using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Styling;
using OnePointUI.Avalonia.Styling.Colors;
using OnePointUI.Avalonia.Styling.Effect;

namespace OnePointUI.Avalonia.Style.Core;

/// <summary>
///     主题管理器：负责加载主题色/中性色资源，并提供从一个主题色自动衍生完整调色板的能力
/// </summary>
public class ThemeManager
{
    private static ThemeManager? _instance;
    public static ThemeVariant CurrentThemeVariant = ThemeVariant.Dark;
    public static Color AccentColor = Colors.Orange;
    private readonly Application _application;

    private bool _isApplyingThemeResources;
    private bool _isLoadingThemeColors;
    private bool _isUpdatingAccentColors;
    private bool _themeColorsLoaded;

    private ThemeManager(Application application)
    {
        Console.WriteLine(@"初始化主题");
        _application = application;
        Console.WriteLine(@"主题初始化完毕");
    }

    /// <summary>
    ///     检查ThemeManager是否已初始化
    /// </summary>
    public static bool IsInitialized => _instance != null;

    public static ThemeManager Instance
    {
        get
        {
            if (_instance == null)
                throw new InvalidOperationException("ThemeManager has not been initialized. Call Initialize first.");
            return _instance;
        }
    }

    /// <summary>
    ///     获取当前主题变体
    /// </summary>
    public ThemeVariant CurrentTheme => CurrentThemeVariant;

    public static void Initialize(Application application)
    {
        if (_instance != null) return;
        _instance = new ThemeManager(application);
    }

    /// <summary>
    ///     加载主题中性色资源（深/浅色），主题色资源在 <see cref="UpdateAccentColors" /> 中按需生成
    /// </summary>
    private void LoadThemeColors()
    {
        if (_isLoadingThemeColors) return;
        _isLoadingThemeColors = true;
        try
        {
            #region 深色主题

            // ==== 深色主题 ====
            var darkTheme = new ResourceDictionary();
            darkTheme["GeneralBorderBrush"] = new SolidColorBrush(Color.Parse("#0a0a0a"));
            darkTheme["GeneralBorderBrushOpacity"] = 0.45;

            // 填充
            darkTheme["SystemFillColorCriticalBrush"] = new SolidColorBrush(Color.Parse("#FF99A4"));
            darkTheme["SystemFillColorSuccessBrush"] = new SolidColorBrush(Color.Parse("#6CCB5F"));
            darkTheme["SystemFillColorCautionBrush"] = new SolidColorBrush(Color.Parse("#F7D154"));
            darkTheme["SystemFillColorNeutralBrush"] = new SolidColorBrush(Color.Parse("#C8C8C8"));

            // 背景与画布
            darkTheme["BackgroundBrush"] = new SolidColorBrush(Color.Parse("#1B1B1B"));
            darkTheme["BackgroundBrushOpacity"] = new SolidColorBrush(Color.Parse("#751B1B1B"));
            darkTheme["BackgroundSecondaryBrush"] = new SolidColorBrush(Color.Parse("#232323"));
            darkTheme["BackgroundSecondaryBrushOpacity"] = new SolidColorBrush(Color.Parse("#2d2d2d"));
            darkTheme["BackgroundTertiaryBrush"] = new SolidColorBrush(Color.Parse("#2C2C2C"));
            darkTheme["BackgroundHoverBrush"] = new SolidColorBrush(Color.Parse("#2F2F2F"));
            darkTheme["BackgroundSubtleBrush"] = new SolidColorBrush(Color.Parse("#1F1F1F"));

            // 前景/文字
            darkTheme["PrimaryForegroundBrush"] = new SolidColorBrush(Colors.White);
            darkTheme["PrimaryForegroundSecondaryBrush"] = new SolidColorBrush(Color.Parse("#D6D6D6"));
            darkTheme["PrimaryDisabledForegroundBrush"] = new SolidColorBrush(Color.Parse("#7A7A7A"));
            darkTheme["PrimaryDisabled2ForegroundBrush"] = new SolidColorBrush(Color.Parse("#A8A8A8"));
            darkTheme["PrimaryAccentForegroundBrush"] = new SolidColorBrush(Color.Parse("#FFBB00"));

            // 主控件背景/边框
            darkTheme["PrimaryBackgroundBrush"] = new SolidColorBrush(Color.Parse("#2D2D2D"));
            darkTheme["PrimaryBackgroundOpacityBrush"] = new SolidColorBrush(Color.Parse("#2D2D2D50"));
            darkTheme["PrimaryBackgroundOverBrush"] = new SolidColorBrush(Color.Parse("#383838"));
            darkTheme["PrimaryBackgroundPressedBrush"] = new SolidColorBrush(Color.Parse("#1A1A1A"));
            darkTheme["PrimaryBorderBrush"] = new SolidColorBrush(Color.Parse("#3F3F3F"));
            darkTheme["PrimaryBorderHoverBrush"] = new SolidColorBrush(Color.Parse("#525252"));
            darkTheme["PrimaryBorderPressedBrush"] = new SolidColorBrush(Color.Parse("#2A2A2A"));
            darkTheme["PrimaryDisabledBackgroundBrush"] = new SolidColorBrush(Color.Parse("#262626"));
            darkTheme["PrimaryDisabledBorderBrush"] = new SolidColorBrush(Color.Parse("#333333"));
            darkTheme["PrimarySubtleBackgroundBrush"] = new SolidColorBrush(Color.Parse("#22FFFFFF"));

            // 阴影/光晕
            darkTheme["ShadowBrush"] = new SolidColorBrush(Color.Parse("#80000000"));
            darkTheme["GlowBrush"] = new SolidColorBrush(Color.Parse("#40000000"));

            #endregion

            #region 浅色主题

            var lightTheme = new ResourceDictionary();
            lightTheme["GeneralBorderBrush"] = new SolidColorBrush(Color.Parse("#fbfbfb"));
            lightTheme["GeneralBorderBrushOpacity"] = 0.25;

            lightTheme["SystemFillColorCriticalBrush"] = new SolidColorBrush(Color.Parse("#C42B1C"));
            lightTheme["SystemFillColorSuccessBrush"] = new SolidColorBrush(Color.Parse("#0F7B0F"));
            lightTheme["SystemFillColorCautionBrush"] = new SolidColorBrush(Color.Parse("#9D5D00"));
            lightTheme["SystemFillColorNeutralBrush"] = new SolidColorBrush(Color.Parse("#5A5A5A"));

            lightTheme["BackgroundBrush"] = new SolidColorBrush(Color.Parse("#e8e8e7"));
            lightTheme["BackgroundBrushOpacity"] = new SolidColorBrush(Color.Parse("#85f4f4f4"));
            lightTheme["BackgroundSecondaryBrushOpacity"] = new SolidColorBrush(Color.Parse("#e9e9e9"));
            lightTheme["BackgroundSecondaryBrush"] = new SolidColorBrush(Color.Parse("#FFFFFF"));
            lightTheme["BackgroundTertiaryBrush"] = new SolidColorBrush(Color.Parse("#EFEFEF"));
            lightTheme["BackgroundHoverBrush"] = new SolidColorBrush(Color.Parse("#EDEDED"));
            lightTheme["BackgroundSubtleBrush"] = new SolidColorBrush(Color.Parse("#FAFAFA"));

            lightTheme["PrimaryForegroundBrush"] = new SolidColorBrush(Colors.Black);
            lightTheme["PrimaryForegroundSecondaryBrush"] = new SolidColorBrush(Color.Parse("#404040"));
            lightTheme["PrimaryDisabledForegroundBrush"] = new SolidColorBrush(Color.Parse("#A8A8A8"));
            lightTheme["PrimaryDisabled2ForegroundBrush"] = new SolidColorBrush(Color.Parse("#7C7C7C"));
            lightTheme["PrimaryAccentForegroundBrush"] = new SolidColorBrush(Color.Parse("#B66B00"));

            lightTheme["PrimaryBackgroundBrush"] = new SolidColorBrush(Color.Parse("#F0F0F0"));
            lightTheme["PrimaryBackgroundOverBrush"] = new SolidColorBrush(Color.Parse("#E6E6E6"));
            lightTheme["PrimaryBackgroundPressedBrush"] = new SolidColorBrush(Color.Parse("#D8D8D8"));
            lightTheme["PrimaryBorderBrush"] = new SolidColorBrush(Color.Parse("#D4D4D4"));
            lightTheme["PrimaryBorderHoverBrush"] = new SolidColorBrush(Color.Parse("#BDBDBD"));
            lightTheme["PrimaryBorderPressedBrush"] = new SolidColorBrush(Color.Parse("#C4C4C4"));
            lightTheme["PrimaryDisabledBackgroundBrush"] = new SolidColorBrush(Color.Parse("#F5F5F5"));
            lightTheme["PrimaryDisabledBorderBrush"] = new SolidColorBrush(Color.Parse("#E2E2E2"));
            lightTheme["PrimarySubtleBackgroundBrush"] = new SolidColorBrush(Color.Parse("#10000000"));

            lightTheme["ShadowBrush"] = new SolidColorBrush(Color.Parse("#33000000"));
            lightTheme["GlowBrush"] = new SolidColorBrush(Color.Parse("#22000000"));

            #endregion

            // 将主题资源添加到应用程序资源中
            _application.Resources["DarkTheme"] = darkTheme;
            _application.Resources["LightTheme"] = lightTheme;
            _themeColorsLoaded = true;
        }
        finally
        {
            _isLoadingThemeColors = false;
        }
    }

    /// <summary>
    ///     切换主题（深色/浅色）
    /// </summary>
    public void SetThemeModel(ThemeVariant theme)
    {
        SetTheme(theme);
    }

    /// <summary>
    ///     设置主题（深色/浅色）
    /// </summary>
    /// <param name="themeVariant">主题变体</param>
    public void SetTheme(ThemeVariant themeVariant)
    {
        CurrentThemeVariant = themeVariant;
        _application.RequestedThemeVariant = themeVariant;
        SkiaEffect.UpdateColor();
        ApplyThemeResources();
    }

    public void SetAccentColor(Color color)
    {
        SkiaEffect.UpdateColor();
        AccentColor = color;
        if (!_isUpdatingAccentColors) UpdateAccentColors();
    }

    private void ApplyThemeResources()
    {
        if (_isApplyingThemeResources) return;
        _isApplyingThemeResources = true;
        try
        {
            if (!_themeColorsLoaded) LoadThemeColors();

            var themeDictKey = CurrentThemeVariant == ThemeVariant.Dark ? "DarkTheme" : "LightTheme";
            if (_application.Resources.TryGetValue(themeDictKey, out var themeDict) &&
                themeDict is ResourceDictionary resourceDict)
            {
                foreach (var key in resourceDict.Keys) _application.Resources[key] = resourceDict[key];
                UpdateAccentColors();
            }
        }
        finally
        {
            _isApplyingThemeResources = false;
        }
    }

    /// <summary>
    ///     根据当前 <see cref="AccentColor" /> 重新生成所有主题色画笔
    /// </summary>
    private void UpdateAccentColors()
    {
        if (_isUpdatingAccentColors) return;
        _isUpdatingAccentColors = true;
        try
        {
            var isDark = CurrentThemeVariant == ThemeVariant.Dark;
            var accent = AccentColor;
            var luminance = accent.GetLuminance();

            // 主色及其明度变化
            var lighter = accent.Lighten(0.35);
            var light = accent.Lighten(0.18);
            var dark = accent.Darken(0.18);
            var darker = accent.Darken(0.35);
            var darkest = accent.Darken(0.55);

            // Hover/Pressed：在深色主题中变亮，在浅色主题中变暗
            var hover = isDark ? accent.Lighten(0.12) : accent.Darken(0.08);
            var pressed = isDark ? accent.Lighten(0.20) : accent.Darken(0.16);

            // 边框色：在深色主题中变暗，在浅色主题中变暗（保持一致）
            var border = isDark ? accent.Darken(0.25) : accent.Darken(0.15);
            var borderHover = isDark ? accent.Darken(0.15) : accent.Darken(0.05);

            // 前景/文字：基于主色亮度自适应
            var foreground = luminance > 0.6 ? Colors.Black : Colors.White;
            var foregroundSecondary = isDark
                ? accent.Lighten(0.25).WithAlpha(0.85)
                : accent.Darken(0.10).WithAlpha(0.85);

            // 微妙的背景（用作 selected/hover 底色）
            var subtle = accent.WithAlpha(isDark ? 0.18 : 0.12);
            var subtleHover = accent.WithAlpha(isDark ? 0.28 : 0.18);
            var subtlePressed = accent.WithAlpha(isDark ? 0.36 : 0.24);

            _application.Resources["AccentBackgroundBrush"] = new SolidColorBrush(accent);
            _application.Resources["AccentBackgroundHoverBrush"] = new SolidColorBrush(hover);
            _application.Resources["AccentBackgroundPressedBrush"] = new SolidColorBrush(pressed);
            _application.Resources["AccentBorderBrush"] = new SolidColorBrush(border);
            _application.Resources["AccentBorderHoverBrush"] = new SolidColorBrush(borderHover);
            _application.Resources["AccentForegroundBrush"] = new SolidColorBrush(foreground);
            _application.Resources["AccentForegroundSecondaryBrush"] = new SolidColorBrush(foregroundSecondary);

            _application.Resources["AccentLightBrush"] = new SolidColorBrush(light);
            _application.Resources["AccentLighterBrush"] = new SolidColorBrush(lighter);
            _application.Resources["AccentDarkBrush"] = new SolidColorBrush(dark);
            _application.Resources["AccentDarkerBrush"] = new SolidColorBrush(darker);
            _application.Resources["AccentDarkestBrush"] = new SolidColorBrush(darkest);

            _application.Resources["AccentSubtleBrush"] = new SolidColorBrush(subtle);
            _application.Resources["AccentSubtleHoverBrush"] = new SolidColorBrush(subtleHover);
            _application.Resources["AccentSubtlePressedBrush"] = new SolidColorBrush(subtlePressed);

            // 向后兼容：保留旧名称，等价映射到新画笔
            _application.Resources["AccentBackgroundOverBrush"] = new SolidColorBrush(pressed);
        }
        finally
        {
            _isUpdatingAccentColors = false;
        }
    }
}