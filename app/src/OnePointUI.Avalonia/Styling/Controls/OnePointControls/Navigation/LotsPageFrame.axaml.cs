using Avalonia.Controls;
using Avalonia.Interactivity;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls.Navigation;

public partial class LotsPageFrame : UserControl
{
    public LotsPageFrame()
    {
        InitializeComponent();
    }

    public int TotalPage { get; set; }
    public int CurrentPage { get; set; }
    public Action UpAction { get; set; }
    public Action DownAction { get; set; }

    public void Update(object page, int max, int thisPage)
    {
        TotalPage = max;
        CurrentPage = thisPage;
        LeftBtn.IsEnabled = true;
        RightBtn.IsEnabled = true;

        CountText.Text = $"{thisPage} / {TotalPage}";
        if (thisPage == max) RightBtn.IsEnabled = false;

        if (thisPage == 1) LeftBtn.IsEnabled = false;

        NavigationFrame.NavigateTo(page);
    }

    public void CleanPage()
    {
        NavigationFrame.NavigateTo("");
    }

    private void LeftBtn_OnClick(object? sender, RoutedEventArgs e)
    {
        UpAction?.Invoke();
    }

    private void RightBtn_OnClick(object? sender, RoutedEventArgs e)
    {
        DownAction?.Invoke();
    }
}