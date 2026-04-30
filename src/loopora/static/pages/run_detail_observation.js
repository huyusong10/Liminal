(function () {
  const TERMINAL_RUN_STATUSES = new Set(["succeeded", "failed", "stopped"]);
  const DEFAULT_RETRY_DELAYS_MS = [1000, 2000, 5000, 10000];

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function numericId(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function isTerminalRun(run) {
    return TERMINAL_RUN_STATUSES.has(String(run?.status || ""));
  }

  function normalizedLatestEventId(...values) {
    return values.reduce((latest, value) => Math.max(latest, numericId(value)), 0);
  }

  function boundedEvents(events, limit) {
    return asArray(events).slice(-Math.max(0, Number(limit) || 0));
  }

  function normalizeSnapshotPayload(payload = {}, fallbackRun = {}) {
    return {
      run: payload.run && typeof payload.run === "object" ? payload.run : fallbackRun,
      latestEventId: numericId(payload.latest_event_id),
      timelineEvents: boundedEvents(payload.timeline_events, 40),
      consoleEvents: boundedEvents(payload.console_events, 160),
      progressEvents: boundedEvents(payload.progress_events, 2000),
      keyTakeaways: payload.key_takeaways && typeof payload.key_takeaways === "object" ? payload.key_takeaways : {},
    };
  }

  function mergeSnapshotState(state, payload) {
    const snapshot = normalizeSnapshotPayload(payload, state.currentRun || {});
    return {
      ...state,
      currentRun: snapshot.run,
      timelineRecords: snapshot.timelineEvents,
      consoleEventRecords: snapshot.consoleEvents,
      progressEventRecords: snapshot.progressEvents,
      takeawaySnapshot: snapshot.keyTakeaways,
      lastEventId: normalizedLatestEventId(state.lastEventId, snapshot.latestEventId),
      observationState: isTerminalRun(snapshot.run) ? "finished" : "ready",
    };
  }

  function appendUniqueEvent(records, event, limit) {
    const eventId = numericId(event?.id);
    if (eventId && asArray(records).some((record) => numericId(record?.id) === eventId)) {
      return asArray(records).slice(-limit);
    }
    return [...asArray(records), event].slice(-limit);
  }

  function applyRunEvent(currentRun, event) {
    const payload = event?.payload || {};
    if (!currentRun || !event?.event_type) {
      return currentRun;
    }
    if (event.event_type === "role_started") {
      return {
        ...currentRun,
        status: "running",
        active_role: payload.role || currentRun.active_role,
        current_iter: payload.iter ?? currentRun.current_iter,
      };
    }
    if (event.event_type === "run_finished") {
      return {
        ...currentRun,
        status: payload.status || currentRun.status,
        active_role: null,
        current_iter: payload.iter ?? currentRun.current_iter,
        finished_at: event.created_at || currentRun.finished_at,
      };
    }
    if (event.event_type === "run_aborted") {
      return {
        ...currentRun,
        status: "failed",
        active_role: null,
      };
    }
    return currentRun;
  }

  function streamFailureState({run, failureCount}) {
    if (isTerminalRun(run)) {
      return "finished";
    }
    return Number(failureCount || 0) > 3 ? "stream-stale" : "stream-error";
  }

  function nextRetryDelay(failureCount, retryDelays = DEFAULT_RETRY_DELAYS_MS) {
    const delays = Array.isArray(retryDelays) && retryDelays.length ? retryDelays : DEFAULT_RETRY_DELAYS_MS;
    const index = Math.max(0, Math.min(delays.length - 1, Number(failureCount || 1) - 1));
    return Number(delays[index]) || DEFAULT_RETRY_DELAYS_MS[Math.min(DEFAULT_RETRY_DELAYS_MS.length - 1, index)];
  }

  function shouldReconnect(run) {
    return !isTerminalRun(run);
  }

  function stateAfterStreamEvent({run, eventType, fallbackState = "ready"}) {
    if (eventType === "run_finished") {
      return "finished";
    }
    if (isTerminalRun(run)) {
      return "finished";
    }
    return fallbackState === "loading" ? "ready" : fallbackState;
  }

  window.LooporaRunDetailObservation = {
    DEFAULT_RETRY_DELAYS_MS,
    appendUniqueEvent,
    applyRunEvent,
    isTerminalRun,
    mergeSnapshotState,
    nextRetryDelay,
    normalizeSnapshotPayload,
    shouldReconnect,
    stateAfterStreamEvent,
    streamFailureState,
  };
})();
