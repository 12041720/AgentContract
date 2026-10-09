# AgentContract 主 agent 迁移交接

> 交接快照：2026-10-09（Asia/Shanghai）。接收者：新的**网页端 ChatGPT 主 agent**，通过已连接的 GitHub 检查实现、修改仓库文件、安排任务并作出验收结论。
>
> 来源：已从用户指定的、加载完整历史的网页标签页分段读取原对话《Agent项目选题建议》的选题及开发正文，并与当前本地仓库的治理文件、架构、任务报告、评审日志和提交记录交叉核对。本文重点保留开发决定、用户纠正、验收边界和当前接续点，略去大部分选题资料。历史“已通过”按原主 agent 的裁决记录描述；测试数字按执行报告描述，不代表本次重新运行。远端当前状态仍需新主 agent 通过 GitHub 刷新。
>
> **接续点：TASK-001～011 已接受；TASK-012 第一轮 CHANGES_REQUESTED，已有第二轮修复及报告，等待复审。原网页末尾第二轮复审回复只有标题，随后显示“连接已中断，正在等待完整答复”，没有可继承的完整裁决。**

## 1. 新主 agent 的身份与工作方式

你接替原网页端 ChatGPT 主 agent，负责项目方向、架构边界、任务拆解、验收标准、代码审查和最终裁决。

- GitHub 仓库：<https://github.com/12041720/AgentContract>；默认分支 `main`。
- 用户本地仓库：`C:\Users\fyfjz\Desktop\fyf\AgentContract`，Windows / PowerShell。
- 主 agent 通过网页端 ChatGPT 的 GitHub 连接读取分支、提交、代码、测试和执行报告，并在连接提供写能力时修改治理文件/代码、布置后续工作。
- 执行 agent 在本地完成当前任务、运行测试、提交/按任务要求推送，在任务文件的 **Executor Report** 中交接。
- 用户说“已完成”通常是复审触发信号；不能直接等同于任务验收通过。应先检查 GitHub 上实际分支头、diff、报告和证据。
- 新会话不会自动继承旧会话的 GitHub 连接或工具权限。先确认仓库访问能力；若只能读取，应如实说明，提供具体补丁/执行指令，不声称已经写入 GitHub。
- 不把网页端主 agent 当作能够直接操作用户 Windows 环境的执行 agent。独立运行了什么、静态审查了什么、执行 agent 报告了什么，必须分别陈述。

原对话：<https://chatgpt.com/c/6aaceb64-5718-83e8-8495-f7fab9f8b0e1>。

### 用户明确表达过的要求

- 本项目用于 Agent 方向求职展示：需要有差异化、可运行成果和可解释的真实量化结果，不止架构设想。
- 2026-09-22/23 用户创建仓库并指定：网页端 ChatGPT 担任主 agent，在 GitHub 搭骨架、落盘任务、检查执行结果；用户另安排执行 agent。关键决定必须进入仓库文件，使换会话后仍能恢复。
- **主 agent → 执行 agent → Review 是项目开发流程，不是 AgentContract 产品功能。** 用户专门纠正过这一点，README、项目介绍和简历不能混淆。
- 给执行 agent 的指令要简洁。用户先说“简洁！”，后又说“你怎么把完整分析写进指令里了，输出简洁指令”。审查分析留在任务 Review，聊天中给分支、任务入口、明确修复点、必要检查和停止边界即可。
- 使用本机已安装的 Python 3.12.9；不强制新建 `.venv`，不为主 agent 自定的兼容声明安装 Python 3.11。此前 uv-managed 3.11 已在 TASK-002 报告/审查中确认清理；不要重新安装或重复清理系统 Python。
- 用户多次问“什么时候能试用”“怎么试用”，后来追问为何 online demo 总是固定 `secrets/prod.key`：需要清楚解释实际模型调用范围，并推进真实 agent 集成。
- Codex 插件、hooks、测试和配置必须局限于项目/测试隔离环境，不影响项目外的 Codex CLI/Desktop，也不能默认动全局认证、配置、信任或市场。

## 2. 权威文件与职责边界

