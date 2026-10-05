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