# KylinBootLab Phase 5 设计方案：优化规划器与验证器

- 日期：2026-07-20
- 状态：已批准（对话中逐节确认）
- 对应赛题：开放原子开源大赛 openKylin 赛题第四题
- 前置阶段：Phase 1-4 均已完成并通过实机验收

## 1. 目标与范围

Phase 5 将 Phase 4 的因果图瓶颈排名和 what-if 模拟器结果转化为可独立验证的优化候选，通过 ABBA 随机化实验逐一衡量收益，用 bootstrap 统计和三级阈值做出接受/拒绝判决，输出 `OptimizationPlan` → `ValidationResult` 闭环。

完成门槛：至少 2 个候选通过完整 ABBA 验证，其中 1 个达到 `ACCEPTED`，1 个达到 `PROMISING` 或 `REJECTED`（证明验证器能正确区分有效与无效优化）。

### 范围裁剪（已确认）

- **5A（OptimizationPlanner）**：纯 Python 候选排序引擎，不修改目标机
- **5B（Profile Executor + Validator）**：实机 ABBA 实验循环，systemd drop-in 事务执行 + bootstrap 统计
- 两阶段同一次设计，分先后实现

## 2. 关键决策（已确认）

| # | 决策 | 选项 |
|---|------|------|
| 1 | 候选粒度 | **独立候选**：一个 plan = 一个 systemd 改动，收益可加，失败单独回滚 |
| 2 | 验证阈值 | **三级**：ACCEPTED（过全部硬门槛）/ PROMISING（统计有效但某门槛挂掉）/ REJECTED |
| 3 | 改动执行方式 | **Systemd drop-in + SSH**：与 Phase 1-4 一致，在 SP2 上实战验证过 |
| 4 | ABBA 设计 | 配对 block 内 ABBA（消除时间趋势），N=16（≥4 blocks × 4 boots） |
| 5 | 统计方法 | 配对差值 + bootstrap 95% CI (10K resamples) |

## 3. 架构

### 3.1 两大组件流水线

```
Phase 4 输出                         Phase 5A (Python only)
────────                            ──────────────────────
BottleneckReport ──┐
                   ├──→ OptimizationPlanner ──→ Sorted Candidate List
WhatIfResult ──────┘         │
                              │ score = gain × confidence × portability
                              │       ÷ risk ÷ cost
                              │
                              └──→ Phase 5B (real VM experiments)
                                           │
                              Phase 2 ExperimentQueue ←──┘
                                           │
                              Profile Executor (SSH drop-ins)
                                           │
                              ABBA Scheduler (4-block A-B-B-A)
                                           │
                              Validator (bootstrap CI + three-tier verdict)
                                           │
                              ACCEPTED / PROMISING / REJECTED
```

### 3.2 与 Phase 1-4 的集成

Phase 5 完全复用以下组件，不做任何修改：

| 组件 | 复用方式 |
|------|---------|
| Phase 2 `ExperimentQueue` | ABBA boot 排队（18 records / candidate） |
| Phase 2 `ExperimentOrchestrator` | 驱动冷启动循环 |
| Phase 2 `TargetPower` (vmrun) | VM 电源控制 |
| Phase 2 `RecoveryManager` | 挂死恢复 |
| Phase 1 `RunStore` | 实验结果入仓 |
| Phase 1 `remote.py` | SSH 命令传输 |
| Phase 4 `CausalGraph` + `Bottleneck` | 候选证据来源 |

## 4. 数据模型

### 4.1 OptimizationPlan

```python
class GainEstimate(ContractModel):
    predicted_ns: NonNegativeInt       # WhatIf 模拟器预测收益
    upper_bound_ns: NonNegativeInt     # 包络上界
    confidence: float = 1.0            # 关键路径出现概率

class BottleneckEvidence(ContractModel):
    node: str                          # 瓶颈单元名
    blame_ns: NonNegativeInt
    slack_ns: NonNegativeInt
    on_critical_path: bool
    action_kind: str                   # "remove_edge" | "reduce_blame" | "service_mask"

class OptimizationPlan(ContractModel):
    """One independent optimization candidate."""
    schema_version: Literal[1] = 1
    plan_id: str                       # "mask-biometric", "socket-nm-wait"
    title: str                         # Human-readable
    category: Literal["service_mask", "socket_activation",
                      "parallelize", "exec_delay", "kernel_param"]
    description: str                   # What this does and why
    evidence: BottleneckEvidence
    expected_gain: GainEstimate
    drop_in_content: str | None        # Exact .conf file content (None for mask)
    drop_in_path: str | None           # e.g. /etc/systemd/system/NM-wait-online.service.d/kbl-opt.conf
    mask_unit: str | None              # e.g. biometric-authentication.service
    preconditions: list[str]           # "systemctl is-active foo.service" etc.
    rollback: list[str]                # Exact bash commands to undo
    functional_regression: list[str]   # Systemctl checks post-optimization
    portability: float = 1.0           # 1.0=all x86 Linux, 0.5=openKylin-specific
    stability_risk: float              # 0.1=mask, 0.3=drop-in, 0.7=kernel
    verification_cost: int = 18        # Cold boots needed (per ABBA protocol)
    falsification: str                 # "If X not in Top-3 post-opt, plan is wrong"
```

