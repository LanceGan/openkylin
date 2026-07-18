# KylinBootLab Phase 3 设计方案：语义就绪探测与观测开销校准

- 日期：2026-07-18
- 状态：已批准（对话中逐节确认）
- 对应赛题：第四题 openKylin 操作系统启动性能分析与优化（"分析深度与方法创新性" 25 分核心）
- 前置阶段：Phase 1（基线采集）、Phase 2（自动化实验台）均已完成并通过真机验收

## 1. 目标与范围

Phase 3 让系统测量用户可感知的四个就绪时间点，并证明测量本身不扰动被测对象：

| 时间点 | 含义 |
|--------|------|
| `T0` | 内核单调时钟零点（已有，CLOCK_BOOTTIME） |
| `Tlogin-ready` | 图形登录界面可交互 |
| `Tsession` | 真实登录完成、用户会话开启 |
| `Tusable` | 桌面真实可用（组件齐 + 可枚举 + 哨兵应用可启动） |

**范围裁剪（已确认）**：本阶段 = 路线图 Phase 3 的 3A（语义就绪时间线）+ 3C（观测开销校准）。3B（ftrace/perf/libbpf CO-RE 深度内核追踪）延后为 Phase 4 前置工作——完成门槛不需要它。

完成门槛：四个 T 点可测量且单调递增；benchmark 模式对 `graphical_target_from_t0` 与 `os_total` 中位数的开销 < 1%。

## 2. 实地勘察结论（2026-07-18，openKylin 2.0 SP2 目标机）

| 设施 | 状态 | 设计影响 |
|------|------|---------|
| BTF `/sys/kernel/btf/vmlinux` | 有 | CO-RE 可行——留给 Phase 4，本阶段不用 |
| lightdm + ukui-greeter 4.10 | 确认 | greeter 日志带单调时间戳且极详细（`start begin!!` @6.713s）——journald 是主信号源 |
| `/dev/uinput` | 有，仅 root | 观测器以 root systemd 单元运行即原生可用，无需 udev 规则 |
| AT-SPI 2.52 | 已装 | 桌面语义探测可行；总线在用户会话 `/run/user/1000/at-spi/` → 强制双组件架构 |
| tracefs | 需 root | 与本阶段无关 |
| 无人值守时无图形登录 | 确认 | Tsession/Tusable 必须由系统自己发起真实登录 → uinput 注入 |

## 3. 关键决策（已确认）

1. **真实登录方式：uinput 键击注入**。观测器在 `Tlogin-ready` 判定后注入密码 + 回车，走真实 PAM + 真实会话启动。不用 autologin（有被评审认定规避的风险，且跳过 greeter 导致 Tlogin-ready 与 Tusable 无法同启动测量）。
2. **Tusable 判据：三条件全满足**。UKUI 核心进程组齐 + AT-SPI 能枚举桌面/面板对象 + 哨兵应用（终端）从 exec 到首个 AT-SPI 窗口对象出现。
3. **架构：扩展 kbl-bootprobe**，新增 `observe` 与 `usable-probe` 子命令，单二进制部署，复用 Phase 1 契约基建。

## 4. 架构

### 4.1 双组件观测器

AT-SPI 总线属于用户会话，root 服务访问困难 → 观测器拆两个组件，同一二进制：

```
目标机 openKylin
├── kbl-bootprobe observe        (root systemd 系统单元，启动早期拉起)
│   ├── 监听 journald（lightdm/greeter/PAM 事件流，__MONOTONIC_TIMESTAMP）
│   ├── 监测 systemd 单元状态（dbus / NetworkManager / lightdm）
│   ├── 判定 Tlogin-ready → uinput 注入密码 + 回车
│   ├── 捕获 Tsession（journald "session opened for user kbl"）
│   ├── 等待 usable-probe 结果文件 → 汇总 Tusable
│   └── 写 /var/lib/kylinbootlab/observe/current.jsonl + done 标记
│
└── kbl-bootprobe usable-probe   (XDG autostart，登录后在 kbl 会话内运行)
    ├── 记录会话侧启动时间戳
    ├── 轮询 UKUI 核心进程组（清单配置于 observe.toml；初始清单在部署时
    │   从真实图形会话勘察确定——勘察时无图形会话，进程名未能预先枚举）
    ├── AT-SPI 枚举桌面/面板对象
    ├── 启动哨兵应用（observe.toml 配置，默认 mate-terminal，部署时验证存在）
    │   → 等首个 AT-SPI 窗口对象
    └── 写结果文件（root 观测器收走）
```

### 4.2 Tlogin-ready 判定条件（全部满足）

- greeter 进程窗口就绪（ukui-greeter journald 信号）
- dbus / NetworkManager / lightdm 单元均 active
- uinput 注入通道自检通过（设备可打开、虚拟键盘已建）

对应 TASK_4.md "到达登录界面"的四项状态要求。

### 4.3 与 Phase 1/2 管道集成——零契约变更

- snapshot 默认采集清单新增一条：`name: "readiness-events"`，command `["cat", "/var/lib/kylinbootlab/observe/current.jsonl"]`，`required: false`
- 事件流作为普通 artifact 随 bundle 校验入仓，`ProbeManifest` schema 不变
- `required: false` → 未部署观测器的目标照常工作（向后兼容）
- 编排器新增 `wait_for_observer_done`（轮询 done 标记，与 `wait_for_boot_finished` 同模式），超时 **300 秒**（覆盖最坏情形链：greeter 90s + 注入 30s + usable 120s + 余量）
- **快速降级路径**：等待前先单次探测 `/var/lib/kylinbootlab/observe/` 目录是否存在——不存在即判定未部署观测器，跳过等待直接采集，实验不判失败；存在才进入 300s 等待