按以下顺序恢复上下文（从 GitHub 当前版本读取）：

1. `AGENTS.md`：仓库协议。
2. `.agent/STATE.md`：当前阶段、唯一活动任务、权威状态。
3. `.agent/tasks/TASK-012.md`：当前任务、执行报告、第一轮评审。
4. `.agent/TASKS.md`：路线图与任务状态。
5. `.agent/REVIEW_LOG.md`：主 agent 的追加式审查历史。
6. `docs/ARCHITECTURE.md`、`README.md` / `README_zh.md`、`docs/integrations/codex.md`：架构、能力和操作边界。

仓库是共享记忆；HANDOFF 是恢复入口，不覆盖最新权威状态。如果用户指示与权威文件冲突，应指出冲突再处理，不自行猜测。

只有主 agent 可以改权威任务状态、标记 accepted/rejected、重定义架构/任务范围、创建下一活动任务。执行 agent 只能实现一个活动任务、运行规定检查、填写 Executor Report；不得自验收、削弱测试或静默开启下一任务。

标准流程：主 agent 写任务 → STATE 指向任务 → 执行 agent 实现和交接 → 主 agent 查代码/测试/diff → 任务 Main Agent Review 与 REVIEW_LOG 写裁决 → 同步 STATE/TASKS → 按需要激活下一项。保持一个活动任务，除非明确引入并行工作；里程碑结束也不自动启动新任务。

## 3. 项目目标、架构与工程原则

AgentContract 是面向长程、工具使用智能体的运行时约束追踪与基于证据的完成核验控制面，关注两类失效：约束漂移、无证据的完成声明。

执行链：用户需求 → 候选需求提取与领域校验 → Constraint Ledger → 拟执行动作 → SpecGuard → 工具执行 → Trace / Evidence → 完成声明 → EvidenceGate。

- **Constraint Ledger**：有来源和版本的约束账本；支持 ACTIVE / REVOKED / SUPERSEDED / CONFLICTED 生命周期。冲突目前是显式标记/解决，不应宣传自动冲突发现。
- **SpecGuard**：执行前 ALLOW / WARN / BLOCK，执行后检查观察到的副作用；HARD 约束不能只靠同一 LLM 自我遵守。
- **Trace / Evidence**：记录具体动作、工具结果、守卫决策和关联标识，支持 OTLP 导出并保留原始溯源 ID。
- **EvidenceGate**：VERIFIED / CONTRADICTED / UNVERIFIED。没有证据不能升级成 VERIFIED；智能体口头声称不能核验自身。
- **提取与外部适配**：LLM 输出先作为不可信候选，调用方权威/来源不能被模型篡改；核心厂商中立，OpenAI-compatible 只是适配层。
- **Codex 集成**：SessionStart、UserPromptSubmit、PreToolUse、PostToolUse、Stop；项目会话账本/trace 持久化，PreToolUse 拦截，Stop 核验。

实现位置：`src/agentcontract/{constraints,trace,guard,evidence,runtime,extraction,adapters,integrations/codex,benchmark}`。

工程约束：开发基线为用户已安装的 **Python 3.12.9**；不为兼容矩阵下载其他 Python。优先标准库 + Pydantic。每项对外新增行为需要测试，优先确定性验证；保留约束/证据来源，不静默“修正”不可信模型输出。v0.1 不做通用 agent 框架、完整策略语言、训练、生产分布式执行；多 agent 共享协议等是 backlog。

### 选题背景与不能继承为“已实现”的早期设想

早期比较过 Context Scheduler、Trace2Flow、AgentOS、CodeMemory、MCP Guard 等方向，最后选择合并 SpecGuard + EvidenceGate，命名 AgentContract：前者约束过程，后者核验结果；它是现有 agent 外部的可靠性控制层。新主 agent 不需要重新选题。

