using System.Collections.ObjectModel;
using Avalonia.Media;

namespace OnePointUI.Avalonia.Style.Core;

/// <summary>
///     主题色选择器，提供预定义的主题色和自定义主题色功能
/// </summary>
public class ThemeColorSelector
{
    // 预定义的主题色
    private static readonly Dictionary<string, Color> PredefinedColors = new()
    {
        { "橙色", Color.Parse("#FFBB00") },
        { "蓝色", Color.Parse("#0078D7") },
        { "绿色", Color.Parse("#107C10") },
        { "红色", Color.Parse("#E81123") },
        { "紫色", Color.Parse("#881798") },
        { "粉色", Color.Parse("#FF4081") },
        { "青色", Color.Parse("#00B7C3") },
        { "琥珀色", Color.Parse("#FFB900") },
        { "棕色", Color.Parse("#8E562E") },
        { "靛蓝色", Color.Parse("#3F51B5") }
    };

    /// <summary>
    ///     应用自定义主题色
    /// </summary>
    /// <param name="color">自定义颜色</param>
    private static bool _isApplyingColor;

    /// <summary>
    ///     获取预定义的主题色列表
    /// </summary>
    public static ReadOnlyDictionary<string, Color> Colors => new(PredefinedColors);

    /// <summary>
    ///     应用预定义的主题色
    /// </summary>
    /// <param name="colorName">主题色名称</param>
    /// <returns>是否应用成功</returns>
    public static bool ApplyPredefinedColor(string colorName)
    {
        if (_isApplyingColor) return false;

        _isApplyingColor = true;
        try
        {
            if (PredefinedColors.TryGetValue(colorName, out var color))
            {
                ThemeManager.Instance.SetAccentColor(color);
                return true;
            }

            return false;
        }
        finally
        {
            _isApplyingColor = false;
        }
    }

    public static void ApplyCustomColor(Color color)
    {
        if (_isApplyingColor) return;

        _isApplyingColor = true;
        try
        {
            ThemeManager.Instance.SetAccentColor(color);
        }
        finally
        {
            _isApplyingColor = false;
        }
    }

    /// <summary>
    ///     应用自定义主题色
    /// </summary>
    /// <param name="hexColor">十六进制颜色值，例如 "#FF0000"</param>
    /// <returns>是否应用成功</returns>
    public static bool ApplyCustomColor(string hexColor)
    {
        if (_isApplyingColor) return false;

        _isApplyingColor = true;
        try
        {
            var color = Color.Parse(hexColor);
            ThemeManager.Instance.SetAccentColor(color);
            return true;
        }
        catch (FormatException)
        {
            return false;
        }
        finally
        {
            _isApplyingColor = false;
        }
    }
}