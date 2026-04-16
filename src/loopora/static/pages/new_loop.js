document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("new-loop-form");
  if (!form || !window.LooporaUI) {
    return;
  }

  const workdirInput = document.getElementById("workdir-input");
  const specPathInput = document.getElementById("spec-path-input");
  const orchestrationInput = document.getElementById("orchestration-id-input");
  const orchestrationSummary = document.getElementById("orchestration-summary");
  const completionModeInput = document.getElementById("completion-mode-input");
  const iterationIntervalInput = document.getElementById("iteration-interval-input");
  const executorKindInput = document.getElementById("executor-kind-input");
  const executorModeInput = document.getElementById("executor-mode-input");
  const modelFieldLabel = document.getElementById("model-field-label");
  const effortFieldLabel = document.getElementById("effort-field-label");
  const modelInput = document.getElementById("model-input");
  const reasoningInput = document.getElementById("reasoning-input");
  const modelHelpTrigger = document.getElementById("model-help-trigger");
  const effortHelpTrigger = document.getElementById("effort-help-trigger");
  const modelFieldNote = document.getElementById("model-field-note");
  const effortFieldNote = document.getElementById("effort-field-note");
  const presetModelField = document.getElementById("preset-model-field");
  const presetEffortField = document.getElementById("preset-effort-field");
  const presetConfigCard = document.getElementById("preset-config-card");
  const commandConfigCard = document.getElementById("command-config-card");
  const presetConfigState = document.getElementById("preset-config-state");
  const commandConfigState = document.getElementById("command-config-state");
  const commandCliField = document.getElementById("command-cli-field");
  const commandArgsField = document.getElementById("command-args-field");
  const commandCliInput = document.getElementById("command-cli-input");
  const commandArgsInput = document.getElementById("command-args-input");
  const commandPreview = document.getElementById("command-preview");
  const commandPreviewNote = document.getElementById("command-preview-note");
  const browseWorkdirButton = document.getElementById("browse-workdir");
  const browseSpecButton = document.getElementById("browse-spec");
  const createSpecTemplateButton = document.getElementById("create-spec-template");
  const saveLoopButton = document.getElementById("save-loop-button");
  const formError = document.getElementById("form-error");
  const draftStatus = document.getElementById("draft-status");
  const draftActions = document.getElementById("draft-actions");
  const clearDraftButton = document.getElementById("clear-draft-button");
  const specValidation = document.getElementById("spec-validation");
  const executorProfiles = JSON.parse(document.getElementById("executor-profiles-json")?.textContent || "[]");
  const orchestrations = JSON.parse(document.getElementById("orchestrations-json")?.textContent || "[]");
  const pristineLoopForm = JSON.parse(document.getElementById("pristine-loop-form-json")?.textContent || "{}");
  const workdirQuickPickButtons = Array.from(document.querySelectorAll("[data-fill-workdir]"));
  const roleModelInputs = {
    builder: document.getElementById("role-model-builder-input"),
    inspector: document.getElementById("role-model-inspector-input"),
    gatekeeper: document.getElementById("role-model-gatekeeper-input"),
    guide: document.getElementById("role-model-guide-input"),
  };

  const DRAFT_STORAGE_KEY = "loopora:new-loop-draft:v1";
  const commandDrafts = new Map();
  let lastExecutorKind = executorKindInput.value;
  let latestSpecValidationRequest = 0;

  function localeText(zh, en) {
    return window.LooporaUI.pickText({zh, en});
  }

  function setBilingualHtml(element, zh, en) {
    element.innerHTML = `<span data-lang="zh">${zh}</span><span data-lang="en">${en}</span>`;
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

  function errorMessage(error, fallbackMessage) {
    if (error && typeof error === "object" && "message" in error && error.message) {
      return String(error.message);
    }
    return fallbackMessage;
  }

  function setButtonBusy(button, isBusy) {
    if (!button) {
      return;
    }
    button.disabled = isBusy;
    button.setAttribute("aria-busy", String(isBusy));
  }

  function loadDraft() {
    try {
      const raw = window.localStorage.getItem(DRAFT_STORAGE_KEY);
      if (!raw) {
        return null;
      }
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : null;
    } catch (_) {
      return null;
    }
  }

  function hasDraft(draft) {
    return Object.keys(pruneDraft(draft)).length > 0;
  }

  function normalizeDraftValue(key, value) {
    if (key === "start_immediately") {
      if (typeof value === "boolean") {
        return value ? "1" : "";
      }
      const normalized = String(value || "").trim().toLowerCase();
      return normalized === "1" || normalized === "true" ? "1" : "";
    }
    return String(value ?? "");
  }

  function pruneDraft(rawDraft) {
    if (!rawDraft || typeof rawDraft !== "object") {
      return {};
    }
    const draft = {};
    Object.entries(rawDraft).forEach(([key, value]) => {
      const normalizedValue = normalizeDraftValue(key, value);
      const pristineValue = normalizeDraftValue(key, pristineLoopForm[key]);
      if (normalizedValue !== pristineValue) {
        draft[key] = normalizedValue;
      }
    });
    return draft;
  }

  function updateDraftUI() {
    const draft = loadDraft();
    const visible = hasDraft(draft);
    if (draftActions) {
      draftActions.hidden = !visible;
    }
  }

  function collectDraft() {
    const formData = new FormData(form);
    const draft = Object.fromEntries(
      Array.from(formData.entries()).map(([key, value]) => [key, typeof value === "string" ? value : String(value)]),
    );
    draft.start_immediately = form.querySelector('input[name="start_immediately"]')?.checked ? "1" : "";
    draft.model = modelInput.value;
    draft.reasoning_effort = reasoningInput.value;
    return draft;
  }

  function saveDraft() {
    const draft = pruneDraft(collectDraft());
    try {
      if (Object.keys(draft).length === 0) {
        window.localStorage.removeItem(DRAFT_STORAGE_KEY);
      } else {
        window.localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
      }
    } catch (_) {
      return;
    }
    updateDraftUI();
  }

  function clearDraft(options = {}) {
    try {
      window.localStorage.removeItem(DRAFT_STORAGE_KEY);
    } catch (_) {
      // Ignore storage cleanup issues.
    }
    updateDraftUI();
    if (options.announce) {
      showStatus(
        draftStatus,
        localeText("本地草稿已清空，当前表单内容保持不变。", "Saved browser draft cleared. The current form stays as-is."),
        "success",
      );
    } else {
      showStatus(draftStatus, "");
    }
  }

  function applyDraft(draft) {
    const normalizedDraft = pruneDraft(draft);
    if (!hasDraft(normalizedDraft)) {
      return false;
    }
    Array.from(form.elements).forEach((element) => {
      if (!(element instanceof HTMLElement)) {
        return;
      }
      const name = element.getAttribute("name");
      if (!name || !(name in normalizedDraft)) {
        return;
      }
      if (element instanceof HTMLInputElement && element.type === "checkbox") {
        element.checked = String(normalizedDraft[name] || "").trim().toLowerCase() === "1";
        return;
      }
      if ("value" in element) {
        element.value = String(normalizedDraft[name] ?? "");
      }
    });
    return true;
  }

  function restoreDraftIfAllowed() {
    updateDraftUI();
    if (form.dataset.restoreDraft !== "true") {
      return false;
    }
    const draft = loadDraft();
    if (!applyDraft(draft)) {
      return false;
    }
    showStatus(
      draftStatus,
      localeText("已恢复这台浏览器里上次没提交完的 loop 草稿。", "Restored the unfinished loop draft saved in this browser."),
      "success",
    );
    return true;
  }

  async function runAction(button, action, options) {
    const {errorTarget, fallbackMessage} = options;
    setButtonBusy(button, true);
    try {
      await action();
    } catch (error) {
      showStatus(errorTarget, errorMessage(error, fallbackMessage), "error");
    } finally {
      setButtonBusy(button, false);
    }
  }

  function selectedExecutorProfile() {
    return executorProfiles.find((profile) => profile.key === executorKindInput.value) || executorProfiles[0];
  }

  function currentOrchestration() {
    return orchestrations.find((item) => item.id === orchestrationInput.value) || orchestrations[0] || null;
  }

  function orchestrationHasFinishGate(orchestration) {
    const workflow = orchestration?.workflow_json || {};
    const roleById = Object.fromEntries((Array.isArray(workflow.roles) ? workflow.roles : []).map((role) => [role.id, role]));
    return (Array.isArray(workflow.steps) ? workflow.steps : []).some((step) => {
      if (step.enabled === false) {
        return false;
      }
      const role = roleById[step.role_id];
      return role?.archetype === "gatekeeper" && String(step.on_pass || "continue") === "finish_run";
    });
  }

  function renderOrchestrationSummary() {
    const selected = currentOrchestration();
    if (!selected) {
      showStatus(orchestrationSummary, localeText("还没有可用的编排方案，请先去“流程编排”里创建。", "No orchestration is available yet. Create one from the Orchestrations page."), "error");
      return;
    }
    const workflow = selected.workflow_json || {};
    const roles = Array.isArray(workflow.roles) ? workflow.roles.length : 0;
    const steps = Array.isArray(workflow.steps) ? workflow.steps.length : 0;
    const finishGate = orchestrationHasFinishGate(selected);
    const source = selected.source === "builtin"
      ? localeText("内置方案", "Built-in")
      : localeText("自定义方案", "Custom");
    const completionMode = completionModeInput?.value || "gatekeeper";
    if (completionMode === "gatekeeper" && !finishGate) {
      showStatus(
        orchestrationSummary,
        localeText(
          `当前方案是 ${selected.name} · ${source} · 角色 ${roles} · 步骤 ${steps}，但它没有“通过即结束”的 GateKeeper 步骤。请改成轮次模式，或先去编排页补一个 GateKeeper finish step。`,
          `The selected orchestration is ${selected.name} · ${source} · Roles ${roles} · Steps ${steps}, but it has no finish-on-pass GateKeeper step. Switch the loop to round-based mode, or add a GateKeeper finish step first.`,
        ),
        "warning",
      );
      return;
    }
    showStatus(
      orchestrationSummary,
      `${selected.name} · ${source} · ${localeText("角色", "Roles")} ${roles} · ${localeText("步骤", "Steps")} ${steps}${selected.description ? ` · ${selected.description}` : ""}`,
      "success",
    );
  }

  function parseCommandArgsText(value) {
    return String(value || "")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
  }

  function defaultCommandArgsText(profile) {
    return Array.isArray(profile?.command_args_template) ? profile.command_args_template.join("\n") : "";
  }

  function shellQuote(arg) {
    const value = String(arg ?? "");
    if (!value) {
      return "''";
    }
    if (/^[A-Za-z0-9_./:=+,@%-]+$/.test(value)) {
      return value;
    }
    return `'${value.replaceAll("'", `'\"'\"'`)}'`;
  }

  function replacePreviewPlaceholders(value) {
    const replacements = {
      "{workdir}": workdirInput.value.trim() || "<workdir>",
      "{schema_path}": "<run_dir>/<role>_schema.json",
      "{output_path}": "<run_dir>/<role>_output.json",
      "{json_schema}": "<json schema>",
      "{sandbox}": "<sandbox-per-role>",
      "{prompt}": "<role prompt>",
      "{model}": modelInput.value.trim() || "<model>",
      "{reasoning_effort}": reasoningInput.value.trim() || "<reasoning>",
    };
    let output = String(value || "");
    Object.entries(replacements).forEach(([placeholder, replacement]) => {
      output = output.replaceAll(placeholder, replacement);
    });
    return output;
  }

  function presetPreviewArgs(profile) {
    const model = modelInput.value.trim() || profile.default_model || "";
    const reasoningEffort = reasoningInput.value.trim() || profile.effort_default || "";
    if (profile.key === "codex") {
      return [
        profile.cli_name,
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--cd",
        workdirInput.value.trim() || "{workdir}",
        "--sandbox",
        "{sandbox}",
        "--output-schema",
        "{schema_path}",
        "--output-last-message",
        "{output_path}",
        "--model",
        model || "<model>",
        "-c",
        `model_reasoning_effort="${reasoningEffort || profile.effort_default}"`,
        "{prompt}",
      ];
    }
    if (profile.key === "claude") {
      const args = [
        profile.cli_name,
        "-p",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--no-session-persistence",
        "--permission-mode",
        "bypassPermissions",
        "--json-schema",
        "{json_schema}",
      ];
      if (model) {
        args.push("--model", model);
      }
      if (reasoningEffort) {
        args.push("--effort", reasoningEffort);
      }
      args.push("{prompt}");
      return args;
    }
    const args = [
      profile.cli_name,
      "run",
      "--format",
      "json",
      "--dir",
      workdirInput.value.trim() || "{workdir}",
      "--dangerously-skip-permissions",
    ];
    if (model) {
      args.push("--model", model);
    }
    if (reasoningEffort) {
      args.push("--variant", reasoningEffort);
    }
    args.push("{prompt}");
    return args;
  }

  function buildPresetCommandSnapshot(profile) {
    const args = presetPreviewArgs(profile);
    return {cli: args[0] || profile.cli_name, argsText: args.slice(1).join("\n")};
  }

  function renderCommandPreview() {
    const profile = selectedExecutorProfile();
    const isCommandMode = executorModeInput.value === "command";
    const argv = [
      commandCliInput.value.trim() || profile.cli_name,
      ...parseCommandArgsText(commandArgsInput.value).map(replacePreviewPlaceholders),
    ];
    commandPreview.textContent = argv.map(shellQuote).join(" ");
    setBilingualHtml(
      commandPreviewNote,
      isCommandMode
        ? "这里展示 raw command 模式下会执行的参数。尖括号内容表示运行时才会替换的动态值。"
        : "这里展示预设模式下自动拼出来的命令参数。你改动模型或推理强度时，下面的命令区会同步刷新，但保持只读。",
      isCommandMode
        ? "This shows the argv used in command mode. Angle-bracket values are filled in only at runtime."
        : "This shows the command assembled from the preset settings. When you change the model or reasoning option, the command block below updates automatically but stays read-only.",
    );
  }

  function saveCommandDraft(profileKey = lastExecutorKind) {
    if (!profileKey) {
      return;
    }
    commandDrafts.set(profileKey, {cli: commandCliInput.value, args: commandArgsInput.value});
  }

  function loadCommandDraft(profile) {
    const saved = commandDrafts.get(profile.key);
    if (saved) {
      commandCliInput.value = saved.cli || profile.cli_name || "";
      commandArgsInput.value = saved.args || defaultCommandArgsText(profile);
      return;
    }
    if (commandCliInput.value.trim() || commandArgsInput.value.trim()) {
      return;
    }
    commandCliInput.value = profile.cli_name || "";
    commandArgsInput.value = defaultCommandArgsText(profile);
  }

  function renderEffortOptions(profile, currentValue = "") {
    reasoningInput.innerHTML = "";
    const options = profile.preset_effort_visible ? profile.effort_options : [];
    options.forEach((option) => {
      const item = document.createElement("option");
      item.value = option;
      item.textContent = (!option && profile.effort_optional) ? localeText("默认", "Default") : option;
      reasoningInput.appendChild(item);
    });
    const fallback = profile.effort_default || "";
    const nextValue = options.includes(currentValue) ? currentValue : fallback;
    reasoningInput.value = options.length ? nextValue : fallback;
  }

  function syncCommandBlock(profile) {
    const isCommandMode = executorModeInput.value === "command";
    const presetSnapshot = buildPresetCommandSnapshot(profile);
    if (isCommandMode) {
      loadCommandDraft(profile);
      commandCliInput.readOnly = false;
      commandArgsInput.readOnly = false;
    } else {
      commandCliInput.value = presetSnapshot.cli;
      commandArgsInput.value = presetSnapshot.argsText;
      commandCliInput.readOnly = true;
      commandArgsInput.readOnly = true;
    }
  }

  function syncExecutorModeUI() {
    const isCommandMode = executorModeInput.value === "command";
    const profile = selectedExecutorProfile();
    presetConfigCard.classList.toggle("is-active", !isCommandMode);
    presetConfigCard.classList.toggle("is-inactive", isCommandMode);
    commandConfigCard.classList.toggle("is-active", isCommandMode);
    commandConfigCard.classList.toggle("is-inactive", !isCommandMode);
    presetConfigCard.setAttribute("aria-disabled", String(isCommandMode));
    commandConfigCard.setAttribute("aria-disabled", String(!isCommandMode));
    presetConfigState.hidden = isCommandMode;
    commandConfigState.hidden = !isCommandMode;

    presetModelField.hidden = false;
    presetEffortField.hidden = !profile.preset_effort_visible;
    commandCliField.hidden = false;
    commandArgsField.hidden = false;
    modelInput.readOnly = isCommandMode;
    reasoningInput.disabled = isCommandMode || !profile.preset_effort_visible;
    syncCommandBlock(profile);
    renderCommandPreview();
  }

  function refreshExecutorFields(options = {}) {
    const preserveUserModel = options.preserveUserModel !== false;
    const preserveUserEffort = options.preserveUserEffort !== false;
    const profile = selectedExecutorProfile();
    if (!profile) {
      return;
    }

    const previousModelDefault = modelInput.dataset.defaultModel || "";
    const previousEffortDefault = reasoningInput.dataset.defaultEffort || "";
    const modelWasDefault = !modelInput.value.trim() || modelInput.value.trim() === previousModelDefault;
    const effortWasDefault = !reasoningInput.value.trim() || reasoningInput.value.trim() === previousEffortDefault;

    modelInput.dataset.placeholderZh = profile.model_placeholder_zh;
    modelInput.dataset.placeholderEn = profile.model_placeholder_en;
    modelHelpTrigger.dataset.titleZh = profile.model_help_zh;
    modelHelpTrigger.dataset.titleEn = profile.model_help_en;
    setBilingualHtml(modelFieldLabel, "模型", "Model");
    setBilingualHtml(effortFieldLabel, profile.effort_label_zh, profile.effort_label_en);
    effortHelpTrigger.dataset.titleZh = profile.effort_help_zh;
    effortHelpTrigger.dataset.titleEn = profile.effort_help_en;
    window.LooporaUI.applyLocalizedAttributes(form);
    setBilingualHtml(modelFieldNote, profile.model_help_zh, profile.model_help_en);
    setBilingualHtml(effortFieldNote, profile.effort_help_zh, profile.effort_help_en);

    const nextEffort = (!preserveUserEffort || effortWasDefault) ? (profile.effort_default || "") : reasoningInput.value;
    renderEffortOptions(profile, nextEffort);
    if ((!preserveUserModel || modelWasDefault) && profile.default_model !== undefined) {
      modelInput.value = profile.default_model;
    }
    modelInput.dataset.defaultModel = profile.default_model || "";
    reasoningInput.dataset.defaultEffort = profile.effort_default || "";
    syncExecutorModeUI();
  }

  function parseNumber(value, fallback) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  async function fetchJson(url, options = {}) {
    try {
      const response = await fetch(url, options);
      const payload = await response.json().catch(() => ({}));
      return {response, payload, error: null};
    } catch (error) {
      return {response: null, payload: {}, error};
    }
  }

  async function validateSpec(options = {}) {
    const quiet = options.quiet ?? false;
    const path = specPathInput.value.trim();
    const requestId = ++latestSpecValidationRequest;
    if (!path) {
      if (quiet) {
        showStatus(specValidation, "");
      } else {
        showStatus(specValidation, localeText("请先提供 spec 路径。", "Please provide a spec path first."), "error");
      }
      return false;
    }
    if (!quiet) {
      showStatus(specValidation, localeText("正在校验 Spec…", "Validating spec..."));
    }
    const {response, payload, error} = await fetchJson(`/api/specs/validate?path=${encodeURIComponent(path)}`);
    if (requestId !== latestSpecValidationRequest) {
      return false;
    }
    if (error || !response) {
      if (!quiet) {
        showStatus(specValidation, errorMessage(error, localeText("Spec 校验暂时不可用。", "Spec validation is temporarily unavailable.")), "error");
      }
      return false;
    }
    if (payload.ok) {
      const modeMessage = payload.check_mode === "auto_generated"
        ? localeText("未提供显式 checks，run 开始时会自动生成并冻结。", "No explicit checks provided. Loopora will generate and freeze them at run start.")
        : localeText(`识别到 ${payload.check_count} 个显式 checks。`, `Detected ${payload.check_count} explicit check(s).`);
      showStatus(specValidation, `${localeText("Spec 校验通过。", "Spec is valid.")} ${modeMessage}`, "success");
      specPathInput.value = payload.path;
      saveDraft();
      renderCommandPreview();
      return true;
    }
    if (!quiet) {
      showStatus(specValidation, payload.error || localeText("Spec 校验失败。", "Spec validation failed."), "error");
    }
    return false;
  }

  async function browseWorkdir() {
    const {response, payload, error} = await fetchJson(`/api/system/pick-directory?start_path=${encodeURIComponent(workdirInput.value.trim())}`);
    if (error || !response?.ok) {
      throw new Error(payload.error || errorMessage(error, localeText("无法打开目录选择器。", "Unable to open the directory picker.")));
    }
    if (payload.path) {
      workdirInput.value = payload.path;
      saveDraft();
      renderCommandPreview();
    }
  }

  async function browseSpec() {
    const startPath = specPathInput.value.trim() || workdirInput.value.trim();
    const {response, payload, error} = await fetchJson(`/api/system/pick-spec-file?start_path=${encodeURIComponent(startPath)}`);
    if (error || !response?.ok) {
      throw new Error(payload.error || errorMessage(error, localeText("无法打开 spec 选择器。", "Unable to open the spec picker.")));
    }
    if (payload.path) {
      specPathInput.value = payload.path;
      await validateSpec();
    }
  }

  async function createSpecTemplate() {
    let targetPath = specPathInput.value.trim();
    if (!targetPath) {
      if (createSpecTemplateButton.dataset.nativeDialogsEnabled === "false") {
        showStatus(specValidation, localeText("网络模式下请先手动填好服务端上的 spec 路径，再创建模版。", "In network mode, enter a server-side spec path first and then create the template."), "error");
        return;
      }
      const startPath = workdirInput.value.trim();
      const selection = await fetchJson(`/api/system/pick-spec-save-path?start_path=${encodeURIComponent(startPath)}`);
      if (selection.error || !selection.response?.ok) {
        throw new Error(selection.payload.error || errorMessage(selection.error, localeText("无法选择 spec 保存路径。", "Unable to choose a spec save path.")));
      }
      if (!selection.payload.path) {
        return;
      }
      targetPath = selection.payload.path;
    }

    const {response, payload, error} = await fetchJson("/api/specs/init", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path: targetPath, locale: window.LooporaUI.currentLocale()}),
    });
    if (error || !response) {
      throw new Error(errorMessage(error, localeText("无法创建 spec 模版。", "Unable to create the spec template.")));
    }
    if (!response.ok) {
      showStatus(specValidation, payload.error || localeText("无法创建 spec 模版。", "Unable to create the spec template."), "error");
      return;
    }
    specPathInput.value = payload.path;
    await validateSpec();
  }

  async function submitForm(event) {
    event.preventDefault();
    if (!form.reportValidity()) {
      return;
    }
    showStatus(formError, "");
    if (!currentOrchestration()) {
      showStatus(formError, localeText("请先选择一个流程编排。", "Choose an orchestration first."), "error");
      return;
    }
    const specValid = await validateSpec();
    if (!specValid) {
      showStatus(formError, localeText("Spec 不满足要求，请先修复后再提交。", "The spec does not satisfy the required structure yet."), "error");
      return;
    }

    const formData = new FormData(form);
    const executorMode = String(formData.get("executor_mode") || "preset").trim();
    const roleModels = Object.fromEntries(
      Object.entries(roleModelInputs).map(([role, input]) => [role, String(input?.value || "").trim()]).filter(([, value]) => value),
    );
    const payload = {
      name: String(formData.get("name") || "").trim(),
      workdir: String(formData.get("workdir") || "").trim(),
      spec_path: String(formData.get("spec_path") || "").trim(),
      orchestration_id: String(formData.get("orchestration_id") || "").trim(),
      executor_kind: String(formData.get("executor_kind") || "codex").trim(),
      executor_mode: executorMode,
      command_cli: executorMode === "command" ? String(formData.get("command_cli") || "").trim() : "",
      command_args_text: executorMode === "command" ? String(formData.get("command_args_text") || "") : "",
      model: String(modelInput.value || "").trim(),
      reasoning_effort: String(reasoningInput.value || "").trim(),
      completion_mode: String(formData.get("completion_mode") || "gatekeeper").trim(),
      iteration_interval_seconds: parseNumber(formData.get("iteration_interval_seconds"), 0),
      max_iters: parseNumber(formData.get("max_iters"), 8),
      max_role_retries: parseNumber(formData.get("max_role_retries"), 2),
      delta_threshold: parseNumber(formData.get("delta_threshold"), 0.005),
      trigger_window: parseNumber(formData.get("trigger_window"), 4),
      regression_window: parseNumber(formData.get("regression_window"), 2),
      role_models: roleModels,
      start_immediately: formData.get("start_immediately") === "1",
    };

    setButtonBusy(saveLoopButton, true);
    try {
      const {response, payload: responsePayload, error} = await fetchJson("/api/loops", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      if (error || !response) {
        showStatus(formError, errorMessage(error, localeText("保存 loop 失败。", "Unable to save the loop.")), "error");
        return;
      }
      if (!response.ok) {
        showStatus(formError, responsePayload.error || localeText("保存 loop 失败。", "Unable to save the loop."), "error");
        return;
      }
      clearDraft();
      window.location.href = responsePayload.redirect_url || "/";
    } finally {
      setButtonBusy(saveLoopButton, false);
    }
  }

  if (browseWorkdirButton && !browseWorkdirButton.disabled) {
    browseWorkdirButton.addEventListener("click", () => runAction(
      browseWorkdirButton,
      browseWorkdir,
      {
        errorTarget: formError,
        fallbackMessage: localeText("无法打开目录选择器。", "Unable to open the directory picker."),
      },
    ));
  }
  if (browseSpecButton && !browseSpecButton.disabled) {
    browseSpecButton.addEventListener("click", () => runAction(
      browseSpecButton,
      browseSpec,
      {
        errorTarget: specValidation,
        fallbackMessage: localeText("无法打开 spec 选择器。", "Unable to open the spec picker."),
      },
    ));
  }
  if (createSpecTemplateButton) {
    createSpecTemplateButton.addEventListener("click", () => runAction(
      createSpecTemplateButton,
      createSpecTemplate,
      {
        errorTarget: specValidation,
        fallbackMessage: localeText("无法创建 spec 模版。", "Unable to create the spec template."),
      },
    ));
  }
  if (clearDraftButton) {
    clearDraftButton.addEventListener("click", () => clearDraft({announce: true}));
  }
  workdirQuickPickButtons.forEach((button) => {
    button.addEventListener("click", () => {
      workdirInput.value = button.dataset.fillWorkdir || "";
      saveDraft();
      renderCommandPreview();
      showStatus(formError, "");
    });
  });
  orchestrationInput?.addEventListener("change", renderOrchestrationSummary);
  completionModeInput?.addEventListener("change", renderOrchestrationSummary);
  iterationIntervalInput?.addEventListener("input", saveDraft);
  executorKindInput.addEventListener("change", () => {
    if (executorModeInput.value === "command") {
      saveCommandDraft(lastExecutorKind);
    }
    lastExecutorKind = executorKindInput.value;
    refreshExecutorFields({preserveUserModel: true, preserveUserEffort: true});
    saveDraft();
  });
  executorModeInput.addEventListener("change", () => {
    if (executorModeInput.value === "preset") {
      saveCommandDraft(selectedExecutorProfile().key);
    }
    syncExecutorModeUI();
    saveDraft();
  });
  specPathInput.addEventListener("change", () => validateSpec({quiet: false}));
  specPathInput.addEventListener("blur", () => validateSpec({quiet: true}));
  workdirInput.addEventListener("input", () => {
    syncExecutorModeUI();
    saveDraft();
  });
  modelInput.addEventListener("input", () => {
    syncExecutorModeUI();
    saveDraft();
  });
  reasoningInput.addEventListener("change", () => syncExecutorModeUI());
  commandCliInput.addEventListener("input", () => {
    if (executorModeInput.value === "command") {
      saveCommandDraft(selectedExecutorProfile().key);
    }
    renderCommandPreview();
    saveDraft();
  });
  commandArgsInput.addEventListener("input", () => {
    if (executorModeInput.value === "command") {
      saveCommandDraft(selectedExecutorProfile().key);
    }
    renderCommandPreview();
    saveDraft();
  });
  form.addEventListener("input", saveDraft);
  form.addEventListener("change", saveDraft);
  form.addEventListener("submit", submitForm);
  document.addEventListener("loopora:localechange", () => {
    refreshExecutorFields({preserveUserModel: true, preserveUserEffort: true});
    renderOrchestrationSummary();
  });

  const restoredDraft = restoreDraftIfAllowed();
  refreshExecutorFields({preserveUserModel: true, preserveUserEffort: true});
  renderOrchestrationSummary();
  if (specPathInput.value.trim()) {
    validateSpec({quiet: true});
  } else {
    renderCommandPreview();
  }
  if (restoredDraft) {
    saveDraft();
  } else {
    updateDraftUI();
  }
});
