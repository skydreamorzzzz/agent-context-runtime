const dataUrl = "data/sessions.json";

const elements = {
  demo: document.querySelector("#demo"),
  error: document.querySelector("#error"),
  loading: document.querySelector("#loading"),
  sessionControl: document.querySelector("#session-control"),
  sessionId: document.querySelector("#session-id"),
  sessionSelect: document.querySelector("#session-select"),
  sessionTitle: document.querySelector("#session-title"),
  verifier: document.querySelector("#verifier"),
};

const escapeHtml = (value) =>
  String(value ?? "").replace(
    /[&<>'"]/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[
        character
      ],
  );

const shortId = (value) => {
  const text = String(value ?? "");
  if (text.length <= 20) return text;
  return `${text.slice(0, 12)}…${text.slice(-7)}`;
};

const formatTime = (value) => {
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.valueOf())) return "时间不可用";
  return timestamp.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
};

function stateCard(kind, receipt, verifier) {
  const isPass = kind === "pass";
  return `
    <article class="state-card ${kind}">
      <div class="state-icon" aria-hidden="true">${isPass ? "✓" : "×"}</div>
      <div>
        <p class="card-label">${isPass ? "最后已验证通过" : "首次已验证失败"}</p>
        <code class="state-command">${escapeHtml(verifier)}</code>
        <div class="state-meta">
          <span title="${escapeHtml(receipt.checkpoint_id)}">checkpoint ${escapeHtml(shortId(receipt.checkpoint_id))}</span>
          <span>${escapeHtml(formatTime(receipt.timestamp))}</span>
        </div>
      </div>
      <div class="exit-code">
        <span>退出码</span>
        <strong>${escapeHtml(receipt.exit_code)}</strong>
      </div>
    </article>`;
}

function connector() {
  return '<div class="connector" aria-hidden="true"><span>↓</span></div>';
}

function diffLines(value) {
  return String(value ?? "")
    .split("\n")
    .map((line) => {
      let lineClass = "";
      if (line.startsWith("+++") || line.startsWith("---")) lineClass = "diff-header";
      else if (line.startsWith("+")) lineClass = "diff-add";
      else if (line.startsWith("-")) lineClass = "diff-remove";
      else if (line.startsWith("@@")) lineClass = "diff-hunk";
      return `<span class="diff-line ${lineClass}">${escapeHtml(line)}</span>`;
    })
    .join("");
}

function fileRows(files) {
  return files
    .map((file, index) => {
      const hasDiff = file.diff_status === "available" && file.diff;
      return `
        <div class="file-entry">
          <div class="file-row">
            <span class="file-name">${escapeHtml(file.path)}</span>
            <span class="change-type">${escapeHtml(file.change_type)}</span>
            <button
              class="diff-toggle"
              type="button"
              data-diff-target="diff-${index}"
              aria-expanded="false"
              ${hasDiff ? "" : "disabled"}
            >${hasDiff ? "查看 diff" : "Diff 不可用"}</button>
          </div>
          <div id="diff-${index}" class="diff-panel">
            <code class="diff-code">${hasDiff ? diffLines(file.diff) : ""}</code>
          </div>
        </div>`;
    })
    .join("");
}

function activityBlock(items) {
  const pills = items.length
    ? items
        .map((item) => `<span class="activity-pill">${escapeHtml(item.label)}</span>`)
        .join("")
    : '<span class="activity-pill">操作详情不可用</span>';
  return `
    <div class="activity-block">
      <p class="section-label">验证边界之间的已观测操作</p>
      <div class="activity-list">${pills}</div>
    </div>`;
}