### 4.4 控制端

新模块 `src/kylinbootlab/readiness.py`：解析 readiness-events artifact → 派生四个 T 点与哨兵首窗耗时 → 扩展 `metrics.json` 与 baseline.html（新增"用户可感知就绪时间线"区块）。

### 4.5 权限模型（一次性设置）

观测器 root 单元原生访问 uinput/journald。安装脚本一次 sudo 完成：systemd 单元 + XDG autostart 桌面项 + `/etc/kylinbootlab/observe.toml`（root 0600，含登录密码；密码建议纯小写字母数字，规避键盘布局差异）。

## 5. ReadinessEvent 契约（v1）

JSONL 事件流，Rust/Python 1:1 对齐（延续 Phase 1 契约模式）：

```json
{"schema_version":1,"monotonic_ns":6713388000,"kind":"greeter_started","detail":"lightdm start begin","source":"journald"}
```

- `kind` 枚举：`observer_started / unit_active / greeter_started / greeter_ready / login_injected / session_opened / desktop_process_up / atspi_desktop_ready / sentinel_launched / sentinel_window_shown / usable / observer_timeout / error`
- `monotonic_ns`：统一 CLOCK_BOOTTIME 时间轴（journald `__MONOTONIC_TIMESTAMP` 与探针时钟同源）
- `source` 枚举：`journald / systemd / probe / atspi`
- 四个 T 点为**派生值**——控制端从事件流计算，原始事件不可变，指标可重算

## 6. benchmark / diagnostic 双模式

| | benchmark（默认） | diagnostic |
|---|---|---|
| 观测手段 | journald 游标监听 + 500ms 低频轮询 + AT-SPI 单次枚举 | 50ms 密集轮询 + 进程树快照 + 每事件 journal 上下文 |
| 事件量 | ~15 条/启动 | 数百条 |
| 用途 | 正式 A/B 计时 | 根因分析（喂 Phase 4） |

模式写入 `observer_started` 事件的 `detail`；控制端报告标注模式，防止 diagnostic 数据混入正式统计。

v1 实现仅差轮询间隔；进程树快照与每事件 journal 上下文随 Phase 4 前置(3B)交付。

## 7. 观测开销校准协议（3C）

复用 Phase 2 实验台，三组对照（experiment profile 区分：`bare / benchmark / diagnostic`）：

1. **bare**：观测器单元 disabled，10 次冷启动（systemd-analyze 指标仍可采）
2. **benchmark**：观测器启用 benchmark 模式，10 次
3. **diagnostic**：观测器启用 diagnostic 模式，10 次（仅记录，不设门槛）

达标判据：benchmark 组相对 bare 组，`graphical_target_from_t0_ns` 与 `os_total_ns` 的**中位数差值 < 1%**。

新增 `kbl calibrate` 命令：自动排队三组实验、调度执行、汇总输出校准报告。

## 8. 错误处理

| 失败模式 | 处理 |
|---------|------|
| greeter 90s 未就绪 | 事件流写 `observer_timeout` 后退出；bundle 照常回传，控制端指标标 `incomplete` |
| 注入后 30s 无 session_opened | 写 `error`（密码错/布局问题），**不重试注入**（防锁定），超时退出 |
| usable-probe 崩溃/未启动 | root 侧 session_opened 后等 120s 无结果 → `observer_timeout`；Tsession 前时间线仍有效 |
| AT-SPI 不可达 | usable-probe 降级为纯进程组信号，事件 `detail` 注明 `atspi_unavailable` |
| 观测器崩溃 | 单元 `Restart=no`（重启污染时间线）；done 缺失 → 编排器超时路径接管 |

## 9. 测试策略

| 层 | 内容 |
|---|---|
| Rust 单元 | 事件序列化往返；journald 行解析（真实 openKylin 日志 fixture）；uinput 键码映射；T 点判据状态机 |
| Python 单元 | ReadinessEvent 解析；T 点派生（含 incomplete/降级）；报告渲染确定性 |
| 跨语言契约 | Rust 事件流样本过 Python 校验（复用 test_rust_contract 模式） |
| 真机验收 | ① 全链路：冷启动→自动登录→四点全出且单调递增；② 三组×10 次校准跑完、benchmark <1%；③ 错误密码→优雅超时、诊断事件完整 |

## 10. 明确不做（YAGNI）

- ftrace / perf / libbpf CO-RE（→ Phase 4 前置）
- 多用户、多显卡、Wayland 适配（SP2 默认 X11 单用户）
- 终端之外的更多哨兵应用（→ Phase 10 功能回归矩阵）
- 键盘布局全覆盖（约定测试密码为纯小写字母数字）

## 11. 与后续阶段的接口

- 事件流 JSONL 是 Phase 4 因果图的直接输入（diagnostic 模式提供密集事件）
- `Tlogin-ready / Tusable` 是 Phase 5 优化验证器的主指标
- 校准协议（bare/benchmark 对照法）在 Phase 10 正式 30×30 基准中复用
