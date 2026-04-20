(() => {
  function pickText(values) {
    return window.LooporaUI?.pickText?.(values) || values.en || values.zh || "";
  }

  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  async function fetchRenderedHtml(markdown, options = {}) {
    const response = await fetch(options.endpoint || "/api/markdown/render", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        markdown: String(markdown || ""),
        strip_front_matter: Boolean(options.stripFrontMatter),
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) {
      throw new Error(String(payload.error || pickText({
        zh: "Markdown 预览暂时不可用。",
        en: "Markdown preview is temporarily unavailable.",
      })));
    }
    return payload.rendered_html || "";
  }

  function createMarkdownWorkbench(options = {}) {
    const textarea = options.textarea instanceof HTMLElement ? options.textarea : null;
    const preview = options.preview instanceof HTMLElement ? options.preview : null;
    if (!preview) {
      throw new Error("preview element is required");
    }
    const debounceMs = Number(options.debounceMs) > 0 ? Number(options.debounceMs) : 180;
    const autoRenderOnInput = options.autoRenderOnInput !== false;
    let renderToken = 0;
    let timerId = 0;

    function setPreviewHtml(markup) {
      preview.innerHTML = markup;
    }

    function currentMarkdown() {
      if (textarea) {
        return textarea.value;
      }
      if (typeof options.getMarkdown === "function") {
        return options.getMarkdown();
      }
      return "";
    }

    function setStatus(kind, message) {
      if (typeof options.onStatus === "function") {
        options.onStatus(kind, message);
      }
    }

    async function renderNow() {
      const markdown = String(currentMarkdown() || "");
      const requestId = ++renderToken;
      if (!markdown.trim()) {
        setStatus("", "");
        setPreviewHtml(
          `<p>${escapeHtml(
            pickText(options.emptyMessage || {
              zh: "这里还没有可显示的 Markdown 内容。",
              en: "There is no Markdown content to preview yet.",
            }),
          )}</p>`,
        );
        return;
      }
      setStatus("loading", pickText(options.loadingMessage || {
        zh: "正在渲染 Markdown…",
        en: "Rendering Markdown...",
      }));
      try {
        const renderedHtml = await fetchRenderedHtml(markdown, options);
        if (requestId !== renderToken) {
          return;
        }
        setPreviewHtml(
          renderedHtml
          || `<p>${escapeHtml(
            pickText(options.emptyMessage || {
              zh: "这里还没有可显示的 Markdown 内容。",
              en: "There is no Markdown content to preview yet.",
            }),
          )}</p>`,
        );
        setStatus("ready", "");
      } catch (error) {
        if (requestId !== renderToken) {
          return;
        }
        setStatus("error", error instanceof Error ? error.message : String(error || ""));
        setPreviewHtml(
          `<div class="binary-preview"><strong>${escapeHtml(
            pickText(options.errorTitle || {
              zh: "暂时无法渲染 Markdown 预览。",
              en: "Markdown preview could not be rendered right now.",
            }),
          )}</strong><p>${escapeHtml(
            error instanceof Error ? error.message : String(error || ""),
          )}</p></div>`,
        );
      }
    }

    function scheduleRender() {
      window.clearTimeout(timerId);
      timerId = window.setTimeout(() => {
        renderNow().catch(() => {});
      }, debounceMs);
    }

    function setValue(value, options = {}) {
      if (!textarea) {
        return;
      }
      textarea.value = String(value || "");
      if (options.render !== false) {
        renderNow().catch(() => {});
      }
    }

    if (textarea && autoRenderOnInput) {
      textarea.addEventListener("input", scheduleRender);
    }

    return {
      getValue: currentMarkdown,
      renderNow,
      scheduleRender,
      setPreviewHtml,
      setValue,
    };
  }

  window.LooporaMarkdownWorkbench = {
    create: createMarkdownWorkbench,
    escapeHtml,
  };
})();
