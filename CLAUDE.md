# KylinBootLab

> openKylin 操作系统启动性能分析与优化 — 开源创新大赛参赛项目

## 项目定位

KylinBootLab 是一套全链路 Linux 客户端启动性能分析、优化与验证系统。以 openKylin 为主平台，覆盖内核启动到 UKUI 桌面可用的全过程，通过因果图建模、统计实验和 BootAgent 辅助分析定位瓶颈并实施可验证的优化。

**架构：双机闭环** — Windows 控制机编排实验、分析数据、生成报告；openKylin 被测机运行 Rust 探针采集启动事件。

## 当前状态

**Phase 1（基础与基线捕获 MVP）代码完成，等待真实目标机验收。**

| 指标 | 值 |
|---|---|
| 分支 | `worktree-kylinbootlab-phase1` |
| 远程 | `https://github.com/LanceGan/openkylin.git` |
| 提交数 | 18（89fc8d5 设计 → d017e9f Codex 审查修复） |
| Python 测试 | 30/30 通过，覆盖率 91% |
| Rust 测试 | 5/5 通过（Windows MSVC 链接器环境问题待解） |
| 静态检查 | ruff ✅ / mypy strict ✅ / cargo fmt ✅ / cargo clippy ✅ |

**Phase 1 代码完成但尚未在真实 openKylin 上验收**（阻塞于硬件/VM 环境）。验收标准见 `docs/runbooks/foundation-baseline.md`。

## 在新机器上开始开发

### 1. 克隆仓库

```powershell
git clone https://github.com/LanceGan/openkylin.git
cd openkylin
git checkout worktree-kylinbootlab-phase1
```

### 2. 安装工具链

```powershell
# Python 3.12 + uv 包管理器
winget install --id astral-sh.uv --exact

# Rust 1.85.1
winget install --id Rustlang.Rustup --exact
# 新终端中：
rustup toolchain install 1.85.1 --profile minimal --component clippy,rustfmt

# 安装 Python 3.12
uv python install 3.12

# 解析依赖
uv sync --all-groups --python 3.12
```

### 3. 运行质量门禁

```powershell
# 完整检查（bash 或 PowerShell 均可）：
uv run python scripts/export_schema.py --check
uv run ruff check .
uv run mypy src tests
uv run pytest -q --ignore=tests/test_rust_contract.py
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```

> 注意：`tests/test_rust_contract.py` 调用 `cargo run` 子进程——需要 `cargo` 在 uv 的 PATH 中。如果单独执行此测试失败，先确保 cargo 可用。

### 4. 部署 openKylin 目标机

详见 `docs/runbooks/foundation-baseline.md`。摘要：

- **物理机**：下载 openKylin 2.0 桌面 ISO → Rufus/Ventoy 写 U 盘 → 安装（用户名 `kbl`）→ `sudo hostnamectl set-hostname kbl-target`
- **VMware**：新建 VM（Linux 5.x+ 内核 64 位，≥40GB 磁盘，≥4GB 内存，2+ 核，桥接网络）→ 挂载 ISO 安装 → 同上配置
- 控制机配 SSH 免密：`ssh-keygen -t ed25519` → `scp` 公钥 → `ssh -o BatchMode=yes kbl@kbl-target.local true`
- 目标机安装必要包：`sudo apt-get install -y avahi-daemon build-essential curl openssh-server python3`

### 5. 执行 Phase 1 验收

```powershell
# 构建 Rust 探针并部署到目标机（按 runbook Section 3）
# 第一次真实采集
$runId = (uv run kbl collect --target kbl@kbl-target.local --data-root var/runs --incoming-root var/incoming).Trim()
# 生成报告
uv run kbl report $runId --data-root var/runs
```

## 项目结构

