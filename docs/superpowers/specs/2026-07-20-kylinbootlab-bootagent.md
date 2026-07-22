# KylinBootLab Phase 8 设计方案：BootAgent 辅助分析系统

- 日期：2026-07-20
- 状态：已批准（对话中逐节确认）
- 对应赛题：开放原子开源大赛 openKylin 赛题第四题（AI/Agent 辅助分析创新加分）
- 前置阶段：Phase 1-6 均已完成，Phase 7 暂跳（裸机环境未就绪）

## 1. 目标与范围

Phase 8 构建 BootAgent——一个受约束的本地 LLM 辅助分析系统，通过四角色顺序流水线（Trace Analyst → Source Investigator → Experiment Designer → Safety Critic）将 Phase 4-6 的瓶颈数据、unit 文件源码和 what-if 模拟器结果转化为结构化的诊断报告和实验建议。

完成门槛：在 5 个已知根因案例上，BootAgent 的诊断准确率 ≥ 60%（Top-3 命中率），或相比因果图排名有明显改进。

### 为什么不做 Agent ↔ 系统的双向交互

原设计 §6.8 要求 Agent "通过结构化工具访问因果图、运行数据、模拟器、源码检索和实验系统"，且 "不直接访问无限制 root shell"。本设计严格遵循此约束：

- Agent **只读**系统数据（瓶颈报告、因果图、unit 文件、blame 日志、就绪事件），通过预加载的 prompt 传递
- Agent **不执行** shell 命令——所有输出都是 JSON schema 格式的分析报告或实验计划
- Agent 提出的实验计划由 Phase 5 ABBA 验证器执行和判定——Agent 与执行完全解耦
- 所有方案经人工审批后才能执行

## 2. 关键决策（已确认）

| # | 决策 | 选项 |
|---|------|------|
| 1 | 推理后端 | Ollama + Qwen2.5-Coder-7B-Instruct Q4_K_M（纯 CPU） |
| 2 | Agent 角色实现 | 固定 Prompt 模板 + 预加载数据（非 function-calling） |
| 3 | 故障基准集 | Phase 4+5+6 物理案例扩展（5 个已知根因案例） |
| 4 | Safety Critic 权限 | 顾问模式（打 risk_score，不下否决） |
| 5 | Skill 配置方式 | 每角色一个 TOML 配置（prompt 模板 + 输入数据 schema + 输出 JSON Schema） |

## 3. 架构

### 3.1 四角色顺序流水线

```
Phase 4 CausalGraph ──┐
Phase 4 Bottleneck ────┤
Phase 3 ReadinessEvents┼──→ Trace Analyst ──→ TraceAnalysis
Phase 1 Blame ─────────┤         │
Phase 1 DOT ───────────┘         │
                                  │
systemctl cat <unit> ────────────→ Source Investigator ──→ SourceReport
unit file corpus                  │
                                  │
TraceAnalysis ──┐                 │
SourceReport ───┤                 │
WhatIfSimulator ─┼───────────────→ Experiment Designer ──→ ExperimentPlan
Phase 6 ABBA ───┘                 │
                                  │
ExperimentPlan ──────────────────→ Safety Critic ──→ SafetyReview
                                        │
                                   (risk_score + concerns)
                                        │
                                   人工审批 → Phase 5 ABBA
```

### 3.2 推理后端

```python
class OllamaBackend:
    """通过 Ollama HTTP API 调用的本地推理后端。"""

    def __init__(self, model: str = "qwen2.5-coder:7b-instruct-q4_k_m",
                 base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    def chat(self, system_prompt: str, user_message: str,
             temperature: float = 0.0) -> str:
        """发送 chat completion 请求，返回模型文本回复。"""
        import requests
        r = requests.post(f"{self.base_url}/api/chat", json={
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            "options": {"temperature": temperature},
        }, timeout=120)
        r.raise_for_status()
        return r.json()["message"]["content"]
```

### 3.3 Skill 配置

每个角色一个 TOML 配置文件：

```toml
# agent/skills/trace-analyst.toml
[role]
name = "Trace Analyst"
description = "定位异常路径和跨启动波动"

[prompt]
system = """
你是一个 Linux 启动性能分析专家（Trace Analyst）。
你的职责是：
1. 阅读 systemd 因果图瓶颈排名和关键路径
2. 识别异常路径——slack 小、blame 大但不在关键路径上的节点
3. 检测跨启动波动——对比多次运行的关键路径变化
4. 以结构化 JSON 输出你的分析结果。

约束：
- 只基于提供的数据进行分析，不编造信息
- 每个结论必须引用具体数据（节点名、blame_ns、slack_ns、关键路径位置）
- 输出必须符合给定的 JSON Schema
"""

[input_schema]
bottleneck_report_json = "Phase 4 rank_bottlenecks() 输出的 JSON 字符串"
critical_path_nodes = "关键路径节点名称列表"
blame_text = "systemd-analyze blame 原始文本"

[output_schema]
description = "TraceAnalysis 输出 JSON Schema"
schema = '''
{
  "anomalies": [
    {
      "node": "string",
      "blame_ns": 0,
      "slack_ns": 0,
      "on_critical_path": false,
      "issue": "string",
      "evidence": "string"
    }
  ],
  "cross_boot_volatility": "string",
  "missed_bottlenecks": ["string"],
  "confidence": 0.0
}
'''
```

