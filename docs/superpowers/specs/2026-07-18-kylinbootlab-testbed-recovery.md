# KylinBootLab Phase 2 设计方案：自动化冷启动实验台与恢复

- 日期：2026-07-18
- 状态：待评审
- 对应赛题：第四题 openKylin 操作系统启动性能分析与优化
- 前置阶段：Phase 1（基础与基线捕获 MVP，已完成）

## 1. 目标

Phase 2 构建自动化冷启动实验循环基础设施，使控制机在无人值守模式下编排多次目标机冷启动、采集、判定、恢复、重试。系统同时支持 VMware 虚拟机（VIX API）和裸机（Wake-on-LAN + ostree），通过统一 `TargetPower` 协议隔离差异。

完成门槛：10 次无人值守冒烟采集 + 注入用户态挂起后自动恢复 + 后续实验正常运行，实验根分区不被损坏。

## 2. 设计原则

- 半自动冷启动循环——首次手动开机，后续全部自动重启
- 双层恢复——VIX snapshot 秒级恢复（VMware）、ostree pinned 部署兜底（全平台）
- 统一抽象——电源控制和恢复通过协议隔离，实验编排不感知后端
- 幂等——同一次实验的多次尝试通过状态机去重
- 可观测——每步操作有超时、有日志、有告警

## 3. 架构

```
控制机 KylinBootLab Controller (Windows)
┌─────────────────────────────────────────────────────────┐
│  ExperimentQueue (JSONL)                                │
│       │                                                 │
│  ExperimentOrchestrator                                 │
│       │                    │                │           │
│  ┌────┴────┐  ┌────────────┴──┐  ┌─────────┴───────┐  │
│  │ Target  │  │ Alive Detector│  │ RecoveryManager │  │
│  │ Power   │  │ (SSH + VIX)  │  │                 │  │
│  │ (VIX /  │  │              │  │ VMware: VIX snap │  │
│  │  WOL)   │  │              │  │ Bare:  ostree    │  │
│  └────┬────┘  └───────────────┘  └─────────────────┘  │
│       │                                                 │
└───────┼─────────────────────────────────────────────────┘
        │ SSH / VIX API
        │
┌───────┴─────────────────────────────────────────────────┐
│ 目标机 openKylin Target                                 │
│ ┌──────────────────────────────┐  ┌──────────────────┐  │
│ │ kbl-bootprobe (Phase 1)     │  │ ostree 部署       │  │
│ └──────────────────────────────┘  │ 0: 恢复环境      │  │
│                                   │ 1: 实验环境      │  │
│                                   └──────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**新增组件：**
- 控制机：`ExperimentOrchestrator`、`TargetPower`（VIX/WOL 后端）、`AliveDetector`、`RecoveryManager`
- 目标机：无新增（复用 Phase 1 探针）
- **未引入**：UDP 心跳守护进程——VIX 探活 + SSH 超时已覆盖所有挂死检测场景

## 4. 核心组件

### 4.1 TargetPower 协议

统一电源控制接口，两个后端实现：

```python
class TargetPower(Protocol):
    def power_on(self) -> None: ...
    def power_off(self) -> None: ...
    def reset(self) -> None: ...
    def snapshot_create(self, name: str) -> None: ...
    def snapshot_restore(self, name: str) -> None: ...
    def guest_alive(self) -> bool: ...
```

| 方法 | VIX 后端 | 裸机 WOL 后端 |
|------|---------|-------------|
| `power_on` | `vmrun -T ws start <vmx> nogui` | 向目标 MAC 发 WOL magic packet |
| `power_off` | `vmrun -T ws stop <vmx> hard` | `ssh sudo poweroff` |
| `reset` | `vmrun -T ws reset <vmx> hard` | power_off → power_on |
| `snapshot_create` | `vmrun -T ws snapshot <vmx> <name>` | Not supported（无操作） |
| `snapshot_restore` | `vmrun -T ws revertToSnapshot <vmx> <name>` | `ostree admin undeploy` + 重启 |
| `guest_alive` | `vmrun -T ws list` 输出包含 vmx 路径 | SSH probe |

**VIX 调用方式（2026-07-18 修订）：**
- 通过 `vmrun.exe` CLI 驱动（`F:\VMware\VMware Workstation\vmrun.exe`，v1.17.0）
- 原方案（PowerShell COM `Connect-VIX`）不可行——该 cmdlet 不存在；最终评审时实测确认 vmrun 可用后改用 vmrun
- 变更操作（power_on/off/reset/snapshot_*）失败时抛异常（fail-loud）；`power_off`/`reset` 对"已关机"的失败视为幂等成功
- 前置条件：VM 必须预先创建名为 `baseline` 的快照

**裸机 WOL 依赖：**
- 目标机 MAC 地址（配置文件提供）
- 目标机 BIOS 启用 PCIe 唤醒
- 控制机和目标机在同一广播域

### 4.2 ExperimentOrchestrator

编排器采用**同步**设计（与 Phase 1 的 `SubprocessRunner` 一致），不使用 asyncio。核心循环：

```python
def run_queue(
    queue: ExperimentQueue,
    store: RunStore,
    power: TargetPower,
    target: str,
    incoming_root: Path,
) -> None:
    while (exp := queue.dequeue("pending")) is not None:
        queue.update(exp.exp_id, status="running", started_at=utcnow())

        try:
            # 1. 确保目标机从干净状态启动
            if not power.guest_alive():
                power.snapshot_restore("baseline")
                power.power_on()
            else:
                # 已在运行→直接重启进入干净状态
                power.reset()

            # 2. 等待 SSH 可达（最多 120 秒）
            if not wait_for_ssh(target, timeout=120):
                raise TargetUnreachableError("SSH not reachable within 120 s")

            # 3. 采集（复用 Phase 1 collect_target_run）
            run_id = uuid4()
            run_path = collect_target_run(
                target=target,
                run_id=run_id,
                incoming_root=incoming_root,
                store=store,
                runner=SubprocessRunner(),
            )

            queue.update(exp.exp_id, status="done", run_id=run_id,
                         completed_at=utcnow())

        except ExperimentError as exc:
            if exp.attempt < exp.max_attempts:
                # 触发恢复→标记 attempt+1→重试
                exp.attempt += 1
                queue.update(exp.exp_id, attempt=exp.attempt)
                RecoveryManager.restore(power, target)
            else:
                queue.update(exp.exp_id, status="failed", error=str(exc))

        finally:
            power.power_off()

