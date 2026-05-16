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
  const artifactRoles = document.getElementById("alignment-artifact-roles");
  const artifactVerdict = document.getElementById("alignment-artifact-verdict");
  const artifactJudgment = document.getElementById("alignment-artifact-judgment");
  const artifactWorkdir = document.getElementById("alignment-artifact-workdir");
  const controlSummary = document.getElementById("alignment-control-summary");
  const judgmentMap = document.getElementById("alignment-judgment-map");
  const diagnosticsStrip = document.getElementById("alignment-diagnostics-strip");
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
    return text.slice(0, 180) || localeText("Loop 契约已生成。", "spec generated.");
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

  function labeledSummary(labelZh, labelEn, value) {
    return localeText(`${labelZh}：${value || "-"}`, `${labelEn}: ${value || "-"}`);
  }

  function verdictSummary(summary) {
    if (summary?.gatekeeper?.enabled === true) {
      return "GateKeeper";
    }
    return localeText("轮次预算", "round budget");
  }

  function coverageSummary(summary) {
    const coverage = summary?.coverage || {};
    const checkCount = Number(coverage.check_count || 0);
    const targetCount = Number(coverage.target_count || 0);
    const requiredCount = Number(coverage.required_target_count || 0);
    const summaryText = localeText(coverage.summary_zh || "", coverage.summary_en || coverage.summary || "");
    if (summaryText && !checkCount && !targetCount) {
      return summaryText;
    }
    if (checkCount && targetCount) {
      return localeText(
        `${checkCount} 项检查 · ${targetCount} 个覆盖目标（${requiredCount} 必需）`,
        `${checkCount} checks · ${targetCount} coverage targets (${requiredCount} required)`
      );
    }
    if (checkCount) {
      return localeText(`${checkCount} 项检查`, `${checkCount} checks`);
    }
    if (targetCount) {
      return localeText(
        `${targetCount} 个覆盖目标（${requiredCount} 必需）`,
        `${targetCount} coverage targets (${requiredCount} required)`
      );
    }
    return "";
  }

  function judgmentStatus(summary) {
    const traceability = summary?.traceability || {};
    const mapped = Number(traceability.mapped_count || 0);
    const required = Number(traceability.required_count || mapped);
    const diagnostics = (summary?.diagnostics || []).filter((item) => String(item?.severity || "") !== "info");
    const base = mapped
      ? localeText(`${mapped}/${required || mapped} 已投影`, `${mapped}/${required || mapped} projected`)
      : localeText("未投影", "not projected");
    if (diagnostics.length) {
      return localeText(`${base} · ${diagnostics.length} 提醒`, `${base} · ${diagnostics.length} warnings`);
    }
    return base;
  }

  function traceItemLabel(item) {
    const labels = {
      loop_fit: localeText("Loopora 适配", "Loopora fit"),
      collaboration_story: localeText("协作判断", "Collaboration"),
      task_scope: localeText("任务边界", "Task scope"),
      success_surface: localeText("成功面", "Success"),
      fake_done_risks: localeText("假完成", "Fake done"),
      evidence_preferences: localeText("证据偏好", "Evidence"),
      coverage_targets: localeText("覆盖目标", "Coverage"),
      execution_strategy: localeText("执行策略", "Execution strategy"),
      residual_risk_policy: localeText("残余风险", "Risk policy"),
      judgment_tradeoffs: localeText("判断取舍", "Tradeoffs"),
      local_governance: localeText("本地治理", "Local governance"),
      role_posture: localeText("角色姿态", "Role posture"),
      workflow_judgment: localeText("运行流程", "Run flow"),
      gatekeeper_closure: localeText("裁决收口", "Closure"),
      runtime_controls: localeText("运行控制", "Controls"),
    };
    return labels[item?.key] || item?.label || item?.key || "-";
  }

  function surfaceSummary(surfaces) {
    const values = (surfaces || []).map((value) => String(value || "").trim()).filter(Boolean);
    return values.slice(0, 2).join(" / ") || "-";
  }

  function localizedDiagnosticText(item, field) {
    const zh = item?.[`${field}_zh`] || item?.[field];
    const en = item?.[`${field}_en`] || item?.[field];
    return localeText(zh || "", en || "");
  }

  function renderJudgmentMap(traceability, diagnostics = []) {
    if (!judgmentMap || !diagnosticsStrip) {
      return;
    }
    const items = Array.isArray(traceability?.items) ? traceability.items : [];
    const visibleItems = items.slice(0, 12);
    if (!visibleItems.length) {
      judgmentMap.hidden = true;
      judgmentMap.innerHTML = "";
    } else {
      judgmentMap.hidden = false;
      judgmentMap.innerHTML = visibleItems.map((item) => {
        const evidence = (item.evidence || []).map((value) => String(value || "").trim()).filter(Boolean)[0] || "";
        const mapped = item.mapped === true;
        return `
          <div class="alignment-judgment-row" data-mapped="${mapped}">
            <strong>${escapeHtml(traceItemLabel(item))}</strong>
            <span>${escapeHtml(mapped ? surfaceSummary(item.surfaces) : localeText("缺少可运行映射", "Missing runnable mapping"))}</span>
            ${evidence ? `<span>${escapeHtml(evidence)}</span>` : ""}
          </div>
        `;
      }).join("");
    }
    const visibleDiagnostics = (diagnostics || [])
      .filter((item) => item && String(item.severity || "") !== "info")
      .slice(0, 3);
    if (!visibleDiagnostics.length) {
      diagnosticsStrip.hidden = true;
      diagnosticsStrip.innerHTML = "";
      return;
    }
    diagnosticsStrip.hidden = false;
    diagnosticsStrip.innerHTML = visibleDiagnostics.map((item) => `
      <div class="alignment-diagnostic-row">
        <strong>${escapeHtml(localizedDiagnosticText(item, "title"))}</strong>
        <span>${escapeHtml(localizedDiagnosticText(item, "message"))}</span>
      </div>
    `).join("");
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
        label: localeText("Loopora 适配", "Loopora fit"),
        value: listSnippet(summary.loop_fit_reasons)
          || localeText("长期治理理由未声明。", "Long-running governance reason not declared."),
      },
      {
        label: localeText("成功面", "Success"),
        value: listSnippet(summary.success_surface)
          || localeText("按 Done When 与任务成功面裁决。", "Judged by Done When and the success surface."),
      },
      {
        label: localeText("假完成", "Fake done"),
        value: listSnippet(summary.fake_done_risks)
          || localeText("未声明额外假完成风险。", "No extra fake-done risks declared."),
      },
      {
        label: localeText("证据偏好", "Evidence preferences"),
        value: listSnippet(summary.evidence_preferences)
          || localeText("按任务契约选择证据。", "Evidence follows the task contract."),
      },
      {
        label: localeText("覆盖目标", "Coverage targets"),
        value: coverageSummary(summary)
          || localeText("由 Done When 和裁决面派生。", "Derived from Done When and verdict surfaces."),
      },
      {
        label: localeText("主要风险", "Main risk"),
        value: listSnippet(summary.risks) || localeText("从 Loop 契约中读取。", "Read from spec."),
      },
      {
        label: localeText("残余风险", "Residual risk"),
        value: listSnippet(summary.residual_risk_policy)
          || localeText("按任务契约失败关闭。", "Fail closed by the task contract."),
      },
      {
        label: localeText("执行策略", "Execution strategy"),
        value: listSnippet(summary.execution_strategy)
          || localeText("下一轮优先级未声明。", "Next-round priority not declared."),
      },
      {
        label: localeText("判断取舍", "Tradeoffs"),
        value: listSnippet(summary.judgment_tradeoffs)
          || localeText("按任务契约裁决。", "Judged by the task contract."),
      },
      {
        label: localeText("角色姿态", "Role posture"),
        value: listSnippet(summary.role_postures)
          || localeText("角色执行姿态未声明。", "Role posture not declared."),
      },
      {
        label: localeText("证据路径", "Evidence path"),
        value: listSnippet(summary.evidence) || localeText("由运行流程落账。", "Recorded during the run flow."),
      },
      ...(Array.isArray(summary.local_governance) && summary.local_governance.length ? [{
        label: localeText("本地治理", "Local governance"),
        value: listSnippet(summary.local_governance),
      }] : []),
      {
        label: localeText("运行流程", "Run flow"),
        value: workflow.summary || localeText(`${workflow.step_count || 0} 个步骤`, `${workflow.step_count || 0} steps`),
      },
      {
        label: localeText("守门者", "GateKeeper"),
        value: gatekeeper.enabled === true
          ? localeText("需要证据引用才能结束。", "Requires evidence refs to finish.")
          : localeText("未配置守门者。", "No GateKeeper configured."),
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
    return description || posture || localeText("点击查看完整角色信息。", "Open to inspect the full role definition.");
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
    artifactName.textContent = metadata.name || localeText("Loop 方案", "Loop plan");
    previewTitle.textContent = localeText("方案预览已准备好", "Plan preview is ready");
    readyNote.textContent = "";
    previewImportButton.hidden = false;
    const summary = payload.control_summary || {};
    const diagnostics = payload.diagnostics || summary.diagnostics || [];
    artifactRoles.textContent = labeledSummary("角色", "Roles", localeText(`${(payload.roles || []).length} 个`, `${(payload.roles || []).length}`));
    if (artifactVerdict) {
      artifactVerdict.textContent = labeledSummary("裁决", "Verdict", verdictSummary(summary));
    }
    if (artifactJudgment) {
      artifactJudgment.textContent = labeledSummary("判断", "Judgment", judgmentStatus({...summary, diagnostics}));
    }
    artifactWorkdir.textContent = labeledSummary("目录", "Workdir", basename(payload.bundle?.loop?.workdir || ""));
    artifactWorkdir.title = payload.bundle?.loop?.workdir || "";
    renderControlSummary(summary);
    renderJudgmentMap(payload.traceability || summary.traceability || {}, diagnostics);
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
      sourcePathLabel.textContent = "";
      sourcePathLabel.title = payload.source_path || "";
    }
    roleList.innerHTML = "";
    (payload.roles || []).forEach((role) => {
      roleList.append(renderRoleCard(role));
    });
    if (window.LooporaWorkflowDiagram) {
      window.LooporaWorkflowDiagram.renderInto(workflowDiagram, payload.workflow_preview || {}, {variant: "editor"});
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
      showImportError(localeText("请填写方案文件路径或粘贴方案文件内容。", "Provide a plan file path or paste plan file content."));
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
        throw new Error(preview.error || localeText("方案文件预览失败。", "Plan file preview failed."));
      }
      renderBundlePreview(preview);
    } catch (error) {
      showImportError(error.message || localeText("方案文件预览失败。", "Plan file preview failed."));
    } finally {
      previewButton.disabled = false;
    }
  }

  previewButton?.addEventListener("click", () => {
    previewBundle().catch((error) => {
      showImportError(error.message || localeText("方案文件预览失败。", "Plan file preview failed."));
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
