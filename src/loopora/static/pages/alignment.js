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
  const taskGoalInput = document.getElementById("alignment-task-goal");
  const fakeDoneRiskInput = document.getElementById("alignment-fake-done-risk");
  const requiredEvidenceInput = document.getElementById("alignment-required-evidence");
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
  const agentReviewBridge = document.getElementById("alignment-agent-review-bridge");
  const sourceContextBridge = document.getElementById("alignment-source-context-bridge");
  const agentLaunchGuide = document.getElementById("alignment-agent-launch-guide");
  const transcriptEl = document.getElementById("alignment-transcript");
  const consoleOutput = document.getElementById("alignment-console-output");
  const liveDetails = document.getElementById("alignment-live-details");
  const liveToggle = document.getElementById("alignment-live-toggle");
  const liveSummaryLabel = document.getElementById("alignment-live-summary-label");
  const liveSummaryMeta = document.getElementById("alignment-live-summary-meta");
  const liveBody = document.getElementById("alignment-live-body");
  const cancelButton = document.getElementById("alignment-cancel-button");
  const readyPreview = document.getElementById("alignment-ready-preview");
  const repairGuide = document.getElementById("alignment-repair-guide");
  const reviewGate = document.getElementById("alignment-review-gate");
  const reviewGateCheckbox = document.getElementById("alignment-review-confirm");
  const reviewGateEvidence = document.getElementById("alignment-review-gate-evidence");
  const reviewGateJudgment = document.getElementById("alignment-review-gate-judgment");
  const reviewGateClosure = document.getElementById("alignment-review-gate-closure");
  const reviewGateStatus = document.getElementById("alignment-review-gate-status");
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
  const revisePreviewButton = document.getElementById("alignment-revise-preview-button");
  const sourceOpenButton = document.getElementById("alignment-source-open-button");
  const sourceSyncButton = document.getElementById("alignment-source-sync-button");
  const workdirContext = document.getElementById("alignment-workdir-context");
  const workdirContextStatus = document.getElementById("alignment-workdir-context-status");
  const workdirContextOptions = document.getElementById("alignment-workdir-context-options");

  const ACTIVE_STATUSES = new Set(["running", "validating", "repairing"]);
  const MISSING_ITEM_LABELS_ZH = {
    loop_fit: "Loopora 适配",
    task_scope: "任务边界",
    success_surface: "完成标准",
    fake_done_risks: "伪完成风险",
    evidence_preferences: "必需证据",
    execution_strategy: "执行策略",
    judgment_tradeoffs: "判断取舍",
    residual_risk_policy: "残余风险",
    local_governance: "本地治理责任",
    role_posture: "角色姿态",
    workflow_shape: "运行流程",
    workdir_facts: "运行目录事实",
  };
  const MISSING_ITEM_LABELS_EN = {
    loop_fit: "Loopora fit",
    task_scope: "Task scope",
    success_surface: "Success criteria",
    fake_done_risks: "Fake-done risks",
    evidence_preferences: "Evidence expectations",
    execution_strategy: "Execution strategy",
    judgment_tradeoffs: "Judgment tradeoffs",
    residual_risk_policy: "Residual risk policy",
    local_governance: "Local governance",
    role_posture: "Role posture",
    workflow_shape: "Workflow shape",
    workdir_facts: "Run directory facts",
  };
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
    "alignment_ready_review_started",
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
  let agentLaunchCopyTimer = null;
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

  function writeClipboardTextWithSelectionFallback(value) {
    const text = String(value || "");
    return new Promise((resolve, reject) => {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.left = "-9999px";
      textarea.style.top = "0";
      document.body.appendChild(textarea);
      textarea.select();
      try {
        if (document.execCommand("copy")) {
          resolve();
        } else {
          reject(new Error("copy failed"));
        }
      } catch (error) {
        reject(error);
      } finally {
        document.body.removeChild(textarea);
      }
    });
  }

  function writeClipboardText(value) {
    const text = String(value || "");
    if (!text) {
      return Promise.reject(new Error("empty copy value"));
    }
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      return navigator.clipboard.writeText(text).catch(() => writeClipboardTextWithSelectionFallback(text));
    }
    return writeClipboardTextWithSelectionFallback(text);
  }

  function textLooksChinese(value) {
    return /[\u3400-\u9fff]/.test(String(value || ""));
  }

  function collectJudgmentBrief() {
    return {
      taskGoal: taskGoalInput?.value.trim() || "",
      fakeDoneRisk: fakeDoneRiskInput?.value.trim() || "",
      requiredEvidence: requiredEvidenceInput?.value.trim() || "",
    };
  }

  function firstMissingJudgmentField(brief = collectJudgmentBrief()) {
    if (!brief.taskGoal) {
      return taskGoalInput;
    }
    if (!brief.fakeDoneRisk) {
      return fakeDoneRiskInput;
    }
    if (!brief.requiredEvidence) {
      return requiredEvidenceInput;
    }
    return null;
  }

  function judgmentBriefHasAnyValue(brief = collectJudgmentBrief()) {
    return Boolean(brief.taskGoal || brief.fakeDoneRisk || brief.requiredEvidence);
  }

  function composeJudgmentMessage(additionalMessage = messageInput.value.trim()) {
    const brief = collectJudgmentBrief();
    const joined = [brief.taskGoal, brief.fakeDoneRisk, brief.requiredEvidence, additionalMessage].join("\n");
    const labels = textLooksChinese(joined) || window.LooporaUI.currentLocale() === "zh"
      ? {
          taskGoal: "任务目标",
          fakeDoneRisk: "伪完成风险",
          requiredEvidence: "必需证据",
          additionalContext: "补充上下文",
        }
      : {
          taskGoal: "Task goal",
          fakeDoneRisk: "Fake-done risk",
          requiredEvidence: "Required evidence",
          additionalContext: "Additional context",
        };
    const parts = [
      `${labels.taskGoal}:\n${brief.taskGoal}`,
      `${labels.fakeDoneRisk}:\n${brief.fakeDoneRisk}`,
      `${labels.requiredEvidence}:\n${brief.requiredEvidence}`,
    ];
    if (additionalMessage) {
      parts.push(`${labels.additionalContext}:\n${additionalMessage}`);
    }
    return parts.join("\n\n");
  }

  function clearJudgmentBriefInputs() {
    [taskGoalInput, fakeDoneRiskInput, requiredEvidenceInput].forEach((input) => {
      if (input) {
        input.value = "";
      }
    });
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

  function statusLabel(status, stage = "") {
    if (status === "waiting_user" && stage) {
      const stageLabels = {
        clarifying: localeText("判断不足，需要补充", "Judgment incomplete"),
        agreement_ready: localeText("等待确认协议", "Waiting for agreement"),
        confirmed: localeText("已确认协议", "Agreement confirmed"),
        compiling: localeText("正在编译方案", "Compiling plan"),
        ready_review: localeText("等待复核", "Waiting for review"),
      };
      if (stageLabels[stage]) {
        return stageLabels[stage];
      }
    }
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
    if (agentReviewBridge) {
      agentReviewBridge.hidden = true;
      agentReviewBridge.innerHTML = "";
    }
    if (sourceContextBridge) {
      sourceContextBridge.hidden = true;
      sourceContextBridge.innerHTML = "";
    }
    transcriptEl.innerHTML = "";
    readyPreview.hidden = true;
    resetReadyReviewGate();
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
      message: composeJudgmentMessage(),
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
    const stage = String(session.alignment_stage || "");
    setStatus(statusLabel(status, stage), status === "ready" ? "ready" : (status === "failed" ? "failed" : ""), status);
    sessionMeta.textContent = `${statusLabel(status, stage)} · ${basename(session.workdir)} · ${session.id}`;
    setBusy(isActiveStatus(status));
    if (!isActiveStatus(status) && status !== "failed") {
      setLiveDetailsOpen(false);
    }
    updateChips();
    const shouldRevealAgentReview = renderAgentReviewBridge(session);
    const shouldRevealSourceContext = renderSourceContextBridge(session);
    renderTranscript(session.transcript || [], session);
    syncActiveExecutionCopy(status);
    if (shouldRevealAgentReview || shouldRevealSourceContext) {
      scrollRegion?.scrollTo({top: 0});
    }
    if (status === "ready") {
      loadReadyBundle({reveal: options.revealReady !== false}).catch((error) => {
        renderBundleLoadError(error.message || localeText("无法加载 Loop 方案。", "Unable to load the loop plan."));
      });
    } else if (status === "running_loop" && String(session.linked_run_id || "").trim() && String(session.bundle_path || "").trim()) {
      loadReadyBundle({reveal: options.revealReady !== false}).catch((error) => {
        renderBundleLoadError(error.message || localeText("无法加载已启动的 Loop 方案。", "Unable to load the launched loop plan."));
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
      resetReadyReviewGate();
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
    const locale = window.LooporaUI.currentLocale();
    if (taskGoalInput) {
      taskGoalInput.value = locale === "zh" ? (button.dataset.goalZh || "") : (button.dataset.goalEn || "");
    }
    if (fakeDoneRiskInput) {
      fakeDoneRiskInput.value = locale === "zh" ? (button.dataset.fakeDoneZh || "") : (button.dataset.fakeDoneEn || "");
    }
    if (requiredEvidenceInput) {
      requiredEvidenceInput.value = locale === "zh" ? (button.dataset.evidenceZh || "") : (button.dataset.evidenceEn || "");
    }
    messageInput.value = locale === "zh" ? (button.dataset.contextZh || "") : (button.dataset.contextEn || "");
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

  function agentReviewItemLabel(itemId) {
    const labels = {
      success_surface: localeText("完成标准", "Success criteria"),
      fake_done_risks: localeText("伪完成风险", "Fake-done risks"),
      evidence_preferences: localeText("必需证据", "Evidence expectations"),
      loop_fit: localeText("Loopora fit", "Loopora fit"),
      execution_strategy: localeText("执行策略", "Execution strategy"),
      judgment_tradeoffs: localeText("判断取舍", "Judgment tradeoffs"),
      residual_risk_policy: localeText("残余风险", "Residual risk policy"),
      local_governance: localeText("本地治理责任", "Local governance"),
    };
    return labels[String(itemId || "")] || String(itemId || "").replaceAll("_", " ");
  }

  function agentReviewSuggestedReply(review) {
    const projectedReply = String(review?.suggested_reply || "").trim();
    if (projectedReply) {
      return projectedReply;
    }
    if (review?.loopora_fit_contradiction === true || review?.review_mode === "not_fit") {
      return localeText(
        "请先重新判断这个任务是否适合 Loopora：如果仍要继续，请说明后续轮次会新增哪些证据、handoff 或 GateKeeper 裁决价值；如果不适合，请明确建议不要生成可运行 Loop。",
        "First re-check whether this task fits Loopora. If we should continue, explain what later evidence, handoffs, or GateKeeper judgment would add. If it does not fit, clearly recommend not generating a runnable Loop."
      );
    }
    return localeText(
      "请基于上面的任务与判断，先确认 Loopora fit，并把完成标准、伪完成风险、证据预期、执行策略、判断取舍、残余风险和本地治理责任整理成可审查的 Loop 预览。",
      "Based on the task and judgment above, first confirm Loopora fit, then organize the success criteria, fake-done risks, evidence expectations, execution strategy, judgment tradeoffs, residual-risk policy, and local governance into a reviewable Loop preview."
    );
  }

  function fillAgentReviewReply(review) {
    const suggestedReply = agentReviewSuggestedReply(review);
    messageInput.value = suggestedReply;
    showError("");
    messageInput.focus();
    messageInput.dispatchEvent(new Event("input", {bubbles: true}));
    if (typeof messageInput.setSelectionRange === "function") {
      messageInput.setSelectionRange(messageInput.value.length, messageInput.value.length);
    }
  }

  function renderAgentReviewBridge(session = currentSession) {
    if (!agentReviewBridge) {
      return false;
    }
    const review = session?.agent_entry_review || {};
    const status = String(session?.status || "");
    const shouldShow = review?.source === "agent_entry"
      && review.requires_web_alignment === true
      && status !== "ready";
    if (!shouldShow) {
      agentReviewBridge.hidden = true;
      agentReviewBridge.innerHTML = "";
      return false;
    }
    const reviewMode = review.loopora_fit_contradiction === true || review.review_mode === "not_fit" ? "not_fit" : "missing_candidate_plan";
    const itemIds = Array.isArray(review.missing_judgment_item_ids) && review.missing_judgment_item_ids.length
      ? review.missing_judgment_item_ids
      : ["success_surface", "fake_done_risks", "evidence_preferences", "loop_fit", "execution_strategy", "judgment_tradeoffs", "residual_risk_policy", "local_governance"];
    const itemMarkup = itemIds.map((itemId) => `
      <li>
        <span aria-hidden="true"></span>
        <strong>${escapeHtml(agentReviewItemLabel(itemId))}</strong>
      </li>
    `).join("");
    const active = isActiveStatus(status);
    const title = reviewMode === "not_fit"
      ? localeText("先重新定义为什么需要 Loop", "First redefine why a Loop is needed")
      : localeText("这还不是可运行 Loop", "This is not a runnable Loop yet");
    const body = reviewMode === "not_fit"
      ? localeText(
        "这次 /loopora-plan 没有提交候选方案文件，而且任务摘要像一次性处理或无需后续新证据的工作。继续前，先证明后续证据、handoff 或 GateKeeper 裁决会带来真实价值。",
        "This /loopora-plan did not submit a candidate plan file, and the task summary looks like one-off work or work with no later evidence. Before continuing, prove that later evidence, handoffs, or GateKeeper judgment add real value."
      )
      : localeText(
        "这次 /loopora-plan 来自宿主 Agent，但没有候选方案文件。Loopora 已保留任务和来源，只能先做 Web review，补齐关键判断后才会生成可审查预览。",
        "This /loopora-plan came from the host Agent but did not include a candidate plan file. Loopora preserved the task and provenance, and must stay in Web review until the missing judgment is filled in."
      );
    const taskMessage = String(review.task_message || "").trim();
    const taskAnchorMarkup = taskMessage
      ? `
        <section class="alignment-agent-review-source" data-testid="alignment-agent-review-source">
          <span>${escapeHtml(localeText("任务锚点", "Task anchor"))}</span>
          <p>${escapeHtml(taskMessage)}</p>
        </section>
      `
      : "";
    agentReviewBridge.hidden = false;
    agentReviewBridge.dataset.reviewMode = reviewMode;
    const reviewStage = String(session?.alignment_stage || "");
    agentReviewBridge.innerHTML = `
      <div class="alignment-agent-review-copy">
        <span class="alignment-agent-review-kicker">/loopora-plan Web review</span>
        <h3>${escapeHtml(title)}</h3>
        <p>${escapeHtml(body)}</p>
        ${taskAnchorMarkup}
        <div class="alignment-agent-review-meta">
          <span>${escapeHtml(localeText("来源", "Source"))}: ${escapeHtml(review.adapter || executorLabel(session))}</span>
          <span>${escapeHtml(localeText("当前状态", "Current state"))}: ${escapeHtml(statusLabel(status, reviewStage))}</span>
          <span>${escapeHtml(localeText("候选方案文件", "Candidate plan file"))}: ${escapeHtml(review.has_candidate_yaml ? localeText("已提供", "provided") : localeText("缺失", "missing"))}</span>
        </div>
      </div>
      <ul class="alignment-agent-review-checklist" data-testid="alignment-agent-review-checklist">
        ${itemMarkup}
      </ul>
      <div class="alignment-agent-review-options" data-testid="alignment-agent-review-options"></div>
      <div class="alignment-agent-review-actions">
        <button class="primary-button" type="button" data-agent-review-send data-testid="alignment-agent-review-send" ${active ? "disabled" : ""}>
          ${escapeHtml(localeText("提交审查并继续", "Send review and continue"))}
        </button>
        <button class="secondary-button" type="button" data-agent-review-fill data-testid="alignment-agent-review-fill">
          ${escapeHtml(localeText("填入审查回复", "Fill review reply"))}
        </button>
      </div>
    `;
    const reviewOptions = agentReviewBridge.querySelector("[data-testid='alignment-agent-review-options']");
    renderDecisionOptions(reviewOptions, {decision_options: review.decision_options || []}, {canChoose: !active});
    if (reviewOptions && !reviewOptions.childElementCount) {
      reviewOptions.hidden = true;
    }
    agentReviewBridge.querySelector("[data-agent-review-fill]")?.addEventListener("click", () => fillAgentReviewReply(review));
    agentReviewBridge.querySelector("[data-agent-review-send]")?.addEventListener("click", async () => {
      if (!currentSession?.id || isActiveStatus(currentSession.status || "")) {
        return;
      }
      showError("");
      setBusy(true);
      try {
        await appendMessage(agentReviewSuggestedReply(review));
      } catch (error) {
        showError(error.message || localeText("提交审查失败。", "Failed to send review."));
        setBusy(false);
      }
    });
    return true;
  }

  function normalizedStringList(value, limit = 6) {
    if (!Array.isArray(value)) {
      return [];
    }
    const items = [];
    value.forEach((item) => {
      const text = String(item || "").trim();
      if (text && !items.includes(text)) {
        items.push(text);
      }
    });
    return items.slice(0, limit);
  }

  function normalizedCount(value) {
    const number = Number(value);
    return Number.isFinite(number) && number >= 0 ? number : 0;
  }

  function sourceTopGapTexts(coverage) {
    if (!Array.isArray(coverage?.top_gaps)) {
      return [];
    }
    const items = [];
    coverage.top_gaps.forEach((gap) => {
      if (!gap || typeof gap !== "object") {
        return;
      }
      const text = String(gap.text || gap.summary || gap.target_id || gap.id || "").trim();
      if (text && !items.includes(text)) {
        items.push(text);
      }
    });
    return items.slice(0, 5);
  }

  function sourceEvidenceClaims(source) {
    if (!Array.isArray(source?.evidence_summary)) {
      return [];
    }
    const items = [];
    source.evidence_summary.forEach((item) => {
      if (!item || typeof item !== "object") {
        return;
      }
      const claim = String(item.claim || item.result || item.id || "").trim();
      if (claim && !items.includes(claim)) {
        items.push(claim);
      }
    });
    return items.slice(0, 3);
  }

  function sourceArtifactLabel(key) {
    const labels = {
      run_contract: localeText("运行判断契约", "Run contract"),
      task_verdict: localeText("任务裁决", "Task verdict"),
      evidence_ledger: localeText("证据账本", "Evidence ledger"),
      evidence_coverage: localeText("覆盖投影", "Coverage projection"),
      evidence_manifest: localeText("证据清单", "Evidence manifest"),
    };
    return labels[String(key || "")] || String(key || "").replaceAll("_", " ");
  }

  function sourceArtifactItems(source) {
    const paths = source?.artifact_paths && typeof source.artifact_paths === "object" ? source.artifact_paths : {};
    return Object.entries(paths)
      .map(([key, value]) => ({
        label: sourceArtifactLabel(key),
        path: String(value || "").trim(),
      }))
      .filter((item) => item.path)
      .slice(0, 5);
  }

  function sourceListMarkup(items, fallback) {
    const visibleItems = normalizedStringList(items, 6);
    if (!visibleItems.length) {
      return `<p class="alignment-source-context-empty">${escapeHtml(fallback)}</p>`;
    }
    return `<ul>${visibleItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
  }

  function renderSourceContextBridge(session = currentSession) {
    if (!sourceContextBridge) {
      return false;
    }
    const agreement = session?.working_agreement && typeof session.working_agreement === "object" ? session.working_agreement : {};
    const source = agreement.source && typeof agreement.source === "object" ? agreement.source : {};
    if (String(source.source_type || "") !== "run") {
      sourceContextBridge.hidden = true;
      sourceContextBridge.innerHTML = "";
      return false;
    }
    const coverage = source.coverage_summary && typeof source.coverage_summary === "object" ? source.coverage_summary : {};
    const verdict = source.task_verdict && typeof source.task_verdict === "object" ? source.task_verdict : {};
    const rawMissingCheckIds = normalizedStringList(coverage.missing_check_ids, 20);
    const missingIds = rawMissingCheckIds.slice(0, 6).map((id) => localeText(`缺失检查：${id}`, `Missing check: ${id}`));
    const topGaps = sourceTopGapTexts(coverage);
    const gapItems = [...topGaps, ...missingIds].slice(0, 6);
    const riskItems = normalizedStringList(coverage.risk_signals, 5);
    const evidenceClaims = sourceEvidenceClaims(source);
    const artifactItems = sourceArtifactItems(source);
    const runId = String(source.source_run_id || "").trim();
    const runStatus = String(source.run_status || "").trim();
    const verdictStatus = String(verdict.status || "").trim();
    const missingCount = normalizedCount(coverage.missing_check_count) || rawMissingCheckIds.length;
    const blockedCount = normalizedCount(coverage.blocked_target_count);
    const weakCount = normalizedCount(coverage.weak_target_count);
    const reason = String(coverage.reason || "").trim();

    sourceContextBridge.hidden = false;
    sourceContextBridge.innerHTML = `
      <div class="alignment-source-context-copy">
        <span class="alignment-source-context-kicker">${escapeHtml(localeText("上一轮证据", "Previous run evidence"))}</span>
        <h3>${escapeHtml(localeText("这次改进从具体缺口开始。", "This revision starts from concrete gaps."))}</h3>
        <p>${escapeHtml(reason || localeText(
          "Loopora 已把上一轮的裁决、覆盖缺口和证据文件带入这次对话；下一版 Loop 应先回应这些缺口。",
          "Loopora carried the previous verdict, coverage gaps, and evidence files into this chat; the next Loop should answer these gaps first."
        ))}</p>
      </div>
      <div class="alignment-source-context-metrics">
        ${runId ? `<span data-testid="alignment-source-run-id">${escapeHtml(localeText("运行", "Run"))}: ${escapeHtml(runId)}</span>` : ""}
        ${runStatus ? `<span>${escapeHtml(localeText("生命周期", "Lifecycle"))}: ${escapeHtml(statusLabel(runStatus))}</span>` : ""}
        ${verdictStatus ? `<span data-testid="alignment-source-task-verdict">${escapeHtml(localeText("任务裁决", "Task verdict"))}: ${escapeHtml(verdictStatus)}</span>` : ""}
        <span data-testid="alignment-source-missing-count">${escapeHtml(localeText("缺失检查", "Missing checks"))}: ${escapeHtml(String(missingCount))}</span>
        <span>${escapeHtml(localeText("弱证据", "Weak targets"))}: ${escapeHtml(String(weakCount))}</span>
        <span>${escapeHtml(localeText("阻断项", "Blocking targets"))}: ${escapeHtml(String(blockedCount))}</span>
      </div>
      <div class="alignment-source-context-grid">
        <article>
          <strong>${escapeHtml(localeText("先修这些缺口", "Gaps to fix first"))}</strong>
          <div data-testid="alignment-source-gap-list">
            ${sourceListMarkup(gapItems, localeText("没有可展示的覆盖缺口；继续检查 GateKeeper 裁决和证据账本。", "No visible coverage gaps; inspect the GateKeeper verdict and evidence ledger."))}
          </div>
        </article>
        <article>
          <strong>${escapeHtml(localeText("风险信号", "Risk signals"))}</strong>
          <div data-testid="alignment-source-risk-list">
            ${sourceListMarkup(riskItems, localeText("没有额外风险信号。", "No additional risk signals."))}
          </div>
        </article>
        <article>
          <strong>${escapeHtml(localeText("最近证据", "Recent evidence"))}</strong>
          <div data-testid="alignment-source-evidence-list">
            ${sourceListMarkup(evidenceClaims, localeText("没有可展示的最近证据摘要。", "No recent evidence summary is available."))}
          </div>
        </article>
        <article>
          <strong>${escapeHtml(localeText("白盒文件", "White-box files"))}</strong>
          <ul data-testid="alignment-source-artifact-list">
            ${artifactItems.length
              ? artifactItems.map((item) => `<li><span>${escapeHtml(item.label)}</span><code>${escapeHtml(item.path)}</code></li>`).join("")
              : `<li>${escapeHtml(localeText("没有可展示的证据文件路径。", "No evidence file paths are available."))}</li>`
            }
          </ul>
        </article>
      </div>
    `;
    return true;
  }

  function renderTranscript(transcript, session = currentSession) {
    transcriptEl.innerHTML = "";
    const latestAssistantIndex = [...transcript].map((entry, index) => ({entry, index})).reverse()
      .find((item) => item.entry?.role === "assistant")?.index ?? -1;
    transcript.forEach((entry, index) => {
      const bubble = document.createElement("article");
      bubble.className = `alignment-message alignment-message--${entry.role === "user" ? "user" : "assistant"}`;
      let missingHtml = "";
      if (entry.role === "assistant" && Array.isArray(entry.missing_items) && entry.missing_items.length) {
        const missingLabels = entry.missing_items.map((id) => {
          const labelZh = MISSING_ITEM_LABELS_ZH[id] || id;
          const labelEn = MISSING_ITEM_LABELS_EN[id] || id;
          return `<li><span aria-hidden="true">⚠</span><span>${escapeHtml(localeText(labelZh, labelEn))}</span></li>`;
        });
        missingHtml = `<ul class="alignment-missing-items" data-testid="alignment-missing-items">${missingLabels.join("")}</ul>`;
      }
      bubble.innerHTML = `
        <p>${escapeHtml(entry.content || "")}</p>
        ${missingHtml}
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
            <span>${escapeHtml(statusLabel(session.status, session.alignment_stage))} · ${escapeHtml(session.executor_kind || "")}</span>
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
    resetReadyReviewGate();
    const agentEntryLaunch = agentEntryProjectionFor({session: currentSession});
    readyPreview.dataset.launchMode = agentEntryLaunch ? "agent-entry" : "web-run";
    if (importRunButton) {
      importRunButton.hidden = true;
      delete importRunButton.dataset.runId;
      delete importRunButton.dataset.copyValue;
      delete importRunButton.dataset.launchAction;
      setBilingualText(importRunButton, agentEntryLaunch ? "修复后回到 Agent" : "修复后运行", agentEntryLaunch ? "Repair before Agent run" : "Repair before running");
      importRunButton.closest(".card-actions")?.setAttribute("hidden", "");
    }
    artifactName.textContent = localeText("无法加载 Loop 方案", "Unable to load loop plan");
    previewTitle.textContent = agentEntryLaunch
      ? localeText("候选方案需要重新加载后再回到 Agent", "Candidate plan needs reload before returning to the Agent")
      : localeText("方案需要重新加载", "Plan needs reload");
    readyNote.textContent = agentEntryLaunch
      ? localeText(
        "这份候选来自 /loopora-plan；Web 只负责展示修复面。修好源文件并重新运行 /loopora-plan，READY 后再回到同一个 Agent 执行 /loopora-run。",
        "This candidate came from /loopora-plan; Web only shows the repair surface. Repair the source file, rerun /loopora-plan, then return to the same Agent for /loopora-run after READY."
      )
      : localeText(
        "源文件当前不可作为可运行 Loop 预览。先按修复焦点处理，再重新同步。",
        "The source file cannot be used as a runnable Loop preview yet. Repair the focus items, then reload."
      );
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
    renderRepairGuide({
      visible: true,
      error: message || "",
      sourcePath: currentSession?.bundle_path || "",
      sessionId: currentSession?.id || "",
      agentEntry: agentEntryLaunch,
    });
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

  function readyReviewGateRequired() {
    return Boolean(reviewGate && reviewGate.dataset.required === "true" && !reviewGate.hidden);
  }

  function resetReadyReviewGate() {
    if (reviewGate) {
      reviewGate.hidden = true;
      reviewGate.dataset.required = "false";
    }
    if (reviewGateCheckbox) {
      reviewGateCheckbox.checked = false;
      reviewGateCheckbox.disabled = true;
    }
    if (reviewGateStatus) {
      reviewGateStatus.textContent = "";
    }
    if (importRunButton) {
      importRunButton.removeAttribute("aria-describedby");
    }
  }

  function updateImportRunReviewGate() {
    if (!importRunButton) {
      return;
    }
    const required = readyReviewGateRequired() && importRunButton.dataset.launchAction === "web-run";
    if (!required) {
      importRunButton.removeAttribute("aria-describedby");
      if (reviewGateStatus) {
        reviewGateStatus.textContent = "";
      }
      return;
    }
    importRunButton.setAttribute("aria-describedby", "alignment-review-gate-status");
    if (importRunButton.dataset.busy !== "true") {
      importRunButton.disabled = reviewGateCheckbox?.checked !== true;
    }
    if (reviewGateStatus) {
      reviewGateStatus.textContent = reviewGateCheckbox?.checked === true
        ? localeText("复核完成，可以创建并运行。", "Review confirmed. Ready to create and run.")
        : localeText("确认复核后才能创建并运行。", "Confirm review before creating and running.");
    }
  }

  function renderReadyReviewGate({required, summary, diagnostics = []}) {
    if (!reviewGate) {
      return;
    }
    if (!required) {
      resetReadyReviewGate();
      return;
    }
    reviewGate.hidden = false;
    reviewGate.dataset.required = "true";
    if (reviewGateCheckbox) {
      reviewGateCheckbox.checked = false;
      reviewGateCheckbox.disabled = false;
    }
    if (reviewGateEvidence) {
      reviewGateEvidence.textContent = labeledSummary("证据路径", "Evidence path", evidenceStatus(summary));
      reviewGateEvidence.title = evidencePathSummary(summary);
    }
    if (reviewGateJudgment) {
      reviewGateJudgment.textContent = labeledSummary("判断投影", "Judgment projection", judgmentStatus({...summary, diagnostics}));
      reviewGateJudgment.title = evidencePathSummary(summary);
    }
    if (reviewGateClosure) {
      reviewGateClosure.textContent = labeledSummary(
        "收口",
        "Closure",
        summary?.gatekeeper?.enabled === true ? "GateKeeper" : verdictSummary(summary)
      );
      reviewGateClosure.title = verdictSummary(summary);
    }
    updateImportRunReviewGate();
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

  function traceSurfaceLabel(value) {
    const surface = String(value || "").trim();
    const labels = {
      collaboration_summary: [ "治理摘要", "Governance summary" ],
      "spec.markdown": [ "Loop 契约", "Loop contract" ],
      "spec.markdown#Task": [ "任务契约", "Task contract" ],
      "spec.markdown#Done When": [ "完成标准", "Completion criteria" ],
      "spec.markdown#Success Surface": [ "成功面", "Success surface" ],
      "spec.markdown#Fake Done": [ "假完成护栏", "Fake-done guardrails" ],
      "spec.markdown#Evidence Preferences": [ "证据偏好", "Evidence expectations" ],
      "spec.markdown#Residual Risk": [ "残余风险策略", "Residual-risk policy" ],
      "spec.markdown#Role Notes": [ "本地治理说明", "Local governance notes" ],
      "role_definitions[].prompt_markdown": [ "角色工作姿态", "Role operating posture" ],
      "role_definitions[].posture_notes": [ "角色姿态说明", "Role posture notes" ],
      "workflow.collaboration_intent": [ "运行意图", "Run-flow intent" ],
      "workflow.steps[].inputs": [ "步骤交接输入", "Step handoff inputs" ],
      "workflow.steps[].on_pass": [ "收口动作", "Closure action" ],
      "workflow.steps[].inputs.evidence_query": [ "GateKeeper 证据查询", "GateKeeper evidence query" ],
      "workflow.controls[]": [ "运行控制钩子", "Runtime control hooks" ],
    };
    if (labels[surface]) {
      return localeText(labels[surface][0], labels[surface][1]);
    }
    if (surface.startsWith("spec.markdown#")) {
      return localeText("Loop 契约章节", "Loop contract section");
    }
    if (surface.startsWith("role_definitions[]")) {
      return localeText("角色运行契约", "Role runtime contract");
    }
    if (surface.startsWith("workflow.")) {
      return localeText("运行流程契约", "Run-flow contract");
    }
    return localeText("可运行合同面", "Runnable contract surface");
  }

  function humanSurfaceSummary(surfaces) {
    const seen = new Set();
    const values = (surfaces || [])
      .map((value) => traceSurfaceLabel(value))
      .filter(Boolean)
      .filter((value) => {
        if (seen.has(value)) {
          return false;
        }
        seen.add(value);
        return true;
      });
    return values.slice(0, 2).join(" / ") || localeText("可运行合同面", "Runnable contract surface");
  }

  function traceEvidencePreview(item) {
    const evidence = (item?.evidence || []).map((value) => String(value || "").trim()).filter(Boolean)[0] || "";
    if (evidence.length <= 180) {
      return evidence;
    }
    return `${evidence.slice(0, 177).trimEnd()}...`;
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
        const evidence = traceEvidencePreview(item);
        const surface = humanSurfaceSummary(item.surfaces);
        const mapped = item.mapped === true;
        const mapping = mapped
          ? localeText(`已投影到：${surface}`, `Mapped into: ${surface}`)
          : localeText("缺少可运行映射", "Missing runnable mapping");
        return `
          <div class="alignment-judgment-row" data-mapped="${mapped}">
            <strong>${escapeHtml(traceItemLabel(item))}</strong>
            <span>${escapeHtml(mapping)}</span>
            ${evidence ? `<span class="alignment-judgment-evidence">${escapeHtml(evidence)}</span>` : ""}
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
    const sessionStatus = String(payload.session?.status || currentSession?.status || "");
    const linkedRunId = String(payload.session?.linked_run_id || currentSession?.linked_run_id || "").trim();
    const allowReadyRun = options.allowImport !== false && sessionStatus === "ready";
    const allowLinkedRun = options.allowImport !== false && sessionStatus === "running_loop" && Boolean(linkedRunId);
    const allowAction = allowReadyRun || allowLinkedRun;
    const agentEntryLaunch = agentEntryProjectionFor(payload);
    const agentLaunch = agentEntryLaunchFor(payload, allowAction);
    readyPreview.dataset.previewState = allowLinkedRun ? "linked-run" : (allowReadyRun ? "ready" : "repair");
    readyPreview.dataset.launchMode = agentEntryLaunch ? "agent-entry" : "web-run";
    if (importRunButton) {
      importRunButton.hidden = !allowAction;
      importRunButton.disabled = !allowAction;
      importRunButton.dataset.launchAction = agentLaunch?.linked_run_id ? "open-linked-run" : (agentLaunch ? "copy-agent-loop" : "web-run");
      if (agentLaunch?.linked_run_id) {
        importRunButton.dataset.runId = agentLaunch.linked_run_id;
        delete importRunButton.dataset.copyValue;
        setBilingualText(importRunButton, "打开运行", "Open run");
      } else if (agentLaunch) {
        delete importRunButton.dataset.runId;
        importRunButton.dataset.copyValue = agentLaunch.slash_command || "/loopora-run";
        setBilingualText(importRunButton, "复制 /loopora-run", "Copy /loopora-run");
      } else if (allowAction) {
        delete importRunButton.dataset.runId;
        delete importRunButton.dataset.copyValue;
        setBilingualText(importRunButton, "复核后创建并运行", "Review, create, run");
      } else {
        delete importRunButton.dataset.runId;
        delete importRunButton.dataset.copyValue;
        setBilingualText(importRunButton, agentEntryLaunch ? "修复后回到 Agent" : "修复后运行", agentEntryLaunch ? "Repair before Agent run" : "Repair before running");
      }
      if (allowAction) {
        importRunButton.closest(".card-actions")?.removeAttribute("hidden");
      } else {
        importRunButton.closest(".card-actions")?.setAttribute("hidden", "");
      }
    }
    if (revisePreviewButton) {
      const canRevisePreview = Boolean(currentSession?.id) && sessionStatus === "ready";
      revisePreviewButton.hidden = !canRevisePreview;
      revisePreviewButton.disabled = !canRevisePreview;
    }
    const metadata = payload.metadata || payload.bundle?.metadata || {};
    artifactName.textContent = metadata.name || localeText("Loop 方案", "Loop plan");
    previewTitle.textContent = agentLaunch?.linked_run_id
      ? localeText("Loop 已在 Agent 中运行", "Loop is running in the Agent")
      : agentLaunch
      ? localeText("Loop 已准备好，回到 Agent 运行", "Plan is ready for the Agent")
      : allowReadyRun
      ? localeText("Loop 已准备好，先复核再运行", "Plan is ready; review before running")
      : agentEntryLaunch
      ? localeText("候选方案需要修复后再回到 Agent", "Candidate plan needs repair before returning to the Agent")
      : localeText("方案文件需要修复后才能运行", "Plan file needs repair before running");
    const repairError = String(options.repairNote || payload.validation?.error || "").trim();
    readyNote.textContent = allowAction
      ? agentLaunch?.linked_run_id
        ? localeText(
          "这份预览已通过 /loopora-run 启动；Web 负责观察证据和运行状态，继续执行仍回到同一个 Agent。",
          "This preview has been launched through /loopora-run; Web observes evidence and run state, while execution still returns to the same Agent."
        )
        : agentLaunch
        ? localeText(
          "这份预览来自 /loopora-plan；用同一个 Agent 执行 /loopora-run，才能保留宿主 Agent-native 交接。",
          "This preview came from /loopora-plan; run /loopora-run in the same Agent to preserve host-native handoff."
        )
        : localeText(
          "READY 只表示方案通过硬校验；确认判断地图、证据路径和运行目录后再启动。",
          "READY only means the plan passed hard validation; confirm the judgment map, evidence path, and run directory before launch."
        )
      : agentEntryLaunch
      ? localeText(
        "候选方案尚未通过校验。先修源候选文件，再重新运行 /loopora-plan；只有预览 READY 后，才回到同一个 Agent 执行 /loopora-run。",
        "The candidate plan has not passed validation. Repair the source candidate file, then rerun /loopora-plan; return to the same Agent for /loopora-run only after the preview is READY."
      )
      : localeText(
        "候选方案尚未通过校验。按下面的修复焦点改源文件，重新同步后再运行。",
        "The candidate plan has not passed validation. Repair the source file using the focus list below, then reload before running."
      );
    renderAgentLaunchGuide(agentLaunch);
    renderRepairGuide({
      visible: !allowAction,
      error: repairError,
      sourcePath: payload.source_path || currentSession?.bundle_path || "",
      sessionId: currentSession?.id || payload.session?.id || "",
      agentEntry: agentEntryLaunch,
    });
    const summary = payload.control_summary || {};
    const diagnostics = payload.diagnostics || summary.diagnostics || [];
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
    renderReadyReviewGate({required: allowReadyRun && !agentLaunch, summary, diagnostics});
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

  function agentEntryProjectionFor(payload) {
    const session = payload?.session || currentSession || {};
    const launch = session.agent_entry_launch || {};
    if (launch.source !== "agent_entry") {
      return null;
    }
    return launch;
  }

  function agentEntryLaunchFor(payload, allowAction) {
    if (!allowAction) {
      return null;
    }
    const session = payload?.session || currentSession || {};
    const launch = agentEntryProjectionFor(payload);
    if (!launch) {
      return null;
    }
    const linkedRunId = String(session.linked_run_id || "").trim();
    return linkedRunId ? {...launch, linked_run_id: linkedRunId} : launch;
  }

  function renderAgentLaunchGuide(launch) {
    if (!agentLaunchGuide) {
      return;
    }
    if (!launch) {
      agentLaunchGuide.hidden = true;
      agentLaunchGuide.innerHTML = "";
      return;
    }
    const adapter = adapterDisplayName(String(launch.adapter || "agent").trim());
    const slashCommand = String(launch.slash_command || "/loopora-run").trim();
    const loopCommand = String(launch.loop_command || "").trim();
    const workdir = String(launch.workdir || "").trim();
    const linkedRunId = String(launch.linked_run_id || "").trim();
    const slashCopyButton = renderAgentLaunchCopyButton(
      slashCommand,
      "alignment-agent-launch-copy-slash",
      "复制同一 Agent slash 命令",
      "Copy same-Agent slash command"
    );
    const cliCopyButton = renderAgentLaunchCopyButton(
      loopCommand,
      "alignment-agent-launch-copy-cli",
      "复制 CLI fallback 命令",
      "Copy CLI fallback command"
    );
    agentLaunchGuide.hidden = false;
    agentLaunchGuide.innerHTML = `
      <div class="alignment-agent-launch-copy">
        <span class="alignment-agent-launch-kicker">${escapeHtml(localeText("Agent-first 运行", "Agent-first run"))}</span>
        <strong>${escapeHtml(linkedRunId
          ? localeText(`当前运行已绑定 ${adapter}`, `Current run is bound to ${adapter}`)
          : localeText(`回到 ${adapter} 执行 /loopora-run`, `Return to ${adapter} and run /loopora-run`))}</strong>
        <p>${escapeHtml(localeText(
          linkedRunId
            ? "Web 只负责查看运行证据和当前交接；下一步执行仍回到宿主 Agent，避免改走后台 worker。"
            : "Web 已完成审查面；运行必须回到宿主 Agent，让 Builder、Inspector 和 GateKeeper 通过原生交接执行。",
          linkedRunId
            ? "Web only shows run evidence and the current handoff; the next execution step still returns to the host Agent instead of a background worker."
            : "Web has finished the review surface; execution must return to the host Agent so Builder, Inspector, and GateKeeper run through native handoff."
        ))}</p>
      </div>
      <div class="alignment-agent-launch-commands">
        <div class="alignment-agent-launch-command-block">
          <span>${escapeHtml(localeText("Slash command", "Slash command"))}</span>
          <div class="alignment-agent-launch-command-row">
            <code data-testid="alignment-agent-launch-slash" data-agent-entry-slash-command-value>${escapeHtml(slashCommand)}</code>
            ${slashCopyButton}
          </div>
        </div>
        ${loopCommand ? `
          <div class="alignment-agent-launch-command-block">
            <span>${escapeHtml(localeText("CLI fallback", "CLI fallback"))}</span>
            <div class="alignment-agent-launch-command-row">
              <code data-testid="alignment-agent-launch-cli" data-agent-entry-command-value>${escapeHtml(loopCommand)}</code>
              ${cliCopyButton}
            </div>
          </div>
        ` : ""}
        ${workdir ? `
          <div class="alignment-agent-launch-command-block">
            <span>${escapeHtml(localeText("Workdir", "Workdir"))}</span>
            <code title="${escapeHtml(workdir)}">${escapeHtml(workdir)}</code>
          </div>
        ` : ""}
        ${linkedRunId ? `<a class="secondary-button alignment-agent-launch-run-link" href="/runs/${encodeURIComponent(linkedRunId)}" data-testid="alignment-agent-launch-run-link">${escapeHtml(localeText("打开当前运行", "Open current run"))}</a>` : ""}
        <p class="alignment-agent-launch-copy-status" data-alignment-agent-copy-status aria-live="polite"></p>
      </div>
    `;
    bindAgentLaunchGuideCopyButtons();
  }

  function renderAgentLaunchCopyButton(value, testId, zhLabel, enLabel) {
    const command = String(value || "").trim();
    if (!command) {
      return "";
    }
    return `
      <button
        class="ghost-button alignment-agent-launch-copy-button"
        type="button"
        data-alignment-agent-command-copy
        data-agent-entry-command-copy
        data-copy-value="${escapeHtml(command)}"
        data-testid="${escapeHtml(testId)}"
        aria-label="${escapeHtml(localeText(zhLabel, enLabel))}"
      >
        <span aria-hidden="true">⧉</span>
        <span class="sr-only">
          <span data-lang="zh">${escapeHtml(zhLabel)}</span>
          <span data-lang="en">${escapeHtml(enLabel)}</span>
        </span>
      </button>
    `;
  }

  function setAgentLaunchCopyStatus(button, message) {
    const status = agentLaunchGuide?.querySelector("[data-alignment-agent-copy-status]");
    button?.classList.add("is-copied");
    if (status) {
      status.textContent = message || "";
    }
    if (agentLaunchCopyTimer) {
      window.clearTimeout(agentLaunchCopyTimer);
    }
    agentLaunchCopyTimer = window.setTimeout(() => {
      button?.classList.remove("is-copied");
      if (status && status.textContent === message) {
        status.textContent = "";
      }
    }, 1800);
  }

  function bindAgentLaunchGuideCopyButtons() {
    agentLaunchGuide?.querySelectorAll("[data-alignment-agent-command-copy]").forEach((button) => {
      button.addEventListener("click", async () => {
        const command = String(button.dataset.copyValue || "").trim();
        if (!command) {
          setAgentLaunchCopyStatus(button, localeText("没有可复制的 Agent 命令。", "No Agent command is available to copy."));
          return;
        }
        try {
          await writeClipboardText(command);
          setAgentLaunchCopyStatus(button, localeText("命令已复制。回到同一 Agent 会话粘贴运行。", "Command copied. Paste it in the same Agent session."));
        } catch (_) {
          setAgentLaunchCopyStatus(button, localeText("无法复制命令，请手动复制页面中的命令。", "Unable to copy the command. Copy it from the page manually."));
        }
      });
    });
  }

  function adapterDisplayName(adapter) {
    const normalized = String(adapter || "").toLowerCase();
    if (normalized === "codex") {
      return "Codex";
    }
    if (normalized === "claude") {
      return "Claude Code";
    }
    if (normalized === "opencode") {
      return "OpenCode";
    }
    return adapter || "Agent";
  }

  function renderRepairGuide({visible, error, sourcePath, sessionId, agentEntry}) {
    if (!repairGuide) {
      return;
    }
    if (!visible) {
      repairGuide.hidden = true;
      repairGuide.innerHTML = "";
      return;
    }
    const isAgentEntryRepair = (agentEntry?.source || currentSession?.agent_entry_launch?.source) === "agent_entry";
    const hints = repairHints(error, {agentEntry: isAgentEntryRepair});
    const source = String(sourcePath || "").trim();
    const rawError = String(error || "").trim();
    const repairMessage = isAgentEntryRepair
      ? localeText(
        "这不是运行失败，也不是 Web 创建运行入口。候选方案还没有把宿主 Agent 的任务判断编译成可运行 Loop；先修源候选文件，重新运行 /loopora-plan，READY 后回到同一个 Agent 执行 /loopora-run。",
        "This is not a run failure and not a Web create-run entry. The candidate plan has not compiled the host Agent task judgment into a runnable Loop yet; repair the source candidate file, rerun /loopora-plan, then return to the same Agent for /loopora-run after READY."
      )
      : localeText(
        "这不是运行失败，而是候选方案还没有把任务判断编译成可运行 Loop。先修方案文件，再重新同步；通过校验前不会允许创建运行。",
        "This is not a run failure. The candidate plan has not yet compiled task judgment into a runnable Loop. Repair the plan file, then reload; creation stays disabled until validation passes."
      );
    repairGuide.hidden = false;
    repairGuide.innerHTML = `
      <div class="alignment-repair-guide-copy">
        <span class="alignment-repair-guide-kicker">${escapeHtml(localeText("下一步修复", "Repair next"))}</span>
        <strong>${escapeHtml(isAgentEntryRepair
          ? localeText("修复候选方案，再回到同一个 Agent。", "Repair the candidate plan, then return to the same Agent.")
          : localeText("把校验错误转成方案修复，而不是继续运行。", "Turn validation errors into plan repair before running."))}</strong>
        <p>${escapeHtml(repairMessage)}</p>
      </div>
      <ol class="alignment-repair-steps">
        ${hints.map((hint) => `<li>${escapeHtml(hint)}</li>`).join("")}
      </ol>
      <div class="alignment-repair-meta">
        ${source ? `<code title="${escapeHtml(source)}">${escapeHtml(source)}</code>` : ""}
        ${sessionId ? `<span>${escapeHtml(localeText(`对话 ${sessionId}`, `Session ${sessionId}`))}</span>` : ""}
      </div>
      ${rawError ? `
        <details class="alignment-repair-raw">
          <summary>${escapeHtml(localeText("查看原始校验错误", "Show raw validation error"))}</summary>
          <p>${escapeHtml(rawError)}</p>
        </details>
      ` : ""}
    `;
  }

  function repairHints(error, options = {}) {
    const text = String(error || "");
    const hints = [];
    if (text.includes("spec Task must describe the concrete user-facing task")) {
      hints.push(localeText(
        "在 # Task 里写清真实用户结果和业务对象，例如谁在什么页面完成什么退款动作；不要只写治理或内部流程。",
        "Make # Task state the real user outcome and domain object, not only governance or internal process."
      ));
    }
    if (text.includes("must follow Chinese user language")) {
      hints.push(localeText(
        "中文任务的可见名称、任务契约、角色名称和角色姿态都要使用中文；Loopora 专有词可以保留。",
        "Keep visible names, task contract, role names, and role posture in the user's language; Loopora terms may remain."
      ));
    }
    if (text.includes("host Agent task summary") || text.includes("project the host Agent task summary")) {
      hints.push(localeText(
        "把 /loopora-plan 摘要里的高信号对象写进 spec、角色责任、workflow intent 和证据规则。",
        "Project high-signal objects from the /loopora-plan summary into spec, role responsibilities, workflow intent, and evidence rules."
      ));
    }
    if (text.includes("evidence preferences") || text.includes("explicit host Agent evidence")) {
      hints.push(localeText(
        "把必需证据模式落到可运行 surface：测试、命令、浏览器 journey、日志、审计或权限/支付证明，而不是只放在摘要里。",
        "Compile required evidence modes into runnable surfaces: tests, commands, browser journeys, logs, audit, or permission/payment proof."
      ));
    }
    if (text.includes("Loopora fit") || text.includes("one-off") || text.includes("no-new-evidence")) {
      hints.push(localeText(
        "说明后续轮次会新增什么证据、handoff、GateKeeper 裁决或残余风险跟踪；否则这件事可能不适合开 Loop。",
        "Explain what later rounds add: new evidence, handoffs, GateKeeper verdict, or residual-risk tracking; otherwise this may not need a Loop."
      ));
    }
    if (!hints.length) {
      hints.push(localeText(
        "先修复最上面的结构或语义错误，再重新同步；如果错误仍然抽象，打开源文件检查 task、证据、角色责任和裁决规则是否一致。",
        "Fix the top structural or semantic error first, then reload; if the error is still abstract, inspect whether task, evidence, role duties, and verdict rules agree."
      ));
    }
    if (options.agentEntry) {
      hints.push(localeText(
        "修完候选文件后重新执行 /loopora-plan；只有看到“Loop 已准备好，回到 Agent 运行”后，才在同一个 Agent 会话执行 /loopora-run。",
        "After editing the candidate file, rerun /loopora-plan; run /loopora-run in the same Agent session only after the preview says the plan is ready for the Agent."
      ));
    } else {
      hints.push(localeText(
        "修完后点击“重新同步”；只有看到“Loop 已准备好，先复核再运行”并确认运行前复核后，才使用页面里的创建 / 运行入口。",
        "After editing, click Reload; use the page's create/run action only after the preview says the Loop is ready for review and the pre-run review is confirmed."
      ));
    }
    return hints.slice(0, 5);
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
        await writeClipboardText(path);
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
        setStatus(statusLabel(currentSession.status, currentSession.alignment_stage), currentSession.status === "ready" ? "ready" : (currentSession.status === "failed" ? "failed" : ""), currentSession.status);
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
    const additionalMessage = messageInput.value.trim();
    const judgmentBrief = collectJudgmentBrief();
    const hasJudgmentBrief = judgmentBriefHasAnyValue(judgmentBrief);
    if (!additionalMessage && !hasJudgmentBrief) {
      showError(localeText("先写任务目标、伪完成风险和必需证据。", "Add the task goal, fake-done risk, and required evidence first."));
      (taskGoalInput || messageInput).focus();
      return;
    }
    const composedMessage = hasJudgmentBrief ? composeJudgmentMessage(additionalMessage) : additionalMessage;
    if (currentSession?.id && !ACTIVE_STATUSES.has(String(currentSession.status || ""))) {
      setBusy(true);
      try {
        await appendMessage(composedMessage);
        clearJudgmentBriefInputs();
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
          await appendMessage(composedMessage);
          clearJudgmentBriefInputs();
          messageInput.value = "";
        }
        closeTools();
      } catch (error) {
        showError(error.message || localeText("继续已有对话失败。", "Failed to continue the existing chat."));
        setBusy(false);
      }
      return;
    }
    const missingJudgmentField = firstMissingJudgmentField(judgmentBrief);
    if (missingJudgmentField) {
      showError(localeText("开始前请补齐任务目标、伪完成风险和必需证据；这三项会进入首条记录。", "Fill task goal, fake-done risk, and required evidence before starting; all three enter the first transcript entry."));
      missingJudgmentField.focus();
      return;
    }
    setBusy(true);
    try {
      await createSession(payload);
      clearJudgmentBriefInputs();
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

  [messageInput, taskGoalInput, fakeDoneRiskInput, requiredEvidenceInput].forEach((input) => {
    input?.addEventListener("input", () => showError(""));
  });
  panel.querySelectorAll("[data-goal-zh][data-goal-en]").forEach((button) => {
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

  reviewGateCheckbox?.addEventListener("change", () => {
    updateImportRunReviewGate();
  });

  importRunButton.addEventListener("click", async () => {
    if (!currentSession?.id) {
      return;
    }
    if (importRunButton.dataset.launchAction === "open-linked-run") {
      const runId = String(importRunButton.dataset.runId || "").trim();
      if (runId) {
        window.location.assign(`/runs/${encodeURIComponent(runId)}`);
      }
      return;
    }
    if (importRunButton.dataset.launchAction === "copy-agent-loop") {
      const value = importRunButton.dataset.copyValue || "/loopora-run";
      try {
        await writeClipboardText(value);
        importRunButton.classList.add("is-copied");
        setBilingualText(importRunButton, "已复制", "Copied");
        window.setTimeout(() => {
          importRunButton.classList.remove("is-copied");
          setBilingualText(importRunButton, "复制 /loopora-run", "Copy /loopora-run");
        }, 1400);
      } catch (error) {
        showError(error.message || localeText("无法复制 /loopora-run。", "Unable to copy /loopora-run."));
      }
      return;
    }
    if (readyReviewGateRequired() && reviewGateCheckbox?.checked !== true) {
      showError(localeText("先确认运行前复核，再创建并运行。", "Confirm the pre-run review before creating and running."));
      reviewGate?.scrollIntoView({block: "nearest", behavior: "smooth"});
      reviewGateCheckbox?.focus();
      updateImportRunReviewGate();
      return;
    }
    importRunButton.dataset.busy = "true";
    importRunButton.disabled = true;
    try {
      const response = await fetchJson(`/api/alignments/sessions/${encodeURIComponent(currentSession.id)}/import`, {
        method: "POST",
        body: JSON.stringify({start_immediately: true}),
      });
      window.location.assign(response.redirect_url || "/");
    } catch (error) {
      showError(error.message || localeText("创建失败，方案源文件已保留。", "Creation failed; the plan source file is preserved."));
      delete importRunButton.dataset.busy;
      updateImportRunReviewGate();
    }
  });
  revisePreviewButton?.addEventListener("click", () => {
    const launch = currentSession?.agent_entry_launch || {};
    const agentFirst = launch?.source === "agent_entry";
    const draft = agentFirst
      ? localeText(
        "我想调整这份 Loop 预览，但保持 Agent-first 交接：审查后仍回到同一个 Agent 运行 /loopora-run。请改进：",
        "I want to revise this Loop preview while keeping the Agent-first handoff: after review, return to the same Agent and run /loopora-run. Please adjust:"
      )
      : localeText(
        "我想调整这份 Loop 预览：",
        "I want to revise this Loop preview:"
      );
    if (!messageInput.value.trim()) {
      messageInput.value = draft;
      messageInput.dispatchEvent(new Event("input", {bubbles: true}));
    }
    messageInput.focus();
    messageInput.setSelectionRange(messageInput.value.length, messageInput.value.length);
    scrollRegion?.scrollTo({top: scrollRegion.scrollHeight, behavior: "smooth"});
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