选题讨论曾提出约束图与例外优先级、自动冲突检测、语义/LLM verifier、证据强弱分数、PLANNED → IMPLEMENTED → LOCALLY_VALIDATED → TARGET_VALIDATED → RELEASED → ACCEPTED、多 agent 和 100～300 个真实任务 benchmark。这些是设计愿景，**不能当成当前交付清单**。早期举例表中的 67%/74% 等成功率也只是理想示意，不是实验数据。当前实现范围以 ARCHITECTURE 和任务裁决为准；正式 benchmark 是 TASK-007 的确定性场景与实际运行结果。

### 开发演示、模型调用和真实 agent 的区别

TASK-005/006 先完成核心闭环，TASK-008 加真实 provider，TASK-009 完成 v0.1 可安装/CLI/文档。当时 online demo 的需求与完成声明由真实模型提取，但读 `src/main.py`、尝试写 `secrets/prod.key`、运行测试等动作及最终声明仍由示例脚本安排；模型没有自由规划整个工具循环。`AgentContractRuntime` 是工具执行 wrapper；benchmark harness 也不是完整自主 agent harness。

BLOCK 来自结构化约束与动作匹配，并在 executor 调用前阻止执行，不是让模型自己说“我遵守了”。保护只覆盖接入受控工具入口的动作；未包装的 `os.remove` / subprocess 等不能自动纳入保护。早期 demo、unit tests 和真实 Codex lifecycle 证据必须分开描述。

用户追问真实 harness 后，原主 agent 优先选择 Codex：直接对接生命周期 hooks，先证明确实接入真实工具调用，再考虑其他框架。OpenCode 的 TS sidecar、DeepSeek Harness、LangGraph 曾作为后续候选；**早期建议的“TASK-011 OpenCode / TASK-012 DeepSeek Harness”已经被后来的实际任务取代**。现在 TASK-011 是隔离修复，TASK-012 是 PreToolUse 协议兼容；不能按旧建议继续布置。

### 用户实际使用的 extraction provider

用户已有环境变量 `BUPT_API_KEY`，使用模型 `deepseek-v4-flash`，base URL 为 `https://myai.bupt.edu.cn/llm-gw/v1`。历史 quickstart 接法是把已有变量映射给 `OPENAI_API_KEY`，配置 `OPENAI_MODEL` / `OPENAI_BASE_URL`，先用 `OPENAI_RESPONSE_FORMAT=json_object`。不得读取、打印或放入交接任何 key 值。

最初 extraction 请求 30 秒超时；用户贴出直接 HTTP 小请求成功结果，随后项目支持更长 timeout（`OPENAI_TIMEOUT`）并完成后续 provider smoke。小请求成功只证明当时那次调用成功，不能证明较复杂 extraction 请求必定成功；原回复把“就是 timeout 太短”说得过于确定，新主 agent 不应照搬这个因果结论。网关是否支持 strict `json_schema` 也不能由 `json_object` 成功推断。

## 4. 已接受的里程碑

以下来自仓库治理记录；历史测试数字为**执行 agent 报告**，本次交接未重新运行。

| 范围 | 结果与 main 集成提交 | 关键内容 / 验证边界 |
|---|---|---|
| TASK-001～004 / M1 | ACCEPTED | 领域模型与账本、统一 trace、SpecGuard、确定性 EvidenceGate |
| TASK-005～006 / M2 | ACCEPTED | runtime/demo、LLM 辅助需求与声明提取 |
| TASK-007 / M3 | ACCEPTED；`12dad52df4b2901905c2ea92c07f8a71d2934d7f` | 四种独立变体、13 个确定性场景；报告 222 tests passed |
| TASK-008 / M4 | ACCEPTED；`0469bf7a0204eba56aaa2fe44d65edfb63b8b4ac` | 外部工具适配、有效 OTLP wire IDs、严格 Structured Outputs schema；报告 268 passed |
| TASK-009 / v0.1 | ACCEPTED；`6c24d9f749e0249a8a75da89effccbdcdb5c6e5e` | CLI/安装包/文档、实际 OpenAI-compatible provider 验收；报告 288 passed |
| TASK-010 / M5 | ACCEPTED；`8b3d4ee1f7ad11991a04f72f83ba303387965623` | 真实 Codex lifecycle/plugin 集成；报告 343 passed、plugin-only 会话实际保护写 DENY、文件 hash 不变、VERIFIED/UNVERIFIED |
| TASK-011 / M6 | 第三轮 ACCEPTED；`a8343521416cbe97a257a4c06f19730c3265ee60` | 配置隔离、保留第三方 hooks/metadata、防 Junction/symlink 逃逸；报告 355 passed |

