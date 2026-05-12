(function () {
  function defaultEscapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function createTimelineProjector(deps = {}) {
    const localeText = deps.localeText || ((zh, en) => en || zh || "");
    const escapeHtml = deps.escapeHtml || defaultEscapeHtml;
    const formatClock = deps.formatClock || (() => "--:--:--");
    const formatAbsoluteDate = deps.formatAbsoluteDate || (() => "-");
    const formatDurationMs = deps.formatDurationMs || (() => "");
    const displayIter = deps.displayIter || ((value) => Number(value) + 1);
    const translateRole = deps.translateRole || ((role) => String(role || ""));
    const translateStatus = deps.translateStatus || ((status) => String(status || ""));
    const resolvedPayloadRoleName = deps.resolvedPayloadRoleName || ((payload = {}, role = "") => String(payload.role_name || role || "-"));

    function nonNegativeInteger(value) {
      return Number.isInteger(value) && value >= 0 ? value : null;
    }

    function displayCount(value, fallback = 0) {
      const count = nonNegativeInteger(value);
      return count === null ? fallback : count;
    }

    function formatTimelineEvent(event) {
      const payload = event.payload || {};
      const role = payload.role || event.role || "role";
      if (event.event_type === "run_started") {
        return {title: localeText("运行已开始", "Run started"), detail: ""};
      }
      if (event.event_type === "checks_resolved") {
        const count = displayCount(payload.count);
        return {
          title: localeText("检查项已就绪", "Checks resolved"),
          detail: localeText(`共 ${count} 条检查项`, `${count} checks ready`),
        };
      }
      if (event.event_type === "role_request_prepared") {
        return {
          title: localeText("角色请求已准备", "Role request prepared"),
          detail: resolvedPayloadRoleName(payload, role),
        };
      }
      if (event.event_type === "step_context_prepared") {
        return {
          title: localeText("步骤上下文已装配", "Step context prepared"),
          detail: `${payload.step_id || "-"} · ${payload.context_path || "-"}`,
        };
      }
      if (event.event_type === "role_execution_summary") {
        const durationMs = nonNegativeInteger(payload.duration_ms);
        const durationText = durationMs === null ? "" : formatDurationMs(durationMs);
        if (payload.ok === true) {
          const parts = [];
          const attempts = nonNegativeInteger(payload.attempts);
          if (attempts !== null && attempts > 1) {
            parts.push(`${localeText("重试", "attempts")}=${attempts}`);
          }
          if (payload.degraded === true) {
            parts.push(localeText("已降级", "degraded"));
          }
          if (durationText) {
            parts.push(durationText);
          }
          return {
            title: `${translateRole(role)} ${localeText("完成", "completed")}`,
            detail: parts.join(" · ") || localeText("正常完成", "ok"),
          };
        }
        return {
          title: `${translateRole(role)} ${localeText("失败", "failed")}`,
          detail: [String(payload.error || ""), durationText].filter(Boolean).join(" · "),
        };
      }
      if (event.event_type === "role_degraded") {
        return {
          title: `${translateRole(role)} ${localeText("降级执行", "degraded")}`,
          detail: String(payload.mode || ""),
        };
      }
      if (event.event_type === "step_handoff_written") {
        return {
          title: localeText("步骤交接包已写入", "Step handoff written"),
          detail: String(payload.summary || payload.step_id || ""),
        };
      }
      if (["parallel_group_started", "parallel_group_finished"].includes(event.event_type)) {
        const stepIds = Array.isArray(payload.step_ids) ? payload.step_ids : [];
        const stepOrders = Array.isArray(payload.step_orders) ? payload.step_orders : [];
        const stepCount = stepIds.length || stepOrders.length || 0;
        const titleByType = {
          parallel_group_started: localeText("并行检视开始", "Parallel review started"),
          parallel_group_finished: localeText("并行检视结束", "Parallel review finished"),
        };
        return {
          title: titleByType[event.event_type],
          detail: `${payload.parallel_group || "-"} · ${localeText(`${stepCount} 个步骤`, `${stepCount} steps`)}`,
        };
      }
      if (["control_triggered", "control_completed", "control_failed", "control_skipped"].includes(event.event_type)) {
        const titleByType = {
          control_triggered: localeText("运行控制已触发", "Control triggered"),
          control_completed: localeText("运行控制已完成", "Control completed"),
          control_failed: localeText("运行控制失败", "Control failed"),
          control_skipped: localeText("运行控制已跳过", "Control skipped"),
        };
        return {
          title: titleByType[event.event_type],
          detail: `${payload.signal || "-"} -> ${payload.role_id || "-"} · ${payload.reason || payload.skip_reason || ""}`,
        };
      }
      if (event.event_type === "iteration_summary_written") {
        return {
          title: localeText("轮次摘要已冻结", "Iteration summary written"),
          detail: `${localeText("综合分", "Composite")} ${payload.composite_score ?? "-"}`,
        };
      }
      if (event.event_type === "challenger_done") {
        return {
          title: localeText("引导者给出新方向", "Guide suggested a new direction"),
          detail: String(payload.mode || ""),
        };
      }
      if (event.event_type === "stop_requested") {
        return {title: localeText("已请求停止", "Stop requested"), detail: ""};
      }
      if (event.event_type === "run_result_accepted") {
        return {
          title: localeText("已接受结论", "Conclusion accepted"),
          detail: String(payload.task_verdict_status || payload.status || ""),
        };
      }
      if (event.event_type === "run_aborted") {
        const attempts = displayCount(payload.attempts);
        return {
          title: localeText("运行中止", "Run aborted"),
          detail: `${translateRole(payload.role || "role")} · ${localeText("尝试次数", "attempts")}=${attempts}`,
        };
      }
      if (event.event_type === "workspace_guard_triggered") {
        const deletedCount = displayCount(payload.deleted_original_count);
        return {
          title: localeText("工作区安全守卫触发", "Workspace safety guard triggered"),
          detail: localeText(
            `检测到删掉了 ${deletedCount} 个原始文件，已立即拦下这次运行。`,
            `Detected ${deletedCount} deleted original files and stopped the run immediately.`
          ),
        };
      }
      if (event.event_type === "run_finished") {
        const detailParts = [];
        const iter = nonNegativeInteger(payload.iter);
        if (payload.reason) {
          detailParts.push(String(payload.reason));
        } else if (iter !== null) {
          detailParts.push(`${localeText("迭代", "Iter")} ${displayIter(iter)}`);
        }
        if (payload.task_verdict_status) {
          detailParts.push(`${localeText("任务裁决", "Task verdict")} ${payload.task_verdict_status}`);
        }
        return {
          title: `${localeText("运行结束", "Run finished")} · ${translateStatus(payload.status || "succeeded")}`,
          detail: detailParts.join(" · "),
        };
      }
      return {title: event.event_type, detail: ""};
    }

    function timelineTone(event) {
      const payload = event.payload || {};
      if (event.event_type === "run_finished") {
        if (payload.task_verdict_status === "failed") {
          return "danger";
        }
        if (["insufficient_evidence", "passed_with_residual_risk"].includes(payload.task_verdict_status)) {
          return "warning";
        }
        return payload.status === "succeeded" ? "success" : (payload.status === "failed" ? "danger" : "warning");
      }
      if (event.event_type === "role_execution_summary") {
        return payload.ok === true ? "success" : "danger";
      }
      if (event.event_type === "checks_resolved") {
        return "accent";
      }
      if (event.event_type === "run_aborted" || event.event_type === "stop_requested") {
        return "warning";
      }
      if (event.event_type === "workspace_guard_triggered") {
        return "danger";
      }
      if (event.event_type === "challenger_done") {
        return "accent";
      }
      return "neutral";
    }

    function timelineMetaPills(event, formatted) {
      const payload = event.payload || {};
      const pills = [];
      if (payload.role) {
        pills.push(translateRole(payload.role));
      }
      if (payload.iter !== undefined) {
        const iter = nonNegativeInteger(payload.iter);
        if (iter !== null) {
          pills.push(localeText(`第 ${displayIter(iter)} 轮`, `Round ${displayIter(iter)}`));
        }
      }
      if (event.event_type === "checks_resolved") {
        pills.push(payload.source === "auto_generated" ? localeText("自动生成", "Auto-generated") : localeText("显式提供", "Specified"));
      }
      if (event.event_type === "workspace_guard_triggered") {
        const deletedCount = displayCount(payload.deleted_original_count);
        pills.push(localeText(`删掉 ${deletedCount} 个原始文件`, `Deleted ${deletedCount} original files`));
      }
      const durationMs = nonNegativeInteger(payload.duration_ms);
      if (durationMs !== null) {
        pills.push(formatDurationMs(durationMs));
      }
      if (!pills.length && formatted.detail) {
        pills.push(formatted.detail);
      }
      return pills.slice(0, 3);
    }

    function renderTimelineItem(event) {
      const formatted = formatTimelineEvent(event);
      const pills = timelineMetaPills(event, formatted);
      const detail = formatted.detail ? `<p class="timeline-event-detail">${escapeHtml(formatted.detail)}</p>` : "";
      const pillsHtml = pills.length
        ? `<div class="timeline-event-meta">${pills.map((pill) => `<span class="timeline-meta-pill">${escapeHtml(pill)}</span>`).join("")}</div>`
        : "";
      return `
        <article class="timeline-event timeline-event--${timelineTone(event)}">
          <div class="timeline-event-rail"><span class="timeline-event-dot"></span></div>
          <div class="timeline-event-body">
            <div class="timeline-event-main">
              <div class="timeline-event-heading">
                <strong>${escapeHtml(formatted.title)}</strong>
                ${pillsHtml}
              </div>
              ${detail}
            </div>
            <div class="timeline-event-timebox">
              <span class="timeline-event-time">${escapeHtml(formatClock(event.created_at))}</span>
              <span class="timeline-event-stamp">${escapeHtml(formatAbsoluteDate(event.created_at))}</span>
            </div>
          </div>
        </article>
      `;
    }

    return {
      formatTimelineEvent,
      renderTimelineItem,
      timelineMetaPills,
      timelineTone,
    };
  }

  window.LooporaRunDetailTimeline = {createTimelineProjector};
})();
