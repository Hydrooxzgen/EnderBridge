// Author: Hydrooxzgen
// Github: https://github.com/Hydrooxzgen
// This project uses the GPL-3.0 license, you can modify/distribute this project according to the GPL-3.0 license
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