v0.1 provider smoke 曾使用 `deepseek-v4-flash`：真实保护文件写入在执行前 BLOCK；真实 pytest 成功声明 VERIFIED；伪造文件存在声明 UNVERIFIED。它证明当时的验收路径，不能泛化成所有语义约束均已解决。

M6 评审时主 agent 可审源码与测试，但其容器 GitHub DNS 失败，未能独立 clone/rerun；当时 combined status 无 CI checks。**Codex Desktop GUI 隔离始终 MANUAL/UNVERIFIED**，不能把 CLI 结果写成 Desktop 验证成功。

## 5. 重要历史审查经验

这些问题已在各任务反复审查，后续修改应避免回归：

- TASK-001/002：账本与 trace 必须不可变、可持久序列化。ToolResult 的 parent 必须与 call_id 指向同一次 ToolCall；durable value 只接受 JSON 风格数据，mapping → FrozenDict、list/tuple → tuple，拒绝 set/frozenset、bytes/bytearray、NaN/Infinity 和任意自定义对象。不能通过转换丢失语义，也不能让原始可变对象改写历史证据。
- TASK-003/004：typed selectors 保留嵌套类型，所有提供的选择条件共同成立，call_id 不能绕过其他条件。0 次或多次候选 execution 不能随意挑一次核验。`files` / `changed_paths` 本身不证明文件存在；需要明确存在状态。trace-level FILE_EXISTS 按目标文件最新明确观察判断，missing → created 为 VERIFIED，反向为 CONTRADICTED；无关路径不影响目标。GENERIC 语义不能伪装成确定性可核验声明。
- TASK-005：executor 内部 TypeError 不能触发重试，签名在执行前绑定；未进入函数体时 executed=False，进入后异常为 True 且记录 ERROR。post-check 要使用真实 outcome 的 target_type。便利构造器也不能先 tuple(set) 绕过有序输入校验。
- TASK-006：模型只能输出 Draft。caller 显式决定 source、author、source_location、source_text、trace/session；不允许默认把缺字段候选升级成 USER/HARD/DENY/global。未知字段不能 extra=ignore；非字符串 scope 项不能 str() 转换；无效输出 strict 模式报错，宽松模式记录 ERROR diagnostic 并跳过。LLM 不直接写账本或产生 VERIFIED；默认 ID 不能跨 extractor 实例碰撞。
- Benchmark：TSR 必须来自独立场景任务真值，不能与 claim 验收/UCR 混为一谈；FBR 只统计错误的前置阻止；额外 tool calls 依据显式真值；不写死完整方案必胜；保留负的延迟差。
- 外部适配：严格路径类型，OTLP IDs 合法且保留来源；实际发出的 strict schema 必须满足供应商要求。不能通过隐式重试或静默改写掩盖无效输出。
- Codex 防护：动态/不透明破坏性 shell 在 HARD 文件约束下需安全处理；混合 apply_patch 应逐 `(path, action_kind)` 匹配；已有会话账本/trace 缺失或损坏不能重置为空而放行；锁超时/I/O/异常需明确 DENY。跨进程锁需要实际 spawned-process 测试。
- 插件：真实 marketplace install/list 只证明发现/启用，不证明 hooks 已获信任并实际运行。真实 plugin-only 验收要排除项目 hooks 的替代作用。
- 隔离：项目 install/uninstall 保留第三方 matcher 子 hooks、未知结构和顶层元数据；未知结构应安全拒绝；防止 `.codex` Junction/symlink 指向项目外。审计只能说明已检查范围，不能从有限快照宣称全局零副作用。
- 测试：隔离 CODEX_HOME；不得默认复制用户 auth/config/trust；不得绕过 sandbox/approvals；失败路径也必须做完整性检查。清理只针对明确属于测试的资源，不做无边界全局插件卸载/文件删除。

