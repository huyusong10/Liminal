document.addEventListener("DOMContentLoaded", () => {
  if (!window.LiminalUI || !window.LiminalRunConsoleBootstrap) {
    return;
  }

  const {runId, initialRun, initialConsoleEvents, latestEventId: initialLatestEventId} = window.LiminalRunConsoleBootstrap;
  const output = document.getElementById("console-focus-output");
  const shell = document.getElementById("console-focus-shell");
  const statusBadge = document.getElementById("console-focus-status");
  const MAX_CONSOLE_LINES = 640;
  let currentRun = initialRun;
  let consoleEventRecords = Array.isArray(initialConsoleEvents) ? initialConsoleEvents.slice() : [];
  let lastEventId = Number(initialLatestEventId || 0);
  let autoScrollConsole = true;

  function localeText(zh, en) {
    return window.LiminalUI.pickText({zh, en});
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

  function lineCountLabel(count) {
    return window.LiminalUI.currentLocale() === "zh" ? `${count} 行` : `${count} lines`;
  }

  function consoleChannelLabel(channel) {
    const labels = {
      command: localeText("命令", "Command"),
      stdout: localeText("输出", "Stdout"),
      state: localeText("状态", "State"),
      progress: localeText("进展", "Progress"),
      model: localeText("模型", "Model"),
      file: localeText("文件", "Files"),
      error: localeText("错误", "Error"),
      warning: localeText("提醒", "Warning"),
    };
    return labels[channel] || localeText("信息", "Info");
  }

  function buildConsoleEntry(event, {tone = "info", channel = "state", text = "", indent = 0, roleLabel = null} = {}) {
    const payload = event.payload || {};
    const resolvedRole = roleLabel || window.LiminalUI.translateRole(event.role || payload.role || "system");
    const normalizedText = String(text ?? "")
      .replaceAll("\r\n", "\n")
      .replace(/\s+$/, "");
    return {
      tone,
      channel,
      text: normalizedText,
      indent: Math.max(0, Math.min(2, Number(indent) || 0)),
      stamp: formatClock(event.created_at),
      label: `${resolvedRole} · ${consoleChannelLabel(channel)}`,
      mergeKey: `${resolvedRole}|${channel}|${tone}`,
      mergeable: channel === "stdout",
    };
  }

  function buildConsoleLines(event) {
    const payload = event.payload || {};
    if (event.event_type === "run_started") {
      return [buildConsoleEntry(event, {tone: "system", channel: "state", text: localeText("运行开始", "Run started")})];
    }
    if (event.event_type === "checks_resolved") {
      return [buildConsoleEntry(event, {
        tone: "system",
        channel: "state",
        text: `${localeText("检查项已就绪", "Checks resolved")} (${payload.count || 0})`,
      })];
    }
    if (event.event_type === "role_started") {
      const iterLabel = payload.iter !== undefined ? ` · ${localeText("迭代", "iter")} ${displayIter(payload.iter)}` : "";
      return [buildConsoleEntry(event, {
        tone: "system",
        channel: "state",
        text: `${localeText("开始执行", "Started")}${iterLabel}`,
      })];
    }
    if (event.event_type === "role_degraded") {
      return [buildConsoleEntry(event, {
        tone: "warning",
        channel: "warning",
        text: `${localeText("降级到", "Degraded to")} ${payload.mode || "-"}`,
      })];
    }
    if (event.event_type === "role_execution_summary") {
      const tone = payload.ok ? "success" : "error";
      const durationText = formatDurationMs(payload.duration_ms);
      const detail = payload.ok
        ? `${localeText("完成", "completed")} · ${localeText("尝试", "attempts")}=${payload.attempts || 1}${durationText ? ` · ${durationText}` : ""}`
        : `${localeText("失败", "failed")} · ${payload.error || "-"}${durationText ? ` · ${durationText}` : ""}`;
      return [buildConsoleEntry(event, {
        tone,
        channel: payload.ok ? "state" : "error",
        text: detail,
      })];
    }
    if (event.event_type === "run_aborted") {
      return [buildConsoleEntry(event, {
        tone: "error",
        channel: "error",
        text: `${localeText("运行中止", "Run aborted")} · ${payload.error || payload.role || "-"}`,
      })];
    }
    if (event.event_type === "workspace_guard_triggered") {
      return [buildConsoleEntry(event, {
        tone: "error",
        channel: "error",
        text: `${localeText("工作区安全守卫触发", "Workspace safety guard triggered")} · ${localeText("删掉原始文件", "Deleted original files")}=${payload.deleted_original_count || 0}`,
      })];
    }
    if (event.event_type === "stop_requested") {
      return [buildConsoleEntry(event, {
        tone: "warning",
        channel: "warning",
        text: localeText("已请求停止", "Stop requested"),
      })];
    }
    if (event.event_type === "run_finished") {
      return [buildConsoleEntry(event, {
        tone: payload.status === "succeeded" ? "success" : "warning",
        channel: "state",
        text: `${localeText("运行结束", "Run finished")} · ${window.LiminalUI.translateStatus(payload.status || "succeeded")}`,
      })];
    }
    if (event.event_type !== "codex_event") {
      return [];
    }
    if (payload.type === "stdout" && payload.message) {
      return [buildConsoleEntry(event, {
        tone: "stdout",
        channel: "stdout",
        text: String(payload.message),
        indent: 1,
      })];
    }
    if (payload.type === "command" && payload.message) {
      return [buildConsoleEntry(event, {
        tone: "command",
        channel: "command",
        text: `$ ${String(payload.message).trim()}`,
      })];
    }
    if (payload.type === "error") {
      return [buildConsoleEntry(event, {
        tone: "error",
        channel: "error",
        text: String(payload.message || payload.error?.message || localeText("发生错误", "Error")).trim(),
        indent: 1,
      })];
    }
    if (payload.type === "turn.failed") {
      return [buildConsoleEntry(event, {
        tone: "error",
        channel: "error",
        text: String(payload.error?.message || localeText("本轮失败", "Turn failed")).trim(),
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
        text: `$ ${item.command || ""}`,
      })];
    }
    if (payload.type === "item.completed" && item.type === "command_execution") {
      if (item.aggregated_output) {
        return [buildConsoleEntry(event, {
          tone: "stdout",
          channel: "stdout",
          text: String(item.aggregated_output),
          indent: 1,
        })];
      }
      return item.exit_code && item.exit_code !== 0
        ? [buildConsoleEntry(event, {
          tone: "error",
          channel: "error",
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
        text: `${localeText("文件变更", "Files changed")}: ${changed || "-"}`,
        indent: 1,
      })];
    }
    if ((payload.type === "item.started" || payload.type === "item.updated") && item.type === "todo_list") {
      const total = (item.items || []).length;
      const completed = (item.items || []).filter((entry) => entry.completed).length;
      return [buildConsoleEntry(event, {
        tone: "progress",
        channel: "progress",
        text: `${localeText("待办进度", "Todo progress")}: ${completed}/${total}`,
        indent: 1,
      })];
    }
    if (payload.type === "item.completed" && item.type === "agent_message" && item.text) {
      return [buildConsoleEntry(event, {
        tone: "progress",
        channel: "model",
        text: String(item.text),
        indent: 1,
      })];
    }
    return [];
  }

  function syncConsoleMeta() {
    document.getElementById("console-focus-line-count").textContent = lineCountLabel(output.children.length);
    const status = currentRun?.status || "draft";
    statusBadge.className = `status-pill progress-status-pill status-${status}`;
    statusBadge.dataset.statusLabel = status;
    statusBadge.textContent = window.LiminalUI.translateStatus(status);
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
      const row = document.createElement("article");
      row.className = `console-line console-line-${line.tone || "info"} console-line-indent-${line.indent || 0}`;
      if (line.mergeKey) {
        row.dataset.mergeKey = line.mergeKey;
      }
      const meta = document.createElement("div");
      meta.className = "console-line-meta";
      const stamp = document.createElement("span");
      stamp.className = "console-line-stamp";
      stamp.textContent = line.stamp || "--:--:--";
      const badge = document.createElement("span");
      badge.className = "console-line-badge";
      badge.textContent = line.label || localeText("系统 · 信息", "system · info");
      meta.append(stamp, badge);
      const body = document.createElement("div");
      body.className = "console-line-body";
      body.textContent = line.text;
      row.append(meta, body);
      output.appendChild(row);
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

  eventSource.addEventListener("codex_event", handleStreamEvent);
  ["run_started", "checks_resolved", "role_started", "role_execution_summary", "role_degraded", "challenger_done", "stop_requested", "run_aborted", "workspace_guard_triggered"].forEach((eventName) => {
    eventSource.addEventListener(eventName, handleStreamEvent);
  });
  eventSource.addEventListener("run_finished", (message) => {
    const payload = handleStreamEvent(message);
    if (!payload) {
      return;
    }
    eventSource.close();
  });

  document.addEventListener("liminal:localechange", () => {
    window.LiminalUI.applyLocalizedAttributes(document);
    renderConsole();
  });

  renderConsole();
  syncConsoleMeta();
});
