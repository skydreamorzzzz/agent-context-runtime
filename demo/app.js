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
  if (Number.isNaN(timestamp.valueOf())) return "time unavailable";
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
        <p class="card-label">${isPass ? "Last verified pass" : "First verified fail"}</p>
        <code class="state-command">${escapeHtml(verifier)}</code>
        <div class="state-meta">
          <span title="${escapeHtml(receipt.checkpoint_id)}">checkpoint ${escapeHtml(shortId(receipt.checkpoint_id))}</span>
          <span>${escapeHtml(formatTime(receipt.timestamp))}</span>
        </div>
      </div>
      <div class="exit-code">
        <span>Exit code</span>
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
            >${hasDiff ? "View diff" : "Diff unavailable"}</button>
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
    : '<span class="activity-pill">Activity details unavailable</span>';
  return `
    <div class="activity-block">
      <p class="section-label">Observed between verification boundaries</p>
      <div class="activity-list">${pills}</div>
    </div>`;
}

function overviewBlock(session) {
  const status = session.summary.overall_status || "green";
  const label = status === "red" ? "FAILED" : status === "yellow" ? "WARNING" : "HEALTHY";
  const count = session.summary.changed_file_count;
  return `
    <section class="overview-panel panel-card">
      <div>
        <p class="section-label">Session overview</p>
        <h2>${escapeHtml(session.presentation.title)}</h2>
        <p class="panel-copy">${escapeHtml(session.presentation.description)}</p>
      </div>
      <div class="overview-status status-${status}">
        <span class="status-dot"></span><strong>${label}</strong>
        <small>${session.summary.verified_fail_present ? "Verified failure observed" : "No verified failure"}</small>
      </div>
      <div class="overview-metrics">
        <span><b>1</b><small>PASS boundary</small></span>
        <span><b>1</b><small>FAIL boundary</small></span>
        <span><b>${count}</b><small>changed ${count === 1 ? "file" : "files"}</small></span>
        <span><b>${session.summary.diagnostic_warning_count}</b><small>heuristic warnings</small></span>
      </div>
    </section>`;
}

function diagnosticBlock(items) {
  return `
    <section class="dashboard-panel diagnostics-panel">
      <div class="panel-heading">
        <div><p class="section-label">Legacy diagnostic layer</p><h2>W01–W08 diagnostic signals</h2></div>
        <span class="panel-note">Heuristic signals are not causal attribution.</span>
      </div>
      <div class="signal-grid">${items.map((item) => `
        <article class="signal-card signal-${escapeHtml(item.severity)}">
          <div class="signal-top"><span class="signal-code">${escapeHtml(item.rule)}</span><span class="signal-state">${escapeHtml(item.status === "warning" ? "SUSPECTED REDUNDANCY" : item.status === "normal" ? "NORMAL" : "NOT EVALUATED")}</span></div>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.summary)}</p>
          ${item.status === "warning" ? `<small>${escapeHtml(item.occurrences)} occurrence${item.occurrences === 1 ? "" : "s"} · worth inspecting · demo metadata</small>${item.event_sequences.length ? `<div class="affected-steps"><span>Affected steps</span>${item.event_sequences.map((sequence) => `<b>#${escapeHtml(sequence)}</b>`).join("")}</div>` : ""}` : ""}
        </article>`).join("")}</div>
      <p class="metadata-note">Annotations marked as heuristic are demo presentation metadata; privacy-bounded F1 evidence does not contain the bodies needed to evaluate every signal.</p>
    </section>`;
}

function timelineBlock(items) {
  return `
    <section class="dashboard-panel timeline-panel">
      <div class="panel-heading"><div><p class="section-label">Observed sequence</p><h2>Incident timeline</h2></div><span class="panel-note">No causal claim</span></div>
      <div class="timeline-list">${items.map((item) => `
        <div class="timeline-item timeline-${escapeHtml(item.status)}">
          <span class="timeline-marker">${item.status === "green" ? "✓" : item.status === "red" ? "×" : "•"}</span>
          <div><strong>${escapeHtml(item.label)} <span class="timeline-status">${escapeHtml(item.status)}</span></strong><p>${item.sequence === null ? "" : `sequence ${escapeHtml(item.sequence)} · `}${escapeHtml(item.detail)}</p>${item.diagnostic_refs.length ? `<div class="timeline-diagnostics">${item.diagnostic_refs.map((ref) => `<span>${escapeHtml(ref.rule)} ${escapeHtml(ref.title)}</span>`).join("")}</div>` : ""}</div>
        </div>`).join("")}</div>
    </section>`;
}

function integrityBlock(integrity) {
  return `<section class="dashboard-panel evidence-panel"><div class="panel-heading"><div><p class="section-label">Evidence integrity</p><h2>Trusted boundary checks</h2></div><span class="healthy-badge">${integrity.status === "verified" ? "✓ VERIFIED" : "! UNSUPPORTED"}</span></div><div class="check-list">${integrity.checks.map((item) => `<div class="check-row"><span class="check-icon ${item.status === "pass" ? "" : "check-fail"}">${item.status === "pass" ? "✓" : "×"}</span><span>${escapeHtml(item.label)}</span><small>${escapeHtml(item.detail || item.status)}</small></div>`).join("")}</div></section>`;
}

function privacyBlock(privacy) {
  return `<section class="dashboard-panel privacy-panel"><div class="panel-heading"><div><p class="section-label">Privacy boundary</p><h2>What stays out of the journal</h2></div><span class="healthy-badge">✓ ENFORCED</span></div><div class="privacy-columns"><div><small class="subheading">Captured</small>${privacy.captured.map((item) => `<span class="privacy-item captured">✓ ${escapeHtml(item)}</span>`).join("")}</div><div><small class="subheading">Not persisted</small>${privacy.not_persisted.map((item) => `<span class="privacy-item">× ${escapeHtml(item)}</span>`).join("")}</div></div><p class="metadata-note">${escapeHtml(privacy.diagnostic_note)}</p></section>`;
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
          <p class="section-label">Captured repository state</p>
          <h2>Repository state changed</h2>
        </div>
        <span class="file-count">${count} changed ${noun}</span>
      </header>
      ${fileRows(session.changed_files)}
    </article>
    ${connector()}
    ${stateCard("fail", session.first_fail, session.verifier)}
    <aside class="boundary-card">
      <div>
        <p class="boundary-kicker">Failure boundary</p>
        <p class="boundary-copy">
          <strong>${count} captured repository ${noun} changed</strong> between the last verified
          PASS and the first verified FAIL.
        </p>
      </div>
      <div class="coming-next" aria-label="Workspace fork is not yet available"><span>Fork last passing state</span>Coming next</div>
    </aside>`;

  elements.demo.insertAdjacentHTML("beforeend", `${integrityBlock(session.evidence_integrity)}${privacyBlock(session.privacy_boundary)}`);

  document.querySelectorAll(".diff-toggle").forEach((button) => {
    button.addEventListener("click", () => {
      const panel = document.getElementById(button.dataset.diffTarget);
      const isOpen = panel.classList.toggle("is-open");
      button.setAttribute("aria-expanded", String(isOpen));
      button.textContent = isOpen ? "Hide diff" : "View diff";
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
    elements.error.textContent = `${error.message} Build demo/data/sessions.json and serve the demo over HTTP.`;
    elements.error.classList.remove("is-hidden");
  }
}

start();
