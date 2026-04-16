(() => {
  let markerSequence = 0;

  const ROLE_COLORS = {
    builder: "#d66a36",
    inspector: "#0d7c66",
    gatekeeper: "#ab2f2a",
    guide: "#5b6fda",
    custom: "#7d6b58",
  };

  function localeText(zh, en) {
    if (window.LooporaUI?.pickText) {
      return window.LooporaUI.pickText({zh, en});
    }
    return en;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function normalizeWorkflow(workflow) {
    const payload = typeof workflow === "object" && workflow ? workflow : {};
    const roles = Array.isArray(payload.roles) ? payload.roles : [];
    const steps = Array.isArray(payload.steps) ? payload.steps : [];
    return {roles, steps};
  }

  function roleById(workflow) {
    return Object.fromEntries((workflow.roles || []).map((role) => [String(role.id || ""), role]));
  }

  function roleColor(archetype) {
    return ROLE_COLORS[String(archetype || "").trim()] || ROLE_COLORS.custom;
  }

  function shortLabel(value, maxLength = 14) {
    const text = String(value || "");
    return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
  }

  function diagramSettings(variant = "card") {
    if (variant === "editor") {
      return {
        width: 640,
        height: 280,
        radiusX: 210,
        radiusY: 92,
        nodeRadius: 20,
        curveDepth: 34,
      };
    }
    return {
      width: 480,
      height: 220,
      radiusX: 152,
      radiusY: 70,
      nodeRadius: 17,
      curveDepth: 26,
    };
  }

  function buildNodes(workflow, variant = "card") {
    const normalized = normalizeWorkflow(workflow);
    const roles = roleById(normalized);
    const settings = diagramSettings(variant);
    const enabledSteps = normalized.steps.filter((step) => step.enabled !== false);
    const sourceSteps = enabledSteps.length ? enabledSteps : normalized.steps;
    const cx = settings.width / 2;
    const cy = settings.height / 2;

    return {
      settings,
      cx,
      cy,
      steps: sourceSteps.map((step, index) => {
        const role = roles[String(step.role_id || "")] || {};
        const total = Math.max(sourceSteps.length, 1);
        const angle = total === 1 ? -Math.PI / 2 : (-Math.PI / 2) + ((Math.PI * 2 * index) / total);
        return {
          order: index + 1,
          stepId: String(step.id || `step_${index + 1}`),
          label: String(role.name || step.role_id || `Step ${index + 1}`),
          shortLabel: shortLabel(String(role.name || step.role_id || `Step ${index + 1}`), variant === "editor" ? 18 : 12),
          archetype: String(role.archetype || "custom"),
          finishGate: String(step.on_pass || "") === "finish_run" && String(role.archetype || "") === "gatekeeper",
          x: cx + settings.radiusX * Math.cos(angle),
          y: cy + settings.radiusY * Math.sin(angle),
        };
      }),
    };
  }

  function vectorLength(x, y) {
    return Math.sqrt(x * x + y * y) || 1;
  }

  function buildSegments(nodes, cx, cy, settings) {
    if (nodes.length <= 1) {
      return [];
    }
    return nodes.map((node, index) => {
      const next = nodes[(index + 1) % nodes.length];
      const midpointX = (node.x + next.x) / 2;
      const midpointY = (node.y + next.y) / 2;
      let normalX = midpointX - cx;
      let normalY = midpointY - cy;
      if (Math.abs(normalX) + Math.abs(normalY) < 1) {
        normalX = -(next.y - node.y);
        normalY = next.x - node.x;
      }
      const normalLength = vectorLength(normalX, normalY);
      const controlX = midpointX + (normalX / normalLength) * settings.curveDepth;
      const controlY = midpointY + (normalY / normalLength) * settings.curveDepth;
      const startVectorX = controlX - node.x;
      const startVectorY = controlY - node.y;
      const endVectorX = controlX - next.x;
      const endVectorY = controlY - next.y;
      const startLength = vectorLength(startVectorX, startVectorY);
      const endLength = vectorLength(endVectorX, endVectorY);
      const startX = node.x + (startVectorX / startLength) * settings.nodeRadius;
      const startY = node.y + (startVectorY / startLength) * settings.nodeRadius;
      const endX = next.x + (endVectorX / endLength) * settings.nodeRadius;
      const endY = next.y + (endVectorY / endLength) * settings.nodeRadius;
      return {
        color: roleColor(node.archetype),
        path: `M ${startX.toFixed(1)} ${startY.toFixed(1)} Q ${controlX.toFixed(1)} ${controlY.toFixed(1)} ${endX.toFixed(1)} ${endY.toFixed(1)}`,
      };
    });
  }

  function buildSingleLoop(node, settings) {
    const rx = settings.nodeRadius + 14;
    const ry = settings.nodeRadius + 10;
    const startX = node.x;
    const startY = node.y - settings.nodeRadius;
    return `M ${startX.toFixed(1)} ${startY.toFixed(1)} C ${(node.x + rx).toFixed(1)} ${(node.y - ry).toFixed(1)} ${(node.x + rx).toFixed(1)} ${(node.y + ry).toFixed(1)} ${startX.toFixed(1)} ${(node.y + settings.nodeRadius).toFixed(1)} C ${(node.x - rx).toFixed(1)} ${(node.y + ry).toFixed(1)} ${(node.x - rx).toFixed(1)} ${(node.y - ry).toFixed(1)} ${startX.toFixed(1)} ${startY.toFixed(1)}`;
  }

  function labelAnchor(node, cx) {
    const delta = node.x - cx;
    if (Math.abs(delta) < 26) {
      return {anchor: "middle", dx: 0};
    }
    return delta < 0 ? {anchor: "end", dx: -24} : {anchor: "start", dx: 24};
  }

  function render(workflow, options = {}) {
    const variant = options.variant || "card";
    const {steps, settings, cx, cy} = buildNodes(workflow, variant);
    if (!steps.length) {
      return `
        <div class="workflow-loop-empty">
          <strong>${escapeHtml(localeText("还没有步骤", "No steps yet"))}</strong>
          <p>${escapeHtml(localeText("加上角色和步骤之后，这里会出现循环实例图。", "Add roles and steps to generate the loop instance map here."))}</p>
        </div>
      `;
    }

    const markerId = `workflow-loop-arrow-${markerSequence += 1}`;
    const singleLoopPath = steps.length === 1 ? buildSingleLoop(steps[0], settings) : "";
    const segments = steps.length === 1 ? [] : buildSegments(steps, cx, cy, settings);
    const legend = steps.map((step) => `
      <li class="workflow-loop-pill${step.finishGate ? " is-finish" : ""}">
        <span class="workflow-loop-pill-order" style="--workflow-loop-accent:${roleColor(step.archetype)}">${step.order}</span>
        <span>${escapeHtml(step.label)}</span>
      </li>
    `).join("");
    const nodes = steps.map((step) => {
      const anchor = labelAnchor(step, cx);
      return `
        <g class="workflow-loop-node${step.finishGate ? " is-finish" : ""}">
          <circle cx="${step.x.toFixed(1)}" cy="${step.y.toFixed(1)}" r="${settings.nodeRadius}" fill="${roleColor(step.archetype)}"></circle>
          <text x="${step.x.toFixed(1)}" y="${(step.y + 1).toFixed(1)}" class="workflow-loop-node-order">${step.order}</text>
          <text x="${(step.x + anchor.dx).toFixed(1)}" y="${(step.y + settings.nodeRadius + 22).toFixed(1)}" class="workflow-loop-node-label" text-anchor="${anchor.anchor}">${escapeHtml(step.shortLabel)}</text>
        </g>
      `;
    }).join("");
    const segmentMarkup = segments.map((segment) => `
      <path d="${segment.path}" class="workflow-loop-segment" style="--workflow-loop-accent:${segment.color}" marker-end="url(#${markerId})"></path>
    `).join("");

    return `
      <div class="workflow-loop-map workflow-loop-map--${variant}">
        <svg class="workflow-loop-svg" viewBox="0 0 ${settings.width} ${settings.height}" role="img" aria-label="${escapeHtml(localeText("循环流程图", "Loop workflow diagram"))}">
          <defs>
            <marker id="${markerId}" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto" markerUnits="strokeWidth">
              <path d="M 0 0 L 12 6 L 0 12 z" fill="rgba(53, 43, 34, 0.74)"></path>
            </marker>
          </defs>
          ${singleLoopPath ? `<path d="${singleLoopPath}" class="workflow-loop-segment is-single" style="--workflow-loop-accent:${roleColor(steps[0].archetype)}" marker-end="url(#${markerId})"></path>` : ""}
          ${segmentMarkup}
          <g class="workflow-loop-center-badge">
            <rect x="${(cx - 60).toFixed(1)}" y="${(cy - 16).toFixed(1)}" width="120" height="32" rx="16"></rect>
            <text x="${cx.toFixed(1)}" y="${(cy + 5).toFixed(1)}">${escapeHtml(localeText("持续循环", "Loop repeats"))}</text>
          </g>
          ${nodes}
        </svg>
        <ol class="workflow-loop-legend">${legend}</ol>
      </div>
    `;
  }

  function renderInto(container, workflow, options = {}) {
    if (!container) {
      return;
    }
    container.innerHTML = render(workflow, options);
  }

  window.LooporaWorkflowDiagram = {
    render,
    renderInto,
  };
})();
