document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("new-orchestration-form");
  if (!form || !window.LooporaUI) {
    return;
  }

  const ARCHETYPE_ORDER = ["builder", "inspector", "gatekeeper", "guide"];
  const ARCHETYPE_LABELS = {
    builder: {zh: "建造者", en: "Builder"},
    inspector: {zh: "巡检者", en: "Inspector"},
    gatekeeper: {zh: "守门人", en: "GateKeeper"},
    guide: {zh: "向导", en: "Guide"},
  };
  const DEFAULT_PROMPTS = {
    builder: "builder.md",
    inspector: "inspector.md",
    gatekeeper: "gatekeeper.md",
    guide: "guide.md",
  };

  const formError = document.getElementById("form-error");
  const workflowValidation = document.getElementById("workflow-validation");
  const workflowPresetInput = document.getElementById("workflow-preset-input");
  const workflowRolesList = document.getElementById("workflow-roles-list");
  const workflowStepsList = document.getElementById("workflow-steps-list");
  const workflowJsonInput = document.getElementById("workflow-json-input");
  const promptFilesJsonInput = document.getElementById("prompt-files-json-input");
  const resetWorkflowPresetButton = document.getElementById("reset-workflow-preset");
  const addRoleButton = document.getElementById("add-role-button");
  const addStepButton = document.getElementById("add-step-button");
  const saveOrchestrationButton = document.getElementById("save-orchestration-button");

  const workflowPresetBundles = JSON.parse(document.getElementById("workflow-preset-bundles-json")?.textContent || "{}");
  const promptTemplates = JSON.parse(document.getElementById("prompt-templates-json")?.textContent || "[]");
  const promptTemplateSet = new Set(promptTemplates.map((entry) => String(entry.prompt_ref || "").trim()).filter(Boolean));

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

  function onPassLabel(value) {
    if (value === "finish_run") {
      return localeText("通过后结束流程", "Finish the run when passed");
    }
    return localeText("继续后续步骤", "Continue to the next step");
  }

  function promptBundleForPreset(name) {
    return workflowPresetBundles[String(name || "").trim()] || workflowPresetBundles.build_first || null;
  }

  function ensurePromptText(promptRef, archetype) {
    const ref = String(promptRef || "").trim();
    if (!ref) {
      return "";
    }
    if (promptFilesState[ref]) {
      return promptFilesState[ref];
    }
    const bundle = promptBundleForPreset(workflowPresetInput.value);
    if (bundle?.prompt_files?.[ref]) {
      promptFilesState[ref] = bundle.prompt_files[ref];
      return promptFilesState[ref];
    }
    const fallbackRef = DEFAULT_PROMPTS[archetype];
    if (fallbackRef && bundle?.prompt_files?.[fallbackRef]) {
      promptFilesState[ref] = bundle.prompt_files[fallbackRef];
      return promptFilesState[ref];
    }
    return "";
  }

  function makeRoleId(archetype) {
    const existing = new Set((workflowState?.roles || []).map((role) => role.id));
    const base = archetype || "role";
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

  function normalizeWorkflowState(workflow, promptFiles) {
    const fallbackBundle = promptBundleForPreset(workflowPresetInput.value);
    const workflowPayload = clone(workflow || fallbackBundle?.workflow || {version: 1, preset: "build_first", roles: [], steps: []});
    workflowPayload.version = 1;
    workflowPayload.roles = Array.isArray(workflowPayload.roles) ? workflowPayload.roles : [];
    workflowPayload.steps = Array.isArray(workflowPayload.steps) ? workflowPayload.steps : [];
    workflowPayload.roles = workflowPayload.roles.map((role, index) => {
      const archetype = ARCHETYPE_ORDER.includes(role.archetype) ? role.archetype : "builder";
      const promptRef = String(role.prompt_ref || "").trim() || DEFAULT_PROMPTS[archetype];
      return {
        id: String(role.id || `role_${index + 1}`),
        name: String(role.name || roleLabel(archetype)),
        archetype,
        prompt_ref: promptRef,
        model: String(role.model || ""),
      };
    });
    workflowPayload.steps = workflowPayload.steps.map((step, index) => ({
      id: String(step.id || `step_${index + 1}`),
      role_id: String(step.role_id || workflowPayload.roles[0]?.id || ""),
      enabled: step.enabled !== false,
      on_pass: String(step.on_pass || "continue"),
    }));
    workflowState = workflowPayload;
    promptFilesState = {...(promptFiles || {})};
    workflowState.roles.forEach((role) => ensurePromptText(role.prompt_ref, role.archetype));
  }

  function syncWorkflowJsonFields() {
    workflowJsonInput.value = JSON.stringify(workflowState, null, 2);
    const nextPromptFiles = {};
    workflowState.roles.forEach((role) => {
      if (role.prompt_ref) {
        nextPromptFiles[role.prompt_ref] = promptFilesState[role.prompt_ref] || "";
      }
    });
    promptFilesState = nextPromptFiles;
    promptFilesJsonInput.value = JSON.stringify(promptFilesState, null, 2);
  }

  function workflowValidationMessages() {
    const messages = [];
    const roleIds = new Set();
    const enabledGateSteps = [];
    if (!workflowState.roles.length) {
      messages.push(localeText("至少需要 1 个角色。", "At least one role is required."));
    }
    workflowState.roles.forEach((role) => {
      if (!role.id.trim()) {
        messages.push(localeText("每个角色都需要一个 id。", "Every role needs an id."));
      }
      if (roleIds.has(role.id)) {
        messages.push(localeText(`角色 id 重复：${role.id}`, `Duplicate role id: ${role.id}`));
      }
      roleIds.add(role.id);
      if (!role.prompt_ref.trim()) {
        messages.push(localeText(`角色 ${role.id} 缺少 prompt_ref。`, `Role ${role.id} is missing a prompt_ref.`));
      }
    });
    if (!workflowState.steps.length) {
      messages.push(localeText("至少需要 1 个步骤。", "At least one step is required."));
    }
    workflowState.steps.forEach((step) => {
      if (!step.role_id || !roleIds.has(step.role_id)) {
        messages.push(localeText(`步骤 ${step.id || "(未命名)"} 引用了不存在的角色。`, `Step ${step.id || "(unnamed)"} references an unknown role.`));
      }
      const role = workflowState.roles.find((entry) => entry.id === step.role_id);
      if (step.enabled !== false && role?.archetype === "gatekeeper" && step.on_pass === "finish_run") {
        enabledGateSteps.push(step);
      }
    });
    if (!enabledGateSteps.length) {
      messages.push(
        localeText(
          "至少要有一个启用中的 GateKeeper 步骤，能够在满足条件时判定流程完成。",
          "Add at least one enabled GateKeeper step that can mark the workflow as complete.",
        ),
      );
    }
    return messages;
  }

  function renderWorkflowValidation() {
    const messages = workflowValidationMessages();
    if (!messages.length) {
      showStatus(workflowValidation, localeText("工作流结构看起来没问题。", "Workflow structure looks valid."), "success");
      return true;
    }
    showStatus(workflowValidation, messages.join(" "), "error");
    return false;
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    const payload = await response.json().catch(() => ({}));
    return {response, payload};
  }

  async function loadPromptTemplate(promptRef) {
    const response = await fetch(`/api/prompts/templates/${encodeURIComponent(promptRef)}`);
    if (!response.ok) {
      throw new Error(localeText("无法下载 prompt 模板。", "Unable to download the prompt template."));
    }
    return response.text();
  }

  async function validatePrompt(promptRef, archetype) {
    return fetchJson("/api/prompts/validate", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({markdown: promptFilesState[promptRef] || "", archetype}),
    }).then(({payload}) => payload);
  }

  async function validateAllPrompts() {
    for (const role of workflowState.roles) {
      const payload = await validatePrompt(role.prompt_ref, role.archetype);
      if (!payload.ok) {
        showStatus(workflowValidation, payload.error || localeText("Prompt 校验失败。", "Prompt validation failed."), "error");
        return false;
      }
    }
    return true;
  }

  function renderRoles() {
    workflowRolesList.innerHTML = "";
    if (!workflowState.roles.length) {
      workflowRolesList.innerHTML = `
        <div class="workflow-empty-state">
          <strong>${localeText("还没有角色", "No roles yet")}</strong>
          <p>${localeText("先添加一个角色，再为它设置原型和 prompt。", "Add a role first, then choose its archetype and prompt.")}</p>
        </div>
      `;
      renderWorkflowValidation();
      return;
    }
    workflowState.roles.forEach((role, index) => {
      const promptText = ensurePromptText(role.prompt_ref, role.archetype);
      const card = document.createElement("article");
      card.className = "workflow-role-card";
      card.innerHTML = `
        <div class="workflow-card-head">
          <strong>${escapeHtml(role.name || role.id)}</strong>
        </div>
        <div class="form-grid">
          <label><span>${localeText("角色 ID", "Role ID")}</span><input data-role-field="id" data-role-index="${index}" value="${escapeHtml(role.id)}" /></label>
          <label><span>${localeText("显示名", "Display name")}</span><input data-role-field="name" data-role-index="${index}" value="${escapeHtml(role.name)}" /></label>
          <label><span>${localeText("原型", "Archetype")}</span>
            <select data-role-field="archetype" data-role-index="${index}">
              ${ARCHETYPE_ORDER.map((item) => `<option value="${escapeHtml(item)}" ${item === role.archetype ? "selected" : ""}>${escapeHtml(roleLabel(item))}</option>`).join("")}
            </select>
          </label>
          <label><span>${localeText("Prompt 文件", "Prompt file")}</span><input data-role-field="prompt_ref" data-role-index="${index}" value="${escapeHtml(role.prompt_ref)}" list="prompt-template-options" /></label>
          <label><span>${localeText("模型覆盖", "Model override")}</span><input data-role-field="model" data-role-index="${index}" value="${escapeHtml(role.model || "")}" /></label>
        </div>
        <label class="wide">
          <span>${localeText("Prompt Markdown", "Prompt Markdown")}</span>
          <textarea data-prompt-field="markdown" data-role-index="${index}" rows="12">${escapeHtml(promptText)}</textarea>
        </label>
        <div class="card-actions card-actions-compact">
          <button type="button" class="ghost-button" data-role-action="load-template" data-role-index="${index}">${localeText("载入模版", "Load template")}</button>
          <button type="button" class="ghost-button" data-role-action="validate-prompt" data-role-index="${index}">${localeText("校验格式", "Validate")}</button>
          <button type="button" class="ghost-button" data-role-action="download-prompt" data-role-index="${index}">${localeText("下载 Prompt", "Download prompt")}</button>
          <label class="ghost-button" style="cursor:pointer;">
            <span>${localeText("上传 Prompt", "Upload prompt")}</span>
            <input type="file" hidden accept=".md,text/markdown,text/plain" data-role-action="upload-prompt" data-role-index="${index}" />
          </label>
          <button type="button" class="ghost-button" data-role-action="remove-role" data-role-index="${index}">${localeText("删除角色", "Remove role")}</button>
        </div>
      `;
      workflowRolesList.appendChild(card);
    });
    renderWorkflowValidation();
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

  workflowRolesList.addEventListener("input", (event) => {
    const index = Number(event.target.dataset.roleIndex);
    const field = event.target.dataset.roleField;
    const role = workflowState.roles[index];
    if (!role || !field) {
      return;
    }
    role[field] = event.target.value;
    if (field === "archetype") {
      role.name = roleLabel(role.archetype);
      if (!role.prompt_ref || promptTemplateSet.has(role.prompt_ref)) {
        role.prompt_ref = DEFAULT_PROMPTS[role.archetype];
      }
      ensurePromptText(role.prompt_ref, role.archetype);
      renderWorkflowEditor();
      return;
    }
    if (field === "prompt_ref") {
      ensurePromptText(role.prompt_ref, role.archetype);
    }
    syncWorkflowJsonFields();
    renderWorkflowValidation();
  });

  workflowRolesList.addEventListener("input", (event) => {
    if (event.target.dataset.promptField !== "markdown") {
      return;
    }
    const index = Number(event.target.dataset.roleIndex);
    const role = workflowState.roles[index];
    if (!role) {
      return;
    }
    promptFilesState[role.prompt_ref] = event.target.value;
    syncWorkflowJsonFields();
  });

  workflowRolesList.addEventListener("click", async (event) => {
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
      return;
    }
    if (action === "load-template") {
      try {
        promptFilesState[role.prompt_ref] = await loadPromptTemplate(role.prompt_ref);
        renderWorkflowEditor();
      } catch (error) {
        showStatus(workflowValidation, error.message, "error");
      }
      return;
    }
    if (action === "validate-prompt") {
      const payload = await validatePrompt(role.prompt_ref, role.archetype);
      showStatus(workflowValidation, payload.ok ? localeText(`Prompt 格式通过：${role.name}`, `Prompt is valid: ${role.name}`) : (payload.error || localeText("Prompt 校验失败。", "Prompt validation failed.")), payload.ok ? "success" : "error");
      return;
    }
    if (action === "download-prompt") {
      const blob = new Blob([promptFilesState[role.prompt_ref] || ""], {type: "text/markdown;charset=utf-8"});
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = role.prompt_ref;
      link.click();
      URL.revokeObjectURL(url);
    }
  });

  workflowRolesList.addEventListener("change", async (event) => {
    if (event.target.dataset.roleAction !== "upload-prompt") {
      return;
    }
    const index = Number(event.target.dataset.roleIndex);
    const role = workflowState.roles[index];
    const file = event.target.files?.[0];
    if (!role || !file) {
      return;
    }
    promptFilesState[role.prompt_ref] = await file.text();
    renderWorkflowEditor();
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

  workflowJsonInput.addEventListener("change", () => {
    try {
      normalizeWorkflowState(JSON.parse(workflowJsonInput.value), JSON.parse(promptFilesJsonInput.value || "{}"));
      renderWorkflowEditor();
    } catch (_) {
      showStatus(workflowValidation, localeText("workflow_json 不是合法 JSON。", "workflow_json must be valid JSON."), "error");
    }
  });

  promptFilesJsonInput.addEventListener("change", () => {
    try {
      promptFilesState = JSON.parse(promptFilesJsonInput.value || "{}");
      renderWorkflowEditor();
    } catch (_) {
      showStatus(workflowValidation, localeText("prompt_files_json 不是合法 JSON。", "prompt_files_json must be valid JSON."), "error");
    }
  });

  resetWorkflowPresetButton.addEventListener("click", () => applyPresetBundle(promptBundleForPreset(workflowPresetInput.value)));
  addRoleButton.addEventListener("click", () => {
    const archetype = "builder";
    const roleId = makeRoleId(archetype);
    workflowState.roles.push({id: roleId, name: roleLabel(archetype), archetype, prompt_ref: DEFAULT_PROMPTS[archetype], model: ""});
    ensurePromptText(DEFAULT_PROMPTS[archetype], archetype);
    renderWorkflowEditor();
  });
  addStepButton.addEventListener("click", () => {
    if (!workflowState.roles.length) {
      workflowState.roles.push({id: "builder", name: roleLabel("builder"), archetype: "builder", prompt_ref: DEFAULT_PROMPTS.builder, model: ""});
    }
    const roleId = workflowState.roles[0].id;
    workflowState.steps.push({id: makeStepId(roleId), role_id: roleId, enabled: true, on_pass: "continue"});
    renderWorkflowEditor();
  });

  form.addEventListener("submit", async (event) => {
    if (!renderWorkflowValidation()) {
      event.preventDefault();
      showStatus(formError, localeText("工作流结构不完整，请先修正。", "The workflow is incomplete. Please fix it before saving."), "error");
      return;
    }
    syncWorkflowJsonFields();
    const promptsValid = await validateAllPrompts();
    if (!promptsValid) {
      event.preventDefault();
      showStatus(formError, localeText("至少有一个 prompt 文件格式不合法。", "At least one prompt file is invalid."), "error");
      return;
    }
    saveOrchestrationButton.disabled = true;
  });

  document.addEventListener("loopora:localechange", () => renderWorkflowEditor());

  normalizeWorkflowState(
    JSON.parse(workflowJsonInput.value || "{}"),
    JSON.parse(promptFilesJsonInput.value || "{}"),
  );
  renderWorkflowEditor();
});
