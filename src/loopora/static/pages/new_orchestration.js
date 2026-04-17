document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("new-orchestration-form");
  if (!form || !window.LooporaUI) {
    return;
  }

  const ARCHETYPE_LABELS = {
    builder: {zh: "建造者", en: "Builder"},
    inspector: {zh: "巡检者", en: "Inspector"},
    gatekeeper: {zh: "守门人", en: "GateKeeper"},
    guide: {zh: "向导", en: "Guide"},
    custom: {zh: "自定义角色", en: "Custom Role"},
  };
  const EXECUTOR_LABELS = {
    codex: "Codex",
    claude: "Claude Code",
    opencode: "OpenCode",
    custom: "Custom Command",
  };

  const formError = document.getElementById("form-error");
  const workflowValidation = document.getElementById("workflow-validation");
  const workflowLoopPreview = document.getElementById("workflow-loop-preview");
  const workflowStarterSelect = document.getElementById("workflow-starter-select");
  const loadWorkflowStarterButton = document.getElementById("load-workflow-starter-button");
  const roleDefinitionSelect = document.getElementById("role-definition-select");
  const addStepButton = document.getElementById("add-step-button");
  const workflowStepsList = document.getElementById("workflow-steps-list");
  const workflowJsonInput = document.getElementById("workflow-json-input");
  const promptFilesJsonInput = document.getElementById("prompt-files-json-input");
  const saveOrchestrationButton = document.getElementById("save-orchestration-button");
  const isReadOnly = form.dataset.readonly === "true";

  const settingsModal = document.getElementById("workflow-step-settings-modal");
  const settingsModalTitle = document.getElementById("workflow-step-settings-title");
  const settingsModalDetail = document.getElementById("workflow-step-settings-detail");
  const settingsStepIdInput = document.getElementById("workflow-settings-step-id");
  const settingsStepRoleInput = document.getElementById("workflow-settings-step-role");
  const settingsStepModelInput = document.getElementById("workflow-settings-step-model");
  const settingsStepOnPassInput = document.getElementById("workflow-settings-step-on-pass");
  const settingsRoleDefinition = document.getElementById("workflow-settings-role-definition");
  const settingsRoleRuntime = document.getElementById("workflow-settings-role-runtime");
  const settingsRoleNameValue = document.getElementById("workflow-settings-role-name");
  const settingsRoleArchetypeValue = document.getElementById("workflow-settings-role-archetype");
  const settingsRolePromptValue = document.getElementById("workflow-settings-role-prompt");
  const settingsRoleExecutorKindValue = document.getElementById("workflow-settings-role-executor-kind");
  const settingsRoleExecutorModeValue = document.getElementById("workflow-settings-role-executor-mode");
  const settingsRoleModelValue = document.getElementById("workflow-settings-role-model");
  const settingsRoleReasoningValue = document.getElementById("workflow-settings-role-reasoning");
  const settingsRoleCommandCliValue = document.getElementById("workflow-settings-role-command-cli");
  const settingsRoleCommandArgsValue = document.getElementById("workflow-settings-role-command-args");

  const workflowPresetBundles = JSON.parse(document.getElementById("workflow-preset-bundles-json")?.textContent || "{}");
  const roleDefinitions = JSON.parse(document.getElementById("role-definitions-json")?.textContent || "[]");

  let workflowState = null;
  let promptFilesState = null;
  let activeRoleId = "";
  let activeStepIndex = -1;
  let openSettingsStepIndex = -1;
  let submitAttempted = false;
  let lastModalTrigger = null;

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

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function showStatus(element, message, kind = "") {
    if (!message) {
      element.hidden = true;
      element.textContent = "";
      element.className = "field-status";
      return;
    }
    element.hidden = false;
    element.textContent = message;
    element.className = `field-status${kind ? ` is-${kind}` : ""}`;
  }

  function roleLabel(archetype) {
    const labels = ARCHETYPE_LABELS[archetype] || {zh: archetype, en: archetype};
    return localeText(labels.zh, labels.en);
  }

  function roleDefinitionById(roleDefinitionId) {
    return roleDefinitions.find((entry) => entry.id === roleDefinitionId) || null;
  }

  function roleById(roleId) {
    return workflowState?.roles?.find((entry) => entry.id === roleId) || null;
  }

  function stepByIndex(index) {
    return workflowState?.steps?.[index] || null;
  }

  function firstStepIndexForRole(roleId) {
    return workflowState?.steps?.findIndex((step) => step.role_id === roleId) ?? -1;
  }

  function optionHtml(value, label, selected) {
    return `<option value="${escapeHtml(value)}" ${selected ? "selected" : ""}>${escapeHtml(label)}</option>`;
  }

  function textOrDash(value) {
    const text = String(value ?? "").trim();
    return text || "-";
  }

  function localizeSelectOptions(select) {
    if (!select) {
      return;
    }
    const useChinese = window.LooporaUI.currentLocale() === "zh";
    Array.from(select.options).forEach((option) => {
      const nextLabel = useChinese ? option.dataset.labelZh : option.dataset.labelEn;
      if (nextLabel) {
        option.textContent = nextLabel;
      }
    });
  }

  function emptyStarterBundle() {
    return {
      id: "",
      copy: {
        label_zh: "空白开始",
        label_en: "Start blank",
        description_zh: "从空白步骤工作台开始",
        description_en: "Start from a blank step workbench",
      },
      workflow: {
        version: 1,
        preset: "",
        roles: [],
        steps: [],
      },
      prompt_files: {},
    };
  }

  function starterBundleById(name) {
    const presetName = String(name || "").trim();
    if (!presetName) {
      return emptyStarterBundle();
    }
    const bundle = workflowPresetBundles[presetName];
    if (!bundle) {
      return null;
    }
    return {
      id: presetName,
      copy: bundle.copy || {},
      workflow: bundle.workflow || {version: 1, preset: presetName, roles: [], steps: []},
      prompt_files: bundle.prompt_files || {},
    };
  }

  function workflowHasContent() {
    return Boolean(workflowState?.roles?.length || workflowState?.steps?.length);
  }

  function makeRoleId(baseName) {
    const existing = new Set((workflowState?.roles || []).map((role) => role.id));
    const seed = String(baseName || "role")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "role";
    if (!existing.has(seed)) {
      return seed;
    }
    for (let index = 2; index < 500; index += 1) {
      const candidate = `${seed}_${index}`;
      if (!existing.has(candidate)) {
        return candidate;
      }
    }
    return `${seed}_${Date.now()}`;
  }

  function makeStepId(roleId) {
    const existing = new Set((workflowState?.steps || []).map((step) => step.id));
    const base = `${roleId || "step"}_step`;
    if (!existing.has(base)) {
      return base;
    }
    for (let index = 2; index < 500; index += 1) {
      const candidate = `${base}_${index}`;
      if (!existing.has(candidate)) {
        return candidate;
      }
    }
    return `${base}_${Date.now()}`;
  }

  function normalizeRole(role, index) {
    const archetype = String(role.archetype || "builder").trim() || "builder";
    return {
      id: String(role.id || `role_${index + 1}`),
      name: String(role.name || roleLabel(archetype)),
      archetype,
      prompt_ref: String(role.prompt_ref || "").trim(),
      role_definition_id: String(role.role_definition_id || ""),
      executor_kind: String(role.executor_kind || ""),
      executor_mode: String(role.executor_mode || ""),
      command_cli: String(role.command_cli || ""),
      command_args_text: String(role.command_args_text || ""),
      model: String(role.model || ""),
      reasoning_effort: String(role.reasoning_effort || ""),
    };
  }

  function ensureActiveSelection() {
    const steps = workflowState?.steps || [];
    if (!steps.length) {
      activeStepIndex = -1;
      activeRoleId = String(workflowState?.roles?.[0]?.id || "");
      return;
    }
    if (activeStepIndex >= 0 && activeStepIndex < steps.length) {
      activeRoleId = String(steps[activeStepIndex].role_id || "");
      return;
    }
    const matchingIndex = firstStepIndexForRole(activeRoleId);
    if (matchingIndex >= 0) {
      activeStepIndex = matchingIndex;
      activeRoleId = steps[matchingIndex].role_id;
      return;
    }
    activeStepIndex = 0;
    activeRoleId = String(steps[0].role_id || "");
  }

  function normalizeWorkflowState(workflow, promptFiles) {
    const workflowPayload = clone(workflow || {});
    workflowPayload.version = 1;
    workflowPayload.preset = String(workflowPayload.preset || "");
    workflowPayload.roles = Array.isArray(workflowPayload.roles) ? workflowPayload.roles.map(normalizeRole) : [];
    workflowPayload.steps = Array.isArray(workflowPayload.steps) ? workflowPayload.steps.map((step, index) => ({
      id: String(step.id || `step_${index + 1}`),
      role_id: String(step.role_id || workflowPayload.roles[0]?.id || ""),
      on_pass: String(step.on_pass || "continue"),
      model: String(step.model || ""),
    })) : [];
    workflowState = workflowPayload;
    promptFilesState = {...(promptFiles || {})};
    if (openSettingsStepIndex >= workflowPayload.steps.length) {
      openSettingsStepIndex = -1;
    }
    ensureActiveSelection();
  }

  function syncWorkflowJsonFields() {
    workflowJsonInput.value = JSON.stringify(workflowState, null, 2);
    const nextPromptFiles = {};
    workflowState.roles.forEach((role) => {
      if (role.prompt_ref && promptFilesState[role.prompt_ref]) {
        nextPromptFiles[role.prompt_ref] = promptFilesState[role.prompt_ref];
      }
    });
    promptFilesState = nextPromptFiles;
    promptFilesJsonInput.value = JSON.stringify(promptFilesState, null, 2);
  }

  function setActiveStep(stepIndex, options = {}) {
    const step = stepByIndex(stepIndex);
    if (!step) {
      return;
    }
    activeStepIndex = stepIndex;
    activeRoleId = String(step.role_id || "");
    syncSelectionHighlights();
    if (options.scroll || options.focus) {
      const card = workflowStepsList?.querySelector(`.workflow-step-row[data-step-index="${stepIndex}"]`);
      if (options.scroll) {
        card?.scrollIntoView({block: "nearest", behavior: "smooth"});
      }
      if (options.focus) {
        card?.focus();
      }
    }
  }

  function setActiveRole(roleId, options = {}) {
    const nextRoleId = String(roleId || "");
    if (!nextRoleId || !workflowState.roles.some((role) => role.id === nextRoleId)) {
      return;
    }
    const stepIndex = Number.isInteger(options.stepIndex) ? options.stepIndex : firstStepIndexForRole(nextRoleId);
    if (stepIndex >= 0) {
      setActiveStep(stepIndex, options);
      return;
    }
    activeRoleId = nextRoleId;
    activeStepIndex = -1;
    syncSelectionHighlights();
  }

  function pruneUnusedRoles() {
    const usedRoleIds = new Set((workflowState.steps || []).map((step) => step.role_id).filter(Boolean));
    if (!usedRoleIds.size) {
      workflowState.roles = [];
      activeRoleId = "";
      activeStepIndex = -1;
      openSettingsStepIndex = -1;
      return;
    }
    workflowState.roles = workflowState.roles.filter((role) => usedRoleIds.has(role.id));
    workflowState.steps = workflowState.steps.filter((step) => usedRoleIds.has(step.role_id));
    ensureActiveSelection();
    if (openSettingsStepIndex >= workflowState.steps.length) {
      openSettingsStepIndex = -1;
    }
  }

  function workflowValidationMessages() {
    const messages = [];
    const roleIds = new Set();
    const stepIds = new Set();
    if (!workflowState.roles.length) {
      messages.push(localeText("至少需要 1 个角色快照。", "At least one role snapshot is required."));
    }
    workflowState.roles.forEach((role) => {
      if (!role.id.trim()) {
        messages.push(localeText("每个角色都需要一个 id。", "Every role needs an id."));
      }
      if (roleIds.has(role.id)) {
        messages.push(localeText(`角色 id 重复：${role.id}`, `Duplicate role id: ${role.id}`));
      }
      roleIds.add(role.id);
    });
    if (!workflowState.steps.length) {
      messages.push(localeText("至少需要 1 个步骤。", "At least one step is required."));
    }
    workflowState.steps.forEach((step) => {
      if (!step.id.trim()) {
        messages.push(localeText("每个步骤都需要一个 id。", "Every step needs an id."));
      }
      if (stepIds.has(step.id)) {
        messages.push(localeText(`步骤 id 重复：${step.id}`, `Duplicate step id: ${step.id}`));
      }
      stepIds.add(step.id);
      if (!step.role_id || !roleIds.has(step.role_id)) {
        messages.push(localeText(`步骤 ${step.id || "(未命名)"} 引用了不存在的角色。`, `Step ${step.id || "(unnamed)"} references an unknown role.`));
      }
    });
    return messages;
  }

  function workflowValidationWarnings() {
    const roleByIdMap = Object.fromEntries(workflowState.roles.map((role) => [role.id, role]));
    const hasFinishGate = workflowState.steps.some((step) => {
      const role = roleByIdMap[step.role_id];
      return role?.archetype === "gatekeeper" && step.on_pass === "finish_run";
    });
    if (hasFinishGate) {
      return [];
    }
    return [
      localeText(
        "这套编排还没有“通过即结束”的 GateKeeper 步骤。用于按轮次推进没问题；如果要靠放行裁决收敛，请补一个 GateKeeper finish step。",
        "This orchestration does not yet have a finish-on-pass GateKeeper step. That is fine for round-based execution; add one before using gate-based completion.",
      ),
    ];
  }

  function renderWorkflowValidation({forceErrors = false} = {}) {
    const messages = workflowValidationMessages();
    if (!messages.length) {
      const warnings = workflowValidationWarnings();
      showStatus(
        workflowValidation,
        warnings[0] || localeText("步骤结构看起来没问题。", "The step structure looks valid."),
        warnings.length ? "warning" : "success",
      );
      return true;
    }
    if (!forceErrors && !submitAttempted && !workflowHasContent()) {
      showStatus(
        workflowValidation,
        localeText("从空白开始没问题。先载入起手模板，或者从角色定义加入一个角色快照。", "Blank is fine here. Load a starter template or add a role snapshot from Role Definitions to begin."),
      );
      return false;
    }
    showStatus(workflowValidation, messages.join(" "), "error");
    return false;
  }

  function roleRuntimeSummary(role) {
    const executorKind = String(role.executor_kind || "").trim();
    const executorMode = String(role.executor_mode || "").trim();
    const executorLabel = executorKind
      ? (EXECUTOR_LABELS[executorKind] || executorKind)
      : localeText("沿用旧 loop 级回退", "Legacy loop-level fallback");
    const parts = [executorLabel];
    if (executorMode) {
      parts.push(executorMode);
    }
    if (role.model) {
      parts.push(role.model);
    }
    if (role.reasoning_effort) {
      parts.push(role.reasoning_effort);
    }
    return parts.join(" · ");
  }

  function roleDefinitionSummary(role) {
    const definition = roleDefinitionById(role.role_definition_id);
    if (definition) {
      return `${definition.name} · ${roleLabel(definition.archetype)}`;
    }
    return localeText("未绑定角色定义", "Unbound role definition");
  }

  function promptFileSummary(role) {
    return role.prompt_ref || localeText("沿用已有 prompt 引用", "Using stored prompt reference");
  }

  function stepPassSummary(step, role) {
    if (!role) {
      return localeText("这个步骤还没有绑定有效角色。", "This step is not bound to a valid role yet.");
    }
    if (role.archetype === "gatekeeper") {
      return step.on_pass === "finish_run"
        ? localeText("GateKeeper 通过后会直接结束流程。", "This GateKeeper ends the run immediately when it passes.")
        : localeText("GateKeeper 通过后会继续后续步骤。", "This GateKeeper continues to later steps after it passes.");
    }
    return localeText(
      `${roleLabel(role.archetype)} 会在这一位执行，并把结果交给下一步。`,
      `${roleLabel(role.archetype)} runs here and hands results to the next step.`,
    );
  }

  function stepPassLabel(step, role) {
    if (role?.archetype === "gatekeeper") {
      return step.on_pass === "finish_run"
        ? localeText("通过后结束", "Finish on pass")
        : localeText("通过后继续", "Continue on pass");
    }
    return localeText("交给下一步", "Hand off to next");
  }

  function stepModelLabel(step) {
    return step.model
      ? `${localeText("模型覆盖", "Model override")} · ${step.model}`
      : localeText("沿用角色默认模型", "Uses role default model");
  }

  function renderWorkflowLoopPreview() {
    if (!workflowLoopPreview || !window.LooporaWorkflowDiagram) {
      return;
    }
    window.LooporaWorkflowDiagram.renderInto(workflowLoopPreview, workflowState, {variant: "editor"});
    syncSelectionHighlights();
  }

  function renderSteps() {
    workflowStepsList.innerHTML = "";
    if (!workflowState.steps.length) {
      workflowStepsList.innerHTML = `
        <div class="workflow-empty-state">
          <strong>${localeText("还没有步骤", "No steps yet")}</strong>
          <p>${localeText("先载入一个起手模板，或者从角色定义加入一个角色快照。每加入一个新角色快照，这里都会自动生成它的第一步。", "Load a starter template, or add a role snapshot from Role Definitions. Each new role snapshot auto-generates its first step here.")}</p>
        </div>
      `;
      syncSelectionHighlights();
      return;
    }

    workflowState.steps.forEach((step, index) => {
      const role = roleById(step.role_id);
      const row = document.createElement("article");
      row.className = "workflow-step-row";
      row.dataset.stepIndex = String(index);
      row.dataset.roleId = step.role_id;
      row.tabIndex = 0;
      row.innerHTML = `
        <div class="workflow-step-card-top">
          <div class="workflow-step-ident">
            <span class="workflow-step-order-badge">${index + 1}</span>
            <div class="workflow-step-title-stack">
              <strong>${escapeHtml(role?.name || step.role_id || localeText("未绑定角色", "Unbound role"))}</strong>
              <p>${escapeHtml(localeText(`步骤 ${index + 1}`, `Step ${index + 1}`))} · ${escapeHtml(step.id)}</p>
            </div>
          </div>
          <div class="workflow-step-actions">
            <button type="button" class="ghost-button" data-open-step-settings="${index}" data-testid="workflow-step-settings-button">
              ${escapeHtml(localeText("设置", "Settings"))}
            </button>
            <button type="button" class="ghost-button" data-step-action="move-up" data-step-index="${index}" ${isReadOnly ? "hidden" : ""}>
              ${escapeHtml(localeText("上移", "Up"))}
            </button>
            <button type="button" class="ghost-button" data-step-action="move-down" data-step-index="${index}" ${isReadOnly ? "hidden" : ""}>
              ${escapeHtml(localeText("下移", "Down"))}
            </button>
            <button type="button" class="ghost-button" data-step-action="remove-step" data-step-index="${index}" ${isReadOnly ? "hidden" : ""}>
              ${escapeHtml(localeText("删除", "Delete"))}
            </button>
          </div>
        </div>
        <div class="workflow-step-chip-row">
          <span class="workflow-chip">${escapeHtml(role ? roleLabel(role.archetype) : localeText("缺失角色", "Missing role"))}</span>
          <span class="workflow-chip workflow-chip-muted">${escapeHtml(stepPassLabel(step, role))}</span>
          <span class="workflow-chip workflow-chip-muted">${escapeHtml(stepModelLabel(step))}</span>
        </div>
        <p class="workflow-step-summary-line">
          <span class="workflow-step-summary-label">${escapeHtml(localeText("角色快照", "Role snapshot"))}</span>
          <span>${escapeHtml(role ? roleDefinitionSummary(role) : localeText("当前没有绑定角色。", "No role is bound yet."))}</span>
          <span class="workflow-step-summary-separator">·</span>
          <span>${escapeHtml(role ? roleRuntimeSummary(role) : "-")}</span>
        </p>
        <p class="workflow-step-summary-line workflow-step-summary-line-muted">
          <span class="workflow-step-summary-label">${escapeHtml(localeText("Prompt 与收束", "Prompt & flow"))}</span>
          <span>${escapeHtml(role ? promptFileSummary(role) : "-")}</span>
          <span class="workflow-step-summary-separator">·</span>
          <span>${escapeHtml(stepPassSummary(step, role))}</span>
        </p>
      `;
      workflowStepsList.appendChild(row);
    });
    syncSelectionHighlights();
  }

  function syncSelectionHighlights() {
    workflowLoopPreview?.querySelectorAll("[data-role-id]").forEach((element) => {
      element.classList.toggle("is-active", element.dataset.roleId === activeRoleId);
    });
    workflowStepsList?.querySelectorAll(".workflow-step-row").forEach((element) => {
      element.classList.toggle("is-active", Number(element.dataset.stepIndex) === activeStepIndex);
      element.classList.toggle("is-role-active", element.dataset.roleId === activeRoleId);
    });
  }

  function syncSettingsFieldState(disabled, roleMissing, isGate) {
    [
      settingsStepIdInput,
      settingsStepRoleInput,
      settingsStepModelInput,
    ].forEach((element) => {
      if (element) {
        element.disabled = disabled;
      }
    });
    if (settingsStepOnPassInput) {
      settingsStepOnPassInput.disabled = disabled || roleMissing || !isGate;
    }
  }

  function renderWorkflowSettingsModal() {
    if (!settingsModal) {
      return;
    }
    if (openSettingsStepIndex < 0) {
      settingsModal.hidden = true;
      settingsModal.setAttribute("aria-hidden", "true");
      document.body.classList.remove("modal-open");
      return;
    }

    const step = stepByIndex(openSettingsStepIndex);
    if (!step) {
      openSettingsStepIndex = -1;
      settingsModal.hidden = true;
      settingsModal.setAttribute("aria-hidden", "true");
      document.body.classList.remove("modal-open");
      return;
    }

    const role = roleById(step.role_id);
    const definition = role ? roleDefinitionById(role.role_definition_id) : null;
    const isGate = role?.archetype === "gatekeeper";
    const roleMissing = !role;

    settingsModalTitle.textContent = localeText("步骤设置", "Step settings");
    settingsModalDetail.textContent = localeText(
      `正在编辑步骤 ${openSettingsStepIndex + 1} 的设置；右侧角色快照仅供查看。`,
      `Editing settings for step ${openSettingsStepIndex + 1}; the role snapshot on the right is read-only.`,
    );
    localizeSelectOptions(settingsStepOnPassInput);

    settingsStepRoleInput.innerHTML = workflowState.roles
      .map((entry) => optionHtml(entry.id, entry.name || entry.id, entry.id === step.role_id))
      .join("");

    settingsStepIdInput.value = step.id || "";
    settingsStepModelInput.value = step.model || "";
    settingsStepOnPassInput.value = isGate && step.on_pass === "finish_run" ? "finish_run" : "continue";
    settingsRoleDefinition.textContent = role
      ? (definition ? `${definition.name} · ${roleLabel(definition.archetype)}` : localeText("未绑定角色定义", "Unbound role definition"))
      : localeText("请先给这个步骤绑定角色。", "Bind a role to this step first.");
    settingsRoleRuntime.textContent = role ? roleRuntimeSummary(role) : localeText("当前没有可用的角色快照。", "No role snapshot is available yet.");
    settingsRoleNameValue.textContent = role ? textOrDash(role.name) : localeText("未绑定", "Unbound");
    settingsRoleArchetypeValue.textContent = role ? roleLabel(role.archetype) : "-";
    settingsRolePromptValue.textContent = role ? textOrDash(role.prompt_ref) : "-";
    settingsRoleExecutorKindValue.textContent = role
      ? (EXECUTOR_LABELS[String(role.executor_kind || "").trim()] || textOrDash(role.executor_kind))
      : "-";
    settingsRoleExecutorModeValue.textContent = role ? textOrDash(role.executor_mode) : "-";
    settingsRoleModelValue.textContent = role ? textOrDash(role.model) : "-";
    settingsRoleReasoningValue.textContent = role ? textOrDash(role.reasoning_effort) : "-";
    settingsRoleCommandCliValue.textContent = role ? textOrDash(role.command_cli) : "-";
    settingsRoleCommandArgsValue.textContent = role ? textOrDash(role.command_args_text) : "-";

    syncSettingsFieldState(isReadOnly, roleMissing, isGate);

    settingsModal.hidden = false;
    settingsModal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
    settingsModal.scrollTop = 0;
    settingsModal.querySelector(".workflow-settings-dialog")?.scrollTo({top: 0});
  }

  function renderWorkflowEditor({forceValidation = false} = {}) {
    ensureActiveSelection();
    localizeSelectOptions(workflowStarterSelect);
    syncWorkflowJsonFields();
    renderWorkflowLoopPreview();
    renderSteps();
    renderWorkflowSettingsModal();
    renderWorkflowValidation({forceErrors: forceValidation});
  }

  function closeWorkflowSettingsModal({restoreFocus = true, refresh = false} = {}) {
    if (!settingsModal) {
      return;
    }
    openSettingsStepIndex = -1;
    settingsModal.hidden = true;
    settingsModal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
    if (refresh) {
      renderWorkflowEditor({forceValidation: submitAttempted});
    }
    if (restoreFocus) {
      lastModalTrigger?.focus?.();
    }
    lastModalTrigger = null;
  }

  function openWorkflowSettingsModal(stepIndex, trigger) {
    const step = stepByIndex(stepIndex);
    if (!step) {
      return;
    }
    lastModalTrigger = trigger || document.activeElement;
    openSettingsStepIndex = stepIndex;
    setActiveStep(stepIndex);
    renderWorkflowSettingsModal();
    const firstFocusable = isReadOnly ? settingsModal.querySelector("[data-close-workflow-settings]") : settingsStepIdInput;
    firstFocusable?.focus?.();
  }

  function applyStarterBundle(bundle) {
    if (!bundle) {
      return;
    }
    if (!isReadOnly && workflowHasContent()) {
      const confirmed = window.confirm(localeText(
        "载入起手模板会替换当前的步骤和角色快照。确定继续吗？",
        "Loading a starter template will replace the current steps and role snapshots. Continue?",
      ));
      if (!confirmed) {
        return;
      }
    }
    normalizeWorkflowState(bundle.workflow, bundle.prompt_files);
    activeRoleId = String(workflowState.steps[0]?.role_id || workflowState.roles[0]?.id || "");
    activeStepIndex = workflowState.steps.length ? 0 : -1;
    openSettingsStepIndex = -1;
    renderWorkflowEditor();
  }

  function addStepFromDefinition(roleDefinitionId) {
    const definition = roleDefinitionById(roleDefinitionId);
    if (!definition) {
      showStatus(workflowValidation, localeText("请选择一个可用的角色定义。", "Choose an available role definition first."), "error");
      return;
    }
    let roleSnapshot = workflowState.roles.find((role) => role.role_definition_id === String(definition.id || ""));
    let isNewSnapshot = false;
    if (!roleSnapshot) {
      isNewSnapshot = true;
      const roleId = makeRoleId(definition.name || definition.archetype || "role");
      roleSnapshot = {
        id: roleId,
        name: String(definition.name || roleLabel(definition.archetype || "builder")),
        archetype: String(definition.archetype || "builder"),
        prompt_ref: String(definition.prompt_ref || ""),
        role_definition_id: String(definition.id || ""),
        executor_kind: String(definition.executor_kind || ""),
        executor_mode: String(definition.executor_mode || ""),
        command_cli: String(definition.command_cli || ""),
        command_args_text: String(definition.command_args_text || ""),
        model: String(definition.model || ""),
        reasoning_effort: String(definition.reasoning_effort || ""),
      };
      workflowState.roles.push(roleSnapshot);
      if (definition.prompt_ref) {
        promptFilesState[definition.prompt_ref] = String(definition.prompt_markdown || "");
      }
    }
    workflowState.steps.push({
      id: makeStepId(roleSnapshot.id),
      role_id: roleSnapshot.id,
      on_pass: isNewSnapshot && roleSnapshot.archetype === "gatekeeper" ? "finish_run" : "continue",
      model: "",
    });
    activeStepIndex = workflowState.steps.length - 1;
    activeRoleId = roleSnapshot.id;
    renderWorkflowEditor();
  }

  function roleIdFromEvent(event) {
    if (typeof event.composedPath === "function") {
      const target = event.composedPath().find((item) => item && item.dataset && item.dataset.roleId);
      if (target?.dataset?.roleId) {
        return target.dataset.roleId;
      }
    }
    return event.target?.closest?.("[data-role-id]")?.dataset?.roleId || "";
  }

  function updateStepField(field, rawValue) {
    const step = stepByIndex(openSettingsStepIndex);
    if (!step || !field) {
      return false;
    }
    step[field] = String(rawValue ?? "");
    if (field === "role_id") {
      const role = roleById(step.role_id);
      if (!role || role.archetype !== "gatekeeper") {
        step.on_pass = "continue";
      }
      activeRoleId = step.role_id;
      activeStepIndex = openSettingsStepIndex;
      pruneUnusedRoles();
      return true;
    }
    return field === "on_pass";
  }

  workflowLoopPreview?.addEventListener("mouseover", (event) => {
    const roleId = roleIdFromEvent(event);
    if (roleId) {
      setActiveRole(roleId);
    }
  });

  workflowLoopPreview?.addEventListener("focusin", (event) => {
    const roleId = roleIdFromEvent(event);
    if (roleId) {
      setActiveRole(roleId);
    }
  });

  workflowLoopPreview?.addEventListener("click", (event) => {
    const roleId = roleIdFromEvent(event);
    if (roleId) {
      setActiveRole(roleId, {scroll: true, focus: true});
    }
  });

  workflowStepsList.addEventListener("click", (event) => {
    const settingsButton = event.target.closest("[data-open-step-settings]");
    if (settingsButton) {
      openWorkflowSettingsModal(Number(settingsButton.dataset.openStepSettings), settingsButton);
      return;
    }

    const actionButton = event.target.closest("[data-step-action]");
    if (actionButton) {
      if (isReadOnly) {
        return;
      }
      const action = actionButton.dataset.stepAction;
      const index = Number(actionButton.dataset.stepIndex);
      if (action === "remove-step") {
        workflowState.steps.splice(index, 1);
        if (openSettingsStepIndex === index) {
          openSettingsStepIndex = -1;
        } else if (openSettingsStepIndex > index) {
          openSettingsStepIndex -= 1;
        }
        pruneUnusedRoles();
      } else if (action === "move-up" && index > 0) {
        [workflowState.steps[index - 1], workflowState.steps[index]] = [workflowState.steps[index], workflowState.steps[index - 1]];
        if (openSettingsStepIndex === index) {
          openSettingsStepIndex = index - 1;
        } else if (openSettingsStepIndex === index - 1) {
          openSettingsStepIndex = index;
        }
        activeStepIndex = index - 1;
      } else if (action === "move-down" && index < workflowState.steps.length - 1) {
        [workflowState.steps[index + 1], workflowState.steps[index]] = [workflowState.steps[index], workflowState.steps[index + 1]];
        if (openSettingsStepIndex === index) {
          openSettingsStepIndex = index + 1;
        } else if (openSettingsStepIndex === index + 1) {
          openSettingsStepIndex = index;
        }
        activeStepIndex = index + 1;
      }
      renderWorkflowEditor({forceValidation: submitAttempted});
      return;
    }

    const card = event.target.closest(".workflow-step-row");
    if (!card) {
      return;
    }
    setActiveStep(Number(card.dataset.stepIndex));
  });

  workflowStepsList.addEventListener("keydown", (event) => {
    const card = event.target.closest(".workflow-step-row");
    if (!card) {
      return;
    }
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    if (event.target.closest("button, input, select, textarea, a")) {
      return;
    }
    event.preventDefault();
    setActiveStep(Number(card.dataset.stepIndex));
  });

  settingsModal?.addEventListener("click", (event) => {
    const closeTarget = event.target.closest("[data-close-workflow-settings]");
    if (closeTarget) {
      closeWorkflowSettingsModal({refresh: true});
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && settingsModal && !settingsModal.hidden) {
      closeWorkflowSettingsModal({refresh: true});
    }
  });

  function handleSettingsFieldEdit(event) {
    if (isReadOnly || openSettingsStepIndex < 0) {
      return;
    }
    const stepField = event.target.dataset.stepField;
    const value = event.target.type === "checkbox" ? event.target.checked : event.target.value;

    let requiresRender = false;
    if (stepField) {
      requiresRender = updateStepField(stepField, value) || event.type === "change";
    } else {
      return;
    }

    syncWorkflowJsonFields();
    renderWorkflowValidation({forceErrors: submitAttempted});
    if (requiresRender) {
      renderWorkflowEditor({forceValidation: submitAttempted});
    }
  }

  settingsModal?.addEventListener("input", handleSettingsFieldEdit);
  settingsModal?.addEventListener("change", handleSettingsFieldEdit);

  loadWorkflowStarterButton?.addEventListener("click", () => {
    if (isReadOnly) {
      return;
    }
    applyStarterBundle(starterBundleById(workflowStarterSelect?.value));
  });

  addStepButton?.addEventListener("click", () => {
    if (isReadOnly) {
      return;
    }
    addStepFromDefinition(roleDefinitionSelect?.value);
  });

  form.addEventListener("submit", (event) => {
    if (isReadOnly) {
      event.preventDefault();
      showStatus(formError, localeText("默认编排是只读的，请新建一条自定义编排。", "Built-in orchestrations are read-only. Create a custom orchestration instead."), "error");
      return;
    }
    submitAttempted = true;
    if (!renderWorkflowValidation({forceErrors: true})) {
      event.preventDefault();
      showStatus(formError, localeText("编排结构不完整，请先修正。", "The orchestration is incomplete. Please fix it before saving."), "error");
      return;
    }
    syncWorkflowJsonFields();
    if (saveOrchestrationButton) {
      saveOrchestrationButton.disabled = true;
    }
  });

  document.addEventListener("loopora:localechange", () => renderWorkflowEditor({forceValidation: submitAttempted}));

  try {
    normalizeWorkflowState(
      JSON.parse(workflowJsonInput.value || "{}"),
      JSON.parse(promptFilesJsonInput.value || "{}"),
    );
  } catch (_) {
    normalizeWorkflowState({version: 1, preset: "", roles: [], steps: []}, {});
  }

  renderWorkflowEditor();
});
