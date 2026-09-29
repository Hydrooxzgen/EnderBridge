using Avalonia.Controls;
using Avalonia.Threading;
using OnePointUI.Avalonia.Base.Entry;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls.Dialog;

public partial class DialogHost : UserControl
{
    private static DialogHost? _host;
    private static readonly Queue<DialogInfo> _dialogQueue = new();
    private static bool _isShowingDialog;

    public DialogHost()
    {
        InitializeComponent();

        // 初始状态
        IsVisible = false;
        BackgroundGrid.Opacity = 0;
    }

    public static void Show(DialogInfo info)
    {
        if (_host == null)
            throw new NullReferenceException("必须初始化 DialogHost");

        Dispatcher.UIThread.Invoke(() =>
        {
            // 如果当前正在显示对话框，将新对话框加入队列
            if (_isShowingDialog)
            {
                _dialogQueue.Enqueue(info);
                return;
            }

            _isShowingDialog = true;

            if (!info.IsWindow)
            {
                _host.IsVisible = true;
                _host.BackgroundGrid.Opacity = 0.8;
                _host.DialogBox.Content = new DialogBorder(info);
            }
        });
    }

    public static async Task Close()
    {
        global::Avalonia.Threading.Dispatcher.UIThread.Invoke(async () =>
        {
            if (_host == null) return;

            // 淡出动画
            _host.DialogBox.Content = null;
            _host.BackgroundGrid.Opacity = 0;

            await Task.Delay(400); // 等待淡出动画完成

            _host.IsVisible = false;
            _isShowingDialog = false;

            // 检查队列中是否有下一个对话框
            if (_dialogQueue.Count > 0)
            {
                var nextInfo = _dialogQueue.Dequeue();
                Show(nextInfo);
            }
        });
    }

    public static void SetHost(DialogHost? host)
    {
        _host = host;
    }
}