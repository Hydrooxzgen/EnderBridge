using System;
using System.Collections.Generic;
using System.Globalization;
using Avalonia;
using Avalonia.Data.Converters;
using Avalonia.Media;

namespace OnePointUI.Avalonia.Converters
{
    public class ScrollViewerOpacityMaskConverter : IMultiValueConverter
    {
        public double FadeSize { get; set; } = 30.0;

        public object? Convert(IList<object?> values, Type targetType, object? parameter, CultureInfo culture)
        {
            if (values.Count >= 3 &&
                values[0] is double offsetY &&
                values[1] is double extentHeight &&
                values[2] is double viewportHeight &&
                viewportHeight > 0)
            {
                double maxScroll = extentHeight - viewportHeight;

                double topRatio = Math.Min(FadeSize / viewportHeight, 0.5);
                double bottomRatio = Math.Min(FadeSize / viewportHeight, 0.5);

                double topAlphaFactor = maxScroll > 0 ? Math.Min(1.0, offsetY / FadeSize) : 0.0;

                double remaining = maxScroll - offsetY;
                double bottomAlphaFactor = maxScroll > 0 ? Math.Min(1.0, Math.Max(0.0, remaining / FadeSize)) : 0.0;

                var brush = new LinearGradientBrush
                {
                    StartPoint = new RelativePoint(0, 0, RelativeUnit.Relative),
                    EndPoint = new RelativePoint(0, 1, RelativeUnit.Relative),
                    GradientStops = new GradientStops
                    {
                        new GradientStop(Color.FromArgb((byte)(255 * (1 - topAlphaFactor)), 0, 0, 0), 0.0),
                        new GradientStop(Colors.Black, topRatio),

                        new GradientStop(Colors.Black, 1.0 - bottomRatio),

                        new GradientStop(Color.FromArgb((byte)(255 * (1 - bottomAlphaFactor)), 0, 0, 0), 1.0)
                    }
                };

                return brush;
            }

            return Brushes.Black;
        }
    }
}