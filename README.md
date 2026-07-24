# KylinBootLab

> 开放原子开源大赛 — openKylin 赛题第四题：操作系统启动性能分析与优化

## 作品简介

KylinBootLab 是一套 **Linux 桌面启动性能全链路分析、优化与验证系统**。系统以 openKylin 2.0 SP2 为主要目标平台，同时验证了 Ubuntu 22.04 LTS 和 Fedora 41 的跨发行版泛化能力。采用 **Windows 控制机 + Linux 目标机** 的双机闭环架构，覆盖从内核启动到桌面可用的完整时间线。

### 核心能力

| 能力 | 说明 |
|------|------|
| **不可变基线采集** | Rust 探针采集 systemd 启动时序数据，SHA-256 校验 + 四阶段验证管道入仓 |
| **自动化冷启动实验台** | VMware vmrun 电源控制 + ABBA 随机化实验协议 + 快照恢复，支持无人值守运行 |
| **语义就绪探测** | uinput 真实 PAM 登录注入 + journald 追踪 + AT-SPI 桌面语义检查 + 哨兵应用冷启动计时 |
| **因果图建模** | systemd DOT 依赖图解析 → 拓扑动态规划关键路径分析 O(V+E) → 瓶颈评分排名 |
| **优化验证器** | ABBA 配对块设计 + Bootstrap 百分位置信区间 + ACCEPTED/PROMISING/REJECTED 三级判定 |
| **LLM 辅助诊断** | Qwen2.5-Coder-7B 本地 CPU 推理，四角色流水线（追踪分析→源码调查→实验设计→安全评审） |
| **跨发行版适配** | `adapters/` 模块支持 openKylin / Ubuntu / Fedora 三发行版，含服务名映射和工具链差异适配 |

### 主要发现

- **kaiming D-Bus 竞态**：`org.kylin.kaiming.service`（blame 20.2s）的 `After=graphical.target` 约束是 openKylin 最大可移除瓶颈
- **组合优化效果**：kaiming 重排 + strongswan/biometric 掩码将冷启动底限从 9.5s 降至 7.3s（**-23%**），三项服务 blame 合计消除约 2.6s
- **跨发行版对比**：openKylin 28.3s、Ubuntu 42.4s、Fedora 9.7s，Fedora 得益于 dracut 精简 initramfs 和更新的 systemd（v256）
- **120+ 次冷启动实验**：ABBA 框架正确区分有效信号与测量噪声，组合优化达到 PROMISING 级别
- **Observation overhead < 1%**：通过自动化标定流程验证 observer 自身开销在竞赛允许范围内

### 跨发行版基线对比

| 发行版 | 内核 | initrd | 用户空间 | 总计 | 最大瓶颈 |
|--------|:----:|:------:|:--------:|:----:|---------|
| openKylin 2.0 SP2 | 4.73s | — | 23.58s | **28.31s** | kaiming.service |
| Ubuntu 22.04 LTS | 2.47s | — | 39.94s | **42.41s** | plymouth-quit-wait.service |
| Fedora 41 | 1.21s | 1.40s | 7.05s | **9.65s** | plymouth-quit-wait.service |

### ABBA 优化验证实验

| 候选方案 | 发行版 | 中位改善 | 95% CI | 判定 |
|---------|--------|:--------:|--------|:-----:|
| mask strongswan | Ubuntu 22.04 | 33ms (0.65%) | [-218, +66]ms | REJECTED |
| mask strongswan | Fedora 41 | 609ms (6.88%) | [-8429, +2932]ms | REJECTED |
| dracut initramfs 裁剪 | Fedora 41 | 2093ms (18.99%) | [-8180, -38]ms | REJECTED* |
| mask biometric | openKylin | — | — | REJECTED |
| socket NM-wait-online | openKylin | PROMISING | — | — |
| kaiming 重排 + 掩码组合 | openKylin | PROMISING (-23%) | — | — |

> \* Fedora dracut 裁剪在所有实验中改善幅度最大（2.1s / 19%），但受限于每组 8 次冷启动的小样本量，CI 跨零。增加样本量后有望达到 ACCEPTED。

## 系统架构

