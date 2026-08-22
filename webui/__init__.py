"""Web 管理界面模块

包含:
- server.py        Web 管理后端服务(HTTP 服务器 + REST API + 静态资源服务)
- index.html       前端入口页面(独立文件,不内嵌 Python 模板)
- static/          前端静态资源目录,可自由使用任意前端技术
  - css/style.css   样式表
  - js/app.js       前端逻辑(原生 JS,可按需替换为 Vue / React 等框架产物)

前端静态资源以独立文件存放,后端仅负责通过 /static/* 提供它们,
因此前端可以用任意语言/框架开发,无需修改 Python 代码。
"""
