document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("new-loop-form");
  if (!form || !window.LiminalUI) {
    return;
  }

  const workdirInput = document.getElementById("workdir-input");
  const specPathInput = document.getElementById("spec-path-input");
  const executorKindInput = document.getElementById("executor-kind-input");
  const executorModeInput = document.getElementById("executor-mode-input");
  const modelFieldLabel = document.getElementById("model-field-label");
  const effortFieldLabel = document.getElementById("effort-field-label");
  const modelInput = document.getElementById("model-input");
  const reasoningInput = document.getElementById("reasoning-input");
  const reasoningSuggestions = document.getElementById("reasoning-effort-suggestions");
  const modelHelpTrigger = document.getElementById("model-help-trigger");
  const effortHelpTrigger = document.getElementById("effort-help-trigger");
  const modelFieldNote = document.getElementById("model-field-note");
  const effortFieldNote = document.getElementById("effort-field-note");
  const presetModelField = document.getElementById("preset-model-field");
  const presetEffortField = document.getElementById("preset-effort-field");
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

  function localeText(zh, en) {
    return window.LiminalUI.pickText({zh, en});
  }

  function setBilingualHtml(element, zh, en) {
    element.innerHTML = `<span data-lang="zh">${zh}</span><span data-lang="en">${en}</span>`;
  }

  function selectedExecutorProfile() {
    return executorProfiles.find((profile) => profile.key === executorKindInput.value) || executorProfiles[0];
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

  function renderCommandPreview() {
    const profile = selectedExecutorProfile();
    const isCommandMode = executorModeInput.value === "command";
    const argv = isCommandMode
      ? [
          commandCliInput.value.trim() || profile.cli_name,
          ...parseCommandArgsText(commandArgsInput.value).map(replacePreviewPlaceholders),
        ]
      : presetPreviewArgs(profile).map(replacePreviewPlaceholders);
    commandPreview.textContent = argv.map(shellQuote).join(" ");
    setBilingualHtml(
      commandPreviewNote,
      isCommandMode
        ? "这里展示 raw command 模式下会执行的参数。尖括号内容表示运行时才会替换的动态值。"
        : "这里展示预设模式下会调用的一条示例命令。尖括号内容表示运行时动态值，不同角色的 prompt、schema 和 sandbox 会自动替换。",
      isCommandMode
        ? "This shows the argv used in command mode. Angle-bracket values are filled in only at runtime."
        : "This shows an example command for preset mode. Angle-bracket values are runtime substitutions such as the role prompt, schema, and sandbox."
    );
  }

  function updateCommandDefaults(profile, options = {}) {
    const preserveUserCommandCli = options.preserveUserCommandCli !== false;
    const preserveUserCommandArgs = options.preserveUserCommandArgs !== false;
    const previousDefaultCli = commandCliInput.dataset.defaultCli || "";
    const previousTemplate = commandArgsInput.dataset.defaultTemplate || "";
    const cliWasDefault = !commandCliInput.value.trim() || commandCliInput.value.trim() === previousDefaultCli;
    const argsWereDefault = !commandArgsInput.value.trim() || commandArgsInput.value.trim() === previousTemplate.trim();
    const nextTemplate = defaultCommandArgsText(profile);

    if (!preserveUserCommandCli || cliWasDefault) {
      commandCliInput.value = profile.cli_name || "";
    }
    if (!preserveUserCommandArgs || argsWereDefault) {
      commandArgsInput.value = nextTemplate;
    }

    commandCliInput.dataset.defaultCli = profile.cli_name || "";
    commandArgsInput.dataset.defaultTemplate = nextTemplate;
  }

  function syncExecutorModeUI() {
    const isCommandMode = executorModeInput.value === "command";
    presetModelField.hidden = isCommandMode;
    presetEffortField.hidden = isCommandMode;
    commandCliField.hidden = !isCommandMode;
    commandArgsField.hidden = !isCommandMode;
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
    reasoningInput.dataset.placeholderZh = profile.effort_optional
      ? "留空使用默认 variant"
      : profile.effort_default;
    reasoningInput.dataset.placeholderEn = profile.effort_optional
      ? "Leave blank for the default variant"
      : profile.effort_default;
    window.LiminalUI.applyLocalizedAttributes(form);

    setBilingualHtml(modelFieldNote, profile.model_help_zh, profile.model_help_en);
    setBilingualHtml(effortFieldNote, profile.effort_help_zh, profile.effort_help_en);

    reasoningSuggestions.innerHTML = "";
    profile.effort_options.forEach((option) => {
      if (!option) {
        return;
      }
      const item = document.createElement("option");
      item.value = option;
      reasoningSuggestions.appendChild(item);
    });

    if ((!preserveUserModel || modelWasDefault) && profile.default_model !== undefined) {
      modelInput.value = profile.default_model;
    }
    if (!preserveUserEffort || effortWasDefault) {
      reasoningInput.value = profile.effort_default || "";
    }
    modelInput.dataset.defaultModel = profile.default_model || "";
    reasoningInput.dataset.defaultEffort = profile.effort_default || "";

    updateCommandDefaults(profile, options);
    syncExecutorModeUI();
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
      const modeMessage = payload.check_mode === "auto_generate"
        ? localeText("未提供显式 checks，run 开始时会自动生成并冻结。", "No explicit checks provided. Liminal will generate and freeze them at run start.")
        : localeText(`识别到 ${payload.check_count} 个显式 checks。`, `Detected ${payload.check_count} explicit check(s).`);
      showStatus(
        specValidation,
        `${localeText("Spec 校验通过。", "Spec is valid.")} ${modeMessage}`,
        "success",
      );
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
    const specValid = await validateSpec();
    if (!specValid) {
      showStatus(formError, localeText("Spec 不满足要求，请先修复后再提交。", "The spec does not satisfy the required structure yet."), "error");
      return;
    }

    const formData = new FormData(form);
    const executorMode = String(formData.get("executor_mode") || "preset").trim();
    const payload = {
      name: String(formData.get("name") || "").trim(),
      workdir: String(formData.get("workdir") || "").trim(),
      spec_path: String(formData.get("spec_path") || "").trim(),
      executor_kind: String(formData.get("executor_kind") || "codex").trim(),
      executor_mode: executorMode,
      command_cli: executorMode === "command" ? String(formData.get("command_cli") || "").trim() : "",
      command_args_text: executorMode === "command" ? String(formData.get("command_args_text") || "") : "",
      model: executorMode === "preset" ? String(formData.get("model") || "").trim() : "",
      reasoning_effort: executorMode === "preset" ? String(formData.get("reasoning_effort") || "").trim() : "",
      max_iters: parseNumber(formData.get("max_iters"), 8),
      max_role_retries: parseNumber(formData.get("max_role_retries"), 2),
      delta_threshold: parseNumber(formData.get("delta_threshold"), 0.005),
      trigger_window: parseNumber(formData.get("trigger_window"), 4),
      regression_window: parseNumber(formData.get("regression_window"), 2),
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

  browseWorkdirButton.addEventListener("click", browseWorkdir);
  browseSpecButton.addEventListener("click", browseSpec);
  createSpecTemplateButton.addEventListener("click", createSpecTemplate);
  executorKindInput.addEventListener("change", () => refreshExecutorFields({
    preserveUserModel: true,
    preserveUserEffort: true,
    preserveUserCommandCli: true,
    preserveUserCommandArgs: true,
  }));
  executorModeInput.addEventListener("change", syncExecutorModeUI);
  specPathInput.addEventListener("change", () => validateSpec({quiet: false}));
  specPathInput.addEventListener("blur", () => validateSpec({quiet: true}));
  workdirInput.addEventListener("input", renderCommandPreview);
  modelInput.addEventListener("input", renderCommandPreview);
  reasoningInput.addEventListener("input", renderCommandPreview);
  commandCliInput.addEventListener("input", renderCommandPreview);
  commandArgsInput.addEventListener("input", renderCommandPreview);
  form.addEventListener("submit", submitForm);
  document.addEventListener("liminal:localechange", () => refreshExecutorFields({
    preserveUserModel: true,
    preserveUserEffort: true,
    preserveUserCommandCli: true,
    preserveUserCommandArgs: true,
  }));

  refreshExecutorFields({
    preserveUserModel: true,
    preserveUserEffort: true,
    preserveUserCommandCli: true,
    preserveUserCommandArgs: true,
  });

  if (specPathInput.value.trim()) {
    validateSpec({quiet: true});
  } else {
    renderCommandPreview();
  }
});
