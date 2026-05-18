document.addEventListener("DOMContentLoaded", () => {
  if (!window.LooporaUI) {
    return;
  }

  const wakeLockToggle = document.getElementById("wake-lock-toggle");
  const wakeLockStatusBox = document.getElementById("wake-lock-status");
  const wakeLockRuntimePill = document.getElementById("wake-lock-runtime-pill");
  const wakeLockHoldPill = document.getElementById("wake-lock-hold-pill");
  const wakeLockRuns = document.getElementById("wake-lock-runs");
  const localAssetsStatusBox = document.getElementById("local-assets-status");
  const localAssetsCountNodes = Array.from(document.querySelectorAll("[data-local-assets-count]"));
  const localAssetsDetails = document.getElementById("local-assets-details");
  const localAssetsToggle = document.getElementById("local-assets-toggle");
  const agentAdapterStatusBox = document.getElementById("agent-adapter-status");
  const agentAdapterWorkdirInput = document.getElementById("agent-adapter-workdir");
  const agentAdapterTargetNote = document.getElementById("agent-adapter-target-note");
  const agentAdapterHandoff = document.getElementById("agent-adapter-handoff");
  const agentAdapterRefreshButton = document.querySelector("[data-testid='agent-adapter-refresh']");
  const agentAdapterCards = Array.from(document.querySelectorAll("[data-agent-adapter]"));
  const agentAdapterStatusNodes = Array.from(document.querySelectorAll("[data-agent-adapter-status]"));
  const agentAdapterInstallButtons = Array.from(document.querySelectorAll("[data-agent-adapter-install]"));
  const agentAdapterUninstallButtons = Array.from(document.querySelectorAll("[data-agent-adapter-uninstall]"));
  const WAKE_LOCK_PREF_KEY = "loopora:tools:wake-lock-enabled";
  const AGENT_ADAPTER_WORKDIR_PREF_KEY = "loopora:tools:agent-adapter-workdir";
  let wakeLockSentinel = null;
  let runtimeActivity = {
    running_count: 0,
    queued_count: 0,
    has_running_runs: false,
    has_active_runs: false,
    runs: [],
  };
  let runtimeActivitySignature = JSON.stringify(runtimeActivity);
  let preferredAgentAdapterHandoff = "";
  let localAssetsDetailsExpanded = false;
  let localAssetsIssueTotal = 0;

  function localeText(zh, en) {
    return window.LooporaUI.pickText({zh, en});
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function showStatus(box, message, kind = "") {
    if (!box) {
      return;
    }
    const nextClassName = `field-status${kind ? ` is-${kind}` : ""}`;
    if (!message) {
      if (box.hidden && box.textContent === "" && box.className === "field-status") {
        return;
      }
      box.hidden = true;
      box.textContent = "";
      box.className = "field-status";
      return;
    }
    if (!box.hidden && box.textContent === message && box.className === nextClassName) {
      return;
    }
    box.hidden = false;
    box.textContent = message;
    box.className = nextClassName;
  }

  function updateNodeTextAndClass(node, text, className) {
    if (!node) {
      return;
    }
    if (node.textContent === text && node.className === className) {
      return;
    }
    node.textContent = text;
    node.className = className;
  }

  function fetchJson(url, options = {}) {
    return fetch(url, options).then(async (response) => {
      const payload = await response.json().catch(() => ({}));
      return {response, payload};
    });
  }

  function parentPath(path) {
    const value = String(path || "").replace(/[\\/]+$/, "");
    if (!value) {
      return "";
    }
    const slashIndex = Math.max(value.lastIndexOf("/"), value.lastIndexOf("\\"));
    if (slashIndex <= 0) {
      return value;
    }
    return value.slice(0, slashIndex);
  }

  function renderLocalAssetDiagnostics(payload) {
    let total = 0;
    for (const node of localAssetsCountNodes) {
      const key = String(node.dataset.localAssetsCount || "");
      const count = Array.isArray(payload?.[key]) ? payload[key].length : 0;
      total += count;
      const label = key === "orphan_alignment_dirs"
        ? localeText("对话编排残留目录", "Conversation orphan dirs")
        : key === "orphan_bundle_dirs"
          ? localeText("方案文件残留目录", "Plan file orphan dirs")
          : key === "orphan_run_dirs"
            ? localeText("运行残留目录", "Run orphan dirs")
            : localeText("记录缺失目录", "Records missing dirs");
      node.textContent = `${label}: ${count}`;
      node.className = `wake-lock-pill ${count > 0 ? "wake-lock-pill-warning" : "wake-lock-pill-neutral"}`;
    }
    localAssetsIssueTotal = total;
    updateLocalAssetsToggle();
    renderLocalAssetDetails(payload, total);
  }

  function updateLocalAssetsToggle() {
    if (!localAssetsToggle) {
      return;
    }
    if (!localAssetsIssueTotal) {
      localAssetsToggle.hidden = true;
      localAssetsToggle.setAttribute("aria-expanded", "false");
      return;
    }
    localAssetsToggle.hidden = false;
    localAssetsToggle.setAttribute("aria-expanded", String(localAssetsDetailsExpanded));
    localAssetsToggle.textContent = localAssetsDetailsExpanded
      ? localeText("收起维护明细", "Hide maintenance details")
      : localeText(
        `查看 ${localAssetsIssueTotal} 项维护明细`,
        `Review ${localAssetsIssueTotal} maintenance ${localAssetsIssueTotal === 1 ? "detail" : "details"}`,
      );
  }

  function localAssetIssueConfig(key) {
    const configs = {
      orphan_alignment_dirs: {
        title: localeText("对话编排残留目录", "Conversation orphan directories"),
        idLabel: localeText("对话", "Conversation"),
        idField: "session_id",
        action: localeText("打开目录", "Open folder"),
        suggestion: localeText(
          "建议先检查 transcript、events 和 artifacts；确认这次对话已不需要后，再在文件管理器中手动清理。",
          "Inspect transcript, events, and artifacts first; once the chat is no longer needed, clean it up manually in your file manager.",
        ),
      },
      orphan_bundle_dirs: {
        title: localeText("方案文件残留目录", "Plan file orphan directories"),
        idLabel: localeText("方案文件", "Plan file"),
        idField: "bundle_id",
        action: localeText("打开目录", "Open folder"),
        suggestion: localeText(
          "建议打开目录确认里面是否还有要导出的方案文件；确认无用后手动清理。",
          "Open the folder and check whether any plan files still need to be exported; clean it manually once it is safe.",
        ),
      },
      orphan_run_dirs: {
        title: localeText("运行残留目录", "Run orphan directories"),
        idLabel: localeText("运行", "Run"),
        idField: "run_id",
        action: localeText("打开目录", "Open folder"),
        suggestion: localeText(
          "建议先检查 evidence、timeline 或输出文件；确认运行证据已迁移或不再需要后手动清理。",
          "Inspect evidence, timeline, or output files first; clean it manually after the run evidence is migrated or no longer needed.",
        ),
      },
      record_without_dir: {
        title: localeText("记录缺失目录", "Records missing directories"),
        idLabel: localeText("记录", "Record"),
        idField: "resource_id",
        action: localeText("打开上级目录", "Open parent folder"),
        suggestion: localeText(
          "这通常表示目录被外部移动或删除；建议确认记录是否仍要保留，必要时重新运行、重新导入或重新开始对话来重建目录。",
          "This usually means the folder was moved or removed externally; decide whether to keep the record, then rerun, reimport, or restart the chat if the directory must be recreated.",
        ),
      },
    };
    return configs[key] || {
      title: key,
      idLabel: "id",
      idField: "id",
      action: localeText("打开目录", "Open folder"),
      suggestion: "",
    };
  }

  function localAssetIssueMeta(key, item) {
    const config = localAssetIssueConfig(key);
    const id = String(item?.[config.idField] || item?.resource_id || item?.path || "-");
    const type = item?.resource_type ? `${item.resource_type} · ` : "";
    const source = item?.source ? ` · ${item.source}` : "";
    const workdir = item?.workdir ? ` · ${item.workdir}` : "";
    return `${config.idLabel}: ${type}${id}${source}${workdir}`;
  }

  function renderLocalAssetDetails(payload, total) {
    if (!localAssetsDetails) {
      return;
    }
    if (!total) {
      localAssetsDetailsExpanded = false;
      localAssetsDetails.hidden = true;
      localAssetsDetails.innerHTML = "";
      return;
    }
    const keys = ["orphan_alignment_dirs", "orphan_bundle_dirs", "orphan_run_dirs", "record_without_dir"];
    const sections = keys.map((key) => {
      const items = Array.isArray(payload?.[key]) ? payload[key] : [];
      if (!items.length) {
        return "";
      }
      const config = localAssetIssueConfig(key);
      const rows = items.map((item) => {
        const path = String(item?.path || "");
        const revealPath = key === "record_without_dir" ? parentPath(path) : path;
        return `
          <article class="local-assets-issue" data-testid="local-assets-issue" data-local-assets-kind="${escapeHtml(key)}">
            <div class="local-assets-issue-copy">
              <strong>${escapeHtml(localAssetIssueMeta(key, item))}</strong>
              <code>${escapeHtml(path || "-")}</code>
              <p>${escapeHtml(config.suggestion)}</p>
            </div>
            <div class="local-assets-issue-actions">
              <button
                class="secondary-button"
                type="button"
                data-local-assets-reveal-path="${escapeHtml(revealPath)}"
                data-local-assets-copy-path="${escapeHtml(path)}"
                data-testid="local-assets-reveal-button"
                ${revealPath ? "" : "disabled"}
              >${escapeHtml(config.action)}</button>
              <button
                class="ghost-button"
                type="button"
                data-local-assets-copy-path="${escapeHtml(path)}"
                data-testid="local-assets-copy-button"
              >${escapeHtml(localeText("复制路径", "Copy path"))}</button>
            </div>
          </article>
        `;
      }).join("");
      return `
        <section class="local-assets-issue-group" data-testid="local-assets-issue-group">
          <header>
            <strong>${escapeHtml(config.title)}</strong>
            <span>${items.length}</span>
          </header>
          <div class="local-assets-issue-list">${rows}</div>
        </section>
      `;
    }).join("");
    localAssetsDetails.hidden = !localAssetsDetailsExpanded;
    localAssetsDetails.innerHTML = `
      <div class="local-assets-guidance">
        <strong>${escapeHtml(localeText("发现本地资产不一致", "Local asset mismatch found"))}</strong>
        <span>${escapeHtml(localeText("下面的动作只会定位或复制路径，不会删除文件或修改记录。", "These actions only reveal or copy paths; they do not delete files or modify records."))}</span>
      </div>
      ${sections}
    `;
  }

  async function copyText(value) {
    await navigator.clipboard.writeText(value);
  }

  async function revealLocalAssetPath(path, copyFallbackPath = path) {
    if (!path && copyFallbackPath) {
      await copyText(copyFallbackPath);
      showStatus(localAssetsStatusBox, localeText("路径已复制到剪贴板。", "Path copied to clipboard."), "success");
      return;
    }
    try {
      const {response, payload} = await fetchJson("/api/system/reveal-path", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({path}),
      });
      if (!response.ok) {
        throw new Error(payload.error || "failed");
      }
      showStatus(localAssetsStatusBox, localeText("已打开对应目录。", "Opened the corresponding folder."), "success");
    } catch (error) {
      try {
        await copyText(copyFallbackPath || path);
        showStatus(
          localAssetsStatusBox,
          localeText("无法自动打开，路径已复制到剪贴板。", "Could not open automatically; the path was copied to clipboard."),
          "warning",
        );
      } catch (_) {
        showStatus(
          localAssetsStatusBox,
          error?.message || localeText("无法打开目录。", "Unable to open the folder."),
          "error",
        );
      }
    }
  }

  async function refreshLocalAssetDiagnostics(options = {}) {
    const quiet = options.quiet ?? false;
    const {response, payload} = await fetchJson("/api/diagnostics/local-assets");
    if (!response.ok) {
      if (!quiet) {
        showStatus(localAssetsStatusBox, payload.error || localeText("无法读取本地资产诊断。", "Unable to load local asset diagnostics."), "error");
      }
      return;
    }
    renderLocalAssetDiagnostics(payload);
    showStatus(localAssetsStatusBox, "");
  }

  function agentAdapterStatusLabel(status) {
    const labels = {
      installed: localeText("已安装", "Installed"),
      not_installed: localeText("未安装", "Not installed"),
      needs_update: localeText("需要更新", "Needs update"),
      error: localeText("不可判断", "Needs attention"),
      not_implemented: localeText("未实现", "Not implemented"),
    };
    return labels[status] || localeText("未知状态", "Unknown");
  }

  function agentAdapterPillClass(status) {
    if (status === "installed") {
      return "wake-lock-pill wake-lock-pill-held";
    }
    if (status === "needs_update") {
      return "wake-lock-pill wake-lock-pill-queued";
    }
    if (status === "error") {
      return "wake-lock-pill wake-lock-pill-warning";
    }
    return "wake-lock-pill wake-lock-pill-neutral";
  }

  function renderAgentAdapters(payload) {
    updateAgentAdapterTargetNote(payload);
    const adapters = Array.isArray(payload?.adapters) ? payload.adapters : [payload].filter(Boolean);
    const byKind = new Map(adapters.map((item) => [String(item?.adapter || ""), item]));
    const implementedFallbacks = new Set(["codex", "claude", "opencode"]);
    for (const node of agentAdapterStatusNodes) {
      const adapter = String(node.dataset.agentAdapterStatus || "");
      const item = byKind.get(adapter);
      const status = String(item?.status || (implementedFallbacks.has(adapter) ? "not_installed" : "not_implemented"));
      node.dataset.agentAdapterState = status;
      updateNodeTextAndClass(node, agentAdapterStatusLabel(status), agentAdapterPillClass(status));
    }
    for (const card of agentAdapterCards) {
      const adapter = String(card.dataset.agentAdapter || "");
      const item = byKind.get(adapter);
      const status = String(item?.status || (implementedFallbacks.has(adapter) ? "not_installed" : "not_implemented"));
      card.dataset.agentAdapterState = status;
      card.classList.toggle("is-disabled", status === "not_implemented");
      card.classList.toggle("is-error", status === "error");
    }
    for (const button of agentAdapterInstallButtons) {
      const adapter = String(button.dataset.agentAdapterInstall || "");
      const item = byKind.get(adapter);
      button.disabled = item?.implemented === false;
    }
    for (const button of agentAdapterUninstallButtons) {
      const adapter = String(button.dataset.agentAdapterUninstall || "");
      const item = byKind.get(adapter);
      button.disabled = item?.implemented === false || item?.status === "not_installed";
    }
    renderAgentAdapterHandoff(payload, adapters);
  }

  function agentAdapterLabel(adapter) {
    const labels = {
      codex: "Codex",
      claude: "Claude Code",
      opencode: "OpenCode",
    };
    return labels[adapter] || adapter || "Agent";
  }

  function updateAgentAdapterTargetNote(payload) {
    if (!agentAdapterTargetNote) {
      return;
    }
    const workdir = String(payload?.workdir || "").trim();
    if (!workdir) {
      agentAdapterTargetNote.textContent = localeText(
        "通常填写你会运行 Codex、Claude Code 或 OpenCode 的项目目录；留空会使用服务当前目录。",
        "Usually set the project directory where you will run Codex, Claude Code, or OpenCode; blank uses the server current directory.",
      );
      agentAdapterTargetNote.title = "";
      return;
    }
    agentAdapterTargetNote.textContent = localeText(
      `实际安装目标：${workdir}。确认这是 Agent 将工作的项目。`,
      `Install target: ${workdir}. Confirm this is the project where the Agent will work.`,
    );
    agentAdapterTargetNote.title = workdir;
  }

  function agentAdapterInstallSuccessMessage(label) {
    return localeText(
      `${label} 接入已安装或更新。回到 ${label}，说明任务目标、伪完成风险和必需证据后运行 /loopora-gen；预览 READY 并审查后，在同一 Agent 会话运行 /loopora-loop。`,
      `${label} entry is installed or updated. Return to ${label} with the task goal, fake-done risk, and required evidence before /loopora-gen; after the READY preview is reviewed, run /loopora-loop in the same Agent session.`,
    );
  }

  function adapterConflictPaths(message) {
    const marker = "adapter files:";
    if (!message || !message.includes(marker)) {
      return [];
    }
    return message.split(marker, 2)[1].split(",").map((part) => part.trim()).filter(Boolean);
  }

  function agentAdapterFailureMessage(adapter, label, action, error) {
    const message = String(error?.message || "");
    const paths = adapterConflictPaths(message);
    if (action === "install" && paths.length) {
      return localeText(
        `${label} 接入未安装。Loopora 发现这些入口文件不是自己管理的，因此没有覆盖：${paths.join("，")}。请先检查、移动或重命名这些文件，或换一个目标项目目录，然后重新安装。`,
        `${label} entry was not installed. Loopora found entry files it does not own, so it left them unchanged: ${paths.join(", ")}. Inspect, move, or rename those files, or choose another target project, then install again.`,
      );
    }
    return message || localeText("Agent 接入操作失败。", "Agent entry action failed.");
  }

  function handoffStatusLabel(status) {
    return status === "needs_update"
      ? localeText("需要更新", "Needs update")
      : localeText("已安装", "Installed");
  }

  function handoffTitle(label, status) {
    if (status === "needs_update") {
      return localeText(
        `${label} 入口需要更新`,
        `${label} entry needs an update`,
      );
    }
    return localeText(
      `${label} 入口已接好`,
      `${label} entry is ready`,
    );
  }

  function managedFileStateLabel(state) {
    const labels = {
      current: localeText("当前", "current"),
      needs_update: localeText("需更新", "needs update"),
      missing: localeText("缺失", "missing"),
      unmanaged_conflict: localeText("冲突", "conflict"),
      error: localeText("错误", "error"),
    };
    return labels[state] || state || localeText("未知", "unknown");
  }

  function handoffCandidate(adapters) {
    const ready = adapters.filter((item) => {
      const status = String(item?.status || "");
      return item?.implemented !== false && (status === "installed" || status === "needs_update");
    });
    if (!ready.length) {
      return null;
    }
    if (preferredAgentAdapterHandoff) {
      const preferred = ready.find((item) => String(item?.adapter || "") === preferredAgentAdapterHandoff);
      if (preferred) {
        return preferred;
      }
    }
    return ready.find((item) => String(item?.status || "") === "installed") || ready[0];
  }

  function renderAgentAdapterHandoff(payload, adapters) {
    if (!agentAdapterHandoff) {
      return;
    }
    const item = handoffCandidate(adapters);
    if (!item) {
      agentAdapterHandoff.hidden = true;
      agentAdapterHandoff.innerHTML = "";
      return;
    }
    const adapter = String(item.adapter || "");
    const label = String(item.label || agentAdapterLabel(adapter));
    const status = String(item.status || "installed");
    const workdir = String(item.workdir || payload?.workdir || agentAdapterWorkdir() || "").trim();
    const manifestPath = String(item.manifest_path || "").trim();
    const managedFiles = Array.isArray(item.managed_files) ? item.managed_files : [];
    const currentCount = managedFiles.filter((file) => String(file?.state || "") === "current").length;
    const fileRows = managedFiles.map((file) => {
      const path = String(file?.path || "");
      const state = String(file?.state || "");
      return `
        <span class="agent-adapter-managed-file" data-testid="agent-adapter-managed-file">
          <code>${escapeHtml(path || "-")}</code>
          <span>${escapeHtml(managedFileStateLabel(state))}</span>
        </span>
      `;
    }).join("");
    const proofSummary = managedFiles.length
      ? localeText(
        `入口文件：${currentCount}/${managedFiles.length} 个为当前版本`,
        `Entry files: ${currentCount}/${managedFiles.length} current`,
      )
      : localeText("入口文件状态暂不可用", "Entry file status is not available yet");
    agentAdapterHandoff.hidden = false;
    agentAdapterHandoff.innerHTML = `
      <div class="agent-adapter-handoff-head">
        <div>
          <strong data-testid="agent-adapter-handoff-title">${escapeHtml(handoffTitle(label, status))}</strong>
          <span data-testid="agent-adapter-handoff-target">${escapeHtml(localeText("目标项目", "Target project"))}: ${escapeHtml(workdir || "-")}</span>
        </div>
        <span class="${escapeHtml(agentAdapterPillClass(status))}">${escapeHtml(handoffStatusLabel(status))}</span>
      </div>
      <div class="agent-adapter-judgment-brief" data-testid="agent-adapter-judgment-brief">
        <strong>${escapeHtml(localeText("把任务判断交给 /loopora-gen，不只是任务标题。", "Give /loopora-gen the task judgment, not just a task title."))}</strong>
        <ul>
          <li><span>${escapeHtml(localeText("目标", "Goal"))}</span>${escapeHtml(localeText("要证明的用户结果", "User result to prove"))}</li>
          <li><span>${escapeHtml(localeText("伪完成", "Fake done"))}</span>${escapeHtml(localeText("看似完成但必须阻断的状态", "Looks done but must block"))}</li>
          <li><span>${escapeHtml(localeText("证据", "Evidence"))}</span>${escapeHtml(localeText("哪些记录、测试或产物才算够硬", "Records, tests, or artifacts that count"))}</li>
        </ul>
      </div>
      <div class="agent-adapter-command-flow" data-testid="agent-adapter-handoff-flow">
        <button
          class="agent-adapter-command-button"
          type="button"
          data-agent-adapter-command-copy="/loopora-gen"
          data-copy-value="/loopora-gen"
          data-testid="agent-adapter-copy-gen"
          aria-label="${escapeHtml(localeText("复制 /loopora-gen", "Copy /loopora-gen"))}"
        >
          <span>1</span>
          <code>/loopora-gen</code>
        </button>
        <span class="agent-adapter-command-then">${escapeHtml(localeText("审查 READY Loop 预览", "Review READY Loop preview"))}</span>
        <button
          class="agent-adapter-command-button"
          type="button"
          data-agent-adapter-command-copy="/loopora-loop"
          data-copy-value="/loopora-loop"
          data-testid="agent-adapter-copy-loop"
          aria-label="${escapeHtml(localeText("复制 /loopora-loop", "Copy /loopora-loop"))}"
        >
          <span>2</span>
          <code>/loopora-loop</code>
        </button>
      </div>
      <p class="agent-adapter-handoff-note" data-testid="agent-adapter-handoff-note">
        ${escapeHtml(localeText(
          "只有预览匹配这些判断后才运行 /loopora-loop；Web 用来观察证据、缺口和裁决，执行仍回到同一个 Agent。",
          "Run /loopora-loop only after the preview matches those judgments; Web observes evidence, gaps, and verdicts while execution stays in the same Agent.",
        ))}
      </p>
      <div class="agent-adapter-install-proof" data-testid="agent-adapter-install-proof">
        <strong>${escapeHtml(proofSummary)}</strong>
        <div class="agent-adapter-managed-files">
          ${fileRows}
          ${manifestPath ? `<span class="agent-adapter-managed-file" data-testid="agent-adapter-manifest-path"><code>${escapeHtml(manifestPath)}</code><span>manifest</span></span>` : ""}
        </div>
      </div>
    `;
  }

  function readAgentAdapterWorkdirPreference() {
    try {
      return window.localStorage.getItem(AGENT_ADAPTER_WORKDIR_PREF_KEY) || "";
    } catch (_) {
      return "";
    }
  }

  function persistAgentAdapterWorkdirPreference(value) {
    try {
      window.localStorage.setItem(AGENT_ADAPTER_WORKDIR_PREF_KEY, value);
    } catch (_) {
      // Ignore storage failures.
    }
  }

  function agentAdapterWorkdir() {
    return String(agentAdapterWorkdirInput?.value || "").trim();
  }

  function agentAdapterStatusUrl() {
    const workdir = agentAdapterWorkdir();
    if (!workdir) {
      return "/api/agent-adapters";
    }
    return `/api/agent-adapters?workdir=${encodeURIComponent(workdir)}`;
  }

  function agentAdapterMutationBody() {
    const workdir = agentAdapterWorkdir();
    return JSON.stringify(workdir ? {workdir} : {});
  }

  async function refreshAgentAdapters(options = {}) {
    const quiet = options.quiet ?? false;
    const {response, payload} = await fetchJson(agentAdapterStatusUrl());
    if (!response.ok) {
      if (!quiet) {
        showStatus(agentAdapterStatusBox, payload.error || localeText("无法读取 Agent 接入状态。", "Unable to load Agent entry status."), "error");
      }
      return;
    }
    renderAgentAdapters(payload);
    if (!quiet) {
      showStatus(agentAdapterStatusBox, "");
    }
  }

  async function mutateAgentAdapter(adapter, action, trigger) {
    const originalDisabled = trigger.disabled;
    let applied = false;
    trigger.disabled = true;
    const label = agentAdapterLabel(adapter);
    showStatus(
      agentAdapterStatusBox,
      action === "install"
        ? localeText(`正在安装 ${label} 接入…`, `Installing ${label} entry…`)
        : localeText(`正在卸载 ${label} 接入…`, `Uninstalling ${label} entry…`),
    );
    try {
      const {response, payload} = await fetchJson(`/api/agent-adapters/${encodeURIComponent(adapter)}/${action}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: agentAdapterMutationBody(),
      });
      if (!response.ok) {
        throw new Error(payload.error || "failed");
      }
      preferredAgentAdapterHandoff = action === "install" ? adapter : "";
      renderAgentAdapters(payload);
      applied = true;
      showStatus(
        agentAdapterStatusBox,
        action === "install"
          ? agentAdapterInstallSuccessMessage(label)
          : localeText(`${label} 接入已卸载。`, `${label} entry is uninstalled.`),
        "success",
      );
      await refreshAgentAdapters({quiet: true});
    } catch (error) {
      showStatus(
        agentAdapterStatusBox,
        agentAdapterFailureMessage(adapter, label, action, error),
        "error",
      );
    } finally {
      if (!applied) {
        trigger.disabled = originalDisabled;
      }
    }
  }

  function readWakeLockPreference() {
    try {
      return window.localStorage.getItem(WAKE_LOCK_PREF_KEY) === "1";
    } catch (_) {
      return false;
    }
  }

  function persistWakeLockPreference(enabled) {
    try {
      window.localStorage.setItem(WAKE_LOCK_PREF_KEY, enabled ? "1" : "0");
    } catch (_) {
      // Ignore storage failures.
    }
  }

  function supportsWakeLock() {
    return Boolean(navigator.wakeLock && typeof navigator.wakeLock.request === "function");
  }

  function displayIter(value, fallback = 1) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed < 0) {
      return fallback;
    }
    return Math.floor(parsed) + 1;
  }

  function updateWakeLockRuntimePill() {
    if (!wakeLockRuntimePill) {
      return;
    }
    const runningCount = Number(runtimeActivity.running_count || 0);
    const queuedCount = Number(runtimeActivity.queued_count || 0);
    let className = "wake-lock-pill wake-lock-pill-neutral";
    let text = localeText("当前没有活动运行", "No runs are currently executing");
    if (runningCount > 0) {
      className = "wake-lock-pill wake-lock-pill-running";
      text = localeText(
        `检测到 ${runningCount} 个活动运行${queuedCount ? `，另有 ${queuedCount} 个排队中` : ""}`,
        `${runningCount} running run(s) detected${queuedCount ? `, plus ${queuedCount} queued` : ""}`
      );
    } else if (queuedCount > 0) {
      className = "wake-lock-pill wake-lock-pill-queued";
      text = localeText(`当前有 ${queuedCount} 个运行在排队`, `${queuedCount} queued run(s) detected`);
    }
    updateNodeTextAndClass(wakeLockRuntimePill, text, className);
  }

  function updateWakeLockHoldPill() {
    if (!wakeLockHoldPill || !wakeLockToggle) {
      return;
    }
    if (!supportsWakeLock()) {
      updateNodeTextAndClass(
        wakeLockHoldPill,
        localeText("当前浏览器不支持防休眠锁", "This browser does not support the Wake Lock API"),
        "wake-lock-pill wake-lock-pill-warning",
      );
      return;
    }
    if (!wakeLockToggle.checked) {
      updateNodeTextAndClass(
        wakeLockHoldPill,
        localeText("防休眠开关处于关闭状态", "Wake lock is currently turned off"),
        "wake-lock-pill wake-lock-pill-neutral",
      );
      return;
    }
    if (wakeLockSentinel) {
      updateNodeTextAndClass(
        wakeLockHoldPill,
        localeText("已持有防休眠锁", "Wake lock is currently held"),
        "wake-lock-pill wake-lock-pill-held",
      );
      return;
    }
    if (document.visibilityState !== "visible") {
      updateNodeTextAndClass(
        wakeLockHoldPill,
        localeText("页面不可见，等待重新获取", "Waiting to reacquire once the page is visible again"),
        "wake-lock-pill wake-lock-pill-neutral",
      );
      return;
    }
    if (Number(runtimeActivity.running_count || 0) > 0) {
      updateNodeTextAndClass(
        wakeLockHoldPill,
        localeText("检测到活动运行，正在等待获取防休眠锁", "A run is active; waiting to acquire the wake lock"),
        "wake-lock-pill wake-lock-pill-neutral",
      );
      return;
    }
    updateNodeTextAndClass(
      wakeLockHoldPill,
        localeText("已开启，等有活动运行时再生效", "Enabled and standing by until a run is actively executing"),
      "wake-lock-pill wake-lock-pill-neutral",
    );
  }

  function renderRuntimeRuns() {
    if (!wakeLockRuns) {
      return;
    }
    const runs = Array.isArray(runtimeActivity.runs) ? runtimeActivity.runs : [];
    if (!runs.length) {
      wakeLockRuns.innerHTML = `
        <div class="wake-lock-empty">
          <span data-lang="zh">当前没有活动运行，这个开关会保持待命。</span>
          <span data-lang="en">There are no active runs right now, so the wake lock stays on standby.</span>
        </div>
      `;
      return;
    }
    wakeLockRuns.innerHTML = runs.map((run) => {
      const role = run.active_role ? window.LooporaUI.translateRole(run.active_role) : localeText("等待调度", "Waiting");
      const status = window.LooporaUI.translateStatus(run.status || "queued");
      const iter = localeText(`第 ${displayIter(run.current_iter)} 轮`, `Round ${displayIter(run.current_iter)}`);
      return `
        <a class="wake-lock-run-card" href="/runs/${encodeURIComponent(run.id)}">
          <div class="wake-lock-run-head">
            <strong>${escapeHtml(run.loop_name || run.id)}</strong>
            <span class="wake-lock-run-state wake-lock-run-state-${escapeHtml(run.status || "queued")}">${escapeHtml(status)}</span>
          </div>
          <p class="wake-lock-run-meta">${escapeHtml(role)} · ${escapeHtml(iter)}</p>
          <p class="wake-lock-run-path">${escapeHtml(run.workdir || "")}</p>
        </a>
      `;
    }).join("");
  }

  async function releaseWakeLock() {
    if (!wakeLockSentinel) {
      updateWakeLockHoldPill();
      return;
    }
    const current = wakeLockSentinel;
    wakeLockSentinel = null;
    try {
      await current.release();
    } catch (_) {
      // Ignore release errors; the sentinel is no longer useful either way.
    }
    updateWakeLockHoldPill();
  }

  async function syncWakeLock() {
    updateWakeLockHoldPill();
    if (!wakeLockToggle || !wakeLockToggle.checked) {
      await releaseWakeLock();
      showStatus(wakeLockStatusBox, "");
      return;
    }
    if (!supportsWakeLock()) {
      showStatus(
        wakeLockStatusBox,
        localeText("这个浏览器不支持屏幕防休眠锁，所以这里只能显示运行状态，不能真正阻止休眠。", "This browser does not support the Screen Wake Lock API, so this page can show run activity but cannot actually keep the screen awake."),
        "warning",
      );
      return;
    }
    if (document.visibilityState !== "visible") {
      await releaseWakeLock();
      showStatus(
        wakeLockStatusBox,
        localeText("页面当前不可见；回到这个工具页后会自动重新尝试。", "The page is not visible right now. It will automatically retry once you come back to this Tools tab."),
      );
      return;
    }
    if (Number(runtimeActivity.running_count || 0) <= 0) {
      await releaseWakeLock();
      showStatus(
        wakeLockStatusBox,
        localeText("开关已经打开，但当前没有活动运行，所以不会主动持有防休眠锁。", "The toggle is on, but there is no actively running task right now, so no wake lock is being held."),
      );
      return;
    }
    if (wakeLockSentinel) {
      showStatus(
        wakeLockStatusBox,
        localeText("已检测到活动运行，屏幕会尽量保持唤醒。", "An active run is detected, so the page is currently trying to keep the screen awake."),
        "success",
      );
      updateWakeLockHoldPill();
      return;
    }
    try {
      wakeLockSentinel = await navigator.wakeLock.request("screen");
      wakeLockSentinel.addEventListener("release", () => {
        wakeLockSentinel = null;
        updateWakeLockHoldPill();
        if (wakeLockToggle.checked && document.visibilityState === "visible" && Number(runtimeActivity.running_count || 0) > 0) {
          window.setTimeout(() => {
            syncWakeLock().catch(() => {});
          }, 200);
        }
      });
      showStatus(
        wakeLockStatusBox,
        localeText("已持有防休眠锁；只要这个页面保持可见且仍有活动运行，就会继续阻止自动休眠。", "Wake lock acquired. As long as this page remains visible and a run is still active, the browser will keep trying to prevent automatic sleep."),
        "success",
      );
    } catch (error) {
      showStatus(
        wakeLockStatusBox,
        localeText(
          `没能拿到防休眠锁：${error?.message || "未知错误"}`,
          `Unable to acquire the wake lock: ${error?.message || "unknown error"}`
        ),
        "error",
      );
    }
    updateWakeLockHoldPill();
  }

  async function refreshRuntimeActivity(options = {}) {
    const quiet = options.quiet ?? false;
    const {response, payload} = await fetchJson("/api/runtime/activity");
    if (!response.ok) {
      if (!quiet) {
        showStatus(wakeLockStatusBox, payload.error || localeText("无法读取当前运行状态。", "Unable to load the current run activity."), "error");
      }
      return;
    }
    const nextSignature = JSON.stringify(payload || {});
    const changed = nextSignature !== runtimeActivitySignature;
    runtimeActivity = payload;
    runtimeActivitySignature = nextSignature;
    if (changed) {
      updateWakeLockRuntimePill();
      renderRuntimeRuns();
    }
    if (changed) {
      await syncWakeLock();
    }
  }

  wakeLockToggle.checked = readWakeLockPreference();
  updateWakeLockRuntimePill();
  updateWakeLockHoldPill();
  renderRuntimeRuns();

  localAssetsDetails?.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) {
      return;
    }
    const revealPath = target.dataset.localAssetsRevealPath || "";
    const copyPath = target.dataset.localAssetsCopyPath || "";
    if (target.dataset.localAssetsRevealPath !== undefined) {
      target.disabled = true;
      revealLocalAssetPath(revealPath, copyPath).finally(() => {
        target.disabled = false;
      });
      return;
    }
    if (target.dataset.localAssetsCopyPath !== undefined) {
      copyText(copyPath)
        .then(() => showStatus(localAssetsStatusBox, localeText("路径已复制到剪贴板。", "Path copied to clipboard."), "success"))
        .catch((error) => showStatus(localAssetsStatusBox, error?.message || localeText("无法复制路径。", "Unable to copy the path."), "error"));
    }
  });

  localAssetsToggle?.addEventListener("click", () => {
    if (!localAssetsIssueTotal || !localAssetsDetails) {
      return;
    }
    localAssetsDetailsExpanded = !localAssetsDetailsExpanded;
    localAssetsDetails.hidden = !localAssetsDetailsExpanded;
    updateLocalAssetsToggle();
  });

  for (const button of agentAdapterInstallButtons) {
    button.addEventListener("click", () => {
      mutateAgentAdapter(String(button.dataset.agentAdapterInstall || ""), "install", button);
    });
  }

  for (const button of agentAdapterUninstallButtons) {
    button.addEventListener("click", () => {
      mutateAgentAdapter(String(button.dataset.agentAdapterUninstall || ""), "uninstall", button);
    });
  }

  agentAdapterHandoff?.addEventListener("click", async (event) => {
    const button = event.target?.closest?.("[data-agent-adapter-command-copy]");
    if (!(button instanceof HTMLButtonElement)) {
      return;
    }
    const value = String(button.dataset.agentAdapterCommandCopy || button.dataset.copyValue || "").trim();
    if (!value) {
      return;
    }
    try {
      await copyText(value);
      button.classList.add("is-copied");
      showStatus(
        agentAdapterStatusBox,
        localeText(`已复制 ${value}。`, `${value} copied.`),
        "success",
      );
      window.setTimeout(() => button.classList.remove("is-copied"), 1400);
    } catch (error) {
      showStatus(
        agentAdapterStatusBox,
        error?.message || localeText("无法复制 Agent 命令。", "Unable to copy the Agent command."),
        "error",
      );
    }
  });

  if (agentAdapterWorkdirInput) {
    agentAdapterWorkdirInput.value = readAgentAdapterWorkdirPreference();
    agentAdapterWorkdirInput.addEventListener("change", () => {
      persistAgentAdapterWorkdirPreference(agentAdapterWorkdir());
      refreshAgentAdapters().catch(() => {});
    });
    agentAdapterWorkdirInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        persistAgentAdapterWorkdirPreference(agentAdapterWorkdir());
        refreshAgentAdapters().catch(() => {});
      }
    });
  }

  agentAdapterRefreshButton?.addEventListener("click", () => {
    persistAgentAdapterWorkdirPreference(agentAdapterWorkdir());
    refreshAgentAdapters().catch(() => {});
  });

  wakeLockToggle.addEventListener("change", async () => {
    persistWakeLockPreference(wakeLockToggle.checked);
    await syncWakeLock();
  });

  document.addEventListener("visibilitychange", () => {
    syncWakeLock().catch(() => {});
  });

  window.addEventListener("beforeunload", () => {
    releaseWakeLock().catch(() => {});
  });

  refreshRuntimeActivity({quiet: true});
  refreshAgentAdapters({quiet: true}).catch(() => {});
  refreshLocalAssetDiagnostics({quiet: true}).catch(() => {});
  window.setInterval(() => {
    refreshRuntimeActivity({quiet: true}).catch(() => {});
  }, 15000);

  document.addEventListener("loopora:localechange", () => {
    updateWakeLockRuntimePill();
    updateWakeLockHoldPill();
    renderRuntimeRuns();
    refreshAgentAdapters({quiet: true}).catch(() => {});
    refreshLocalAssetDiagnostics({quiet: true}).catch(() => {});
    syncWakeLock().catch(() => {});
  });
});
