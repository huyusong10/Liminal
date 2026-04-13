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

  function updateSkillCard(target) {
    const state = document.getElementById(`skill-state-${target.target}`);
    const path = document.getElementById(`skill-path-${target.target}`);
    if (!state || !path) {
      return;
    }
    state.className = `skill-target-state ${target.installed ? "is-installed" : "is-missing"}`;
    state.textContent = target.installed
      ? localeText("已安装", "Installed")
      : localeText("未安装", "Not installed");
    path.textContent = (target.install_paths || []).join(" · ");
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
      showStatus(
        localeText(
          `${payload.result.label} 安装完成。重新启动对应工具后会更稳妥地识别到新 skill。`,
          `${payload.result.label} install completed. Restarting that tool is the safest way to pick up the new skill.`
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
