(function () {
  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function numericId(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function copyState(state) {
    return {
      ...state,
      timelineRecords: asArray(state.timelineRecords).slice(),
      consoleEventRecords: asArray(state.consoleEventRecords).slice(),
      progressEventRecords: asArray(state.progressEventRecords).slice(),
      takeawaySnapshot: state.takeawaySnapshot && typeof state.takeawaySnapshot === "object"
        ? {...state.takeawaySnapshot}
        : {},
    };
  }

  function normalizeState(state = {}) {
    return {
      currentRun: state.currentRun || {},
      timelineRecords: asArray(state.timelineRecords),
      consoleEventRecords: asArray(state.consoleEventRecords),
      progressEventRecords: asArray(state.progressEventRecords),
      takeawaySnapshot: state.takeawaySnapshot && typeof state.takeawaySnapshot === "object"
        ? state.takeawaySnapshot
        : {},
      lastEventId: numericId(state.lastEventId),
      observationState: state.observationState || "loading",
    };
  }

  function createRunDetailState(initialState = {}, options = {}) {
    const observation = options.observation || window.LooporaRunDetailObservation;
    let state = normalizeState(initialState);

    function getState() {
      return copyState(state);
    }

    function replace(patch = {}) {
      state = normalizeState({...state, ...patch});
      return getState();
    }

    function mergeSnapshot(payload = {}) {
      state = normalizeState(observation.mergeSnapshotState(state, payload));
      return getState();
    }

    function applyStreamEvent(event = {}) {
      const eventId = numericId(event.id);
      if (eventId > 0 && eventId <= state.lastEventId) {
        return {duplicate: true, event: null, state: getState()};
      }
      state = normalizeState({
        ...state,
        currentRun: observation.applyRunEvent(state.currentRun, event),
        lastEventId: Math.max(state.lastEventId, eventId),
      });
      return {duplicate: false, event, state: getState()};
    }

    return {
      applyStreamEvent,
      getState,
      mergeSnapshot,
      replace,
    };
  }

  window.LooporaRunDetailState = {
    createRunDetailState,
  };
})();
