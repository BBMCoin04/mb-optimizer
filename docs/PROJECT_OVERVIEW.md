# MB CF Optimizer 项目结构与演进状态

文档版本：0.2.0

更新日期：2026-07-31

## 一、项目目标

MB CF Optimizer 是一个 Windows 本地 Cloudflare IP 优选工具，只负责从当前网络环境中选出少量稳定、快速的 IP。

不负责：

- 修改代理客户端配置
- 上传测试结果
- 自动操作 VPS 或 Cloudflare 账户
- 使用不透明的第三方测速 EXE
- 默认引入来源不明的反代 IP

## 二、整体结构

```text
mb-optimizer/
├─ app.py                         程序入口
├─ pyproject.toml                 项目版本、依赖和打包元数据
├─ scripts/
│  └─ build_windows.ps1           Windows 单文件 EXE 构建脚本
├─ src/mb_optimizer/
│  ├─ app.py                      Qt 应用初始化、字体和图标
│  ├─ gui.py                      单窗口界面、线程、表格、日志和更新交互
│  ├─ models.py                   测速输入、单轮结果和聚合结果模型
│  ├─ optimizer.py                一键优选流程编排
│  ├─ runner.py                   CFST 子进程、停止、超时和实时进度解析
│  ├─ parser.py                   result.csv 编码与字段兼容解析
│  ├─ ranking.py                  多轮成功率、中位数和波动排序
│  ├─ engine.py                   CFST 下载、SHA-256 校验和本地缓存
│  ├─ endpoints.py                测速地址预设、预检和备用切换
│  ├─ ip_source.py                官方 IP 更新、缓存回退和限量抽样
│  ├─ updater.py                  GitHub Release 应用自更新
│  ├─ paths.py                    本地数据与资源路径
│  └─ resources/
│     ├─ app.png                  窗口与任务栏图标
│     └─ app.ico                  Windows 多尺寸 EXE 图标
├─ tests/                         解析、排序、流程、更新和回退测试
├─ .github/workflows/build.yml    Windows 自动测试、构建和发布
├─ CHANGELOG.md                   版本变更
├─ LICENSE                        本项目 MIT 许可
└─ THIRD_PARTY_NOTICES.md         CFST 第三方许可说明
```

## 三、0.2.0 完整链路

```text
用户点击开始
      ↓
确保 CFST v2.3.5 已安装且哈希正确
      ↓
以最多 64 KB 读取验证测速地址
首选失败 → 尝试备用地址
      ↓
获取 Cloudflare 官方 IP 段
官方更新失败 → 缓存 → 内置列表
      ↓
从 CIDR 抽取 800 个精确 IP
      ↓
第一轮只做延迟和丢包测试
      ↓
取前 10 个做下载测速
      ↓
按速度、丢包、延迟取前 3 个
      ↓
前 3 个额外复测 2 轮
      ↓
按稳定性和中位数排序
      ↓
输出 1 个首选和最多 2 个备用
```

## 四、稳定性设计

### 1. 测速引擎

- 只从 XIU2/CloudflareSpeedTest 官方 GitHub Release 下载。
- 固定版本和官方 SHA-256。
- 已安装引擎每次使用前校验 EXE 哈希。
- GitHub 临时不可访问时，已安装引擎仍可继续使用。

### 2. 官方 IP 段

- 首选 Cloudflare 官方 `ips-v4` / `ips-v6` 地址。
- 缓存有效期 7 天，避免每次启动依赖远程服务。
- 更新失败不覆盖旧缓存。
- 没有缓存时回退到 CFST 自带列表。
- 下载内容会进行大小、编码、CIDR 和 IP 版本校验。

### 3. 测速地址

- 默认使用 Cloudflare 镜像站稳定大文件。
- 备用使用 Cloudflare 官方 Speed Test 下载端点。
- 允许用户填写自己的 Cloudflare CDN 大文件。
- 预检只读取 64 KB，避免误下载完整镜像。
- 不再使用已返回 HTTP 403 的 `cf.xiu2.xyz/url` 作为默认值。

### 4. 任务控制

- CFST 始终作为独立子进程运行。
- 不使用 `shell=True`。
- 停止时终止完整进程树。
- 每个任务使用独立临时目录。
- 单个 CFST 阶段最长 15 分钟，超时自动终止。

## 五、排序原则

最终排序顺序：

```text
多轮成功率降序
丢包率中位数升序
下载速度中位数降序
延迟中位数升序
延迟绝对偏差中位数升序
```

不采用难以解释的黑盒综合分数。

## 六、版本演进

### 0.1.0：首个可运行版本

完成：

- PySide6 单窗口界面
- CFST 自动下载和校验
- IPv4/IPv6、自定义候选文件
- 三轮复测、排序、复制和 CSV
- GitHub Release 自更新
- Windows 自动构建

实机测试发现：

- 原默认测速地址返回 HTTP 403
- 直接扫描约 5955 个地址耗时长
- 进度输出使用回车刷新，界面看起来卡死
- 固定高度日志无法查看大量输出
- 下载复测数量过多，可能消耗数 GB 流量
- 透明代理会产生低于 2 ms 的虚假延迟

### 0.2.0：稳定数据源与可观察性版本

已实现：

- 稳定测速地址预设和自动备用
- Cloudflare 官方 IP 自动更新
- 7 天缓存、过期缓存和内置三级回退
- 限量 800 地址延迟广筛
- 10 个下载短名单、3 个最终复测地址
- CFST 回车进度实时解析
- 主进度条、当前数量、可用数量和已用时间
- 可拖动及放大的日志区域
- 柔和浅色背景
- MB Deer LOGO 窗口、任务栏和 EXE 图标
- 透明代理异常延迟提示

## 七、当前状态

| 项目 | 状态 |
| --- | --- |
| Python 核心单元测试 | 已覆盖 |
| CSV 解析和排序 | 已验证 |
| 官方 IP 缓存回退 | 已验证 |
| 测速地址备用切换 | 已验证 |
| CFST 实时进度解析 | 已验证 |
| Windows 自动构建 | 由 GitHub Actions 验证 |
| Windows 直连真实测速 | 需要 0.2.0 用户实机复测 |
| 打包 EXE 图标 | 需要 Windows 构建后目视确认 |
| 应用自更新 | 需要创建正式 Release 后端到端验证 |

## 八、后续可选演进

优先级较高：

- 根据实机结果校准 800/10/3 的默认数量
- 增加快速与标准扫描，但保持默认一键使用
- 对测速地址记录最近一次成功时间
- 在界面显示当前使用的是官方列表、缓存还是内置回退

暂不计划：

- 自动修改 Mihomo 或 sing-box 配置
- 上传 GitHub、Cloudflare 或第三方面板
- 默认使用第三方反代 IP 列表
- 后台定时扫描
- 公网 Web 管理界面