**重试逻辑：** 每个实验 `max_attempts=3`，单次失败后 `RecoveryManager.restore()` 恢复基线，然后 `queue.dequeue` 会再次取出同一条（因为状态仍是 pending/running）。重试上限由 `attempt` 计数器控制。

**Power 后端选择：** 通过 `kbl experiment run --backend vix|wol` 参数指定，默认为 `vix`。后端工厂函数根据参数返回对应的 `TargetPower` 实例。

**Profile：** Profile 是声明式基线/实验配置的名称。Phase 2 仅使用 `"baseline"` 这个 profile（只采集、不做任何优化改动）。Phase 5+ 将引入优化 profile（如 `"tuned-systemd"`、`"no-network-wait"`），每份 profile 描述一组 systemd drop-in 或内核参数。

### 4.3 ExperimentQueue

JSONL 持久化实验队列，一行一条状态快照：

```jsonl
{"schema_version":1,"exp_id":"coldboot-baseline-001","profile":"baseline","status":"pending","run_id":null,"attempt":0,"max_attempts":3,"error":null,"created_at":"2026-07-18T10:00:00Z","started_at":null,"completed_at":null}
{"schema_version":1,"exp_id":"coldboot-baseline-001","profile":"baseline","status":"running","run_id":null,"attempt":1,"max_attempts":3,"error":null,"created_at":"2026-07-18T10:00:00Z","started_at":"2026-07-18T10:00:05Z","completed_at":null}
{"schema_version":1,"exp_id":"coldboot-baseline-001","profile":"baseline","status":"done","run_id":"abcd-1234","attempt":1,"max_attempts":3,"error":null,"created_at":"2026-07-18T10:00:00Z","started_at":"2026-07-18T10:00:05Z","completed_at":"2026-07-18T10:03:12Z"}
```

**关键设计：** 同一 `exp_id` 多行 = 状态迁移历史。查询时按 `exp_id` 取最后一条。追加写保证崩溃不丢数据（最多丢失正在写的最新一行，状态回退到上一行）。

**操作：**
- `dequeue(status="pending")` → 取一条 + 追加 `running` 行
- `update(exp_id, **fields)` → 读取最后一行、合并 fields、追加新行
- `list(status=None)` → 读取全部行、按 exp_id 取最后状态
- `enqueue(records)` → 追加新实验到队列

**数据模型：**

```python
class ExperimentRecord(ContractModel):
    schema_version: Literal[1] = 1
    exp_id: str
    profile: str
    status: Literal["pending", "running", "done", "failed", "skipped"]
    run_id: UUID | None = None
    attempt: int = 0
    max_attempts: int = 3
    error: str | None = None
    created_at: AwareDatetime
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
```

### 4.4 Alive Detector

```python
def wait_for_ssh(target: str, timeout: float, interval: float = 5) -> bool:
    """每 interval 秒试连 SSH，成功返回 True，超时返回 False。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                 target, "true"],
                check=False, capture_output=True, timeout=10,
            )
            if result.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
        time.sleep(interval)
    return False
```

**VIX guest_alive 作为快速路径：** 编排循环在 `wait_for_ssh` 之前先调 `power.guest_alive()`，如果返回 False（VM 完全挂了），直接跳进恢复流程，不等 SSH 超时。

### 4.5 RecoveryManager

双层恢复——一层失败自动跌到下一层：

```
第一层：VIX snapshot restore（仅 VMware）
  → vmrun -T ws revertToSnapshot <vmx> baseline
  → vmrun -T ws start <vmx> nogui
  → 秒级恢复，不依赖 OS

第二层：ostree rollback（跨平台通用）
  → 前置条件：目标机 SSH 可达且能正常启动
  → ostree admin undeploy <实验部署号>
  → grub-set-default <pinned 部署号>
  → reboot
  → 分钟级恢复
```

