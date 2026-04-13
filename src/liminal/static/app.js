(() => {
  const STATUS_LABELS = {
    zh: {
      draft: "草稿",
      queued: "排队中",
      running: "运行中",
      succeeded: "已完成",
      failed: "失败",
      stopped: "已停止",
    },
    en: {
      draft: "draft",
      queued: "queued",
      running: "running",
      succeeded: "succeeded",
      failed: "failed",
      stopped: "stopped",
    },
  };

  const ROLE_LABELS = {
    zh: {
      generator: "generator",
      check_planner: "检查规划",
      tester: "tester",
      verifier: "verifier",
      challenger: "challenger",
      system: "系统",
    },
    en: {
      generator: "generator",
      check_planner: "check planner",
      tester: "tester",
      verifier: "verifier",
      challenger: "challenger",
      system: "system",
    },
  };

  function readSavedLocale() {
    try {
      const saved = window.localStorage.getItem("liminal:locale");
      if (saved === "zh" || saved === "en") {
        return saved;
      }
    } catch (_) {
      // Ignore storage access issues and fall back to environment detection.
    }
    return null;
  }

  function normalizeLocale(value) {
    if (typeof value !== "string") {
      return "";
    }
    return value.trim().replace(/_/g, "-").toLowerCase();
  }

  function isChineseLocale(value) {
    const locale = normalizeLocale(value);
    return locale === "zh" || locale.startsWith("zh-") || locale.includes("-hans") || locale.includes("-hant");
  }

  function detectPreferredLocale() {
    const saved = readSavedLocale();
    if (saved) {
      return saved;
    }

    const nav = typeof navigator === "object" && navigator ? navigator : {};
    const systemCandidates = [];
    const browserCandidates = [];

    if (typeof nav.systemLanguage === "string") {
      systemCandidates.push(nav.systemLanguage);
    }

    try {
      const intlLocale = Intl.DateTimeFormat().resolvedOptions().locale;
      if (typeof intlLocale === "string") {
        systemCandidates.push(intlLocale);
      }
    } catch (_) {
      // Ignore Intl availability issues.
    }

    if (Array.isArray(nav.languages) && nav.languages.length > 0) {
      browserCandidates.push(nav.languages[0]);
    }
    browserCandidates.push(nav.language, nav.userLanguage, nav.browserLanguage);

    if (systemCandidates.some(isChineseLocale)) {
      return "zh";
    }
    if (browserCandidates.some(isChineseLocale)) {
      return "zh";
    }
    return "en";
  }

  function initialLocale() {
    return detectPreferredLocale();
  }

  function currentLocale() {
    return document.documentElement.dataset.locale || initialLocale();
  }

  function pickText(values) {
    return currentLocale() === "zh" ? values.zh : values.en;
  }

  function translateStatus(value) {
    return STATUS_LABELS[currentLocale()][value] || value || "-";
  }

  function translateRole(value) {
    if (!value || value === "-") {
      return "-";
    }
    return ROLE_LABELS[currentLocale()][value] || value;
  }

  function applyLocalizedAttributes(root = document) {
    root.querySelectorAll("[data-placeholder-zh]").forEach((element) => {
      const placeholder = currentLocale() === "zh" ? element.dataset.placeholderZh : element.dataset.placeholderEn;
      if (placeholder) {
        element.setAttribute("placeholder", placeholder);
      }
    });

    root.querySelectorAll("[data-title-zh]").forEach((element) => {
      const title = currentLocale() === "zh" ? element.dataset.titleZh : element.dataset.titleEn;
      if (title) {
        element.setAttribute("data-tooltip", title);
        element.setAttribute("title", title);
        element.setAttribute("aria-label", title);
      }
    });

    root.querySelectorAll("[data-status-label]").forEach((element) => {
      element.textContent = translateStatus(element.dataset.statusLabel);
    });

    root.querySelectorAll("[data-role-label]").forEach((element) => {
      element.textContent = translateRole(element.dataset.roleLabel);
    });
  }

  function syncLocaleButtons() {
    document.querySelectorAll("[data-set-locale]").forEach((button) => {
      button.classList.toggle("active", button.dataset.setLocale === currentLocale());
    });
  }

  function setLocale(locale, options = {}) {
    if (locale !== "zh" && locale !== "en") {
      return;
    }
    const persist = options.persist !== false;
    document.documentElement.dataset.locale = locale;
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
    if (persist) {
      try {
        window.localStorage.setItem("liminal:locale", locale);
      } catch (_) {
        // Ignore storage access issues.
      }
    }
    applyLocalizedAttributes(document);
    syncLocaleButtons();
    document.dispatchEvent(new CustomEvent("liminal:localechange", {detail: {locale}}));
  }

  function bindDeleteLoopButtons() {
    document.querySelectorAll("[data-delete-loop]").forEach((button) => {
      if (button.dataset.bound === "1") {
        return;
      }
      button.dataset.bound = "1";
      button.addEventListener("click", async () => {
        const loopId = button.dataset.deleteLoop;
        const loopName = button.dataset.loopName || loopId;
        const confirmed = window.confirm(
          pickText({
            zh: `删除 loop "${loopName}"？这也会移除它保存的运行记录。`,
            en: `Delete loop "${loopName}"? This also removes its stored runs.`,
          }),
        );
        if (!confirmed) {
          return;
        }

        const response = await fetch(`/api/loops/${encodeURIComponent(loopId)}`, {method: "DELETE"});
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          window.alert(payload.error || pickText({
            zh: "删除失败。",
            en: "Unable to delete the loop.",
          }));
          return;
        }
        window.location.reload();
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    setLocale(initialLocale(), {persist: false});
    document.querySelectorAll("[data-set-locale]").forEach((button) => {
      button.addEventListener("click", () => setLocale(button.dataset.setLocale));
    });
    bindDeleteLoopButtons();
  });

  window.LiminalUI = {
    currentLocale,
    detectPreferredLocale,
    setLocale,
    pickText,
    translateStatus,
    translateRole,
    applyLocalizedAttributes,
    bindDeleteLoopButtons,
  };
})();
