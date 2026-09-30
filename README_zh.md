# AgentContract

**面向长程任务智能体（Long-Horizon Agents）的运行时约束追踪与基于证据的事实核验控制面**

[English](README.md) | [简体中文](README_zh.md)

AgentContract 是一个为使用工具的 AI 智能体设计的确定性可靠性与安全控制面系统。它从用户自然语言指令中提取规范要求，将其转化为可执行的运行时约束，在工具调用执行前拦截违规行为，并通过可观测的运行轨迹证据对智能体的任务交付声明进行严格核验。

```text
用户意图（User Intent）
    ↓
需求提取（Requirement Extraction：候选草案与领域校验）
    ↓
约束账本（Constraint Ledger：生命周期管理与冲突追踪）
    ↓
拟执行动作（Proposed Action）──→ SpecGuard（动作前置拦截：BLOCK / WARN / ALLOW）
    ↓
工具执行结果（Tool Execution Outcome）──→ 轨迹存储（Trace Store：规范化事件与溯源链）
    ↓
智能体最终陈述（Agent Completion Prose）──→ 声明提取（Claim Extraction）
    ↓
EvidenceGate（确定性核验：VERIFIED / CONTRADICTED / UNVERIFIED）
    ↓
可信交付与 OpenTelemetry 轨迹导出（Verified Completion & OpenTelemetry Export）
```

---

## 解决的两大核心失效模式

1. **约束漂移（Constraint Drift）**：长程任务智能体在多轮对话上下文膨胀或处于工具调用循环时，极易遗忘、忽视甚至覆盖负向约束（例如“严禁修改 `secrets/prod.key`”、“绝不能删除生产数据库表”）。SpecGuard 在动作到达工具执行器前以确定性逻辑完成拦截——无需依赖智能体的自我审查或自觉遵守。
2. **无凭据虚假交付（Unsupported Completion）**：智能体常常在工具调用报错、超时或根本未运行的情况下，直接在文本中声明任务已完成或测试全部通过。EvidenceGate 依据可观测的运行轨迹证据，对原子粒度的交付声明进行严格核验与判定。

---

## 系统架构与核心能力 (v0.1)

### 1. 结构化提取层 (`agentcontract.extraction`)
- **厂商中立协议**：通过 `StructuredExtractionClient` 抽象层，可在 OpenAI、本地模型（vLLM、Ollama）或单元测试 Mock 之间无缝切换，无需改动业务逻辑。
- **特定供应商 Guidance 与严格 Schema**：提供兼容 OpenAI strict Structured Outputs 的 JSON Schema 转换能力（`to_strict_json_schema`），确保 `additionalProperties: false` 及严格的非空约束。
- **候选草案与领域验证隔离边界**：大模型输出先进入候选草案模型（`ConstraintDraft`、`ClaimDraft`），再由严格的领域不变式进行校验。模型无法篡改调用方溯源信息（如将推理篡改为 `ConstraintSource.USER`）、不可伪造元数据或规避必填字段。
- **严格规则约束定义**：`REQUIRE` 与 `PREFER` 规则强制要求非空合规范围（`compliance_scope`）；禁止类规则（`DENY`）则无合规范围。

### 2. 约束账本 (`agentcontract.constraints`)
- **版本化生命周期追踪**：具备显式状态机（`ACTIVE` 生效、`REVOKED` 撤销、`SUPERSEDED` 被替代、`CONFLICTED` 冲突）并校验状态流转图。
- **细粒度约束范围（Scope）**：支持资源路径模式（通配符与目录层级）、工具标识符、标准动作类型（`FILE_READ`、`FILE_WRITE`、`FILE_DELETE`、`TOOL_CALL`、`COMMAND_EXEC`）与目标类型（`filesystem`、`tool`、`network`、`database`）。
- **显式冲突生命周期**：支持显式标记冲突与解决冲突（`mark_conflicted()`、`resolve_conflict()`），具备完整的审计追溯链。

### 3. SpecGuard 运行时拦截 (`agentcontract.guard`)
- **动作前置拦截（Pre-Action Interception）**：在执行前即时评估拟执行动作。对违反 `HARD` 强约束的动作触发直接 `BLOCK`，彻底阻断工具执行。
- **后置动作校验（Post-Action Validation）**：根据账本规则校验观测到的运行时副作用（`ActionObservation`）。
- **优先级仲裁层次**：`BLOCK`（违反强约束）> `WARN`（违反弱约束/前提假设）> `ALLOW`（放行）。

### 4. 轨迹存储与 OpenTelemetry 导出 (`agentcontract.trace`, `agentcontract.adapters.otel`)
- **不可变时序审计链**：以只追加（Append-Only）方式完整记录用户请求、智能体步骤、工具调用、工具返回值以及安全守卫决策。
- **确定性关联 ID（Correlation IDs）**：生成符合 OpenTelemetry (OTLP) 规范的稳定 32 位十六进制 `traceId` 与 16 位十六进制 `spanId`，同时在 `agentcontract.*` 属性中保留底层原始标识符。