```
控制机 (Windows 10/11, Python 3.12)              目标机 (Linux, Rust 1.85)
┌──────────────────────────────────┐          ┌──────────────────────────────┐
│  kbl CLI (Typer, 11 子命令)      │  SSH/SCP │  kbl-bootprobe (Rust 探针)   │
│  ├─ collect / ingest / report    │ ───────→ │  ├─ snapshot 启动快照采集     │
│  ├─ experiment queue / run       │          │  ├─ observe  就绪度观测       │
│  ├─ analyze (因果图 + 瓶颈)      │  vmrun   │  └─ usable-probe 桌面可用性   │
│  ├─ optimize plan / run (ABBA)   │ ───────→ │                              │
│  ├─ calibrate (观测器开销标定)    │          │  systemd / journald / AT-SPI  │
│  └─ agent analyze (LLM 诊断)     │          │  uinput 虚拟键盘自动登录      │
│                                  │          │  D-Bus / proc 扫描            │
│  RunStore (4阶段 TOCTOU 安全导入) │          │                              │
│  CausalGraph (DAG + DP关键路径)   │          │  VMware 快照恢复 + 冷启动     │
│  ABBA Validator (Bootstrap CI)   │          │  ostree 部署回滚 (恢复层)     │
└──────────────────────────────────┘          └──────────────────────────────┘
```

## 运行说明

### 环境要求

| 组件 | 要求 |
|------|------|
| 控制机 | Windows 10/11，Python 3.12，Rust 1.85.1，Node.js 18+ |
| 目标机 | openKylin 2.0 SP2（VMware 虚拟机），SSH 免密登录，`kbl` 用户 |
| LLM（可选） | Ollama + Qwen2.5-Coder-7B-Instruct（Q4_K_M 量化，CPU 推理） |
| 虚拟化 | VMware Workstation 17.x，vmrun.exe 可用 |

### 安装工具链

```powershell
# Python 3.12 + uv 包管理器
winget install --id astral-sh.uv --exact
uv python install 3.12

# Rust 1.85.1
winget install --id Rustlang.Rustup --exact
rustup toolchain install 1.85.1 --profile minimal --component clippy,rustfmt

# Node.js（仪表板可选）
winget install OpenJS.NodeJS
```

### 克隆并构建

```powershell
git clone <仓库地址>
cd <项目目录>
uv sync --all-groups --python 3.12

# 可选：构建仪表板
cd dashboard && npm install && npm run build && cd ..
```

### 质量门禁

```powershell
uv run ruff check . && uv run mypy src tests && uv run pytest -q
cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
```

测试套件：Python 313 + Rust 54 = **367 tests**

### 目标机部署

Rust 探针需在目标 Linux 环境中编译（`x86_64-unknown-linux-gnu` 目标）。部署脚本位于 `scripts/target/`：

```bash
# 基础探针部署
sudo bash scripts/target/install_bootprobe.sh <binary> <username>

# Observer 部署（含自动登录注入 + 桌面可用性探测）
sudo bash scripts/target/install_observer.sh <binary> <username> <password>

# 对于 Ubuntu/Fedora（使用 GDM），安装后修改配置：
sudo sed -i 's/lightdm.service/gdm.service/' /etc/kylinbootlab/observe.toml
```

### 主要命令

```bash
kbl version                      # 打印包版本
kbl collect --target HOST        # 从目标机 SSH 采集启动快照
kbl ingest BUNDLE                # 验证并导入探针数据包
kbl report RUN_ID                # 生成基线 HTML/JSON 报告
kbl experiment queue/run         # 排队并执行无人值守冷启动实验
kbl calibrate                    # 观测器开销自动化标定
kbl optimize plan/run            # 优化候选方案排序 + ABBA 冷启动验证
kbl analyze RUN_ID [--dot-target HOST]  # 因果图瓶颈分析
kbl agent analyze/benchmark      # LLM 辅助诊断
kbl dashboard                    # 打开证据仪表板
```

### 复现关键实验

