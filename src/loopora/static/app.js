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
      generator: "Builder",
      builder: "Builder",
      check_planner: "Check Planner",
      tester: "Inspector",
      inspector: "Inspector",
      verifier: "GateKeeper",
      gatekeeper: "GateKeeper",
      challenger: "Guide",
      guide: "Guide",
      system: "System",
    },
    en: {
      generator: "Builder",
      builder: "Builder",
      check_planner: "Check Planner",
      tester: "Inspector",
      inspector: "Inspector",
      verifier: "GateKeeper",
      gatekeeper: "GateKeeper",
      challenger: "Guide",
      guide: "Guide",
      system: "System",
    },
  };
  const ROLE_DISPLAY_BY_ARCHETYPE = {
    builder: "Builder",
    inspector: "Inspector",
    gatekeeper: "GateKeeper",
    guide: "Guide",
    custom: "Custom Role",
  };
  const ROLE_NAME_ALIASES = {
    builder: ["建造者", "generator", "builder"],
    inspector: ["巡检者", "tester", "inspector"],
    gatekeeper: ["守门人", "verifier", "gatekeeper"],
    guide: ["向导", "challenger", "guide"],
    custom: ["自定义角色", "custom role", "custom"],
  };
  const ROLE_NAME_LOOKUP = Object.fromEntries(
    Object.entries(ROLE_NAME_ALIASES).flatMap(([archetype, aliases]) => {
      const canonical = ROLE_DISPLAY_BY_ARCHETYPE[archetype];
      return aliases.flatMap((alias) => {
        const normalized = String(alias || "").trim();
        return normalized ? [[normalized, canonical], [normalized.toLowerCase(), canonical]] : [];
      });
    })
  );

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
    return ROLE_LABELS[currentLocale()][value] || normalizeRoleName(value);
  }

  function normalizeRoleName(value, archetype = "") {
    if (!value || value === "-") {
      return value || "-";
    }
    const text = String(value).trim();
    if (!text) {
      return "-";
    }
    const canonical = ROLE_DISPLAY_BY_ARCHETYPE[String(archetype || "").trim().toLowerCase()] || "";
    if (canonical) {
      const lowered = text.toLowerCase();
      if (lowered === canonical.toLowerCase()) {
        return canonical;
      }
      if (ROLE_NAME_LOOKUP[text] === canonical || ROLE_NAME_LOOKUP[lowered] === canonical) {
        return canonical;
      }
      return text;
    }
    return ROLE_NAME_LOOKUP[text] || ROLE_NAME_LOOKUP[text.toLowerCase()] || text;
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
        element.setAttribute("aria-label", title);
        element.removeAttribute("title");
      } else {
        element.removeAttribute("data-tooltip");
        element.removeAttribute("aria-label");
        element.removeAttribute("title");
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
    if (!modal || !modalDetail || !modalCancel || !modalConfirm) {
      return;
    }

    const deleteConfigs = [
      {
        selector: "[data-delete-loop]",
        idKey: "deleteLoop",
        nameKey: "loopName",
        endpointPrefix: "/api/loops/",
        redirectUrl: "/",
        countId: "loop-count",
        gridId: "loop-grid",
        emptyStateId: "loops-empty-state",
        noteSelector: ".loop-grid-note",
        detail(name) {
          return pickText({
            zh: `“${name}” 和它保存下来的运行记录都会一起消失，这次就真的不回头了。`,
            en: `"${name}" and its stored run history will disappear together. This one really does not come back.`,
          });
        },
        failure() {
          return pickText({
            zh: "无法删除这个循环。",
            en: "Unable to delete this loop.",
          });
        },
      },
      {
        selector: "[data-delete-bundle]",
        idKey: "deleteBundle",
        nameKey: "bundleName",
        endpointPrefix: "/api/bundles/",
        redirectUrl: "/bundles",
        countId: "bundle-count",
        gridId: "bundle-grid",
        emptyStateId: "bundles-empty-state",
        noteSelector: ".bundle-grid-note",
        detail(name) {
          return pickText({
            zh: `“${name}” 和它导入的 loop、流程编排、角色定义都会一起清理。手动资源不会被影响。`,
            en: `"${name}" and its imported loop, orchestration, and role definitions will be removed together. Unrelated manual assets stay intact.`,
          });
        },
        failure() {
          return pickText({
            zh: "无法删除这个 Bundle。",
            en: "Unable to delete this bundle.",
          });
        },
      },
    ];

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

    function openDeleteModal(config, button, resourceId, resourceName) {
      pendingDelete = {config, button, resourceId, resourceName};
      lastFocusedElement = button;
      modalDetail.textContent = config.detail(resourceName);
      modal.hidden = false;
      modal.setAttribute("aria-hidden", "false");
      document.body.classList.add("modal-open");
      modalConfirm.focus();
    }

    function removeResourceCard(button, config) {
      const card = button.closest(".loop-card");
      if (!card) {
        window.location.href = config.redirectUrl || window.location.href;
        return;
      }
      const grid = document.getElementById(config.gridId);
      card.remove();
      const remainingCards = grid ? grid.querySelectorAll(".loop-card").length : 0;
      const countElement = document.getElementById(config.countId);
      const emptyState = document.getElementById(config.emptyStateId);
      const gridNote = document.querySelector(config.noteSelector);
      if (countElement) {
        countElement.textContent = String(remainingCards);
      }
      if (remainingCards === 0) {
        if (grid) {
          grid.hidden = true;
        }
        if (gridNote) {
          gridNote.hidden = true;
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
      const {button, config, resourceId} = pendingDelete;
      const response = await fetch(`${config.endpointPrefix}${encodeURIComponent(resourceId)}`, {method: "DELETE"});
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        modalConfirm.disabled = false;
        window.alert(payload.error || config.failure());
        return;
      }
      closeDeleteModal();
      removeResourceCard(button, config);
    });

    deleteConfigs.forEach((config) => {
      document.querySelectorAll(config.selector).forEach((button) => {
        if (button.dataset.bound === "1") {
          return;
        }
        button.dataset.bound = "1";
        button.addEventListener("click", async () => {
          const resourceId = button.dataset[config.idKey];
          const resourceName = button.dataset[config.nameKey] || resourceId;
          openDeleteModal(config, button, resourceId, resourceName);
        });
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

  async function revealPath(path) {
    if (!path) {
      return;
    }
    try {
      const response = await fetch("/api/system/reveal-path", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({path}),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || "failed");
      }
    } catch (error) {
      try {
        await navigator.clipboard.writeText(path);
        window.alert(pickText({
          zh: "无法自动打开，路径已复制到剪贴板。",
          en: "Could not open automatically. The path was copied to your clipboard.",
        }));
        return;
      } catch (_) {
        window.alert(pickText({
          zh: "无法自动打开该路径。",
          en: "Unable to open that path automatically.",
        }));
      }
    }
  }

  function bindPathPickers() {
    document.querySelectorAll("[data-pick-file][data-target-input]").forEach((button) => {
      if (button.dataset.boundPickFile === "1") {
        return;
      }
      button.dataset.boundPickFile = "1";
      button.addEventListener("click", async () => {
        const endpoint = button.dataset.pickEndpoint || "/api/system/pick-bundle-file";
        const targetId = button.dataset.targetInput || "";
        const target = targetId ? document.getElementById(targetId) : null;
        if (!(target instanceof HTMLInputElement)) {
          return;
        }
        button.disabled = true;
        try {
          const startPath = target.value ? `?start_path=${encodeURIComponent(target.value)}` : "";
          const response = await fetch(`${endpoint}${startPath}`);
          const payload = await response.json().catch(() => ({}));
          if (!response.ok) {
            throw new Error(payload.error || "failed");
          }
          if (payload.path) {
            target.value = payload.path;
            target.focus();
            target.dispatchEvent(new Event("change", {bubbles: true}));
          }
        } catch (error) {
          window.alert(error.message || pickText({
            zh: "无法选择文件。",
            en: "Unable to choose a file.",
          }));
        } finally {
          button.disabled = false;
        }
      });
    });
  }

  function bindRevealPathButtons() {
    document.querySelectorAll("[data-reveal-path]").forEach((button) => {
      if (button.dataset.boundRevealPath === "1") {
        return;
      }
      button.dataset.boundRevealPath = "1";
      button.addEventListener("click", () => revealPath(button.dataset.revealPath || ""));
    });
  }

  function bindHelpTooltips() {
    let tooltip = document.querySelector(".help-floating-tooltip");
    if (!tooltip) {
      tooltip = document.createElement("div");
      tooltip.className = "help-floating-tooltip";
      tooltip.hidden = true;
      tooltip.setAttribute("role", "tooltip");
      document.body.appendChild(tooltip);
    }

    const hide = () => {
      tooltip.hidden = true;
      tooltip.textContent = "";
    };
    const show = (target) => {
      const text = target.getAttribute("data-tooltip") || "";
      if (!text) {
        hide();
        return;
      }
      tooltip.textContent = text;
      tooltip.hidden = false;
      positionHelpTooltip(tooltip, target);
    };

    document.querySelectorAll(".help-dot[data-tooltip]").forEach((button) => {
      if (button.dataset.boundHelpTooltip === "1") {
        return;
      }
      button.dataset.boundHelpTooltip = "1";
      button.addEventListener("mouseenter", () => show(button));
      button.addEventListener("focus", () => show(button));
      button.addEventListener("mousemove", () => positionHelpTooltip(tooltip, button));
      button.addEventListener("mouseleave", hide);
      button.addEventListener("blur", hide);
      button.addEventListener("click", () => {
        if (tooltip.hidden) {
          show(button);
        } else {
          hide();
        }
      });
    });
  }

  function positionHelpTooltip(tooltip, target) {
    if (tooltip.hidden) {
      return;
    }
    const rect = target.getBoundingClientRect();
    const tipRect = tooltip.getBoundingClientRect();
    const gap = 12;
    const viewportPadding = 14;
    const centered = rect.left + rect.width / 2 - tipRect.width / 2;
    const left = Math.max(viewportPadding, Math.min(centered, window.innerWidth - tipRect.width - viewportPadding));
    const above = rect.top - tipRect.height - gap;
    const top = above >= viewportPadding ? above : rect.bottom + gap;
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${Math.max(viewportPadding, top)}px`;
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
    bindPathPickers();
    bindRevealPathButtons();
    bindHelpTooltips();
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
    normalizeRoleName,
    applyLocalizedAttributes,
    bindDeleteLoopButtons,
    bindOpenCards,
    bindPrimaryNavigation,
    bindPathPickers,
    bindHelpTooltips,
  };
  if (typeof window.matchMedia === "function") {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (event) => {
      if (!readSavedTheme()) {
        setTheme(event.matches ? "dark" : "light", {persist: false});
      }
    });
  }
})();
