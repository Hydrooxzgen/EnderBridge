# 贡献指南 / Contributing Guide

感谢你对 EnderBridge 的关注！本文档将帮助你快速上手开发。

Thank you for your interest in EnderBridge! This guide will help you get started.

---

## 快速开始 / Getting Started

### 环境要求 / Prerequisites

- **Python 3.12+**（代码使用了 PEP 701 嵌套 f-string 等 3.12 语法）
- **Node.js 20+**（Bot 假人功能需要）
- **Git**

### 克隆与安装 / Clone & Install

```bash
git clone https://github.com/Hydrooxzgen/EnderBridge.git
cd EnderBridge

# 创建虚拟环境（推荐）
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 安装 Python 依赖
pip install -r requirements.txt

# Bot 假人功能的 Node.js 依赖（可选）
cd mod/bot && npm install && cd ../..
```

### 启动 / Run

```bash
python main.py
```

首次运行会启动配置向导（浏览器访问 `http://127.0.0.1:18888`），完成后自动生成 `config.py`。

---

## 项目结构 / Project Structure

```
EnderBridge/
├── main.py              # 入口：连接 MCBE 服务器、加载 Mod
├── config.example.py    # 配置模板（首次运行时自动生成 config.py）
├── setup.py             # 依赖安装器（空包主机用）
├── requirements.txt     # Python 依赖清单
├── permission.json      # 权限配置（gitignore）
│
├── lib/                 # 核心库
│   ├── command.py       #   命令注册与分发框架
│   ├── mods.py          #   Mod 加载器（Client/Server ModManager）
│   ├── permission.py    #   权限管理
│   ├── sapi.py          #   WebSocket 通信协议
│   ├── shared.py        #   全局状态（Current）
│   ├── utils.py         #   ClientConnection 等工具类
│   └── setup.py         #   MOD_REGISTRY 定义与配置生成
│
├── mod/                 # 内置 Mod
│   ├── ezmatic/         #   建筑投影导入（.litematic → MCBE）
│   ├── image/           #   图片转方块
│   ├── music/           #   MIDI 音乐播放
│   ├── tool/            #   通用工具命令
│   ├── position/        #   坐标管理
│   ├── permission/      #   权限命令
│   ├── mcfunc/          #   MC 函数执行
│   ├── morews/          #   WebSocket 扩展
│   ├── read.py          #   聊天/终端读取（服务端）
│   ├── ai.py            #   AI 对话
│   └── bot/             #   假人 Bot（Python + Node.js）
│
├── resources/           # 用户资源目录（gitignore，保留 .gitkeep）
│   ├── ezmatic/         #   .litematic 投影文件放这里
│   ├── mcfunc/          #   MC 函数脚本
│   ├── midi/            #   MIDI 音乐文件
│   └── pictures/        #   图片文件
│
├── webui/               # Web 管理界面
│   ├── server.py        #   Flask 后端
│   └── static/          #   前端资源
│
├── structures/          # ezmatic 导出的 .mcstructure 文件
├── wiki/                # 项目文档
└── logs/                # 运行日志（gitignore）
```

---

## 开发规范 / Development Guidelines

### 代码风格 / Code Style

- **Python 最低版本 3.12**，可自由使用 `match/case`、嵌套 f-string（PEP 701）等新语法
- 缩进使用 **4 空格**，行宽不限
- 字符串优先使用 **f-string**
- 异步函数优先使用 `async/await`，避免 `asyncio.run()` 嵌套
- 中文注释和文档字符串（与项目风格一致）

### 命令注册 / Command Registration

所有内置 Mod 使用**单入口命令模式**：

```python
def onCommand(self):
    return {
        "op": [
            Command.create("ezmatic", "Ezmatic 建筑投影命令（方法: create/preview/...）")
                .add_string("方法", False)
                .add_optional_string("参数1")
                .set_func(self._cmd_ezmatic),
        ],
    }
```

- 入口注册在最低权限等级
- dispatcher 内做 per-method 权限检查
- 方法表为 4 元组：`(方法名, 参数描述, 说明, 所需权限等级)`

### 类型注解 / Type Annotations

- `__init__` 参数和实例属性**必须加类型注解**（Pylance 会推断 Optional 导致大量误报）
- 销毁标记（如 `self.client = None`）加 `# type: ignore[assignment]`
- 使用 `from __future__ import annotations` 或字符串注解避免循环导入

### Pylance 检查 / Pylance Check

编辑 `.py` 文件后确认 Pylance **0 个 Error 级别报错**（Warning 可忽略）。项目根目录有 `pyrightconfig.json`。

---

## 提交 PR / Submitting a Pull Request

### 流程 / Workflow

1. **Fork** 本仓库
2. 从 `main` 创建你的分支：`git checkout -b feat/my-feature`
3. 提交改动并推送
4. 在 GitHub 上创建 **Pull Request**（目标：`main`）

### Commit 规范 / Commit Convention

使用 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

```
<type>: <description>
```

常用 type：
| Type | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | 修复 Bug |
| `docs` | 文档变更 |
| `chore` | 构建/工具/依赖变更 |
| `refactor` | 重构（不改变功能） |

示例：
```
feat: ezmatic 支持批量导入
fix: bot 断线重连逻辑修复
docs: 更新 README 安装说明
```

### CI 检查 / CI Checks

推送后 GitHub Actions 会自动运行以下检查：

| Job | 内容 |
|-----|------|
| **python-check** | `python -m compileall` 编译检查 + `import main` 导入检查 |
| **node-check** | Bot 补丁脚本语法检查 |
| **yaml-check** | Issue 模板 YAML 语法检查 |

本地可手动运行验证：

```bash
# 编译检查
python -m compileall -q . -x "useful|\.git|resources|structures|wiki|logs|__pycache__"

# 导入检查（注意：会读 config.py，首次运行前需确保 config.py 存在）
python -c "import main"
```

### 注意事项 / Important Notes

- **不要修改 `H:\Projects\EnderBridge_useful`**（维护者的个人使用目录）
- `permission.json` 和 `config.py` 在 `.gitignore` 中，不要提交
- 新增 Mod 需要在 `lib/setup.py` 的 `MOD_REGISTRY` 中注册
- 新增资源目录需在 `config.example.py` 的 `basePath` 中声明

---

## 报告 Bug / Reporting Bugs

请使用 [Bug Report 模板](https://github.com/Hydrooxzgen/EnderBridge/issues/new?template=bug_report.yml)提交，包含：

- 运行环境（Python 版本、操作系统、MCBE 版本）
- 复现步骤
- 期望行为 vs 实际行为
- 日志输出（如有）

---

## 请求功能 / Requesting Features

请使用 [Feature Request 模板](https://github.com/Hydrooxzgen/EnderBridge/issues/new?template=feature_request.yml)提交。

---

## 行为准则 / Code of Conduct

本项目遵循 [Contributor Covenant 2.1](CODE_OF_CONDUCT.md) 行为准则。

---

## 许可证 / License

本项目采用 [GPL-3.0](LICENSE) 许可证。提交贡献即表示你同意你的代码以相同许可证发布。
