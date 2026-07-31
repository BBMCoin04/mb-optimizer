# MB CF Optimizer

一个专注于本地 Cloudflare IP 优选的 Windows 桌面工具。

程序使用官方 [XIU2/CloudflareSpeedTest](https://github.com/XIU2/CloudflareSpeedTest) 作为独立测速引擎，不上传结果，也不修改系统或代理配置。

## 当前流程

1. 首次运行时下载并校验固定版本的 CFST 引擎。
2. 每 7 天尝试从 Cloudflare 官方地址更新 IPv4/IPv6 网段。
3. 更新失败时使用上次缓存；没有缓存时使用 CFST 内置列表。
4. 从网段中随机抽取 800 个精确 IP，只做延迟广筛。
5. 让延迟与丢包较好的前 10 个进入下载测速。
6. 选出前 3 个，再复测 2 轮。
7. 按成功率、丢包、速度中位数、延迟中位数和波动排序。

相较于 0.1.0，这个流程避免对数千地址直接下载测速，明显缩短耗时并减少流量。

## 下载和运行

从仓库的 [Releases](https://github.com/BBMCoin04/mb-optimizer/releases) 下载：

```text
MB-CF-Optimizer-windows-x64.exe
```

直接运行即可。首次点击“开始优选”需要联网下载 CFST `v2.3.5`，程序会验证上游公布的 SHA-256。

## 默认配置

- IPv4
- 端口 `443`
- 延迟上限 `1000 ms`
- 丢包上限 `100%`，用于宽松广筛
- 广筛候选 `800`
- 下载短名单 `10`
- 最终复测 `3`
- 额外复测 `2` 轮

广筛宽松不代表最终结果宽松。下载失败和多轮不稳定的地址会在后续阶段被淘汰。

## 测速地址

测速地址使用可编辑下拉框，当前预设：

```text
Cloudflare 镜像（推荐）
https://cloudflaremirrors.com/archlinux/iso/latest/archlinux-x86_64.iso

Cloudflare 官方测速
https://speed.cloudflare.com/__down?bytes=250000000
```

程序开始前会以最多 64 KB 的流式读取验证地址，不会在预检时下载完整文件。首选地址失败时会尝试备用地址；所有地址失败时给出明确错误。

## 官方 IP 更新与回退

优先来源：

```text
https://www.cloudflare.com/ips-v4/
https://www.cloudflare.com/ips-v6/
```

回退顺序：

```text
Cloudflare 官方地址
        ↓
7 天内的本地缓存
        ↓
过期但格式有效的本地缓存
        ↓
CFST 安装包内置列表
```

缓存位置：

```text
%LOCALAPPDATA%\MB-CF-Optimizer\ip-lists\
```

第三方反代 IP 不会作为默认候选。可通过候选 IP 文件按钮自行导入 IP 或 CIDR 文本。

## 网络要求

优选时应让测速电脑直连网络。OpenClash、PassWall、Mihomo TUN 等透明代理可能在局域网内接管 TCP 连接，产生异常低延迟和无效结果。

若延迟中位数低于 `5 ms`，程序会在日志中提示可能存在透明代理。

## 本地源码运行

推荐 Python 3.12，也支持项目依赖可安装的 Python 3.11 以上版本。

```powershell
cd D:\Projects\Code\mb-optimizer
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe app.py
```

需要测试和打包工具时：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\scripts\build_windows.ps1
```

## 应用更新

“检查更新”读取本仓库最新 GitHub Release。正式打包版会：

1. 下载新的 Windows EXE；
2. 下载配套 `.sha256`；
3. 校验文件；
4. 退出当前程序；
5. 替换原 EXE 并自动重启。

源码运行模式只会打开 Release 页面，不会覆盖开发目录。

## 项目说明

完整结构、模块职责、稳定性设计和版本演进记录见：

[docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md)

## 许可

本项目使用 MIT License。CFST 是独立下载和执行的第三方 GPL-3.0 程序，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