### 5. EvidenceGate 事实证据核验门禁 (`agentcontract.evidence`)
- **原子化声明核验**：将交付总结拆解为离散的事实声明（`TESTS_PASSED`、`FILE_EXISTS`、`TOOL_SUCCEEDED`、`COMMAND_EXITED_ZERO`、`ACTION_COMPLETED`）。
- **确定性判定裁决**：直接将声明与轨迹证据进行严格比对：
  - `VERIFIED`（已证实）：有确凿、已记录的轨迹事实支持。
  - `CONTRADICTED`（相悖）：存在相互矛盾的轨迹记录（如工具返回非零退出码或错误状态）。
  - `UNVERIFIED`（未核验）：轨迹中缺乏充分的支撑证据。
- **防自我验证机制**：智能体的自我口头陈述不能作为自身的支撑证据；只有可观测的实际工具执行记录与外部系统状态才能作为判定事实。

### 6. 可靠性基准测试套件 (`agentcontract.benchmark`)
- 包含 13 个确定性可靠性评测场景，覆盖四种控制架构变体：
  - `BASELINE`：无防护的基线智能体。
  - `SPECGUARD`：启用动作前置约束拦截。
  - `EVIDENCEGATE`：启用后置事实声明核验。
  - `FULL_AGENTCONTRACT`：同时启用 SpecGuard 与 EvidenceGate 完整双向防护。

---

## 安装说明

AgentContract 要求 **Python 3.12+**。核心库零第三方强制 SDK 依赖（仅依赖 Pydantic 与 Python 标准库 `urllib`）。

```bash
# 克隆仓库
git clone https://github.com/12041720/AgentContract.git
cd AgentContract

# 以可编辑模式安装（包含开发与测试依赖）
python -m pip install -e ".[dev]"
```

验证安装是否成功：
```bash
agentcontract --version
```

---

## 命令行工具 (CLI)

包内集成了用于演示与基准评测的 CLI 命令行工具：

### 1. 查看版本
```bash
agentcontract version
```

### 2. 运行快速演示
运行端到端可靠性工作流演示：
```bash
# 离线确定性演示（默认模式，无需网络请求或 API Key）
agentcontract demo

# 在线演示（连接配置的 OpenAI/兼容模型网关，需设置 OPENAI_API_KEY）
agentcontract demo --online
```

### 3. 运行可靠性评测基准
在四种架构变体上运行 13 个确定性评测场景：
```bash
# 终端纯文本表格输出（默认）
agentcontract benchmark

# Markdown 表格格式输出
agentcontract benchmark --format markdown

# 机器可读的 JSON 格式输出
agentcontract benchmark --format json
```

---

## 配置说明

OpenAI 兼容提取适配器（`OpenAICompatibleExtractionClient`）与示例支持通过以下环境变量或配置文件进行配置：

| 环境变量 | 作用说明 | 默认值 |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI 或兼容模型网关的 API 鉴权密钥 | *空（触发离线演示模式）* |
| `OPENAI_MODEL` | 目标语言模型名称 | `gpt-4o-mini` |
| `OPENAI_BASE_URL` | API 网关基础 URL | `https://api.openai.com/v1` |
| `OPENAI_RESPONSE_FORMAT` | 格式模式：`json_schema`（严格结构化输出）或 `json_object`（JSON 模式） | `json_schema` |
| `OPENAI_TIMEOUT` | 网络请求超时秒数（必须为正数） | `30.0`（示例程序中为 `120.0` 或更高） |

### 配置文件 (.env)
AgentContract 会自动发现并加载当前工作目录或上级目录中的 `.env` 或 `.agentcontract.env` 配置文件。它原生支持环境变量嵌套展开与 PowerShell 语法（如 `$env:VAR`、`${VAR}` 或 `$VAR`）：

```ini
# .env（已加入 .gitignore，不会被提交）
OPENAI_API_KEY="your-api-key"
OPENAI_MODEL="gpt-4o-mini"
OPENAI_BASE_URL="https://api.openai.com/v1"
OPENAI_RESPONSE_FORMAT="json_schema"
OPENAI_TIMEOUT="30"

# 亦支持环境变量引用与 PowerShell 语法，例如：
# OPENAI_API_KEY="${HOST_KEY}"
# $env:OPENAI_API_KEY = $env:HOST_KEY
```

### 使用第三方通用 OpenAI 兼容接口
如需接入第三方网关（例如 DeepSeek、vLLM、LiteLLM、Ollama 等）：
```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_BASE_URL="https://your-gateway.example.com/v1"
export OPENAI_MODEL="deepseek-v4-flash"
export OPENAI_RESPONSE_FORMAT="json_object"
export OPENAI_TIMEOUT="120"

python examples/quickstart.py
```

