document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("new-loop-form");
  if (!form || !window.LiminalUI) {
    return;
  }

  const workdirInput = document.getElementById("workdir-input");
  const specPathInput = document.getElementById("spec-path-input");
  const browseWorkdirButton = document.getElementById("browse-workdir");
  const browseSpecButton = document.getElementById("browse-spec");
  const createSpecTemplateButton = document.getElementById("create-spec-template");
  const saveLoopButton = document.getElementById("save-loop-button");
  const formError = document.getElementById("form-error");
  const specValidation = document.getElementById("spec-validation");

  function localeText(zh, en) {
    return window.LiminalUI.pickText({zh, en});
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
    const payload = {
      name: String(formData.get("name") || "").trim(),
      workdir: String(formData.get("workdir") || "").trim(),
      spec_path: String(formData.get("spec_path") || "").trim(),
      model: String(formData.get("model") || "gpt-5.4").trim(),
      reasoning_effort: String(formData.get("reasoning_effort") || "medium").trim(),
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
  specPathInput.addEventListener("change", () => validateSpec({quiet: false}));
  specPathInput.addEventListener("blur", () => validateSpec({quiet: true}));
  form.addEventListener("submit", submitForm);

  if (specPathInput.value.trim()) {
    validateSpec({quiet: true});
  }
});
