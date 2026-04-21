document.addEventListener("DOMContentLoaded", () => {
  if (!window.LooporaUI) {
    return;
  }

  const modal = document.getElementById("tutorial-spec-practice-modal");
  const title = document.getElementById("tutorial-spec-practice-title");
  const summary = document.getElementById("tutorial-spec-practice-summary");
  const preview = document.getElementById("tutorial-spec-practice-preview");
  const payload = JSON.parse(document.getElementById("tutorial-spec-practices-json")?.textContent || "{}");

  if (!modal || !title || !summary || !preview || !Object.keys(payload).length) {
    return;
  }

  let activeExampleId = "";
  let lastTrigger = null;

  function currentLocale() {
    return window.LooporaUI.currentLocale();
  }

  function localeText(zh, en) {
    return window.LooporaUI.pickText({zh, en});
  }

  function exampleById(exampleId) {
    return payload[String(exampleId || "").trim()] || null;
  }

  function renderExample(exampleId) {
    const example = exampleById(exampleId);
    if (!example) {
      return false;
    }
    const locale = currentLocale();
    title.textContent = `${example.name || ""} ${localeText("样例", "Example")}`.trim();
    summary.textContent = String(locale === "zh" ? example.summary_zh || "" : example.summary_en || "");
    preview.innerHTML = String(locale === "zh" ? example.rendered_html_zh || "" : example.rendered_html_en || "");
    activeExampleId = exampleId;
    return true;
  }

  function openModal(exampleId, trigger) {
    if (!renderExample(exampleId)) {
      return;
    }
    lastTrigger = trigger || document.activeElement;
    modal.hidden = false;
    modal.setAttribute("aria-hidden", "false");
  }

  function closeModal() {
    if (modal.hidden) {
      return;
    }
    modal.hidden = true;
    modal.setAttribute("aria-hidden", "true");
    activeExampleId = "";
    if (lastTrigger && typeof lastTrigger.focus === "function") {
      lastTrigger.focus();
    }
  }

  document.querySelectorAll("[data-open-tutorial-spec-practice]").forEach((button) => {
    button.addEventListener("click", () => {
      openModal(button.dataset.openTutorialSpecPractice, button);
    });
  });

  modal.querySelectorAll("[data-close-tutorial-spec-practice]").forEach((element) => {
    element.addEventListener("click", closeModal);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) {
      event.preventDefault();
      closeModal();
    }
  });

  document.addEventListener("loopora:localechange", () => {
    if (activeExampleId) {
      renderExample(activeExampleId);
    }
  });
});