TASK-007 第一轮虽然有 218 passed 和看似漂亮的 CVR/UCR 表，因指标语义有误被拒绝，旧数字明确作废；修复后重新运行才接受。不能从聊天中摘旧表作宣传。TASK-008 曾因 strict schema 不完整被再次拒绝：每个 object 都需关闭 additionalProperties，全部 properties 纳入 required，语义可选值用 nullable；实际 HTTP payload 也要检查，不能只验证内部 schema。每次 extraction 恰好一次请求，不隐式 fallback/retry。

### TASK-010～012 的真实集成转折与用户机器记录

TASK-010 多轮审查从“有 hooks 代码”推进到实际 plugin-only session：真实提取方法不得缺失后退回 regex；不能宣称不支持的 continue/approve hook；HARD 文件限制下不透明 Bash 不能静默放行；混合 apply_patch 按路径与动作配对，不能做交叉乘积；已有会话 ledger 缺失/损坏不可重置；atomic replace 不能替代跨进程锁。marketplace 被发现不等于 hooks 已信任或运行。

之后用户在 Desktop 看到“35 个 hooks 待审核”，明确要求项目内外隔离。追查发现测试继承全局 CODEX_HOME 的风险，TASK-011 因此改为配置隔离/保留第三方结构/越界路径审计，经过三轮才接受。不能把那 35 条全部归因于 AgentContract，也不能声称 Desktop GUI 已全部验证。

另有 Codex CLI 安装故障：当时缺启动 shim/Windows optional package，修复 npm 安装后用户说“codexcli 正常了”。没有证据证明 AgentContract 导致安装损坏；这不是当前待做事项。

全局残留检查当时发现 7 条 AgentContract 测试插件 enabled 配置，但 plugin list 已无对应插件，属于残留配置而非已证明生效的 hooks。用户已按精确范围、先备份的指令删除这 7 个条目，并贴出复查结果：AgentContract 条目消失，3 个官方市场保留。历史备份路径：`C:\Users\fyfjz\.codex\config.toml.backup-20261009-104716`。这是用户已完成的历史清理；不需要新主 agent 再删全局配置，不代表本次重新审计过机器。

后来 project-A / project-B 的 CLI probe 先遇到 hooks trust 门槛，随后实际 project-A 会话出现 PreToolUse Failed、读文件却成功。原主 agent 结合 Codex 源码/测试定位 ALLOW-without-updatedInput 协议兼容问题；日志没有直接给出精确 parser 错误，不能把推断伪称成日志原文。这一问题触发当前 TASK-012。

## 6. 当前活动任务：TASK-012，尚未接受

**仓库权威状态：CHANGES_REQUESTED — round 1；M7 未完成；未集成 main。**

原对话最后的用户消息是第二次“已完成”。原主 agent 回复仅出现“TASK-012 第二轮复审结果”标题，随后页面提示连接中断、等待完整答复。因此原聊天没有完整第二轮 verdict；不能把开始生成标题、用户说完成或执行报告视为 ACCEPTED。新会话应接着复审，而非假定旧主 agent 已审完。

- 任务：Codex CLI PreToolUse Output Protocol Compatibility。
- 分支：`task/TASK-012-codex-pretooluse-compat`。
- 本次读取的本地 HEAD：`5ba98f73b12a78fe9795445a9667633e9c0c9609`（补充执行报告）。
- 第二轮修复提交：`0599b50a0c5947a49acbac70400c7775f8f0b0eb`。
- 以上是本地快照，**本次未实时核实 GitHub 分支头/推送状态**；新主 agent 必须刷新，不能把此 SHA 当作远端最新值。

触发问题：用户在真实 Codex CLI **v0.162.0** 的临时 project-A 中读 `probe.txt`，SessionStart / UserPromptSubmit / PostToolUse / Stop 完成，但 **PreToolUse Failed**，工具仍成功读出文件；trace 同时存在 GUARD_DECISION=ALLOW、TOOL_CALL、SUCCESS TOOL_RESULT。说明“工具成功”和“账本有 ALLOW”不等于 hook wire 输出被运行时正确接受。

