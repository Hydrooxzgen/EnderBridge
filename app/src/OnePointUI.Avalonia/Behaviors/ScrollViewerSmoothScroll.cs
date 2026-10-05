using System;
using Avalonia;
using Avalonia.Animation.Easings;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Threading;

namespace OnePointUI.Avalonia.Behaviors
{
    public static class ScrollViewerSmoothScroll
    {
        public static readonly AttachedProperty<bool> EnableSmoothScrollProperty =
            AvaloniaProperty.RegisterAttached<StyledElement, bool>(
                "EnableSmoothScroll",
                typeof(ScrollViewerSmoothScroll));

        private static readonly AttachedProperty<ScrollAnimationState?> AnimationStateProperty =
            AvaloniaProperty.RegisterAttached<StyledElement, ScrollAnimationState?>(
                "AnimationState",
                typeof(ScrollViewerSmoothScroll));

        static ScrollViewerSmoothScroll()
        {
            EnableSmoothScrollProperty.Changed.AddClassHandler<ScrollViewer>(OnEnableSmoothScrollChanged);
        }

        public static void SetEnableSmoothScroll(StyledElement element, bool value)
            => element.SetValue(EnableSmoothScrollProperty, value);

        public static bool GetEnableSmoothScroll(StyledElement element)
            => element.GetValue(EnableSmoothScrollProperty);

        private static void OnEnableSmoothScrollChanged(ScrollViewer sv, AvaloniaPropertyChangedEventArgs e)
        {
            if ((bool)e.NewValue!)
            {
                sv.AddHandler(InputElement.PointerWheelChangedEvent, OnPointerWheelChanged, RoutingStrategies.Tunnel);
                sv.DetachedFromVisualTree += OnDetachedFromVisualTree;
            }
            else
            {
                sv.RemoveHandler(InputElement.PointerWheelChangedEvent, OnPointerWheelChanged);
                sv.DetachedFromVisualTree -= OnDetachedFromVisualTree;
                var state = sv.GetValue(AnimationStateProperty);
                state?.Stop();
                sv.SetValue(AnimationStateProperty, null);
            }
        }

        private static void OnDetachedFromVisualTree(object? sender, VisualTreeAttachmentEventArgs e)
        {
            if (sender is ScrollViewer sv)
            {
                sv.RemoveHandler(InputElement.PointerWheelChangedEvent, OnPointerWheelChanged);
                sv.DetachedFromVisualTree -= OnDetachedFromVisualTree;
                var state = sv.GetValue(AnimationStateProperty);
                state?.Stop();
                sv.SetValue(AnimationStateProperty, null);
            }
        }

        private static void OnPointerWheelChanged(object? sender, RoutedEventArgs e)
        {
            var args = (PointerWheelEventArgs)e;
            if (args.Handled) return;
            var sv = (ScrollViewer)sender!;

            args.Handled = true;

            var delta = args.Delta;
            const double scrollAmount = 100;

            var offset = sv.Offset;
            var extent = sv.Extent;
            var viewport = sv.Viewport;
            var maxX = Math.Max(0, extent.Width - viewport.Width);
            var maxY = Math.Max(0, extent.Height - viewport.Height);
            var targetX = Math.Clamp(offset.X - delta.X * scrollAmount, 0, maxX);
            var targetY = Math.Clamp(offset.Y - delta.Y * scrollAmount, 0, maxY);
            var target = new Vector(targetX, targetY);

            var state = sv.GetValue(AnimationStateProperty);
            if (state == null)
            {
                state = new ScrollAnimationState(sv);
                sv.SetValue(AnimationStateProperty, state);
            }
            state.StartAnimation(target);
        }

        private class ScrollAnimationState
        {
            private readonly ScrollViewer _sv;
            private DispatcherTimer? _timer;
            private Vector _from;
            private Vector _to;
            private long _startTicks;
            private readonly long _durationTicks = TimeSpan.FromMilliseconds(300).Ticks;
            private readonly Easing _easing = new ExponentialEaseOut();

            public ScrollAnimationState(ScrollViewer sv)
            {
                _sv = sv;
            }

            public void StartAnimation(Vector target)
            {
                _from = _sv.Offset;
                _to = target;
                _startTicks = DateTime.Now.Ticks;

                if (_timer == null)
                {
                    _timer = new DispatcherTimer(TimeSpan.FromMilliseconds(16), DispatcherPriority.Render, OnTick);
                    _timer.Start();
                }
            }

            public void Stop()
            {
                _timer?.Stop();
                _timer = null;
            }

            private void OnTick(object? sender, EventArgs e)
            {
                var elapsedTicks = DateTime.Now.Ticks - _startTicks;
                if (elapsedTicks >= _durationTicks)
                {
                    _sv.Offset = _to;
                    _timer?.Stop();
                    _timer = null;
                    return;
                }

                var t = (double)elapsedTicks / _durationTicks;
                var easedT = _easing.Ease((float)t);
                _sv.Offset = _from + (_to - _from) * easedT;
            }
        }
    }
}
