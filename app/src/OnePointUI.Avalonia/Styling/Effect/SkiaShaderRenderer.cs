using Avalonia;
using Avalonia.Controls;
using Avalonia.Rendering.Composition;
using SkiaSharp;

namespace OnePointUI.Avalonia.Styling.Effect;

public sealed class SkiaShaderRenderer : Control
{
    private CompositionCustomVisual _customVisual;
    private SkiaEffect _sukiEffect;
    private bool _isRunning;

    protected override void OnAttachedToVisualTree(VisualTreeAttachmentEventArgs e)
    {
        base.OnAttachedToVisualTree(e);
        var comp = ElementComposition.GetElementVisual(this)?.Compositor;
        if (comp == null || _customVisual?.Compositor == comp)
            return;

        var visualHandler = new ShaderDraw();
        _customVisual = comp.CreateCustomVisual(visualHandler);
        ElementComposition.SetElementChildVisual(this, _customVisual);
        // 仅在 IsVisible 状态下才启动动画，避免后台/不可见时持续占用 GPU
        if (IsVisible) SendStart();
        if (_sukiEffect != null)
            _customVisual.SendHandlerMessage(_sukiEffect);

        Update();
    }

    private void Update()
    {
        if (_customVisual == null) return;
        _customVisual.Size = new Vector(Bounds.Width, Bounds.Height);
    }

    public void Stop()
    {
        IsVisible = false;
        SendStop();
    }

    public void Start()
    {
        IsVisible = true;
        SendStart();
    }

    private void SendStart()
    {
        if (_isRunning || _customVisual == null) return;
        _customVisual.SendHandlerMessage(EffectDrawBase.StartAnimations);
        _isRunning = true;
    }

    private void SendStop()
    {
        if (!_isRunning || _customVisual == null) return;
        _customVisual.SendHandlerMessage(EffectDrawBase.StopAnimations);
        _isRunning = false;
    }

    public void SetEffect(SkiaEffect effect)
    {
        _sukiEffect = effect;
        _customVisual?.SendHandlerMessage(effect);
    }

    protected override void OnPropertyChanged(AvaloniaPropertyChangedEventArgs change)
    {
        base.OnPropertyChanged(change);

        if (change.Property == BoundsProperty)
        {
            Update();
        }
        else if (change.Property == IsVisibleProperty)
        {
            // 跟随 IsVisible 自动启停动画，避免后台 60fps 空转
            if (IsVisible) SendStart();
            else SendStop();
        }
    }

    protected override void OnDetachedFromVisualTree(VisualTreeAttachmentEventArgs e)
    {
        // 控件从视觉树卸载时强制停止动画，防止后台帧回调持续触发
        SendStop();
        base.OnDetachedFromVisualTree(e);
    }

    private class ShaderDraw : EffectDrawBase
    {
        public ShaderDraw()
        {
            AnimationEnabled = true;
            AnimationSpeedScale = 2f;
        }

        protected override void Render(SKCanvas canvas, SKRect rect)
        {
            using var mainShaderPaint = new SKPaint();

            if (Effect is not null)
            {
                using var shader = EffectWithUniforms();
                mainShaderPaint.Shader = shader;
                canvas.DrawRect(rect, mainShaderPaint);
            }
        }

        protected override void RenderSoftware(SKCanvas canvas, SKRect rect)
        {
            throw new NotImplementedException();
        }
    }
}