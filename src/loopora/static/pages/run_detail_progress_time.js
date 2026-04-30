(function () {
  function createProgressTimeHelpers(deps = {}) {
    const localeText = deps.localeText || ((zh, en) => en || zh || "");

    function formatDurationMs(value) {
      if (value === undefined || value === null || Number.isNaN(Number(value))) {
        return "";
      }
      const ms = Number(value);
      if (ms < 1000) {
        return `${Math.round(ms)}ms`;
      }
      const seconds = ms / 1000;
      return seconds >= 10 ? `${seconds.toFixed(1)}s` : `${seconds.toFixed(2)}s`;
    }

    function formatStageDuration(ms) {
      const totalSeconds = Math.max(0, Math.round(Number(ms || 0) / 1000));
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
