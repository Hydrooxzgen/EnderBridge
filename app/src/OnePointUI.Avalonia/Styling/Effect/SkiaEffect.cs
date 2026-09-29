using System.Reflection;
using System.Text;
using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Media;
using Avalonia.Styling;
using OnePointUI.Avalonia.Style.Core;
using OnePointUI.Avalonia.Styling.Colors;
using SkiaSharp;

namespace OnePointUI.Avalonia.Styling.Effect;

public class SkiaEffect
{
    // Basic uniforms passed into the shader from the CPU.
    private static readonly string[] Uniforms =
    [
        "uniform float iTime;",
        "uniform float iDark;",
        "uniform float iAlpha;",
        "uniform vec3 iResolution;",
        "uniform vec3 iPrimary;",
        "uniform vec3 iAccent;",
        "uniform vec3 iBase;"
    ];

    private static bool _disposed;
    private static readonly float[] White = [0.95f, 0.95f, 0.95f];
    private static readonly List<SkiaEffect> LoadedEffects = [];
    private static float[] _backgroundAlloc = new[] { 0.08f, 0.08f, 0.12f };
    private static float[] _backgroundAccentAlloc = new[] { 1.00f, 0.27f, 0.00f };
    private static float[] _backgroundPrimaryAlloc = new[] { 0.00f, 0.82f, 0.82f };
    private readonly float[] _boundsAlloc = new float[3];
    private readonly string _rawShaderString;

    private readonly string _shaderString;

    static SkiaEffect()
    {
        if (Application.Current.ApplicationLifetime is IControlledApplicationLifetime controlled)
            controlled.Exit += (_, _) => EnsureDisposed();
    }

    //error: 85: unknown identifier 'smoothstep'\n1 error\n
    private SkiaEffect(string shaderString, string rawShaderString)
    {
        _shaderString = shaderString;
        _rawShaderString = rawShaderString;
        var compiledEffect = SKRuntimeEffect.CreateShader(_shaderString, out var errors);
        Effect = compiledEffect ?? throw new ShaderCompilationException(errors);
    }

    /// <summary>
    ///     The compiled <see cref="SKRuntimeEffect" /> that will actually be used in draw calls.
    /// </summary>
    public SKRuntimeEffect Effect { get; }

    public static void UpdateColor()
    {
        if (ThemeManager.CurrentThemeVariant == ThemeVariant.Dark)
        {
            var color = ThemeManager.AccentColor;
            _backgroundPrimaryAlloc = new[] { color.R / 255f, color.G / 255f, color.B / 255f };
            _backgroundAlloc = new[]
                { color.Darken(0.5).R / 255f, color.Darken(0.5).G / 255f, color.Darken(0.5).B / 255f };
            _backgroundAccentAlloc = new[]
                { color.Darken(1).R / 255f, color.Darken(1).G / 255f, color.Darken(1).B / 255f };
        }
        else if (ThemeManager.CurrentThemeVariant == ThemeVariant.Light)
        {
            var color = ThemeManager.AccentColor;
            _backgroundPrimaryAlloc = new[] { global::Avalonia.Media.Colors.White.R / 255f, global::Avalonia.Media.Colors.White.G / 255f, global::Avalonia.Media.Colors.White.B / 255f };
            _backgroundAlloc = new[]
                { color.Lighten(0.3).R / 255f, color.Lighten(0.3).G / 255f, color.Lighten(0.3).B / 255f };
            _backgroundAccentAlloc = new[]
                { color.Lighten(0.1).R / 255f, color.Lighten(0.1).G / 255f, color.Lighten(0.1).B / 255f };
        }
    }

