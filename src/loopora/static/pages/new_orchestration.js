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
  };

  const formError = document.getElementById("form-error");
  const workflowValidation = document.getElementById("workflow-validation");
  const workflowPresetInput = document.getElementById("workflow-preset-input");
  const workflowRolesList = document.getElementById("workflow-roles-list");
  const workflowStepsList = document.getElementById("workflow-steps-list");
  const workflowJsonInput = document.getElementById("workflow-json-input");
  const promptFilesJsonInput = document.getElementById("prompt-files-json-input");
  const resetWorkflowPresetButton = document.getElementById("reset-workflow-preset");
  const roleDefinitionSelect = document.getElementById("role-definition-select");
  const addRoleFromDefinitionButton = document.getElementById("add-role-from-definition-button");
  const addStepButton = document.getElementById("add-step-button");
  const saveOrchestrationButton = document.getElementById("save-orchestration-button");

  const workflowPresetBundles = JSON.parse(document.getElementById("workflow-preset-bundles-json")?.textContent || "{}");
  const roleDefinitions = JSON.parse(document.getElementById("role-definitions-json")?.textContent || "[]");

  let workflowState = null;
  let promptFilesState = null;

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

  function promptBundleForPreset(name) {
    return workflowPresetBundles[String(name || "").trim()] || workflowPresetBundles.build_first || null;
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

  function normalizeWorkflowState(workflow, promptFiles) {
    const fallbackBundle = promptBundleForPreset(workflowPresetInput.value);
    const workflowPayload = clone(workflow || fallbackBundle?.workflow || {version: 1, preset: "build_first", roles: [], steps: []});
    workflowPayload.version = 1;
    workflowPayload.roles = Array.isArray(workflowPayload.roles) ? workflowPayload.roles.map(normalizeRole) : [];
    workflowPayload.steps = Array.isArray(workflowPayload.steps) ? workflowPayload.steps.map((step, index) => ({
      id: String(step.id || `step_${index + 1}`),
      role_id: String(step.role_id || workflowPayload.roles[0]?.id || ""),
      enabled: step.enabled !== false,
      on_pass: String(step.on_pass || "continue"),
      model: String(step.model || ""),
    })) : [];
    workflowState = workflowPayload;
    promptFilesState = {...(promptFiles || {})};
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

  function workflowValidationMessages() {
    const messages = [];
    const roleIds = new Set();
    const stepIds = new Set();
    if (!workflowState.roles.length) {
      messages.push(localeText("至少需要 1 个角色定义快照。", "At least one role definition snapshot is required."));
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
    const roleById = Object.fromEntries(workflowState.roles.map((role) => [role.id, role]));
    const enabledFinishGate = workflowState.steps.some((step) => {
      if (step.enabled === false) {
        return false;
      }
      const role = roleById[step.role_id];
      return role?.archetype === "gatekeeper" && step.on_pass === "finish_run";
    });
    if (enabledFinishGate) {
      return [];
    }
    return [
      localeText(
        "这套编排没有“通过即结束”的 GateKeeper 步骤。把它交给按轮次推进的 loop 没问题；如果要靠守门裁决收敛，请补一个 GateKeeper finish step。",
        "This orchestration has no finish-on-pass GateKeeper step. It is fine for round-based loops; add a GateKeeper finish step before using gate-based completion.",
      ),
    ];
  }

  function renderWorkflowValidation() {
    const messages = workflowValidationMessages();
    if (!messages.length) {
      const warnings = workflowValidationWarnings();
      showStatus(
        workflowValidation,
        warnings[0] || localeText("编排结构看起来没问题。", "The orchestration structure looks valid."),
        warnings.length ? "warning" : "success",
      );
      return true;
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

  function renderRoles() {
    workflowRolesList.innerHTML = "";
    if (!workflowState.roles.length) {
      workflowRolesList.innerHTML = `
        <div class="workflow-empty-state">
          <strong>${localeText("还没有角色", "No roles yet")}</strong>
          <p>${localeText("先从“角色定义”里选一个角色加入编排。", "Start by adding a role definition snapshot into the orchestration.")}</p>
        </div>
      `;
      renderWorkflowValidation();
      return;
    }
    workflowState.roles.forEach((role, index) => {
      const definition = roleDefinitionById(role.role_definition_id);
      const card = document.createElement("article");
      card.className = "workflow-role-card";
      card.innerHTML = `
        <div class="workflow-card-head">
          <div>
            <strong>${escapeHtml(role.name || role.id)}</strong>
            <p class="workflow-section-note">${definition
              ? `${localeText("来源角色定义", "Role definition")}: ${escapeHtml(definition.name)}`
              : localeText("这是较早版本留下的角色快照，建议重新绑定一个角色定义。", "This is a legacy role snapshot. Rebind it to a role definition when convenient.")}</p>
          </div>
        </div>
        <div class="form-grid">
          <label><span>${localeText("角色 ID", "Role ID")}</span><input value="${escapeHtml(role.id)}" readonly /></label>
          <label><span>${localeText("角色模板", "Role template")}</span><input value="${escapeHtml(roleLabel(role.archetype))}" readonly /></label>
          <label><span>${localeText("执行配置", "Execution config")}</span><input value="${escapeHtml(roleRuntimeSummary(role))}" readonly /></label>
          <label><span>${localeText("Prompt 文件", "Prompt file")}</span><input value="${escapeHtml(role.prompt_ref || "-")}" readonly /></label>
        </div>
        <div class="card-actions card-actions-compact">
          <button type="button" class="ghost-button" data-role-action="remove-role" data-role-index="${index}">${localeText("移出编排", "Remove role")}</button>
        </div>
      `;
      workflowRolesList.appendChild(card);
    });
    renderWorkflowValidation();
  }

  function onPassLabel(value) {
    if (value === "finish_run") {
      return localeText("通过后结束流程", "Finish the run when passed");
    }
    return localeText("继续后续步骤", "Continue to the next step");
  }

  function renderSteps() {
    workflowStepsList.innerHTML = "";
    if (!workflowState.steps.length) {
      workflowStepsList.innerHTML = `
        <div class="workflow-empty-state">
          <strong>${localeText("还没有步骤", "No steps yet")}</strong>
          <p>${localeText("步骤决定每轮的执行顺序。先添加一个步骤，把角色串起来。", "Steps define the execution order for each iteration. Add one to start wiring roles together.")}</p>
        </div>
      `;
      renderWorkflowValidation();
      return;
    }
    workflowState.steps.forEach((step, index) => {
      const roleOptions = workflowState.roles.map((role) => `<option value="${escapeHtml(role.id)}" ${role.id === step.role_id ? "selected" : ""}>${escapeHtml(role.name)}</option>`).join("");
      const role = workflowState.roles.find((entry) => entry.id === step.role_id);
      const isGate = role?.archetype === "gatekeeper";
      const card = document.createElement("article");
      card.className = "workflow-step-card";
      card.innerHTML = `
        <div class="workflow-card-head">
          <strong>${localeText(`步骤 ${index + 1}`, `Step ${index + 1}`)}</strong>
        </div>
        <div class="form-grid">
          <label><span>${localeText("步骤 ID", "Step ID")}</span><input data-step-field="id" data-step-index="${index}" value="${escapeHtml(step.id)}" /></label>
          <label><span>${localeText("角色", "Role")}</span><select data-step-field="role_id" data-step-index="${index}">${roleOptions}</select></label>
          <label><span>${localeText("步骤模型覆盖", "Step model override")}</span><input data-step-field="model" data-step-index="${index}" value="${escapeHtml(step.model || "")}" /></label>
          <label><span>${localeText("通过后动作", "On pass")}</span><select data-step-field="on_pass" data-step-index="${index}" ${isGate ? "" : "disabled"}>
            <option value="continue" ${step.on_pass === "continue" ? "selected" : ""}>${escapeHtml(onPassLabel("continue"))}</option>
            <option value="finish_run" ${step.on_pass === "finish_run" ? "selected" : ""}>${escapeHtml(onPassLabel("finish_run"))}</option>
          </select></label>
          <label class="checkbox-row"><input type="checkbox" data-step-field="enabled" data-step-index="${index}" ${step.enabled !== false ? "checked" : ""} /><span>${localeText("启用这个步骤", "Enable this step")}</span></label>
        </div>
        <p class="workflow-step-note">${isGate
          ? localeText("这个 GateKeeper 可以决定流程是继续推进，还是在满足条件后直接结束。", "This GateKeeper can decide whether the workflow keeps going or ends once it passes.")
          : localeText("只有 GateKeeper 步骤才会出现“通过后动作”的收敛选项。", "Only GateKeeper steps can decide what happens after a passing result.")}</p>
        <div class="card-actions card-actions-compact">
          <button type="button" class="ghost-button" data-step-action="move-up" data-step-index="${index}">${localeText("上移", "Move up")}</button>
          <button type="button" class="ghost-button" data-step-action="move-down" data-step-index="${index}">${localeText("下移", "Move down")}</button>
          <button type="button" class="ghost-button" data-step-action="remove-step" data-step-index="${index}">${localeText("删除步骤", "Remove step")}</button>
        </div>
      `;
      workflowStepsList.appendChild(card);
    });
    renderWorkflowValidation();
  }

  function renderWorkflowEditor() {
    syncWorkflowJsonFields();
    renderRoles();
    renderSteps();
  }

  function applyPresetBundle(bundle) {
    if (!bundle) {
      return;
    }
    normalizeWorkflowState(bundle.workflow, bundle.prompt_files);
    renderWorkflowEditor();
  }

  function addRoleFromDefinition(roleDefinitionId) {
    const definition = roleDefinitionById(roleDefinitionId);
    if (!definition) {
      showStatus(workflowValidation, localeText("请选择一个可用的角色定义。", "Choose an available role definition first."), "error");
      return;
    }
    const roleId = makeRoleId(definition.name || definition.archetype || "role");
    workflowState.roles.push({
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
    });
    if (definition.prompt_ref) {
      promptFilesState[definition.prompt_ref] = String(definition.prompt_markdown || "");
    }
    renderWorkflowEditor();
  }

  workflowRolesList.addEventListener("click", (event) => {
    const action = event.target.dataset.roleAction;
    if (!action) {
      return;
    }
    const index = Number(event.target.dataset.roleIndex);
    const role = workflowState.roles[index];
    if (!role) {
      return;
    }
    if (action === "remove-role") {
      workflowState.roles.splice(index, 1);
      workflowState.steps = workflowState.steps.filter((step) => step.role_id !== role.id);
      renderWorkflowEditor();
    }
  });

  workflowStepsList.addEventListener("input", (event) => {
    const index = Number(event.target.dataset.stepIndex);
    const field = event.target.dataset.stepField;
    const step = workflowState.steps[index];
    if (!step || !field) {
      return;
    }
    step[field] = field === "enabled" ? event.target.checked : event.target.value;
    if (field === "role_id") {
      const role = workflowState.roles.find((entry) => entry.id === step.role_id);
      if (!role || role.archetype !== "gatekeeper") {
        step.on_pass = "continue";
      }
      renderSteps();
      return;
    }
    syncWorkflowJsonFields();
    renderWorkflowValidation();
  });

  workflowStepsList.addEventListener("click", (event) => {
    const action = event.target.dataset.stepAction;
    if (!action) {
      return;
    }
    const index = Number(event.target.dataset.stepIndex);
    if (action === "remove-step") {
      workflowState.steps.splice(index, 1);
    } else if (action === "move-up" && index > 0) {
      [workflowState.steps[index - 1], workflowState.steps[index]] = [workflowState.steps[index], workflowState.steps[index - 1]];
    } else if (action === "move-down" && index < workflowState.steps.length - 1) {
      [workflowState.steps[index + 1], workflowState.steps[index]] = [workflowState.steps[index], workflowState.steps[index + 1]];
    }
    renderWorkflowEditor();
  });

  resetWorkflowPresetButton?.addEventListener("click", () => applyPresetBundle(promptBundleForPreset(workflowPresetInput.value)));
  addRoleFromDefinitionButton?.addEventListener("click", () => addRoleFromDefinition(roleDefinitionSelect?.value));
  addStepButton?.addEventListener("click", () => {
    if (!workflowState.roles.length) {
      showStatus(workflowValidation, localeText("请先加入至少一个角色定义。", "Add at least one role definition first."), "error");
      return;
    }
    const roleId = workflowState.roles[0].id;
    workflowState.steps.push({id: makeStepId(roleId), role_id: roleId, enabled: true, on_pass: "continue", model: ""});
    renderWorkflowEditor();
  });

  form.addEventListener("submit", (event) => {
    if (!renderWorkflowValidation()) {
      event.preventDefault();
      showStatus(formError, localeText("编排结构不完整，请先修正。", "The orchestration is incomplete. Please fix it before saving."), "error");
      return;
    }
    syncWorkflowJsonFields();
    saveOrchestrationButton.disabled = true;
  });

  document.addEventListener("loopora:localechange", () => renderWorkflowEditor());

  normalizeWorkflowState(
    JSON.parse(workflowJsonInput.value || "{}"),
    JSON.parse(promptFilesJsonInput.value || "{}"),
  );
  renderWorkflowEditor();
});
