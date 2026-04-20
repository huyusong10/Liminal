document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("[data-testid='role-definition-editor-form']");
  if (!form || !window.LooporaUI) {
    return;
  }

  const profiles = JSON.parse(document.getElementById("role-definition-executor-profiles-json")?.textContent || "[]");
  const builtinTemplates = JSON.parse(document.getElementById("role-definition-builtin-templates-json")?.textContent || "{}");
  const archetypeInput = document.getElementById("role-definition-archetype-input");
  const executorKindInput = document.getElementById("role-definition-executor-kind-input");
  const executorModeInput = document.getElementById("role-definition-executor-mode-input");
  const promptMarkdownInput = document.getElementById("role-definition-prompt-markdown-input");
  const promptMarkdownPreview = document.getElementById("role-definition-prompt-markdown-preview");
  const promptMarkdownPreviewNote = document.getElementById("role-definition-prompt-preview-note");
  const modeNote = document.getElementById("role-definition-mode-note");
  const modeButtons = Array.from(document.querySelectorAll("[data-mode-choice]"));
  const modelInput = document.getElementById("role-definition-model-input");
  const modelFieldLabel = document.getElementById("role-definition-model-field-label");
  const modelNote = document.getElementById("role-definition-model-note");
  const reasoningInput = document.getElementById("role-definition-reasoning-input");
  const reasoningMirrorInput = document.getElementById("role-definition-reasoning-hidden-input");
  const reasoningField = document.getElementById("role-definition-reasoning-field");
  const reasoningFieldLabel = document.getElementById("role-definition-reasoning-field-label");
  const reasoningNote = document.getElementById("role-definition-reasoning-note");
  const presetCard = document.getElementById("role-definition-preset-card");
  const commandCard = document.getElementById("role-definition-command-card");
  const presetState = document.getElementById("role-definition-preset-state");
  const commandState = document.getElementById("role-definition-command-state");
  const presetBody = document.getElementById("role-definition-preset-body");
  const presetEmpty = document.getElementById("role-definition-preset-empty");
  const commandCliInput = document.getElementById("role-definition-command-cli-input");
  const commandCliNote = document.getElementById("role-definition-command-cli-note");
  const commandArgsInput = document.getElementById("role-definition-command-args-input");
  const commandPreview = document.getElementById("role-definition-command-preview");
  const commandPreviewNote = document.getElementById("role-definition-command-preview-note");
  const archetypeSummary = document.getElementById("role-definition-archetype-summary");
  const archetypeRecommendation = document.getElementById("role-definition-archetype-recommendation");
  const archetypeWarning = document.getElementById("role-definition-archetype-warning");

  const commandDrafts = new Map();
  let lastExecutorKind = executorKindInput?.value || "";
  let promptMarkdownWorkbench = null;

  function localeText(zh, en) {
    return window.LooporaUI.pickText({zh, en});
  }

  function setBilingualHtml(element, zh, en) {
    if (!element) {
      return;
    }
    element.innerHTML = `<span data-lang="zh">${zh}</span><span data-lang="en">${en}</span>`;
  }

  function setPromptPreviewNote(kind = "", message = "") {
    if (!promptMarkdownPreviewNote) {
      return;
    }
    promptMarkdownPreviewNote.className = `markdown-workbench-panel-note${kind ? ` is-${kind}` : ""}`;
    if (message) {
      promptMarkdownPreviewNote.textContent = message;
      return;
    }
    setBilingualHtml(
      promptMarkdownPreviewNote,
      "会自动忽略 front matter，只展示 Markdown 正文。",
      "Front matter is ignored here so only the Markdown body is shown.",
    );
  }

  function refreshPromptPreview() {
    promptMarkdownWorkbench?.renderNow().catch(() => {});
  }

  function selectedProfile() {
    return profiles.find((profile) => profile.key === executorKindInput?.value) || profiles[0] || null;
  }

  function currentBuiltinTemplate(archetype) {
    return builtinTemplates[String(archetype || "").trim()] || null;
  }

  function currentArchetypeOption() {
    return archetypeInput?.selectedOptions?.[0] || null;
  }

  function templateMarkdownVariants(template) {
    const variants = new Set();
    if (!template || typeof template !== "object") {
      return variants;
    }
    const localized = template.prompt_markdown_by_locale || {};
    Object.values(localized).forEach((value) => {
      const text = String(value || "").trim();
      if (text) {
        variants.add(text);
      }
    });
    const fallback = String(template.prompt_markdown || "").trim();
    if (fallback) {
      variants.add(fallback);
    }
    return variants;
  }

  function templateMarkdownForLocale(template, locale = window.LooporaUI.currentLocale()) {
    if (!template || typeof template !== "object") {
      return "";
    }
    const localized = template.prompt_markdown_by_locale || {};
    return String(
      localized[locale]
      || localized.en
      || localized.zh
      || template.prompt_markdown
      || "",
    );
  }

  function promptMatchesTemplate(markdown, template) {
    const value = String(markdown || "").trim();
    if (!value) {
      return false;
    }
    return templateMarkdownVariants(template).has(value);
  }

  function canAutoSyncBuiltinPrompt() {
    return form.dataset.builtinPromptSync === "true";
  }

  function localizeArchetypeOptions() {
    const locale = window.LooporaUI.currentLocale();
    Array.from(archetypeInput?.options || []).forEach((option) => {
      const label = locale === "zh" ? option.dataset.labelZh : option.dataset.labelEn;
      option.textContent = label || option.dataset.labelEn || option.dataset.labelZh || option.textContent || "";
    });
  }

  function syncArchetypeGuide() {
    if (!archetypeSummary || !archetypeRecommendation || !archetypeWarning) {
      return;
    }
    const option = currentArchetypeOption();
    if (!option) {
      return;
    }
    const locale = window.LooporaUI.currentLocale();
    const summary = locale === "zh" ? option.dataset.summaryZh : option.dataset.summaryEn;
    const recommendation = locale === "zh" ? option.dataset.recommendationZh : option.dataset.recommendationEn;
    const warning = locale === "zh" ? option.dataset.warningZh : option.dataset.warningEn;
    setBilingualHtml(archetypeSummary, option.dataset.summaryZh || "", option.dataset.summaryEn || "");
    setBilingualHtml(archetypeRecommendation, option.dataset.recommendationZh || "", option.dataset.recommendationEn || "");
    setBilingualHtml(archetypeWarning, option.dataset.warningZh || "", option.dataset.warningEn || "");
    archetypeWarning.hidden = !warning;
  }

  function syncPromptMarkdownForArchetype(nextArchetype, previousArchetype = "", options = {}) {
    if (!canAutoSyncBuiltinPrompt()) {
      return;
    }
    const nextTemplate = currentBuiltinTemplate(nextArchetype);
    if (!nextTemplate) {
      return;
    }
    const previousTemplate = currentBuiltinTemplate(previousArchetype);
    const currentPrompt = String(promptMarkdownInput?.value || "").trim();
    const shouldReplace = options.force
      || !currentPrompt
      || promptMatchesTemplate(currentPrompt, previousTemplate)
      || promptMatchesTemplate(currentPrompt, nextTemplate);
    if (!shouldReplace) {
      return;
    }
    promptMarkdownInput.value = templateMarkdownForLocale(nextTemplate);
    refreshPromptPreview();
  }

  function defaultCommandArgsText(profile) {
    return Array.isArray(profile?.command_args_template) ? profile.command_args_template.join("\n") : "";
  }

  function isCommandMode() {
    const profile = selectedProfile();
    return String(executorModeInput?.value || "preset") === "command" || Boolean(profile?.command_only);
  }

  function syncReasoningMirror() {
    if (reasoningMirrorInput) {
      reasoningMirrorInput.value = reasoningInput?.value || "";
    }
  }

  function parseCommandArgsText(value) {
    return String(value || "")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
  }

  function shellQuote(arg) {
    const value = String(arg ?? "");
    if (!value) {
      return "''";
    }
    if (/^[A-Za-z0-9_./:=+,@%<>{}-]+$/.test(value)) {
      return value;
    }
    return `'${value.replaceAll("'", `'\"'\"'`)}'`;
  }

  function replacePreviewPlaceholders(value) {
    const replacements = {
      "{workdir}": "<workdir>",
      "{schema_path}": "<schema_path>",
      "{output_path}": "<output_path>",
      "{json_schema}": "<json schema>",
      "{sandbox}": "<sandbox>",
      "{prompt}": "<role prompt>",
      "{model}": modelInput?.value.trim() || "<model>",
      "{reasoning_effort}": reasoningMirrorInput?.value.trim() || "<reasoning>",
    };
    let output = String(value || "");
    Object.entries(replacements).forEach(([placeholder, replacement]) => {
      output = output.replaceAll(placeholder, replacement);
    });
    return output;
  }

  function presetPreviewArgs(profile) {
    const model = modelInput?.value.trim() || profile?.default_model || "";
    const reasoningEffort = reasoningMirrorInput?.value.trim() || profile?.effort_default || "";
    if (!profile) {
      return [];
    }
    if (profile.key === "codex") {
      const args = [
        profile.cli_name,
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--cd",
        "<workdir>",
        "--sandbox",
        "<sandbox>",
        "--output-schema",
        "<schema_path>",
        "--output-last-message",
        "<output_path>",
      ];
      if (model) {
        args.push("--model", model);
      }
      args.push("-c", `model_reasoning_effort="${reasoningEffort || profile.effort_default}"`, "<role prompt>");
      return args;
    }
    if (profile.key === "claude") {
      const args = [
        profile.cli_name,
        "--setting-sources",
        "local,project",
        "-p",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--no-session-persistence",
        "--permission-mode",
        "bypassPermissions",
        "--json-schema",
        "<json schema>",
      ];
      if (model) {
        args.push("--model", model);
      }
      if (reasoningEffort) {
        args.push("--effort", reasoningEffort);
      }
      args.push("<role prompt>");
      return args;
    }
    if (profile.key === "opencode") {
      const args = [
        profile.cli_name,
        "run",
        "--format",
        "json",
        "--dir",
        "<workdir>",
        "--dangerously-skip-permissions",
      ];
      if (model) {
        args.push("--model", model);
      }
      if (reasoningEffort) {
        args.push("--variant", reasoningEffort);
      }
      args.push("<role prompt>");
      return args;
    }
    return [];
  }

  function buildPresetCommandSnapshot(profile) {
    const args = presetPreviewArgs(profile);
    if (!args.length) {
      return {cli: "", argsText: ""};
    }
    return {cli: args[0] || "", argsText: args.slice(1).join("\n")};
  }

  function renderCommandPreview() {
    const profile = selectedProfile();
    const commandMode = isCommandMode();
    let argv = [];

    if (commandMode) {
      argv = [
        String(commandCliInput?.value || "").trim() || profile?.cli_name || "<command>",
        ...parseCommandArgsText(commandArgsInput?.value).map(replacePreviewPlaceholders),
      ];
    } else {
      const snapshot = buildPresetCommandSnapshot(profile);
      argv = [
        snapshot.cli || profile?.cli_name || "<command>",
        ...parseCommandArgsText(snapshot.argsText).map(replacePreviewPlaceholders),
      ];
    }

    commandPreview.textContent = argv.length
      ? argv.map(shellQuote).join(" ")
      : localeText("先配置执行命令。", "Configure the execution command first.");

    if (profile?.command_only) {
      setBilingualHtml(
        commandPreviewNote,
        "自定义执行工具只认这里的直接命令。命令结束前，必须把最终 JSON 对象写到 `{output_path}`。",
        "Custom execution tools only use this direct command. Before the process exits, it must write the final JSON object to `{output_path}`.",
      );
      return;
    }

    setBilingualHtml(
      commandPreviewNote,
      commandMode
        ? "这是直接命令模式下的最终 argv 预览。尖括号表示运行时才会替换的值。"
        : "这是预设模式下自动生成的最终命令。你调模型或推理强度时，这里会同步刷新。",
      commandMode
        ? "This is the final argv preview for direct-command mode. Angle-bracket values are only filled at runtime."
        : "This is the final command assembled from preset mode. It refreshes whenever you change the model or reasoning setting.",
    );
  }

  function saveCommandDraft(profileKey = lastExecutorKind) {
    if (!profileKey) {
      return;
    }
    commandDrafts.set(profileKey, {
      cli: commandCliInput?.value || "",
      args: commandArgsInput?.value || "",
    });
  }

  function loadCommandDraft(profile) {
    if (!profile) {
      return;
    }
    const saved = commandDrafts.get(profile.key);
    if (saved) {
      commandCliInput.value = saved.cli || profile.cli_name || "";
      commandArgsInput.value = saved.args || defaultCommandArgsText(profile);
      return;
    }
    if (!commandCliInput.value.trim() || commandCliInput.dataset.autofilled === "true") {
      commandCliInput.value = profile.cli_name || "";
      commandCliInput.dataset.autofilled = "true";
    }
    if (!commandArgsInput.value.trim() || commandArgsInput.dataset.autofilled === "true") {
      commandArgsInput.value = defaultCommandArgsText(profile);
      commandArgsInput.dataset.autofilled = "true";
    }
  }

  function renderEffortOptions(profile, currentValue = "") {
    const options = Array.isArray(profile?.effort_options) && profile.effort_options.length
      ? profile.effort_options
      : [""];
    reasoningInput.innerHTML = "";
    options.forEach((option) => {
      const item = document.createElement("option");
      item.value = option;
      item.textContent = (!option && profile?.effort_optional)
        ? localeText("默认", "Default")
        : option || localeText("默认", "Default");
      reasoningInput.appendChild(item);
    });
    const fallback = profile?.effort_default || options[0] || "";
    reasoningInput.value = options.includes(currentValue) ? currentValue : fallback;
    syncReasoningMirror();
  }

  function setMode(nextMode) {
    const profile = selectedProfile();
    const resolvedMode = profile?.command_only ? "command" : nextMode;
    if (executorModeInput) {
      executorModeInput.value = resolvedMode;
    }
    syncModeUI();
  }

  function syncModeButtons(profile) {
    const activeMode = String(executorModeInput?.value || "preset");
    modeButtons.forEach((button) => {
      const mode = button.dataset.modeChoice || "";
      const isActive = mode === activeMode;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-pressed", String(isActive));
      if (mode === "preset") {
        button.disabled = Boolean(profile?.command_only);
      }
    });
  }

  function syncCommandBlock(profile) {
    if (!profile) {
      return;
    }
    const commandMode = isCommandMode();
    const presetSnapshot = buildPresetCommandSnapshot(profile);
    if (commandMode) {
      loadCommandDraft(profile);
      commandCliInput.readOnly = false;
      commandArgsInput.readOnly = false;
      return;
    }
    commandCliInput.value = presetSnapshot.cli || profile.cli_name || "";
    commandArgsInput.value = presetSnapshot.argsText;
    commandCliInput.readOnly = true;
    commandArgsInput.readOnly = true;
  }

  function syncModeUI() {
    const profile = selectedProfile();
    if (!profile) {
      return;
    }
    if (profile.command_only && executorModeInput.value !== "command") {
      executorModeInput.value = "command";
    }
    const commandMode = isCommandMode();

    syncModeButtons(profile);
    presetCard.classList.toggle("is-active", !commandMode && !profile.command_only);
    presetCard.classList.toggle("is-inactive", commandMode || profile.command_only);
    commandCard.classList.toggle("is-active", commandMode);
    commandCard.classList.toggle("is-inactive", !commandMode);
    presetState.hidden = commandMode || profile.command_only;
    commandState.hidden = !commandMode;

    presetBody.hidden = Boolean(profile.command_only);
    presetEmpty.hidden = !profile.command_only;
    reasoningField.hidden = Boolean(profile.command_only);

    modelInput.readOnly = commandMode;
    reasoningInput.disabled = commandMode || profile.command_only;

    if (profile.command_only) {
      setBilingualHtml(
        modeNote,
        "自定义执行工具只支持“直接命令”模式。Loopora 会按你的 CLI 模版执行，并从 `{output_path}` 回收结构化结果。",
        "Custom execution tools only support direct-command mode. Loopora will execute your CLI template as-is and recover structured output from `{output_path}`.",
      );
    } else if (commandMode) {
      setBilingualHtml(
        modeNote,
        "现在由直接命令接管。模型和推理强度会冻结成只读参考，真正的执行细节以右侧 CLI 模版为准。",
        "Direct command now owns the execution. Model and reasoning freeze into a read-only reference while the CLI template on the right becomes the source of truth.",
      );
    } else {
      setBilingualHtml(
        modeNote,
        "现在由预设模式接管。你只需要改模型和推理强度，Loopora 会自动拼出最终命令。",
        "Preset mode now owns the execution. You only need to tune the model and reasoning, and Loopora assembles the final command for you.",
      );
    }

    syncCommandBlock(profile);
    renderCommandPreview();
  }

  function refreshExecutorFields(options = {}) {
    const preserveUserModel = options.preserveUserModel !== false;
    const preserveUserEffort = options.preserveUserEffort !== false;
    const profile = selectedProfile();
    if (!profile) {
      return;
    }

    const previousModelDefault = modelInput.dataset.defaultModel || "";
    const previousEffortDefault = reasoningInput.dataset.defaultEffort || "";
    const currentModel = modelInput.value.trim();
    const currentEffort = reasoningMirrorInput.value.trim();
    const modelWasDefault = !currentModel || currentModel === previousModelDefault;
    const effortWasDefault = !currentEffort || currentEffort === previousEffortDefault;

    if ((!preserveUserModel || modelWasDefault) && profile.default_model !== undefined) {
      modelInput.value = profile.default_model || "";
    }
    modelInput.dataset.defaultModel = profile.default_model || "";
    modelInput.dataset.placeholderZh = profile.model_placeholder_zh || "";
    modelInput.dataset.placeholderEn = profile.model_placeholder_en || "";
    setBilingualHtml(modelFieldLabel, "默认模型", "Default model");
    setBilingualHtml(modelNote, profile.model_help_zh || "", profile.model_help_en || "");

    const nextEffort = (!preserveUserEffort || effortWasDefault)
      ? (profile.effort_default || "")
      : currentEffort;
    renderEffortOptions(profile, nextEffort);
    reasoningInput.dataset.defaultEffort = profile.effort_default || "";
    setBilingualHtml(reasoningFieldLabel, profile.effort_label_zh || "推理强度", profile.effort_label_en || "Reasoning effort");
    setBilingualHtml(reasoningNote, profile.effort_help_zh || "", profile.effort_help_en || "");

    const defaultCliPlaceholderZh = profile.cli_name ? `例如：${profile.cli_name}` : "例如：your-wrapper";
    const defaultCliPlaceholderEn = profile.cli_name ? `For example: ${profile.cli_name}` : "For example: your-wrapper";
    commandCliInput.dataset.placeholderZh = defaultCliPlaceholderZh;
    commandCliInput.dataset.placeholderEn = defaultCliPlaceholderEn;
    setBilingualHtml(
      commandCliNote,
      profile.command_only
        ? `这里填你自己的命令入口。至少要让命令读到 \`{prompt}\`，并在结束前把 JSON 结果写到 \`{output_path}\`。`
        : `切到直接命令后，这里就是最终会执行的可执行文件。至少建议保留：${(profile.command_required_placeholders || []).join(" ") || "{prompt}"}` ,
      profile.command_only
        ? "Put your own command entrypoint here. At minimum it must receive `{prompt}` and write a JSON result to `{output_path}` before it exits."
        : `Once direct command mode is active, this is the executable Loopora will run. Recommended required tokens: ${(profile.command_required_placeholders || []).join(" ") || "{prompt}"}`,
    );

    window.LooporaUI.applyLocalizedAttributes(form);
    syncModeUI();
  }

  archetypeInput?.addEventListener("change", () => {
    syncPromptMarkdownForArchetype(archetypeInput.value, archetypeInput.dataset.previousArchetype || "");
    syncArchetypeGuide();
    archetypeInput.dataset.previousArchetype = archetypeInput.value;
  });

  executorKindInput?.addEventListener("change", () => {
    if (isCommandMode()) {
      saveCommandDraft(lastExecutorKind);
    }
    lastExecutorKind = executorKindInput.value;
    commandCliInput.dataset.autofilled = "true";
    commandArgsInput.dataset.autofilled = "true";
    refreshExecutorFields({preserveUserModel: true, preserveUserEffort: true});
  });

  modeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const nextMode = button.dataset.modeChoice || "preset";
      if (nextMode === executorModeInput.value) {
        return;
      }
      if (nextMode === "preset") {
        saveCommandDraft(selectedProfile()?.key || lastExecutorKind);
      }
      setMode(nextMode);
    });
  });

  modelInput?.addEventListener("input", renderCommandPreview);
  commandCliInput?.addEventListener("input", () => {
    commandCliInput.dataset.autofilled = "false";
    if (isCommandMode()) {
      saveCommandDraft(selectedProfile()?.key || lastExecutorKind);
    }
    renderCommandPreview();
  });
  commandArgsInput?.addEventListener("input", () => {
    commandArgsInput.dataset.autofilled = "false";
    if (isCommandMode()) {
      saveCommandDraft(selectedProfile()?.key || lastExecutorKind);
    }
    renderCommandPreview();
  });
  reasoningInput?.addEventListener("change", () => {
    syncReasoningMirror();
    renderCommandPreview();
  });

  form.addEventListener("submit", () => {
    syncReasoningMirror();
    const profile = selectedProfile();
    if (profile?.command_only) {
      executorModeInput.value = "command";
    }
  });

  document.addEventListener("loopora:localechange", () => {
    localizeArchetypeOptions();
    syncArchetypeGuide();
    syncPromptMarkdownForArchetype(archetypeInput?.value || "", archetypeInput?.value || "", {force: false});
    refreshExecutorFields({preserveUserModel: true, preserveUserEffort: true});
    setPromptPreviewNote();
    refreshPromptPreview();
  });

  if (window.LooporaMarkdownWorkbench && promptMarkdownInput && promptMarkdownPreview) {
    promptMarkdownWorkbench = window.LooporaMarkdownWorkbench.create({
      textarea: promptMarkdownInput,
      preview: promptMarkdownPreview,
      stripFrontMatter: true,
      onStatus(kind, message) {
        if (kind === "error") {
          setPromptPreviewNote("is-error", message);
          return;
        }
        setPromptPreviewNote();
      },
      emptyMessage: {
        zh: "这里还没有可显示的 Prompt 正文。",
        en: "There is no prompt body to preview yet.",
      },
      loadingMessage: {
        zh: "正在渲染 Prompt 预览…",
        en: "Rendering the prompt preview...",
      },
    });
  }

  archetypeInput.dataset.previousArchetype = archetypeInput?.value || "";
  localizeArchetypeOptions();
  syncArchetypeGuide();
  syncPromptMarkdownForArchetype(archetypeInput?.value || "", archetypeInput?.value || "", {force: true});
  refreshExecutorFields({preserveUserModel: true, preserveUserEffort: true});
  setPromptPreviewNote();
  refreshPromptPreview();
});
