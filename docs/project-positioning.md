# Agent Context Runtime：Project Positioning and Engineering Success Criteria

## 1. 项目定位

Agent Context Runtime 的目标不是做一个单纯的 Token Monitor，也不是预设某一种上下文压缩算法一定有效。

项目希望构建一个面向 Coding Agent 的、可运行且可验证的上下文运行时，使系统能够：

```text
Observe
→ Diagnose
→ Intervene
→ Rerun
→ Evaluate
→ Account
```

即：

1. 观察 Coding Agent 实际使用了什么上下文；
2. 定位重复、低效或潜在可优化的上下文；
3. 对真实请求实施受控干预；
4. 从相同初始条件重新执行；
5. 独立评估任务质量；
6. 统计完整的运行时成本和后续行为变化。

核心研究问题不是：

> 某一段文本能否少发送一些 Token？

而是：

> 对 Coding Agent 上下文进行干预后，是否能够在保持任务质量的同时降低真实端到端运行成本，以及什么条件决定这种干预是否有效。

因此必须同时考虑：

* immediate token saving；
* downstream tool / model behavior；
* re-read / retry / recovery；
* task quality；
* latency；
* total execution cost。

局部 Token 减少不自动等价于系统级成本降低。

---

## 2. 双出口项目目标

本项目采用 **research-first engineering, outcome-dependent packaging** 的路线。

工程底座必须独立成立，最终研究结果决定项目的进一步出口。

### Research Track

如果实验得到稳定且可复现的现象，例如：

* 某类上下文能够稳定安全省略；
* 总成本显著下降而质量损失可控；
* 存在可解释的 rebound effect；
* 不同任务、上下文类别或模型之间存在稳定规律；
* 能进一步形成 cost-quality aware policy；

则围绕真实 Coding Agent 上下文干预形成 empirical / systems research contribution，并考虑 workshop、CCF-C 或后续更完整研究。

### Engineering Track

如果单一干预的科学收益较弱、不稳定或高度依赖任务，仍保留完整的运行时基础设施，并进一步增强：

* Agent execution visualization；
* context composition analysis；
* token / cost timeline；
* request inspector；
* tool-call trace；
* redundancy diagnostics；
* intervention before/after diff；
* provenance / audit visualization；
* experiment comparison；
* cost-quality report。

最终形成一个可实际运行、可演示、可用于进一步研究和工程项目的 Coding Agent observability and context optimization platform。

因此：

> 负面或弱实验结果不等于工程失败。

只有当系统既无法形成可信实验，也无法形成有价值的 Agent runtime observability / optimization capability 时，才视为整体项目失败。

---

## 3. 工程复杂度来自哪里

项目复杂度不以代码量或组件数量衡量，而来自跨层一致性和真实运行闭环。

### 3.1 多层数据一致性

系统需要保持：

```text
upstream source
→ immutable raw evidence
→ normalized representation
→ field provenance
→ runtime state
→ actual request
→ execution result
→ evaluation
→ cost report
```

任意一层失去绑定都会使实验结论失去可信性。

### 3.2 实际请求观测

不能只保存“程序准备发送的 prompt”。

系统需要区分并尽可能验证：

```text
request draft
→ prepared request
→ actual outbound request
→ provider attempt
```

从而证明一次 context intervention 实际进入了模型请求。

### 3.3 Agent 状态与上下文状态绑定

Coding Agent 的上下文与 repository 状态相互影响。

例如同样一次 `read_file`：

* 文件未变化时可能构成重复；
* 文件发生变化后不能继续视为相同信息。

因此 context analysis 必须和实际文件字节、hash、workspace state 绑定。

### 3.4 真实成本不是局部 Token 数

一次上下文干预可能导致：

```text
prompt token ↓
but
re-read ↑
retry ↑
tool calls ↑
additional model attempts ↑
```

因此必须记录 physical attempts 和后续行为，而不能只计算单次请求差值。

### 3.5 配对实验隔离

Baseline 与 treatment 必须从可比的初始状态重新运行，并分别保留完整证据。

不能通过编辑历史 trajectory 后缀来模拟真实反事实。

### 3.6 Evaluation isolation

评测数据和 runtime 必须隔离，避免 Coding Agent 在运行期间获得私有 evaluator 信息。

这同时是研究可信性和工程安全边界的一部分。

---

## 4. 核心技术能力

MVP 优先采用简单、可审计的技术实现，而不是为了增加技术栈复杂度引入额外基础设施。

核心技术包括：

* Python；
* Pydantic versioned contracts；
* SHA256 content-addressed evidence storage；
* JSON / JSONL persistence；
* field-level provenance；
* fail-closed audit；
* adapter-based external format integration；
* synchronous Agent runtime；
* provider request interception / capture；
* tool execution tracing；
* repository / file-state hashing；
* isolated workspace execution；
* from-scratch paired rerun；
* evaluator isolation；
* usage and cost accounting；
* reproducible reporting；
* CLI orchestration。

