# Agent Context Runtime: Stable Instructions

## 核心原则

1. **计划优先**：与 `agent-context-runtime-mvp-plan.md` 冲突时，以计划为准。必须先报告冲突，再扩展范围。

2. **证据驱动**：任何结论必须有可追溯的原始证据（源 → SHA256 → 规范化产物 → 出处 → 审计）。禁止推断缺失信息（prompts、状态、缓存、提供商行为、评测结果）。

3. **内容标识**：hash 标识字节内容，不标识出现次数。逻辑/事件或源位置标识独立于内容重复。

4. **未知处理**：`unknown`、`not_applicable`、零/空/假互不相同。缺失证据必须阻断（fail-closed）。禁止用 `"unknown"` 等魔法字符串表示认知未知；使用 `Fact/status/reason` 语义。

5. **审计阻断**：缺失 blob、hash 不匹配、定位符错误、出处缺失/冲突、来源/生产者不匹配、不可验证的观测声明 → 一律 BLOCK，不得静默修复。

6. **异常安全**：格式错误的持久化证据产生确定性 BLOCK/AuditFinding；格式错误的用户输入不得转义为未处理的解析器/索引/键异常。

## 架构边界

* contracts、visibility、state、candidates、interventions、accounting、evaluation、runtime 保持逻辑独立。**Evaluation 必须作为独立进程执行，private evaluator inputs 不得进入 runtime。**
* `ports.py` 只包含 `TrajectoryAdapter`、`Provider`、`Runtime`、`Evaluator` 四个 Protocol。不加注册器、DI、插件系统、事件总线、DAG 引擎、ORM、通用中间件。
* 存储只用本地 JSON/JSONL + 内容寻址 blob。不加数据库、仪表盘、图服务、分布式编排器。
* 历史数组/消息顺序仅认 `source_position`，未经上游证明不得提升为权威运行时顺序或未来可见性。
* 顶层持久记录使用 `Envelope` 约定（schema 版本 `1.0`），复用 `acr.contracts.Provenance`，不加平行出处 schema。

## 里程碑隔离

* 只实现当前明确要求的里程碑。前一道门未关，不开始后续的 runtime、provider、candidate、intervention、paired rerun、evaluator、accounting 工作。
* 不创建合成证据替代缺失的上游产物。缺失输入记录为 blocked/unknown + 原因。
* 来源清单（source manifest）与生产者清单（producer manifest）分离：来源说明原始出处，生产者说明生成产物的代码/配置/格式。
* 完成前必须：运行测试和 lint → 检查工作区 → 仅提交验证过的变更 → 按需推送。
* 回归不变量累积：新增审计/完整性门禁时，不得移除或削弱已有门禁/测试，除非冻结架构明确替代且有文档记录。

## Git 与凭证安全

* 使用仓库已配置的认证 Git 传输（credential helper 或 SSH agent）。
* **禁止**在任何命令、URL、日志、文档、提交、`https://<TOKEN>@github.com/...` URL 中放入 PAT、token、密码、私钥内容。
* **禁止** cat/echo/print/copy 或记录密钥文件、本地密钥路径、凭证环境变量值、私钥材料。敏感信息总结需安全脱敏。
* 认证传输不可用时，停止推送并报告：`push unavailable: authenticated Git transport not available`。
* 提交前检查暂存 diff 中是否含 `.env`、凭证、token、私钥、密钥配置。未经明确批准不得 force-push 或重写历史。
* 安全提交流程（依赖已配置认证，不嵌入凭证）：

```bash
git status --short
git diff --check
git add -- <reviewed-paths>
git diff --cached --check
git diff --cached
git commit -m "<accurate message>"
git push origin HEAD
git status --short
git rev-parse HEAD
```

* 若需使用环境变量中的 GitHub credential，用此方式（不打印/导出/持久化）：

```bash
GITHUB_TOKEN="${GITHUB_PAT_TOKEN:?GITHUB_PAT_TOKEN is required}" git push origin HEAD
```

`GITHUB_PAT_TOKEN` 仅为环境变量标识符，值必须保密，不得显示、嵌入 URL、写入文件或提交。

* 若 `git push origin HEAD` 认证失败，报告 push-unavailable 消息，禁止改用 token-bearing URL 或检查密钥材料。
* 提交内容影响里程碑状态、实现检查点或交接上下文时，在同一工作会话中更新 `docs/project-status.md`。纯上下文提交可定义上下文基线为仓库 HEAD，而非嵌入会自失效的精确 SHA。
