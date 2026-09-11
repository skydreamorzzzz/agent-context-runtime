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

function renderSession(session) {
  elements.sessionTitle.textContent = session.presentation.title;
  elements.sessionId.textContent = session.session_id;
  elements.verifier.textContent = session.verifier;
  const count = session.summary.changed_file_count;
  const noun = count === 1 ? "file" : "files";
  elements.demo.innerHTML = `
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
      <div class="coming-next" aria-label="Workspace fork is not yet available">
        <span>Fork last passing state</span>
        Coming next
      </div>
    </aside>`;

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
