using System.Reflection;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Interactivity;

namespace OnePointUI.Avalonia.Behaviors;

public static class PopupDismissBehavior
{
    public static readonly AttachedProperty<bool> EnableDismissProperty =
        AvaloniaProperty.RegisterAttached<StyledElement, bool>(
            "EnableDismiss",
            typeof(PopupDismissBehavior));

    private static readonly FieldInfo? HostField =
        typeof(PopupRoot).GetField("Host", BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);

    private static readonly PropertyInfo? IsOpenProperty =
        typeof(Popup).GetProperty("IsOpen");

    static PopupDismissBehavior()
    {
        EnableDismissProperty.Changed.AddClassHandler<PopupRoot>(OnEnableDismissChanged);
    }

    public static void SetEnableDismiss(StyledElement element, bool value)
        => element.SetValue(EnableDismissProperty, value);

    public static bool GetEnableDismiss(StyledElement element)
        => element.GetValue(EnableDismissProperty);

    private static void OnEnableDismissChanged(PopupRoot popupRoot, AvaloniaPropertyChangedEventArgs e)
    {
        if ((bool)e.NewValue!)
        {
            popupRoot.Deactivated += OnPopupRootDeactivated;
            popupRoot.DetachedFromVisualTree += OnDetachedFromVisualTree;
        }
        else
        {
            popupRoot.Deactivated -= OnPopupRootDeactivated;
            popupRoot.DetachedFromVisualTree -= OnDetachedFromVisualTree;
        }
    }

    private static void OnDetachedFromVisualTree(object? sender, VisualTreeAttachmentEventArgs e)
    {
        if (sender is PopupRoot popupRoot)
        {
            popupRoot.Deactivated -= OnPopupRootDeactivated;
            popupRoot.DetachedFromVisualTree -= OnDetachedFromVisualTree;
        }
    }

    private static void OnPopupRootDeactivated(object? sender, EventArgs e)
    {
        if (sender is not PopupRoot popupRoot)
            return;

        // PopupRoot.Host is internal — use reflection to get the owning Popup
        if (HostField?.GetValue(popupRoot) is not Popup popup)
            return;

        popup.IsOpen = false;
    }
}
