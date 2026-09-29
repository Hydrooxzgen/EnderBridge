# EnderBridge Manage Desktop (Android )App

基于 **.NET 10 + Avalonia UI 12** 构建的现代化跨平台桌面与移动端客户端。

## 🌟 特性概览

- **高保真亚克力毛玻璃界面**：深色现代暗黑主题，圆角微边框卡片 (`BorderCard`)，悬浮缓动动效。
- **跨平台多端覆盖**：
  - 🖥️ **Windows / Linux / macOS**：原生运行，支持一键在后台拉起、守护及优雅停止同级目录下的 `python main.py`，内置毫秒级实时彩色控制台。
  - 📱 **Android 移动端 (APK)**：轻量级随身控制台，自适应移动端布局，通过 REST API / WebSocket 随时随地连接管理服务器。
- **解耦防臃肿架构**：
  - PC 端不强制将 Python 与 Node.js 打包进二进制，原工程目录保持干净整洁；
  - Android 端仅约 15MB 轻巧 APK，秒开秒连，零发热长效连接。

---

## 🚀 快速开始

### 1. 运行桌面端 (Windows / Linux / macOS)

在项目根目录下或 `app/` 目录下执行：

```powershell
dotnet run --project app/src/EnderBridge.App.Desktop/EnderBridge.App.Desktop.csproj
```

或者编译成独立单文件：
```powershell
dotnet publish app/src/EnderBridge.App.Desktop/EnderBridge.App.Desktop.csproj -c Release -r win-x64 --self-contained false -p:PublishSingleFile=true -o app/bin/
```

### 2. 构建 Android APK (移动端)

需安装 .NET Android Workload (`dotnet workload install android`)：

```powershell
dotnet build app/src/EnderBridge.App.Android/EnderBridge.App.Android.csproj -c Release
```

生成的 APK 位于：
`app/src/EnderBridge.App.Android/bin/Release/net10.0-android/`

---

## 📁 目录架构

```
app/
├── EnderBridge.App.sln              # 解决方案
├── README.md                        # 本说明文档
└── src/
    ├── EnderBridge.App/             # 跨平台共享 UI 与业务逻辑层 (net10.0)
    │   ├── Styles/Theme.axaml       # 样式
    │   └── Views/
    │       ├── MainView.axaml (.cs) # 主界面与自适应交互控制器
    │       └── MainWindow.axaml     # 桌面端主窗口宿主
    ├── EnderBridge.App.Desktop/     # 桌面端运行入口 (net10.0)
    └── EnderBridge.App.Android/     # 安卓端运行入口 (net10.0-android)
```
