document.addEventListener("DOMContentLoaded", () => {
  if (!window.LooporaUI || !window.LooporaRunConsoleBootstrap) {
    return;
  }

  const {runId, initialRun, initialConsoleEvents, latestEventId: initialLatestEventId} = window.LooporaRunConsoleBootstrap;
  const output = document.getElementById("console-focus-output");
  const shell = document.getElementById("console-focus-shell");
  const statusBadge = document.getElementById("console-focus-status");
  const lineCountNode = document.getElementById("console-focus-line-count");
  const filterGroup = document.getElementById("console-focus-filters");
  const expandAllButton = document.getElementById("console-focus-expand-all");
  const collapseAllButton = document.getElementById("console-focus-collapse-all");
  const MAX_CONSOLE_LINES = 640;
  const FILTER_OPTIONS = [
    {key: "status", zh: "状态", en: "Status"},
    {key: "actions", zh: "动作", en: "Actions"},
    {key: "result", zh: "结果", en: "Result"},
  ];
  const selectedFilters = new Set(FILTER_OPTIONS.map((item) => item.key));

  let currentRun = initialRun;
  let consoleEventRecords = Array.isArray(initialConsoleEvents) ? initialConsoleEvents.slice() : [];
  let lastEventId = Number(initialLatestEventId || 0);
  let autoScrollConsole = true;

  function localeText(zh, en) {
    return window.LooporaUI.pickText({zh, en});
  }

  function formatClock(value) {
    if (!value) {
      return "--:--:--";
    }
    return new Date(value).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  }

  function formatDurationMs(value) {
    const duration = Number(value);
    if (!Number.isFinite(duration) || duration < 0) {
      return "";
    }
    if (duration < 1000) {
      return `${Math.round(duration)}ms`;
    }
    return `${(duration / 1000).toFixed(duration >= 10_000 ? 0 : 1)}s`;
  }

  function displayIter(value, fallback = 1) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed < 0) {
      return fallback;
    }
    return Math.floor(parsed) + 1;
  }

  function lineCountLabel(visibleCount, totalCount = visibleCount) {
    if (visibleCount === totalCount) {
      return window.LooporaUI.currentLocale() === "zh" ? `${visibleCount} 行` : `${visibleCount} lines`;
    }
    return window.LooporaUI.currentLocale() === "zh"
      ? `${visibleCount}/${totalCount} 行`
      : `${visibleCount}/${totalCount} lines`;
  }

  function consoleChannelLabel(channel) {
    const labels = {
      command: localeText("命令", "Command"),
      stdout: localeText("输出", "Stdout"),
      state: localeText("状态", "State"),
      context: localeText("上下文", "Context"),
      progress: localeText("进展", "Progress"),
      model: localeText("模型", "Model"),
      file: localeText("文件", "Files"),
      error: localeText("错误", "Error"),
      warning: localeText("提醒", "Warning"),
    };
    return labels[channel] || localeText("信息", "Info");
  }

  function firstLine(text) {
    return String(text || "").split("\n")[0] || "";
  }

  function truncateSummary(text, maxChars = 140) {
    const normalized = firstLine(text).trim();
    if (normalized.length <= maxChars) {
      return normalized;
    }
    return `${normalized.slice(0, maxChars - 1).trimEnd()}…`;
  }

  function prettyJson(value) {
    return JSON.stringify(value, null, 2);
  }

  function buildConsoleEntry(
    event,
    {
      tone = "info",
      channel = "state",
      filterKey = "status",
      text = "",
      summary = "",
      indent = 0,
      roleLabel = null,
      collapsed = false,
    } = {},
  ) {
    const payload = event.payload || {};
    const resolvedRole = roleLabel || (
      payload.role_name && window.LooporaUI?.normalizeRoleName
        ? window.LooporaUI.normalizeRoleName(payload.role_name, payload.archetype || payload.role)
        : window.LooporaUI.translateRole(event.role || payload.role || "system")
    );
    const normalizedText = String(text ?? "").replaceAll("\r\n", "\n").replace(/\s+$/, "");
    return {
      tone,
      channel,
      filterKey,
      text: normalizedText,
      summary: truncateSummary(summary || normalizedText),
      indent: Math.max(0, Math.min(2, Number(indent) || 0)),
      stamp: formatClock(event.created_at),
      label: `${resolvedRole} · ${consoleChannelLabel(channel)}`,
      mergeKey: `${resolvedRole}|${channel}|${tone}|${filterKey}`,
      mergeable: channel === "stdout",
      collapsed,
    };
  }

  function buildContextDetail(payload) {
    const resolvedRole = payload.role_name && window.LooporaUI?.normalizeRoleName
      ? window.LooporaUI.normalizeRoleName(payload.role_name, payload.archetype || payload.role)
      : (payload.role || "-");
    return [
      `iter=${payload.iter !== undefined ? displayIter(payload.iter) : "-"}`,
      `step=${payload.step_id || "-"}`,
      `role=${resolvedRole}`,
      `path=${payload.context_path || payload.handoff_path || payload.summary_path || payload.step_prompt_path || payload.output_path || "-"}`,
    ].join(" · ");
  }

  function buildConsoleLines(event) {
    const payload = event.payload || {};
    if (event.event_type === "run_started") {
      return [buildConsoleEntry(event, {
        tone: "system",
        channel: "state",
        filterKey: "status",
        summary: localeText("运行开始", "Run started"),
        text: localeText("运行开始，Loopora 已进入执行态。", "Run started and Loopora entered execution mode."),
      })];
    }
    if (event.event_type === "checks_resolved") {
      return [buildConsoleEntry(event, {
        tone: "system",
        channel: "state",
        filterKey: "status",
        summary: `${localeText("检查项已就绪", "Checks resolved")} (${payload.count || 0})`,
        text: prettyJson(payload),
      })];
    }
    if (event.event_type === "role_request_prepared") {
      const resolvedRole = payload.role_name && window.LooporaUI?.normalizeRoleName
        ? window.LooporaUI.normalizeRoleName(payload.role_name, payload.archetype || payload.role)
        : (payload.role || "-");
      return [buildConsoleEntry(event, {
        tone: "system",
        channel: "context",
        filterKey: "actions",
        summary: `${localeText("角色请求已准备", "Role request prepared")} · ${resolvedRole}`,
        text: prettyJson(payload),
        collapsed: true,
      })];
    }
    if (event.event_type === "step_context_prepared") {
      return [buildConsoleEntry(event, {
        tone: "system",
        channel: "context",
        filterKey: "actions",
        summary: `${localeText("上下文已装配", "Context prepared")} · ${buildContextDetail(payload)}`,
        text: prettyJson(payload),
        collapsed: true,
      })];
    }
    if (event.event_type === "role_started") {
      const iterLabel = payload.iter !== undefined ? ` · ${localeText("迭代", "iter")} ${displayIter(payload.iter)}` : "";
      return [buildConsoleEntry(event, {
        tone: "system",
        channel: "state",
        filterKey: "status",
        summary: `${localeText("开始执行", "Started")}${iterLabel}`,
        text: prettyJson(payload),
      })];
    }
    if (event.event_type === "role_degraded") {
      return [buildConsoleEntry(event, {
        tone: "warning",
        channel: "warning",
        filterKey: "result",
        summary: `${localeText("降级到", "Degraded to")} ${payload.mode || "-"}`,
        text: prettyJson(payload),
      })];
    }
    if (event.event_type === "role_execution_summary") {
      const tone = payload.ok ? "success" : "error";
      const durationText = formatDurationMs(payload.duration_ms);
      const detail = payload.ok
        ? `${localeText("完成", "Completed")} · ${localeText("尝试", "attempts")}=${payload.attempts || 1}${durationText ? ` · ${durationText}` : ""}`
        : `${localeText("失败", "Failed")} · ${payload.error || "-"}${durationText ? ` · ${durationText}` : ""}`;
      return [buildConsoleEntry(event, {
        tone,
        channel: payload.ok ? "state" : "error",
        filterKey: "result",
        summary: detail,
        text: prettyJson(payload),
      })];
    }
    if (event.event_type === "step_handoff_written") {
      return [buildConsoleEntry(event, {
        tone: payload.status === "blocked" ? "warning" : payload.status === "passed" ? "success" : "system",
        channel: "context",
        filterKey: "actions",
        summary: `${localeText("交接包已写入", "Handoff written")} · ${payload.summary || "-"}`,
        text: prettyJson(payload),
        collapsed: true,
      })];
    }
    if (event.event_type === "iteration_summary_written") {
      return [buildConsoleEntry(event, {
        tone: payload.passed ? "success" : "system",
        channel: "context",
        filterKey: "actions",
        summary: `${localeText("轮次摘要已冻结", "Iteration summary written")} · score=${payload.composite_score ?? "n/a"}`,
        text: prettyJson(payload),
        collapsed: true,
      })];
    }
    if (event.event_type === "run_aborted") {
      return [buildConsoleEntry(event, {
        tone: "error",
        channel: "error",
        filterKey: "result",
        summary: `${localeText("运行中止", "Run aborted")} · ${payload.error || payload.role || "-"}`,
        text: prettyJson(payload),
      })];
    }
    if (event.event_type === "workspace_guard_triggered") {
      return [buildConsoleEntry(event, {
        tone: "error",
        channel: "error",
        filterKey: "result",
        summary: `${localeText("工作区安全守卫触发", "Workspace safety guard triggered")} · ${localeText("删掉原始文件", "Deleted original files")}=${payload.deleted_original_count || 0}`,
        text: prettyJson(payload),
      })];
    }
    if (event.event_type === "stop_requested") {
      return [buildConsoleEntry(event, {
        tone: "warning",
        channel: "warning",
        filterKey: "status",
        summary: localeText("已请求停止", "Stop requested"),
        text: prettyJson(payload),
      })];
    }
    if (event.event_type === "run_finished") {
      return [buildConsoleEntry(event, {
        tone: payload.status === "succeeded" ? "success" : "warning",
        channel: "state",
        filterKey: "result",
        summary: `${localeText("运行结束", "Run finished")} · ${window.LooporaUI.translateStatus(payload.status || "succeeded")}`,
        text: prettyJson(payload),
      })];
    }
    if (event.event_type !== "codex_event") {
      return [];
    }

    if (payload.type === "stdout" && payload.message) {
      return [buildConsoleEntry(event, {
        tone: "stdout",
        channel: "stdout",
        filterKey: "result",
        summary: String(payload.message),
        text: String(payload.message),
        indent: 1,
      })];
    }
    if (payload.type === "command" && payload.message) {
      return [buildConsoleEntry(event, {
        tone: "command",
        channel: "command",
        filterKey: "actions",
        summary: `$ ${String(payload.message).trim()}`,
        text: `$ ${String(payload.message).trim()}`,
      })];
    }
    if (payload.type === "error") {
      const message = String(payload.message || payload.error?.message || localeText("发生错误", "Error")).trim();
      return [buildConsoleEntry(event, {
        tone: "error",
        channel: "error",
        filterKey: "result",
        summary: message,
        text: message,
        indent: 1,
      })];
    }
    if (payload.type === "turn.failed") {
      const message = String(payload.error?.message || localeText("本轮失败", "Turn failed")).trim();
      return [buildConsoleEntry(event, {
        tone: "error",
        channel: "error",
        filterKey: "result",
        summary: message,
        text: message,
        indent: 1,
      })];
    }

    const item = payload.item || {};
    if (!item.type) {
      return [];
    }
    if (payload.type === "item.started" && item.type === "command_execution") {
      return [buildConsoleEntry(event, {
        tone: "command",
        channel: "command",
        filterKey: "actions",
        summary: `$ ${item.command || ""}`,
        text: `$ ${item.command || ""}`,
      })];
    }
    if (payload.type === "item.completed" && item.type === "command_execution") {
      if (item.aggregated_output) {
        return [buildConsoleEntry(event, {
          tone: "stdout",
          channel: "stdout",
          filterKey: "result",
          summary: String(item.aggregated_output),
          text: String(item.aggregated_output),
          indent: 1,
        })];
      }
      return item.exit_code && item.exit_code !== 0
        ? [buildConsoleEntry(event, {
          tone: "error",
          channel: "error",
          filterKey: "result",
          summary: `${localeText("命令退出码", "Command exit code")} ${item.exit_code}`,
          text: `${localeText("命令退出码", "Command exit code")} ${item.exit_code}`,
          indent: 1,
        })]
        : [];
    }
    if (payload.type === "item.completed" && item.type === "file_change") {
      const changed = (item.changes || []).map((change) => change.path?.split("/").pop()).filter(Boolean).join(", ");
      return [buildConsoleEntry(event, {
        tone: "success",
        channel: "file",
        filterKey: "actions",
        summary: `${localeText("文件变更", "Files changed")}: ${changed || "-"}`,
        text: prettyJson(item),
        indent: 1,
      })];
    }
    if ((payload.type === "item.started" || payload.type === "item.updated") && item.type === "todo_list") {
      const total = (item.items || []).length;
      const completed = (item.items || []).filter((entry) => entry.completed).length;
      return [buildConsoleEntry(event, {
        tone: "progress",
        channel: "progress",
        filterKey: "status",
        summary: `${localeText("待办进度", "Todo progress")}: ${completed}/${total}`,
        text: prettyJson(item),
        indent: 1,
      })];
    }
    if (payload.type === "item.completed" && item.type === "agent_message" && item.text) {
      return [buildConsoleEntry(event, {
        tone: "progress",
        channel: "model",
        filterKey: "result",
        summary: String(item.text),
        text: String(item.text),
        indent: 1,
      })];
    }
    return [];
  }

  function setRowCollapsed(row, collapsed) {
    row.classList.toggle("is-collapsed", collapsed);
    const expander = row.querySelector(".console-line-expander");
    if (expander) {
      expander.textContent = collapsed ? localeText("展开", "Expand") : localeText("收起", "Collapse");
    }
  }

  function applyConsoleFilters() {
    const rows = output.querySelectorAll(".console-line");
    let visibleCount = 0;
    for (const row of rows) {
      const visible = selectedFilters.has(row.dataset.filterKey || "status");
      row.classList.toggle("is-hidden", !visible);
      if (visible) {
        visibleCount += 1;
      }
    }
    if (lineCountNode) {
      lineCountNode.textContent = lineCountLabel(visibleCount, rows.length);
    }
  }

  function syncConsoleMeta() {
    applyConsoleFilters();
    if (statusBadge) {
      const status = currentRun?.status || "draft";
      statusBadge.className = `status-pill progress-status-pill status-${status}`;
      statusBadge.dataset.statusLabel = status;
      statusBadge.textContent = window.LooporaUI.translateStatus(status);
    }
  }

  function buildRow(line) {
    const row = document.createElement("article");
    row.className = `console-line console-line-${line.tone || "info"} console-line-indent-${line.indent || 0}`;
    row.dataset.filterKey = line.filterKey || "status";
    if (line.mergeKey) {
      row.dataset.mergeKey = line.mergeKey;
    }

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "console-line-toggle";

    const meta = document.createElement("div");
    meta.className = "console-line-meta";
    const stamp = document.createElement("span");
    stamp.className = "console-line-stamp";
    stamp.textContent = line.stamp || "--:--:--";
    const badge = document.createElement("span");
    badge.className = "console-line-badge";
    badge.textContent = line.label || localeText("系统 · 信息", "system · info");
    meta.append(stamp, badge);

    const summary = document.createElement("div");
    summary.className = "console-line-summary";
    summary.textContent = line.summary || firstLine(line.text);

    const expander = document.createElement("span");
    expander.className = "console-line-expander";

    const body = document.createElement("pre");
    body.className = "console-line-body";
    body.textContent = line.text;

    toggle.append(meta, summary, expander);
    toggle.addEventListener("click", () => {
      setRowCollapsed(row, !row.classList.contains("is-collapsed"));
    });

    row.append(toggle, body);
    setRowCollapsed(row, Boolean(line.collapsed));
    row.classList.toggle("is-hidden", !selectedFilters.has(line.filterKey || "status"));
    return row;
  }

  function appendConsoleLines(lines) {
    if (!lines.length) {
      return;
    }
    const shouldStick = autoScrollConsole || shell.scrollTop + shell.clientHeight >= shell.scrollHeight - 24;
    for (const line of lines) {
      const lastRow = output.lastElementChild;
      if (line.mergeable && lastRow && lastRow.dataset.mergeKey === line.mergeKey) {
        const body = lastRow.querySelector(".console-line-body");
        if (body) {
          body.textContent = `${body.textContent}\n${line.text}`;
        }
        continue;
      }
      output.appendChild(buildRow(line));
    }
    while (output.children.length > MAX_CONSOLE_LINES) {
      output.removeChild(output.firstChild);
    }
    syncConsoleMeta();
    if (shouldStick) {
      shell.scrollTop = shell.scrollHeight;
    }
  }

  function renderConsole() {
    output.innerHTML = "";
    for (const event of consoleEventRecords) {
      appendConsoleLines(buildConsoleLines(event));
    }
    syncConsoleMeta();
  }

  function pushConsoleEvent(event) {
    consoleEventRecords.push(event);
    if (consoleEventRecords.length > MAX_CONSOLE_LINES) {
      consoleEventRecords = consoleEventRecords.slice(-MAX_CONSOLE_LINES);
      renderConsole();
      return;
    }
    appendConsoleLines(buildConsoleLines(event));
  }

  function updateRunStateFromEvent(event) {
    const payload = event.payload || {};
    if (event.event_type === "role_started") {
      currentRun = {
        ...currentRun,
        status: "running",
        active_role: payload.role || currentRun.active_role,
        current_iter: payload.iter ?? currentRun.current_iter,
      };
      syncConsoleMeta();
      return;
    }
    if (event.event_type === "run_finished") {
      currentRun = {
        ...currentRun,
        status: payload.status || currentRun.status,
        active_role: null,
        current_iter: payload.iter ?? currentRun.current_iter,
        finished_at: event.created_at || currentRun.finished_at,
      };
      syncConsoleMeta();
      return;
    }
    if (event.event_type === "run_aborted") {
      currentRun = {
        ...currentRun,
        status: "failed",
        active_role: null,
      };
      syncConsoleMeta();
    }
  }

  function buildFilterControls() {
    if (!filterGroup) {
      return;
    }
    function syncFilterChipState(label, checkbox) {
      label.classList.toggle("is-active", checkbox.checked);
      label.classList.toggle("is-inactive", !checkbox.checked);
    }
    if (expandAllButton) {
      expandAllButton.textContent = localeText("全部展开", "Expand all");
    }
    if (collapseAllButton) {
      collapseAllButton.textContent = localeText("全部收缩", "Collapse all");
    }
    filterGroup.innerHTML = "";
    for (const option of FILTER_OPTIONS) {
      const label = document.createElement("label");
      label.className = `console-filter-chip console-filter-chip--${option.key}`;
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = selectedFilters.has(option.key);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) {
          selectedFilters.add(option.key);
        } else {
          selectedFilters.delete(option.key);
        }
        syncFilterChipState(label, checkbox);
        applyConsoleFilters();
      });
      const text = document.createElement("span");
      text.textContent = localeText(option.zh, option.en);
      label.append(checkbox, text);
      syncFilterChipState(label, checkbox);
      filterGroup.appendChild(label);
    }
    if (expandAllButton) {
      expandAllButton.onclick = () => {
        output.querySelectorAll(".console-line").forEach((row) => setRowCollapsed(row, false));
      };
    }
    if (collapseAllButton) {
      collapseAllButton.onclick = () => {
        output.querySelectorAll(".console-line").forEach((row) => setRowCollapsed(row, true));
      };
    }
  }

  shell.addEventListener("scroll", (event) => {
    const currentShell = event.currentTarget;
    autoScrollConsole = currentShell.scrollTop + currentShell.clientHeight >= currentShell.scrollHeight - 24;
  });

  const eventSource = new EventSource(`/api/runs/${runId}/stream?after_id=${encodeURIComponent(lastEventId)}`);
  eventSource.onmessage = () => {};

  function handleStreamEvent(message) {
    const payload = JSON.parse(message.data);
    if (payload.id <= lastEventId) {
      return null;
    }
    lastEventId = payload.id;
    pushConsoleEvent(payload);
    updateRunStateFromEvent(payload);
    return payload;
  }

  const streamedEvents = [
    "run_started",
    "checks_resolved",
    "role_request_prepared",
    "step_context_prepared",
    "role_started",
    "role_execution_summary",
    "step_handoff_written",
    "iteration_summary_written",
    "role_degraded",
    "challenger_done",
    "stop_requested",
    "run_aborted",
    "workspace_guard_triggered",
  ];
  eventSource.addEventListener("codex_event", handleStreamEvent);
  streamedEvents.forEach((eventName) => {
    eventSource.addEventListener(eventName, handleStreamEvent);
  });
  eventSource.addEventListener("run_finished", (message) => {
    const payload = handleStreamEvent(message);
    if (!payload) {
      return;
    }
    eventSource.close();
  });

  document.addEventListener("loopora:localechange", () => {
    window.LooporaUI.applyLocalizedAttributes(document);
    buildFilterControls();
    renderConsole();
  });

  buildFilterControls();
  renderConsole();
  syncConsoleMeta();
});