**恢复触发条件：**
- Alive 检测 120s 超时
- `collect_run` 返回失败
- 实验 `attempt` 未耗尽时自动触发

**恢复失败的处理：**
- 两层都失败 → 标记实验 `skipped` → 暂停队列 → 人工介入

## 5. 数据流

一次完整实验循环：

```
1. queue.dequeue("pending") → exp.status = "running"
2. power.guest_alive() → VIX/WOL 检查
3. [if dead] power.snapshot_restore("baseline")
   power.power_on() → 目标机开机
4. wait_for_ssh(timeout=120) → SSH 重试循环
5. Phase 1 collect → kbl-bootprobe snapshot → scp bundle → store.ingest()
6. [success] queue.update(exp, done)
   [failure]  RecoveryManager.restore() → retry or failed
7. power.power_off() → 目标机关机
8. loop → step 1
```

## 6. 错误处理

| 场景 | 检测方式 | 处理 |
|------|---------|------|
| VM 无法开机 | VIX power_on 超时 | exp → failed，继续下一个 |
| 目标机 120s SSH 不可达 | wait_for_ssh 超时 | 触发恢复 → retry → failed |
| 采集失败 | kbl collect 返回非零 | 诊断 bundle 入仓 → 恢复 → retry |
| 恢复本身失败 | VIX/ostree 命令异常 | exp → skipped + 暂停队列 |
| 实验 attempt 耗尽 | attempt >= max_attempts | exp → failed，继续下一个 |
| 控制器线程被中断 | SIGINT / Ctrl-C | 当前运行实验保持 running 状态，下次 `run` 命令从第一条 pending 继续。中断不丢数据——队列文件和 RunStore 均不可变 |

**错误类型：**

```python
class ExperimentError(Exception): pass
class PowerControlError(ExperimentError): pass
class TargetUnreachableError(ExperimentError): pass
class RecoveryFailedError(ExperimentError): pass
```

## 7. CLI 扩展

```bash
# 实验管理
kbl experiment queue --profile baseline --count 10     # 排队 10 个基线实验
kbl experiment run --target kbl@192.168.19.128         # 启动实验循环
kbl experiment status                                   # 查看队列状态
kbl experiment retry --exp-id coldboot-baseline-005     # 重试单个失败实验
kbl experiment reset --status failed                    # 重置所有失败实验为 pending
```

## 8. 新增文件

```
src/kylinbootlab/experiments/
├── __init__.py
├── queue.py              # ExperimentQueue (JSONL 持久化)
├── orchestrator.py       # ExperimentOrchestrator
├── power.py              # TargetPower 协议 + VIX/WOL 实现
├── recovery.py           # RecoveryManager
└── aliveness.py          # Alive Detector
src/kylinbootlab/cli.py   # 新增 kbl experiment 子命令组
tests/
├── test_queue.py
├── test_orchestrator.py
├── test_power.py
├── test_recovery.py
scripts/target/
├── prepare_recovery.sh   # 恢复环境初始化脚本
```

## 9. 测试策略

| 类型 | 内容 | 通过标准 |
|------|------|---------|
| 单元测试 | `ExperimentQueue` JSONL 读写、状态迁移、幂等重放 | 全部操作正确 |
| 单元测试 | `ExperimentRecord` Pydantic 验证 | 拒绝非法状态字段 |
| 单元测试 | `TargetPower` 命令构造（VIX/WOL 后端） | 命令参数正确 |
| 集成测试 | FakeRunner 模拟 SSH/VIX，跑 3 个实验队列 | 全部 done |
| 集成测试 | 注入 SSH 超时 → 验证恢复路径 | 触发恢复、重试正确 |
| 集成测试 | 注入恢复失败 → 验证暂停 | 队列暂停、exp skipped |
| 集成测试 | 注入采集失败 → 验证诊断入仓 | bundle 入仓、错误记录 |
| 真实环境验收 | VM 上跑 10 次无人值守循环 | 100% 成功或失败有清晰日志 |
| 真实环境验收 | 注入用户态挂死（`systemctl stop ssh && sleep`） | 控制机检测到 → VIX 恢复 → 剩余实验正常 |
| 真实环境验收 | 10 次+循环后手动验证：OS 仍可正常启动、探针可正常采集 | 功能无回退 |

## 10. 与 Phase 1 的合约

Phase 2 使用但**不修改**以下 Phase 1 组件：

| 组件 | 使用方式 |
|------|---------|
| `RunStore` | 实验采集结果入仓 |
| `remote.py` / `collect_target_run` | 从目标机采集 snapshot |
| `kbl-bootprobe` | 不变 |
| `ProbeManifest` 契约 | 不变 |

Phase 2 新增 `ExperimentRecord` 契约（独立 schema version 1），与 Phase 1 的 `ProbeManifest` 正交。

## 11. 与后续阶段的接口

Phase 2 输出的 `run_id` 列表直接喂给 Phase 3（可观测性）和 Phase 5（优化验证器）。`TargetPower` 协议在 Phase 6/7 的 A/B 实验中复用。
