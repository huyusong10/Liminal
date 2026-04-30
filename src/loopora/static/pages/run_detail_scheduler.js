(function () {
  function createScheduler(options = {}) {
    const windowRef = options.windowRef || window;
    const documentRef = options.documentRef || document;
    const fetchRun = options.fetchRun || (() => Promise.resolve());
    const isActive = options.isActive || (() => false);
    const onHeartbeat = options.onHeartbeat || (() => {});
    const refreshDelayMs = Number(options.refreshDelayMs || 140);
    const pollIntervalMs = Number(options.pollIntervalMs || 2500);
    const heartbeatIntervalMs = Number(options.heartbeatIntervalMs || 1000);
    let refreshTimer = null;
    let refreshInFlight = false;
    let refreshQueued = false;
    let takeawayRefreshQueued = false;
    let pollTimer = null;
    let heartbeatTimer = null;

    function scheduleRunRefresh({immediate = false, refreshTakeaways = false} = {}) {
      if (refreshTakeaways) {
        takeawayRefreshQueued = true;
      }
      if (refreshTimer) {
        return;
      }
      refreshTimer = windowRef.setTimeout(async () => {
        refreshTimer = null;
        if (refreshInFlight) {
          refreshQueued = true;
          return;
        }
        refreshInFlight = true;
        const shouldRefreshTakeaways = takeawayRefreshQueued;
        takeawayRefreshQueued = false;
        try {
          await fetchRun({shouldRefreshTakeaways});
        } finally {
          refreshInFlight = false;
          if (refreshQueued) {
            refreshQueued = false;
            scheduleRunRefresh({immediate: true, refreshTakeaways: takeawayRefreshQueued});
          }
        }
      }, immediate ? 0 : refreshDelayMs);
    }

    function syncLiveRefreshers() {
      const active = Boolean(isActive());
      if (active && !pollTimer) {
        pollTimer = windowRef.setInterval(() => {
          if (documentRef.visibilityState === "hidden") {
            return;
          }
          scheduleRunRefresh({immediate: true});
        }, pollIntervalMs);
      } else if (!active && pollTimer) {
        windowRef.clearInterval(pollTimer);
        pollTimer = null;
      }

      if (active && !heartbeatTimer) {
        heartbeatTimer = windowRef.setInterval(onHeartbeat, heartbeatIntervalMs);
      } else if (!active && heartbeatTimer) {
        windowRef.clearInterval(heartbeatTimer);
        heartbeatTimer = null;
      }
    }

    function clear() {
      if (refreshTimer) {
        windowRef.clearTimeout(refreshTimer);
        refreshTimer = null;
      }
      if (pollTimer) {
        windowRef.clearInterval(pollTimer);
        pollTimer = null;
      }
      if (heartbeatTimer) {
        windowRef.clearInterval(heartbeatTimer);
        heartbeatTimer = null;
      }
      refreshInFlight = false;
      refreshQueued = false;
      takeawayRefreshQueued = false;
    }

    function snapshot() {
      return {
        hasRefreshTimer: Boolean(refreshTimer),
        refreshInFlight,
        refreshQueued,
        takeawayRefreshQueued,
        hasPollTimer: Boolean(pollTimer),
        hasHeartbeatTimer: Boolean(heartbeatTimer),
      };
    }

    return {
      scheduleRunRefresh,
      syncLiveRefreshers,
      clear,
      snapshot,
    };
  }

  window.LooporaRunDetailScheduler = {createScheduler};
})();