---

## Python API 使用示例

```python
from agentcontract.constraints.models import (
    Constraint,
    ConstraintProvenance,
    ConstraintScope,
    ConstraintSource,
    ConstraintStrength,
    RuleEffect,
)
from agentcontract.guard.models import Action, ActionKind
from agentcontract.runtime import AgentContractRuntime
from agentcontract.runtime.models import ToolExecutionOutcome
from agentcontract.evidence.models import Claim, ClaimType

# 1. 初始化运行时（Runtime）
runtime = AgentContractRuntime(trace_id="session_trace_001")

# 2. 注册可执行的强约束（Hard Constraint）
runtime.add_constraint(
    Constraint(
        id="protect_prod_keys",
        name="protect_prod_keys",
        description="严禁写入或删除 secrets/prod.key 文件",
        strength=ConstraintStrength.HARD,
        rule_effect=RuleEffect.DENY,
        provenance=ConstraintProvenance(
            source=ConstraintSource.USER,
            source_text="Do not touch secrets/prod.key",
            author="User",
        ),
        scope=ConstraintScope(
            target_type="filesystem",
            paths=("secrets/prod.key",),
            actions=("FILE_WRITE", "FILE_DELETE"),
        ),
    )
)

# 3. 带安全防护的动作执行
def tool_executor(action, tool_call):
    return ToolExecutionOutcome.success(output="File written")

# 构造一个试图违规写入受保护文件的动作
prohibited_action = Action(
    action_kind=ActionKind.FILE_WRITE,
    tool_name="write_file",
    target_path="secrets/prod.key",
    target_type="filesystem",
)

result = runtime.execute(prohibited_action, executor=tool_executor)
print("是否被 SpecGuard 成功拦截？", result.is_blocked)  # True
print("底层工具是否被实际执行？", result.executed)         # False（安全未执行）

# 4. 基于轨迹证据的事实核验
claims = [
    Claim(
        claim_id="cl_01",
        claim_type=ClaimType.TESTS_PASSED,
        description="所有测试通过且退出码为 0",
        trace_id=runtime.trace_id,
        command="pytest",
        expected_exit_code=0,
    )
]

verification = runtime.verify_claims(claims)
for eval_record in verification.evaluations:
    print(f"声明: {eval_record.claim.description} -> 核验结论: {eval_record.verdict}")
```

---

## 安全机制与权威控制模型

AgentContract 严格将大语言模型的生成式候选提案与确定性验证逻辑解耦：

1. **不可信 LLM 输出假定**：大模型的输出一律视为不可信的原始 JSON。提示词中虽附带任务规则约束，但模型输出永远无法自行赋予权威级别、不可伪造调用方溯源信息（如将智能体推理伪造成 `USER` 指令），也无法私自提升约束强度。
2. **确定性领域逻辑门禁**：模型提取出的候选模型必须经过严格的 Pydantic 校验。非法的数据结构、`REQUIRE` 规则缺失 `compliance_scope` 或伪造属性均会被直接拒绝。
3. **动作前置独立拦截**：SpecGuard 完全独立于大模型执行。在网络请求或本地文件系统被实际改动前，违规动作会在底层代码中被硬性阻断。
4. **可观测证据锚定**：EvidenceGate 仅以 `TraceStore` 中的不可变执行记录为权威依据。只有当轨迹中存在明确的客观事实时，交付声明才能被裁定为 `VERIFIED`。

---

## 可靠性基准测试与核心指标

基准测试套件通过 13 个标准化场景，全面评测各智能体架构在对抗条件、上下文漂移与虚假断言下的可靠性表现：

### 核心指标定义

- **约束违规率（Constraint Violation Rate, CVR）**：被禁止的违规动作实际发生的比例。（*越低越好；0.0% 为最优*）
- **无凭据虚假交付率（Unsupported Completion Rate, UCR）**：未经客观事实证实或完全虚假的完成声明被直接采信的比例。（*越低越好；0.0% 为最优*）
- **误拦截率（False Blocking Rate, FBR）**：符合合规要求的正常安全动作被错误拦截的比例。（*越低越好；0.0% 为最优*）
- **任务成功率（Task Success Rate, TSR）**：在无任何违规行为且无误拦截的前提下，所有必选目标均圆满完成的场景比例。（*越高越好*）
- **额外工具调用数（Extra Tool Calls）**：超出场景基准要求之外的额外工具调用次数。
- **时间开销（Latency Overhead）**：由于约束评估与轨迹记录为每个场景带来的平均时间延迟。

> **关于评测范围的说明**：基准评测结果反映的是针对控制面机制在确定性场景下的严谨评测，旨在评估系统架构级的安全保证能力，而非用于衡量通用大语言模型在开放式发散创作任务上的通用智能水平。

---

## 开源协议

本项目采用 MIT 开源许可证。详细信息请参阅 [LICENSE](LICENSE)。