function overviewBlock(session) {
  const status = session.summary.overall_status || "green";
  const label = status === "red" ? "失败" : status === "yellow" ? "警告" : "正常";
  const count = session.summary.changed_file_count;
  return `
    <section class="overview-panel panel-card">
      <div>
        <p class="section-label">会话概览</p>
        <h2>${escapeHtml(session.presentation.title)}</h2>
        <p class="panel-copy">${escapeHtml(session.presentation.description)}</p>
      </div>
      <div class="overview-status status-${status}">
        <span class="status-dot"></span><strong>${label}</strong>
        <small>${session.summary.verified_fail_present ? "已观测到验证失败" : "未观测到验证失败"}</small>
      </div>
      <div class="overview-metrics">
        <span><b>1</b><small>PASS 边界</small></span>
        <span><b>1</b><small>FAIL 边界</small></span>
        <span><b>${count}</b><small>个变化文件</small></span>
        <span><b>${session.summary.diagnostic_warning_count}</b><small>条诊断信号</small></span>
      </div>
    </section>`;
}

function diagnosticBlock(items) {
  return `
    <section class="dashboard-panel diagnostics-panel">
      <div class="panel-heading">
        <div><p class="section-label">Legacy + demo_raw</p><h2>冗余诊断信号</h2></div>
        <span class="panel-note">诊断信号不代表因果归因</span>
      </div>
      <div class="signal-grid">${items.map((item) => `
        <article class="signal-card signal-${escapeHtml(item.severity)}">
          <div class="signal-top"><span class="signal-code">${escapeHtml(item.rule)}</span><span class="signal-state">${escapeHtml(item.status === "warning" ? "疑似冗余" : item.status === "normal" ? "正常" : "未评估")}</span></div>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.summary)}</p>
          ${item.status === "warning" ? `<small>${escapeHtml(item.occurrences)} 次 · 值得检查 · 来源 ${escapeHtml(item.source)}</small>${item.event_sequences.length ? `<div class="affected-steps"><span>关联步骤</span>${item.event_sequences.map((sequence) => `<b>#${escapeHtml(sequence)}</b>`).join("")}</div>` : ""}` : ""}
        </article>`).join("")}</div>
      <p class="metadata-note">W01–W08 未评估不等于正常；D01/D02 仅是 demo_raw 上的 exact compatible signals，不冒充完整 W04/W06。</p>
    </section>`;
}

function timelineBlock(items) {
  return `
    <section class="dashboard-panel timeline-panel">
      <div class="panel-heading"><div><p class="section-label">已观测顺序</p><h2>执行轨迹</h2></div><span class="panel-note">不代表因果归因</span></div>
      <div class="timeline-list">${items.map((item) => `
        <div class="timeline-item timeline-${escapeHtml(item.status)}">
          <span class="timeline-marker">${item.status === "green" ? "✓" : item.status === "red" ? "×" : "•"}</span>
          <div><strong>${escapeHtml(item.label)} <span class="timeline-status">${escapeHtml(item.status)}</span></strong><p>${item.sequence === null ? "" : `步骤 ${escapeHtml(item.sequence)} · `}${escapeHtml(item.detail)}</p>${item.diagnostic_refs.length ? `<div class="timeline-diagnostics">${item.diagnostic_refs.map((ref) => `<span>${escapeHtml(ref.rule)} ${escapeHtml(ref.title)} · ${escapeHtml(ref.source)}</span>`).join("")}</div>` : ""}</div>
        </div>`).join("")}</div>
    </section>`;
}

function integrityBlock(integrity) {
  return `<section class="dashboard-panel evidence-panel"><div class="panel-heading"><div><p class="section-label">证据完整性</p><h2>可信边界检查</h2></div><span class="healthy-badge">${integrity.status === "verified" ? "✓ 已验证" : "! 不支持"}</span></div><div class="check-list">${integrity.checks.map((item) => `<div class="check-row"><span class="check-icon ${item.status === "pass" ? "" : "check-fail"}">${item.status === "pass" ? "✓" : "×"}</span><span>${escapeHtml(item.label)}</span><small>${escapeHtml(item.detail || item.status)}</small></div>`).join("")}</div></section>`;
}

