using Avalonia.Controls;
using Avalonia.Interactivity;
using OnePointUI.Avalonia.Base.Entry;
using OnePointUI.Avalonia.Base.Enum;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls.Dialog;

public partial class DialogContent : UserControl
{
    private readonly DialogInfo _info;

    public DialogContent(DialogInfo info)
    {
        _info = info;
        InitializeComponent();

        TitleBox.Text = info.Title;
        ContentBox.Content = info.Content;

        switch (info.AccountButton)
        {
            case DialogButtons.CloseButton:
                CloseBtn.Classes.Add("AccentBorder");
                break;
            case DialogButtons.PrimaryButton:
                PrimaryBtn.Classes.Add("AccentBorder");
                break;
            case DialogButtons.SecondaryButton:
                SecondaryBtn.Classes.Add("AccentBorder");
                break;
        }

        if (info.CloseButtonText != null)
        {
            CloseBtn.IsVisible = true;
            CloseBtn.Content = info.CloseButtonText;
        }

        if (info.PrimaryButtonText != null)
        {
            PrimaryBtn.IsVisible = true;
            PrimaryBtn.Content = info.PrimaryButtonText;
        }

        if (info.SecondaryButtonText != null)
        {
            SecondaryBtn.IsVisible = true;
            SecondaryBtn.Content = info.SecondaryButtonText;
        }

        if (info.CloseButtonText == null &&
            info.PrimaryButtonText == null &&
            info.SecondaryButtonText == null)
            BtnBorder.Height = 0;
    }

    private void CloseBtn_OnClick(object? sender, RoutedEventArgs e)
    {
        DialogHost.Close();
        _info.CloseAction?.Invoke();
    }

    private void PrimaryBtn_OnClick(object? sender, RoutedEventArgs e)
    {
        DialogHost.Close();
        _info.PrimaryAction?.Invoke();
    }

    private void SecondaryBtn_OnClick(object? sender, RoutedEventArgs e)
    {
        DialogHost.Close();
        _info.SecondaryAction?.Invoke();
    }
}