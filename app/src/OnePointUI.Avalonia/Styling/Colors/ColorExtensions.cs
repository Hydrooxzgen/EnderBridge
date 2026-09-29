using Avalonia.Media;

namespace OnePointUI.Avalonia.Styling.Colors;

/// <summary>
///     颜色扩展工具，提供颜色变暗、变亮、混合、透明度调整、亮度计算等通用方法
/// </summary>
public static class ColorExtensions
{
    private static double Clamp(double value, double min, double max)
    {
        return value < min ? min : value > max ? max : value;
    }

    /// <summary>
    ///     颜色变暗
    /// </summary>
    public static Color Darken(this Color color, double factor)
    {
        factor = Clamp(factor, 0, 1);
        return Color.FromArgb(
            color.A,
            (byte)(color.R * (1 - factor)),
            (byte)(color.G * (1 - factor)),
            (byte)(color.B * (1 - factor)));
    }

    /// <summary>
    ///     颜色变亮
    /// </summary>
    public static Color Lighten(this Color color, double factor)
    {
        factor = Clamp(factor, 0, 1);
        return Color.FromArgb(
            color.A,
            (byte)(color.R + (255 - color.R) * factor),
            (byte)(color.G + (255 - color.G) * factor),
            (byte)(color.B + (255 - color.B) * factor));
    }

    /// <summary>
    ///     调整透明度
    /// </summary>
    public static Color WithAlpha(this Color color, byte alpha)
    {
        return Color.FromArgb(alpha, color.R, color.G, color.B);
    }

    /// <summary>
    ///     调整透明度（0~1 浮点）
    /// </summary>
    public static Color WithAlpha(this Color color, double alpha)
    {
        alpha = Clamp(alpha, 0, 1);
        return Color.FromArgb((byte)(255 * alpha), color.R, color.G, color.B);
    }

    /// <summary>
    ///     与另一种颜色按比例混合（0 = 完全 current，1 = 完全 other）
    /// </summary>
    public static Color Mix(this Color color, Color other, double factor)
    {
        factor = Clamp(factor, 0, 1);
        return Color.FromArgb(
            (byte)(color.A + (other.A - color.A) * factor),
            (byte)(color.R + (other.R - color.R) * factor),
            (byte)(color.G + (other.G - color.G) * factor),
            (byte)(color.B + (other.B - color.B) * factor));
    }

    /// <summary>
    ///     叠加白色（叠加强度 0~1）
    /// </summary>
    public static Color Tint(this Color color, double factor)
    {
        return color.Mix(global::Avalonia.Media.Colors.White, Clamp(factor, 0, 1));
    }

    /// <summary>
    ///     叠加黑色（叠加强度 0~1）
    /// </summary>
    public static Color Shade(this Color color, double factor)
    {
        return color.Mix(global::Avalonia.Media.Colors.Black, Clamp(factor, 0, 1));
    }

    /// <summary>
    ///     计算相对亮度（0~1）
    /// </summary>
    public static double GetLuminance(this Color color)
    {
        var r = color.R / 255.0;
        var g = color.G / 255.0;
        var b = color.B / 255.0;
        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    }

    /// <summary>
    ///     根据亮度返回黑或白，确保对比度
    /// </summary>
    public static Color GetContrastColor(this Color color, double threshold = 0.55)
    {
        return color.GetLuminance() > threshold ? global::Avalonia.Media.Colors.Black : global::Avalonia.Media.Colors.White;
    }

    /// <summary>
    ///     提升饱和度
    /// </summary>
    public static Color Saturate(this Color color, double factor)
    {
        factor = Clamp(factor, 0, 1);
        var hsl = RgbToHsl(color);
        hsl.S = Clamp(hsl.S * (1 + factor), 0, 1);
        return HslToRgb(hsl);
    }

    /// <summary>
    ///     降低饱和度
    /// </summary>
    public static Color Desaturate(this Color color, double factor)
    {
        factor = Clamp(factor, 0, 1);
        var hsl = RgbToHsl(color);
        hsl.S = Clamp(hsl.S * (1 - factor), 0, 1);
        return HslToRgb(hsl);
    }

    private struct Hsl
    {
        public double H;
        public double S;
        public double L;
        public double A;
    }

    private static Hsl RgbToHsl(Color color)
    {
        var r = color.R / 255.0;
        var g = color.G / 255.0;
        var b = color.B / 255.0;
        var max = Math.Max(r, Math.Max(g, b));
        var min = Math.Min(r, Math.Min(g, b));
        var h = 0.0;
        var s = 0.0;
        var l = (max + min) / 2.0;
        if (Math.Abs(max - min) < 0.00001)
        {
            h = s = 0;
        }
        else
        {
            var d = max - min;
            s = l > 0.5 ? d / (2.0 - max - min) : d / (max + min);
            if (max == r) h = (g - b) / d + (g < b ? 6 : 0);
            else if (max == g) h = (b - r) / d + 2;
            else h = (r - g) / d + 4;
            h /= 6;
        }

        return new Hsl { H = h, S = s, L = l, A = color.A };
    }

    private static Color HslToRgb(Hsl hsl)
    {
        double r, g, b;
        if (hsl.S == 0)
        {
            r = g = b = hsl.L;
        }
        else
        {
            var q = hsl.L < 0.5 ? hsl.L * (1 + hsl.S) : hsl.L + hsl.S - hsl.L * hsl.S;
            var p = 2 * hsl.L - q;
            r = HueToRgb(p, q, hsl.H + 1.0 / 3.0);
            g = HueToRgb(p, q, hsl.H);
            b = HueToRgb(p, q, hsl.H - 1.0 / 3.0);
        }

        return Color.FromArgb(
            (byte)hsl.A,
            (byte)Math.Round(r * 255),
            (byte)Math.Round(g * 255),
            (byte)Math.Round(b * 255));
    }

    private static double HueToRgb(double p, double q, double t)
    {
        if (t < 0) t += 1;
        if (t > 1) t -= 1;
        if (t < 1.0 / 6.0) return p + (q - p) * 6 * t;
        if (t < 1.0 / 2.0) return q;
        if (t < 2.0 / 3.0) return p + (q - p) * (2.0 / 3.0 - t) * 6;
        return p;
    }
}
