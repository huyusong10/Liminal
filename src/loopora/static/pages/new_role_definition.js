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
  const promptRefInput = document.getElementById("role-definition-prompt-ref-input");
  const promptMarkdownInput = document.getElementById("role-definition-prompt-markdown-input");
  const commandCliInput = document.getElementById("role-definition-command-cli-input");
  const commandArgsInput = document.getElementById("role-definition-command-args-input");
  const modelInput = form.querySelector("input[name='model']");
  const reasoningInput = document.getElementById("role-definition-reasoning-input");
  const commandCliField = commandCliInput?.closest("label");
  const commandArgsField = commandArgsInput?.closest("label");

  function selectedProfile() {
    return profiles.find((profile) => profile.key === executorKindInput?.value) || profiles[0] || null;
  }

  function defaultArgs(profile) {
    return Array.isArray(profile?.command_args_template) ? profile.command_args_template.join("\n") : "";
  }

  function currentBuiltinTemplate(archetype) {
    return builtinTemplates[String(archetype || "").trim()] || null;
  }

  function syncDefaults() {
    const profile = selectedProfile();
    if (!profile) {
      return;
    }

    if (!commandCliInput.value.trim() || commandCliInput.dataset.autofilled === "true") {
      commandCliInput.value = profile.cli_name || "";
      commandCliInput.dataset.autofilled = "true";
    }

    const defaultModel = modelInput.dataset.defaultModel || "";
    const currentModel = modelInput.value.trim();
    if (!currentModel || currentModel === defaultModel) {
      modelInput.value = profile.default_model || "";
    }
    modelInput.dataset.defaultModel = profile.default_model || "";

    const defaultReasoning = reasoningInput.dataset.defaultReasoning || "";
    const currentReasoning = reasoningInput.value.trim();
    if (!currentReasoning || currentReasoning === defaultReasoning) {
      reasoningInput.value = profile.effort_default || "";
    }
    reasoningInput.dataset.defaultReasoning = profile.effort_default || "";

    if ((!commandArgsInput.value.trim() || commandArgsInput.dataset.autofilled === "true") && executorModeInput.value === "command") {
      commandArgsInput.value = defaultArgs(profile);
      commandArgsInput.dataset.autofilled = "true";
    }
  }

  function syncMode() {
    const isCommandMode = executorModeInput.value === "command";
    if (commandCliField) {
      commandCliField.hidden = !isCommandMode;
    }
    if (commandArgsField) {
      commandArgsField.hidden = !isCommandMode;
    }
  }

  executorKindInput?.addEventListener("change", () => {
    commandCliInput.dataset.autofilled = "true";
    commandArgsInput.dataset.autofilled = "true";
    syncDefaults();
    syncMode();
  });

  archetypeInput?.addEventListener("change", () => {
    const nextTemplate = currentBuiltinTemplate(archetypeInput.value);
    if (!nextTemplate) {
      return;
    }
    const previousTemplate = currentBuiltinTemplate(archetypeInput.dataset.previousArchetype);
    if (!promptRefInput.value.trim() || promptRefInput.value === previousTemplate?.prompt_ref) {
      promptRefInput.value = nextTemplate.prompt_ref || "";
    }
    if (!promptMarkdownInput.value.trim() || promptMarkdownInput.value === previousTemplate?.prompt_markdown) {
      promptMarkdownInput.value = nextTemplate.prompt_markdown || "";
    }
    archetypeInput.dataset.previousArchetype = archetypeInput.value;
  });

  executorModeInput?.addEventListener("change", () => {
    syncDefaults();
    syncMode();
  });

  commandCliInput?.addEventListener("input", () => {
    commandCliInput.dataset.autofilled = "false";
  });

  commandArgsInput?.addEventListener("input", () => {
    commandArgsInput.dataset.autofilled = "false";
  });

  archetypeInput.dataset.previousArchetype = archetypeInput?.value || "";
  syncDefaults();
  syncMode();
});