```powershell
# 1. 采集基线（需 VM 运行中）
uv run kbl collect --target kbl@<target-ip>

# 2. 生成报告
uv run kbl report <run-id>

# 3. 因果图 + 瓶颈分析
uv run kbl analyze <run-id> --dot-target kbl@<target-ip>

# 4. 优化候选方案评分
uv run kbl optimize plan <run-id>

# 5. ABBA 冷启动验证实验（18 次冷启动）
uv run kbl optimize run <plan-id> --target kbl@<target-ip> --vmx-path "<vmx路径>"

# 可用 plan-id: mask-strongswan, fedora-mask-strongswan, fedora-initramfs-trim,
#              mask-biometric, socket-nm-wait, parallelize-kylin,
#              phase6-kaiming-stagger, phase6-mitigations-off, phase6-initramfs-trim
```

## 项目结构

```
├── src/kylinbootlab/          # Python 控制端
│   ├── cli.py                 # CLI 入口（11 子命令）
│   ├── contracts.py           # Pydantic 数据契约（跨语言一致性）
│   ├── store.py               # 不可变 RunStore（4 阶段 TOCTOU 安全导入）
│   ├── remote.py              # SSH/SCP 远程采集传输
│   ├── systemd.py             # systemd-analyze 输出解析
│   ├── report.py              # 基线报告生成（Jinja2 模板）
│   ├── readiness.py           # 就绪事件解析 + T-point 推导
│   ├── calibrate.py           # 观测器开销自动化标定
│   ├── capture.py             # 命令采集加载与验证
│   ├── analysis/              # 因果图引擎（Phase 4）
│   │   ├── dot.py             # graphviz DOT 解析器
│   │   ├── graph.py           # 因果图数据模型
│   │   ├── builder.py         # 图构建器（DOT + blame + readiness 融合）
│   │   ├── critical_path.py   # 拓扑 DP 关键路径 O(V+E)
│   │   ├── bottleneck.py      # 瓶颈评分排名
│   │   ├── simulator.py       # What-If 仿真器
│   │   ├── compare.py         # 跨运行图对比
│   │   └── fault_corpus.py    # 故障注入语料库
│   ├── experiments/           # 冷启动实验编排（Phase 2）
│   │   ├── contracts.py       # ExperimentRecord 数据模型
│   │   ├── queue.py           # 追加式 JSONL 实验队列
│   │   ├── power.py           # 电源控制抽象（VixPower / WolPower）
│   │   ├── aliveness.py       # SSH 存活性检测 + observer 门控
│   │   ├── orchestrator.py    # 实验主循环（出队→上电→等待→采集→重复）
│   │   └── recovery.py        # 双层恢复（VMware 快照 → ostree 回滚）
│   ├── optimization/          # ABBA 优化验证（Phase 5-6）
│   │   ├── plan.py            # 10 个优化候选方案工厂函数
│   │   ├── planner.py         # 加权评分排序引擎
│   │   ├── scheduler.py       # ABBA 随机化块调度器
│   │   ├── executor.py        # SSH 远程配置执行器
│   │   ├── runner.py          # ABBA 实验运行器
│   │   └── validator.py       # Bootstrap CI + 三级判定门
│   ├── agent/                 # LLM 辅助诊断（Phase 8）
│   │   ├── backend.py         # Ollama HTTP API 后端
│   │   ├── controller.py      # 四角色流水线控制器
│   │   ├── models.py          # 结构化输出 Pydantic 模型
│   │   ├── skills.py          # TOML 技能加载 + JSON 输出验证
│   │   └── benchmark.py       # 结构性代理评分
│   └── schemas/               # JSON Schema 定义
├── target/bootprobe/          # Rust 目标机探针
│   └── src/
│       ├── main.rs            # CLI 入口（snapshot / observe / usable-probe）
│       ├── model.rs           # 跨语言数据契约（ProbeManifest 等）
│       ├── capture.rs         # 子进程执行 + 采集持久化
│       ├── system.rs          # 系统信息发现（/etc/os-release, CLOCK_BOOTTIME）
│       ├── snapshot.rs        # 快照编排
│       ├── events.rs          # ReadinessEvent v1 契约 + 跨语言 fixture
│       ├── observe/           # root 侧就绪观测器
│       │   ├── config.rs      # observe.toml 解析（ObserveConfig）
│       │   ├── state.rs       # 纯状态机（Signal → ReadinessEvent）
│       │   ├── journal.rs     # journald JSON 解析 + 跟随进程
│       │   ├── keymap.rs      # 字符→evdev 键码映射（[a-z0-9] 限定）
│       │   └── uinput.rs      # /dev/uinput 虚拟键盘（PAM 真实登录）
│       └── usable/            # 会话侧桌面可用性探测
│           ├── atspi.rs       # AT-SPI busctl 交互
│           └── procscan.rs    # /proc 扫描（进程组完整性检查）
├── adapters/                  # 跨发行版适配器
│   ├── distro.py              # 发行版识别 + 工具链路径
│   ├── desktop.py             # 桌面环境配置（LightDM/GDM/UKUI/GNOME）
│   └── services.py            # 服务名映射（openKylin ↔ Ubuntu ↔ Fedora）
├── scripts/target/            # 目标机部署脚本
│   ├── install_bootprobe.sh   # 探针安装器
│   ├── install_observer.sh    # 观测器一键部署
│   ├── kbl-observe.service    # systemd 单元
│   ├── kbl-usable-probe.desktop  # XDG 自动启动
│   ├── kbl-capture-run        # 特权受限 sudo 封装
│   ├── kbl-dot-capture.sh     # DOT 图采集脚本
│   ├── prepare_recovery.sh    # ostree 恢复基线
│   └── verify_foundation.sh   # 基础安装验证
├── tests/                     # Python 测试套件（313 tests）
├── dashboard/                 # React 证据仪表板（Vite + Recharts + Tailwind）
├── agent/skills/              # LLM 角色 TOML 技能定义（4 文件）
├── docs/evidence/             # 实验证据
│   └── cross-distro/          # 跨发行版基线 + ABBA 结果
├── pyproject.toml             # Python 项目配置
├── Cargo.toml                 # Rust workspace 配置
└── .gitignore
```

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| 控制端 | Python 3.12 · Pydantic 2 · Typer · Jinja2 · NumPy | CLI、分析管道、报告生成 |
| 目标机探针 | Rust 1.85 · serde · clap · input-linux · nix | 启动数据采集、就绪度观测 |
| 电源控制 | VMware vmrun / Wake-on-LAN + SSH | 虚拟机/物理机冷启动自动化 |
| LLM 后端 | Ollama + Qwen2.5-Coder-7B-Instruct (Q4_K_M, CPU) | 本地推理、四角色诊断 |
| 仪表板 | React 19 + Recharts 2 + Tailwind CSS 4 + Vite 8 | 交互式证据浏览器 |
| 测试 | pytest 8 + mypy strict + ruff / cargo test + clippy | 367 测试、零 lint 告警 |