function privacyBlock(privacy) {
  return `<section class="dashboard-panel privacy-panel"><div class="panel-heading"><div><p class="section-label">隐私边界</p><h2>F1 journal 不保存的内容</h2></div><span class="healthy-badge">✓ 已执行</span></div><div class="privacy-columns"><div><small class="subheading">已捕获</small>${privacy.captured.map((item) => `<span class="privacy-item captured">✓ ${escapeHtml(item)}</span>`).join("")}</div><div><small class="subheading">F1 未持久化</small>${privacy.not_persisted.map((item) => `<span class="privacy-item">× ${escapeHtml(item)}</span>`).join("")}</div></div><p class="metadata-note">${escapeHtml(privacy.diagnostic_note)}</p></section>`;
}

function renderSession(session) {
  elements.sessionTitle.textContent = session.presentation.title;
  elements.sessionId.textContent = session.session_id;
  elements.verifier.textContent = session.verifier;
  const count = session.summary.changed_file_count;
  const noun = count === 1 ? "file" : "files";
  elements.demo.innerHTML = `
    ${overviewBlock(session)}
    ${diagnosticBlock(session.diagnostics)}
    ${timelineBlock(session.timeline)}
    ${stateCard("pass", session.last_pass, session.verifier)}
    ${connector()}
    ${activityBlock(session.observed_activity)}
    ${connector()}
    <article class="change-card">
      <header class="change-heading">
        <div>
          <p class="section-label">已捕获仓库状态</p>
          <h2>仓库状态变化</h2>
        </div>
        <span class="file-count">${count} 个变化文件</span>
      </header>
      ${fileRows(session.changed_files)}
    </article>
    ${connector()}
    ${stateCard("fail", session.first_fail, session.verifier)}
    <aside class="boundary-card">
      <div>
        <p class="boundary-kicker">失败边界</p>
        <p class="boundary-copy">
          最后一次已验证 PASS 与首次已验证 FAIL 之间，
          <strong>${count} 个已捕获仓库文件发生变化</strong>。
        </p>
      </div>
      <div class="coming-next" aria-label="Workspace Fork 尚不可用"><span>Fork last passing state</span>后续提供</div>
    </aside>`;

  elements.demo.insertAdjacentHTML("beforeend", `${integrityBlock(session.evidence_integrity)}${privacyBlock(session.privacy_boundary)}`);

  document.querySelectorAll(".diff-toggle").forEach((button) => {
    button.addEventListener("click", () => {
      const panel = document.getElementById(button.dataset.diffTarget);
      const isOpen = panel.classList.toggle("is-open");
      button.setAttribute("aria-expanded", String(isOpen));
    button.textContent = isOpen ? "收起 diff" : "查看 diff";
    });
  });
}

function configureSessionSelector(sessions) {
  if (sessions.length <= 1) return;
  elements.sessionSelect.innerHTML = sessions
    .map(
      (session, index) =>
        `<option value="${index}">${escapeHtml(session.presentation.title)}</option>`,
    )
    .join("");
  elements.sessionControl.classList.remove("is-hidden");
  elements.sessionSelect.addEventListener("change", (event) => {
    renderSession(sessions[Number(event.target.value)]);
  });
}

async function start() {
  try {
    const response = await fetch(dataUrl, { cache: "no-store" });
    if (!response.ok) throw new Error(`Demo data request failed (${response.status})`);
    const payload = await response.json();
    if (!Array.isArray(payload.sessions) || payload.sessions.length === 0) {
      throw new Error("No supported demo sessions were generated.");
    }
    configureSessionSelector(payload.sessions);
    renderSession(payload.sessions[0]);
    elements.loading.classList.add("is-hidden");
    elements.demo.classList.remove("is-hidden");
  } catch (error) {
    elements.loading.classList.add("is-hidden");
    elements.error.textContent = `${error.message} 请先生成 demo/data/sessions.json，并通过 HTTP 提供页面。`;
    elements.error.classList.remove("is-hidden");
  }
}

start();
