# KylinBootLab

> 开放原子开源大赛 — openKylin 赛题第四题：操作系统启动性能分析与优化

## 作品简介

KylinBootLab 是一套 Linux 桌面启动性能全链路分析、优化与验证系统。系统以 openKylin 2.0 SP2 为主平台，
采用 Windows 控制机 + openKylin 目标机的双机闭环架构，覆盖从内核启动到 UKUI 桌面可用的完整时间线。

### 核心能力

| 能力 | 说明 |
|------|------|
| **不可变基线采集** | Rust 探针采集 systemd 时序数据，SHA-256 校验 + 4 阶段验证管道入仓 |
| **自动化冷启动实验台** | VMware vmrun 电源控制 + ABBA 随机化实验协议 + 快照恢复 |
| **语义就绪探测** | uinput 真实 PAM 登录 + AT-SPI 桌面语义检查 + 哨兵应用冷启动计时 |
| **因果图建模** | 333 节点/1651 边 systemd 依赖 DAG → 拓扑 DP 关键路径分析 + 瓶颈排名 |
| **优化验证器** | ABBA 配对块设计 + bootstrap 置信区间 + ACCEPTED/PROMISING/REJECTED 三级判定 |
| **BootAgent LLM 诊断** | Qwen2.5-Coder-7B 本地 CPU 推理，四角色 prompt 流水线 |

### 主要发现

- **kaiming D-Bus 竞态**：`org.kylin.kaiming.service`（1.4s blame）的 `After=graphical.target` 约束是最大可移除瓶颈
- **组合优化**：kaiming 重排 + strongswan/biometric 掩码将冷启动底限从 9.5s 降至 7.3s（-23%），三项服务 blame 合计消除 ~2.6s
- **120+ 次冷启动实验**：ABBA 框架正确区分有效信号与测量噪声，组合优化达到 PROMISING 级别

### 技术栈

| 层级 | 技术 |
|------|------|
| 控制端 | Python 3.12 · Pydantic 2 · Typer · Jinja2 · numpy |
| 目标机探针 | Rust 1.85 · serde · clap · input-linux |
| LLM 后端 | Ollama + Qwen2.5-Coder-7B-Instruct (Q4_K_M, CPU) |
| 仪表板 | React 18 + Recharts 2 + Tailwind CSS 4 + Vite |

### 项目结构

```
├── src/kylinbootlab/          # Python 控制端（分析、存储、CLI）
│   ├── cli.py                 # 11 个子命令
│   ├── contracts.py           # Pydantic 数据契约
│   ├── store.py               # 不可变 RunStore
│   ├── analysis/              # 因果图 + 模拟器
│   ├── experiments/           # 实验编排 + 电源控制
│   ├── optimization/          # ABBA 规划器 + 验证器
│   └── agent/                 # BootAgent LLM 诊断
├── target/bootprobe/          # Rust 目标机探针
│   └── src/
│       ├── main.rs            # CLI（snapshot, observe, usable-probe）
│       ├── observe/           # root 侧启动就绪观测器
│       └── usable/            # 会话侧桌面可用探测器
├── tests/                     # Python 测试套件（300+ 测试）
├── dashboard/                 # 交互式证据仪表板（React SPA）
├── agent/skills/              # BootAgent 四角色 TOML 配置
├── adapters/                  # 跨发行版适配器（openKylin/Ubuntu/Fedora）
└── scripts/target/            # 目标机部署脚本
```

## 运行说明

### 环境要求

- **控制机**：Windows 10/11，Python 3.12，Rust 1.85.1，Node.js 18+
- **目标机**：openKylin 2.0 SP2（VMware 虚拟机），SSH 免密登录
- **LLM（可选）**：Ollama + Qwen2.5-Coder-7B-Instruct

### 安装工具链

```powershell
# Python 3.12 + uv 包管理器
winget install --id astral-sh.uv --exact
uv python install 3.12

# Rust 1.85.1
winget install --id Rustlang.Rustup --exact
rustup toolchain install 1.85.1 --profile minimal --component clippy,rustfmt

# Node.js（仪表板需要）
winget install OpenJS.NodeJS
```

### 克隆并构建

```powershell
git clone <仓库地址>
cd <项目目录>
uv sync --all-groups --python 3.12

# 构建仪表板
cd dashboard && npm install && npm run build && cd ..
```

### 运行质量门禁

```powershell
uv run ruff check . && uv run mypy src tests && uv run pytest -q
cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
```

### 部署目标机探针

参考 `scripts/target/install_bootprobe.sh` 和 `scripts/target/install_observer.sh`
在 openKylin 目标机上安装 Rust 探针和就绪观测器。

### 主要命令

```bash
kbl version                  # 打印包版本
kbl collect --target HOST    # 从目标机 SSH 采集启动快照
kbl ingest BUNDLE            # 验证并导入探针数据包
kbl report RUN_ID            # 生成基线 HTML/JSON 报告
kbl experiment queue/run     # 排队并执行无人值守冷启动实验
kbl calibrate                # 观测器开销校准
kbl optimize plan/run        # 优化候选排序 + ABBA 验证
kbl analyze RUN_ID           # 因果图瓶颈分析
kbl agent analyze/benchmark  # BootAgent LLM 诊断
kbl dashboard                # 打开证据仪表板
```

### 仪表板

```bash
uv run kbl dashboard
```

浏览器自动打开交互式证据仪表板，包含三个标签页：
- **Boot Timeline**：启动阶段图表 + 就绪时间线 + 服务耗时排名
- **Optimization**：ABBA 验证结果卡片 + 校准开销
- **Agent**：BootAgent 四角色技能面板 + 瓶颈分析
