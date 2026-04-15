document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("new-loop-form");
  if (!form || !window.LiminalUI) {
    return;
  }

  const workdirInput = document.getElementById("workdir-input");
  const specPathInput = document.getElementById("spec-path-input");
  const orchestrationInput = document.getElementById("orchestration-id-input");
  const orchestrationSummary = document.getElementById("orchestration-summary");
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
  const specValidation = document.getElementById("spec-validation");
  const executorProfiles = JSON.parse(document.getElementById("executor-profiles-json")?.textContent || "[]");
  const orchestrations = JSON.parse(document.getElementById("orchestrations-json")?.textContent || "[]");
  const roleModelInputs = {
    builder: document.getElementById("role-model-builder-input"),
    inspector: document.getElementById("role-model-inspector-input"),
    gatekeeper: document.getElementById("role-model-gatekeeper-input"),
    guide: document.getElementById("role-model-guide-input"),
  };

  const commandDrafts = new Map();
  let lastExecutorKind = executorKindInput.value;

  function localeText(zh, en) {
    return window.LiminalUI.pickText({zh, en});
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

  function selectedExecutorProfile() {
    return executorProfiles.find((profile) => profile.key === executorKindInput.value) || executorProfiles[0];
  }

  function currentOrchestration() {
    return orchestrations.find((item) => item.id === orchestrationInput.value) || orchestrations[0] || null;
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
    const source = selected.source === "builtin"
      ? localeText("内置方案", "Built-in")
      : localeText("自定义方案", "Custom");
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
    window.LiminalUI.applyLocalizedAttributes(form);
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
    const response = await fetch(url, options);
    const payload = await response.json().catch(() => ({}));
    return {response, payload};
  }

  async function validateSpec(options = {}) {
    const quiet = options.quiet ?? false;
    const path = specPathInput.value.trim();
    if (!path) {
      if (!quiet) {
        showStatus(specValidation, localeText("请先提供 spec 路径。", "Please provide a spec path first."), "error");
      }
      return false;
    }
    const {payload} = await fetchJson(`/api/specs/validate?path=${encodeURIComponent(path)}`);
    if (payload.ok) {
      const modeMessage = payload.check_mode === "auto_generated"
        ? localeText("未提供显式 checks，run 开始时会自动生成并冻结。", "No explicit checks provided. Liminal will generate and freeze them at run start.")
        : localeText(`识别到 ${payload.check_count} 个显式 checks。`, `Detected ${payload.check_count} explicit check(s).`);
      showStatus(specValidation, `${localeText("Spec 校验通过。", "Spec is valid.")} ${modeMessage}`, "success");
      specPathInput.value = payload.path;
      renderCommandPreview();
      return true;
    }
    if (!quiet) {
      showStatus(specValidation, payload.error || localeText("Spec 校验失败。", "Spec validation failed."), "error");
    }
    return false;
  }

  async function browseWorkdir() {
    const {payload} = await fetchJson(`/api/system/pick-directory?start_path=${encodeURIComponent(workdirInput.value.trim())}`);
    if (payload.path) {
      workdirInput.value = payload.path;
      renderCommandPreview();
    }
  }

  async function browseSpec() {
    const startPath = specPathInput.value.trim() || workdirInput.value.trim();
    const {payload} = await fetchJson(`/api/system/pick-spec-file?start_path=${encodeURIComponent(startPath)}`);
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
      if (!selection.payload.path) {
        return;
      }
      targetPath = selection.payload.path;
    }

    const {response, payload} = await fetchJson("/api/specs/init", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path: targetPath, locale: window.LiminalUI.currentLocale()}),
    });
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
      max_iters: parseNumber(formData.get("max_iters"), 8),
      max_role_retries: parseNumber(formData.get("max_role_retries"), 2),
      delta_threshold: parseNumber(formData.get("delta_threshold"), 0.005),
      trigger_window: parseNumber(formData.get("trigger_window"), 4),
      regression_window: parseNumber(formData.get("regression_window"), 2),
      role_models: roleModels,
      start_immediately: formData.get("start_immediately") === "1",
    };

    saveLoopButton.disabled = true;
    try {
      const {response, payload: responsePayload} = await fetchJson("/api/loops", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        showStatus(formError, responsePayload.error || localeText("保存 loop 失败。", "Unable to save the loop."), "error");
        return;
      }
      window.location.href = responsePayload.redirect_url || "/";
    } finally {
      saveLoopButton.disabled = false;
    }
  }

  if (browseWorkdirButton && !browseWorkdirButton.disabled) {
    browseWorkdirButton.addEventListener("click", browseWorkdir);
  }
  if (browseSpecButton && !browseSpecButton.disabled) {
    browseSpecButton.addEventListener("click", browseSpec);
  }
  if (createSpecTemplateButton) {
    createSpecTemplateButton.addEventListener("click", createSpecTemplate);
  }
  orchestrationInput?.addEventListener("change", renderOrchestrationSummary);
  executorKindInput.addEventListener("change", () => {
    if (executorModeInput.value === "command") {
      saveCommandDraft(lastExecutorKind);
    }
    lastExecutorKind = executorKindInput.value;
    refreshExecutorFields({preserveUserModel: true, preserveUserEffort: true});
  });
  executorModeInput.addEventListener("change", () => {
    if (executorModeInput.value === "preset") {
      saveCommandDraft(selectedExecutorProfile().key);
    }
    syncExecutorModeUI();
  });
  specPathInput.addEventListener("change", () => validateSpec({quiet: false}));
  specPathInput.addEventListener("blur", () => validateSpec({quiet: true}));
  workdirInput.addEventListener("input", syncExecutorModeUI);
  modelInput.addEventListener("input", () => syncExecutorModeUI());
  reasoningInput.addEventListener("change", () => syncExecutorModeUI());
  commandCliInput.addEventListener("input", () => {
    if (executorModeInput.value === "command") {
      saveCommandDraft(selectedExecutorProfile().key);
    }
    renderCommandPreview();
  });
  commandArgsInput.addEventListener("input", () => {
    if (executorModeInput.value === "command") {
      saveCommandDraft(selectedExecutorProfile().key);
    }
    renderCommandPreview();
  });
  form.addEventListener("submit", submitForm);
  document.addEventListener("liminal:localechange", () => {
    refreshExecutorFields({preserveUserModel: true, preserveUserEffort: true});
    renderOrchestrationSummary();
  });

  refreshExecutorFields({preserveUserModel: true, preserveUserEffort: true});
  renderOrchestrationSummary();
  if (specPathInput.value.trim()) {
    validateSpec({quiet: true});
  } else {
    renderCommandPreview();
  }
});
