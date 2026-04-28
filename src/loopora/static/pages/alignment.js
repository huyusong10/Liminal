document.addEventListener("DOMContentLoaded", () => {
  const panel = document.querySelector("[data-testid='loop-alignment-panel']");
  if (!panel || !window.LooporaUI) {
    return;
  }

  const scrollRegion = document.getElementById("alignment-scroll-region");
  const profiles = JSON.parse(document.getElementById("executor-profiles-json")?.textContent || "[]");
  const shell = document.querySelector("[data-testid='loop-bundle-create-panel']");
  const startForm = document.getElementById("alignment-start-form");
  const emptyState = document.getElementById("alignment-empty-state");
  const toolsMenu = document.getElementById("alignment-tools-menu");
  const toolsCloseButton = document.getElementById("alignment-tools-close");
  const toolPanels = Array.from(document.querySelectorAll("[data-tool-panel]"));
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
  const agentChip = document.getElementById("alignment-agent-chip");
  const workdirChip = document.getElementById("alignment-workdir-chip");
  const chat = document.getElementById("alignment-chat");
  const sessionMeta = document.getElementById("alignment-session-meta");
  const thinkingStatus = document.getElementById("alignment-thinking-status");
  const historyList = document.getElementById("alignment-history-list");
  const transcriptEl = document.getElementById("alignment-transcript");
  const consoleOutput = document.getElementById("alignment-console-output");
  const liveDetails = document.getElementById("alignment-live-details");
  const liveToggle = document.getElementById("alignment-live-toggle");
  const liveBody = document.getElementById("alignment-live-body");
  const cancelButton = document.getElementById("alignment-cancel-button");
  const readyPreview = document.getElementById("alignment-ready-preview");
  const previewTitle = document.getElementById("bundle-preview-title");
  const artifactName = document.getElementById("alignment-artifact-name");
  const readyNote = document.getElementById("alignment-ready-note");
  const artifactGoal = document.getElementById("alignment-artifact-goal");
  const artifactRoles = document.getElementById("alignment-artifact-roles");
  const artifactFlow = document.getElementById("alignment-artifact-flow");
  const artifactWorkdir = document.getElementById("alignment-artifact-workdir");
  const controlSummary = document.getElementById("alignment-control-summary");
  const artifactSource = document.getElementById("alignment-artifact-source");
  const sourcePathLabel = document.getElementById("alignment-source-path");
  const specPreview = document.getElementById("alignment-spec-preview");
  const roleList = document.getElementById("alignment-role-list");
  const workflowDiagram = document.getElementById("alignment-workflow-diagram");
  const importRunButton = document.getElementById("alignment-import-run-button");
  const sourceOpenButton = document.getElementById("alignment-source-open-button");
  const sourceSyncButton = document.getElementById("alignment-source-sync-button");

  const ACTIVE_STATUSES = new Set(["running", "validating", "repairing"]);
  const SESSION_STORAGE_KEY = "loopora:alignment-session:v1";
  const EVENT_TYPES = [
    "alignment_session_created",
    "alignment_started",
    "alignment_user_message",
    "alignment_message",
    "alignment_agreement_ready",
    "alignment_agreement_confirmed",
    "alignment_agreement_reopened",
    "alignment_stage_blocked",
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
    "alignment_bundle_synced",
    "alignment_bundle_sync_failed",
    "codex_event",
    "stream_error",
  ];
  let currentSession = null;
  let eventSource = null;
  let latestEventId = 0;
  let thinkingStartedAt = 0;
  let thinkingTimer = null;
  let errorTimer = null;
  const commandDrafts = new Map();
  let lastExecutorKind = executorInput?.value || "codex";

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

  function basename(path) {
    const cleaned = String(path || "").replace(/\/+$/, "");
    if (!cleaned) {
      return "";
    }
    return cleaned.split("/").filter(Boolean).pop() || cleaned;
  }

  function profileFor(kind) {
    return profiles.find((profile) => profile.key === kind) || profiles[0] || {};
  }

  function defaultCommandArgsText(profile) {
    return Array.isArray(profile?.command_args_template) ? profile.command_args_template.join("\n") : "";
  }

  function isCommandMode() {
    const profile = profileFor(executorInput.value);
    return String(executorModeInput?.value || "preset") === "command" || Boolean(profile.command_only);
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

  function showError(message, options = {}) {
    const autoHide = options.autoHide !== false;
    if (errorTimer) {
      clearTimeout(errorTimer);
      errorTimer = null;
    }
    if (!message) {
      errorBox.hidden = true;
      errorBox.textContent = "";
      return;
    }
    errorBox.hidden = false;
    errorBox.textContent = message;
    if (autoHide) {
      errorTimer = window.setTimeout(() => showError(""), 7000);
    }
  }

  function setBusy(isBusy) {
    sendButton.disabled = isBusy;
    sendButton.setAttribute("aria-busy", String(isBusy));
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

  function setStatus(message, kind = "") {
    statusPill.textContent = message;
    statusPill.className = `alignment-status-pill${kind ? ` is-${kind}` : ""}`;
    statusPill.disabled = false;
    statusPill.setAttribute("aria-disabled", String(kind !== "ready"));
    statusPill.setAttribute("aria-pressed", "false");
  }

  function executorLabel(session = currentSession) {
    const profile = profileFor(session?.executor_kind || executorInput.value || "codex");
    return localeText(profile.label_zh || profile.label || "Agent", profile.label || profile.label_zh || "Agent");
  }

  function updateChips() {
    const profile = profileFor(executorInput.value || "codex");
    agentChip.textContent = executorLabel();
    const currentWorkdir = currentSession?.workdir || workdirInput.value.trim();
    workdirChip.textContent = currentWorkdir
      ? basename(currentWorkdir)
      : localeText("选择 workdir", "Choose workdir");
    workdirChip.title = currentWorkdir || "";
    if (profile.command_only || isCommandMode()) {
      agentChip.textContent = `${agentChip.textContent} · ${localeText("自定义命令", "Custom")}`;
    }
  }

  function setToolControlsExpanded(panelName = "") {
    document.querySelectorAll("[data-open-panel][aria-expanded]").forEach((button) => {
      button.setAttribute("aria-expanded", String(!toolsMenu.hidden && button.dataset.openPanel === panelName));
    });
    document.querySelectorAll(".alignment-tool-tabs [data-open-panel]").forEach((button) => {
      const active = button.dataset.openPanel === panelName;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function openTools(panelName = "workdir") {
    toolsMenu.hidden = false;
    toolsMenu.dataset.activePanel = panelName;
    toolPanels.forEach((section) => {
      section.hidden = section.dataset.toolPanel !== panelName;
    });
    setToolControlsExpanded(panelName);
    const firstFocusable = toolsMenu.querySelector(`[data-tool-panel="${panelName}"] input, [data-tool-panel="${panelName}"] textarea, [data-tool-panel="${panelName}"] select, [data-tool-panel="${panelName}"] button`);
    firstFocusable?.focus();
  }

  function closeTools() {
    toolsMenu.hidden = true;
    toolsMenu.dataset.activePanel = "";
    setToolControlsExpanded("");
  }

  function setLiveDetailsOpen(open) {
    if (!liveDetails || !liveToggle || !liveBody) {
      return;
    }
    liveDetails.classList.toggle("is-open", open);
    liveToggle.setAttribute("aria-expanded", String(open));
    liveBody.hidden = !open;
  }

  function resetToEmptyConversation() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    currentSession = null;
    latestEventId = 0;
    forgetSession();
    closeTools();
    setLiveDetailsOpen(false);
    consoleOutput.innerHTML = "";
    transcriptEl.innerHTML = "";
    readyPreview.hidden = true;
    chat.hidden = true;
    scrollRegion?.scrollTo({top: 0});
    if (liveDetails) {
      liveDetails.hidden = true;
    }
    if (sourceOpenButton) {
      sourceOpenButton.hidden = true;
      sourceOpenButton.dataset.sourcePath = "";
    }
    if (sourceSyncButton) {
      sourceSyncButton.hidden = true;
    }
    if (artifactSource) {
      artifactSource.hidden = true;
    }
    if (sourcePathLabel) {
      sourcePathLabel.textContent = "";
    }
    emptyState.hidden = false;
    shell?.classList.remove("has-session", "has-artifact");
    setStatus(localeText("未开始", "Idle"));
    updateThinkingStatus("");
    updateChips();
    setBusy(false);
    showError("");
    messageInput.value = "";
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
    updateChips();
    window.LooporaUI.applyLocalizedAttributes(document);
  }

  function setAlignmentMode(nextMode) {
    const profile = profileFor(executorInput.value);
    executorModeInput.value = profile.command_only ? "command" : nextMode;
    updateExecutorControls({preserveUserModel: true, preserveUserEffort: true});
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

  function updateThinkingStatus(status) {
    if (!thinkingStatus) {
      return;
    }
    if (!ACTIVE_STATUSES.has(String(status || ""))) {
      thinkingStatus.hidden = true;
      thinkingStatus.textContent = "";
      thinkingStartedAt = 0;
      if (thinkingTimer) {
        clearInterval(thinkingTimer);
        thinkingTimer = null;
      }
      return;
    }
    if (!thinkingStartedAt) {
      thinkingStartedAt = Date.now();
    }
    const render = () => {
      const seconds = Math.max(0, Math.floor((Date.now() - thinkingStartedAt) / 1000));
      const statusText = String(currentSession?.status || status);
      const zh = statusText === "validating"
        ? `正在校验方案 ${seconds}s`
        : (statusText === "repairing" ? `正在自动修复 ${seconds}s` : `${executorLabel()} 思考中 ${seconds}s`);
      const en = statusText === "validating"
        ? `Validating plan ${seconds}s`
        : (statusText === "repairing" ? `Repairing plan ${seconds}s` : `${executorLabel()} thinking ${seconds}s`);
      thinkingStatus.hidden = false;
      thinkingStatus.textContent = localeText(zh, en);
    };
    render();
    if (!thinkingTimer) {
      thinkingTimer = window.setInterval(render, 1000);
    }
  }

  function renderSession(session, options = {}) {
    currentSession = session;
    rememberSession(session.id);
    shell?.classList.add("has-session");
    emptyState.hidden = true;
    chat.hidden = false;
    if (liveDetails) {
      liveDetails.hidden = false;
    }
    const status = String(session.status || "idle");
    setStatus(statusLabel(status), status === "ready" ? "ready" : (status === "failed" ? "failed" : ""));
    sessionMeta.textContent = `${statusLabel(status)} · ${basename(session.workdir)} · ${session.id}`;
    cancelButton.hidden = !ACTIVE_STATUSES.has(status);
    setBusy(ACTIVE_STATUSES.has(status));
    updateThinkingStatus(status);
    updateChips();
    renderTranscript(session.transcript || [], session);
    if (status === "ready") {
      loadReadyBundle({reveal: options.revealReady !== false}).catch((error) => {
        renderBundleLoadError(error.message || localeText("无法加载循环方案。", "Unable to load the loop plan."));
      });
    } else {
      readyPreview.hidden = true;
      shell?.classList.remove("has-artifact");
    }
    loadHistory().catch(() => {});
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

  function renderTranscript(transcript, session = currentSession) {
    transcriptEl.innerHTML = "";
    transcript.forEach((entry) => {
      const bubble = document.createElement("article");
      bubble.className = `alignment-message alignment-message--${entry.role === "user" ? "user" : "assistant"}`;
      bubble.innerHTML = `
        <p>${escapeHtml(entry.content || "")}</p>
      `;
      transcriptEl.append(bubble);
    });
    if (String(session?.status || "") === "failed") {
      const failure = document.createElement("article");
      failure.className = "alignment-failure-card";
      failure.innerHTML = `
        <strong>${escapeHtml(localeText("这轮没有生成可用方案", "This turn did not produce a usable plan"))}</strong>
        <p>${escapeHtml(session?.error_message || localeText("可以查看执行详情，或让 Agent 按这个错误继续修复。", "Check execution details, or ask the Agent to repair from this error."))}</p>
        <div class="card-actions card-actions-compact">
          <button class="primary-button" type="button" data-repair-failure data-testid="alignment-repair-failure-button">${escapeHtml(localeText("继续修复", "Continue repair"))}</button>
          <button class="secondary-button" type="button" data-open-live-details>${escapeHtml(localeText("查看详情", "View details"))}</button>
          <button class="ghost-button" type="button" data-open-panel="advanced">${escapeHtml(localeText("Agent 设置", "Agent settings"))}</button>
        </div>
      `;
      failure.querySelector("[data-repair-failure]")?.addEventListener("click", async () => {
        if (!currentSession?.id) {
          return;
        }
        setBusy(true);
        try {
          await appendMessage(localeText("请根据上面的校验错误继续修复这份循环方案。", "Please repair this loop plan using the validation error above."));
        } catch (error) {
          showError(error.message || localeText("继续修复失败。", "Failed to continue repair."));
          setBusy(false);
        }
      });
      failure.querySelector("[data-open-live-details]")?.addEventListener("click", () => {
        if (liveDetails) {
          liveDetails.hidden = false;
        }
        setLiveDetailsOpen(true);
      });
      failure.querySelector("[data-open-panel]")?.addEventListener("click", () => openTools("advanced"));
      transcriptEl.append(failure);
    }
    scrollRegion?.scrollTo({top: scrollRegion.scrollHeight});
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
    if (liveDetails) {
      liveDetails.hidden = false;
    }
    consoleOutput.parentElement.scrollTop = consoleOutput.parentElement.scrollHeight;
  }

  async function deleteHistorySession(sessionId) {
    if (!sessionId) {
      return;
    }
    showError("");
    try {
      await fetchJson(`/api/alignments/sessions/${encodeURIComponent(sessionId)}`, {
        method: "DELETE",
      });
      if (currentSession?.id === sessionId) {
        resetToEmptyConversation();
      }
      await loadHistory();
    } catch (error) {
      showError(error.message || localeText("删除历史对话失败。", "Failed to delete chat history."));
    }
  }

  function renderHistory(sessions) {
    if (!historyList) {
      return;
    }
    historyList.innerHTML = "";
    if (!sessions.length) {
      const empty = document.createElement("p");
      empty.className = "field-note";
      empty.textContent = localeText("还没有历史对话。", "No recent chats yet.");
      historyList.append(empty);
      return;
    }
    sessions.forEach((session) => {
      const item = document.createElement("article");
      item.className = "alignment-history-item";
      item.dataset.sessionId = session.id;
      item.classList.toggle("is-active", currentSession?.id === session.id);
      const isActive = ACTIVE_STATUSES.has(String(session.status || ""));
      item.innerHTML = `
        <button class="alignment-history-open" type="button">
          <strong>${escapeHtml(session.title || session.id)}</strong>
          <span>${escapeHtml(statusLabel(session.status))} · ${escapeHtml(session.executor_kind || "")}</span>
        </button>
        <button
          class="alignment-history-delete"
          type="button"
          data-testid="alignment-history-delete"
          ${isActive ? "disabled aria-disabled=\"true\"" : ""}
          aria-label="${escapeHtml(localeText("删除历史对话", "Delete chat"))}"
          title="${escapeHtml(localeText("删除", "Delete"))}"
        >×</button>
      `;
      item.querySelector(".alignment-history-open")?.addEventListener("click", () => restoreSession(session.id));
      item.querySelector(".alignment-history-delete")?.addEventListener("click", (event) => {
        event.stopPropagation();
        deleteHistorySession(session.id).catch(() => {});
      });
      historyList.append(item);
    });
  }

  async function loadHistory() {
    if (!historyList) {
      return;
    }
    const payload = await fetchJson("/api/alignments/sessions?limit=30");
    renderHistory(payload.sessions || []);
  }

  async function restoreSession(sessionId) {
    if (!sessionId) {
      return;
    }
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    latestEventId = 0;
    consoleOutput.innerHTML = "";
    closeTools();
    const payload = await fetchJson(`/api/alignments/sessions/${encodeURIComponent(sessionId)}`);
    renderSession(payload.session, {revealReady: true});
    await loadSeedEvents(payload.session.id);
    if (ACTIVE_STATUSES.has(String(payload.session.status || ""))) {
      openStream(payload.session.id);
    }
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

  async function loadReadyBundle(options = {}) {
    if (!currentSession?.id) {
      return;
    }
    const payload = await fetchJson(`/api/alignments/sessions/${encodeURIComponent(currentSession.id)}/bundle`);
    if (!payload.ok) {
      renderBundleLoadError(payload.error || localeText("READY 方案暂时无法读取。", "The READY plan cannot be read right now."));
      return;
    }
    renderBundlePreview(payload, {reveal: options.reveal !== false});
  }

  function renderBundleLoadError(message) {
    shell?.classList.add("has-artifact");
    readyPreview.hidden = false;
    artifactName.textContent = localeText("无法加载循环方案", "Unable to load loop plan");
    previewTitle.textContent = localeText("READY 方案需要重新加载", "READY plan needs reload");
    readyNote.textContent = message || "";
    if (artifactGoal) {
      artifactGoal.textContent = localeText("方案文件暂时不可用。", "Plan file is temporarily unavailable.");
    }
    artifactRoles.textContent = "-";
    artifactFlow.textContent = "-";
    artifactWorkdir.textContent = basename(currentSession?.workdir || "");
    renderControlSummary(null);
    roleList.innerHTML = "";
    workflowDiagram.innerHTML = "";
    if (sourceOpenButton) {
      const path = currentSession?.bundle_path || "";
      sourceOpenButton.hidden = !path;
      sourceOpenButton.dataset.sourcePath = path;
    }
    if (sourceSyncButton) {
      sourceSyncButton.hidden = false;
    }
    if (artifactSource) {
      artifactSource.hidden = false;
    }
    if (sourcePathLabel) {
      const path = currentSession?.bundle_path || "";
      sourcePathLabel.textContent = path ? `${localeText("源文件", "Source")}: ${path}` : "";
      sourcePathLabel.title = path;
    }
    specPreview.innerHTML = `
      <div class="field-status is-error">
        ${escapeHtml(message || localeText("无法加载循环方案。", "Unable to load the loop plan."))}
      </div>
      <div class="card-actions">
        <button class="secondary-button" type="button" data-reload-ready-bundle>${escapeHtml(localeText("重新同步源文件", "Reload source file"))}</button>
      </div>
    `;
    specPreview.querySelector("[data-reload-ready-bundle]")?.addEventListener("click", () => {
      syncReadyBundle().catch((error) => renderBundleLoadError(error.message));
    });
    selectPreviewTab("spec");
    readyPreview.scrollIntoView({block: "nearest", behavior: "smooth"});
  }

  function taskSummary(bundle) {
    const markdown = String(bundle?.spec?.markdown || "");
    const taskMatch = markdown.match(/# Task\s+([\s\S]*?)(?:\n# |\s*$)/);
    const text = (taskMatch ? taskMatch[1] : markdown)
      .replace(/```[\s\S]*?```/g, "")
      .replace(/[#*_`>-]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    return text.slice(0, 180) || localeText("spec 已生成。", "spec generated.");
  }

  function workflowSummary(preview) {
    const roleById = new Map((preview?.roles || []).map((role) => [role.id, role.name || role.id]));
    return (preview?.steps || [])
      .map((step) => roleById.get(step.role_id) || step.role_id)
      .filter(Boolean)
      .join(" -> ");
  }

  function listSnippet(values) {
    return (values || [])
      .map((value) => String(value || "").trim())
      .filter(Boolean)
      .slice(0, 2)
      .join(" / ");
  }

  function renderControlSummary(summary) {
    if (!controlSummary) {
      return;
    }
    if (!summary) {
      controlSummary.innerHTML = "";
      return;
    }
    const workflow = summary.workflow || {};
    const gatekeeper = summary.gatekeeper || {};
    const controls = Array.isArray(summary.controls) ? summary.controls : [];
    const controlSnippet = controls
      .slice(0, 2)
      .map((control) => {
        const after = control.after && control.after !== "0s" ? `${control.after} · ` : "";
        return `${after}${control.signal || "control"} -> ${control.role_name || control.role_id || "role"}`;
      })
      .join(" / ");
    const cards = [
      {
        label: localeText("主要风险", "Main risk"),
        value: listSnippet(summary.risks) || localeText("从 spec 中读取。", "Read from spec."),
      },
      {
        label: localeText("证据路径", "Evidence path"),
        value: listSnippet(summary.evidence) || localeText("由 workflow 运行时落账。", "Recorded by the workflow runtime."),
      },
      {
        label: "workflow",
        value: workflow.summary || localeText(`${workflow.step_count || 0} 个 step`, `${workflow.step_count || 0} steps`),
      },
      {
        label: "GateKeeper",
        value: gatekeeper.enabled
          ? localeText("需要 evidence refs 才能结束。", "Requires evidence refs to finish.")
          : localeText("未配置 GateKeeper。", "No GateKeeper configured."),
      },
      ...(controls.length ? [{
        label: localeText("运行控制", "Runtime controls"),
        value: controlSnippet || localeText("按误差风险触发检查。", "Triggered by error-control risk."),
      }] : []),
    ];
    controlSummary.innerHTML = cards.map((card) => `
      <div class="alignment-control-card">
        <strong>${escapeHtml(card.label)}</strong>
        <span>${escapeHtml(card.value)}</span>
      </div>
    `).join("");
  }

  function compactRoleSummary(role) {
    const description = String(role.description || "").trim();
    const posture = String(role.posture_notes || "").trim();
    return description || posture || localeText("点击查看完整 role 信息。", "Open to inspect the full role definition.");
  }

  function roleDetailRow(label, value, options = {}) {
    const text = String(value || "").trim();
    if (!text) {
      return "";
    }
    const body = options.pre
      ? `<pre>${escapeHtml(text)}</pre>`
      : `<dd>${escapeHtml(text)}</dd>`;
    return `<div><dt>${escapeHtml(label)}</dt>${body}</div>`;
  }

  function renderRoleCard(role) {
    const item = document.createElement("details");
    item.className = "alignment-role-card";
    item.dataset.testid = "alignment-role-card";
    const name = role.name || role.key || "role";
    const archetype = role.archetype || "";
    const executor = [
      role.executor_kind,
      role.model,
      role.reasoning_effort,
    ].filter(Boolean).join(" · ");
    item.innerHTML = `
      <summary class="alignment-role-summary" data-testid="alignment-role-toggle">
        <span class="alignment-role-title">
          <strong>${escapeHtml(name)}</strong>
          <em>${escapeHtml(archetype)}</em>
        </span>
        <span class="alignment-role-brief">${escapeHtml(compactRoleSummary(role))}</span>
      </summary>
      <dl class="alignment-role-details">
        ${roleDetailRow("key", role.key)}
        ${roleDetailRow("archetype", archetype)}
        ${roleDetailRow("description", role.description)}
        ${roleDetailRow("posture_notes", role.posture_notes)}
        ${roleDetailRow("executor", executor)}
        ${roleDetailRow("executor_mode", role.executor_mode)}
        ${roleDetailRow("command_cli", role.command_cli)}
        ${roleDetailRow("command_args_text", role.command_args_text, {pre: true})}
        ${roleDetailRow("prompt_ref", role.prompt_ref)}
        ${roleDetailRow("prompt_markdown", role.prompt_markdown, {pre: true})}
      </dl>
    `;
    return item;
  }

  function selectPreviewTab(tabName) {
    document.querySelectorAll("[data-preview-tab]").forEach((button) => {
      const active = button.dataset.previewTab === tabName;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", String(active));
    });
    document.querySelectorAll("[data-preview-panel]").forEach((section) => {
      section.hidden = section.dataset.previewPanel !== tabName;
    });
  }

  function renderBundlePreview(payload, options = {}) {
    shell?.classList.add("has-artifact");
    readyPreview.hidden = false;
    const metadata = payload.metadata || payload.bundle?.metadata || {};
    artifactName.textContent = metadata.name || localeText("循环方案", "Loop plan");
    previewTitle.textContent = localeText("循环方案已准备好", "Loop plan is ready");
    readyNote.textContent = taskSummary(payload.bundle);
    importRunButton.hidden = false;
    if (artifactGoal) {
      artifactGoal.textContent = taskSummary(payload.bundle);
    }
    artifactRoles.textContent = localeText(`${(payload.roles || []).length} roles`, `${(payload.roles || []).length} roles`);
    artifactFlow.textContent = workflowSummary(payload.workflow_preview) || localeText("workflow 已生成", "workflow generated");
    artifactWorkdir.textContent = basename(payload.bundle?.loop?.workdir || "");
    artifactWorkdir.title = payload.bundle?.loop?.workdir || "";
    renderControlSummary(payload.control_summary || null);
    specPreview.innerHTML = payload.spec_rendered_html || "";
    if (sourceOpenButton) {
      sourceOpenButton.hidden = !payload.source_path;
      sourceOpenButton.dataset.sourcePath = payload.source_path || "";
      sourceOpenButton.title = payload.source_path || "";
    }
    if (sourceSyncButton) {
      sourceSyncButton.hidden = !payload.source_path;
    }
    if (artifactSource) {
      artifactSource.hidden = !payload.source_path;
    }
    if (sourcePathLabel) {
      sourcePathLabel.textContent = payload.source_path ? `${localeText("源文件", "Source")}: ${payload.source_path}` : "";
      sourcePathLabel.title = payload.source_path || "";
    }
    roleList.innerHTML = "";
    (payload.roles || []).forEach((role) => {
      roleList.append(renderRoleCard(role));
    });
    if (window.LooporaWorkflowDiagram) {
      window.LooporaWorkflowDiagram.renderInto(workflowDiagram, payload.workflow_preview || {}, {variant: "card"});
    }
    selectPreviewTab("spec");
    if (options.reveal !== false) {
      readyPreview.scrollIntoView({block: "nearest", behavior: "smooth"});
    }
  }

  async function revealSourcePath(path) {
    if (!path) {
      return;
    }
    try {
      await fetchJson("/api/system/reveal-path", {
        method: "POST",
        body: JSON.stringify({path}),
      });
    } catch (error) {
      try {
        await navigator.clipboard.writeText(path);
        showError(localeText("无法自动打开，路径已复制到剪贴板。", "Could not open automatically. The path was copied to your clipboard."));
      } catch (_) {
        showError(error.message || localeText("无法打开源文件。", "Unable to open the source file."));
      }
    }
  }

  async function syncReadyBundle() {
    if (!currentSession?.id) {
      return;
    }
    if (sourceSyncButton) {
      sourceSyncButton.disabled = true;
    }
    try {
      const payload = await fetchJson(`/api/alignments/sessions/${encodeURIComponent(currentSession.id)}/bundle/sync`, {
        method: "POST",
        body: "{}",
      });
      if (payload.session) {
        currentSession = payload.session;
        renderTranscript(currentSession.transcript || [], currentSession);
        setStatus(statusLabel(currentSession.status), currentSession.status === "ready" ? "ready" : (currentSession.status === "failed" ? "failed" : ""));
      }
      if (!payload.ok) {
        renderBundleLoadError(payload.validation?.error || localeText("源文件校验失败。", "Source validation failed."));
        await loadHistory();
        return;
      }
      renderBundlePreview(payload, {reveal: true});
      await loadHistory();
    } finally {
      if (sourceSyncButton) {
        sourceSyncButton.disabled = false;
      }
    }
  }

  async function createSession(payload) {
    const response = await fetchJson("/api/alignments/sessions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    latestEventId = 0;
    consoleOutput.innerHTML = "";
    renderSession(response.session);
    await loadSeedEvents(response.session.id);
    openStream(response.session.id);
    await loadHistory();
  }

  async function appendMessage(message) {
    const response = await fetchJson(`/api/alignments/sessions/${encodeURIComponent(currentSession.id)}/messages`, {
      method: "POST",
      body: JSON.stringify({message}),
    });
    renderSession(response.session);
    openStream(response.session.id);
    await loadHistory();
  }

  startForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    const message = messageInput.value.trim();
    if (!message) {
      showError(localeText("先描述你想做什么。", "Describe what you want first."));
      messageInput.focus();
      return;
    }
    if (currentSession?.id && !ACTIVE_STATUSES.has(String(currentSession.status || ""))) {
      setBusy(true);
      try {
        await appendMessage(message);
        messageInput.value = "";
      } catch (error) {
        showError(error.message || localeText("发送回复失败。", "Failed to send reply."));
        setBusy(false);
      }
      return;
    }
    const payload = collectStartPayload();
    if (!payload.workdir) {
      showError(localeText("先选择这次循环要运行的 workdir。", "Choose the workdir for this loop first."));
      openTools("workdir");
      return;
    }
    setBusy(true);
    try {
      await createSession(payload);
      messageInput.value = "";
      closeTools();
    } catch (error) {
      showError(error.message || localeText("启动对齐失败。", "Failed to start alignment."));
      setBusy(false);
    }
  });

  messageInput.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) {
      return;
    }
    event.preventDefault();
    startForm.requestSubmit();
  });

  messageInput.addEventListener("input", () => showError(""));
  workdirInput.addEventListener("input", () => showError(""));
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
    resetToEmptyConversation();
    messageInput.focus();
    loadHistory().catch(() => {});
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

  document.querySelectorAll("[data-open-panel]").forEach((button) => {
    button.addEventListener("click", () => {
      const panelName = button.dataset.openPanel || "workdir";
      if (!toolsMenu.hidden && toolsMenu.dataset.activePanel === panelName) {
        closeTools();
        return;
      }
      openTools(panelName);
    });
  });
  toolsCloseButton?.addEventListener("click", closeTools);
  liveToggle?.addEventListener("click", () => {
    setLiveDetailsOpen(!liveDetails?.classList.contains("is-open"));
  });
  sourceOpenButton?.addEventListener("click", () => {
    revealSourcePath(sourceOpenButton.dataset.sourcePath || currentSession?.bundle_path || "").catch((error) => {
      showError(error.message || localeText("无法打开源文件。", "Unable to open the source file."));
    });
  });
  sourceSyncButton?.addEventListener("click", () => {
    syncReadyBundle().catch((error) => {
      renderBundleLoadError(error.message || localeText("无法重新同步源文件。", "Unable to reload the source file."));
    });
  });
  statusPill?.addEventListener("click", () => {
    if (String(currentSession?.status || "") !== "ready") {
      return;
    }
    loadReadyBundle({reveal: true}).catch((error) => {
      renderBundleLoadError(error.message || localeText("无法加载循环方案。", "Unable to load the loop plan."));
    });
  });
  document.addEventListener("click", (event) => {
    if (toolsMenu.hidden) {
      return;
    }
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    if (toolsMenu.contains(target) || target.closest("[data-open-panel]")) {
      return;
    }
    closeTools();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeTools();
      setLiveDetailsOpen(false);
    }
  });
  document.querySelectorAll("[data-preview-tab]").forEach((button) => {
    button.addEventListener("click", () => selectPreviewTab(button.dataset.previewTab || "spec"));
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
          updateChips();
        }
      } catch (error) {
        showError(error.message || localeText("无法打开目录选择器。", "Could not open the directory picker."));
      }
    });
  });

  workdirInput.addEventListener("input", updateChips);
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
      await restoreSession(sessionId);
    } catch (_) {
      forgetSession();
    }
  }

  if (window.location.hash === "#bundle-import-form") {
    window.location.replace("/loops/new/manual#bundle-import-form");
    return;
  }
  updateExecutorControls();
  loadHistory().catch(() => {});
  restoreSessionIfPresent();
});
