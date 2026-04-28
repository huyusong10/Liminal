document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("bundle-import-form-fields");
  if (!form || !window.LooporaUI) {
    return;
  }

  const errorBox = document.getElementById("bundle-import-error");
  const pathInput = document.getElementById("bundle-import-path");
  const yamlInput = document.getElementById("bundle-import-yaml");
  const previewButton = document.getElementById("bundle-preview-button");
  const previewImportButton = document.getElementById("bundle-preview-import-button");
  const readyPreview = document.getElementById("alignment-ready-preview");
  const previewTitle = document.getElementById("bundle-preview-title");
  const artifactName = document.getElementById("alignment-artifact-name");
  const readyNote = document.getElementById("alignment-ready-note");
  const artifactGoal = document.getElementById("alignment-artifact-goal");
  const artifactRoles = document.getElementById("alignment-artifact-roles");
  const artifactFlow = document.getElementById("alignment-artifact-flow");
  const artifactWorkdir = document.getElementById("alignment-artifact-workdir");
  const controlSummary = document.getElementById("alignment-control-summary");
  const artifactSource = document.getElementById("alignment-artifact-source");
  const sourcePathLabel = document.getElementById("alignment-source-path");
  const specPreview = document.getElementById("alignment-spec-preview");
  const roleList = document.getElementById("alignment-role-list");
  const workflowDiagram = document.getElementById("alignment-workflow-diagram");
  const sourceOpenButton = document.getElementById("alignment-source-open-button");
  let errorTimer = null;

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

  function basename(path) {
    const cleaned = String(path || "").replace(/\/+$/, "");
    if (!cleaned) {
      return "";
    }
    return cleaned.split("/").filter(Boolean).pop() || cleaned;
  }

  function showImportError(message, options = {}) {
    const autoHide = options.autoHide !== false;
    if (errorTimer) {
      clearTimeout(errorTimer);
      errorTimer = null;
    }
    if (!message) {
      errorBox.hidden = true;
      errorBox.textContent = "";
      return;
    }
    errorBox.hidden = false;
    errorBox.textContent = message;
    if (autoHide) {
      errorTimer = window.setTimeout(() => showImportError(""), 7000);
    }
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: {
        "content-type": "application/json",
        ...(options.headers || {}),
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || payload.detail || response.statusText);
    }
    return payload;
  }

  function taskSummary(bundle) {
    const markdown = String(bundle?.spec?.markdown || "");
    const taskMatch = markdown.match(/# Task\s+([\s\S]*?)(?:\n# |\s*$)/);
    const text = (taskMatch ? taskMatch[1] : markdown)
      .replace(/```[\s\S]*?```/g, "")
      .replace(/[#*_`>-]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    return text.slice(0, 180) || localeText("spec 已生成。", "spec generated.");
  }

  function workflowSummary(preview) {
    const roleById = new Map((preview?.roles || []).map((role) => [role.id, role.name || role.id]));
    return (preview?.steps || [])
      .map((step) => roleById.get(step.role_id) || step.role_id)
      .filter(Boolean)
      .join(" -> ");
  }

  function listSnippet(values) {
    return (values || [])
      .map((value) => String(value || "").trim())
      .filter(Boolean)
      .slice(0, 2)
      .join(" / ");
  }

  function renderControlSummary(summary) {
    if (!controlSummary) {
      return;
    }
    if (!summary) {
      controlSummary.innerHTML = "";
      return;
    }
    const workflow = summary.workflow || {};
    const gatekeeper = summary.gatekeeper || {};
    const controls = Array.isArray(summary.controls) ? summary.controls : [];
    const controlSnippet = controls
      .slice(0, 2)
      .map((control) => {
        const after = control.after && control.after !== "0s" ? `${control.after} · ` : "";
        return `${after}${control.signal || "control"} -> ${control.role_name || control.role_id || "role"}`;
      })
      .join(" / ");
    const cards = [
      {
        label: localeText("主要风险", "Main risk"),
        value: listSnippet(summary.risks) || localeText("从 spec 中读取。", "Read from spec."),
      },
      {
        label: localeText("证据路径", "Evidence path"),
        value: listSnippet(summary.evidence) || localeText("由 workflow 运行时落账。", "Recorded by the workflow runtime."),
      },
      {
        label: "workflow",
        value: workflow.summary || localeText(`${workflow.step_count || 0} 个 step`, `${workflow.step_count || 0} steps`),
      },
      {
        label: "GateKeeper",
        value: gatekeeper.enabled
          ? localeText("需要 evidence refs 才能结束。", "Requires evidence refs to finish.")
          : localeText("未配置 GateKeeper。", "No GateKeeper configured."),
      },
      ...(controls.length ? [{
        label: localeText("运行控制", "Runtime controls"),
        value: controlSnippet || localeText("按误差风险触发检查。", "Triggered by error-control risk."),
      }] : []),
    ];
    controlSummary.innerHTML = cards.map((card) => `
      <div class="alignment-control-card">
        <strong>${escapeHtml(card.label)}</strong>
        <span>${escapeHtml(card.value)}</span>
      </div>
    `).join("");
  }

  function compactRoleSummary(role) {
    const description = String(role.description || "").trim();
    const posture = String(role.posture_notes || "").trim();
    return description || posture || localeText("点击查看完整 role 信息。", "Open to inspect the full role definition.");
  }

  function roleDetailRow(label, value, options = {}) {
    const text = String(value || "").trim();
    if (!text) {
      return "";
    }
    const body = options.pre
      ? `<pre>${escapeHtml(text)}</pre>`
      : `<dd>${escapeHtml(text)}</dd>`;
    return `<div><dt>${escapeHtml(label)}</dt>${body}</div>`;
  }

  function renderRoleCard(role) {
    const item = document.createElement("details");
    item.className = "alignment-role-card";
    item.dataset.testid = "alignment-role-card";
    const name = role.name || role.key || "role";
    const archetype = role.archetype || "";
    const executor = [
      role.executor_kind,
      role.model,
      role.reasoning_effort,
    ].filter(Boolean).join(" · ");
    item.innerHTML = `
      <summary class="alignment-role-summary" data-testid="alignment-role-toggle">
        <span class="alignment-role-title">
          <strong>${escapeHtml(name)}</strong>
          <em>${escapeHtml(archetype)}</em>
        </span>
        <span class="alignment-role-brief">${escapeHtml(compactRoleSummary(role))}</span>
      </summary>
      <dl class="alignment-role-details">
        ${roleDetailRow("key", role.key)}
        ${roleDetailRow("archetype", archetype)}
        ${roleDetailRow("description", role.description)}
        ${roleDetailRow("posture_notes", role.posture_notes)}
        ${roleDetailRow("executor", executor)}
        ${roleDetailRow("executor_mode", role.executor_mode)}
        ${roleDetailRow("command_cli", role.command_cli)}
        ${roleDetailRow("command_args_text", role.command_args_text, {pre: true})}
        ${roleDetailRow("prompt_ref", role.prompt_ref)}
        ${roleDetailRow("prompt_markdown", role.prompt_markdown, {pre: true})}
      </dl>
    `;
    return item;
  }

  async function revealSourcePath(path) {
    if (!path) {
      return;
    }
    try {
      await fetchJson("/api/system/reveal-path", {
        method: "POST",
        body: JSON.stringify({path}),
      });
    } catch (error) {
      try {
        await navigator.clipboard.writeText(path);
        showImportError(localeText("无法自动打开，路径已复制到剪贴板。", "Could not open automatically. The path was copied to your clipboard."));
      } catch (_) {
        showImportError(error.message || localeText("无法打开源文件。", "Unable to open the source file."));
      }
    }
  }

  function selectPreviewTab(tabName) {
    document.querySelectorAll("[data-preview-tab]").forEach((button) => {
      const active = button.dataset.previewTab === tabName;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", String(active));
    });
    document.querySelectorAll("[data-preview-panel]").forEach((section) => {
      section.hidden = section.dataset.previewPanel !== tabName;
    });
  }

  function renderBundlePreview(payload) {
    readyPreview.hidden = false;
    const metadata = payload.metadata || payload.bundle?.metadata || {};
    artifactName.textContent = metadata.name || localeText("循环方案", "Loop plan");
    previewTitle.textContent = localeText("方案预览已准备好", "Plan preview is ready");
    readyNote.textContent = taskSummary(payload.bundle);
    previewImportButton.hidden = false;
    if (artifactGoal) {
      artifactGoal.textContent = taskSummary(payload.bundle);
    }
    artifactRoles.textContent = localeText(`${(payload.roles || []).length} roles`, `${(payload.roles || []).length} roles`);
    artifactFlow.textContent = workflowSummary(payload.workflow_preview) || localeText("workflow 已生成", "workflow generated");
    artifactWorkdir.textContent = basename(payload.bundle?.loop?.workdir || "");
    artifactWorkdir.title = payload.bundle?.loop?.workdir || "";
    renderControlSummary(payload.control_summary || null);
    specPreview.innerHTML = payload.spec_rendered_html || "";
    if (sourceOpenButton) {
      sourceOpenButton.hidden = !payload.source_path;
      sourceOpenButton.dataset.sourcePath = payload.source_path || "";
      sourceOpenButton.title = payload.source_path || "";
    }
    if (artifactSource) {
      artifactSource.hidden = !payload.source_path;
    }
    if (sourcePathLabel) {
      sourcePathLabel.textContent = payload.source_path ? `${localeText("源文件", "Source")}: ${payload.source_path}` : "";
      sourcePathLabel.title = payload.source_path || "";
    }
    roleList.innerHTML = "";
    (payload.roles || []).forEach((role) => {
      roleList.append(renderRoleCard(role));
    });
    if (window.LooporaWorkflowDiagram) {
      window.LooporaWorkflowDiagram.renderInto(workflowDiagram, payload.workflow_preview || {}, {variant: "card"});
    }
    selectPreviewTab("spec");
    readyPreview.scrollIntoView({block: "start", behavior: "smooth"});
  }

  async function previewBundle() {
    showImportError("");
    const payload = {
      bundle_path: pathInput?.value?.trim() || "",
      bundle_yaml: yamlInput?.value || "",
    };
    if (!payload.bundle_path && !payload.bundle_yaml.trim()) {
      showImportError(localeText("请填写 Bundle 路径或粘贴 YAML。", "Provide a bundle path or paste YAML."));
      form.scrollIntoView({block: "start", behavior: "smooth"});
      return;
    }
    previewButton.disabled = true;
    try {
      const preview = await fetchJson("/api/bundles/preview", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (!preview.ok) {
        throw new Error(preview.error || localeText("Bundle 预览失败。", "Bundle preview failed."));
      }
      renderBundlePreview(preview);
    } catch (error) {
      showImportError(error.message || localeText("Bundle 预览失败。", "Bundle preview failed."));
    } finally {
      previewButton.disabled = false;
    }
  }

  previewButton?.addEventListener("click", () => {
    previewBundle().catch((error) => {
      showImportError(error.message || localeText("Bundle 预览失败。", "Bundle preview failed."));
    });
  });
  previewImportButton?.addEventListener("click", () => form.requestSubmit());
  sourceOpenButton?.addEventListener("click", () => {
    revealSourcePath(sourceOpenButton.dataset.sourcePath || "").catch((error) => {
      showImportError(error.message || localeText("无法打开源文件。", "Unable to open the source file."));
    });
  });
  pathInput?.addEventListener("input", () => showImportError(""));
  yamlInput?.addEventListener("input", () => showImportError(""));
  document.querySelectorAll("[data-preview-tab]").forEach((button) => {
    button.addEventListener("click", () => selectPreviewTab(button.dataset.previewTab || "spec"));
  });

  if (window.location.hash === "#bundle-import-form") {
    document.getElementById("bundle-import-form")?.scrollIntoView({block: "start"});
  }
});
