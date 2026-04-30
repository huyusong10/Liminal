(function () {
  function createConsoleEventProjector({
    buildConsoleEntry,
    localeText,
    prettyConsoleJson,
    resolvedPayloadRoleName,
    buildContextDetail,
    displayIter,
    formatDurationMs,
    translateStatus,
  }) {
    const translateRunStatus = translateStatus || ((status) => window.LooporaUI.translateStatus(status));

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
          text: prettyConsoleJson(payload),
        })];
      }
      if (event.event_type === "role_request_prepared") {
        return [buildConsoleEntry(event, {
          tone: "system",
          channel: "context",
          filterKey: "actions",
          summary: `${localeText("角色请求已准备", "Role request prepared")} · ${resolvedPayloadRoleName(payload)}`,
          text: prettyConsoleJson(payload),
          collapsed: true,
        })];
      }
      if (event.event_type === "step_context_prepared") {
        return [buildConsoleEntry(event, {
          tone: "system",
          channel: "context",
          filterKey: "actions",
          summary: `${localeText("上下文已装配", "Context prepared")} · ${buildContextDetail(payload)}`,
          text: prettyConsoleJson(payload),
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
          text: prettyConsoleJson(payload),
        })];
      }
      if (event.event_type === "role_degraded") {
        return [buildConsoleEntry(event, {
          tone: "warning",
          channel: "warning",
          filterKey: "result",
          summary: `${localeText("降级到", "Degraded to")} ${payload.mode || "-"}`,
          text: prettyConsoleJson(payload),
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
          text: prettyConsoleJson(payload),
        })];
      }
      if (event.event_type === "step_handoff_written") {
        return [buildConsoleEntry(event, {
          tone: payload.status === "blocked" ? "warning" : payload.status === "passed" ? "success" : "system",
          channel: "context",
          filterKey: "actions",
          summary: `${localeText("交接包已写入", "Handoff written")} · ${payload.summary || "-"}`,
          text: prettyConsoleJson(payload),
          collapsed: true,
        })];
      }
      if (["control_triggered", "control_completed", "control_failed", "control_skipped"].includes(event.event_type)) {
        const tone = event.event_type === "control_failed"
          ? "error"
          : event.event_type === "control_skipped"
            ? "warning"
            : event.event_type === "control_completed"
              ? "success"
              : "system";
        const label = {
          control_triggered: localeText("运行控制已触发", "Control triggered"),
          control_completed: localeText("运行控制已完成", "Control completed"),
          control_failed: localeText("运行控制失败", "Control failed"),
          control_skipped: localeText("运行控制已跳过", "Control skipped"),
        }[event.event_type];
        return [buildConsoleEntry(event, {
          tone,
          channel: tone === "error" ? "error" : tone === "warning" ? "warning" : "context",
          filterKey: tone === "error" ? "result" : "actions",
          summary: `${label} · ${payload.signal || "-"} -> ${payload.role_id || "-"}`,
          text: prettyConsoleJson(payload),
          collapsed: true,
        })];
      }
      if (event.event_type === "iteration_summary_written") {
        return [buildConsoleEntry(event, {
          tone: payload.passed ? "success" : "system",
          channel: "context",
          filterKey: "actions",
          summary: `${localeText("轮次摘要已冻结", "Iteration summary written")} · score=${payload.composite_score ?? "n/a"}`,
          text: prettyConsoleJson(payload),
          collapsed: true,
        })];
      }
      if (event.event_type === "run_aborted") {
        return [buildConsoleEntry(event, {
          tone: "error",
          channel: "error",
          filterKey: "result",
          summary: `${localeText("运行中止", "Run aborted")} · ${payload.error || payload.role || "-"}`,
          text: prettyConsoleJson(payload),
        })];
      }
      if (event.event_type === "workspace_guard_triggered") {
        return [buildConsoleEntry(event, {
          tone: "error",
          channel: "error",
          filterKey: "result",
          summary: `${localeText("工作区安全守卫触发", "Workspace safety guard triggered")} · ${localeText("删掉原始文件", "Deleted original files")}=${payload.deleted_original_count || 0}`,
          text: prettyConsoleJson(payload),
        })];
      }
      if (event.event_type === "stop_requested") {
        return [buildConsoleEntry(event, {
          tone: "warning",
          channel: "warning",
          filterKey: "status",
          summary: localeText("已请求停止", "Stop requested"),
          text: prettyConsoleJson(payload),
        })];
      }
      if (event.event_type === "run_finished") {
        return [buildConsoleEntry(event, {
          tone: payload.status === "succeeded" ? "success" : "warning",
          channel: "state",
          filterKey: "result",
          summary: `${localeText("运行结束", "Run finished")} · ${translateRunStatus(payload.status || "succeeded")}`,
          text: prettyConsoleJson(payload),
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
          text: prettyConsoleJson(item),
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
          text: prettyConsoleJson(item),
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

    return {buildConsoleLines};
  }

  window.LooporaRunDetailConsole = {createConsoleEventProjector};
})();
