(function () {
  function createStreamController(options = {}) {
    const observation = options.observation || window.LooporaRunDetailObservation;
    const retryDelays = options.retryDelays || observation.DEFAULT_RETRY_DELAYS_MS;
    const getRun = options.getRun || (() => null);
    const setObservationState = options.setObservationState || (() => {});
    const scheduleReconnect = options.scheduleReconnect || (() => {});
    let failureCount = 0;
    let suppressNextConnectionError = false;

    function resetFailures() {
      failureCount = 0;
      suppressNextConnectionError = false;
      return failureCount;
    }

    function markFailure(source = "connection") {
      const run = getRun();
      if (!observation.shouldReconnect(run)) {
        setObservationState("finished");
        return {counted: false, failureCount, reconnect: false, state: "finished"};
      }
      if (source === "connection" && suppressNextConnectionError) {
        suppressNextConnectionError = false;
        return {counted: false, failureCount, reconnect: false, state: null};
      }
      if (source === "stream_error") {
        suppressNextConnectionError = true;
      }
      failureCount += 1;
      const state = observation.streamFailureState({run, failureCount});
      const delay = observation.nextRetryDelay(failureCount, retryDelays);
      setObservationState(state);
      scheduleReconnect(delay);
      return {counted: true, failureCount, reconnect: true, state, delay};
    }

    function getFailureCount() {
      return failureCount;
    }

    return {
      getFailureCount,
      markFailure,
      resetFailures,
    };
  }

  window.LooporaRunDetailStream = {
    createStreamController,
  };
})();