```
KylinBootLab/
├── src/kylinbootlab/          # Python 控制端（分析、存储、报告、CLI）
│   ├── cli.py                 # Typer CLI 入口（kbl version/ingest/report/collect）
│   ├── contracts.py           # Pydantic 数据契约（ProbeManifest, ArtifactRecord）
│   ├── store.py               # 不可变 RunStore（校验 → 暂存 → 原子发布）
│   ├── capture.py             # 命令采集文档加载器
│   ├── systemd.py             # systemd-analyze 输出解析（duration/blame/time）
│   ├── report.py              # 基线报告生成（metrics.json + baseline.html）
│   ├── remote.py              # SSH/SCP 传输（BatchMode, ConnectTimeout, ServerAlive）
│   ├── schema.py              # JSON Schema 加载器
│   ├── schemas/               # 版本化的 JSON Schema
│   └── templates/             # Jinja2 HTML 报告模板
├── target/bootprobe/          # Rust 目标机探针
│   ├── src/
│   │   ├── main.rs            # CLI（contract-fixture, snapshot 子命令）
│   │   ├── model.rs           # Rust 契约类型（与服务端 Pydantic 1:1 对齐）
│   │   ├── snapshot.rs        # 快照编排（默认采集 systemd time/blame/chain/journal）
│   │   ├── capture.rs         # 命令执行 + 文件哈希（SHA-256）
│   │   └── system.rs          # 系统发现（os-release, boot_id, CLOCK_BOOTTIME）
│   └── tests/
├── tests/                     # Python 测试（30 项，覆盖率 91%）
│   ├── test_cli.py            # CLI 集成测试
│   ├── test_contracts.py      # 契约验证（schema, 未知字段, 路径遍历, 冒号拒绝）
│   ├── test_store.py          # RunStore 完整性（校验和, 文件集, TOCTOU, containment）
│   ├── test_systemd.py        # systemd 输出解析（时长, 启动, blame）
│   ├── test_report.py         # 报告确定性（byte-for-byte 一致）
│   ├── test_remote.py         # SSH/SCP 传输（FakeRunner, 诊断导入, 超时）
│   ├── test_rust_contract.py  # Rust ↔ Python 跨语言契约验证
│   ├── helpers.py             # create_probe_bundle() 测试工具
│   └── fixtures/              # 跨语言契约固定数据
├── scripts/
│   ├── check.ps1              # 本地质量门禁脚本（Invoke-Checked）
│   ├── export_schema.py       # 确定性 JSON Schema 导出（--check 陈腐检查）
│   └── target/
│       ├── kbl-capture-run    # 特权采集 wrapper（固定 PATH, UUID 校验, umask 0027）
│       ├── install_bootprobe.sh # 等幂安装器（kbl 用户组, sudoers, visudo 校验）
│       └── verify_foundation.sh # 目标机冒烟验证
├── docs/
│   ├── superpowers/specs/     # GPT 完成的架构设计
│   ├── superpowers/plans/     # Phase 1 详细计划 + 10 阶段路线图
│   └── runbooks/              # 运维手册
├── profiles/                  # 声明式基线与优化配置（待填充）
├── adapters/                  # 跨发行版适配器（openKylin/Ubuntu/Fedora）
├── agent/                     # BootAgent 工具和基准测试
└── dashboard/                 # TypeScript 交互式证据面板
```

## 已解决的关键设计问题

### 安全契约

- **路径安全**：`contracts.py` 拒绝所有 path segment 中的冒号、`..`、反斜杠、绝对路径。`store.py` 的 `artifact_path()` 对已解析路径进行 containment 检查。
- **TOCTOU**：`store.py` 采用"先复制到 staging，再验证 staging 中的字节"模式——写入存储的字节与已验证的字节完全相同。
- **特权采集**：`kbl-capture-run` wrapper 在执行前设置显式安全 PATH；Rust `Command::new` 也设置为备用的硬编码 PATH。
- **SSH**：`BatchMode=yes`、`ConnectTimeout=15`、`ServerAliveInterval=15`、`ServerAliveCountMax=3`。

### 不可变存储

`RunStore.ingest()` 分 4 个阶段：
1. **枚举源**：符号链接检查 + 文件集精确匹配
2. **复制到 staging**：将文件复制到 `.incoming-<uuid>/raw/`；manifest 以已验证的内存中 Pydantic 对象序列化（而非源磁盘副本）
3. **从 staging 验证**：读取 SHA-256、大小、无符号链接——这些是将被原子移动的确切字节
4. **原子安装**：`shutil.move` → 最终 store 位置；任一阶段失败 → 移除整个 `.incoming-*`

## 下一阶段（Phase 2）

自动化冷启动实验台与恢复，需要：
- Wake-on-LAN（或 VMware：`vmrun`）用于目标机电源控制
- GRUB 一次性启动项用于实验系统
- 硬件/VM watchdog + 控制器超时
- 恢复环境作为 GRUB 默认项
- 实验队列持久化

计划文档模板：`docs/superpowers/plans/2026-07-15-kylinbootlab-testbed-recovery.md`

## 关键命令

```powershell
# 开发
uv run kbl version                    # 打印包版本
uv run kbl ingest BUNDLE_DIR          # 验证并导入探针 bundle
uv run kbl report RUN_ID              # 生成 baseline.html + metrics.json
uv run kbl collect --target kbl@kbl-target.local  # SSH 采集完整管道

# Rust 目标机
cargo run -p kbl-bootprobe -- contract-fixture   # 打印跨语言契约固件
cargo run -p kbl-bootprobe -- snapshot --run-id $(uuidgen) --output ./run  # 启动快照

# 质量门禁
uv run ruff check . && uv run mypy src tests && uv run pytest -q
cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
```