### 4.2 ABBA Scheduler

```python
class ABBAScheduler:
    """Generate and track ABBA experiment blocks."""
    
    blocks: int = 4                    # Minimum blocks per candidate
    warmup_boots: int = 2              # Discarded from statistics
    total_boots: int                    # = warmup + blocks × 4
    
    def generate_sequence(self) -> list[Literal["A", "B"]]: ...
    def current_profile(self, boot_index: int) -> Literal["A", "B"]: ...
    def needs_switch(self, from_idx: int, to_idx: int) -> bool: ...
```

### 4.3 ValidationResult

```python
class ABBAStatistics(ContractModel):
    a_median_ns: int
    b_median_ns: int
    median_improvement_ns: int         # A_median - B_median (positive = faster)
    median_improvement_pct: float
    ci_lower_95_ns: int                # Bootstrap percentile CI lower bound
    ci_upper_95_ns: int
    p95_a_ns: int
    p95_b_ns: int
    paired_diffs_ns: list[int]         # Per-block B-A differences

class ValidationResult(ContractModel):
    schema_version: Literal[1] = 1
    plan_id: str
    verdict: Literal["ACCEPTED", "PROMISING", "REJECTED"]
    statistics: ABBAStatistics
    functional_passed: bool
    first_use_regression: bool | None  # None if sentinel not yet automated
    failed_gates: list[str]            # Which hard gates failed (PROMISING case)
    recommendation: str                # Next step
```

## 5. 候选排序公式

```python
def score(plan: OptimizationPlan) -> float:
    return (
        plan.expected_gain.predicted_ns
        * plan.expected_gain.confidence
        * plan.portability
        / max(plan.stability_risk, 0.01)
        / max(plan.verification_cost, 1)
    )
```

| 因子 | 来源 | 说明 |
|------|------|------|
| `predicted_ns` | Phase 4 WhatIfSimulator | 删除边/缩减 blame 后的预测收益 |
| `confidence` | Phase 4 关键路径概率 | 候选在多少次运行中出现在关键路径上 |
| `portability` | 硬编码 | 1.0 = 所有 x86 Linux；0.5 = openKylin 专用 |
| `stability_risk` | 硬编码 + 类型 | mask=0.1, drop-in=0.3, kernel_param=0.7 |
| `verification_cost` | 常数 18 | ABBA 热启动次数 |

输出按 score 降序排列的候选列表。

## 6. ABBA 调度协议

```
实验序列: A₁ B₁ B₂ A₂  |  A₃ B₃ B₄ A₄  |  A₅ B₅ B₆ A₆  |  A₇ B₇ B₈ A₈
         └─ 第1块 ─┘    └─ 第2块 ─┘    └─ 第3块 ─┘    └─ 第4块 ─┘
A = baseline（无drop-in）
B = optimized（drop-in生效）
```

| 参数 | 值 |
|------|-----|
| 每 block boot 数 | 4（A-B-B-A） |
| 最少 block 数 | 4（16 次统计有效 boot） |
| 预热 boot | 每候选前 2 次，不计入统计 |
| 总 boot / 候选 | 18（含 2 预热；统计 N=16） |
| `verification_cost` 字段 | 18（常数：总分母排序一致性） |

每块内 A-B-B-A 顺序保证局部均衡，块间序列随机化消除长程漂移。Profile 切换只发生在 A→B 或 B→A 边界。

## 7. 事务式执行与回滚

### Drop-in 格式示例

```ini
# /etc/systemd/system/NetworkManager-wait-online.service.d/kbl-opt.conf
# KylinBootLab Phase 5 — skip wait-online on single-NIC VM
[Service]
ExecStart=
ExecStart=/usr/bin/nm-online -s -q --timeout=0
```

