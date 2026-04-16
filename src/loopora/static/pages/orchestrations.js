document.addEventListener("DOMContentLoaded", () => {
  if (!window.LooporaWorkflowDiagram) {
    return;
  }

  function renderAllWorkflowDiagrams() {
    document.querySelectorAll("[data-workflow-diagram]").forEach((element) => {
      try {
        const workflow = JSON.parse(element.dataset.workflowDiagram || "{}");
        window.LooporaWorkflowDiagram.renderInto(element, workflow, {variant: "card"});
      } catch (_) {
        element.innerHTML = "";
      }
    });
  }

  document.addEventListener("loopora:localechange", renderAllWorkflowDiagrams);
  renderAllWorkflowDiagrams();
});
