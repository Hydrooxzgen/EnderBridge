using System;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Media;

namespace OnePointUI.Avalonia.Classes;

public sealed class ParallaxImage3D : Image
{
    // --- 定义属性 ---
    public static readonly StyledProperty<double> RotateXProperty =
        AvaloniaProperty.Register<ParallaxImage3D, double>(nameof(RotateX));

    public static readonly StyledProperty<double> RotateYProperty =
        AvaloniaProperty.Register<ParallaxImage3D, double>(nameof(RotateY));

    public static readonly StyledProperty<double> ScaleValueProperty =
        AvaloniaProperty.Register<ParallaxImage3D, double>(nameof(ScaleValue), 1.0);

    public double RotateX { get => GetValue(RotateXProperty); set => SetValue(RotateXProperty, value); }
    public double RotateY { get => GetValue(RotateYProperty); set => SetValue(RotateYProperty, value); }
    public double ScaleValue { get => GetValue(ScaleValueProperty); set => SetValue(ScaleValueProperty, value); }

    // --- 配置参数 ---
    private const double MaxRotationAngle = 6.0;
    private const double DeadzoneThreshold = 0.0;
    private const double EdgeCompensation = 0.05;

    // 动态计算的缩放基准
    private double _dynamicActiveScale = 1.2; 

    private readonly Rotate3DTransform _rotateTransform;
    private readonly ScaleTransform _scaleTransform;

    public ParallaxImage3D()
    {
        this.RenderTransformOrigin = new RelativePoint(0.5, 0.5, RelativeUnit.Relative);

        _rotateTransform = new Rotate3DTransform { Depth = 800 };
        _scaleTransform = new ScaleTransform();

        base.RenderTransform = new TransformGroup
        {
            Children = { _rotateTransform, _scaleTransform }
        };

        this.Stretch = Stretch.UniformToFill;
        this.ClipToBounds = false;

        // 监听自身大小变化，重新计算缩放倍率
        this.PropertyChanged += (s, e) =>
        {
            if (e.Property == BoundsProperty) UpdateDynamicScale();
        };
    }

    /// <summary>
    /// 根据当前窗口/控件大小计算最合适的缩放倍率
    /// </summary>
    private void UpdateDynamicScale()
    {
        if (TopLevel.GetTopLevel(this) is Window window)
        {
            // 获取窗口短边作为参考
            double windowRef = Math.Min(window.Bounds.Width, window.Bounds.Height);
            double controlRef = Math.Max(this.Bounds.Width, this.Bounds.Height);

            if (controlRef <= 0) return;

            // 算法逻辑：
            // 如果控件占满全屏，缩放倍率要小（如 1.05），否则边缘会出界太多
            // 如果控件很小（如缩略图），缩放倍率可以大一点（如 1.5）
            double ratio = controlRef / windowRef;

            // 线性插值计算：ratio 越大，scale 越小
            // 当 ratio=1 (全屏) -> scale=1.05
            // 当 ratio=0.2 (小组件) -> scale=1.3
            _dynamicActiveScale = Math.Clamp(1.35 - (ratio * 0.3), 1.05, 1.5);
        }
    }

    protected override void OnPropertyChanged(AvaloniaPropertyChangedEventArgs change)
    {
        base.OnPropertyChanged(change);
        if (change.Property == RotateXProperty) _rotateTransform.AngleX = change.GetNewValue<double>();
        else if (change.Property == RotateYProperty) _rotateTransform.AngleY = change.GetNewValue<double>();
        else if (change.Property == ScaleValueProperty)
        {
            double s = change.GetNewValue<double>();
            _scaleTransform.ScaleX = s;
            _scaleTransform.ScaleY = s;
        }
    }

    protected override void OnAttachedToVisualTree(VisualTreeAttachmentEventArgs e)
    {
        base.OnAttachedToVisualTree(e);
        if (TopLevel.GetTopLevel(this) is Window window)
        {
            window.PointerMoved += OnGlobalPointerMoved;
            window.PointerExited += OnGlobalPointerExited;
            // 窗口调整大小时也更新
            window.PropertyChanged += Window_PropertyChanged;
            UpdateDynamicScale();
        }
    }

    private void Window_PropertyChanged(object? sender, AvaloniaPropertyChangedEventArgs e)
    {
        if (e.Property == Window.BoundsProperty) UpdateDynamicScale();
    }

    protected override void OnDetachedFromVisualTree(VisualTreeAttachmentEventArgs e)
    {
        base.OnDetachedFromVisualTree(e);
        if (TopLevel.GetTopLevel(this) is Window window)
        {
            window.PointerMoved -= OnGlobalPointerMoved;
            window.PointerExited -= OnGlobalPointerExited;
            window.PropertyChanged -= Window_PropertyChanged;
        }
    }

    private void OnGlobalPointerMoved(object? sender, PointerEventArgs e)
    {
        var bounds = base.Bounds;
        if (!base.IsLoaded || bounds.Width <= 0 || bounds.Height <= 0) return;

        var pos = e.GetPosition(this);
        double percentX = (pos.X / bounds.Width - 0.5) * 2.0;
        double percentY = (pos.Y / bounds.Height - 0.5) * 2.0;

        if (Math.Abs(percentX) <= 1.1 && Math.Abs(percentY) <= 1.1)
        {
            double finalX = ApplyThreshold(percentX, DeadzoneThreshold);
            double finalY = ApplyThreshold(percentY, DeadzoneThreshold);

            RotateY = finalX * MaxRotationAngle;
            RotateX = -finalY * MaxRotationAngle;

            double intensity = Math.Max(Math.Abs(finalX), Math.Abs(finalY));
            // 使用动态计算的基准倍率
            ScaleValue = _dynamicActiveScale + (EdgeCompensation * intensity);
        }
        else
        {
            ResetTransform();
        }
    }

    private void OnGlobalPointerExited(object? sender, PointerEventArgs e) => ResetTransform();

    private void ResetTransform()
    {
        RotateX = 0;
        RotateY = 0;
        ScaleValue = 1.0;
    }

    private double ApplyThreshold(double value, double threshold)
    {
        double absValue = Math.Abs(value);
        if (absValue < threshold) return 0;
        return Math.Sign(value) * Math.Clamp((absValue - threshold) / (1.0 - threshold), 0, 1.0);
    }
}