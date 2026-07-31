# MB CF Optimizer

一个只做一件事的 Windows 本地工具：从当前网络环境中筛选稳定、快速的 Cloudflare IP。

## 工作方式

1. 使用官方 [XIU2/CloudflareSpeedTest](https://github.com/XIU2/CloudflareSpeedTest) 做第一轮广泛筛选。
2. 选取速度较好的前 10 个候选地址。
3. 对候选地址连续复测 3 轮。
4. 按多轮成功率、丢包率、下载速度中位数、延迟中位数和延迟波动排序。
5. 给出一个首选和最多三个备用地址。

测速结果只保存在当前界面中，可按需导出 CSV。程序不上传结果，也不修改系统或代理配置。

## 使用

从仓库的 [Releases](https://github.com/BBMCoin04/mb-optimizer/releases) 下载 `MB-CF-Optimizer-windows-x64.exe` 并直接运行。

首次开始优选时，程序会从官方 GitHub Release 下载固定版本的 CFST 引擎。当前固定版本为 `v2.3.5`，下载后会验证上游公布的 SHA-256；校验失败时不会执行。

默认设置适合大多数 Cloudflare HTTPS 场景：

- IPv4
- 端口 `443`
- 延迟上限 `300 ms`
- 丢包上限 `20%`
- 10 个候选、3 轮复测

测速地址决定下载测速的实际目标。需要评估自己的 Cloudflare 业务时，应换成由对应 CDN 提供、可直接下载且足够大的 HTTPS 文件。

## 自定义候选

“候选 IP”旁的文件按钮可选择文本文件。每行填写一个 IP 或 CIDR，例如：

```text
104.16.0.0/13
172.64.0.0/13
2606:4700::/32
```

## 应用更新

“检查更新”按钮读取本仓库最新 GitHub Release。正式打包版本会：

1. 下载 `MB-CF-Optimizer-windows-x64.exe`；
2. 下载配套 `.sha256` 文件并校验；
3. 退出当前程序；
4. 替换原 EXE 并自动重启。

源码运行模式不会覆盖开发目录，只会打开 Release 页面。

## 本地开发

要求 Python 3.11 或更高版本。Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python app.py
```

运行测试：

```powershell
pytest
```

生成单文件 EXE：

```powershell
.\scripts\build_windows.ps1
```

输出文件位于 `dist/MB-CF-Optimizer-windows-x64.exe`。

## 发布

推送与项目版本一致的标签会触发 GitHub Actions，例如：

```powershell
git tag v0.1.0
git push origin v0.1.0
```

工作流会先运行测试，再构建 Windows x64 EXE，生成 SHA-256，并将两个文件附加到对应 GitHub Release。应用内更新依赖这两个固定文件名。

## 数据目录

程序数据位于：

```text
%LOCALAPPDATA%\MB-CF-Optimizer\
├─ engine\
└─ updates\
```

删除该目录可清理已下载的 CFST 引擎和更新缓存。

## 许可

本项目使用 MIT License。CFST 是独立下载和执行的第三方 GPL-3.0 程序，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
