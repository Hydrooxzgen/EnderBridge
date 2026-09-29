using Avalonia.Controls;

namespace EnderBridge.App.Views;

public partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();
        Closing += (s, e) =>
        {
            if (Content is MainView mv)
            {
                mv.KillServer();
            }
        };
    }
}
