(function () {
  function createProgressProjector(deps = {}) {
    const localeText = deps.localeText || ((zh, en) => en || zh || "");
    const parseTimestamp = deps.parseTimestamp || ((value) => {
      const timestamp = Date.parse(value || "");
      return Number.isFinite(timestamp) ? timestamp : null;
    });
    const formatDuration = deps.formatDuration || (() => "-");
    const formatRelativeAge = deps.formatRelativeAge || (() => "");
    const formatAbsoluteDate = deps.formatAbsoluteDate || (() => "");
    const translateStatus = deps.translateStatus || ((status) => String(status || ""));
    const translateRole = deps.translateRole || ((role) => String(role || ""));
    const normalizeRoleName = deps.normalizeRoleName || ((name) => String(name || ""));
    const displayIter = deps.displayIter || ((value) => {
      const parsed = Number(value);
      return Number.isFinite(parsed) && parsed >= 0 ? Math.floor(parsed) + 1 : 1;
    });
    const stripMarkdown = deps.stripMarkdown || ((value) => String(value || ""));
    const truncateText = deps.truncateText || ((value, maxLength = 140) => {
      const text = String(value || "").trim();
      return text.length > maxLength ? `${text.slice(0, maxLength - 1).trimEnd()}…` : text;
    });
    const getProgressEvents = deps.getProgressEvents || (() => []);
    const getConsoleEvents = deps.getConsoleEvents || (() => []);
    const getCurrentRun = deps.getCurrentRun || (() => null);
    const timeHelpers = window.LooporaRunDetailProgressTime.createProgressTimeHelpers({localeText});
    const {formatDurationMs, formatStageDuration} = timeHelpers;
    const activityProjector = window.LooporaRunDetailProgressActivity.createProgressActivityProjector({
      localeText,
      truncateText,
      stripMarkdown,
      activityHintKey,
    });

    const ARCHETYPE_LABELS = {
      builder: {zh: "Builder", en: "Builder"},
      inspector: {zh: "Inspector", en: "Inspector"},
      gatekeeper: {zh: "GateKeeper", en: "GateKeeper"},
      guide: {zh: "Guide", en: "Guide"},
      custom: {zh: "Custom Role", en: "Custom Role"},
    };
    const LEGACY_RUNTIME_ROLE_BY_ARCHETYPE = {
      builder: "generator",
      inspector: "tester",
      gatekeeper: "verifier",
      guide: "challenger",
    };

    function stageKeyForStep(stepId) {
      return `step:${stepId}`;
    }

    function stepIdFromStageKey(stage) {
      return typeof stage === "string" && stage.startsWith("step:") ? stage.slice(5) : "";
    }

    function getWorkflow(run) {
      if (run?.workflow_json && typeof run.workflow_json === "object") {
        return run.workflow_json;
      }
      return {roles: [], steps: []};
    }

    function getWorkflowRoleMap(run) {
      return new Map(
        (getWorkflow(run).roles || [])
          .filter((role) => role && typeof role === "object")
          .map((role) => [String(role.id || "").trim(), role])
          .filter(([roleId]) => roleId)
      );
    }

    function runtimeRoleForWorkflowRole(role) {
      const roleId = String(role?.id || "").trim();
      const archetype = String(role?.archetype || "").trim();
      if (roleId && archetype && roleId === archetype) {
        return LEGACY_RUNTIME_ROLE_BY_ARCHETYPE[archetype] || roleId;
      }
      return roleId || archetype;
    }

    function displayRoleSnapshotName(role) {
      const rawName = String(role?.name || "").trim();
      const archetype = String(role?.archetype || "").trim();
      const labels = ARCHETYPE_LABELS[archetype];
      if (!rawName) {
        return labels ? localeText(labels.zh, labels.en) : localeText("未命名步骤", "Unnamed step");
      }
      const normalized = normalizeRoleName(rawName, archetype);
      if (labels && normalized) {
        const lowered = normalized.toLowerCase();
        if (lowered === labels.zh.toLowerCase() || lowered === labels.en.toLowerCase()) {
          return localeText(labels.zh, labels.en);
        }
      }
      return normalized || rawName;
    }

    function resolvedPayloadRoleName(payload = {}, fallbackRole = "") {
      const roleName = String(payload.role_name || "").trim();
      const archetype = String(payload.archetype || fallbackRole || payload.role || "").trim();
      if (roleName) {
        return normalizeRoleName(roleName, archetype);
      }
      const resolvedRole = String(fallbackRole || payload.role || "").trim();
      return resolvedRole ? translateRole(resolvedRole) : "-";
    }

    function workflowStepDetail(role, step) {
      const archetype = String(role?.archetype || "").trim();
      const details = {
        builder: localeText(
          "真正修改工作区，朝 Task 和检查项推进实现。",
          "Actually changes the workspace to move the implementation toward the Task and checks."
        ),
        inspector: localeText(
          "运行命令、页面交互或源码检查来收集证据，回答“发生了什么”。",
          "Runs commands, page interactions, or source inspection to collect evidence and answer 'what happened?'"
        ),
        gatekeeper: localeText(
          "根据 Task、检查项、Guardrails 和测试证据做裁决，回答“算不算通过”。",
          "Judges the evidence against the Task, checks, and Guardrails to answer 'does this count as passing?'"
        ),
        guide: localeText(
          "只有在停滞或回退时才触发，用来提出新的方向，不是每轮必跑。",
          "Only triggers on plateau or regression to suggest a new direction; it does not run on every iteration."
        ),
        custom: localeText(
          "执行当前编排里定义的自定义步骤，并把结果交接给后续阶段。",
          "Executes the custom workflow step defined in this orchestration and hands its result to the next stage."
        ),
      };
      const base = details[archetype] || details.custom;
      if (archetype === "gatekeeper" && String(step?.on_pass || "").trim() === "finish_run") {
        return `${base} ${localeText("通过时可以直接结束本次运行。", "A passing result can finish the run immediately.")}`;
      }
      return base;
    }

    function stageOrderLabel(stage) {
      const sequence = Number(stage?.sequence || 0);
      return sequence > 0 ? String(sequence).padStart(2, "0") : "--";
    }

    function getProgressStages(run = getCurrentRun()) {
      const workflow = getWorkflow(run);
      const roleById = getWorkflowRoleMap(run);
      const stages = [
        {
          key: "checks",
          kind: "checks",
          title: localeText("检查项", "Checks"),
          detail: localeText(
            "决定这次运行到底用哪些检查项。显式检查项会直接采用；否则会自动生成一组并在本次运行内冻结。",
            "Decides which checks this run uses. Explicit Checks are adopted directly; otherwise a frozen set is auto-generated."
          ),
        },
      ];
      (workflow.steps || []).forEach((step, index) => {
        const stepId = String(step?.id || "").trim();
        if (!stepId) {
          return;
        }
        const role = roleById.get(String(step?.role_id || "").trim()) || {};
        stages.push({
          key: stageKeyForStep(stepId),
          kind: "workflow_step",
          stepId,
          stepOrder: index,
          step,
          role,
          roleId: String(step?.role_id || "").trim(),
          runtimeRole: runtimeRoleForWorkflowRole(role),
          archetype: String(role?.archetype || "").trim(),
          title: displayRoleSnapshotName(role),
          detail: workflowStepDetail(role, step),
        });
      });
      stages.push({
        key: "finished",
        kind: "finished",
        title: localeText("完成", "Done"),
        detail: localeText(
          "这次 run 已经结束，可能是成功、失败或手动停止。",
          "The run has ended, whether by success, failure, or manual stop."
        ),
      });
      return stages.map((stage, index) => ({
        ...stage,
        sequence: index + 1,
        chipLabel: stage.title,
      }));
    }

    function getStageDefinition(stage, run = getCurrentRun()) {
      const stages = getProgressStages(run);
      return stages.find((item) => item.key === stage) || stages[0] || {
        key: "checks",
        kind: "checks",
        title: localeText("检查项", "Checks"),
        chipLabel: localeText("检查项", "Checks"),
        sequence: 1,
        detail: "",
      };
    }

    function workflowLoopSummary(run = getCurrentRun()) {
      const workflowStages = getProgressStages(run).filter((stage) => stage.kind === "workflow_step");
      if (!workflowStages.length) {
        return {
          eyebrow: localeText("Loop steps", "Loop steps"),
          title: localeText("还没有中间步骤", "No middle steps yet"),
          detail: localeText(
            "这次运行没有冻结中间步骤，所以这里只显示入口和最终状态。",
            "This run has no frozen middle steps, so only the entry and final state remain."
          ),
        };
      }
      const hasFinishGate = workflowStages.some((stage) => (
        stage.archetype === "gatekeeper" && String(stage.step?.on_pass || "").trim() === "finish_run"
      ));
      return {
        eyebrow: localeText("Loop steps", "Loop steps"),
        title: workflowStages.map((stage) => stage.title).join(" → "),
        detail: hasFinishGate
          ? localeText(
            "中间步骤按 Loop 计划循环推进，直到 GateKeeper 放行或运行预算耗尽。",
            "These middle steps repeat according to the Loop plan until GateKeeper passes or the run budget ends."
          )
          : localeText(
            "中间步骤按 Loop 计划循环推进，直到当前完成模式结束本次运行。",
            "These middle steps repeat according to the Loop plan until the configured completion mode ends the run."
          ),
      };
    }

    function findLatestEvent(records, predicate) {
      for (let index = records.length - 1; index >= 0; index -= 1) {
        const event = records[index];
        if (predicate(event)) {
          return event;
        }
      }
      return null;
    }

    function latestProgressEventOfType(type) {
      return findLatestEvent(getProgressEvents(), (event) => event.event_type === type);
    }

    function findAttemptByIter(attempts, iter) {
      for (let index = attempts.length - 1; index >= 0; index -= 1) {
        const attempt = attempts[index];
        if (attempt.iter === iter) {
          return attempt;
        }
      }
      return null;
    }

    function attemptDurationMs(attempt) {
      const explicit = Number(attempt?.durationMs);
      if (Number.isFinite(explicit) && explicit > 0) {
        return explicit;
      }
      const startedAt = parseTimestamp(attempt?.startedAt);
      const endedAt = parseTimestamp(attempt?.handoffAt || attempt?.summaryAt);
      if (startedAt === null || endedAt === null) {
        return 0;
      }
      return Math.max(0, endedAt - startedAt);
    }

    function workflowStepAttempts(run = getCurrentRun()) {
      const attemptsByStep = new Map(
        getProgressStages(run)
          .filter((stage) => stage.kind === "workflow_step")
          .map((stage) => [stage.stepId, []])
      );
      getProgressEvents().forEach((event) => {
        const payload = event.payload || {};
        const stepId = String(payload.step_id || "").trim();
        if (!stepId || !attemptsByStep.has(stepId)) {
          return;
        }
        const iter = payload.iter === undefined || payload.iter === null ? null : Number(payload.iter);
        const attempts = attemptsByStep.get(stepId);
        let attempt = findAttemptByIter(attempts, iter);
        if (!attempt) {
          attempt = {
            iter,
            stepId,
            stepOrder: payload.step_order,
            role: event.role || payload.role || "",
            roleName: payload.role_name || "",
            archetype: payload.archetype || "",
            startedAt: null,
            summaryAt: null,
            handoffAt: null,
            ok: null,
            attempts: 0,
            error: "",
            durationMs: null,
            handoffStatus: "",
          };
          attempts.push(attempt);
        }
        attempt.stepOrder = attempt.stepOrder ?? payload.step_order;
        attempt.role = attempt.role || event.role || payload.role || "";
        attempt.roleName = attempt.roleName || payload.role_name || "";
        attempt.archetype = attempt.archetype || payload.archetype || "";
        if (["role_started", "role_request_prepared", "step_context_prepared"].includes(event.event_type)) {
          attempt.startedAt = attempt.startedAt || event.created_at;
        }
        if (event.event_type === "role_execution_summary") {
          attempt.summaryAt = event.created_at;
          attempt.ok = Boolean(payload.ok);
          attempt.attempts = Number(payload.attempts || 0);
          attempt.error = String(payload.error || "").trim();
          attempt.durationMs = Number(payload.duration_ms || 0);
        }
        if (event.event_type === "step_handoff_written") {
          attempt.handoffAt = event.created_at;
          attempt.handoffStatus = String(payload.status || "").trim();
        }
      });
      return attemptsByStep;
    }

    function currentIterValue(run = getCurrentRun()) {
      const parsed = Number(run?.current_iter);
      return Number.isFinite(parsed) && parsed >= 0 ? Math.floor(parsed) : 0;
    }

    function currentWorkflowStepEvent(run = getCurrentRun()) {
      const activeRole = String(run?.active_role || "").trim();
      const iter = currentIterValue(run);
      const progressEvents = getProgressEvents();
      if (activeRole) {
        const activeEvent = findLatestEvent(progressEvents, (event) => {
          const payload = event.payload || {};
          const stepId = String(payload.step_id || "").trim();
          if (!stepId) {
            return false;
          }
          const eventRole = String(event.role || payload.role || "").trim();
          if (eventRole && eventRole !== activeRole) {
            return false;
          }
          if (payload.iter !== undefined && payload.iter !== null && Number(payload.iter) !== iter) {
            return false;
          }
          return true;
        });
        if (activeEvent) {
          return activeEvent;
        }
      }
      return findLatestEvent(progressEvents, (event) => Boolean(event.payload?.step_id));
    }

    function runIsActive(run) {
      return ["queued", "running"].includes(run?.status || "");
    }

    function getCurrentStage(run = getCurrentRun()) {
      if (!run) {
        return "checks";
      }
      const checksResolved = latestProgressEventOfType("checks_resolved");
      if (run.status === "queued" || (!checksResolved && runIsActive(run))) {
        return "checks";
      }
      if (run.status === "succeeded") {
        return "finished";
      }
      const currentStepEvent = currentWorkflowStepEvent(run);
      const stepId = String(currentStepEvent?.payload?.step_id || "").trim();
      if (stepId) {
        return stageKeyForStep(stepId);
      }
      if (run.status === "failed" || run.status === "stopped") {
        return checksResolved ? "finished" : "checks";
      }
      return "checks";
    }

    function getStageSnapshots(run = getCurrentRun()) {
      const stages = getProgressStages(run);
      const runFinished = ["succeeded", "failed", "stopped"].includes(run?.status || "");
      const currentStage = getCurrentStage(run);
      const snapshots = {};
      const runStartTs = parseTimestamp(run?.started_at || run?.queued_at || run?.created_at);
      const checksResolved = latestProgressEventOfType("checks_resolved");
      const checksResolvedTs = parseTimestamp(checksResolved?.created_at);
      const checksLiveMs = runStartTs === null ? null : Math.max(0, Date.now() - runStartTs);

      if (checksResolvedTs !== null && runStartTs !== null) {
        snapshots.checks = {
          state: "complete",
          stateLabel: localeText("已冻结", "Ready"),
          durationLabel: formatStageDuration(checksResolvedTs - runStartTs) || localeText("已就绪", "Ready"),
          meta: checksResolved?.payload?.source === "auto_generated"
            ? localeText("自动生成", "Auto")
            : localeText("显式提供", "Specified"),
        };
      } else if (currentStage === "checks" && runIsActive(run)) {
        snapshots.checks = {
          state: "current",
          stateLabel: run?.status === "queued" ? localeText("排队中", "Queued") : localeText("处理中", "Active"),
          durationLabel: formatStageDuration(checksLiveMs) || localeText("刚开始", "Just started"),
          meta: run?.status === "queued"
            ? localeText("等待执行槽", "Waiting for a slot")
            : localeText("正在整理检查集", "Resolving checks"),
        };
      } else if (runFinished && checksResolvedTs === null) {
        snapshots.checks = {
          state: "failed",
          stateLabel: translateStatus(run?.status || "failed"),
          durationLabel: formatDuration(run?.started_at, run?.finished_at),
          meta: localeText("运行在检查项冻结前结束了。", "The run ended before checks were resolved."),
        };
      } else {
        snapshots.checks = {
          state: "pending",
          stateLabel: localeText("未开始", "Pending"),
          durationLabel: localeText("待开始", "Waiting"),
          meta: localeText("还没进入这一阶段", "Not started yet"),
        };
      }

      const attemptsByStep = workflowStepAttempts(run);
      stages.filter((stage) => stage.kind === "workflow_step").forEach((stage) => {
        const attempts = attemptsByStep.get(stage.stepId) || [];
        const latestAttempt = attempts[attempts.length - 1] || null;
        const totalMs = attempts.reduce((total, attempt) => total + attemptDurationMs(attempt), 0);
        const completedCount = attempts.filter((attempt) => Boolean(attempt.handoffAt || attempt.ok === true)).length;

        if (currentStage === stage.key && run?.status === "running") {
          const startedAt = parseTimestamp(latestAttempt?.startedAt || currentWorkflowStepEvent(run)?.created_at || run?.started_at);
          const liveMs = startedAt === null ? null : Math.max(0, Date.now() - startedAt);
          snapshots[stage.key] = {
            state: "current",
            stateLabel: localeText("处理中", "Active"),
            durationLabel: formatStageDuration(liveMs) || localeText("刚开始", "Just started"),
            meta: completedCount
              ? localeText(`已完成 ${completedCount} 次`, `Completed ${completedCount}x`)
              : localeText("当前步骤", "Current step"),
          };
          return;
        }

        if (latestAttempt && latestAttempt.ok === false && !latestAttempt.handoffAt) {
          const failedLabel = run?.status === "stopped" && currentStage === stage.key
            ? translateStatus("stopped")
            : localeText("失败", "Failed");
          snapshots[stage.key] = {
            state: "failed",
            stateLabel: failedLabel,
            durationLabel: formatStageDuration(totalMs || attemptDurationMs(latestAttempt)) || localeText("已执行", "Done"),
            meta: run?.status === "stopped" && currentStage === stage.key
              ? localeText("在这个步骤被手动停止。", "The run was stopped during this step.")
              : localeText(`最近一次失败 · 共 ${attempts.length} 次`, `Last attempt failed · ${attempts.length}x`),
          };
          return;
        }

        if (latestAttempt && (latestAttempt.handoffAt || latestAttempt.ok === true)) {
          snapshots[stage.key] = {
            state: "complete",
            stateLabel: localeText("已完成", "Done"),
            durationLabel: formatStageDuration(totalMs || attemptDurationMs(latestAttempt)) || localeText("已执行", "Done"),
            meta: attempts.length > 1
              ? localeText(`已完成 ${attempts.length} 次`, `Completed ${attempts.length}x`)
              : localeText("这一阶段已走通。", "This stage completed."),
          };
          return;
        }

        if (runFinished) {
          snapshots[stage.key] = {
            state: "skipped",
            stateLabel: localeText("未触发", "Skipped"),
            durationLabel: localeText("未触发", "Skipped"),
            meta: stage.archetype === "guide"
              ? localeText("只有停滞或回退才会运行", "Only on plateau or regression")
              : localeText("本次运行没有走到这一步。", "This run never reached this step."),
          };
          return;
        }

        snapshots[stage.key] = {
          state: "pending",
          stateLabel: localeText("未开始", "Pending"),
          durationLabel: localeText("待开始", "Waiting"),
          meta: localeText("还没进入这一阶段", "Not started yet"),
        };
      });

      snapshots.finished = {
        state: runFinished ? (run?.status === "succeeded" ? "complete" : "failed") : "pending",
        stateLabel: runFinished
          ? translateStatus(run?.status || "draft")
          : localeText("进行中", "Open"),
        durationLabel: runFinished
          ? formatDuration(run?.started_at, run?.finished_at)
          : localeText("进行中", "In progress"),
        meta: runFinished
          ? `${localeText("最终状态", "Final status")}: ${translateStatus(run?.status || "draft")}`
          : localeText("运行尚未结束", "The run is still in progress"),
      };

      return snapshots;
    }

    function stageTooltipText(stage, run = getCurrentRun(), snapshots = getStageSnapshots(run || getCurrentRun())) {
      const definition = getStageDefinition(stage, run);
      const snapshot = snapshots[stage] || {durationLabel: "-", meta: "-"};
      return [definition.title, snapshot.durationLabel, snapshot.meta, definition.detail].filter(Boolean).join(" · ");
    }

    function currentRoleStartEvent(run = getCurrentRun()) {
      const stepId = stepIdFromStageKey(getCurrentStage(run));
      if (!stepId) {
        return null;
      }
      const iter = currentIterValue(run);
      return findLatestEvent(getProgressEvents(), (event) => (
        event.event_type === "role_started"
        && String(event.payload?.step_id || "").trim() === stepId
        && Number(event.payload?.iter ?? iter) === iter
      ));
    }

    function latestRoleActivityEvent(run = getCurrentRun()) {
      const role = run?.active_role;
      const stepId = stepIdFromStageKey(getCurrentStage(run));
      if (!role) {
        return null;
      }
      const stageStart = currentRoleStartEvent(run);
      const stageStartTs = parseTimestamp(stageStart?.created_at);
      return findLatestEvent(getConsoleEvents(), (event) => {
        const eventRole = event.role || event.payload?.role;
        if (eventRole !== role || event.event_type === "role_started") {
          return false;
        }
        const eventStepId = String(event.payload?.step_id || "").trim();
        if (stepId && eventStepId && eventStepId !== stepId) {
          return false;
        }
        if (stageStartTs === null) {
          return true;
        }
        const eventTs = parseTimestamp(event.created_at);
        return eventTs !== null && eventTs >= stageStartTs;
      });
    }

    function activityHintKey(stage, run = getCurrentRun()) {
      const definition = getStageDefinition(stage, run);
      if (definition.kind === "checks" || definition.kind === "finished") {
        return definition.kind;
      }
      return definition.archetype || "custom";
    }

    function extractActivitySummary(event, stage) {
      return activityProjector.extractActivitySummary(event, stage, getCurrentRun());
    }

    function describeLiveWork(run = getCurrentRun()) {
      const status = run?.status || "draft";
      const stage = getCurrentStage(run);
      const snapshots = getStageSnapshots(run);
      if (status === "queued") {
        return {
          title: localeText("正在排队，马上轮到它", "Queued up and waiting for its turn"),
          detail: localeText("还没真正进入执行器，队列一空就会开跑。", "It has not entered the executor yet; it will start as soon as a slot opens."),
          duration: snapshots.checks?.durationLabel || formatDuration(run?.queued_at || run?.created_at, null),
          metaLeft: localeText("当前阶段 · 检查项", "Current stage · Checks"),
          metaRight: formatRelativeAge(run?.updated_at),
        };
      }
      if (status === "running") {
        const stageStart = currentRoleStartEvent(run);
        const latestActivity = latestRoleActivityEvent(run);
        const activity = extractActivitySummary(latestActivity, stage);
        const latestSignal = latestActivity?.created_at
          ? localeText(`上次有新动静 ${formatRelativeAge(latestActivity.created_at)}`, `Last signal ${formatRelativeAge(latestActivity.created_at)}`)
          : localeText("还没冒出第一条具体输出", "Waiting for the first concrete signal");
        return {
          title: activity.title,
          detail: activity.detail,
          duration: snapshots[stage]?.durationLabel || (stageStart ? formatDuration(stageStart.created_at, null) : formatDuration(run?.started_at, null)),
          metaLeft: localeText(`第 ${displayIter(run?.current_iter)} 轮 · ${stageDisplayName(stage, run)}`, `Round ${displayIter(run?.current_iter)} · ${stageDisplayName(stage, run)}`),
          metaRight: latestSignal,
        };
      }
      const latestEvent = deps.summarizeLatestEvent ? deps.summarizeLatestEvent() : {
        title: localeText("还没有关键事件", "No key event yet"),
        detail: localeText("运行推进后会在这里显示最新里程碑。", "Recent milestones will appear here once the run advances."),
        meta: "",
      };
      return {
        title: latestEvent.title,
        detail: latestEvent.detail,
        duration: formatDuration(run?.started_at, run?.finished_at),
        metaLeft: localeText(`第 ${displayIter(run?.current_iter)} 轮`, `Round ${displayIter(run?.current_iter)}`),
        metaRight: latestEvent.meta ? formatAbsoluteDate(latestEvent.meta) : localeText("没有更多时间点。", "No additional timestamp."),
      };
    }

    function stageDisplayName(stage, run = getCurrentRun()) {
      return getStageDefinition(stage, run).title || stage;
    }

    return {
      stageKeyForStep,
      stepIdFromStageKey,
      getProgressStages,
      getStageDefinition,
      workflowLoopSummary,
      stageOrderLabel,
      formatDurationMs,
      findLatestEvent,
      getCurrentStage,
      getStageSnapshots,
      stageTooltipText,
      currentIterValue,
      resolvedPayloadRoleName,
      describeLiveWork,
      stageDisplayName,
      runIsActive,
    };
  }

  window.LooporaRunDetailProgress = {createProgressProjector};
})();