    /// <summary>
    ///     Attempts to load and compile a ".sksl" shader file from the assembly.
    ///     You don't need to provide the extension.
    ///     The shader will be pre-compiled
    ///     REMEMBER: For files to be discoverable in the assembly they should be marked as an embedded resource.
    /// </summary>
    /// <param name="shaderName">Name of the shader to load, with or without extension. - MUST BE .sksl</param>
    public static SkiaEffect FromEmbeddedResource(string shaderName)
    {
        shaderName = shaderName.ToLowerInvariant();
        if (!shaderName.EndsWith(".sksl"))
            shaderName += ".sksl";

        var assembly = Assembly.GetEntryAssembly();
        var resName = assembly?.GetManifestResourceNames()
            .FirstOrDefault(x => x.Contains(shaderName, StringComparison.InvariantCultureIgnoreCase));

        if (resName is null)
        {
            assembly = Assembly.GetExecutingAssembly();
            resName = assembly?.GetManifestResourceNames()
                .FirstOrDefault(x => x.Contains(shaderName, StringComparison.InvariantCultureIgnoreCase));
        }

        if (resName is null)
        {
            assembly = typeof(SkiaEffect).Assembly;
            resName = assembly?.GetManifestResourceNames()
                .FirstOrDefault(x => x.Contains(shaderName, StringComparison.InvariantCultureIgnoreCase));
        }

        if (resName is null)
            throw new FileNotFoundException(
                $"Unable to find a file with the name \"{shaderName}\" anywhere in the assembly.");

        using var tr = new StreamReader(assembly.GetManifestResourceStream(resName)!);
        return FromString(tr.ReadToEnd());
    }

    /// <summary>
    ///     Attempts to compile an sksl shader from a string.
    ///     The shader will be pre-compiled and any errors will be thrown as an exception.
    ///     REMEMBER: For files to be discoverable in the assembly they should be marked as an embedded resource.
    /// </summary>
    /// <param name="shaderString">The shader code to be compiled.</param>
    /// <returns>An instance of a SukiBackgroundShader with the loaded shader</returns>
    public static SkiaEffect FromString(string shaderString)
    {
        var sb = new StringBuilder();
        foreach (var uniform in Uniforms)
            sb.AppendLine(uniform);

        sb.Append(shaderString);
        var withUniforms = sb.ToString();
        return new SkiaEffect(withUniforms, shaderString);
    }


    /// <summary>
    ///     Necessary to make sure all the unmanaged effects are disposed.
    /// </summary>
    internal static void EnsureDisposed()
    {
        if (_disposed)
            throw new InvalidOperationException(
                "Effects should only be disposed once at the app lifecycle end.");

        _disposed = true;
        foreach (var loaded in LoadedEffects)
            loaded.Effect.Dispose();

        LoadedEffects.Clear();
    }

    public override bool Equals(object obj)
    {
        if (obj is not SkiaEffect effect) return false;
        return effect._shaderString == _shaderString;
    }

    internal SKShader ToShaderWithUniforms(float timeSeconds, ThemeVariant activeVariant, Rect bounds,
        float animationScale, float alpha = 1f)
    {
        _boundsAlloc[0] = (float)bounds.Width;
        _boundsAlloc[1] = (float)bounds.Height;

        var inputs = new SKRuntimeEffectUniforms(Effect)
        {
            { "iResolution", _boundsAlloc },
            { "iTime", timeSeconds * animationScale },
            { "iBase", _backgroundAlloc },
            { "iAccent", _backgroundAccentAlloc },
            { "iPrimary", _backgroundPrimaryAlloc },
            { "iDark", activeVariant == ThemeVariant.Dark ? 1f : 0f },
            { "iAlpha", alpha }
        };

        return Effect.ToShader(inputs);
    }

    internal SKShader ToShaderWithCustomUniforms(Func<SKRuntimeEffect, SKRuntimeEffectUniforms> uniformFactory,
        float timeSeconds, Rect bounds,
        float animationScale, float alpha = 1f)
    {
        var uniforms = uniformFactory(Effect);
        uniforms.Add("iResolution", new[] { (float)bounds.Width, (float)bounds.Height, 0f });
        uniforms.Add("iTime", timeSeconds * animationScale);
        uniforms.Add("iAlpha", alpha);
        return Effect.ToShader(uniforms);
    }

    /// <summary>
    ///     Returns the pure shader string without uniforms.
    /// </summary>
    public override string ToString()
    {
        return _rawShaderString;
    }

    public override int GetHashCode()
    {
        return base.GetHashCode();
    }

    private class ShaderCompilationException(string message) : Exception(message);
}