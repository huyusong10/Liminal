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
      generator: "建造者",
      builder: "建造者",
      check_planner: "检查规划",
      tester: "巡检者",
      inspector: "巡检者",
      verifier: "守门人",
      gatekeeper: "守门人",
      challenger: "向导",
      guide: "向导",
      system: "系统",
    },
    en: {
      generator: "Builder",
      builder: "Builder",
      check_planner: "check planner",
      tester: "Inspector",
      inspector: "Inspector",
      verifier: "GateKeeper",
      gatekeeper: "GateKeeper",
      challenger: "Guide",
      guide: "Guide",
      system: "system",
    },
  };

  function readSavedLocale() {
    try {
      const saved = window.localStorage.getItem("loopora:locale");
      if (saved === "zh" || saved === "en") {
        return saved;
      }
    } catch (_) {
      // Ignore storage access issues and fall back to environment detection.
    }
    return null;
  }

  function readSavedTheme() {
    try {
      const saved = window.localStorage.getItem("loopora:theme");
      if (saved === "light" || saved === "dark") {
        return saved;
      }
    } catch (_) {
      // Ignore storage access issues and fall back to system preferences.
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

  function initialTheme() {
    const saved = readSavedTheme();
    if (saved) {
      return saved;
    }
    const prefersDark = typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-color-scheme: dark)").matches;
    return prefersDark ? "dark" : "light";
  }

  function currentTheme() {
    return document.documentElement.dataset.theme || initialTheme();
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
        window.localStorage.setItem("loopora:locale", locale);
      } catch (_) {
        // Ignore storage access issues.
      }
    }
    applyLocalizedAttributes(document);
    syncLocaleButtons();
    document.dispatchEvent(new CustomEvent("loopora:localechange", {detail: {locale}}));
  }

  function setTheme(theme, options = {}) {
    if (theme !== "light" && theme !== "dark") {
      return;
    }
    const persist = options.persist !== false;
    document.documentElement.dataset.theme = theme;
    if (persist) {
      try {
        window.localStorage.setItem("loopora:theme", theme);
      } catch (_) {
        // Ignore storage access issues.
      }
    }
    document.querySelectorAll("[data-set-theme]").forEach((button) => {
      button.classList.toggle("active", button.dataset.setTheme === theme);
    });
    document.dispatchEvent(new CustomEvent("loopora:themechange", {detail: {theme}}));
  }

  function bindDeleteLoopButtons() {
    const modal = document.getElementById("confirm-modal");
    const modalDetail = document.getElementById("confirm-modal-detail");
    const modalCancel = document.getElementById("confirm-modal-cancel");
    const modalConfirm = document.getElementById("confirm-modal-confirm");
    const modalBackdrop = modal?.querySelector("[data-close-confirm-modal]");
    const loopCount = document.getElementById("loop-count");
    const loopGrid = document.getElementById("loop-grid");
    const emptyState = document.getElementById("loops-empty-state");
    const loopGridNote = document.querySelector(".loop-grid-note");
    if (!modal || !modalDetail || !modalCancel || !modalConfirm) {
      return;
    }

    let pendingDelete = null;
    let lastFocusedElement = null;

    function closeDeleteModal() {
      modal.hidden = true;
      modal.setAttribute("aria-hidden", "true");
      document.body.classList.remove("modal-open");
      pendingDelete = null;
      modalConfirm.disabled = false;
      lastFocusedElement?.focus?.();
    }

    function openDeleteModal(button, loopId, loopName) {
      pendingDelete = {button, loopId, loopName};
      lastFocusedElement = button;
      modalDetail.textContent = pickText({
        zh: `“${loopName}” 和它保存下来的运行记录都会一起消失，这次就真的不回头了。`,
        en: `"${loopName}" and its stored run history will disappear together. This one really does not come back.`,
      });
      modal.hidden = false;
      modal.setAttribute("aria-hidden", "false");
      document.body.classList.add("modal-open");
      modalConfirm.focus();
    }

    function removeLoopCard(button) {
      const card = button.closest(".loop-card");
      if (!card) {
        window.location.reload();
        return;
      }
      card.remove();
      const remainingCards = document.querySelectorAll(".loop-card").length;
      if (loopCount) {
        loopCount.textContent = String(remainingCards);
      }
      if (remainingCards === 0) {
        if (loopGrid) {
          loopGrid.hidden = true;
        }
        if (loopGridNote) {
          loopGridNote.hidden = true;
        }
        if (emptyState) {
          emptyState.hidden = false;
        } else {
          window.location.reload();
        }
      }
    }

    modalCancel.addEventListener("click", closeDeleteModal);
    modalBackdrop?.addEventListener("click", closeDeleteModal);
    modal.addEventListener("click", (event) => {
      if (event.target === modal) {
        closeDeleteModal();
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !modal.hidden) {
        closeDeleteModal();
      }
    });
    modalConfirm.addEventListener("click", async () => {
      if (!pendingDelete) {
        return;
      }
      modalConfirm.disabled = true;
      const {button, loopId} = pendingDelete;
      const response = await fetch(`/api/loops/${encodeURIComponent(loopId)}`, {method: "DELETE"});
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        modalConfirm.disabled = false;
        window.alert(payload.error || pickText({
          zh: "删除失败。",
          en: "Unable to delete the loop.",
        }));
        return;
      }
      closeDeleteModal();
      removeLoopCard(button);
    });

    document.querySelectorAll("[data-delete-loop]").forEach((button) => {
      if (button.dataset.bound === "1") {
        return;
      }
      button.dataset.bound = "1";
      button.addEventListener("click", async () => {
        const loopId = button.dataset.deleteLoop;
        const loopName = button.dataset.loopName || loopId;
        openDeleteModal(button, loopId, loopName);
      });
    });
  }

  function bindOpenCards() {
    document.querySelectorAll("[data-open-card]").forEach((card) => {
      if (card.dataset.boundCard === "1") {
        return;
      }
      card.dataset.boundCard = "1";
      const openUrl = card.dataset.openCard;
      if (!openUrl) {
        return;
      }

      const isInteractive = (target) => target instanceof Element
        && Boolean(target.closest("a, button, input, select, textarea, summary, [role='button']"));

      card.addEventListener("click", (event) => {
        if (isInteractive(event.target)) {
          return;
        }
        window.location.href = openUrl;
      });

      card.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") {
          return;
        }
        if (isInteractive(event.target)) {
          return;
        }
        event.preventDefault();
        window.location.href = openUrl;
      });
    });
  }

  function bindPrimaryNavigation() {
    document.querySelectorAll(".top-nav-link").forEach((link) => {
      if (link.dataset.boundNav === "1") {
        return;
      }
      link.dataset.boundNav = "1";
      link.addEventListener("click", () => {
        link.classList.add("is-routing");
      });
    });
  }

  function bindNavPreferences() {
    const root = document.querySelector("[data-testid='nav-preferences']");
    if (!root || root.dataset.boundPreferences === "1") {
      return;
    }
    root.dataset.boundPreferences = "1";

    const toggle = root.querySelector("[data-toggle-nav-preferences]");
    const panel = root.querySelector("[data-nav-preferences-panel]");
    if (!toggle || !panel) {
      return;
    }

    const close = () => {
      root.classList.remove("is-open");
      panel.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
    };

    const open = () => {
      root.classList.add("is-open");
      panel.hidden = false;
      toggle.setAttribute("aria-expanded", "true");
    };

    toggle.addEventListener("click", (event) => {
      event.preventDefault();
      if (root.classList.contains("is-open")) {
        close();
        return;
      }
      open();
    });

    document.addEventListener("click", (event) => {
      if (!(event.target instanceof Node) || root.contains(event.target)) {
        return;
      }
      close();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        close();
      }
    });

    panel.querySelectorAll("[data-set-theme], [data-set-locale]").forEach((button) => {
      button.addEventListener("click", () => {
        window.setTimeout(close, 0);
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    setLocale(currentLocale(), {persist: false});
    setTheme(currentTheme(), {persist: false});
    document.querySelectorAll("[data-set-locale]").forEach((button) => {
      button.addEventListener("click", () => setLocale(button.dataset.setLocale));
    });
    document.querySelectorAll("[data-set-theme]").forEach((button) => {
      button.addEventListener("click", () => setTheme(button.dataset.setTheme));
    });
    bindDeleteLoopButtons();
    bindOpenCards();
    bindPrimaryNavigation();
    bindNavPreferences();
  });

  window.LooporaUI = {
    currentLocale,
    detectPreferredLocale,
    setLocale,
    currentTheme,
    setTheme,
    pickText,
    translateStatus,
    translateRole,
    applyLocalizedAttributes,
    bindDeleteLoopButtons,
    bindOpenCards,
    bindPrimaryNavigation,
  };
  if (typeof window.matchMedia === "function") {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (event) => {
      if (!readSavedTheme()) {
        setTheme(event.matches ? "dark" : "light", {persist: false});
      }
    });
  }
})();