任务协议要求：ALLOW 且未改参数 → `{}` / 空 stdout，exit 0；DENY → 保留 `hookSpecificOutput` 的 `hookEventName="PreToolUse"`、`permissionDecision="deny"`、reason；有 updatedInput 时保留对应结构。不削弱原 fail-closed 保护。

### 第一轮评审（已落盘）

审查实现 `98c5eaea7ae56db6e9e88175b90d099cf863ddd0`，报告 head `86832ff28f0ad02daa8d4d2c668c49a3f4ce5b2e`。生产协议补丁方向认可，执行报告称 358 passed；主 agent 未独立重跑。四项阻塞：

1. 真实 CLI 测试默认复制用户 `~/.codex/auth.json` 到临时目录。
2. 使用 `--dangerously-bypass-approvals-and-sandbox`。
3. ALLOW 没有证明 hook 实际完成；DENY 接受含 constraint/BLOCK 等模型文案，未证明真实拟执行目标动作被 SpecGuard 拦截。
4. subprocess 继承 checkout cwd，在仓库根产生 `.agentcontract/sessions`。

要求：测试认证必须显式 opt-in，否则准确 skip；sandbox 生效；真实 trace 决策与对应工具结果/目标相关联；仅临时项目写入；准确报告 pass/skip；提交推送任务分支，不合并 main。

### 最新 Executor Report（待第二轮审查）

报告称已改为显式 `AGENTCONTRACT_TEST_CODEX_AUTH_JSON` / `CODEX_TEST_AUTH_JSON`、移除全绕过 flag，采用 `--approve-for-me`；增加 Guard trace 断言、`AGENTCONTRACT_SESSION_DIR`、payload cwd fallback 和 subprocess 临时 cwd。

报告测试结果：

- `python -m pytest tests/integrations/test_codex_hooks.py`：22 passed。
- `python -m pytest tests/integrations/test_codex_adapter.py`：16 passed。
- `python -m pytest tests/integrations/test_codex_cli.py`：2 passed / **2 skipped**。
- 全量：**357 passed / 2 skipped / 0 failures**，Python 3.12.9，12.92s。
- 两项真实 CLI ALLOW/DENY 测试因为未配置测试认证而 skip，**此次没有真实运行时验收结果**。
- 临时认证副本清理、用户认证未变等是执行报告声明，本次未独立复核。

报告的 Known limitations / Questions 均写 None，并称“fully verified”；这与在线测试 skip 的事实有差异。新主 agent 需准确评价证据和验收条件，而不是继承这句结论。

### 第二轮需重点核实的静态疑点（不是正式裁决）

本次仅为交接做了源码阅读，未修改任务状态、未执行测试。以下留给主 agent 检查：

- `tests/integrations/test_codex_cli.py` 目前只是查找任意 GUARD_DECISION=ALLOW/BLOCK；是否把决策关联到指定 probe/保护文件动作，并为 ALLOW 关联 SUCCESS ToolResult？是否排除 BLOCK 来自无关动作、锁错误等？
- DENY 仍保留“constraint”等文案检查；新增 trace 断言虽更强，仍需确认实际目标与拒绝原因。
- `--approve-for-me` 被报告描述为保留 workspace-write；命令未显式列出 `--sandbox workspace-write`。需要依据实际安装版本/运行证据确认，不能只看注释。
- subprocess 使用 `shell=True`；应核实 Windows 参数传递、实际执行命令和可移植性是否满足当前任务。
- `finally` 中认证 unlink 失败被忽略；测试初始化部分发生在 try 外。要检查初始化失败时仍能执行必要清理/完整性验证。
- `_verify_real_codex_untouched()` 只验证此前有 hash 的三个文件与新增顶层项，是否能漏掉原本不存在文件的新建、已有其他文件的修改/删除？这是快照覆盖范围问题，不能宣称完全零副作用。
- `AGENTCONTRACT_SESSION_DIR` 和 cwd fallback 是新增生产行为，检查范围、优先级、隔离语义和测试；不能为测试方便引入跨项目状态泄漏。
- 真实测试 skip 是明确允许的无认证处理，但不证明运行时行为。需决定验收是补充受限、显式 opt-in 的真实证据，还是在治理文档中明确保留未验证项；不可把 skip 写成 pass。

