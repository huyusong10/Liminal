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
  const completionModeField = document.getElementById("completion-mode-field");
  const completionModeNote = document.getElementById("completion-mode-note");
  const triggerWindowField = document.getElementById("trigger-window-field");
  const regressionWindowField = document.getElementById("regression-window-field");
  const browseWorkdirButton = document.getElementById("browse-workdir");
  const browseSpecButton = document.getElementById("browse-spec");
  const editSpecButton = document.getElementById("edit-spec");
  const createSpecTemplateButton = document.getElementById("create-spec-template");
  const saveLoopButton = document.getElementById("save-loop-button");
  const formError = document.getElementById("form-error");
  const draftStatus = document.getElementById("draft-status");
  const draftActions = document.getElementById("draft-actions");
  const clearDraftButton = document.getElementById("clear-draft-button");
  const specValidation = document.getElementById("spec-validation");
  const specPreviewModal = document.getElementById("spec-preview-modal");
  const specPreviewStatus = document.getElementById("spec-preview-status");
  const specPreviewPath = document.getElementById("spec-preview-path");
  const specPreviewContent = document.getElementById("spec-preview-content");
  const specPreviewToggleButton = document.getElementById("toggle-spec-preview");
  const specEditorInput = document.getElementById("spec-editor-input");
  const specEditorWorkbenchShell = document.querySelector(".spec-preview-workbench");
  const specEditorSourcePanel = document.getElementById("spec-editor-source-panel");
  const specEditorPreviewPanel = document.getElementById("spec-editor-preview-panel");
  const specEditorSaveButton = document.getElementById("save-spec-document");
  const specEditorValidationPill = document.getElementById("spec-editor-validation-pill");
  const specEditorSaveState = document.getElementById("spec-editor-save-state");
  const executorProfiles = JSON.parse(document.getElementById("executor-profiles-json")?.textContent || "[]");
  const orchestrations = JSON.parse(document.getElementById("orchestrations-json")?.textContent || "[]");
  const pristineLoopForm = JSON.parse(document.getElementById("pristine-loop-form-json")?.textContent || "{}");
  const workdirQuickPickButtons = Array.from(document.querySelectorAll("[data-fill-workdir]"));

  const DRAFT_STORAGE_KEY = "loopora:new-loop-draft:v2";
  let latestSpecValidationRequest = 0;
  let lastSpecPreviewTrigger = null;
  let specEditorWorkbench = null;
  let specEditorLoadedPath = "";
  let specEditorSavedText = "";
  let specEditorLastValidation = null;
  let specPreviewVisible = false;

  function localeText(zh, en) {
    return window.LooporaUI.pickText({zh, en});
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

  function specValidationFeedback(validation) {
    if (!validation || typeof validation !== "object") {
      return {
        message: localeText("Spec 状态未知。", "Spec status is unknown."),
        kind: "warning",
        pill: localeText("待检查", "Pending"),
      };
    }
    if (validation.state === "dirty") {
      return {
        message: validation.error || localeText("编辑器里有未保存的改动。", "There are unsaved editor changes."),
        kind: "warning",
        pill: localeText("未保存", "Unsaved"),
      };
    }
    if (validation.state === "detached") {
      return {
        message: validation.error || localeText("当前编辑器还没有绑定新的 spec 文件。", "The editor is not bound to the new spec file yet."),
        kind: "warning",
        pill: localeText("需重载", "Reload"),
      };
    }
    if (validation.ok) {
      const detail = validation.check_mode === "auto_generated"
        ? localeText("当前内容还没有显式 checks，run 开始时会自动生成并冻结。", "The current text has no explicit checks yet. Loopora will generate and freeze them at run start.")
        : localeText(`当前内容识别到 ${validation.check_count} 个显式 checks。`, `The current text contains ${validation.check_count} explicit check(s).`);
      return {
        message: `${localeText("Spec 校验通过。", "Spec is valid.")} ${detail}`,
        kind: "success",
        pill: validation.check_mode === "auto_generated"
          ? localeText("自动 checks", "Auto checks")
          : localeText("校验通过", "Valid"),
      };
    }
    return {
      message: validation.error || localeText("Spec 还没有满足最小结构。", "The spec does not satisfy the minimum structure yet."),
      kind: "error",
      pill: localeText("需修正", "Needs fixes"),
    };
  }

  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
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
    const visible = Object.keys(pruneDraft(draft)).length > 0;
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
    if (!Object.keys(normalizedDraft).length) {
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

  async function fetchJson(url, options = {}) {
    try {
      const response = await fetch(url, options);
      const payload = await response.json().catch(() => ({}));
      return {response, payload, error: null};
    } catch (error) {
      return {response: null, payload: {}, error};
    }
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

  function currentOrchestration() {
    return orchestrations.find((item) => item.id === orchestrationInput.value) || orchestrations[0] || null;
  }

  function workflowRoles(orchestration) {
    const workflow = orchestration?.workflow_json || {};
    return Array.isArray(workflow.roles) ? workflow.roles : [];
  }

  function workflowSteps(orchestration) {
    const workflow = orchestration?.workflow_json || {};
    return Array.isArray(workflow.steps) ? workflow.steps : [];
  }

  function orchestrationHasRole(orchestration, archetype) {
    return workflowRoles(orchestration).some((role) => String(role?.archetype || "") === archetype);
  }

  function executorLabel(kind) {
    return executorProfiles.find((profile) => profile.key === kind)?.label || kind || "-";
  }

  function orchestrationHasFinishGate(orchestration) {
    const roleById = Object.fromEntries(workflowRoles(orchestration).map((role) => [role.id, role]));
    return workflowSteps(orchestration).some((step) => {
      const role = roleById[step.role_id];
      return role?.archetype === "gatekeeper" && String(step.on_pass || "continue") === "finish_run";
    });
  }

  function orchestrationPolicy(orchestration) {
    return {
      hasGuide: orchestrationHasRole(orchestration, "guide"),
      supportsGatekeeperCompletion: orchestrationHasFinishGate(orchestration),
    };
  }

  function roleRuntimeSummary(orchestration) {
    const roles = workflowRoles(orchestration);
    const counts = new Map();
    roles.forEach((role) => {
      const label = executorLabel(String(role.executor_kind || "codex"));
      counts.set(label, (counts.get(label) || 0) + 1);
    });
    if (!counts.size) {
      return localeText("沿用旧 loop 级回退", "Legacy loop-level fallback");
    }
    return Array.from(counts.entries()).map(([label, count]) => (count > 1 ? `${label} x${count}` : label)).join(" · ");
  }

  function syncCompletionModeLabels() {
    if (!completionModeInput) {
      return;
    }
    Array.from(completionModeInput.querySelectorAll("option[data-label-zh]")).forEach((option) => {
      option.textContent = localeText(option.dataset.labelZh || "", option.dataset.labelEn || "");
    });
  }

  function syncCompletionModeState(policy) {
    if (!completionModeInput) {
      return;
    }
    const gatekeeperOption = completionModeInput.querySelector('option[value="gatekeeper"]');
    if (gatekeeperOption) {
      gatekeeperOption.hidden = !policy.supportsGatekeeperCompletion;
      gatekeeperOption.disabled = !policy.supportsGatekeeperCompletion;
    }
    if (!policy.supportsGatekeeperCompletion) {
      completionModeInput.value = "rounds";
    }
    if (completionModeField) {
      completionModeField.dataset.modeLocked = String(!policy.supportsGatekeeperCompletion);
    }
    if (completionModeNote) {
      if (policy.supportsGatekeeperCompletion) {
        completionModeNote.hidden = true;
        completionModeNote.textContent = "";
      } else {
        completionModeNote.hidden = false;
        completionModeNote.textContent = localeText(
          "当前编排没有“通过即结束”的 GateKeeper 步骤，所以这里只能使用轮次推进。",
          "This orchestration has no finish-on-pass GateKeeper step, so rounds is the only completion mode available here.",
        );
      }
    }
  }

  function applyOrchestrationPolicy() {
    const selected = currentOrchestration();
    const policy = orchestrationPolicy(selected);
    syncCompletionModeLabels();
    syncCompletionModeState(policy);
    if (triggerWindowField) {
      triggerWindowField.hidden = !policy.hasGuide;
    }
    if (regressionWindowField) {
      regressionWindowField.hidden = !policy.hasGuide;
    }
    return policy;
  }

  function renderOrchestrationSummary() {
    const selected = currentOrchestration();
    if (!selected) {
      applyOrchestrationPolicy();
      showStatus(orchestrationSummary, localeText("还没有可用的编排方案，请先去“流程编排”里创建。", "No orchestration is available yet. Create one from the Orchestrations page."), "error");
      return;
    }
    const workflow = selected.workflow_json || {};
    const roles = Array.isArray(workflow.roles) ? workflow.roles.length : 0;
    const steps = Array.isArray(workflow.steps) ? workflow.steps.length : 0;
    const policy = applyOrchestrationPolicy();
    const source = selected.source === "builtin"
      ? localeText("内置方案", "Built-in")
      : localeText("自定义方案", "Custom");
    const runtimeSummary = roleRuntimeSummary(selected);
    const notes = [];
    if (!policy.supportsGatekeeperCompletion) {
      notes.push(localeText("仅支持轮次推进", "Rounds only"));
    }
    if (!policy.hasGuide) {
      notes.push(localeText("无 Guide，已隐藏触发/回退窗口", "No Guide, trigger/regression windows hidden"));
    }
    if (!policy.supportsGatekeeperCompletion) {
      showStatus(
        orchestrationSummary,
        localeText(
          `当前方案是 ${selected.name} · ${source} · 角色 ${roles} · 步骤 ${steps} · 执行 ${runtimeSummary}${notes.length ? ` · ${notes.join(" · ")}` : ""}。如果你想用守门裁决收束，请先去编排页补一个“通过即结束”的 GateKeeper 步骤。`,
          `The selected orchestration is ${selected.name} · ${source} · Roles ${roles} · Steps ${steps} · Runtime ${runtimeSummary}${notes.length ? ` · ${notes.join(" · ")}` : ""}. Add a finish-on-pass GateKeeper step in Orchestrations if you want gate-based completion.`,
        ),
        "warning",
      );
      return;
    }
    showStatus(
      orchestrationSummary,
      `${selected.name} · ${source} · ${localeText("角色", "Roles")} ${roles} · ${localeText("步骤", "Steps")} ${steps} · ${localeText("执行", "Runtime")} ${runtimeSummary}${notes.length ? ` · ${notes.join(" · ")}` : ""}${selected.description ? ` · ${selected.description}` : ""}`,
      "success",
    );
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
      const feedback = specValidationFeedback({
        ok: true,
        check_mode: payload.check_mode,
        check_count: payload.check_count,
      });
      showStatus(specValidation, feedback.message, feedback.kind);
      specPathInput.value = payload.path;
      saveDraft();
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

  function setSpecPreviewStatus(message, kind = "") {
    if (!specPreviewStatus) {
      return;
    }
    specPreviewStatus.textContent = message || "";
    specPreviewStatus.className = `spec-preview-status${kind ? ` is-${kind}` : ""}`;
  }

  function setSpecEditorSaveState(message, kind = "") {
    if (!specEditorSaveState) {
      return;
    }
    specEditorSaveState.textContent = message || "";
    specEditorSaveState.className = `field-note markdown-workbench-save-state${kind ? ` is-${kind}` : ""}`;
  }

  function setSpecEditorValidation(validation) {
    if (!specEditorValidationPill) {
      return;
    }
    const feedback = specValidationFeedback(validation);
    specEditorValidationPill.textContent = feedback.pill;
    specEditorValidationPill.className = `status-pill spec-preview-readonly${feedback.kind ? ` is-${feedback.kind}` : ""}`;
  }

  function specEditorIsDirty() {
    return Boolean(specEditorInput) && specEditorInput.value !== specEditorSavedText;
  }

  function specPreviewPlaceholderHtml() {
    return `<p>${escapeHtml(localeText(
      "这里只在你手动点击“预览”后显示渲染结果。",
      "The rendered result appears here only after you click Preview.",
    ))}</p>`;
  }

  function syncSpecPreviewToggleButton() {
    if (!specPreviewToggleButton) {
      return;
    }
    specPreviewToggleButton.textContent = specPreviewVisible
      ? localeText("返回编辑", "Back to editor")
      : localeText("预览", "Preview");
    specPreviewToggleButton.setAttribute("aria-pressed", String(specPreviewVisible));
  }

  function syncSpecPreviewMode() {
    specEditorWorkbenchShell?.classList.toggle("is-previewing", specPreviewVisible);
    if (specEditorSourcePanel) {
      specEditorSourcePanel.hidden = specPreviewVisible;
    }
    if (specEditorPreviewPanel) {
      specEditorPreviewPanel.hidden = !specPreviewVisible;
    }
    syncSpecPreviewToggleButton();
  }

  function syncSpecPreviewStatusForCurrentMode() {
    if (specPreviewVisible) {
      setSpecPreviewStatus(
        localeText("这是当前文本的渲染结果。要继续修改，请返回编辑。", "This is the rendered result for the current text. Go back to the editor to keep changing it."),
        "success",
      );
      return;
    }
    if (specEditorIsDirty()) {
      setSpecPreviewStatus(
        localeText("当前先保持在源码编辑态；准备好后再手动点“预览”。", "Stay in source-editing mode for now, then click Preview manually when you are ready."),
        "warning",
      );
      return;
    }
    setSpecPreviewStatus(
      localeText("先专心修改源码，准备好后再手动打开预览。", "Focus on editing first, then open the preview manually when you are ready."),
      "",
    );
  }

  function openSpecPreview(trigger = editSpecButton) {
    if (!specPreviewModal) {
      return;
    }
    lastSpecPreviewTrigger = trigger instanceof HTMLElement ? trigger : document.activeElement;
    specPreviewModal.hidden = false;
    specPreviewModal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
    specPreviewModal.querySelector(".spec-preview-dialog")?.scrollTo({top: 0});
    syncSpecPreviewMode();
  }

  function closeSpecPreview() {
    if (!specPreviewModal) {
      return;
    }
    specPreviewModal.hidden = true;
    specPreviewModal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
    if (lastSpecPreviewTrigger instanceof HTMLElement) {
      lastSpecPreviewTrigger.focus();
    }
  }

  function applyLoadedSpecDocument(payload) {
    if (!payload || !payload.ok || !specEditorInput) {
      return;
    }
    specEditorLoadedPath = payload.path;
    specEditorSavedText = String(payload.content || "");
    specEditorLastValidation = payload.validation || null;
    specPathInput.value = payload.path;
    specPreviewPath.textContent = payload.path;
    specEditorWorkbench?.setValue(payload.content || "", {render: false});
    specEditorWorkbench?.setPreviewHtml(specPreviewPlaceholderHtml());
    setSpecEditorValidation(payload.validation);
    showStatus(
      specValidation,
      specValidationFeedback(payload.validation).message,
      specValidationFeedback(payload.validation).kind,
    );
    setSpecEditorSaveState(
      payload.validation?.ok
        ? localeText("磁盘内容已载入，可以继续修改。", "Disk content loaded. You can keep editing.")
        : localeText("磁盘内容已载入，但当前 spec 还需要修正。", "Disk content loaded, but the current spec still needs fixes."),
      payload.validation?.ok ? "success" : "warning",
    );
    syncSpecPreviewStatusForCurrentMode();
    saveDraft();
  }

  async function loadSpecDocument(options = {}) {
    const path = specPathInput.value.trim();
    if (!path) {
      showStatus(specValidation, localeText("请先提供 spec 路径，再打开编辑器。", "Provide a spec path before opening the editor."), "error");
      return;
    }
    if (!options.force && specEditorLoadedPath === path && specEditorInput?.value) {
      specPreviewPath.textContent = path;
      if (!specEditorIsDirty() && specEditorLastValidation) {
        setSpecEditorValidation(specEditorLastValidation);
      }
      syncSpecPreviewStatusForCurrentMode();
      return;
    }

    specPreviewPath.textContent = path;
    setSpecPreviewStatus(localeText("正在读取 spec…", "Loading spec..."));
    setSpecEditorSaveState(localeText("正在把磁盘内容载入编辑器。", "Loading the file from disk into the editor."));

    const {response, payload, error} = await fetchJson(`/api/specs/document?path=${encodeURIComponent(path)}`);
    if (error || !response) {
      specPreviewPath.textContent = path;
      setSpecPreviewStatus(errorMessage(error, localeText("Spec 编辑器暂时不可用。", "The spec editor is temporarily unavailable.")), "error");
      setSpecEditorSaveState(errorMessage(error, localeText("暂时无法读取这份 spec。", "This spec cannot be read right now.")), "error");
      return;
    }
    if (!payload.ok) {
      specPreviewPath.textContent = path;
      setSpecPreviewStatus(payload.error || localeText("Spec 编辑器加载失败。", "The spec editor could not be loaded."), "error");
      setSpecEditorSaveState(payload.error || localeText("请检查路径和文件内容。", "Check the path and file contents."), "error");
      return;
    }
    applyLoadedSpecDocument(payload);
  }

  async function saveSpecDocument(options = {}) {
    const path = specPathInput.value.trim();
    if (!path) {
      showStatus(specValidation, localeText("请先提供 spec 路径，再保存编辑器内容。", "Provide a spec path before saving the editor contents."), "error");
      return false;
    }
    if (!specEditorInput) {
      return false;
    }
    setSpecEditorSaveState(localeText("正在把改动写回磁盘。", "Writing your changes back to disk."));
    const {response, payload, error} = await fetchJson("/api/specs/document", {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path, content: specEditorInput.value}),
    });
    if (error || !response) {
      const message = errorMessage(error, localeText("保存 spec 失败。", "Unable to save the spec."));
      setSpecEditorSaveState(message, "error");
      if (!options.silent) {
        showStatus(specValidation, message, "error");
      }
      return false;
    }
    if (!payload.ok) {
      const message = payload.error || localeText("保存 spec 失败。", "Unable to save the spec.");
      setSpecEditorSaveState(message, "error");
      if (!options.silent) {
        showStatus(specValidation, message, "error");
      }
      return false;
    }
    applyLoadedSpecDocument(payload);
    if (payload.validation?.ok) {
      setSpecEditorSaveState(localeText("已保存到磁盘，当前 spec 已通过校验。", "Saved to disk. The current spec is valid."), "success");
    } else {
      setSpecEditorSaveState(localeText("已保存到磁盘，但当前 spec 还需要修正。", "Saved to disk, but the current spec still needs fixes."), "warning");
    }
    if (!options.silent) {
      showStatus(
        specValidation,
        specValidationFeedback(payload.validation).message,
        specValidationFeedback(payload.validation).kind,
      );
    }
    return true;
  }

  async function editSpec() {
    specPreviewVisible = false;
    openSpecPreview(editSpecButton);
    syncSpecPreviewMode();
    if (!specEditorWorkbench && window.LooporaMarkdownWorkbench && specPreviewContent && specEditorInput) {
      specEditorWorkbench = window.LooporaMarkdownWorkbench.create({
        textarea: specEditorInput,
        preview: specPreviewContent,
        autoRenderOnInput: false,
        onStatus(kind, message) {
          if (kind === "loading") {
            setSpecPreviewStatus(message || localeText("正在生成 Markdown 预览…", "Generating the Markdown preview..."));
            return;
          }
          if (kind === "error") {
            setSpecPreviewStatus(message || localeText("Markdown 预览失败。", "Markdown preview failed."), "error");
            return;
          }
          syncSpecPreviewStatusForCurrentMode();
        },
        emptyMessage: {
          zh: "这份 spec 目前还是空的。",
          en: "This spec is currently empty.",
        },
        loadingMessage: {
          zh: "正在渲染 Markdown 预览…",
          en: "Rendering the Markdown preview...",
        },
      });
      specEditorInput.addEventListener("input", () => {
        setSpecEditorSaveState(localeText("有未保存的改动。提交 loop 前会先尝试自动保存。", "There are unsaved changes. Loop submission will try to save them first."), "warning");
        setSpecEditorValidation({
          state: "dirty",
          error: localeText("编辑器里有未保存的改动。", "There are unsaved editor changes."),
          check_count: 0,
          check_mode: "",
        });
        syncSpecPreviewStatusForCurrentMode();
      });
    }
    await loadSpecDocument();
    syncSpecPreviewMode();
    syncSpecPreviewStatusForCurrentMode();
    specEditorInput?.focus();
  }

  async function toggleSpecPreview() {
    if (specPreviewVisible) {
      specPreviewVisible = false;
      syncSpecPreviewMode();
      syncSpecPreviewStatusForCurrentMode();
      specEditorInput?.focus();
      return;
    }
    specPreviewVisible = true;
    syncSpecPreviewMode();
    await specEditorWorkbench?.renderNow();
  }

  function parseNumber(value, fallback) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
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
    if (specEditorIsDirty()) {
      if (specPathInput.value.trim() !== specEditorLoadedPath) {
        showStatus(
          formError,
          localeText("Spec 路径已经变了，请重新打开编辑器确认要保存哪份文件。", "The spec path changed. Reopen the editor to confirm which file should be saved."),
          "error",
        );
        return;
      }
      const saved = await saveSpecDocument({silent: false});
      if (!saved) {
        showStatus(formError, localeText("Spec 编辑器里的改动还没有成功保存，请先修复后再提交。", "The editor changes were not saved successfully. Fix that first before submitting."), "error");
        return;
      }
    }
    const specValid = await validateSpec();
    if (!specValid) {
      showStatus(formError, localeText("Spec 不满足要求，请先修复后再提交。", "The spec does not satisfy the required structure yet."), "error");
      return;
    }

    const formData = new FormData(form);
    const payload = {
      name: String(formData.get("name") || "").trim(),
      workdir: String(formData.get("workdir") || "").trim(),
      spec_path: String(formData.get("spec_path") || "").trim(),
      orchestration_id: String(formData.get("orchestration_id") || "").trim(),
      completion_mode: String(formData.get("completion_mode") || "gatekeeper").trim(),
      iteration_interval_seconds: parseNumber(formData.get("iteration_interval_seconds"), 0),
      max_iters: parseNumber(formData.get("max_iters"), 8),
      max_role_retries: parseNumber(formData.get("max_role_retries"), 2),
      delta_threshold: parseNumber(formData.get("delta_threshold"), 0.005),
      trigger_window: parseNumber(formData.get("trigger_window"), 4),
      regression_window: parseNumber(formData.get("regression_window"), 2),
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
  if (editSpecButton) {
    editSpecButton.addEventListener("click", () => runAction(
      editSpecButton,
      editSpec,
      {
        errorTarget: specValidation,
        fallbackMessage: localeText("无法打开 spec 编辑器。", "Unable to open the spec editor."),
      },
    ));
  }
  if (specEditorSaveButton) {
    specEditorSaveButton.addEventListener("click", () => runAction(
      specEditorSaveButton,
      () => saveSpecDocument({silent: false}),
      {
        errorTarget: specValidation,
        fallbackMessage: localeText("无法保存 spec。", "Unable to save the spec."),
      },
    ));
  }
  if (specPreviewToggleButton) {
    specPreviewToggleButton.addEventListener("click", () => runAction(
      specPreviewToggleButton,
      toggleSpecPreview,
      {
        errorTarget: specValidation,
        fallbackMessage: localeText("无法切换 spec 预览。", "Unable to toggle the spec preview."),
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
      showStatus(formError, "");
    });
  });

  orchestrationInput?.addEventListener("change", renderOrchestrationSummary);
  completionModeInput?.addEventListener("change", renderOrchestrationSummary);
  specPathInput.addEventListener("change", () => {
    if (specPathInput.value.trim() !== specEditorLoadedPath) {
      specEditorLoadedPath = "";
      specEditorSavedText = "";
      specEditorLastValidation = null;
      setSpecEditorSaveState(localeText("路径已经变化，重新打开编辑器后会读取新的 spec 文件。", "The path changed. Reopen the editor to load the new spec file."));
      setSpecEditorValidation({
        state: "detached",
        error: localeText("当前编辑器还没有绑定新的 spec 文件。", "The editor is not bound to the new spec file yet."),
        check_count: 0,
        check_mode: "",
      });
    }
    validateSpec({quiet: false});
  });
  specPathInput.addEventListener("blur", () => validateSpec({quiet: true}));
  form.addEventListener("input", saveDraft);
  form.addEventListener("change", saveDraft);
  form.addEventListener("submit", submitForm);
  document.addEventListener("loopora:localechange", () => {
    renderOrchestrationSummary();
    syncSpecPreviewToggleButton();
    syncSpecPreviewStatusForCurrentMode();
    if (!specPreviewVisible) {
      specEditorWorkbench?.setPreviewHtml(specPreviewPlaceholderHtml());
    }
  });
  document.querySelectorAll("[data-close-spec-preview]").forEach((element) => {
    element.addEventListener("click", closeSpecPreview);
  });
  specPreviewModal?.addEventListener("click", (event) => {
    if (event.target === specPreviewModal) {
      closeSpecPreview();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && specPreviewModal && !specPreviewModal.hidden) {
      closeSpecPreview();
    }
  });

  const restoredDraft = restoreDraftIfAllowed();
  specEditorWorkbench?.setPreviewHtml(specPreviewPlaceholderHtml());
  syncSpecPreviewMode();
  renderOrchestrationSummary();
  if (specPathInput.value.trim()) {
    validateSpec({quiet: true});
  }
  if (restoredDraft) {
    saveDraft();
  } else {
    updateDraftUI();
  }
});
