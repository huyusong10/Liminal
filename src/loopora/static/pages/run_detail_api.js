(function () {
  async function jsonRequest(url, options = {}) {
    const response = await fetch(url, options);
    let payload = {};
    try {
      payload = await response.json();
    } catch (_) {
      payload = {};
    }
    if (!response.ok) {
      throw new Error(payload.error || `request failed: ${response.status}`);
    }
    return payload;
  }

  function runUrl(runId, suffix = "") {
    return `/api/runs/${encodeURIComponent(runId)}${suffix}`;
  }

  function fetchRun(runId) {
    return jsonRequest(runUrl(runId));
  }

  function fetchKeyTakeaways(runId) {
    return jsonRequest(runUrl(runId, "/key-takeaways"));
  }

  function fetchObservationSnapshot(runId) {
    return jsonRequest(runUrl(runId, "/observation-snapshot"));
  }

  function stopRun(runId) {
    return jsonRequest(runUrl(runId, "/stop"), {method: "POST"});
  }

  function revealPath(path) {
    return jsonRequest("/api/system/reveal-path", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path}),
    });
  }

  window.LooporaRunDetailApi = {
    fetchKeyTakeaways,
    fetchObservationSnapshot,
    fetchRun,
    revealPath,
    stopRun,
  };
})();
