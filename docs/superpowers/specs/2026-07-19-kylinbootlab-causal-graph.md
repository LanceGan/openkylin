# KylinBootLab Phase 4 设计方案：依赖因果图与 What-If 模拟器

- 日期：2026-07-19
- 状态：已批准（对话中逐节确认）
- 对应赛题：第四题 openKylin 操作系统启动性能分析与优化（"分析深度与方法创新性" 25 分核心）
- 前置阶段：Phase 1（基线采集）、Phase 2（自动化实验台）、Phase 3（语义就绪探测）均已完成并通过实机验收

## 1. 目标与范围

Phase 4 将 systemd DOT 依赖图、blame 独占时间和就绪事件流合并为一个统一因果图，在图上计算关键路径、slack、瓶颈排名和 what-if 模拟，输出可直接喂给 Phase 5 优化规划器的候选排序。

完成门槛：在 5 个可逆故障注入案例上正确诊断出 Top-3 根因，命中率 ≥ 80%（15 个预测中至少 12 个正确）。

### 范围裁剪（已确认）

采用**纯依赖因果图**——基于 DOT 图 + blame + 就绪事件的依赖级分析。资源归因（CPU/IO trace）不在本阶段：BTF 存在但 ftrace 调试接口运行时空不完整，且赛题评分标准不缺此项。资源追踪在后期优化触达依赖图解释不了的瓶颈时按需补齐。

## 2. 关键决策（已确认）

| # | 决策 | 选项 |
|---|------|------|
| 1 | 系统层与用户层的关系 | **混合方案**：DOT 图 + 就绪层串行时间线，由 graphical.target→greeter_started 桥接 |
| 2 | 边权重模型 | **固定边权重 + blame 节点权重**：边无传输延迟，节点权重 = blame 独占时间 |
| 3 | 故障语料库 | **systemd drop-in 注入**：5 个物理故障案例，每案例注入→验证→恢复 |
| 4 | 关键路径算法 | 最长路径（blame 之和），slack = 关键路径长度 - 经该节点的最长路径 |

## 3. 架构

### 3.1 图构造流水线

```
DOT 图 (1651 边) ──┐
                    ├──→ CausalGraphBuilder ──→ CausalGraph ──→ Analyzer
blame 数据 ────────┘         │                      │               │
                              │ 规范化：              │ 关键路径       │
就绪事件流 ──────────────────┘ • 节点合并            │ slack          │
                              │ • 虚拟汇点注入        │ 关键性概率     │
                              │ • 两层桥接            │ 瓶颈排名       │
                              │                       │               │
                              │                  WhatIfSimulator ←──┘
                              │                  │ 删除边/并行化
                              │                  │ 收益上界
                              │                  │ 候选排序 → Phase 5
```

### 3.2 混合分层

```
systemd 层 (DOT 图)                  就绪层 (事件流)
  ┌──────────────────┐               ┌─────────────────────┐
  │ basic.target     │               │                     │
  │   └→ dbus        │               │ greeter_started ──→ greeter_ready
  │       └→ NM      │               │                     │
  │           └→ NMW │  ───桥接───→  │ login_injected ──→ session_opened
  │               └→ graphical      │                     │
  │                   (3.129s)      │ desktop_processes ─→ atspi_ready
  └──────────────────┘               │                     │
                                     │ sentinel ──→ usable │
                                     │              (78s)  │
                                     └─────────────────────┘
```

- systemd 层汇点：`graphical.target`
- 用户层汇点：`usable`
- 桥接边：`graphical.target → greeter_started`（greeter_started.earliest_ns = graphical.target 的最晚子节点完成时间）

### 3.3 与 Phase 1/2/3 的集成

Phase 4 使用但**不修改** Phase 1-3 的组件。输入来自 `RunStore` 中已有的数据：

| 输入 | 来源 | 格式 |
|------|------|------|
| DOT 图 | `systemd-analyze --no-pager dot --order` 输出（capture artifact `systemd-critical-chain` 的同级产物，或 snapshot 运行中采集） | 文本 DOT |
| blame | `systemd-analyze blame` capture artifact（Phase 1 已采集） | 文本（时长 + 单元名） |
| 就绪事件 | `readiness-events` capture artifact（Phase 3 已采集） | JSONL |

输入通过 Phase 1 的 `RunStore.raw/` 路径加载：

```python
def from_run(store: RunStore, run_id: UUID) -> CausalGraph:
    manifest = store.load_manifest(run_id)
    dot_text = load_capture(run_id, manifest, "systemd-critical-chain")  # 或独立 DOT artifact
    blame_list = parse_systemd_blame(load_capture(run_id, manifest, "systemd-blame"))
    events = load_readiness_events(run_id, manifest)
    return CausalGraphBuilder.build(dot_text, blame_list, events)
```

