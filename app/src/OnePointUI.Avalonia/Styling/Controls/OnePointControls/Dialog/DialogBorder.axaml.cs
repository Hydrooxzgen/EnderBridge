// Author: Hydrooxzgen
// Github: https://github.com/Hydrooxzgen
// This project uses the GPL-3.0 license, you can modify/distribute this project according to the GPL-3.0 license
using Avalonia.Controls;
using OnePointUI.Avalonia.Base.Entry;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls.Dialog;

public partial class DialogBorder : UserControl
{
    public DialogBorder(DialogInfo info)
    {
        InitializeComponent();

        ContentBorder.Child = new DialogContent(info);
    }
}