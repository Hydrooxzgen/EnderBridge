using Avalonia;
using Avalonia.Controls;
using OnePointUI.Avalonia.Styling.Controls.OnePointControls.WindowFrame;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls.Navigation.TabView;

public class TabViewWindow : OnePointWindow
{
    public TabViewWindow()
    {
        WindowStartupLocation = WindowStartupLocation.Manual;
        Width = 900;
        Height = 560;
        MinWidth = 420;
        MinHeight = 280;
        IsMainWindow = false;
        TabView = new TabView
        {
            CloseOnLastTabClosed = true
        };
        TabView.SelectionChanged += (_, _) => SyncTitle();
        TabView.AddTabClick += (_, _) =>
        {
            TabView.AddPage("New Tab", new TextBlock
            {
                Text = "New Tab",
                Margin = new Thickness(20)
            });
        };
        MainContent = TabView;
        SyncTitle();
    }

    public TabView TabView { get; }

    private void SyncTitle()
    {
        Title = TabView.SelectedItem is TabViewItem item
            ? item.Header?.ToString() ?? "Tab"
            : "Tab";
    }
}