## 4. 数据模型

### 4.1 CausalNode

```python
class CausalNode(ContractModel):
    name: str                          # 单元名或就绪里程碑名
    blame_ns: NonNegativeInt = 0       # 独占时间 (blame)
    earliest_ns: NonNegativeInt | None = None   # 最早可能启动时刻
    latest_ns: NonNegativeInt | None = None     # 最晚必须完成时刻 (earliest + blame)
    layer: Literal["systemd", "readiness"]
```

### 4.2 CausalEdge

```python
class CausalEdge(ContractModel):
    source: str                        # 父节点名
    target: str                        # 子节点名
    kind: Literal["after", "wants", "requires", "readiness_gate"]
    weight_ns: NonNegativeInt = 0      # 边传输延迟（本阶段恒为 0）
```

### 4.3 CausalGraph

```python
class CausalGraph:
    nodes: dict[str, CausalNode]
    edges: list[CausalEdge]

    def critical_path(self, sink: str = "usable") -> list[CausalNode]:
        """从源点到汇点的最长时间节点链。"""

    def slack(self, node_name: str, sink: str = "usable") -> int:
        """该节点不拖慢汇点的最大可延迟时间。"""

    def bottlenecks(self, top_k: int = 10) -> list[Bottleneck]:
        """按 (blame × slack_penalty × criticality) 排名的瓶颈列表。"""

    def compare(self, other: "CausalGraph") -> GraphDiff: ...
```

### 4.4 Bottleneck

```python
class Bottleneck(ContractModel):
    rank: int
    node: str
    blame_ns: NonNegativeInt
    slack_ns: NonNegativeInt
    on_critical_path: bool
    score: float                        # 归一化瓶颈得分
    evidence: str | None = None         # "slack=0; on critical path 10/10 runs"
```

### 4.5 WhatIfResult

```python
class WhatIfResult(ContractModel):
    action: str                         # "remove_edge(src, dst)" | "reduce_blame(node, pct)"
    predicted_gain_ns: int              # 预测收益
    upper_bound_ns: int                 # 包络上界
    affected_nodes: list[str]           # 受影响节点
    degenerates_to_same_path: bool = False  # 无收益
    note: str | None = None
```

### 4.6 GraphDiff

```python
class GraphDiff(ContractModel):
    run_a: UUID
    run_b: UUID
    nodes_added: list[str]
    nodes_removed: list[str]
    edges_added: list[tuple[str, str]]
    edges_removed: list[tuple[str, str]]
    blame_changed: list[BlameChange]    # (node, before_ns, after_ns, delta_pct)
    critical_path_shifted: bool
    new_bottlenecks: list[str]          # 原 slack 大、现关键路径上的节点
```

## 5. 算法

### 5.1 关键路径计算

以 given sink 为汇点，对所有从源到汇的路径，计算每条路径的 blame_ns 之和。返回和最大的那条路径。

```
critical_path(sink):
    best_path = []
    best_len = 0
    for path in all_paths_to(sink):
        length = Σ node.blame_ns for node in path
        if length > best_len:
            best_len = length
            best_path = path
    return best_path
```

### 5.2 Slack 计算

```
slack(node, sink):
    cp_len = len(critical_path(sink))      # 关键路径长度
    mp_len = max_{path through node} len(path)  # 经过该节点的最长路径
    return cp_len - mp_len
```

### 5.3 瓶颈排序

```
bottleneck_score(node):
    slack_penalty = 1.0 / (1.0 + slack_ns / 1_000_000_000)
    criticality = count_on_cp / total_runs
    return blame_ns * slack_penalty * criticality
```

### 5.4 What-If 模拟器

```
simulate_remove_edge(src, dst, graph):
    graph' = graph.copy()
    graph'.remove_edge(src, dst)
    new_cp = graph'.critical_path()
    old_cp = graph.critical_path()
    return new_cp.length - old_cp.length   # ≤ 0（不会更糟）

simulate_reduce_blame(node, pct, graph):
    graph' = graph.copy()
    graph'.nodes[node].blame_ns *= (1 - pct/100)
    new_cp = graph'.critical_path()
    old_cp = graph.critical_path()
    return new_cp.length - old_cp.length   # 也可能是 0（如果节点不在关键路径上）
```

从上界特性：删除边后图的最长路径选次长替代——模拟器对收益的估计是**上界**，单删不会有害，也不会低估真实收益。

## 6. 就绪层 blame 映射

就绪事件的 blame 定义为其到下一个事件的时间差：

```python
def readiness_blame(events: list[ReadinessEvent]) -> dict[str, int]:
    """将就绪事件流映射到 blame 式独占时间。"""
    blame = {}
    for i in range(len(events) - 1):
        blame[events[i].kind] = events[i+1].monotonic_ns - events[i].monotonic_ns
    blame[events[-1].kind] = 0  # 汇点 (usable)
    return blame
```

