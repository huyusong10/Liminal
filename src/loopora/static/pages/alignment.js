document.addEventListener("DOMContentLoaded", () => {
  const panel = document.querySelector("[data-testid='loop-alignment-panel']");
  if (!panel || !window.LooporaUI) {
    return;
  }

  const scrollRegion = document.getElementById("alignment-scroll-region");
  const profiles = JSON.parse(document.getElementById("executor-profiles-json")?.textContent || "[]");
  const shell = document.querySelector("[data-testid='loop-compose-shell']");
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
  const liveSummaryLabel = document.getElementById("alignment-live-summary-label");
  const liveSummaryMeta = document.getElementById("alignment-live-summary-meta");
  const liveBody = document.getElementById("alignment-live-body");
  const cancelButton = document.getElementById("alignment-cancel-button");
  const readyPreview = document.getElementById("alignment-ready-preview");
  const previewTitle = document.getElementById("bundle-preview-title");
  const artifactName = document.getElementById("alignment-artifact-name");
  const readyNote = document.getElementById("alignment-ready-note");
  const artifactRisk = document.getElementById("alignment-artifact-risk");
  const artifactEvidence = document.getElementById("alignment-artifact-evidence");
  const artifactJudgment = document.getElementById("alignment-artifact-judgment");
  const artifactVerdict = document.getElementById("alignment-artifact-verdict");
  const artifactWorkdir = document.getElementById("alignment-artifact-workdir");
  const controlSummary = document.getElementById("alignment-control-summary");
  const judgmentMap = document.getElementById("alignment-judgment-map");
  const diagnosticsStrip = document.getElementById("alignment-diagnostics-strip");
  const artifactSource = document.getElementById("alignment-artifact-source");
  const sourcePathLabel = document.getElementById("alignment-source-path");
  const specPreview = document.getElementById("alignment-spec-preview");
  const roleList = document.getElementById("alignment-role-list");
  const workflowDiagram = document.getElementById("alignment-workflow-diagram");
  const importRunButton = document.getElementById("alignment-import-run-button");
  const sourceOpenButton = document.getElementById("alignment-source-open-button");
  const sourceSyncButton = document.getElementById("alignment-source-sync-button");
  const workdirContext = document.getElementById("alignment-workdir-context");
  const workdirContextStatus = document.getElementById("alignment-workdir-context-status");
  const workdirContextOptions = document.getElementById("alignment-workdir-context-options");

  const ACTIVE_STATUSES = new Set(["running", "validating", "repairing"]);
  const SESSION_STORAGE_KEY = "loopora:alignment-session:v1";
  const EVENT_TYPES = [
    "alignment_session_created",
    "alignment_source_context_selected",
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
  let submitPending = false;
  let cancelPending = false;
  let errorTimer = null;
  const commandDrafts = new Map();
  let lastExecutorKind = executorInput?.value || "codex";
  let workdirContextState = {
    workdir: "",
    options: [],
    requiresChoice: false,
    selectedOptionId: "",
    loaded: false,
  };
  let workdirContextTimer = null;

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

  function statusLabel(status) {
    const labels = {
      idle: localeText("未开始", "Idle"),
      running: localeText("编排中", "Composing"),
      waiting_user: localeText("等待回复", "Waiting"),
      validating: localeText("校验中", "Validating"),
      repairing: localeText("自动修复", "Repairing"),
      ready: localeText("方案已准备好", "Plan ready"),
      failed: localeText("失败", "Failed"),
      imported: localeText("已导入", "Imported"),
      running_loop: localeText("运行中", "Running loop"),
    };
    return labels[status] || status || "-";
  }

  function isActiveStatus(status) {
    return ACTIVE_STATUSES.has(String(status || ""));
  }

  function activeStatusCopy(status) {
    const labels = {
      running: {
        label: localeText("Agent 正在执行", "Agent running"),
        meta: localeText(`${executorLabel()} 正在处理`, `${executorLabel()} is working`),
      },
      validating: {
        label: localeText("正在校验 Loop", "Validating Loop"),
        meta: localeText("检查方案契约与运行面", "Checking plan contract and runtime surface"),
      },
      repairing: {
        label: localeText("正在自动修复", "Repairing plan"),
        meta: localeText("根据校验结果修复", "Repairing from validation results"),
      },
    };
    return labels[String(status || "")] || {
      label: statusLabel(status),
      meta: "",
    };
  }

  function setSendButtonState(status = currentSession?.status || "idle") {
    const active = isActiveStatus(status);
    sendButton.disabled = submitPending || cancelPending;
    sendButton.classList.toggle("is-stop", active);
    sendButton.dataset.action = active ? "cancel" : "send";
    sendButton.textContent = active ? "■" : "↑";
    sendButton.setAttribute("aria-label", active ? localeText("停止执行", "Stop execution") : localeText("发送", "Send"));
    sendButton.setAttribute("aria-busy", String(submitPending || cancelPending || active));
  }

  function setLiveSummaryStatus(status = currentSession?.status || "idle") {
    if (!liveToggle || !liveSummaryLabel || !liveSummaryMeta) {
      return;
    }
    const active = isActiveStatus(status);
    liveToggle.classList.toggle("is-active", active);
    liveToggle.dataset.status = status;
    liveSummaryLabel.textContent = localeText("执行详情", "Execution details");
    liveSummaryMeta.textContent = active
      ? localeText("实时事件流", "Live event stream")
      : (latestEventId ? localeText(`最近事件 #${latestEventId}`, `Latest event #${latestEventId}`) : "");
  }

  function setExecutionState(status = currentSession?.status || "idle") {
    const normalized = String(status || "idle");
    [panel, shell, startForm, chat, liveDetails].forEach((element) => {
      if (!element) {
        return;
      }
      element.dataset.alignmentExecutionState = normalized;
      element.classList.toggle("is-executing", isActiveStatus(normalized));
    });
    cancelButton.hidden = !isActiveStatus(normalized);
    cancelButton.disabled = cancelPending;
    setSendButtonState(normalized);
    setLiveSummaryStatus(normalized);
  }

  function setBusy(isBusy) {
    submitPending = Boolean(isBusy) && !isActiveStatus(currentSession?.status || "");
    setExecutionState();
  }

  function setStatus(message, kind = "", status = "") {
    statusPill.textContent = message;
    const normalized = String(status || kind || currentSession?.status || "");
    statusPill.className = `alignment-status-pill${kind ? ` is-${kind}` : ""}`;
    statusPill.classList.toggle("is-active", isActiveStatus(normalized));
    statusPill.dataset.status = normalized || "idle";
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
      : localeText("选择运行目录", "Choose run directory");
    workdirChip.title = currentWorkdir || "";
    if (profile.command_only || isCommandMode()) {
      agentChip.textContent = `${agentChip.textContent} · ${localeText("自定义命令", "Custom")}`;
    }
  }

  function syncWorkdirInputFromSession() {
    const sessionWorkdir = String(currentSession?.workdir || "").trim();
    if (!sessionWorkdir) {
      return;
    }
    workdirInput.value = sessionWorkdir;
    updateChips();
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
    if (panelName === "workdir") {
      syncWorkdirInputFromSession();
      loadWorkdirContext().catch(() => {});
    }
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
    submitPending = false;
    cancelPending = false;
    workdirContextState = {workdir: "", options: [], requiresChoice: false, selectedOptionId: "", loaded: false};
    forgetSession();
    closeTools();
    renderWorkdirContext();
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
    renderJudgmentMap({}, []);
    emptyState.hidden = false;
    shell?.classList.remove("has-session", "has-artifact");
    setStatus(localeText("未开始", "Idle"));
    syncActiveExecutionCopy("");
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

  function selectedWorkdirContextOption() {
    return (workdirContextState.options || []).find((option) => option.option_id === workdirContextState.selectedOptionId) || null;
  }

  function shouldRequireWorkdirContextChoice() {
    const currentWorkdir = workdirInput.value.trim();
    return Boolean(
      currentWorkdir
      && workdirContextState.loaded
      && workdirContextState.workdir === currentWorkdir
      && workdirContextState.requiresChoice
      && !workdirContextState.selectedOptionId
    );
  }

  function renderWorkdirContext() {
    if (!workdirContext || !workdirContextOptions || !workdirContextStatus) {
      return;
    }
    const options = workdirContextState.options || [];
    const visibleOptions = options.filter((option) => option.action !== "regenerate");
    if (!workdirContextState.workdir || (!workdirContextState.requiresChoice && visibleOptions.length === 0)) {
      workdirContext.hidden = true;
      workdirContextOptions.innerHTML = "";
      workdirContextStatus.textContent = "";
      return;
    }
    workdirContext.hidden = false;
    workdirContextStatus.textContent = workdirContextState.requiresChoice
      ? localeText("请选择启动方式", "Choose how to start")
      : localeText("未发现可继承产物", "No reusable artifacts found");
    const renderedOptions = options.filter((option) => option.action !== "regenerate" || workdirContextState.requiresChoice);
    workdirContextOptions.innerHTML = renderedOptions.map((option) => {
      const optionId = escapeHtml(option.option_id || "");
      const checked = option.option_id === workdirContextState.selectedOptionId ? " checked" : "";
      const label = escapeHtml(localeText(option.label_zh || "", option.label_en || option.label_zh || ""));
      const description = escapeHtml(localeText(option.description_zh || "", option.description_en || option.description_zh || ""));
      return `
        <label class="alignment-workdir-context-option" data-testid="alignment-workdir-context-option">
          <input type="radio" name="alignment_source_option" value="${optionId}"${checked} />
          <span>
            <strong>${label}</strong>
            <small>${description}</small>
          </span>
        </label>
      `;
    }).join("");
    workdirContextOptions.querySelectorAll("input[name='alignment_source_option']").forEach((input) => {
      input.addEventListener("change", () => {
        workdirContextState.selectedOptionId = input.value;
        renderWorkdirContext();
        showError("");
      });
    });
  }

  async function loadWorkdirContext({force = false} = {}) {
    const workdir = workdirInput.value.trim();
    if (!workdir) {
      workdirContextState = {workdir: "", options: [], requiresChoice: false, selectedOptionId: "", loaded: false};
      renderWorkdirContext();
      return;
    }
    if (!force && workdirContextState.loaded && workdirContextState.workdir === workdir) {
      renderWorkdirContext();
      return;
    }
    if (workdirContext && workdirContextStatus) {
      workdirContext.hidden = false;
      workdirContextStatus.textContent = localeText("正在检查…", "Checking...");
    }
    try {
      const payload = await fetchJson("/api/alignments/workdir-context", {
        method: "POST",
        body: JSON.stringify({workdir}),
      });
      const nextOptions = Array.isArray(payload.options) ? payload.options : [];
      const keepSelection = workdirContextState.workdir === workdir
        && nextOptions.some((option) => option.option_id === workdirContextState.selectedOptionId);
      workdirContextState = {
        workdir,
        options: nextOptions,
        requiresChoice: Boolean(payload.requires_choice),
        selectedOptionId: keepSelection ? workdirContextState.selectedOptionId : "",
        loaded: true,
      };
      if (!workdirContextState.requiresChoice) {
        workdirContextState.selectedOptionId = payload.recommended_option_id || "";
      }
      renderWorkdirContext();
    } catch (error) {
      workdirContextState = {workdir, options: [], requiresChoice: false, selectedOptionId: "", loaded: false};
      if (workdirContext && workdirContextStatus) {
        workdirContext.hidden = false;
        workdirContextStatus.textContent = error.message || localeText("检查失败", "Check failed");
      }
      if (workdirContextOptions) {
        workdirContextOptions.innerHTML = "";
      }
    }
  }

  function scheduleWorkdirContextLoad() {
    clearTimeout(workdirContextTimer);
    workdirContextTimer = window.setTimeout(() => {
      loadWorkdirContext().catch(() => {});
    }, 300);
  }

  function collectStartPayload() {
    const commandMode = isCommandMode();
    const payload = {
      executor_kind: executorInput.value,
      executor_mode: commandMode ? "command" : "preset",
      workdir: workdirInput.value.trim(),
      message: messageInput.value.trim(),
      model: commandMode ? "" : modelInput.value.trim(),
      reasoning_effort: commandMode ? "" : effortInput.value.trim(),
      command_cli: commandMode ? commandCliInput.value.trim() : "",
      command_args_text: commandMode ? commandArgsInput.value : "",
    };
    const selectedOption = selectedWorkdirContextOption();
    if (selectedOption && selectedOption.action !== "regenerate" && selectedOption.action !== "continue_session") {
      payload.source_option_id = selectedOption.option_id;
    }
    return payload;
  }

  function syncActiveExecutionCopy(status) {
    if (thinkingStatus) {
      thinkingStatus.hidden = true;
      thinkingStatus.textContent = "";
    }
    const statusText = String(currentSession?.status || status);
    setLiveSummaryStatus(statusText);
    if (!isActiveStatus(statusText)) {
      return;
    }
    const copy = activeStatusCopy(statusText);
    const workingTitle = transcriptEl.querySelector("[data-working-title]");
    const workingMeta = transcriptEl.querySelector("[data-working-meta]");
    if (workingTitle) {
      workingTitle.textContent = copy.label;
    }
    if (workingMeta) {
      workingMeta.textContent = copy.meta;
    }
  }

  function renderSession(session, options = {}) {
    currentSession = session;
    rememberSession(session.id);
    syncWorkdirInputFromSession();
    shell?.classList.add("has-session");
    emptyState.hidden = true;
    chat.hidden = false;
    if (liveDetails) {
      liveDetails.hidden = false;
    }
    const status = String(session.status || "idle");
    setStatus(statusLabel(status), status === "ready" ? "ready" : (status === "failed" ? "failed" : ""), status);
    sessionMeta.textContent = `${statusLabel(status)} · ${basename(session.workdir)} · ${session.id}`;
    setBusy(isActiveStatus(status));
    if (!isActiveStatus(status) && status !== "failed") {
      setLiveDetailsOpen(false);
    }
    updateChips();
    renderTranscript(session.transcript || [], session);
    syncActiveExecutionCopy(status);
    if (status === "ready") {
      loadReadyBundle({reveal: options.revealReady !== false}).catch((error) => {
        renderBundleLoadError(error.message || localeText("无法加载 Loop 方案。", "Unable to load the loop plan."));
      });
    } else if (status === "failed" && String(session.bundle_path || "").trim()) {
      loadReadyBundle({
        reveal: options.revealRepair !== false,
        allowImport: false,
        repairNote: session.error_message || localeText(
          "方案文件未通过校验；可以打开源文件修复，然后重新同步。",
          "The plan file did not pass validation; open the source, repair it, then reload."
        ),
      }).catch((error) => {
        renderBundleLoadError(error.message || localeText("无法加载待修复的方案文件。", "Unable to load the plan file that needs repair."));
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

  function fillStarterPrompt(button) {
    if (!messageInput || !button) {
      return;
    }
    const prompt = window.LooporaUI.currentLocale() === "zh" ? button.dataset.starterZh : button.dataset.starterEn;
    if (!prompt) {
      return;
    }
    messageInput.value = prompt;
    showError("");
    messageInput.focus();
    messageInput.dispatchEvent(new Event("input", {bubbles: true}));
    if (typeof messageInput.setSelectionRange === "function") {
      messageInput.setSelectionRange(messageInput.value.length, messageInput.value.length);
    }
  }

  function renderWorkingCard(session = currentSession) {
    const status = String(session?.status || "");
    if (!isActiveStatus(status)) {
      return;
    }
    const copy = activeStatusCopy(status);
    const card = document.createElement("article");
    card.className = "alignment-working-card";
    card.dataset.testid = "alignment-working-card";
    card.setAttribute("aria-live", "polite");
    card.innerHTML = `
      <span class="alignment-working-beacon" aria-hidden="true"></span>
      <span class="alignment-working-copy">
        <strong data-working-title>${escapeHtml(copy.label)}</strong>
        <span data-working-meta>${escapeHtml(copy.meta)}</span>
      </span>
      <span class="alignment-working-dots" aria-hidden="true"><i></i><i></i><i></i></span>
    `;
    transcriptEl.append(card);
  }

  function normalizeDecisionOptions(options) {
    if (!Array.isArray(options)) {
      return [];
    }
    return options
      .filter((option) => option && typeof option === "object")
      .map((option, index) => ({
        id: String(option.id || `option_${index + 1}`),
        label: String(option.label || "").trim(),
        description: String(option.description || "").trim(),
        recommended: option.recommended === true,
        userReply: String(option.user_reply || option.userReply || option.label || "").trim(),
      }))
      .filter((option) => option.label && option.userReply)
      .slice(0, 4);
  }

  function renderDecisionOptions(container, entry, {canChoose = false} = {}) {
    const options = normalizeDecisionOptions(entry?.decision_options);
    if (!options.length) {
      return;
    }
    const group = document.createElement("div");
    group.className = "alignment-decision-options";
    group.dataset.testid = "alignment-decision-options";
    group.setAttribute("role", "group");
    group.setAttribute("aria-label", localeText("推荐选择", "Recommended choices"));
    options.forEach((option) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `alignment-decision-option${option.recommended ? " is-recommended" : ""}`;
      button.dataset.testid = "alignment-decision-option";
      button.dataset.optionId = option.id;
      button.disabled = !canChoose;
      const badge = option.recommended
        ? `<span class="alignment-decision-badge">${escapeHtml(localeText("推荐", "Recommended"))}</span>`
        : "";
      button.innerHTML = `
        <span class="alignment-decision-option-title">
          <strong>${escapeHtml(option.label)}</strong>
          ${badge}
        </span>
        <small>${escapeHtml(option.description)}</small>
      `;
      button.addEventListener("click", async () => {
        if (!canChoose || !currentSession?.id || isActiveStatus(currentSession.status || "")) {
          return;
        }
        showError("");
        setBusy(true);
        try {
          await appendMessage(option.userReply);
        } catch (error) {
          showError(error.message || localeText("发送选择失败。", "Failed to send choice."));
          setBusy(false);
        }
      });
      group.append(button);
    });
    container.append(group);
  }

  function renderTranscript(transcript, session = currentSession) {
    transcriptEl.innerHTML = "";
    const latestAssistantIndex = [...transcript].map((entry, index) => ({entry, index})).reverse()
      .find((item) => item.entry?.role === "assistant")?.index ?? -1;
    transcript.forEach((entry, index) => {
      const bubble = document.createElement("article");
      bubble.className = `alignment-message alignment-message--${entry.role === "user" ? "user" : "assistant"}`;
      bubble.innerHTML = `
        <p>${escapeHtml(entry.content || "")}</p>
      `;
      if (entry.role === "assistant") {
        renderDecisionOptions(bubble, entry, {
          canChoose: index === latestAssistantIndex && !isActiveStatus(session?.status || "") && String(session?.status || "") !== "ready",
        });
      }
      transcriptEl.append(bubble);
    });
    renderWorkingCard(session);
    if (String(session?.status || "") === "failed") {
      const failure = document.createElement("article");
      failure.className = "alignment-failure-card";
      failure.innerHTML = `
        <strong>${escapeHtml(localeText("这轮没有生成可用方案", "This turn did not produce a usable plan"))}</strong>
        <p>${escapeHtml(session?.error_message || localeText("可以查看执行详情，或让智能体按这个错误继续修复。", "Check execution details, or ask the Agent to repair from this error."))}</p>
        <div class="card-actions card-actions-compact">
          <button class="primary-button" type="button" data-repair-failure data-testid="alignment-repair-failure-button">${escapeHtml(localeText("继续修复", "Continue repair"))}</button>
          <button class="secondary-button" type="button" data-open-live-details>${escapeHtml(localeText("查看详情", "View details"))}</button>
          <button class="ghost-button" type="button" data-open-panel="advanced">${escapeHtml(localeText("智能体设置", "Agent settings"))}</button>
        </div>
      `;
      failure.querySelector("[data-repair-failure]")?.addEventListener("click", async () => {
        if (!currentSession?.id) {
          return;
        }
        setBusy(true);
        try {
          await appendMessage(localeText("请根据上面的校验错误继续修复这个 Loop 方案。", "Please repair this loop plan using the validation error above."));
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
    setLiveSummaryStatus(currentSession?.status || "idle");
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
      item.dataset.testid = "alignment-history-item";
      item.dataset.sessionId = session.id;
      const sessionStatus = String(session.status || "");
      item.dataset.sessionStatus = sessionStatus;
      item.classList.toggle("is-active", currentSession?.id === session.id);
      const isActive = isActiveStatus(sessionStatus);
      item.classList.toggle("is-running", isActive);
      item.innerHTML = `
        <button class="alignment-history-open" type="button" data-testid="alignment-history-open">
          <strong>${escapeHtml(session.title || session.id)}</strong>
          <span class="alignment-history-status">
            <span class="alignment-history-status-dot" aria-hidden="true"></span>
            <span>${escapeHtml(statusLabel(session.status))} · ${escapeHtml(session.executor_kind || "")}</span>
          </span>
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
      return null;
    }
    const payload = await fetchJson(`/api/alignments/sessions/${encodeURIComponent(currentSession.id)}`);
    renderSession(payload.session);
    return payload.session;
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
      renderBundleLoadError(payload.error || localeText("方案暂时无法读取。", "The plan cannot be read right now."));
      return;
    }
    renderBundlePreview(payload, options);
  }

  function renderBundleLoadError(message) {
    shell?.classList.add("has-artifact");
    readyPreview.hidden = false;
    readyPreview.dataset.previewState = "error";
    if (importRunButton) {
      importRunButton.hidden = true;
      importRunButton.closest(".card-actions")?.setAttribute("hidden", "");
    }
    artifactName.textContent = localeText("无法加载 Loop 方案", "Unable to load loop plan");
    previewTitle.textContent = localeText("方案需要重新加载", "Plan needs reload");
    readyNote.textContent = message || "";
    if (artifactRisk) {
      artifactRisk.textContent = localeText("风险：-", "Risk: -");
    }
    if (artifactEvidence) {
      artifactEvidence.textContent = localeText("证据：-", "Evidence: -");
    }
    if (artifactJudgment) {
      artifactJudgment.textContent = localeText("判断：-", "Judgment: -");
    }
    if (artifactVerdict) {
      artifactVerdict.textContent = localeText("裁决：-", "Verdict: -");
    }
    artifactWorkdir.textContent = localeText(
      `运行目录：${basename(currentSession?.workdir || "") || "-"}`,
      `Run directory: ${basename(currentSession?.workdir || "") || "-"}`
    );
    renderControlSummary(null);
    renderJudgmentMap({}, []);
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
        ${escapeHtml(message || localeText("无法加载 Loop 方案。", "Unable to load the loop plan."))}
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
    return text.slice(0, 180) || localeText("Loop 目标已生成。", "Task goal generated.");
  }

  function workflowSummary(preview) {
    const roleById = new Map((preview?.roles || []).map((role) => [role.id, role.name || role.id]));
    return (preview?.steps || [])
      .map((step) => roleById.get(step.role_id) || step.role_id)
      .filter(Boolean)
      .join(" -> ");
  }

  function labeledSummary(labelZh, labelEn, value) {
    return localeText(`${labelZh}：${value || "-"}`, `${labelEn}: ${value || "-"}`);
  }

  function mainRiskSummary(summary) {
    return listSnippet(summary?.risks) || localeText("按方案中的假完成风险收束。", "Controlled from the plan's fake-done risks.");
  }

  function primaryRiskSummary(summary) {
    return (summary?.risks || [])
      .map((value) => String(value || "").trim())
      .filter(Boolean)[0] || localeText("按方案中的假完成风险收束。", "Controlled from the plan's fake-done risks.");
  }

  function evidencePathSummary(summary) {
    const evidence = listSnippet(summary?.evidence) || localeText("运行时写入证据账本。", "Recorded into the run evidence ledger.");
    const coverage = coverageSummary(summary);
    const evidenceText = coverage ? `${evidence}; ${coverage}` : evidence;
    const traceability = summary?.traceability || {};
    if (Number(traceability.mapped_count || 0) > 0) {
      return localeText(
        `${evidenceText}；${traceability.mapped_count}/${traceability.required_count || traceability.mapped_count} 项判断已投影。`,
        `${evidenceText}; ${traceability.mapped_count}/${traceability.required_count || traceability.mapped_count} judgments projected.`
      );
    }
    return evidenceText;
  }

  function coverageSummary(summary) {
    const coverage = summary?.coverage || {};
    const checkCount = Number(coverage.check_count || 0);
    const targetCount = Number(coverage.target_count || 0);
    const requiredCount = Number(coverage.required_target_count || 0);
    const summaryText = localeText(coverage.summary_zh || "", coverage.summary_en || coverage.summary || "");
    if (summaryText && !checkCount && !targetCount) {
      return summaryText;
    }
    if (checkCount && targetCount) {
      return localeText(
        `${checkCount} 项检查 · ${targetCount} 个覆盖目标（${requiredCount} 必需）`,
        `${checkCount} checks · ${targetCount} coverage targets (${requiredCount} required)`
      );
    }
    if (checkCount) {
      return localeText(`${checkCount} 项检查`, `${checkCount} checks`);
    }
    if (targetCount) {
      return localeText(
        `${targetCount} 个覆盖目标（${requiredCount} 必需）`,
        `${targetCount} coverage targets (${requiredCount} required)`
      );
    }
    return "";
  }

  function evidenceStatus(summary) {
    const count = (summary?.evidence || []).filter((value) => String(value || "").trim()).length;
    const coverage = summary?.coverage || {};
    const targetCount = Number(coverage.target_count || 0);
    const traceabilityCount = Number(summary?.traceability?.mapped_count || 0);
    if (targetCount) {
      const checkCount = Number(coverage.check_count || count || 0);
      return localeText(`${checkCount} 检查 · ${targetCount} 目标`, `${checkCount} checks · ${targetCount} targets`);
    }
    if (count) {
      if (traceabilityCount) {
        return localeText(`${count} 项 · ${traceabilityCount} 映射`, `${count} checks · ${traceabilityCount} mapped`);
      }
      return localeText(`${count} 项`, `${count} checks`);
    }
    if (traceabilityCount) {
      return localeText(`${traceabilityCount} 映射`, `${traceabilityCount} mapped`);
    }
    return localeText("已配置", "configured");
  }

  function judgmentStatus(summary) {
    const traceability = summary?.traceability || {};
    const mapped = Number(traceability.mapped_count || 0);
    const required = Number(traceability.required_count || mapped);
    const diagnostics = (summary?.diagnostics || []).filter((item) => String(item?.severity || "") !== "info");
    const base = mapped
      ? localeText(`${mapped}/${required || mapped} 已投影`, `${mapped}/${required || mapped} projected`)
      : localeText("未投影", "not projected");
    if (diagnostics.length) {
      return localeText(`${base} · ${diagnostics.length} 提醒`, `${base} · ${diagnostics.length} warnings`);
    }
    return base;
  }

  function verdictSummary(summary) {
    const gatekeeper = summary?.gatekeeper || {};
    if (gatekeeper.enabled === true) {
      return localeText("守门者依据证据裁决。", "GateKeeper judges from evidence.");
    }
    return localeText("按轮次预算收束。", "Ends by round budget.");
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
        label: localeText("Loopora 适配", "Loopora fit"),
        value: listSnippet(summary.loop_fit_reasons)
          || localeText("长期治理理由未声明。", "Long-running governance reason not declared."),
      },
      {
        label: localeText("成功面", "Success"),
        value: listSnippet(summary.success_surface)
          || localeText("按 Done When 与任务成功面裁决。", "Judged by Done When and the success surface."),
      },
      {
        label: localeText("假完成", "Fake done"),
        value: listSnippet(summary.fake_done_risks)
          || localeText("未声明额外假完成风险。", "No extra fake-done risks declared."),
      },
      {
        label: localeText("证据偏好", "Evidence preferences"),
        value: listSnippet(summary.evidence_preferences)
          || localeText("按任务契约选择证据。", "Evidence follows the task contract."),
      },
      {
        label: localeText("覆盖目标", "Coverage targets"),
        value: coverageSummary(summary)
          || localeText("由 Done When 和裁决面派生。", "Derived from Done When and verdict surfaces."),
      },
      {
        label: localeText("主要风险", "Main risk"),
        value: listSnippet(summary.risks) || localeText("从 Loop 契约中读取。", "Read from the task contract."),
      },
      {
        label: localeText("残余风险", "Residual risk"),
        value: listSnippet(summary.residual_risk_policy)
          || localeText("按任务契约失败关闭。", "Fail closed by the task contract."),
      },
      {
        label: localeText("执行策略", "Execution strategy"),
        value: listSnippet(summary.execution_strategy)
          || localeText("下一轮优先级未声明。", "Next-round priority not declared."),
      },
      {
        label: localeText("判断取舍", "Tradeoffs"),
        value: listSnippet(summary.judgment_tradeoffs)
          || localeText("按任务契约裁决。", "Judged by the task contract."),
      },
      {
        label: localeText("角色姿态", "Role posture"),
        value: listSnippet(summary.role_postures)
          || localeText("角色执行姿态未声明。", "Role posture not declared."),
      },
      {
        label: localeText("证据路径", "Evidence path"),
        value: listSnippet(summary.evidence) || localeText("运行时写入证据账本。", "Recorded into the run evidence ledger."),
      },
      {
        label: localeText("执行顺序", "Execution path"),
        value: workflow.summary || localeText(`${workflow.step_count || 0} 个步骤`, `${workflow.step_count || 0} steps`),
      },
      ...(Array.isArray(summary.local_governance) && summary.local_governance.length ? [{
        label: localeText("本地治理", "Local governance"),
        value: listSnippet(summary.local_governance),
      }] : []),
      {
        label: localeText("守门者", "GateKeeper"),
        value: gatekeeper.enabled === true
          ? localeText("需要证据引用才能结束。", "Requires evidence refs to finish.")
          : localeText("未配置守门者。", "No GateKeeper configured."),
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

  function traceItemLabel(item) {
    const labels = {
      loop_fit: localeText("Loopora 适配", "Loopora fit"),
      collaboration_story: localeText("协作判断", "Collaboration"),
      task_scope: localeText("任务边界", "Task scope"),
      success_surface: localeText("成功面", "Success"),
      fake_done_risks: localeText("假完成", "Fake done"),
      evidence_preferences: localeText("证据偏好", "Evidence"),
      coverage_targets: localeText("覆盖目标", "Coverage"),
      execution_strategy: localeText("执行策略", "Execution strategy"),
      residual_risk_policy: localeText("残余风险", "Risk policy"),
      judgment_tradeoffs: localeText("判断取舍", "Tradeoffs"),
      local_governance: localeText("本地治理", "Local governance"),
      role_posture: localeText("角色姿态", "Role posture"),
      workflow_judgment: localeText("运行流程", "Run flow"),
      gatekeeper_closure: localeText("裁决收口", "Closure"),
      runtime_controls: localeText("运行控制", "Controls"),
    };
    return labels[item?.key] || item?.label || item?.key || "-";
  }

  function surfaceSummary(surfaces) {
    const values = (surfaces || []).map((value) => String(value || "").trim()).filter(Boolean);
    return values.slice(0, 2).join(" / ") || "-";
  }

  function localizedDiagnosticText(item, field) {
    const zh = item?.[`${field}_zh`] || item?.[field];
    const en = item?.[`${field}_en`] || item?.[field];
    return localeText(zh || "", en || "");
  }

  function renderJudgmentMap(traceability, diagnostics = []) {
    if (!judgmentMap || !diagnosticsStrip) {
      return;
    }
    const items = Array.isArray(traceability?.items) ? traceability.items : [];
    const visibleItems = items.slice(0, 12);
    if (!visibleItems.length) {
      judgmentMap.hidden = true;
      judgmentMap.innerHTML = "";
    } else {
      judgmentMap.hidden = false;
      judgmentMap.innerHTML = visibleItems.map((item) => {
        const evidence = (item.evidence || []).map((value) => String(value || "").trim()).filter(Boolean)[0] || "";
        const surface = surfaceSummary(item.surfaces);
        const mapped = item.mapped === true;
        return `
          <div class="alignment-judgment-row" data-mapped="${mapped}">
            <strong>${escapeHtml(traceItemLabel(item))}</strong>
            <span>${escapeHtml(mapped ? surface : localeText("缺少可运行映射", "Missing runnable mapping"))}</span>
            ${evidence ? `<span>${escapeHtml(evidence)}</span>` : ""}
          </div>
        `;
      }).join("");
    }

    const visibleDiagnostics = (diagnostics || [])
      .filter((item) => item && String(item.severity || "") !== "info")
      .slice(0, 3);
    if (!visibleDiagnostics.length) {
      diagnosticsStrip.hidden = true;
      diagnosticsStrip.innerHTML = "";
      return;
    }
    diagnosticsStrip.hidden = false;
    diagnosticsStrip.innerHTML = visibleDiagnostics.map((item) => `
      <div class="alignment-diagnostic-row">
        <strong>${escapeHtml(localizedDiagnosticText(item, "title"))}</strong>
        <span>${escapeHtml(localizedDiagnosticText(item, "message"))}</span>
      </div>
    `).join("");
  }

  function compactRoleSummary(role) {
    const description = String(role.description || "").trim();
    const posture = String(role.posture_notes || "").trim();
    return description || posture || localeText("点击查看完整角色信息。", "Open to inspect the full role definition.");
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
    const allowImport = options.allowImport !== false && String(payload.session?.status || currentSession?.status || "") === "ready";
    readyPreview.dataset.previewState = allowImport ? "ready" : "repair";
    if (importRunButton) {
      importRunButton.hidden = !allowImport;
      importRunButton.disabled = !allowImport;
      if (allowImport) {
        importRunButton.closest(".card-actions")?.removeAttribute("hidden");
      } else {
        importRunButton.closest(".card-actions")?.setAttribute("hidden", "");
      }
    }
    const metadata = payload.metadata || payload.bundle?.metadata || {};
    artifactName.textContent = metadata.name || localeText("Loop 方案", "Loop plan");
    previewTitle.textContent = allowImport
      ? localeText("Loop 已准备好，可以创建并运行", "Plan is ready to create and run")
      : localeText("方案文件需要修复后才能运行", "Plan file needs repair before running");
    readyNote.textContent = allowImport
      ? ""
      : String(options.repairNote || payload.validation?.error || localeText(
        "修复源文件后重新同步，校验通过才可以创建并运行。",
        "Reload after repairing the source file; creation is enabled only after validation passes."
      ));
    const summary = payload.control_summary || {};
    if (artifactRisk) {
      const risk = primaryRiskSummary(summary);
      artifactRisk.textContent = labeledSummary("最大风险", "Risk", risk);
      artifactRisk.title = risk;
    }
    if (artifactEvidence) {
      const evidenceText = evidencePathSummary(summary);
      artifactEvidence.textContent = labeledSummary("证据", "Evidence", evidenceStatus(summary));
      artifactEvidence.title = evidenceText;
    }
    const diagnostics = payload.diagnostics || summary.diagnostics || [];
    if (artifactJudgment) {
      artifactJudgment.textContent = labeledSummary("判断", "Judgment", judgmentStatus({...summary, diagnostics}));
      artifactJudgment.title = evidencePathSummary(summary);
    }
    if (artifactVerdict) {
      artifactVerdict.textContent = labeledSummary("裁决", "Verdict", summary?.gatekeeper?.enabled === true ? "GateKeeper" : verdictSummary(summary));
      artifactVerdict.title = verdictSummary(summary);
    }
    artifactWorkdir.textContent = labeledSummary("运行目录", "Run directory", basename(payload.bundle?.loop?.workdir || ""));
    artifactWorkdir.title = payload.bundle?.loop?.workdir || "";
    renderControlSummary(summary);
    renderJudgmentMap(payload.traceability || summary.traceability || {}, diagnostics);
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
      sourcePathLabel.textContent = "";
      sourcePathLabel.title = payload.source_path || "";
    }
    roleList.innerHTML = "";
    (payload.roles || []).forEach((role) => {
      roleList.append(renderRoleCard(role));
    });
    if (window.LooporaWorkflowDiagram) {
      window.LooporaWorkflowDiagram.renderInto(workflowDiagram, payload.workflow_preview || {}, {variant: "editor"});
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
        setStatus(statusLabel(currentSession.status), currentSession.status === "ready" ? "ready" : (currentSession.status === "failed" ? "failed" : ""), currentSession.status);
        setExecutionState(currentSession.status);
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

  async function cancelCurrentSession() {
    if (!currentSession?.id || !isActiveStatus(currentSession.status)) {
      return;
    }
    cancelPending = true;
    setExecutionState(currentSession.status);
    try {
      const response = await fetchJson(`/api/alignments/sessions/${encodeURIComponent(currentSession.id)}/cancel`, {
        method: "POST",
        body: "{}",
      });
      renderSession(response.session);
      await loadHistory();
    } catch (error) {
      showError(error.message || localeText("取消失败。", "Failed to cancel."));
    } finally {
      cancelPending = false;
      setExecutionState(currentSession?.status || "idle");
    }
  }

  startForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    if (isActiveStatus(currentSession?.status || "")) {
      const latestSession = await refreshSession().catch(() => currentSession);
      if (isActiveStatus(latestSession?.status || "")) {
        await cancelCurrentSession();
        return;
      }
    }
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
      showError(localeText("先选择这次 Loop 的运行目录。", "Choose the run directory for this Loop first."));
      openTools("workdir");
      return;
    }
    await loadWorkdirContext();
    if (shouldRequireWorkdirContextChoice()) {
      showError(localeText("这个运行目录已有 Loopora 产物，请先选择继续、改进或重新生成。", "This run directory has Loopora artifacts. Choose continue, improve, or start fresh first."));
      openTools("workdir");
      return;
    }
    const selectedOption = selectedWorkdirContextOption();
    if (selectedOption?.action === "continue_session" && selectedOption.session_id) {
      setBusy(true);
      try {
        await restoreSession(selectedOption.session_id);
        if (!isActiveStatus(currentSession?.status || "")) {
          await appendMessage(message);
          messageInput.value = "";
        }
        closeTools();
      } catch (error) {
        showError(error.message || localeText("继续已有对话失败。", "Failed to continue the existing chat."));
        setBusy(false);
      }
      return;
    }
    setBusy(true);
    try {
      await createSession(payload);
      messageInput.value = "";
      closeTools();
    } catch (error) {
      showError(error.message || localeText("启动对话失败。", "Failed to start conversation."));
      setBusy(false);
    }
  });

  messageInput.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) {
      return;
    }
    event.preventDefault();
    if (isActiveStatus(currentSession?.status || "")) {
      showError(localeText("Agent 正在执行；当前输入会保留，需停止后再发送。", "The Agent is running; your draft is preserved and can be sent after stopping."));
      return;
    }
    startForm.requestSubmit();
  });

  messageInput.addEventListener("input", () => showError(""));
  panel.querySelectorAll("[data-starter-zh][data-starter-en]").forEach((button) => {
    button.addEventListener("click", () => fillStarterPrompt(button));
  });
  workdirInput.addEventListener("input", () => {
    showError("");
    workdirContextState = {
      workdir: workdirInput.value.trim(),
      options: [],
      requiresChoice: false,
      selectedOptionId: "",
      loaded: false,
    };
    renderWorkdirContext();
    scheduleWorkdirContextLoad();
  });
  cancelButton.addEventListener("click", () => {
    cancelCurrentSession().catch(() => {});
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
      showError(error.message || localeText("创建失败，方案源文件已保留。", "Creation failed; the plan source file is preserved."));
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
      renderBundleLoadError(error.message || localeText("无法加载 Loop 方案。", "Unable to load the loop plan."));
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
        const payload = await fetchJson(endpoint, {
          method: "POST",
          body: JSON.stringify({start_path: target.value.trim()}),
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
  setExecutionState("idle");
  loadHistory().catch(() => {});
  restoreSessionIfPresent();
});
