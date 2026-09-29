using System.Diagnostics;
using Avalonia;
using Avalonia.Media;
using Avalonia.Platform;
using Avalonia.Rendering.Composition;
using Avalonia.Rendering.SceneGraph;
using Avalonia.Skia;
using Avalonia.Styling;
using SkiaSharp;

namespace OnePointUI.Avalonia.Styling.Effect;

public abstract class EffectDrawBase : CompositionCustomVisualHandler
{
    public static readonly object StartAnimations = new(),
        StopAnimations = new(),
        EnableForceSoftwareRendering = new(),
        DisableForceSoftwareRendering = new();

    private readonly Stopwatch _animationTick = new();
    private readonly bool _invalidateRect;
    private bool _animationEnabled;
    private SkiaEffect _effect;

    protected EffectDrawBase(bool invalidateRect = true)
    {
        _invalidateRect = invalidateRect;

        //var sTheme = SukiTheme.GetInstance();
        //sTheme.OnBaseThemeChanged += v => ActiveVariant = v;
        //ActiveVariant = sTheme.ActiveBaseTheme;
        //sTheme.OnColorThemeChanged += t => ActiveTheme = t;
        //ActiveTheme = sTheme.ActiveColorTheme!;
    }

    public SkiaEffect Effect
    {
        get => _effect;
        set
        {
            var old = _effect;
            if (Equals(old, value)) return;
            _effect = value;
            EffectChanged(old, _effect);
        }
    }

    public bool AnimationEnabled
    {
        get => _animationEnabled;
        set
        {
            if (value) _animationTick.Start();
            else _animationTick.Stop();
            _animationEnabled = value;
        }
    }

    public bool ForceSoftwareRendering { get; set; }
    protected float AnimationSpeedScale { get; set; } = 0.1f;
    protected ThemeVariant ActiveVariant { get; private set; }
    protected float AnimationSeconds => (float)_animationTick.Elapsed.TotalSeconds;

    public override void OnRender(ImmediateDrawingContext context)
    {
        var leaseFeature = context.TryGetFeature<ISkiaSharpApiLeaseFeature>()
                           ?? throw new InvalidOperationException("Unable to lease Skia API");

        using var lease = leaseFeature.Lease();
        var rect = SKRect.Create((float)EffectiveSize.X, (float)EffectiveSize.Y);
        if (lease.GrContext is null ||
            ForceSoftwareRendering) // GrContext is null whenever there is no hardware acceleration available
            RenderSoftware(lease.SkCanvas, rect);
        else
            Render(lease.SkCanvas, rect);
    }

    public override void OnMessage(object message)
    {
        if (message == StartAnimations)
        {
            AnimationEnabled = true;
            RegisterForNextAnimationFrameUpdate();
        }
        else if (message == StopAnimations)
        {
            AnimationEnabled = false;
        }
        else if (message is SkiaEffect effect)
        {
            Effect = effect;
        }
    }

    public override void OnAnimationFrameUpdate()
    {
        if (!AnimationEnabled) return;

        // 当 visual 被分离（窗口最小化、控件不可见、Compositor 暂停）时跳过渲染
        if (!IsAttachedToVisualTree)
        {
            RegisterForNextAnimationFrameUpdate();
            return;
        }

        if (_invalidateRect)
            Invalidate(GetRenderBounds());
        else
            Invalidate();
        RegisterForNextAnimationFrameUpdate();
    }

    private bool IsAttachedToVisualTree =>
        // CompositionCustomVisualHandler 没有直接的 IsAttached 暴露，依赖外部 Start/Stop 即可
        // 当窗口最小化 / 控件被卸载时，OnAnimationFrameUpdate 仍会被调用但渲染目标已失效
        // 因此用 RenderBounds 是否为 0 来判定，不为 0 才进行 Invalidate
        EffectiveSize.X > 0 && EffectiveSize.Y > 0;

    //protected abstract void InvalidateInternal();

    /// <summary>
    ///     Called every frame to render content.
    /// </summary>
    protected abstract void Render(SKCanvas canvas, SKRect rect);

    /// <summary>
    ///     Called every frame whenever the app falls back to software rendering (or <see cref="ForceSoftwareRendering" /> is
    ///     enabled)
    /// </summary>
    protected abstract void RenderSoftware(SKCanvas canvas, SKRect rect);

    protected SKShader EffectWithUniforms(float alpha = 1f)
    {
        return EffectWithUniforms(Effect, alpha);
    }

    protected SKShader EffectWithUniforms(SkiaEffect effect, float alpha = 1f)
    {
        return effect?.ToShaderWithUniforms(AnimationSeconds, ActiveVariant, GetRenderBounds(), AnimationSpeedScale,
            alpha);
    }

    protected SKShader EffectWithCustomUniforms(Func<SKRuntimeEffect, SKRuntimeEffectUniforms> uniformFactory,
        float alpha = 1f)
    {
        return EffectWithCustomUniforms(Effect, uniformFactory, alpha);
    }

    protected SKShader EffectWithCustomUniforms(SkiaEffect effect,
        Func<SKRuntimeEffect, SKRuntimeEffectUniforms> uniformFactory, float alpha = 1f)
    {
        return effect?.ToShaderWithCustomUniforms(uniformFactory, AnimationSeconds, GetRenderBounds(),
            AnimationSpeedScale, alpha);
    }

    protected virtual void EffectChanged(SkiaEffect oldValue, SkiaEffect newValue)
    {
        // no-op
    }

    public virtual void Dispose()
    {
        // no-op
    }

    public virtual bool Equals(ICustomDrawOperation other)
    {
        return false;
    }

    public virtual bool HitTest(Point p)
    {
        return false;
    }
}