整个就绪层形成一条串行链。slack = 0 的节点等于"用户可感知关键路径"。

## 7. 故障注入语料库

5 个物理案例，使用 systemd drop-in 注入，所有注入在验证后立即移除：

| # | 案例 | 注入方式 | 预期 Top-3 诊断 |
|---|------|---------|---------------|
| 1 | 关键路径假依赖 | `NetworkManager.service` 加 `After=foo-slow.service`（新建空单元） | 新边 → rank 1 |
| 2 | 独占延迟 | `dbus.service` 加 `ExecStartPre=/bin/sleep 3` | dbus blame ↑ + slack=0 → rank 1 |
| 3 | 无关延迟（大 slack） | `ukui-bluetooth.service` 加 `ExecStartPre=/bin/sleep 5` | 不在 Top-3（slack 惩罚） |
| 4 | 就绪层阻塞 | `lightdm.service` 加 `ExecStartPre=/bin/sleep 2` | Tsession 延迟 → rank 1/2 |
| 5 | 组合故障 | dbus 延迟 2s + lightdm 延迟 2s | dbus + lightdm 分别 rank 1/2 |

验证流程（每个案例）：

1. SSH 到目标机 → 写 drop-in 到 `/etc/systemd/system/<unit>.d/kbl-fault.conf` → `systemctl daemon-reload`
2. 冷启动一次（Phase 2 实验队列单轮）
3. 提取 DOT + blame + readiness → `CausalGraphBuilder.build()` → `bottlenecks(top_k=3)`
4. 断言预期节点出现在排名中
5. 移除 drop-in → `systemctl daemon-reload`
6. 记录命中/遗漏到 `FaultCorpusReport`

## 8. 测试策略

| 层 | 内容 | 测试数 |
|---|---|---|
| DOT 解析 | 合法图、空图、损坏图、SCC 图、注释行 | ~15 |
| CausalGraphBuilder | 节点属性、边合并、虚拟汇点注入、就绪层 blame 映射 | ~10 |
| 关键路径 | 单路径、多路径平局、零 blame、孤立节点 | ~8 |
| slack | 零/非零/独占时间不变量 | ~6 |
| 瓶颈排名 | Top-1/3/5、slack 惩罚、blame 排名一致性 | ~7 |
| WhatIf 模拟 | 删边、减 blame、收益上界、不变操作 | ~6 |
| 跨运行比较 | 相同图、不同时间、关键路径转移 | ~5 |
| 真实数据 | Phase 4 侦察数据 → 图构造 → 关键路径 = 3.129s | 2 |
| 故障语料 | 5 个物理 case，记录命中率 ≥ 80% | 5 |
| CLI | `kbl analyze RUN_ID` 烟雾测试 | 1 |

## 9. 新增文件

```
src/kylinbootlab/analysis/
├── __init__.py
├── dot.py               # DOT 图解析器
├── graph.py              # CausalNode/CausalEdge/CausalGraph 模型
├── builder.py            # CausalGraphBuilder
├── critical_path.py      # 关键路径与 slack
├── bottleneck.py         # 瓶颈排名引擎
├── simulator.py          # WhatIfSimulator
├── compare.py            # 跨运行比较 (GraphDiff)
├── fault_corpus.py       # 故障语料库注入/验证/恢复
src/kylinbootlab/cli.py   # + kbl analyze 命令
tests/
├── test_dot.py
├── test_graph.py
├── test_critical_path.py
├── test_bottleneck.py
├── test_simulator.py
├── test_builder.py
├── test_fault_corpus.py
docs/evidence/fault-corpus/  # 各案例数据与报告
```

## 10. 明确不做（YAGNI）

- C/libbpf eBPF 资源追踪（→ 3B，在需要时回头补）
- 模拟器中的 CPU/IO/磁盘/网络模型（无 trace 数据来源——仅做依赖级）
- 运行时图热更新（每次运行构造新图——图本身不可变）
- 可视化（→ Phase 9 dashboard——本阶段输出 JSON）
- 自动优化方案生成（→ Phase 5）
- 多目标优化（当前单目标 = 最小化 Tusable）
- 就绪事件流以外的第三方数据源

## 11. 与 Phase 5 的接口

Phase 4 为 Phase 5 的 OptimizationPlanner 提供：

| 输出 | 用途 |
|------|------|
| `Bottleneck.list`（按得分排序） | 候选优化池 |
| `WhatIfResult`（每候选的模拟器预测） | 候选排序公式中的 `expected_gain_ns` |
| `GraphDiff`（跨运行比较） | `evidence_confidence` 中的跨运行关键性 |
| `FaultCorpusReport` 的命中率 | `evidence_confidence` 的替代——方法论正确性的证据 |
