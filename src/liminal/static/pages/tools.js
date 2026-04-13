document.addEventListener("DOMContentLoaded", () => {
  if (!window.LiminalUI) {
    return;
  }

  const statusBox = document.getElementById("skill-install-status");
  if (!statusBox) {
    return;
  }

  function localeText(zh, en) {
    return window.LiminalUI.pickText({zh, en});
  }

  function showStatus(message, kind = "") {
    if (!message) {
      statusBox.hidden = true;
      statusBox.textContent = "";
      statusBox.className = "field-status";
      return;
    }
    statusBox.hidden = false;
    statusBox.textContent = message;
    statusBox.className = `field-status${kind ? ` is-${kind}` : ""}`;
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
    window.LiminalUI.applyLocalizedAttributes(button);
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    const payload = await response.json().catch(() => ({}));
    return {response, payload};
  }

  async function refreshSkillTargets(options = {}) {
    const quiet = options.quiet ?? false;
    const {response, payload} = await fetchJson("/api/skills/liminal-spec");
    if (!response.ok) {
      if (!quiet) {
        showStatus(payload.error || localeText("无法读取 skill 安装状态。", "Unable to load skill install status."), "error");
      }
      return;
    }
    (payload.targets || []).forEach(updateSkillCard);
    if (!quiet) {
      showStatus("");
    }
  }

  async function installSkill(target, button) {
    if (!target) {
      return;
    }
    button.disabled = true;
    showStatus(localeText("正在安装 skill…", "Installing the skill…"));
    try {
      const {response, payload} = await fetchJson("/api/skills/liminal-spec/install", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({target}),
      });
      if (!response.ok) {
        showStatus(payload.error || localeText("安装失败。", "Installation failed."), "error");
        return;
      }
      (payload.targets || []).forEach(updateSkillCard);
      const actionText = payload.result?.action === "reinstalled"
        ? localeText("已覆盖安装。", "Reinstalled and replaced the existing files.")
        : localeText("安装完成。", "Installed successfully.");
      showStatus(
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

  document.querySelectorAll("[data-install-skill]").forEach((button) => {
    button.addEventListener("click", () => installSkill(button.dataset.installSkill, button));
  });

  refreshSkillTargets({quiet: true});
});