## 设计亮点

### 1. 跨语言数据契约
Rust 探针和 Python 控制端共享相同的 JSON Schema（`probe-manifest-v1.schema.json`），并通过 Pydantic `extra="forbid"` 和 serde `deny_unknown_fields` 双重确保数据完整性。跨语言一致性由 `test_rust_contract.py` 自动验证——每次构建时 Rust fixture 与 Python 模型对比，byte-for-byte 完全相同。

### 2. 追加式不可变状态
实验队列（`ExperimentQueue`）采用追加式 JSONL 格式，每行是实验状态的完整快照。当前状态是最后一行——即使写入中途崩溃，最多丢失当前行，状态自然回退至上一行。RunStore 同样不可变，`ingest()` 使用四阶段 TOCTOU 安全管道（枚举→复制到暂存→从暂存验证→原子安装）。

### 3. uinput 真实 PAM 登录
Observer 不依赖自动登录捷径——它通过 `/dev/uinput` 创建虚拟键盘，在真实的 LightDM/GDM greeter 中输入密码，驱动完整的 PAM 认证流程。这就保证了"登录就绪"测量的真实性，与实际用户体验完全对齐。

### 4. ABBA 消除时间趋势
ABBA 随机化块设计（每块 A-B-B-A）消除线性时间趋势（如背景升温），配合 Bootstrap 百分位置信区间（10000 次重采样），提供严格的统计推断，**而非简单的均值比较**，防止将噪声误判为优化效果。

### 5. 纯逻辑与平台 I/O 分离（Rust 侧）
观测器状态机、键码映射、AT-SPI 输出解析均为纯函数，`#[cfg(test)]` 可在任何平台上单独测试。平台相关的 I/O（uinput、journalctl、busctl、/proc 扫描）通过 `#[cfg(target_os = "linux")]` 隔离运行。

## 许可证

Apache-2.0