## 7. 新会话第一步与后续操作

第一步是**从 GitHub 刷新 TASK-012 并进行第二轮复审**，不重新选题、不创建 TASK-013、不立即合并。

1. 读取 main 和任务分支当前 STATE / TASK-012 / REVIEW_LOG；确认是否已有更晚裁决。若与本文快照不同，以最新权威文件为准并说明变化。
2. 取得远端任务分支当前完整 SHA，与第一轮审查基线及 main 比较；读取实际 diff 和测试，核对 Executor Report。
3. 检查生产 ALLOW/DENY wire、认证隔离、sandbox、状态写入边界、真实工具关联证据和清理失败路径。
4. 能运行测试则按规定执行；不能则写明“静态审查 + 执行报告，未独立复跑”。没有 CI 不是 CI passed。
5. 将具体 verdict 与阻塞点落盘到任务 Main Agent Review 和 append-only REVIEW_LOG，再同步 STATE/TASKS。
6. 如需修复，继续同一任务分支，给执行 agent 一条范围明确、带文件/检查/验收条件的指令。接受时先审集成范围，避免把任务分支旧治理状态整批覆盖回 main；历史已多次使用选择性集成。

用户要求每轮提供简洁可执行指令与可核对结果，关键结论落实到仓库，明确通过/待修复/未验证；避免只给口头规划或“执行 agent 说通过所以通过”。不要把完整审查分析再次塞进执行指令。

## 8. 可复制到新网页端 ChatGPT 的启动消息

```text
你现在接替 AgentContract 的主 agent。旧主 agent 对话《Agent项目选题建议》已达到长度上限。请阅读我上传的 HANDOFF.md，并通过本会话连接的 GitHub 访问 https://github.com/12041720/AgentContract。

你的职责是项目方向、架构、任务拆解、审查验收及治理文件维护；本地执行 agent 负责按活动任务实现和测试。仓库 AGENTS.md、.agent/STATE.md、.agent/TASKS.md、任务文件、.agent/REVIEW_LOG.md 和 docs/ARCHITECTURE.md 是权威来源。不要假定继承了旧会话的连接/权限；先实际检查访问能力。

请先从 GitHub 刷新 main 与 task/TASK-012-codex-pretooluse-compat 的状态和当前 SHA。HANDOFF 快照中 TASK-001～011 已接受，TASK-012 是 CHANGES_REQUESTED round 1，本地已有 0599b50 第二轮修复和 5ba98f7 报告；报告 357 passed、2 skipped，两项真实 Codex ALLOW/DENY 未运行。请确认远端是否已有后续更新，然后进行当前任务复审。

重点核对认证/配置隔离、sandbox、ALLOW 空 stdout、DENY fail-closed、真实 Guard 决策与具体目标动作/ToolResult 的关联、临时状态写入边界和失败清理。区分你独立执行、静态审查、执行 agent 报告和未验证项。不要将 skip 或模型文案当作真实运行时证明，不要复制用户全局认证、修改全局 Codex 配置或绕过 sandbox。

完成审查后按协议落盘 verdict、review log、STATE/TASKS，并给出唯一明确的下一步。不要未经审查接受 TASK-012、合并 main 或自动启动 TASK-013。开发基线是用户本地 Python 3.12.9，不要为兼容测试另装 Python。
```

## 9. 本次交接制作的操作范围

本次仅创建并补充 `HANDOFF.md`，未修改产品代码、权威状态、任务评审或路线图；未运行项目测试、未提交/推送/合并，未在旧对话发送消息。仓库起始 `git status --short` 为空。本文是面向接续开发的摘要，不是原对话逐字归档；原网页已用于补充开发历史、用户要求及末尾中断状态，不再依赖接口末尾五轮的占位回复。
