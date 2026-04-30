(function () {
  function createRenderProjector(deps = {}) {
    const localeText = deps.localeText || ((zh, en) => en || zh || "");
    const takeawayProjector = deps.takeawayProjector || {};
    const timelineProjector = deps.timelineProjector || {};
    const formatAbsoluteDate = deps.formatAbsoluteDate || (() => "");

    function summarizeTaskVerdict(verdict) {
      const taskVerdict = verdict && typeof verdict === "object" ? verdict : {};
      const status = String(taskVerdict.status || "not_evaluated").toLowerCase();
      const buckets = taskVerdict.buckets || {};
      const bucketMeta = [
        `${localeText("已证明", "proven")} ${Array.isArray(buckets.proven) ? buckets.proven.length : 0}`,
        `${localeText("未证明", "unproven")} ${Array.isArray(buckets.unproven) ? buckets.unproven.length : 0}`,
        `${localeText("阻断", "blocking")} ${Array.isArray(buckets.blocking) ? buckets.blocking.length : 0}`,
      ].join(" · ");
      const title = takeawayProjector.taskVerdictStatusLabel
        ? takeawayProjector.taskVerdictStatusLabel(status)
        : status;
      const detail = taskVerdict.summary || localeText(
        "还没有可用的证据裁决。",
        "No evidence-based task verdict is available yet."
      );
      const meta = `${localeText("来源", "Source")} ${taskVerdict.source || "-"} · ${bucketMeta}`;
      return {title, detail, meta, status};
    }

    function taskVerdictTone(status) {
      const normalized = String(status || "").toLowerCase();
      if (normalized === "passed") {
        return "tone-success";
      }
      if (["passed_with_residual_risk", "insufficient_evidence", "failed"].includes(normalized)) {
        return "tone-warning";
      }
      return "tone-neutral";
    }

    function summarizeLatestEvent(timelineRecords = []) {
      const latestEvent = timelineRecords[timelineRecords.length - 1];
      if (!latestEvent) {
        return {
          title: localeText("还没有关键事件", "No key event yet"),
          detail: localeText("运行推进后会在这里显示最新里程碑。", "Recent milestones will appear here once the run advances."),
          meta: "",
        };
      }
      const formatted = timelineProjector.formatTimelineEvent
        ? timelineProjector.formatTimelineEvent(latestEvent)
        : {title: latestEvent.event_type || "", detail: ""};
      return {
        title: formatted.title,
        detail: formatted.detail || localeText("无附加说明。", "No extra detail."),
        meta: formatAbsoluteDate(latestEvent.created_at),
      };
    }

    return {
      summarizeTaskVerdict,
      taskVerdictTone,
      summarizeLatestEvent,
    };
  }

  function createDomRenderer(deps = {}) {
    const localeText = deps.localeText || ((zh, en) => en || zh || "");
    const escapeHtml = deps.escapeHtml || ((value) => String(value || ""));
    const formatClock = deps.formatClock || (() => "--:--:--");
    const formatAbsoluteDate = deps.formatAbsoluteDate || (() => "-");
    const formatDuration = deps.formatDuration || (() => "-");
    const stripMarkdown = deps.stripMarkdown || ((value) => String(value || ""));
    const truncateText = deps.truncateText || ((value) => String(value || ""));
    const displayIter = deps.displayIter || ((value) => value);
    const runId = deps.runId || "";
    const initialRun = deps.initialRun || {};
    const maxConsoleLines = Number(deps.maxConsoleLines || 420);
    const getRun = deps.getRun || (() => ({}));
    const getTimelineRecords = deps.getTimelineRecords || (() => []);
    const getConsoleEventRecords = deps.getConsoleEventRecords || (() => []);
    const getTakeawaySnapshot = deps.getTakeawaySnapshot || (() => ({}));
    const progressProjector = deps.progressProjector || {};
    const timelineProjector = deps.timelineProjector || {};
    const takeawayProjector = deps.takeawayProjector || {};
    const renderProjector = deps.renderProjector || {};
    const syncLiveRefreshers = deps.syncLiveRefreshers || (() => {});
    let selectedTakeawayIter = null;
    let autoScrollConsole = true;
    let takeawayFeedbackTimer = null;
    const consoleFilterOptions = [
      {key: "status", zh: "状态", en: "Status"},
      {key: "actions", zh: "动作", en: "Actions"},
      {key: "result", zh: "结果", en: "Result"},
    ];
    const selectedConsoleFilters = new Set(consoleFilterOptions.map((item) => item.key));

    function setTextContentIfChanged(target, value) {
      const node = typeof target === "string" ? document.getElementById(target) : target;
      if (!node) {
        return;
      }
      const next = value ?? "";
      if (node.textContent !== next) {
        node.textContent = next;
      }
    }

    function setClassNameIfChanged(node, value) {
      if (node && node.className !== value) {
        node.className = value;
      }
    }

    function setAttributeIfChanged(node, name, value) {
      if (!node) {
        return;
      }
      const next = value ?? "";
      if (node.getAttribute(name) !== next) {
        node.setAttribute(name, next);
      }
    }

    function eventAlreadyRecorded(records, event) {
      const eventId = Number(event?.id || 0);
      return eventId > 0 && records.some((record) => Number(record?.id || 0) === eventId);
    }

    function stageChipMarkup(stage) {
      return `
        <div class="stage-chip-head">
          <span class="stage-chip-order" data-stage-order>${escapeHtml(progressProjector.stageOrderLabel(stage))}</span>
          <span class="stage-chip-label" data-stage-label>${escapeHtml(stage.chipLabel || stage.title)}</span>
          <span class="stage-chip-state" data-stage-state>-</span>
        </div>
        <strong class="stage-chip-duration" data-stage-duration>-</strong>
        <span class="stage-chip-meta" data-stage-meta>-</span>
      `;
    }

    function createStageChip(stage) {
      const chip = document.createElement("div");
      chip.className = `stage-chip ${stage.kind === "workflow_step" ? "stage-chip--workflow" : "stage-chip--terminal"}`;
      chip.dataset.stage = stage.key;
      chip.dataset.stageKind = stage.kind;
      chip.tabIndex = 0;
      chip.innerHTML = stageChipMarkup(stage);
      return chip;
    }

    function buildStageStripLayout(stages) {
      const fragment = document.createDocumentFragment();
      const checksStage = stages.find((stage) => stage.kind === "checks") || null;
      const workflowStages = stages.filter((stage) => stage.kind === "workflow_step");
      const finishedStage = stages.find((stage) => stage.kind === "finished") || null;

      if (checksStage) {
        const terminal = document.createElement("div");
        terminal.className = "stage-strip-terminal stage-strip-terminal--entry";
        terminal.appendChild(createStageChip(checksStage));
        fragment.appendChild(terminal);
      }

      const loopShell = document.createElement("div");
      loopShell.className = `stage-loop-shell${workflowStages.length ? "" : " is-empty"}`;
      loopShell.dataset.testid = "run-stage-loop-shell";
      loopShell.dataset.workflowEmpty = workflowStages.length ? "false" : "true";
      loopShell.innerHTML = `
        <div class="stage-loop-banner">
          <span class="stage-loop-eyebrow" id="stage-loop-eyebrow">-</span>
          <strong class="stage-loop-title" id="stage-loop-title">-</strong>
          <p class="stage-loop-copy" id="stage-loop-copy">-</p>
        </div>
        <div class="stage-loop-track">
          <span class="stage-loop-connector stage-loop-connector--entry" aria-hidden="true"></span>
          <div class="stage-loop-steps"></div>
          <span class="stage-loop-connector stage-loop-connector--exit" aria-hidden="true"></span>
          <div class="stage-loop-arcs" aria-hidden="true">
            <span class="stage-loop-arc stage-loop-arc--top"></span>
            <span class="stage-loop-arc stage-loop-arc--bottom"></span>
          </div>
        </div>
      `;
      const workflowContainer = loopShell.querySelector(".stage-loop-steps");
      if (workflowStages.length) {
        workflowContainer.replaceChildren(...workflowStages.map(createStageChip));
      } else {
        workflowContainer.innerHTML = `
          <div class="stage-loop-empty" data-testid="run-stage-loop-empty">
            <strong>${escapeHtml(localeText("还没有 workflow steps", "No workflow steps yet"))}</strong>
            <p>${escapeHtml(localeText(
              "这次 run 没有冻结下中间编排步骤，所以这里只显示入口和最终状态。",
              "This run has no frozen middle workflow steps, so only the entry and final state remain."
            ))}</p>
          </div>
        `;
      }
      fragment.appendChild(loopShell);

      if (finishedStage) {
        const terminal = document.createElement("div");
        terminal.className = "stage-strip-terminal stage-strip-terminal--exit";
        terminal.appendChild(createStageChip(finishedStage));
        fragment.appendChild(terminal);
      }
      return fragment;
    }

    function updateStageLoopSummary(run = getRun()) {
      const summary = progressProjector.workflowLoopSummary(run);
      setTextContentIfChanged("stage-loop-eyebrow", summary.eyebrow);
      setTextContentIfChanged("stage-loop-title", summary.title);
      setTextContentIfChanged("stage-loop-copy", summary.detail);
      const loopShell = document.querySelector("#stage-strip .stage-loop-shell");
      if (loopShell) {
        const workflowEmpty = !progressProjector.getProgressStages(run).some((stage) => stage.kind === "workflow_step");
        loopShell.classList.toggle("is-empty", workflowEmpty);
        loopShell.dataset.workflowEmpty = workflowEmpty ? "true" : "false";
      }
    }

    function ensureStageStrip(run) {
      const stageStrip = document.getElementById("stage-strip");
      if (!stageStrip) {
        return;
      }
      const stages = progressProjector.getProgressStages(run);
      const existingKeys = Array.from(stageStrip.querySelectorAll(".stage-chip")).map((chip) => chip.dataset.stage);
      const expectedKeys = stages.map((stage) => stage.key);
      if (existingKeys.length === expectedKeys.length && existingKeys.every((key, index) => key === expectedKeys[index])) {
        updateStageLoopSummary(run);
        return;
      }
      stageStrip.replaceChildren(buildStageStripLayout(stages));
      updateStageLoopSummary(run);
    }

    function renderEvidenceCoverage(snapshot = getTakeawaySnapshot()) {
      const node = document.getElementById("takeaway-evidence-strip");
      if (!node) {
        return;
      }
      node.hidden = false;
      node.innerHTML = takeawayProjector.evidenceCoverageHtml(snapshot, runId);
    }

    function renderEvidenceOutcome(snapshot = getTakeawaySnapshot(), run = getRun()) {
      const card = document.getElementById("takeaway-outcome-card");
      if (!card) {
        return;
      }
      const outcome = takeawayProjector.evidenceOutcome(snapshot, run);
      card.classList.toggle("is-soft", outcome.soft);
      setTextContentIfChanged("takeaway-outcome-title", outcome.title);
      setTextContentIfChanged("takeaway-outcome-detail", outcome.detail);
    }

    function ensureSelectedTakeawayIter(iterations) {
      const resolved = takeawayProjector.resolveSelectedIteration(iterations, selectedTakeawayIter);
      selectedTakeawayIter = resolved.selectedKey;
      return resolved.iteration;
    }

    function renderTakeaways(snapshot = getTakeawaySnapshot(), run = getRun()) {
      const selectorRow = document.getElementById("takeaway-selector-row");
      const selector = document.getElementById("takeaway-iteration-select");
      const view = document.getElementById("takeaway-iteration-view");
      const empty = document.getElementById("takeaway-empty");
      const meta = document.getElementById("takeaway-meta");
      const iterations = Array.isArray(snapshot?.iterations) ? snapshot.iterations : [];
      setTextContentIfChanged("takeaway-build-path", snapshot?.build_dir || "-");
      setTextContentIfChanged("takeaway-log-path", snapshot?.log_dir || "-");
      renderEvidenceCoverage(snapshot);
      renderEvidenceOutcome(snapshot, run);
      meta.textContent = takeawayProjector.takeawayMeta(snapshot);
      if (!iterations.length) {
        selectorRow.hidden = true;
        selector.innerHTML = "";
        view.innerHTML = "";
        empty.hidden = false;
        return;
      }
      const activeIteration = ensureSelectedTakeawayIter(iterations);
      empty.hidden = true;
      selectorRow.hidden = false;
      selector.innerHTML = takeawayProjector.iterationOptionsHtml(iterations, selectedTakeawayIter);
      view.innerHTML = activeIteration ? takeawayProjector.renderTakeawayIterationCard(activeIteration, snapshot) : "";
    }

    function setSelectedTakeawayIter(value) {
      selectedTakeawayIter = String(value || "");
    }

    function renderTimeline(records = getTimelineRecords()) {
      const timeline = document.getElementById("timeline");
      const visible = records.slice(-14).reverse();
      timeline.innerHTML = visible.map((event) => timelineProjector.renderTimelineItem(event)).join("");
      document.getElementById("timeline-count").textContent = localeText(`最近 ${visible.length} 条`, `Latest ${visible.length}`);
      syncTimelineState();
    }

    function syncTimelineState() {
      const timeline = document.getElementById("timeline");
      const empty = document.getElementById("timeline-empty");
      const count = document.getElementById("timeline-count");
      empty.hidden = timeline.children.length > 0;
      if (!timeline.children.length && count) {
        count.textContent = localeText("还没冒出节点", "Waiting for milestones");
      }
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

    function firstConsoleLine(text) {
      return String(text || "").split("\n")[0] || "";
    }

    function truncateConsoleSummary(text, maxChars = 140) {
      const normalized = firstConsoleLine(text).trim();
      if (normalized.length <= maxChars) {
        return normalized;
      }
      return `${normalized.slice(0, maxChars - 1).trimEnd()}…`;
    }

    function prettyConsoleJson(value) {
      return JSON.stringify(value, null, 2);
    }

    function buildContextDetail(payload) {
      return [
        `iter=${payload.iter !== undefined ? displayIter(payload.iter) : "-"}`,
        `step=${payload.step_id || "-"}`,
        `role=${progressProjector.resolvedPayloadRoleName(payload)}`,
        `path=${payload.context_path || payload.handoff_path || payload.summary_path || payload.step_prompt_path || payload.output_path || "-"}`,
      ].join(" · ");
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
      const resolvedRole = roleLabel || progressProjector.resolvedPayloadRoleName(payload, event.role || payload.role || "system");
      const normalizedText = String(text ?? "").replaceAll("\r\n", "\n").replace(/\s+$/, "");
      return {
        tone,
        channel,
        filterKey,
        text: normalizedText,
        summary: truncateConsoleSummary(summary || normalizedText),
        indent: Math.max(0, Math.min(2, Number(indent) || 0)),
        stamp: formatClock(event.created_at),
        label: `${resolvedRole} · ${consoleChannelLabel(channel)}`,
        mergeKey: `${resolvedRole}|${channel}|${tone}|${filterKey}`,
        mergeable: channel === "stdout",
        collapsed,
      };
    }

    const {buildConsoleLines} = window.LooporaRunDetailConsole.createConsoleEventProjector({
      buildConsoleEntry,
      localeText,
      prettyConsoleJson,
      resolvedPayloadRoleName: progressProjector.resolvedPayloadRoleName,
      buildContextDetail,
      displayIter,
      formatDurationMs: progressProjector.formatDurationMs,
      translateStatus: (status) => window.LooporaUI.translateStatus(status),
    });

    function setConsoleRowCollapsed(row, collapsed) {
      row.classList.toggle("is-collapsed", collapsed);
      const expander = row.querySelector(".console-line-expander");
      if (expander) {
        expander.textContent = collapsed ? localeText("展开", "Expand") : localeText("收起", "Collapse");
      }
    }

    function applyConsoleFilters() {
      const output = document.getElementById("console-output");
      const rows = output.querySelectorAll(".console-line");
      let visibleCount = 0;
      for (const row of rows) {
        const visible = selectedConsoleFilters.has(row.dataset.filterKey || "status");
        row.classList.toggle("is-hidden", !visible);
        if (visible) {
          visibleCount += 1;
        }
      }
      document.getElementById("console-line-count").textContent = lineCountLabel(visibleCount, rows.length);
    }

    function syncConsoleMeta(run = getRun()) {
      applyConsoleFilters();
      const liveBadge = document.getElementById("console-live-badge");
      const status = run?.status || initialRun?.status || "queued";
      liveBadge.className = `status-pill progress-status-pill status-${status}`;
      if (status === "running" || status === "queued") {
        liveBadge.innerHTML = `<span data-lang="zh">实时输出</span><span data-lang="en">Streaming</span>`;
      } else {
        liveBadge.dataset.statusLabel = status;
        liveBadge.textContent = window.LooporaUI.translateStatus(status);
      }
    }

    function buildConsoleRow(line) {
      const row = document.createElement("article");
      row.className = `console-line console-line-${line.tone || "info"} console-line-indent-${line.indent || 0}`;
      row.dataset.testid = "run-console-line";
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
      summary.textContent = line.summary || firstConsoleLine(line.text);
      const expander = document.createElement("span");
      expander.className = "console-line-expander";
      const body = document.createElement("pre");
      body.className = "console-line-body";
      body.textContent = line.text;
      toggle.append(meta, summary, expander);
      toggle.addEventListener("click", () => {
        setConsoleRowCollapsed(row, !row.classList.contains("is-collapsed"));
      });
      row.append(toggle, body);
      setConsoleRowCollapsed(row, Boolean(line.collapsed));
      row.classList.toggle("is-hidden", !selectedConsoleFilters.has(line.filterKey || "status"));
      return row;
    }

    function appendConsoleLines(lines) {
      if (!lines.length) {
        return;
      }
      const shell = document.getElementById("console-shell");
      const output = document.getElementById("console-output");
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
        output.appendChild(buildConsoleRow(line));
      }
      while (output.children.length > maxConsoleLines) {
        output.removeChild(output.firstChild);
      }
      syncConsoleMeta();
      if (shouldStick) {
        shell.scrollTop = shell.scrollHeight;
      }
    }

    function buildConsoleControls() {
      const filterGroup = document.getElementById("console-filters");
      const expandAllButton = document.getElementById("console-expand-all");
      const collapseAllButton = document.getElementById("console-collapse-all");
      function syncFilterChipState(label, checkbox) {
        label.classList.toggle("is-active", checkbox.checked);
        label.classList.toggle("is-inactive", !checkbox.checked);
      }
      expandAllButton.textContent = localeText("全部展开", "Expand all");
      collapseAllButton.textContent = localeText("全部收缩", "Collapse all");
      filterGroup.innerHTML = "";
      for (const option of consoleFilterOptions) {
        const label = document.createElement("label");
        label.className = `console-filter-chip console-filter-chip--${option.key}`;
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = selectedConsoleFilters.has(option.key);
        checkbox.addEventListener("change", () => {
          if (checkbox.checked) {
            selectedConsoleFilters.add(option.key);
          } else {
            selectedConsoleFilters.delete(option.key);
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
      expandAllButton.onclick = () => {
        document.querySelectorAll("#console-output .console-line").forEach((row) => setConsoleRowCollapsed(row, false));
      };
      collapseAllButton.onclick = () => {
        document.querySelectorAll("#console-output .console-line").forEach((row) => setConsoleRowCollapsed(row, true));
      };
    }

    function bindConsoleScroll() {
      document.getElementById("console-shell")?.addEventListener("scroll", (event) => {
        const shell = event.currentTarget;
        autoScrollConsole = shell.scrollTop + shell.clientHeight >= shell.scrollHeight - 24;
      });
    }

    function renderConsole(records = getConsoleEventRecords()) {
      const output = document.getElementById("console-output");
      output.innerHTML = "";
      for (const event of records) {
        appendConsoleLines(buildConsoleLines(event));
      }
      syncConsoleMeta();
    }

    function pushConsoleEvent(records, event) {
      if (eventAlreadyRecorded(records, event)) {
        return records;
      }
      let nextRecords = records.concat([event]);
      if (nextRecords.length > maxConsoleLines) {
        nextRecords = nextRecords.slice(-maxConsoleLines);
        renderConsole(nextRecords);
        return nextRecords;
      }
      appendConsoleLines(buildConsoleLines(event));
      return nextRecords;
    }

    function updateProgressLiveTimers(run, {stage = null, snapshots = null, liveWork = null} = {}) {
      if (!run) {
        return;
      }
      const resolvedStage = stage || progressProjector.getCurrentStage(run);
      const resolvedSnapshots = snapshots || progressProjector.getStageSnapshots(run);
      const resolvedLiveWork = liveWork || progressProjector.describeLiveWork(run);
      setTextContentIfChanged(
        "progress-live-duration",
        resolvedLiveWork.duration
          ? localeText(`已持续 ${resolvedLiveWork.duration}`, `${resolvedLiveWork.duration} elapsed`)
          : localeText("刚刚开始", "Just started")
      );
      setTextContentIfChanged("progress-meta", resolvedLiveWork.metaRight);
      const currentChip = document.querySelector(`.stage-chip[data-stage="${resolvedStage}"]`);
      if (currentChip) {
        setTextContentIfChanged(currentChip.querySelector("[data-stage-duration]"), resolvedSnapshots[resolvedStage]?.durationLabel || "-");
      }
    }

    function updateProgressPanel(run, {liveOnly = false} = {}) {
      ensureStageStrip(run);
      const stage = progressProjector.getCurrentStage(run);
      const snapshots = progressProjector.getStageSnapshots(run);
      const stageDefinitions = new Map(progressProjector.getProgressStages(run).map((definition) => [definition.key, definition]));
      const statusBadge = document.getElementById("progress-status-badge");
      const status = run?.status || "draft";
      const liveWork = progressProjector.describeLiveWork(run);
      const progressLiveCard = document.getElementById("progress-live-card");
      const progressTone = status === "running"
        ? "active"
        : (status === "queued"
          ? "queued"
          : (status === "succeeded"
            ? "success"
            : (status === "failed" || status === "stopped" ? "danger" : "neutral")));

      if (liveOnly) {
        updateProgressLiveTimers(run, {stage, snapshots, liveWork});
        syncLiveRefreshers();
        return;
      }

      setAttributeIfChanged(statusBadge, "data-status-label", status);
      setTextContentIfChanged(statusBadge, window.LooporaUI.translateStatus(status));
      setClassNameIfChanged(statusBadge, `status-pill progress-status-pill status-${status}`);
      setClassNameIfChanged(progressLiveCard, `progress-live-card progress-live-card--${progressTone}`);
      updateProgressLiveTimers(run, {stage, snapshots, liveWork});
      setTextContentIfChanged("progress-live-title", liveWork.title);
      setTextContentIfChanged("progress-live-subtitle", localeText(
        `${progressProjector.stageDisplayName(stage)} · ${window.LooporaUI.translateStatus(status)}`,
        `${progressProjector.stageDisplayName(stage)} · ${window.LooporaUI.translateStatus(status)}`
      ));
      setTextContentIfChanged("progress-live-detail", liveWork.detail);
      setTextContentIfChanged("progress-stage-label", liveWork.metaLeft);
      setTextContentIfChanged("progress-caption", status === "running"
        ? localeText("不再猜一个虚假的百分比，只保留当前阶段和已经走过的阶段耗时痕迹。", "No fake percentage here anymore. This view keeps the current stage and the time traces already left on completed stages.")
        : localeText("这一轮已经收尾，下面保留最终阶段结果和整条路径的耗时痕迹。", "This run has settled, and the stage flow below now shows the final outcome with the time spent along the way."));

      document.querySelectorAll(".stage-chip").forEach((chip) => {
        const snapshot = snapshots[chip.dataset.stage] || {state: "pending", stateLabel: "-", durationLabel: "-", meta: "-"};
        const definition = stageDefinitions.get(chip.dataset.stage);
        const tooltip = progressProjector.stageTooltipText(chip.dataset.stage, run, snapshots);
        const baseClass = chip.dataset.stageKind === "workflow_step"
          ? "stage-chip stage-chip--workflow"
          : "stage-chip stage-chip--terminal";
        setClassNameIfChanged(chip, `${baseClass} ${snapshot.state}`);
        if (chip.dataset.tooltip !== tooltip) {
          chip.dataset.tooltip = tooltip;
        }
        setAttributeIfChanged(chip, "aria-label", tooltip);
        setTextContentIfChanged(chip.querySelector("[data-stage-order]"), progressProjector.stageOrderLabel(definition));
        setTextContentIfChanged(chip.querySelector("[data-stage-label]"), definition?.chipLabel || definition?.title || chip.dataset.stage);
        setTextContentIfChanged(chip.querySelector("[data-stage-state]"), snapshot.stateLabel || "-");
        setTextContentIfChanged(chip.querySelector("[data-stage-duration]"), snapshot.durationLabel || "-");
        setTextContentIfChanged(chip.querySelector("[data-stage-meta]"), snapshot.meta || "-");
      });
      syncLiveRefreshers();
    }

    function updateHighlights(run) {
      const status = run?.run_status || run?.status || "draft";
      const stage = progressProjector.getCurrentStage(run);
      const focusName = progressProjector.stageDisplayName(stage, run);
      const focusTitle = window.LooporaUI.translateStatus(status);
      const focusDetail = status === "running"
        ? localeText(`${focusName} 正在处理中；任务裁决会在终态后单独收束。`, `${focusName} is in progress; the task verdict settles separately at terminal state.`)
        : localeText(`生命周期状态是 ${window.LooporaUI.translateStatus(status)}，这不等于任务是否通过。`, `Lifecycle status is ${window.LooporaUI.translateStatus(status)}; it is separate from task pass/fail.`);
      const focusMeta = `${localeText("迭代", "Iter")} ${displayIter(run?.current_iter)} · ${localeText("耗时", "Duration")} ${formatDuration(run?.started_at, run?.finished_at)}`;
      document.getElementById("focus-title").textContent = focusTitle;
      document.getElementById("focus-detail").textContent = focusDetail;
      document.getElementById("focus-meta").textContent = focusMeta;
      document.getElementById("focus-card").className = `highlight-card ${status === "running" ? "tone-active" : "tone-neutral"}`;

      const verdict = renderProjector.summarizeTaskVerdict(run?.task_verdict);
      document.getElementById("output-title").textContent = verdict.title;
      document.getElementById("output-detail").textContent = verdict.detail;
      document.getElementById("output-meta").textContent = verdict.meta || truncateText(stripMarkdown(run?.summary_md), 120) || localeText("等待首轮输出。", "Waiting for the first substantive output.");
      document.getElementById("output-card").className = `highlight-card ${renderProjector.taskVerdictTone(verdict.status)}`;

      const latestEvent = renderProjector.summarizeLatestEvent(getTimelineRecords());
      document.getElementById("event-title").textContent = latestEvent.title;
      document.getElementById("event-detail").textContent = latestEvent.detail;
      document.getElementById("event-meta").textContent = latestEvent.meta;
      document.getElementById("event-card").className = "highlight-card tone-neutral";
    }

    function renderRunDetailPanels() {
      const run = getRun();
      renderTimeline(getTimelineRecords());
      renderConsole(getConsoleEventRecords());
      renderTakeaways(getTakeawaySnapshot(), run);
      updateProgressPanel(run);
      updateHighlights(run);
      syncConsoleMeta(run);
    }

    return {
      bindConsoleScroll,
      buildConsoleControls,
      pushConsoleEvent,
      renderConsole,
      renderRunDetailPanels,
      renderTakeaways,
      renderTimeline,
      setSelectedTakeawayIter,
      syncConsoleMeta,
      updateHighlights,
      updateProgressPanel,
    };
  }

  window.LooporaRunDetailRender = {createDomRenderer, createRenderProjector};
})();