## 4. 数据模型

### 4.1 四个角色输出

```python
class TraceAnalysis(ContractModel):
    anomalies: list[Anomaly]
    cross_boot_volatility: str
    missed_bottlenecks: list[str]
    confidence: float = Field(ge=0.0, le=1.0)

class Anomaly(ContractModel):
    node: str
    blame_ns: NonNegativeInt
    slack_ns: NonNegativeInt
    on_critical_path: bool
    issue: str  # "high blame but off critical path" / "unexpected spike" etc.
    evidence: str  # data citation

class SourceReport(ContractModel):
    unit_findings: list[UnitFinding]
    relevant_documentation: list[str]
    actionable_insights: list[str]

class UnitFinding(ContractModel):
    unit_name: str
    issue: str  # e.g. "After=graphical.target unnecessary for dbus service"
    evidence_lines: list[str]  # quoted lines from unit file
    suggested_change: str | None

class ExperimentPlan(ContractModel):
    plan_id: str
    hypothesis: str
    predicted_gain_ns: NonNegativeInt
    evidence_chain: list[str]  # how TraceAnalysis + SourceReport led here
    drop_in_content: str | None
    rollback: list[str]
    functional_regression: list[str]
    falsification: str

class SafetyReview(ContractModel):
    risk_score: float = Field(ge=0.0, le=1.0)
    concerns: list[str]
    functional_regression_risks: list[str]
    portability_concern: str | None
    recommendation: Literal["APPROVE", "REVIEW", "REJECT"]
```

## 5. BootAgent 控制器

```python
class BootAgent:
    """四角色顺序流水线——每个角色一次推理调用。"""

    def __init__(self, backend: OllamaBackend, run_store: RunStore):
        self.backend = backend
        self.store = run_store

    def analyze(self, run_id: UUID) -> BootAgentReport:
        # 1. Trace Analyst: 读瓶颈 + 因果图 + blame
        trace = self._trace_analyst(run_id)

        # 2. Source Investigator: 读 anomaly 节点 unit 文件
        source = self._source_investigator(trace)

        # 3. Experiment Designer: 读模拟器预测 + 设计实验
        experiment = self._experiment_designer(trace, source)

        # 4. Safety Critic: 打风险分 + 提关注点
        safety = self._safety_critic(experiment)

        return BootAgentReport(trace=trace, source=source,
                               experiment=experiment, safety=safety)
```

## 6. 故障基准集

5 个案例来自 Phase 4+5+6 的真实数据：

| 案例 | 来源 | 已知根因 | 期望 Agent 行为 |
|------|------|---------|----------------|
| B1 | Phase 4 case 2 | dbus ExecStartPre=/bin/sleep 3 | Trace Analyst 识别 blame 暴增 + slack=0 → rank 1 |
| B2 | Phase 4 case 3 | bluetooth ExecStartPre=/bin/sleep 5 | Trace Analyst 识别大 slack → 不排入 Top-3 |
| B3 | Phase 6 kaiming-stagger | After= 约束重排 | Experiment Designer 解释 CI 跨零 + 建议更大 N 或组合优化 |
| B4 | Phase 5 socket-nm-wait | ExecStart= 覆盖破坏 NM | Safety Critic 识别功能回归风险 → risk_score ≥ 0.5 |
| B5 | Phase 4 case 5 | dbus+lightdm 双延迟 | Trace Analyst 识别两个独立瓶颈 → Source Investigator 分别查分 |

评定标准：每个案例由人工评分（1=完全正确 / 0.5=方向正确但细节不足 / 0=错误），总正确率 = 总分 / 5。

## 7. 测试策略

| 层 | 内容 |
|---|---|
| Python 单元 | OllamaBackend (mock HTTP)，Skill loader (parse TOML + validate JSON Schema)，BootAgent 流程（组角色输出、最终报告聚合） |
| 基准集 | 5 个案例独立评分，正确率 ≥ 60% |
| CLI | `kbl agent analyze RUN_ID` 烟雾测试 |

## 8. 新增文件

```
agent/
├── skills/
│   ├── trace-analyst.toml
│   ├── source-investigator.toml
│   ├── experiment-designer.toml
│   └── safety-critic.toml
├── benchmark/
│   ├── cases.json           # 5 cases with ground truth
│   └── evaluator.py         # scoring logic
src/kylinbootlab/agent/
├── __init__.py
├── backend.py               # OllamaBackend
├── models.py                # TraceAnalysis, SourceReport, ExperimentPlan, SafetyReview
├── skills.py                # Skill loader (TOML + JSON Schema validation)
├── controller.py            # BootAgent 四角色流水线
├── benchmark.py             # 基准集评分
src/kylinbootlab/cli.py      # + kbl agent analyze
tests/
├── test_agent_backend.py
├── test_agent_skills.py
├── test_agent_controller.py
├── test_agent_benchmark.py
```

## 9. 明确不做

- Function-calling / 多轮交互式探索（Prompt 模板 + 预加载数据已足够）
- Agent 直接执行 shell 命令
- GPU 推理（纯 CPU，Qwen2.5-7B Q4_K_M 约 4.5GB）
- 实时分析（Agent 是批处理模式——开机→采集→Agent 分析→人工审批→Phase 5 验证）
- Web dashboard 集成（→ Phase 9）