后续 Engineering Track 可以增加 Web visualization / interactive experiment inspection，但 UI 不属于首个可信实验闭环的前置条件。

原则：

> 不为了展示“技术复杂度”增加无必要的数据库、分布式服务、消息队列、DAG 引擎或微服务。

项目复杂度应来自真实问题，而不是架构装饰。

---

## 5. 项目成果分层

### L1 — Trusted Evidence Infrastructure

能够证明：

```text
raw evidence
→ normalized representation
→ provenance
→ audit
```

可信、可复查、可阻断篡改。

### L2 — Trusted Agent Runtime

能够运行真实 Coding Agent，并捕获：

* initial state；
* actual requests；
* model attempts；
* tool calls；
* exact file reads；
* execution events；
* provider usage。

### L3 — Controlled Experiment Runtime

能够执行：

```text
baseline
vs
treatment
```

的独立配对运行，并验证：

* 初始环境一致；
* intervention 确实生效；
* 两次运行证据彼此独立；
* evaluator 不泄漏；
* 成本完整统计。

### L4 — Context Optimization Evidence

至少一种 context intervention 能够在真实任务上被系统性测量，包括：

* candidate coverage；
* intervention acceptance / rejection；
* immediate saving；
* downstream rebound；
* task-quality difference；
* total-cost difference。

是否出现正收益属于实验结果，而不是系统验收前提。

### L5 — Demonstrable Engineering System

若进入 Engineering Track，系统应能够交互式展示：

* Agent execution timeline；
* context composition；
* token and cost breakdown；
* tool / file usage；
* detected redundancy；
* intervention evidence；
* before / after request；
* baseline / treatment comparison；
* evaluation result；
* provenance / audit state。

---

## 6. 验收指标体系

项目不使用单一的 “Token saving percentage” 作为成功标准。

### 6.1 Runtime / Engineering

关注系统是否真的工作：

* real task execution coverage；
* completed-run rate；
* request capture coverage；
* provider-attempt accounting coverage；
* tool-event capture coverage；
* reproducible report generation。

### 6.2 Evidence / Trust

关注实验是否可信：

* raw artifact integrity；
* provenance coverage；
* actual-sent-request verification；
* initial-state alignment；
* mutation / tamper detection；
* unresolved BLOCK count。

对于进入正式分析的 run，关键 evidence 不允许通过默认值、推测或静默修复补齐。

### 6.3 Optimization

关注优化是否真的减少系统资源：

* input token difference；
* total token difference；
* API monetary-cost difference；
* wall-clock difference；
* model-attempt difference；
* tool-call difference。

### 6.4 Rebound

必须单独报告：

* re-read rate；
* retry rate；
* additional model attempts；
* additional tool calls；
* recovered token consumption；
* recovered monetary cost。

### 6.5 Task Quality

至少包括：

* task completion；
* patch validity；
* test execution；
* passed / failed tests；
* benchmark/evaluator result；
* infrastructure error rate。

---

## 7. 指标解释原则

所有指标必须区分：

```text
target
measurement
observation
conclusion
```

工程目标可以提前定义。

实验结果不能提前定义。

例如：

```text
request capture coverage = 100%
```

可以作为工程验收要求，因为这是系统自己能够控制的能力。

但：

```text
token saving >= 20%
```

不能作为证明系统成功的工程硬门槛，因为它属于尚未得到的科学结果。

同理：

> “没有质量下降”

必须来自 paired evaluation，而不能从 Token 减少推断。

---

## 8. 每个 Milestone 的双重验收

从 M2 开始，每个 milestone 完成时同时回答两组问题。

### Research readiness

1. 新增能力使我们能够回答什么科学问题？
2. 新增了什么可观测事实？
3. 哪些变量现在能够被控制？
4. 哪些 claim 仍然不能做？

### Engineering readiness

1. 解决了什么真实工程问题？
2. 主要技术难点是什么？
3. 使用了哪些关键技术？
4. 哪些 failure modes 已处理？
5. 用什么指标证明该模块完成？
6. 当前有哪些可演示的实际能力？

这两组回答应随 milestone status 一起维护，但不得用展示价值替代研究证据。

---

## 9. 项目成功的最终定义

项目成功不要求预先证明某一种 context optimization policy 一定有效。

最低成功条件是：

> 构建一个能够真实运行 Coding Agent、准确观察上下文与成本、实施可验证干预，并可信评估其结果的 Agent Context Runtime。

在此基础上：

* 有稳定 optimization finding → 形成 Research Track；
* optimization finding 较弱 → 强化 Engineering Track；
* 两者同时成立 → 形成完整的 research prototype / engineering platform。

系统必须先真实、可复现、可验收，再追求复杂策略或展示效果。
