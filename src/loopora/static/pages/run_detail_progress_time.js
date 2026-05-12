(function () {
  function createProgressTimeHelpers(deps = {}) {
    const localeText = deps.localeText || ((zh, en) => en || zh || "");

    function nonNegativeNumber(value) {
      return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
    }

    function formatDurationMs(value) {
      const ms = nonNegativeNumber(value);
      if (ms === null) {
        return "";
      }
      if (ms < 1000) {
        return `${Math.round(ms)}ms`;
      }
      const seconds = ms / 1000;
      return seconds >= 10 ? `${seconds.toFixed(1)}s` : `${seconds.toFixed(2)}s`;
    }

    function formatStageDuration(ms) {
      const normalized = nonNegativeNumber(ms);
      if (normalized === null) {
        return "";
      }
      const totalSeconds = Math.round(normalized / 1000);
      if (!totalSeconds) {
        return "";
      }
      const hours = Math.floor(totalSeconds / 3600);
      const minutes = Math.floor((totalSeconds % 3600) / 60);
      const seconds = totalSeconds % 60;
      if (hours) {
        return minutes
          ? localeText(`${hours} 小时 ${minutes} 分`, `${hours}h ${minutes}m`)
          : localeText(`${hours} 小时`, `${hours}h`);
      }
      if (minutes) {
        return seconds
          ? localeText(`${minutes} 分 ${seconds} 秒`, `${minutes}m ${seconds}s`)
          : localeText(`${minutes} 分钟`, `${minutes}m`);
      }
      return localeText(`${seconds} 秒`, `${seconds}s`);
    }

    return {
      formatDurationMs,
      formatStageDuration,
    };
  }

  window.LooporaRunDetailProgressTime = {createProgressTimeHelpers};
})();
