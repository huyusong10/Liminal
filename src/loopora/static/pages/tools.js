document.addEventListener("DOMContentLoaded", () => {
  if (!window.LooporaUI) {
    return;
  }

  const wakeLockToggle = document.getElementById("wake-lock-toggle");
  const wakeLockStatusBox = document.getElementById("wake-lock-status");
  const wakeLockRuntimePill = document.getElementById("wake-lock-runtime-pill");
  const wakeLockHoldPill = document.getElementById("wake-lock-hold-pill");
  const wakeLockRuns = document.getElementById("wake-lock-runs");
  const skillInstallStatusBox = document.getElementById("skill-install-status");
  const skillInstallButtons = Array.from(document.querySelectorAll("[data-install-skill]"));
  const localAssetsStatusBox = document.getElementById("local-assets-status");
  const localAssetsCountNodes = Array.from(document.querySelectorAll("[data-local-assets-count]"));
  const localAssetsDetails = document.getElementById("local-assets-details");
  const WAKE_LOCK_PREF_KEY = "loopora:tools:wake-lock-enabled";
  let wakeLockSentinel = null;
  let runtimeActivity = {
    running_count: 0,
    queued_count: 0,
    has_running_runs: false,
    has_active_runs: false,
    runs: [],
  };
  let runtimeActivitySignature = JSON.stringify(runtimeActivity);

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
    const nextClassName = `field-status${kind ? ` is-${kind}` : ""}`;
    if (!message) {
      if (box.hidden && box.textContent === "" && box.className === "field-status") {
        return;
      }
      box.hidden = true;
      box.textContent = "";
      box.className = "field-status";
      return;
    }
    if (!box.hidden && box.textContent === message && box.className === nextClassName) {
      return;
    }
    box.hidden = false;
    box.textContent = message;
    box.className = nextClassName;
  }

  function updateNodeTextAndClass(node, text, className) {
    if (!node) {
      return;
    }
    if (node.textContent === text && node.className === className) {
      return;
    }
    node.textContent = text;
    node.className = className;
  }

  function fetchJson(url, options = {}) {
    return fetch(url, options).then(async (response) => {
      const payload = await response.json().catch(() => ({}));
      return {response, payload};
    });
  }

  function parentPath(path) {
    const value = String(path || "").replace(/[\\/]+$/, "");
    if (!value) {
      return "";
    }
    const slashIndex = Math.max(value.lastIndexOf("/"), value.lastIndexOf("\\"));
    if (slashIndex <= 0) {
      return value;
    }
    return value.slice(0, slashIndex);
  }

  function skillStateLabel(state) {
    if (state === "installed") {
      return localeText("已同步", "Up to date");
    }
    if (state === "stale") {
      return localeText("需覆盖更新", "Needs refresh");
    }
    return localeText("未安装", "Not installed");
  }

  function skillActionLabel(state) {
    if (state === "missing") {
      return localeText("安装", "Install");
    }
    if (state === "stale") {
      return localeText("覆盖更新", "Overwrite");
    }
    return localeText("重新安装", "Reinstall");
  }

  function renderSkillTargets(targets) {
    if (!Array.isArray(targets)) {
      return;
    }
    for (const target of targets) {
      const targetName = String(target.target || "");
      const state = String(target.install_state || "missing");
      const stateNode = document.getElementById(`skill-state-${targetName}`);
      const pathNode = document.getElementById(`skill-path-${targetName}`);
      const button = skillInstallButtons.find((candidate) => candidate.dataset.installSkill === targetName);
      if (stateNode) {
        stateNode.textContent = skillStateLabel(state);
        stateNode.className = `skill-target-state skill-target-state--${state} ${
          state === "installed" ? "is-installed" : state === "stale" ? "is-stale" : "is-missing"
        }`;
      }
      if (pathNode) {
        pathNode.textContent = Array.isArray(target.install_paths) ? target.install_paths.join(" · ") : "";
      }
      if (button) {
        button.textContent = skillActionLabel(state);
      }
    }
  }

  async function refreshSkillTargets(options = {}) {
    const quiet = options.quiet ?? false;
    const {response, payload} = await fetchJson("/api/skills/loopora-task-alignment");
    if (!response.ok) {
      if (!quiet) {
        showStatus(skillInstallStatusBox, payload.error || localeText("无法读取技能安装状态。", "Unable to load skill installation status."), "error");
      }
      return;
    }
    renderSkillTargets(payload.targets);
  }

  function renderLocalAssetDiagnostics(payload) {
    let total = 0;
    for (const node of localAssetsCountNodes) {
      const key = String(node.dataset.localAssetsCount || "");
      const count = Array.isArray(payload?.[key]) ? payload[key].length : 0;
      total += count;
      const label = key === "orphan_alignment_dirs"
        ? localeText("对话编排残留目录", "Alignment orphan dirs")
        : key === "orphan_bundle_dirs"
          ? localeText("方案包残留目录", "Bundle orphan dirs")
          : key === "orphan_run_dirs"
            ? localeText("运行残留目录", "Run orphan dirs")
            : localeText("记录缺失目录", "Records missing dirs");
      node.textContent = `${label}: ${count}`;
      node.className = `wake-lock-pill ${count > 0 ? "wake-lock-pill-warning" : "wake-lock-pill-neutral"}`;
    }
    renderLocalAssetDetails(payload, total);
  }

  function localAssetIssueConfig(key) {
    const configs = {
      orphan_alignment_dirs: {
        title: localeText("对话编排残留目录", "Alignment orphan directories"),
        idLabel: localeText("Session", "Session"),
        idField: "session_id",
        action: localeText("打开目录", "Open folder"),
        suggestion: localeText(
          "建议先检查 transcript、events 和 artifacts；确认这次对话已不需要后，再在文件管理器中手动清理。",
          "Inspect transcript, events, and artifacts first; once the chat is no longer needed, clean it up manually in your file manager.",
        ),
      },
      orphan_bundle_dirs: {
        title: localeText("方案包残留目录", "Bundle orphan directories"),
        idLabel: localeText("方案包", "Bundle"),
        idField: "bundle_id",
        action: localeText("打开目录", "Open folder"),
        suggestion: localeText(
          "建议打开目录确认里面是否还有要导出的方案文件；确认无用后手动清理。",
          "Open the folder and check whether any plan files still need to be exported; clean it manually once it is safe.",
        ),
      },
      orphan_run_dirs: {
        title: localeText("运行残留目录", "Run orphan directories"),
        idLabel: localeText("运行", "Run"),
        idField: "run_id",
        action: localeText("打开目录", "Open folder"),
        suggestion: localeText(
          "建议先检查 evidence、timeline 或输出文件；确认运行证据已迁移或不再需要后手动清理。",
          "Inspect evidence, timeline, or output files first; clean it manually after the run evidence is migrated or no longer needed.",
        ),
      },
      record_without_dir: {
        title: localeText("记录缺失目录", "Records missing directories"),
        idLabel: localeText("记录", "Record"),
        idField: "resource_id",
        action: localeText("打开上级目录", "Open parent folder"),
        suggestion: localeText(
          "这通常表示目录被外部移动或删除；建议确认记录是否仍要保留，必要时重新运行、重新导入或重新开始对话来重建目录。",
          "This usually means the folder was moved or removed externally; decide whether to keep the record, then rerun, reimport, or restart the chat if the directory must be recreated.",
        ),
      },
    };
    return configs[key] || {
      title: key,
      idLabel: "id",
      idField: "id",
      action: localeText("打开目录", "Open folder"),
      suggestion: "",
    };
  }

  function localAssetIssueMeta(key, item) {
    const config = localAssetIssueConfig(key);
    const id = String(item?.[config.idField] || item?.resource_id || item?.path || "-");
    const type = item?.resource_type ? `${item.resource_type} · ` : "";
    const source = item?.source ? ` · ${item.source}` : "";
    const workdir = item?.workdir ? ` · ${item.workdir}` : "";
    return `${config.idLabel}: ${type}${id}${source}${workdir}`;
  }

  function renderLocalAssetDetails(payload, total) {
    if (!localAssetsDetails) {
      return;
    }
    if (!total) {
      localAssetsDetails.hidden = true;
      localAssetsDetails.innerHTML = "";
      return;
    }
    const keys = ["orphan_alignment_dirs", "orphan_bundle_dirs", "orphan_run_dirs", "record_without_dir"];
    const sections = keys.map((key) => {
      const items = Array.isArray(payload?.[key]) ? payload[key] : [];
      if (!items.length) {
        return "";
      }
      const config = localAssetIssueConfig(key);
      const rows = items.map((item) => {
        const path = String(item?.path || "");
        const revealPath = key === "record_without_dir" ? parentPath(path) : path;
        return `
          <article class="local-assets-issue" data-testid="local-assets-issue" data-local-assets-kind="${escapeHtml(key)}">
            <div class="local-assets-issue-copy">
              <strong>${escapeHtml(localAssetIssueMeta(key, item))}</strong>
              <code>${escapeHtml(path || "-")}</code>
              <p>${escapeHtml(config.suggestion)}</p>
            </div>
            <div class="local-assets-issue-actions">
              <button
                class="secondary-button"
                type="button"
                data-local-assets-reveal-path="${escapeHtml(revealPath)}"
                data-local-assets-copy-path="${escapeHtml(path)}"
                data-testid="local-assets-reveal-button"
                ${revealPath ? "" : "disabled"}
              >${escapeHtml(config.action)}</button>
              <button
                class="ghost-button"
                type="button"
                data-local-assets-copy-path="${escapeHtml(path)}"
                data-testid="local-assets-copy-button"
              >${escapeHtml(localeText("复制路径", "Copy path"))}</button>
            </div>
          </article>
        `;
      }).join("");
      return `
        <section class="local-assets-issue-group" data-testid="local-assets-issue-group">
          <header>
            <strong>${escapeHtml(config.title)}</strong>
            <span>${items.length}</span>
          </header>
          <div class="local-assets-issue-list">${rows}</div>
        </section>
      `;
    }).join("");
    localAssetsDetails.hidden = false;
    localAssetsDetails.innerHTML = `
      <div class="local-assets-guidance">
        <strong>${escapeHtml(localeText("发现本地资产不一致", "Local asset mismatch found"))}</strong>
        <span>${escapeHtml(localeText("下面的动作只会定位或复制路径，不会删除文件或修改记录。", "These actions only reveal or copy paths; they do not delete files or modify records."))}</span>
      </div>
      ${sections}
    `;
  }

  async function copyText(value) {
    await navigator.clipboard.writeText(value);
  }

  async function revealLocalAssetPath(path, copyFallbackPath = path) {
    if (!path && copyFallbackPath) {
      await copyText(copyFallbackPath);
      showStatus(localAssetsStatusBox, localeText("路径已复制到剪贴板。", "Path copied to clipboard."), "success");
      return;
    }
    try {
      const {response, payload} = await fetchJson("/api/system/reveal-path", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({path}),
      });
      if (!response.ok) {
        throw new Error(payload.error || "failed");
      }
      showStatus(localAssetsStatusBox, localeText("已打开对应目录。", "Opened the corresponding folder."), "success");
    } catch (error) {
      try {
        await copyText(copyFallbackPath || path);
        showStatus(
          localAssetsStatusBox,
          localeText("无法自动打开，路径已复制到剪贴板。", "Could not open automatically; the path was copied to clipboard."),
          "warning",
        );
      } catch (_) {
        showStatus(
          localAssetsStatusBox,
          error?.message || localeText("无法打开目录。", "Unable to open the folder."),
          "error",
        );
      }
    }
  }

  async function refreshLocalAssetDiagnostics(options = {}) {
    const quiet = options.quiet ?? false;
    const {response, payload} = await fetchJson("/api/diagnostics/local-assets");
    if (!response.ok) {
      if (!quiet) {
        showStatus(localAssetsStatusBox, payload.error || localeText("无法读取本地资产诊断。", "Unable to load local asset diagnostics."), "error");
      }
      return;
    }
    renderLocalAssetDiagnostics(payload);
    showStatus(localAssetsStatusBox, "");
  }

  async function installSkillTarget(target) {
    showStatus(skillInstallStatusBox, localeText("正在安装技能…", "Installing skill…"));
    for (const button of skillInstallButtons) {
      button.disabled = true;
    }
    try {
      const {response, payload} = await fetchJson("/api/skills/loopora-task-alignment/install", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({target}),
      });
      if (!response.ok) {
        showStatus(skillInstallStatusBox, payload.error || localeText("技能安装失败。", "Skill installation failed."), "error");
        return;
      }
      renderSkillTargets(payload.targets);
      const result = payload.result || {};
      const paths = Array.isArray(result.written_paths) ? result.written_paths.join(" · ") : "";
      showStatus(
        skillInstallStatusBox,
        localeText(
          `已安装 ${result.skill_name || "技能"}。重启目标工具后生效。${paths ? ` 写入：${paths}` : ""}`,
          `${result.skill_name || "Skill"} installed. Restart the target tool to load it.${paths ? ` Written to: ${paths}` : ""}`,
        ),
        "success",
      );
    } catch (error) {
      showStatus(
        skillInstallStatusBox,
        localeText(`技能安装失败：${error?.message || "未知错误"}`, `Skill installation failed: ${error?.message || "unknown error"}`),
        "error",
      );
    } finally {
      for (const button of skillInstallButtons) {
        button.disabled = false;
      }
    }
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
    let text = localeText("当前没有活动运行", "No runs are currently executing");
    if (runningCount > 0) {
      className = "wake-lock-pill wake-lock-pill-running";
      text = localeText(
        `检测到 ${runningCount} 个活动运行${queuedCount ? `，另有 ${queuedCount} 个排队中` : ""}`,
        `${runningCount} running run(s) detected${queuedCount ? `, plus ${queuedCount} queued` : ""}`
      );
    } else if (queuedCount > 0) {
      className = "wake-lock-pill wake-lock-pill-queued";
      text = localeText(`当前有 ${queuedCount} 个运行在排队`, `${queuedCount} queued run(s) detected`);
    }
    updateNodeTextAndClass(wakeLockRuntimePill, text, className);
  }

  function updateWakeLockHoldPill() {
    if (!wakeLockHoldPill || !wakeLockToggle) {
      return;
    }
    if (!supportsWakeLock()) {
      updateNodeTextAndClass(
        wakeLockHoldPill,
        localeText("当前浏览器不支持防休眠锁", "This browser does not support the Wake Lock API"),
        "wake-lock-pill wake-lock-pill-warning",
      );
      return;
    }
    if (!wakeLockToggle.checked) {
      updateNodeTextAndClass(
        wakeLockHoldPill,
        localeText("防休眠开关处于关闭状态", "Wake lock is currently turned off"),
        "wake-lock-pill wake-lock-pill-neutral",
      );
      return;
    }
    if (wakeLockSentinel) {
      updateNodeTextAndClass(
        wakeLockHoldPill,
        localeText("已持有防休眠锁", "Wake lock is currently held"),
        "wake-lock-pill wake-lock-pill-held",
      );
      return;
    }
    if (document.visibilityState !== "visible") {
      updateNodeTextAndClass(
        wakeLockHoldPill,
        localeText("页面不可见，等待重新获取", "Waiting to reacquire once the page is visible again"),
        "wake-lock-pill wake-lock-pill-neutral",
      );
      return;
    }
    if (Number(runtimeActivity.running_count || 0) > 0) {
      updateNodeTextAndClass(
        wakeLockHoldPill,
        localeText("检测到活动运行，正在等待获取防休眠锁", "A run is active; waiting to acquire the wake lock"),
        "wake-lock-pill wake-lock-pill-neutral",
      );
      return;
    }
    updateNodeTextAndClass(
      wakeLockHoldPill,
        localeText("已开启，等有活动运行时再生效", "Enabled and standing by until a run is actively executing"),
      "wake-lock-pill wake-lock-pill-neutral",
    );
  }

  function renderRuntimeRuns() {
    if (!wakeLockRuns) {
      return;
    }
    const runs = Array.isArray(runtimeActivity.runs) ? runtimeActivity.runs : [];
    if (!runs.length) {
      wakeLockRuns.innerHTML = `
        <div class="wake-lock-empty">
          <span data-lang="zh">当前没有活动运行，这个开关会保持待命。</span>
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
        localeText("这个浏览器不支持屏幕防休眠锁，所以这里只能显示运行状态，不能真正阻止休眠。", "This browser does not support the Screen Wake Lock API, so this page can show run activity but cannot actually keep the screen awake."),
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
        localeText("开关已经打开，但当前没有活动运行，所以不会主动持有防休眠锁。", "The toggle is on, but there is no actively running task right now, so no wake lock is being held."),
      );
      return;
    }
    if (wakeLockSentinel) {
      showStatus(
        wakeLockStatusBox,
        localeText("已检测到活动运行，屏幕会尽量保持唤醒。", "An active run is detected, so the page is currently trying to keep the screen awake."),
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
        localeText("已持有防休眠锁；只要这个页面保持可见且仍有活动运行，就会继续阻止自动休眠。", "Wake lock acquired. As long as this page remains visible and a run is still active, the browser will keep trying to prevent automatic sleep."),
        "success",
      );
    } catch (error) {
      showStatus(
        wakeLockStatusBox,
        localeText(
          `没能拿到防休眠锁：${error?.message || "未知错误"}`,
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
    const nextSignature = JSON.stringify(payload || {});
    const changed = nextSignature !== runtimeActivitySignature;
    runtimeActivity = payload;
    runtimeActivitySignature = nextSignature;
    if (changed) {
      updateWakeLockRuntimePill();
      renderRuntimeRuns();
    }
    if (changed) {
      await syncWakeLock();
    }
  }

  wakeLockToggle.checked = readWakeLockPreference();
  updateWakeLockRuntimePill();
  updateWakeLockHoldPill();
  renderRuntimeRuns();

  for (const button of skillInstallButtons) {
    button.addEventListener("click", () => {
      const target = String(button.dataset.installSkill || "").trim();
      if (target) {
        installSkillTarget(target).catch(() => {});
      }
    });
  }

  localAssetsDetails?.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) {
      return;
    }
    const revealPath = target.dataset.localAssetsRevealPath || "";
    const copyPath = target.dataset.localAssetsCopyPath || "";
    if (target.dataset.localAssetsRevealPath !== undefined) {
      target.disabled = true;
      revealLocalAssetPath(revealPath, copyPath).finally(() => {
        target.disabled = false;
      });
      return;
    }
    if (target.dataset.localAssetsCopyPath !== undefined) {
      copyText(copyPath)
        .then(() => showStatus(localAssetsStatusBox, localeText("路径已复制到剪贴板。", "Path copied to clipboard."), "success"))
        .catch((error) => showStatus(localAssetsStatusBox, error?.message || localeText("无法复制路径。", "Unable to copy the path."), "error"));
    }
  });

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

  refreshRuntimeActivity({quiet: true});
  refreshLocalAssetDiagnostics({quiet: true}).catch(() => {});
  window.setInterval(() => {
    refreshRuntimeActivity({quiet: true}).catch(() => {});
  }, 15000);

  document.addEventListener("loopora:localechange", () => {
    updateWakeLockRuntimePill();
    updateWakeLockHoldPill();
    renderRuntimeRuns();
    refreshSkillTargets({quiet: true}).catch(() => {});
    refreshLocalAssetDiagnostics({quiet: true}).catch(() => {});
    syncWakeLock().catch(() => {});
  });
});
