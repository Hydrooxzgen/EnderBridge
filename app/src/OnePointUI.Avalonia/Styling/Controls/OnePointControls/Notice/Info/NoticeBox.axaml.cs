using Avalonia;
using Avalonia.Animation;
using Avalonia.Animation.Easings;
using Avalonia.Controls;
using Avalonia.Styling;
using Avalonia.Threading;
using OnePointUI.Avalonia.Base.Entry;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls.Notice.Info;

public partial class NoticeBox : UserControl
{
    public NoticeBox(NoticeInfo noticeInfo)
    {
        InitializeComponent();

        NoticeTitle.Text = noticeInfo.Title;
        NoticeContent.Text = noticeInfo.Message;

        // 使用DispatcherTimer替代Thread.Sleep
        var closeTimer = new DispatcherTimer();
        closeTimer.Interval = TimeSpan.FromMilliseconds(4500);
        closeTimer.Tick += (s, e) =>
        {
            closeTimer.Stop();
            CloseThis();
        };
        closeTimer.Start();
    }

    public Action<NoticeBox> OnClose { get; set; } = null!;

    public async void CloseThis()
    {
        // 创建动画（总时长800ms）
        var animation = new Animation
        {
            Duration = TimeSpan.FromMilliseconds(800),
            Easing = new ExponentialEaseOut(),
            Children =
            {
                new KeyFrame
                {
                    Cue = new Cue(0),
                    Setters =
                    {
                        new Setter(MarginProperty, new Thickness(15, 5))
                    }
                },
                new KeyFrame
                {
                    Cue = new Cue(1),
                    Setters =
                    {
                        new Setter(MarginProperty, new Thickness(220, 5, -220, 5))
                    }
                }
            }
        };

        animation.RunAsync(PATH_Border);
        await Task.Delay(600);

        OnClose?.Invoke(this);
    }
}