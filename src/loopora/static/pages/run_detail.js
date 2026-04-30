  const runDetailData = window.LOOPORA_RUN_DETAIL || {};
  const runId = runDetailData.runId;
  const initialRun = runDetailData.initialRun || {};
  let currentRun = initialRun;
  let timelineRecords = [];
  let consoleEventRecords = [];
  let progressEventRecords = [];
  let takeawaySnapshot = {};
  let lastEventId = 0;
  let eventSource = null;
  let observationState = "loading";
  let streamReconnectTimer = null;
  let scheduler = null;
  let renderProjector = null;
  let domRenderer = null;
  const MAX_CONSOLE_LINES = 420;
  const api = window.LooporaRunDetailApi;
  const observation = window.LooporaRunDetailObservation;
  const stateStore = window.LooporaRunDetailState.createRunDetailState({
    currentRun,
    timelineRecords,
    consoleEventRecords,
    progressEventRecords,
    takeawaySnapshot,
    lastEventId,
    observationState,
  }, {observation});
  const streamRetryDelays = window.LOOPORA_RUN_DETAIL_RETRY_DELAYS
    || runDetailData.streamRetryDelays
    || observation.DEFAULT_RETRY_DELAYS_MS;
  const streamController = window.LooporaRunDetailStream.createStreamController({
    observation,
    retryDelays: streamRetryDelays,
    getRun: () => currentRun,
    setObservationState,
    scheduleReconnect: (delay) => scheduleStreamReconnect(delay),
  });

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

  function parseTimestamp(value) {
    const timestamp = Date.parse(value || "");
    return Number.isFinite(timestamp) ? timestamp : null;
  }

  function formatAbsoluteDate(value) {
    const timestamp = parseTimestamp(value);
    if (timestamp === null) {
      return "-";
    }
    return new Date(timestamp).toLocaleString([], {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  }

  function formatRelativeAge(value) {
    const timestamp = parseTimestamp(value);
    if (timestamp === null) {
      return "";
    }
    const deltaSeconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
    if (deltaSeconds < 5) {
      return localeText("刚刚", "just now");
    }
    if (deltaSeconds < 60) {
      return localeText(`${deltaSeconds} 秒前`, `${deltaSeconds}s ago`);
    }
    if (deltaSeconds < 3600) {
      const minutes = Math.floor(deltaSeconds / 60);
      const seconds = deltaSeconds % 60;
      return seconds
        ? localeText(`${minutes} 分 ${seconds} 秒前`, `${minutes}m ${seconds}s ago`)
        : localeText(`${minutes} 分钟前`, `${minutes}m ago`);
    }
    const hours = Math.floor(deltaSeconds / 3600);
    const minutes = Math.floor((deltaSeconds % 3600) / 60);
    return minutes
      ? localeText(`${hours} 小时 ${minutes} 分钟前`, `${hours}h ${minutes}m ago`)
      : localeText(`${hours} 小时前`, `${hours}h ago`);
  }

  function scheduleRunRefresh({immediate = false, refreshTakeaways = false} = {}) {
    scheduler?.scheduleRunRefresh({immediate, refreshTakeaways});
  }

  function stripMarkdown(value) {
    return String(value || "")
      .replace(/^#.*$/gm, "")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/\*\*([^*]+)\*\*/g, "$1")
      .replace(/\*([^*]+)\*/g, "$1")
      .replace(/\[(.*?)\]\((.*?)\)/g, "$1")
      .replace(/\s+/g, " ")
      .trim();
  }

  function truncateText(value, maxLength = 140) {
    const text = String(value || "").trim();
    if (!text) {
      return "";
    }
    return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
  }

  function displayIter(value, fallback = 1) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed < 0) {
      return fallback;
    }
    return Math.floor(parsed) + 1;
  }

  function observationStateLabel(state) {
    const labels = {
      loading: localeText("正在连接观察数据", "Loading observation data"),
      ready: localeText("观察数据已连接", "Observation connected"),
      degraded: localeText("首屏观察数据降级，正在等待增量事件", "Snapshot degraded; waiting for live events"),
      "stream-error": localeText("事件流短暂中断，正在重连", "Event stream interrupted; reconnecting"),
      "stream-stale": localeText("事件流多次中断，当前观察可能滞后", "Event stream is stale after repeated reconnects"),
      finished: localeText("运行已结束，观察数据已冻结", "Run finished; observation is frozen"),
    };
    return labels[state] || labels.ready;
  }

  function setObservationState(state) {
    observationState = state || "ready";
    const node = document.getElementById("run-observation-status");
    if (!node) {
      return;
    }
    node.dataset.observationState = observationState;
    node.textContent = observationStateLabel(observationState);
  }

  function eventAlreadyRecorded(records, event) {
    const eventId = Number(event?.id || 0);
    return eventId > 0 && records.some((record) => Number(record?.id || 0) === eventId);
  }

  function syncStateStore() {
    stateStore.replace({
      currentRun,
      timelineRecords,
      consoleEventRecords,
      progressEventRecords,
      takeawaySnapshot,
      lastEventId,
      observationState,
    });
  }

  function applyStoredState(state) {
    currentRun = state.currentRun;
    timelineRecords = state.timelineRecords;
    consoleEventRecords = state.consoleEventRecords;
    progressEventRecords = state.progressEventRecords;
    takeawaySnapshot = state.takeawaySnapshot;
    lastEventId = state.lastEventId;
    observationState = state.observationState;
  }

  function resetStreamFailures() {
    streamController.resetFailures();
  }

  function clearStreamReconnect() {
    if (streamReconnectTimer) {
      window.clearTimeout(streamReconnectTimer);
      streamReconnectTimer = null;
    }
  }

  function closeRunStream() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    clearStreamReconnect();
  }

  function scheduleStreamReconnect(delay) {
    if (!observation.shouldReconnect(currentRun) || streamReconnectTimer) {
      return;
    }
    const resolvedDelay = Number(delay) || observation.nextRetryDelay(streamController.getFailureCount(), streamRetryDelays);
    streamReconnectTimer = window.setTimeout(() => {
      streamReconnectTimer = null;
      connectRunStream();
    }, resolvedDelay);
  }

  function markStreamFailure(source = "connection") {
    streamController.markFailure(source);
  }

  const progressProjector = window.LooporaRunDetailProgress.createProgressProjector({
    localeText,
    parseTimestamp,
    formatDuration,
    formatRelativeAge,
    formatAbsoluteDate,
    stripMarkdown,
    truncateText,
    displayIter,
    translateStatus: (status) => window.LooporaUI.translateStatus(status),
    translateRole: (role) => window.LooporaUI.translateRole(role),
    normalizeRoleName: (name, archetype) => window.LooporaUI?.normalizeRoleName
      ? window.LooporaUI.normalizeRoleName(name, archetype)
      : String(name || ""),
    getCurrentRun: () => currentRun,
    getProgressEvents: () => progressEventRecords,
    getConsoleEvents: () => consoleEventRecords,
    summarizeLatestEvent: () => summarizeLatestEvent(),
  });
  const {
    formatDurationMs,
    resolvedPayloadRoleName,
    runIsActive,
  } = progressProjector;
  scheduler = window.LooporaRunDetailScheduler.createScheduler({
    fetchRun: (options) => fetchRun(options),
    isActive: () => runIsActive(currentRun),
    onHeartbeat: () => {
      updateProgressPanel(currentRun, {liveOnly: true});
      syncConsoleMeta();
    },
  });

  const timelineProjector = window.LooporaRunDetailTimeline.createTimelineProjector({
    localeText,
    escapeHtml,
    formatClock,
    formatAbsoluteDate,
    formatDurationMs,
    displayIter,
    resolvedPayloadRoleName,
    translateStatus: (status) => window.LooporaUI.translateStatus(status),
    translateRole: (role) => window.LooporaUI.translateRole(role),
  });

  const takeawayProjector = window.LooporaRunDetailTakeaways.createTakeawayProjector({
    localeText,
    escapeHtml,
    formatAbsoluteDate,
  });
  renderProjector = window.LooporaRunDetailRender.createRenderProjector({
    localeText,
    takeawayProjector,
    timelineProjector,
    formatAbsoluteDate,
  });
  domRenderer = window.LooporaRunDetailRender.createDomRenderer({
    localeText,
    escapeHtml,
    formatClock,
    formatAbsoluteDate,
    formatDuration,
    stripMarkdown,
    truncateText,
    displayIter,
    runId,
    initialRun,
    maxConsoleLines: MAX_CONSOLE_LINES,
    getRun: () => currentRun,
    getTimelineRecords: () => timelineRecords,
    getConsoleEventRecords: () => consoleEventRecords,
    getTakeawaySnapshot: () => takeawaySnapshot,
    progressProjector,
    timelineProjector,
    takeawayProjector,
    renderProjector,
    syncLiveRefreshers: () => syncLiveRefreshers(),
  });
  function renderTakeaways() {
    domRenderer.renderTakeaways(takeawaySnapshot, currentRun);
  }

  async function refreshTakeawaySnapshot() {
    takeawaySnapshot = await api.fetchKeyTakeaways(runId);
    renderTakeaways();
  }

  let takeawayFeedbackTimer = null;

  function setTakeawayFeedback(message) {
    const node = document.getElementById("takeaway-feedback");
    if (!node) {
      return;
    }
    node.textContent = message || "";
    if (takeawayFeedbackTimer) {
      window.clearTimeout(takeawayFeedbackTimer);
      takeawayFeedbackTimer = null;
    }
    if (message) {
      takeawayFeedbackTimer = window.setTimeout(() => {
        node.textContent = "";
      }, 2400);
    }
  }

  async function revealPath(path) {
    if (!path) {
      return;
    }
    try {
      await api.revealPath(path);
      setTakeawayFeedback(localeText("已打开目录。", "Opened the folder."));
      return;
    } catch (error) {
      try {
        await navigator.clipboard.writeText(path);
        setTakeawayFeedback(localeText("无法自动打开，路径已复制。", "Could not open automatically. The path was copied."));
        return;
      } catch (copyError) {
        setTakeawayFeedback(localeText("无法自动打开目录。", "Unable to open the folder automatically."));
      }
    }
  }

  function bindTakeawayActions() {
    document.getElementById("takeaway-open-build")?.addEventListener("click", () => revealPath(takeawaySnapshot?.build_dir));
    document.getElementById("takeaway-open-logs")?.addEventListener("click", () => revealPath(takeawaySnapshot?.log_dir));
    document.getElementById("takeaway-iteration-select")?.addEventListener("change", (event) => {
      domRenderer.setSelectedTakeawayIter(event?.target?.value || "");
      renderTakeaways();
    });
  }

  function renderTimeline() {
    domRenderer.renderTimeline(timelineRecords);
  }

  function syncConsoleMeta() {
    domRenderer.syncConsoleMeta(currentRun);
  }

  function buildConsoleControls() {
    domRenderer.buildConsoleControls();
  }

  function renderConsole() {
    domRenderer.renderConsole(consoleEventRecords);
  }

  function pushConsoleEvent(event) {
    consoleEventRecords = domRenderer.pushConsoleEvent(consoleEventRecords, event);
  }

  function summarizeLatestEvent() {
    return renderProjector.summarizeLatestEvent(timelineRecords);
  }

  function updateProgressPanel(run, {liveOnly = false} = {}) {
    domRenderer.updateProgressPanel(run, {liveOnly});
  }

  function updateHighlights(run) {
    domRenderer.updateHighlights(run);
  }

  async function fetchRun({shouldRefreshTakeaways = false} = {}) {
    const payload = await api.fetchRun(runId);
    currentRun = payload;
    if (observation.isTerminalRun(currentRun)) {
      setObservationState("finished");
      clearStreamReconnect();
    }
    updateProgressPanel(payload);
    updateHighlights(payload);
    syncConsoleMeta();
    if (!shouldRefreshTakeaways) {
      return;
    }
    refreshTakeawaySnapshot().catch(() => {});
  }

  function pushTimelineEvent(event) {
    if (eventAlreadyRecorded(timelineRecords, event)) {
      return;
    }
    timelineRecords.push(event);
    renderTimeline();
    if (currentRun) {
      updateProgressPanel(currentRun);
      updateHighlights(currentRun);
    }
  }

  function isProgressEvent(event) {
    return [
      "checks_resolved",
      "role_started",
      "role_request_prepared",
      "step_context_prepared",
      "role_execution_summary",
      "step_handoff_written",
      "control_triggered",
      "control_completed",
      "control_failed",
      "control_skipped",
      "run_aborted",
      "run_finished",
    ].includes(event?.event_type);
  }

  function pushProgressEvent(event) {
    if (!isProgressEvent(event)) {
      return;
    }
    if (eventAlreadyRecorded(progressEventRecords, event)) {
      return;
    }
    progressEventRecords.push(event);
    if (progressEventRecords.length > 4000) {
      progressEventRecords = progressEventRecords.slice(-4000);
    }
  }

  domRenderer.bindConsoleScroll();

  document.getElementById("stop-run")?.addEventListener("click", async () => {
    try {
      await api.stopRun(runId);
      await fetchRun();
    } catch (error) {
      alert(error?.message || localeText("无法停止运行。", "Unable to stop the run."));
    }
  });

  function formatDuration(startedAt, finishedAt) {
    if (!startedAt) return "-";
    const start = new Date(startedAt);
    const end = finishedAt ? new Date(finishedAt) : new Date();
    const seconds = Math.max(0, Math.floor((end - start) / 1000));
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds % 60;
    return minutes ? `${minutes}m ${remainder}s` : `${remainder}s`;
  }

  function syncLiveRefreshers() {
    scheduler?.syncLiveRefreshers();
  }

  function renderRunDetailPanels() {
    domRenderer.renderRunDetailPanels();
  }

  async function loadObservationSnapshot() {
    const payload = await api.fetchObservationSnapshot(runId);
    syncStateStore();
    const merged = stateStore.mergeSnapshot(payload);
    applyStoredState(merged);
    resetStreamFailures();
    setObservationState(merged.observationState);
    renderRunDetailPanels();
  }

  function handleStreamEvent(message, options = {}) {
    const payload = JSON.parse(message.data);
    syncStateStore();
    const applied = stateStore.applyStreamEvent(payload);
    if (applied.duplicate) {
      return null;
    }
    applyStoredState(applied.state);
    if (options.console !== false) {
      pushConsoleEvent(payload);
    }
    pushProgressEvent(payload);
    if (currentRun && payload.event_type === "role_started") {
      updateProgressPanel(currentRun);
      updateHighlights(currentRun);
      syncConsoleMeta();
    }
    if (currentRun && payload.event_type === "run_finished") {
      updateProgressPanel(currentRun);
      updateHighlights(currentRun);
      syncConsoleMeta();
    }
    if (currentRun && payload.event_type === "run_aborted") {
      updateProgressPanel(currentRun);
      updateHighlights(currentRun);
      syncConsoleMeta();
    }
    if (options.timeline) {
      pushTimelineEvent(payload);
    }
    if (options.refresh) {
      scheduleRunRefresh({
        immediate: options.immediate === true,
        refreshTakeaways: options.refreshTakeaways === true,
      });
    }
    resetStreamFailures();
    setObservationState(observation.stateAfterStreamEvent({
      run: currentRun,
      eventType: payload.event_type,
      fallbackState: "ready",
    }));
    return payload;
  }

  function handleStreamErrorEvent(message) {
    let payload = {};
    try {
      payload = JSON.parse(message.data || "{}");
    } catch (error) {
      // Keep the visible state stable even if a backend stream error payload is malformed.
    }
    if (payload.retryable === false) {
      setObservationState("stream-error");
      return;
    }
    markStreamFailure("stream_error");
  }

  function connectRunStream() {
    closeRunStream();
    if (!observation.shouldReconnect(currentRun)) {
      setObservationState("finished");
      return;
    }
    eventSource = new EventSource(`/api/runs/${runId}/stream?after_id=${encodeURIComponent(lastEventId)}`);
    eventSource.onmessage = () => {};
    eventSource.onopen = () => {
      resetStreamFailures();
      if (observation.isTerminalRun(currentRun)) {
        setObservationState("finished");
      } else if (observationState !== "degraded") {
        setObservationState("ready");
      }
    };
    eventSource.onerror = () => {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      markStreamFailure("connection");
    };
    eventSource.addEventListener("stream_error", handleStreamErrorEvent);
    eventSource.addEventListener("codex_event", (message) => {
      handleStreamEvent(message, {console: true, timeline: false, refresh: false});
    });
    eventSource.addEventListener("role_started", (message) => {
      handleStreamEvent(message, {console: true, timeline: false, refresh: true});
    });
    eventSource.addEventListener("run_finished", (message) => {
      const payload = handleStreamEvent(message, {
        console: true,
        timeline: true,
        refresh: true,
        refreshTakeaways: true,
        immediate: true,
      });
      if (!payload) {
        return;
      }
      closeRunStream();
      setObservationState("finished");
    });
    ["run_started", "checks_resolved", "role_request_prepared", "step_context_prepared", "role_execution_summary", "step_handoff_written", "control_triggered", "control_completed", "control_failed", "control_skipped", "iteration_summary_written", "role_degraded", "challenger_done", "stop_requested", "run_aborted", "workspace_guard_triggered"].forEach((eventName) => {
      eventSource.addEventListener(eventName, (message) => {
        handleStreamEvent(message, {
          console: true,
          timeline: true,
          refresh: true,
          refreshTakeaways: ["checks_resolved", "role_execution_summary", "challenger_done", "run_aborted", "workspace_guard_triggered", "step_handoff_written", "control_completed", "control_failed", "iteration_summary_written"].includes(eventName),
        });
      });
    });
  }

  document.addEventListener("loopora:localechange", () => {
    window.LooporaUI.applyLocalizedAttributes(document);
    buildConsoleControls();
    renderTakeaways();
    if (currentRun) {
      updateProgressPanel(currentRun);
      updateHighlights(currentRun);
    }
    renderTimeline();
    renderConsole();
    setObservationState(observationState);
  });

  buildConsoleControls();
  bindTakeawayActions();
  setObservationState("loading");
  renderRunDetailPanels();
  loadObservationSnapshot()
    .catch(() => {
      setObservationState("degraded");
      return fetchRun({shouldRefreshTakeaways: true}).catch(() => {});
    })
    .finally(() => connectRunStream());