### 事务保证

每次从 A 切换到 B（或 B 切换到 A），执行器执行原子操作：

1. **读当前状态**：SSH `test -f <drop_in_path>` 确认当前是否处于优化状态
2. **执行所需步骤**：写入或删除 drop-in → `systemctl daemon-reload`
3. **验证**：SSH `test -f <drop_in_path>` 确认切换成功
4. **失败处理**：最多 2 次重试，3 次失败 → 标记候选 `REJECTED`

回滚路径：Phase 2 RecoveryManager 接管挂死恢复（VIX snapshot → 开机 → 重新注入当前应生效的 profile）。

## 8. 三级验证阈值

```python
class Verdict(str, Enum):
    ACCEPTED = "accepted"     # All hard gates passed → enters final patch set
    PROMISING = "promising"   # Statistically significant but one gate concerns
    REJECTED = "rejected"     # No improvement or functional regression
```

| 门槛 | ACCEPTED | PROMISING |
|------|---------|-----------|
| 中位数改善 | ≥ 2% 且 CI 下限 > 0 | ≥ 0% 且 CI 下限 > 0 |
| P95 回退 | ≤ 1% | 报告但不阻断 |
| 功能回归 | 全部通过 | 全部通过 |
| 首用性能 | CI 上限 ≤ 基线 105% | 报告但不阻断（或 N/A 如果未实现哨兵检查） |

## 9. 错误处理

| 场景 | 处理 |
|------|------|
| SSH 断连（drop-in 写失败） | 重试 2 次（间隔 5s）→ `REJECTED` |
| 目标机 ABBA 循环中挂死 | RecoveryManager → 恢复 → 重新注入 profile |
| 恢复后再挂死 | `REJECTED` + 跳过剩余 boot |
| Bootstrap CI 宽度 > 改善幅度 | `PROMISING`（样本量不足），建议增加块数 |
| 功能回归失败 | 即时 `REJECTED`（不等剩余 boot） |
| Profile 状态不一致 | 强制执行切换到目标状态 |

## 10. 测试策略

| 层 | 内容 | 数量 |
|---|---|---|
| Python 单元 | `OptimizationPlan` Pydantic 验证 | 5 |
| Python 单元 | 排序公式（因子独立性、边界） | 8 |
| Python 单元 | Scheduler 状态机（A→B→A 切换） | 6 |
| Python 单元 | ABBA 序列生成（块数 1/2/4） | 4 |
| Python 单元 | Bootstrap CI（均匀/正态/空数据） | 5 |
| Python 单元 | 三级阈值边界判定 | 6 |
| 集成测试 | FakeRunner 模拟 SSH → ABBA 2 块 | 2 |
| 实机验收 | 2 候选（mask-biometric + socket-nm-wait）各 18 boot | 2 |

## 11. 新增文件

```
src/kylinbootlab/optimization/
├── __init__.py
├── plan.py                # OptimizationPlan + GainEstimate + BottleneckEvidence
├── planner.py             # Phase 5A: 候选排序引擎
├── scheduler.py           # ABBA 序列生成 + profile 切换状态机
├── executor.py            # SSH drop-in 写/删/验证
├── validator.py           # Bootstrap CI + 三级阈值
src/kylinbootlab/cli.py    # + kbl optimize plan / run / run-all / status / report
tests/
├── test_plan.py
├── test_planner.py
├── test_scheduler.py
├── test_validator.py
profiles/                   # 声明式 profile 目录（→ Phase 6+）
```

## 12. 明确不做（YAGNI）

- Sqlite 存储验证结果（Phase 1 `var/runs/<run_id>/derived/` 足够）
- 软件包级回滚（Phase 5 只做 systemd 配置；源码补丁 → Phase 6/7）
- 跨发行版适配器集成（→ Phase 10）
- 首次使用非劣性自动化（哨兵 app 窗时间外全部手动→ Phase 10 回归矩阵）
- BootAgent 工具集成（→ Phase 8）
- 声明式 profile 文件（Phase 6+ 填充 `profiles/` 目录）

## 13. 与 Phase 6 的接口

| Phase 5 输出 | Phase 6 使用方式 |
|-------------|-----------------|
| `ACCEPTED` 候选列表 | 确认配置级优化已生效，作为源码优化的 baseline |
| `PROMISING` 报告 | 标记需更深层源码修改的方向 |
| ABBA 统计框架 | Phase 6 直接复用 |
| Profile Executor | Phase 6 复用——改为 `source_patch` 类型 |
