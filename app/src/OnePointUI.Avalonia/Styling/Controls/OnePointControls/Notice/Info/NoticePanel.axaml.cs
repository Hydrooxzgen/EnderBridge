using Avalonia.Controls;
using OnePointUI.Avalonia.Base.Entry;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls.Notice.Info;

public partial class NoticePanel : UserControl
{
    public static NoticePanel? InstancePanel;
    public static List<NoticeInfo> NoticeInfos = new();

    public NoticePanel()
    {
        InitializeComponent();

        InstancePanel = this;
    }

    public void AddNotice(NoticeInfo notice)
    {
        NoticeInfos.Add(notice);
        var noticeBox = new NoticeBox(notice);
        noticeBox.OnClose = box => NoticesPanel.Children.Remove(box);

        // 添加到开头
        NoticesPanel.Children.Insert(0, noticeBox);
        // NoticesPanel.Children.Add(noticeBox);

        // 如果超过5个，删除最后一个（带淡出动画）
        if (NoticesPanel.Children.Count > 5)
        {
            var oldestNotice = (NoticeBox)NoticesPanel.Children[NoticesPanel.Children.Count - 1];
            oldestNotice.CloseThis();
        }
    }
}