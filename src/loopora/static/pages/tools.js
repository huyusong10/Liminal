document.addEventListener("DOMContentLoaded", () => {
  if (!window.LooporaUI) {
    return;
  }

  const skillStatusBox = document.getElementById("skill-install-status");
  const wakeLockToggle = document.getElementById("wake-lock-toggle");
  const wakeLockStatusBox = document.getElementById("wake-lock-status");
  const wakeLockRuntimePill = document.getElementById("wake-lock-runtime-pill");
  const wakeLockHoldPill = document.getElementById("wake-lock-hold-pill");
  const wakeLockRuns = document.getElementById("wake-lock-runs");
  const WAKE_LOCK_PREF_KEY = "loopora:tools:wake-lock-enabled";
  let wakeLockSentinel = null;
  let runtimeActivity = {
    running_count: 0,
    queued_count: 0,
    has_running_runs: false,
    has_active_runs: false,
    runs: [],
  };

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

  function showStatus(box, message, kind = "") {
    if (!box) {
      return;
    }
    if (!message) {
      box.hidden = true;
      box.textContent = "";
      box.className = "field-status";
      return;
    }
    box.hidden = false;
    box.textContent = message;
    box.className = `field-status${kind ? ` is-${kind}` : ""}`;
  }

  function fetchJson(url, options = {}) {
    return fetch(url, options).then(async (response) => {
      const payload = await response.json().catch(() => ({}));
      return {response, payload};
    });
  }

  function readWakeLockPreference() {
    try {
      return window.localStorage.getItem(WAKE_LOCK_PREF_KEY) === "1";
    } catch (_) {
      return false;
    }
  }

  function persistWakeLockPreference(enabled) {
    try {
      window.localStorage.setItem(WAKE_LOCK_PREF_KEY, enabled ? "1" : "0");
    } catch (_) {
      // Ignore storage failures.
    }
  }

  function supportsWakeLock() {
    return Boolean(navigator.wakeLock && typeof navigator.wakeLock.request === "function");
  }

  function displayIter(value, fallback = 1) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed < 0) {
      return fallback;
    }
    return Math.floor(parsed) + 1;
  }

  function updateWakeLockRuntimePill() {
    if (!wakeLockRuntimePill) {
      return;
    }
    const runningCount = Number(runtimeActivity.running_count || 0);
    const queuedCount = Number(runtimeActivity.queued_count || 0);
    let className = "wake-lock-pill wake-lock-pill-neutral";
    let text = localeText("当前没有运行中的任务", "No runs are currently executing");
    if (runningCount > 0) {
      className = "wake-lock-pill wake-lock-pill-running";
      text = localeText(
        `检测到 ${runningCount} 个运行中的 run${queuedCount ? `，另有 ${queuedCount} 个排队中` : ""}`,
        `${runningCount} running run(s) detected${queuedCount ? `, plus ${queuedCount} queued` : ""}`
      );
    } else if (queuedCount > 0) {
      className = "wake-lock-pill wake-lock-pill-queued";
      text = localeText(`当前有 ${queuedCount} 个 run 在排队`, `${queuedCount} queued run(s) detected`);
    }
    wakeLockRuntimePill.className = className;
    wakeLockRuntimePill.textContent = text;
  }

  function updateWakeLockHoldPill() {
    if (!wakeLockHoldPill || !wakeLockToggle) {
      return;
    }
    if (!supportsWakeLock()) {
      wakeLockHoldPill.className = "wake-lock-pill wake-lock-pill-warning";
      wakeLockHoldPill.textContent = localeText("当前浏览器不支持 Wake Lock", "This browser does not support the Wake Lock API");
      return;
    }
    if (!wakeLockToggle.checked) {
      wakeLockHoldPill.className = "wake-lock-pill wake-lock-pill-neutral";
      wakeLockHoldPill.textContent = localeText("防休眠开关处于关闭状态", "Wake lock is currently turned off");
      return;
    }
    if (wakeLockSentinel) {
      wakeLockHoldPill.className = "wake-lock-pill wake-lock-pill-held";
      wakeLockHoldPill.textContent = localeText("已持有 wake lock", "Wake lock is currently held");
      return;
    }
    if (document.visibilityState !== "visible") {
      wakeLockHoldPill.className = "wake-lock-pill wake-lock-pill-neutral";
      wakeLockHoldPill.textContent = localeText("页面不可见，等待重新获取", "Waiting to reacquire once the page is visible again");
      return;
    }
    if (Number(runtimeActivity.running_count || 0) > 0) {
      wakeLockHoldPill.className = "wake-lock-pill wake-lock-pill-neutral";
      wakeLockHoldPill.textContent = localeText("运行中，正在等待获取 wake lock", "A run is active; waiting to acquire the wake lock");
      return;
    }
    wakeLockHoldPill.className = "wake-lock-pill wake-lock-pill-neutral";
    wakeLockHoldPill.textContent = localeText("已开启，等有运行中的任务时再生效", "Enabled and standing by until a run is actively executing");
  }

  function renderRuntimeRuns() {
    if (!wakeLockRuns) {
      return;
    }
    const runs = Array.isArray(runtimeActivity.runs) ? runtimeActivity.runs : [];
    if (!runs.length) {
      wakeLockRuns.innerHTML = `
        <div class="wake-lock-empty">
          <span data-lang="zh">当前没有活动中的 run，这个开关会保持待命。</span>
          <span data-lang="en">There are no active runs right now, so the wake lock stays on standby.</span>
        </div>
      `;
      return;
    }
    wakeLockRuns.innerHTML = runs.map((run) => {
      const role = run.active_role ? window.LooporaUI.translateRole(run.active_role) : localeText("等待调度", "Waiting");
      const status = window.LooporaUI.translateStatus(run.status || "queued");
      const iter = localeText(`第 ${displayIter(run.current_iter)} 轮`, `Round ${displayIter(run.current_iter)}`);
      return `
        <a class="wake-lock-run-card" href="/runs/${encodeURIComponent(run.id)}">
          <div class="wake-lock-run-head">
            <strong>${escapeHtml(run.loop_name || run.id)}</strong>
            <span class="wake-lock-run-state wake-lock-run-state-${escapeHtml(run.status || "queued")}">${escapeHtml(status)}</span>
          </div>
          <p class="wake-lock-run-meta">${escapeHtml(role)} · ${escapeHtml(iter)}</p>
          <p class="wake-lock-run-path">${escapeHtml(run.workdir || "")}</p>
        </a>
      `;
    }).join("");
  }

  async function releaseWakeLock() {
    if (!wakeLockSentinel) {
      updateWakeLockHoldPill();
      return;
    }
    const current = wakeLockSentinel;
    wakeLockSentinel = null;
    try {
      await current.release();
    } catch (_) {
      // Ignore release errors; the sentinel is no longer useful either way.
    }
    updateWakeLockHoldPill();
  }

  async function syncWakeLock() {
    updateWakeLockHoldPill();
    if (!wakeLockToggle || !wakeLockToggle.checked) {
      await releaseWakeLock();
      showStatus(wakeLockStatusBox, "");
      return;
    }
    if (!supportsWakeLock()) {
      showStatus(
        wakeLockStatusBox,
        localeText("这个浏览器不支持 Screen Wake Lock，所以这里只能显示运行状态，不能真正阻止休眠。", "This browser does not support the Screen Wake Lock API, so this page can show run activity but cannot actually keep the screen awake."),
        "warning",
      );
      return;
    }
    if (document.visibilityState !== "visible") {
      await releaseWakeLock();
      showStatus(
        wakeLockStatusBox,
        localeText("页面当前不可见；回到这个工具页后会自动重新尝试。", "The page is not visible right now. It will automatically retry once you come back to this Tools tab."),
      );
      return;
    }
    if (Number(runtimeActivity.running_count || 0) <= 0) {
      await releaseWakeLock();
      showStatus(
        wakeLockStatusBox,
        localeText("开关已经打开，但当前没有运行中的任务，所以不会主动持有 wake lock。", "The toggle is on, but there is no actively running task right now, so no wake lock is being held."),
      );
      return;
    }
    if (wakeLockSentinel) {
      showStatus(
        wakeLockStatusBox,
        localeText("已检测到运行中的任务，屏幕会尽量保持唤醒。", "An active run is detected, so the page is currently trying to keep the screen awake."),
        "success",
      );
      updateWakeLockHoldPill();
      return;
    }
    try {
      wakeLockSentinel = await navigator.wakeLock.request("screen");
      wakeLockSentinel.addEventListener("release", () => {
        wakeLockSentinel = null;
        updateWakeLockHoldPill();
        if (wakeLockToggle.checked && document.visibilityState === "visible" && Number(runtimeActivity.running_count || 0) > 0) {
          window.setTimeout(() => {
            syncWakeLock().catch(() => {});
          }, 200);
        }
      });
      showStatus(
        wakeLockStatusBox,
        localeText("已持有 wake lock；只要这个页面保持可见且任务仍在运行，就会继续阻止自动休眠。", "Wake lock acquired. As long as this page remains visible and a run is still active, the browser will keep trying to prevent automatic sleep."),
        "success",
      );
    } catch (error) {
      showStatus(
        wakeLockStatusBox,
        localeText(
          `没能拿到 wake lock：${error?.message || "未知错误"}`,
          `Unable to acquire the wake lock: ${error?.message || "unknown error"}`
        ),
        "error",
      );
    }
    updateWakeLockHoldPill();
  }

  async function refreshRuntimeActivity(options = {}) {
    const quiet = options.quiet ?? false;
    const {response, payload} = await fetchJson("/api/runtime/activity");
    if (!response.ok) {
      if (!quiet) {
        showStatus(wakeLockStatusBox, payload.error || localeText("无法读取当前运行状态。", "Unable to load the current run activity."), "error");
      }
      return;
    }
    runtimeActivity = payload;
    updateWakeLockRuntimePill();
    renderRuntimeRuns();
    await syncWakeLock();
  }

  function stateMeta(installState) {
    if (installState === "installed") {
      return {
        className: "is-installed",
        label: localeText("已同步", "Up to date"),
        buttonZh: "重新安装",
        buttonEn: "Reinstall",
      };
    }
    if (installState === "stale") {
      return {
        className: "is-stale",
        label: localeText("需覆盖更新", "Needs refresh"),
        buttonZh: "覆盖更新",
        buttonEn: "Overwrite",
      };
    }
    return {
      className: "is-missing",
      label: localeText("未安装", "Not installed"),
      buttonZh: "安装",
      buttonEn: "Install",
    };
  }

  function updateSkillCard(target) {
    const state = document.getElementById(`skill-state-${target.target}`);
    const path = document.getElementById(`skill-path-${target.target}`);
    const button = document.querySelector(`[data-install-skill="${target.target}"]`);
    if (!state || !path || !button) {
      return;
    }
    const meta = stateMeta(target.install_state);
    state.className = `skill-target-state skill-target-state--${target.install_state} ${meta.className}`;
    state.textContent = meta.label;
    path.textContent = (target.install_paths || []).join(" · ");
    button.innerHTML = `<span data-lang="zh">${meta.buttonZh}</span><span data-lang="en">${meta.buttonEn}</span>`;
    window.LooporaUI.applyLocalizedAttributes(button);
  }

  async function refreshSkillTargets(options = {}) {
    const quiet = options.quiet ?? false;
    const {response, payload} = await fetchJson("/api/skills/loopora-spec");
    if (!response.ok) {
      if (!quiet) {
        showStatus(skillStatusBox, payload.error || localeText("无法读取 skill 安装状态。", "Unable to load skill install status."), "error");
      }
      return;
    }
    (payload.targets || []).forEach(updateSkillCard);
    if (!quiet) {
      showStatus(skillStatusBox, "");
    }
  }

  async function installSkill(target, button) {
    if (!target) {
      return;
    }
    button.disabled = true;
    showStatus(skillStatusBox, localeText("正在安装 skill…", "Installing the skill…"));
    try {
      const {response, payload} = await fetchJson("/api/skills/loopora-spec/install", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({target}),
      });
      if (!response.ok) {
        showStatus(skillStatusBox, payload.error || localeText("安装失败。", "Installation failed."), "error");
        return;
      }
      (payload.targets || []).forEach(updateSkillCard);
      const actionText = payload.result?.action === "reinstalled"
        ? localeText("已覆盖安装。", "Reinstalled and replaced the existing files.")
        : localeText("安装完成。", "Installed successfully.");
      showStatus(
        skillStatusBox,
        localeText(
          `${payload.result.label} ${actionText} 重新启动对应工具后会更稳妥地识别到新 skill。`,
          `${payload.result.label}: ${actionText} Restarting that tool is the safest way to pick up the new skill.`
        ),
        "success",
      );
    } finally {
      button.disabled = false;
    }
  }

  wakeLockToggle.checked = readWakeLockPreference();
  updateWakeLockRuntimePill();
  updateWakeLockHoldPill();
  renderRuntimeRuns();

  wakeLockToggle.addEventListener("change", async () => {
    persistWakeLockPreference(wakeLockToggle.checked);
    await syncWakeLock();
  });

  document.addEventListener("visibilitychange", () => {
    syncWakeLock().catch(() => {});
  });

  window.addEventListener("beforeunload", () => {
    releaseWakeLock().catch(() => {});
  });

  document.querySelectorAll("[data-install-skill]").forEach((button) => {
    button.addEventListener("click", () => installSkill(button.dataset.installSkill, button));
  });

  refreshSkillTargets({quiet: true});
  refreshRuntimeActivity({quiet: true});
  window.setInterval(() => {
    refreshRuntimeActivity({quiet: true}).catch(() => {});
  }, 5000);

  document.addEventListener("loopora:localechange", () => {
    updateWakeLockRuntimePill();
    updateWakeLockHoldPill();
    renderRuntimeRuns();
    refreshSkillTargets({quiet: true}).catch(() => {});
    syncWakeLock().catch(() => {});
  });
});
