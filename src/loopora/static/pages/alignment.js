document.addEventListener("DOMContentLoaded", () => {
  const panel = document.querySelector("[data-testid='loop-alignment-panel']");
  if (!panel || !window.LooporaUI) {
    return;
  }

  const profiles = JSON.parse(document.getElementById("executor-profiles-json")?.textContent || "[]");
  const startForm = document.getElementById("alignment-start-form");
  const executorInput = document.getElementById("alignment-executor-kind");
  const workdirInput = document.getElementById("alignment-workdir");
  const messageInput = document.getElementById("alignment-message");
  const modelInput = document.getElementById("alignment-model");
  const effortInput = document.getElementById("alignment-reasoning-effort");
  const executorModeInput = document.getElementById("alignment-executor-mode");
  const modeButtons = Array.from(document.querySelectorAll("[data-alignment-mode-choice]"));
  const modeNote = document.getElementById("alignment-executor-mode-note");
  const presetCard = document.getElementById("alignment-preset-card");
  const commandCard = document.getElementById("alignment-command-card");
  const presetState = document.getElementById("alignment-preset-state");
  const commandState = document.getElementById("alignment-command-state");
  const presetBody = document.getElementById("alignment-preset-body");
  const presetEmpty = document.getElementById("alignment-preset-empty");
  const reasoningField = document.getElementById("alignment-reasoning-field");
  const reasoningNote = document.getElementById("alignment-reasoning-note");
  const commandCliInput = document.getElementById("alignment-command-cli");
  const commandCliNote = document.getElementById("alignment-command-cli-note");
  const commandArgsInput = document.getElementById("alignment-command-args");
  const sendButton = document.getElementById("alignment-send-button");
  const newSessionButton = document.getElementById("alignment-new-session-button");
  const errorBox = document.getElementById("alignment-error");
  const statusPill = document.getElementById("alignment-status-pill");
  const chat = document.getElementById("alignment-chat");
  const sessionMeta = document.getElementById("alignment-session-meta");
  const transcriptEl = document.getElementById("alignment-transcript");
  const consoleOutput = document.getElementById("alignment-console-output");
  const cancelButton = document.getElementById("alignment-cancel-button");
  const replyForm = document.getElementById("alignment-reply-form");
  const replyInput = document.getElementById("alignment-reply-message");
  const readyPreview = document.getElementById("alignment-ready-preview");
  const previewTitle = document.getElementById("bundle-preview-title");
  const readyNote = document.getElementById("alignment-ready-note");
  const specPreview = document.getElementById("alignment-spec-preview");
  const roleList = document.getElementById("alignment-role-list");
  const workflowDiagram = document.getElementById("alignment-workflow-diagram");
  const yamlSource = document.getElementById("alignment-yaml-source");
  const importRunButton = document.getElementById("alignment-import-run-button");
  const bundleImportForm = document.getElementById("bundle-import-form");
  const bundleImportError = document.getElementById("bundle-import-error");
  const bundleImportPath = document.getElementById("bundle-import-path");
  const bundleImportYaml = document.getElementById("bundle-import-yaml");
  const bundlePreviewButton = document.getElementById("bundle-preview-button");
  const bundlePreviewImportButton = document.getElementById("bundle-preview-import-button");

  const ACTIVE_STATUSES = new Set(["running", "validating", "repairing"]);
  const REPLY_STATUSES = new Set(["waiting_user", "ready", "failed"]);
  const SESSION_STORAGE_KEY = "loopora:alignment-session:v1";
  const EVENT_TYPES = [
    "alignment_session_created",
    "alignment_started",
    "alignment_user_message",
    "alignment_message",
    "alignment_waiting_user",
    "alignment_bundle_written",
    "alignment_validation_passed",
    "alignment_validation_failed",
    "alignment_repair_started",
    "alignment_ready",
    "alignment_failed",
    "alignment_cancel_requested",
    "alignment_cancelled",
    "alignment_imported",
    "alignment_import_failed",
    "alignment_run_started",
    "alignment_run_start_failed",
    "codex_event",
    "stream_error",
  ];
  let currentSession = null;
  let currentPreviewSource = "";
  let eventSource = null;
  let latestEventId = 0;

  function localeText(zh, en) {
    return window.LooporaUI.pickText({zh, en});
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function profileFor(kind) {
    return profiles.find((profile) => profile.key === kind) || profiles[0] || {};
  }

  function setBilingualText(element, zh, en) {
    if (!element) {
      return;
    }
    const zhNode = document.createElement("span");
    zhNode.dataset.lang = "zh";
    zhNode.textContent = String(zh || "");
    const enNode = document.createElement("span");
    enNode.dataset.lang = "en";
    enNode.textContent = String(en || "");
    element.replaceChildren(zhNode, enNode);
  }

  function setStatus(message, kind = "") {
    statusPill.textContent = message;
    statusPill.className = `alignment-status-pill${kind ? ` is-${kind}` : ""}`;
  }

  function showError(message) {
    if (!message) {
      errorBox.hidden = true;
      errorBox.textContent = "";
      return;
    }
    errorBox.hidden = false;
    errorBox.textContent = message;
  }

  function setBusy(isBusy) {
    sendButton.disabled = isBusy;
    sendButton.setAttribute("aria-busy", String(isBusy));
  }

  function defaultCommandArgsText(profile) {
    return Array.isArray(profile?.command_args_template) ? profile.command_args_template.join("\n") : "";
  }

  function isCommandMode() {
    const profile = profileFor(executorInput.value);
    return String(executorModeInput?.value || "preset") === "command" || Boolean(profile.command_only);
  }

  function renderEffortOptions(profile, currentValue = "") {
    effortInput.innerHTML = "";
    const options = Array.isArray(profile.effort_options) && profile.effort_options.length
      ? profile.effort_options
      : [""];
    options.forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value || localeText("默认", "Default");
      effortInput.append(option);
    });
    const fallback = profile.effort_default || "";
    effortInput.value = options.includes(currentValue) ? currentValue : fallback;
  }

  const commandDrafts = new Map();
  let lastExecutorKind = executorInput?.value || "codex";

  function saveCommandDraft(profileKey = lastExecutorKind) {
    if (!profileKey || !commandCliInput || !commandArgsInput) {
      return;
    }
    commandDrafts.set(profileKey, {
      cli: commandCliInput.value || "",
      args: commandArgsInput.value || "",
    });
  }

  function loadCommandDraft(profile) {
    if (!profile || !commandCliInput || !commandArgsInput) {
      return;
    }
    const saved = commandDrafts.get(profile.key);
    if (saved) {
      commandCliInput.value = saved.cli || profile.cli_name || "";
      commandArgsInput.value = saved.args || defaultCommandArgsText(profile);
      return;
    }
    commandCliInput.value = commandCliInput.value.trim() && commandCliInput.dataset.autofilled !== "true"
      ? commandCliInput.value
      : profile.cli_name || "";
    commandCliInput.dataset.autofilled = "true";
    commandArgsInput.value = commandArgsInput.value.trim() && commandArgsInput.dataset.autofilled !== "true"
      ? commandArgsInput.value
      : defaultCommandArgsText(profile);
    commandArgsInput.dataset.autofilled = "true";
  }

  function setAlignmentMode(nextMode) {
    const profile = profileFor(executorInput.value);
    executorModeInput.value = profile.command_only ? "command" : nextMode;
    updateExecutorControls({preserveUserModel: true, preserveUserEffort: true});
  }

  function updateModeButtons(profile, commandMode) {
    modeButtons.forEach((button) => {
      const mode = button.dataset.alignmentModeChoice || "";
      const active = commandMode ? mode === "command" : mode === "preset";
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
      if (mode === "preset") {
        button.disabled = Boolean(profile.command_only);
      }
    });
  }

  function updateCommandInputs(profile, commandMode) {
    if (commandMode) {
      loadCommandDraft(profile);
      commandCliInput.readOnly = false;
      commandArgsInput.readOnly = false;
      return;
    }
    commandCliInput.value = profile.cli_name || "";
    commandArgsInput.value = defaultCommandArgsText(profile);
    commandCliInput.readOnly = true;
    commandArgsInput.readOnly = true;
  }

  function updateExecutorControls(options = {}) {
    const profile = profileFor(executorInput.value);
    if (profile.command_only && executorModeInput.value !== "command") {
      executorModeInput.value = "command";
    }
    const commandMode = isCommandMode();
    const preserveUserModel = options.preserveUserModel !== false;
    const preserveUserEffort = options.preserveUserEffort !== false;
    const previousModelDefault = modelInput.dataset.defaultModel || "";
    const previousEffortDefault = effortInput.dataset.defaultEffort || "";
    const currentModel = modelInput.value.trim();
    const currentEffort = effortInput.value.trim();
    const modelWasDefault = !currentModel || currentModel === previousModelDefault;
    const effortWasDefault = !currentEffort || currentEffort === previousEffortDefault;

    modelInput.placeholder = profile.model_placeholder_zh || profile.model_placeholder_en || profile.default_model || "";
    if ((!preserveUserModel || modelWasDefault) && profile.default_model !== undefined) {
      modelInput.value = profile.default_model || "";
    }
    modelInput.dataset.defaultModel = profile.default_model || "";
    renderEffortOptions(profile, (!preserveUserEffort || effortWasDefault) ? (profile.effort_default || "") : currentEffort);
    effortInput.dataset.defaultEffort = profile.effort_default || "";

    presetCard?.classList.toggle("is-active", !commandMode && !profile.command_only);
    presetCard?.classList.toggle("is-inactive", commandMode || profile.command_only);
    commandCard?.classList.toggle("is-active", commandMode);
    commandCard?.classList.toggle("is-inactive", !commandMode);
    if (presetState) {
      presetState.hidden = commandMode || profile.command_only;
    }
    if (commandState) {
      commandState.hidden = !commandMode;
    }
    if (presetBody) {
      presetBody.hidden = Boolean(profile.command_only);
    }
    if (presetEmpty) {
      presetEmpty.hidden = !profile.command_only;
    }
    if (reasoningField) {
      reasoningField.hidden = Boolean(profile.command_only);
    }
    modelInput.readOnly = commandMode;
    effortInput.disabled = commandMode || Boolean(profile.command_only);

    updateModeButtons(profile, commandMode);
    updateCommandInputs(profile, commandMode);
    setBilingualText(
      modeNote,
      profile.command_only
        ? "自定义命令完全由 CLI 模板决定，不会额外套模型或推理强度。"
        : (commandMode
          ? "现在由自定义命令接管。模型和推理强度只作为灰掉的参考，不会单独传入。"
          : "现在由预设模式接管。Loopora 会按所选工具自动拼出 Agent 调用。"),
      profile.command_only
        ? "Custom command is governed entirely by the CLI template; no separate model or reasoning setting is applied."
        : (commandMode
          ? "Custom command now owns the run. Model and reasoning are disabled references and are not submitted separately."
          : "Preset mode now owns the run. Loopora assembles the Agent invocation for the selected tool."),
    );
    setBilingualText(
      commandCliNote,
      profile.command_only
        ? "这里填你自己的命令入口。"
        : "切到自定义命令后，这里就是最终会执行的可执行文件。",
      profile.command_only
        ? "Put your own command executable here."
        : "Once custom command mode is active, this is the executable Loopora will run.",
    );
    setBilingualText(
      reasoningNote,
      profile.key === "opencode"
        ? "OpenCode 默认不填推理强度；需要变体时再选择。"
        : "留空时使用该工具的默认推理设置。",
      profile.key === "opencode"
        ? "OpenCode defaults to blank reasoning effort; choose a variant only when needed."
        : "Leave blank to use the tool's default reasoning setting.",
    );
    window.LooporaUI.applyLocalizedAttributes(document);
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: {
        "content-type": "application/json",
        ...(options.headers || {}),
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || payload.detail || response.statusText);
    }
    return payload;
  }

  function collectStartPayload() {
    const commandMode = isCommandMode();
    return {
      executor_kind: executorInput.value,
      executor_mode: commandMode ? "command" : "preset",
      workdir: workdirInput.value.trim(),
      message: messageInput.value.trim(),
      model: commandMode ? "" : modelInput.value.trim(),
      reasoning_effort: commandMode ? "" : effortInput.value.trim(),
      command_cli: commandMode ? commandCliInput.value.trim() : "",
      command_args_text: commandMode ? commandArgsInput.value : "",
    };
  }

  function statusLabel(status) {
    const labels = {
      idle: localeText("未开始", "Idle"),
      running: localeText("对齐中", "Running"),
      waiting_user: localeText("等待回复", "Waiting"),
      validating: localeText("校验中", "Validating"),
      repairing: localeText("自动修复", "Repairing"),
      ready: "READY",
      failed: localeText("失败", "Failed"),
      imported: localeText("已导入", "Imported"),
      running_loop: localeText("运行中", "Running loop"),
    };
    return labels[status] || status || "-";
  }

  function renderSession(session) {
    currentSession = session;
    rememberSession(session.id);
    chat.hidden = false;
    newSessionButton.hidden = false;
    const status = String(session.status || "idle");
    setStatus(statusLabel(status), status === "ready" ? "ready" : (status === "failed" ? "failed" : ""));
    sessionMeta.textContent = `${session.id} · ${session.workdir}`;
    cancelButton.hidden = !ACTIVE_STATUSES.has(status);
    replyForm.hidden = !REPLY_STATUSES.has(status);
    setBusy(ACTIVE_STATUSES.has(status));
    renderTranscript(session.transcript || []);
    if (status === "ready") {
      if (currentPreviewSource === "import") {
        return;
      }
      loadReadyBundle();
    } else if (currentPreviewSource !== "import") {
      readyPreview.hidden = true;
    }
  }

  function rememberSession(sessionId) {
    try {
      if (sessionId) {
        window.localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
      }
    } catch (_) {
      return;
    }
  }

  function forgetSession() {
    try {
      window.localStorage.removeItem(SESSION_STORAGE_KEY);
    } catch (_) {
      return;
    }
  }

  function renderTranscript(transcript) {
    transcriptEl.innerHTML = "";
    if (!transcript.length) {
      transcriptEl.innerHTML = `<p class="field-note">${escapeHtml(localeText("对话开始后会显示在这里。", "The conversation appears here after it starts."))}</p>`;
      return;
    }
    transcript.forEach((entry) => {
      const bubble = document.createElement("article");
      bubble.className = `alignment-message alignment-message--${entry.role === "user" ? "user" : "assistant"}`;
      bubble.innerHTML = `
        <strong>${escapeHtml(entry.role === "user" ? localeText("你", "You") : "Agent")}</strong>
        <p>${escapeHtml(entry.content || "")}</p>
      `;
      transcriptEl.append(bubble);
    });
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
  }

  function eventKind(event) {
    if (event.event_type === "codex_event") {
      const type = String(event.payload?.type || "");
      if (type === "command") {
        return "command";
      }
      if (type.includes("complete")) {
        return "success";
      }
      return "stdout";
    }
    if (event.event_type.includes("failed") || event.event_type.includes("cancel")) {
      return "error";
    }
    if (event.event_type.includes("ready") || event.event_type.includes("passed") || event.event_type.includes("imported")) {
      return "success";
    }
    if (event.event_type.includes("repair") || event.event_type.includes("validat")) {
      return "progress";
    }
    return "system";
  }

  function eventSummary(event) {
    const payload = event.payload || {};
    if (event.event_type === "codex_event") {
      return payload.message || payload.type || "agent event";
    }
    if (payload.error) {
      return payload.error;
    }
    if (payload.content) {
      return payload.content;
    }
    if (payload.bundle_path) {
      return payload.bundle_path;
    }
    return event.event_type.replaceAll("_", " ");
  }

  function appendEvent(event) {
    if (!event || !event.id || event.id <= latestEventId) {
      return;
    }
    latestEventId = event.id;
    const kind = eventKind(event);
    const line = document.createElement("article");
    line.className = `console-line console-line-${kind} is-collapsed`;
    line.innerHTML = `
      <button class="console-line-toggle" type="button">
        <span class="console-line-meta">
          <span class="console-line-stamp">#${event.id}</span>
          <span class="console-line-badge">${escapeHtml(kind)}</span>
        </span>
        <span class="console-line-summary">${escapeHtml(eventSummary(event))}</span>
        <span class="console-line-expander">view</span>
      </button>
      <pre class="console-line-body">${escapeHtml(JSON.stringify(event.payload || {}, null, 2))}</pre>
    `;
    line.querySelector(".console-line-toggle")?.addEventListener("click", () => {
      line.classList.toggle("is-collapsed");
    });
    consoleOutput.append(line);
    consoleOutput.parentElement.scrollTop = consoleOutput.parentElement.scrollHeight;
  }

  async function refreshSession() {
    if (!currentSession?.id) {
      return;
    }
    const payload = await fetchJson(`/api/alignments/sessions/${encodeURIComponent(currentSession.id)}`);
    renderSession(payload.session);
  }

  function openStream(sessionId) {
    if (eventSource) {
      eventSource.close();
    }
    eventSource = new EventSource(`/api/alignments/sessions/${encodeURIComponent(sessionId)}/stream?after_id=${latestEventId}`);
    EVENT_TYPES.forEach((eventType) => {
      eventSource.addEventListener(eventType, (message) => {
        try {
          appendEvent(JSON.parse(message.data));
        } catch (_) {
          return;
        }
        refreshSession().catch(() => {});
      });
    });
    eventSource.onerror = () => {
      eventSource?.close();
      eventSource = null;
      refreshSession().catch(() => {});
    };
  }

  async function loadSeedEvents(sessionId) {
    const events = await fetchJson(`/api/alignments/sessions/${encodeURIComponent(sessionId)}/events`);
    events.forEach(appendEvent);
  }

  async function loadReadyBundle() {
    if (!currentSession?.id) {
      return;
    }
    const payload = await fetchJson(`/api/alignments/sessions/${encodeURIComponent(currentSession.id)}/bundle`);
    if (!payload.ok) {
      readyPreview.hidden = true;
      return;
    }
    renderBundlePreview(payload, "alignment");
  }

  function renderBundlePreview(payload, source) {
    currentPreviewSource = source;
    readyPreview.hidden = false;
    previewTitle.textContent = source === "alignment"
      ? "READY"
      : localeText("预览已就绪", "Preview Ready");
    readyNote.textContent = payload.source_path || (source === "alignment"
      ? ""
      : localeText("这个预览还没有导入；确认无误后可以按下方按钮导入。", "This preview has not been imported yet; import it when it looks right."));
    importRunButton.hidden = source !== "alignment";
    bundlePreviewImportButton.hidden = source !== "import";
    specPreview.innerHTML = payload.spec_rendered_html || "";
    yamlSource.textContent = payload.yaml || "";
    roleList.innerHTML = "";
    (payload.roles || []).forEach((role) => {
      const item = document.createElement("article");
      item.className = "alignment-role-card";
      item.innerHTML = `
        <strong>${escapeHtml(role.name || role.key)}</strong>
        <span>${escapeHtml(role.archetype || "")}</span>
        <p>${escapeHtml(role.description || role.posture_notes || "")}</p>
      `;
      roleList.append(item);
    });
    if (window.LooporaWorkflowDiagram) {
      window.LooporaWorkflowDiagram.renderInto(workflowDiagram, payload.workflow_preview || {}, {variant: "card"});
    }
  }

  async function previewImportBundle() {
    if (!bundleImportForm || !bundlePreviewButton) {
      return;
    }
    showImportError("");
    const payload = {
      bundle_path: bundleImportPath?.value?.trim() || "",
      bundle_yaml: bundleImportYaml?.value || "",
    };
    if (!payload.bundle_path && !payload.bundle_yaml.trim()) {
      showImportError(localeText("请填写 Bundle 路径或粘贴 YAML。", "Provide a bundle path or paste YAML."));
      return;
    }
    bundlePreviewButton.disabled = true;
    try {
      const preview = await fetchJson("/api/bundles/preview", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (!preview.ok) {
        throw new Error(preview.error || localeText("Bundle 预览失败。", "Bundle preview failed."));
      }
      renderBundlePreview(preview, "import");
      readyPreview.scrollIntoView({block: "nearest", behavior: "smooth"});
    } catch (error) {
      showImportError(error.message || localeText("Bundle 预览失败。", "Bundle preview failed."));
    } finally {
      bundlePreviewButton.disabled = false;
    }
  }

  function showImportError(message) {
    if (!bundleImportError) {
      return;
    }
    if (!message) {
      bundleImportError.hidden = true;
      bundleImportError.textContent = "";
      return;
    }
    bundleImportError.hidden = false;
    bundleImportError.textContent = message;
  }

  startForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    const payload = collectStartPayload();
    if (!payload.workdir || !payload.message) {
      showError(localeText("请填写 workdir 和需求。", "Fill in the workdir and request."));
      return;
    }
    setBusy(true);
    try {
      const response = await fetchJson("/api/alignments/sessions", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      latestEventId = 0;
      consoleOutput.innerHTML = "";
      renderSession(response.session);
      await loadSeedEvents(response.session.id);
      openStream(response.session.id);
    } catch (error) {
      showError(error.message || localeText("启动对齐失败。", "Failed to start alignment."));
      setBusy(false);
    }
  });

  replyForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!currentSession?.id) {
      return;
    }
    const message = replyInput.value.trim();
    if (!message) {
      return;
    }
    showError("");
    replyInput.value = "";
    try {
      const response = await fetchJson(`/api/alignments/sessions/${encodeURIComponent(currentSession.id)}/messages`, {
        method: "POST",
        body: JSON.stringify({message}),
      });
      renderSession(response.session);
      openStream(response.session.id);
    } catch (error) {
      showError(error.message || localeText("发送回复失败。", "Failed to send reply."));
    }
  });

  cancelButton.addEventListener("click", async () => {
    if (!currentSession?.id) {
      return;
    }
    try {
      const response = await fetchJson(`/api/alignments/sessions/${encodeURIComponent(currentSession.id)}/cancel`, {
        method: "POST",
        body: "{}",
      });
      renderSession(response.session);
    } catch (error) {
      showError(error.message || localeText("取消失败。", "Failed to cancel."));
    }
  });

  newSessionButton.addEventListener("click", () => {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    currentSession = null;
    currentPreviewSource = "";
    latestEventId = 0;
    forgetSession();
    consoleOutput.innerHTML = "";
    transcriptEl.innerHTML = "";
    readyPreview.hidden = true;
    chat.hidden = true;
    replyForm.hidden = true;
    newSessionButton.hidden = true;
    setStatus(localeText("未开始", "Idle"));
    setBusy(false);
    showError("");
    messageInput.focus();
  });

  importRunButton.addEventListener("click", async () => {
    if (!currentSession?.id) {
      return;
    }
    importRunButton.disabled = true;
    try {
      const response = await fetchJson(`/api/alignments/sessions/${encodeURIComponent(currentSession.id)}/import`, {
        method: "POST",
        body: JSON.stringify({start_immediately: true}),
      });
      window.location.assign(response.redirect_url || "/");
    } catch (error) {
      showError(error.message || localeText("导入失败，READY bundle 已保留。", "Import failed; the READY bundle is preserved."));
      importRunButton.disabled = false;
    }
  });

  bundlePreviewButton?.addEventListener("click", () => {
    previewImportBundle().catch((error) => {
      showImportError(error.message || localeText("Bundle 预览失败。", "Bundle preview failed."));
    });
  });

  bundlePreviewImportButton?.addEventListener("click", () => {
    bundleImportForm?.requestSubmit();
  });

  panel.querySelectorAll("[data-pick-directory][data-target-input]").forEach((button) => {
    button.addEventListener("click", async () => {
      const target = document.getElementById(button.dataset.targetInput || "");
      if (!target) {
        return;
      }
      const endpoint = button.dataset.pickEndpoint || "/api/system/pick-directory";
      try {
        const payload = await fetchJson(`${endpoint}?start_path=${encodeURIComponent(target.value.trim())}`, {
          headers: {},
        });
        if (payload.path) {
          target.value = payload.path;
        }
      } catch (error) {
        showError(error.message || localeText("无法打开目录选择器。", "Could not open the directory picker."));
      }
    });
  });

  executorInput.addEventListener("change", () => {
    if (isCommandMode()) {
      saveCommandDraft(lastExecutorKind);
    }
    lastExecutorKind = executorInput.value;
    commandCliInput.dataset.autofilled = "true";
    commandArgsInput.dataset.autofilled = "true";
    updateExecutorControls({preserveUserModel: true, preserveUserEffort: true});
  });
  modeButtons.forEach((button) => {
    button.addEventListener("click", () => setAlignmentMode(button.dataset.alignmentModeChoice || "preset"));
  });
  [modelInput, effortInput, commandCliInput, commandArgsInput].forEach((input) => {
    input?.addEventListener("input", () => {
      if (input === commandCliInput || input === commandArgsInput) {
        input.dataset.autofilled = "false";
      }
    });
  });
  updateExecutorControls();

  async function restoreSessionIfPresent() {
    let sessionId = new URLSearchParams(window.location.search).get("alignment_session_id") || "";
    if (!sessionId) {
      try {
        sessionId = window.localStorage.getItem(SESSION_STORAGE_KEY) || "";
      } catch (_) {
        sessionId = "";
      }
    }
    if (!sessionId) {
      return;
    }
    try {
      const payload = await fetchJson(`/api/alignments/sessions/${encodeURIComponent(sessionId)}`);
      renderSession(payload.session);
      await loadSeedEvents(payload.session.id);
      if (ACTIVE_STATUSES.has(String(payload.session.status || ""))) {
        openStream(payload.session.id);
      }
    } catch (_) {
      forgetSession();
    }
  }

  restoreSessionIfPresent();
});
