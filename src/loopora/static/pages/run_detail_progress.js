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
    function nonNegativeInteger(value) {
      return Number.isInteger(value) && value >= 0 ? value : null;
    }
    const displayIter = deps.displayIter || ((value) => {
      const parsed = nonNegativeInteger(value);
      return parsed === null ? 1 : parsed + 1;
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
      builder: {zh: "构建者", en: "Builder"},
      inspector: {zh: "巡检者", en: "Inspector"},
      gatekeeper: {zh: "守门者", en: "GateKeeper"},
      guide: {zh: "引导者", en: "Guide"},
      custom: {zh: "自定义角色", en: "Custom Role"},
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
          "真正修改工作区，朝 Loop 目标和检查项推进实现。",
          "Actually changes the workspace to move the implementation toward the Task and checks."
        ),
        inspector: localeText(
          "运行命令、页面交互或源码检查来收集证据，回答“发生了什么”。",
          "Runs commands, page interactions, or source inspection to collect evidence and answer 'what happened?'"
        ),
        gatekeeper: localeText(
          "根据 Loop 目标、检查项、边界和测试证据做裁决，回答“算不算通过”。",
          "Judges the evidence against the full task contract to answer 'does this count as passing?'"
        ),
        guide: localeText(
          "把上游证据压缩成下一步修复或收窄方向；显式出现在流程里时会正常运行。",
          "Turns upstream evidence into the next repair or narrowing direction; it runs when explicitly placed in the run flow."
        ),
        custom: localeText(
          "执行当前编排里定义的自定义步骤，并把结果交接给后续阶段。",
          "Executes the custom step defined in this flow and hands its result to the next stage."
        ),
      };
      const base = details[archetype] || details.custom;
      if (archetype === "gatekeeper" && String(step?.on_pass || "").trim() === "finish_run") {
        return `${base} ${localeText("通过时可以直接结束本次运行。", "A passing result can finish the run immediately.")}`;
      }
      return base;
    }

    function stageOrderLabel(stage) {
      const sequence = nonNegativeInteger(stage?.sequence);
      return sequence !== null && sequence > 0 ? String(sequence).padStart(2, "0") : "--";
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
        title: localeText("运行收束", "Run closed"),
        detail: localeText(
          "这次运行已经结束，可能是成功、失败或手动停止。",
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
          eyebrow: localeText("Loop 步骤", "Loop steps"),
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
        eyebrow: localeText("Loop 步骤", "Loop steps"),
        title: workflowStages.map((stage) => stage.title).join(" → "),
        detail: hasFinishGate
          ? localeText(
            "中间步骤按 Loop 计划循环推进，直到守门者放行或运行预算耗尽。",
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
      const explicit = nonNegativeInteger(attempt?.durationMs);
      if (explicit !== null) {
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
        const iter = payload.iter === undefined || payload.iter === null ? null : nonNegativeInteger(payload.iter);
        if (payload.iter !== undefined && payload.iter !== null && iter === null) {
          return;
        }
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
          attempt.ok = payload.ok === true;
          attempt.attempts = nonNegativeInteger(payload.attempts) ?? 0;
          attempt.error = String(payload.error || "").trim();
          attempt.durationMs = nonNegativeInteger(payload.duration_ms);
        }
        if (event.event_type === "step_handoff_written") {
          attempt.handoffAt = event.created_at;
          attempt.handoffStatus = String(payload.status || "").trim();
        }
      });
      return attemptsByStep;
    }

    function currentIterValue(run = getCurrentRun()) {
      return nonNegativeInteger(run?.current_iter) ?? 0;
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
          const eventIter = payload.iter === undefined || payload.iter === null ? iter : nonNegativeInteger(payload.iter);
          if (eventIter === null || eventIter !== iter) {
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
      return ["queued", "running", "awaiting_agent"].includes(run?.status || "");
    }

    function runIsTerminal(run) {
      return ["succeeded", "failed", "stopped"].includes(run?.status || "");
    }

    function taskVerdictStatus(run) {
      const taskVerdict = run?.task_verdict && typeof run.task_verdict === "object" ? run.task_verdict : {};
      return String(taskVerdict.status || "not_evaluated").trim().toLowerCase() || "not_evaluated";
    }

    function taskVerdictSummary(run) {
      const taskVerdict = run?.task_verdict && typeof run.task_verdict === "object" ? run.task_verdict : {};
      return String(taskVerdict.summary || "").trim();
    }

    function terminalTaskOutcome(run = getCurrentRun()) {
      if (!runIsTerminal(run)) {
        return null;
      }
      const status = taskVerdictStatus(run);
      const runStatus = String(run?.status || "draft");
      const runStatusLabel = translateStatus(runStatus);
      const verdictMeta = `${localeText("生命周期", "Lifecycle")}: ${runStatusLabel} · ${localeText("Loop 裁决", "Task verdict")}: ${status}`;
      const summary = taskVerdictSummary(run);

      if (runStatus === "failed" || runStatus === "stopped") {
        return {
          state: "failed",
          stateLabel: runStatus === "stopped" ? localeText("已停止", "Stopped") : localeText("运行失败", "Run failed"),
          title: runStatus === "stopped"
            ? localeText("运行已停止，Loop 裁决单独查看", "Run stopped; inspect the task verdict separately")
            : localeText("运行失败，Loop 裁决单独查看", "Run failed; inspect the task verdict separately"),
          detail: summary || localeText(
            "系统生命周期没有正常收束；这不能被读成任务已经证明完成。",
            "The system lifecycle did not settle cleanly; this is not evidence that the task was proven complete."
          ),
          meta: verdictMeta,
        };
      }

      if (status === "passed") {
        return {
          state: "complete",
          stateLabel: localeText("已通过", "Passed"),
          title: localeText("Loop 裁决已通过", "Task verdict passed"),
          detail: summary || localeText(
            "证据支持本次 Loop 结论。",
            "Evidence supports the task conclusion."
          ),
          meta: verdictMeta,
        };
      }

      if (status === "passed_with_residual_risk") {
        return {
          state: "warning",
          stateLabel: localeText("带风险", "Risk kept"),
          title: localeText("Loop 已通过，但保留残余风险", "Task passed with residual risk"),
          detail: summary || localeText(
            "证据支持本次结论，但仍有已接受的残余风险需要保持可见。",
            "Evidence supports the conclusion, with accepted residual risk still visible."
          ),
          meta: verdictMeta,
        };
      }

      if (status === "insufficient_evidence") {
        return {
          state: "warning",
          stateLabel: localeText("未证成", "Unproven"),
          title: localeText("运行已收束，但任务仍未证成", "Run closed; task still unproven"),
          detail: summary || localeText(
            "生命周期已经结束，但证据还不足以证明 Loop 通过。",
            "The lifecycle ended, but evidence is not strong enough for a task pass."
          ),
          meta: verdictMeta,
        };
      }

      if (status === "failed") {
        return {
          state: "failed",
          stateLabel: localeText("未通过", "Failed"),
          title: localeText("运行已收束，Loop 裁决未通过", "Run closed; task verdict failed"),
          detail: summary || localeText(
            "阻断项仍然存在，优先查看证据桶和下一步动作。",
            "Blockers remain; start with the evidence buckets and next action."
          ),
          meta: verdictMeta,
        };
      }

      return {
        state: "warning",
        stateLabel: localeText("未裁决", "No verdict"),
        title: localeText("运行已收束，但没有 Loop 裁决", "Run closed without a task verdict"),
        detail: summary || localeText(
          "只能确认系统生命周期结束，不能确认任务已经被证据证明。",
          "Only the system lifecycle is closed; the task has not been proven by evidence."
        ),
        meta: verdictMeta,
      };
    }

    function getCurrentStage(run = getCurrentRun()) {
      if (!run) {
        return "checks";
      }
      if (run.status === "succeeded") {
        return "finished";
      }
      const currentStepEvent = currentWorkflowStepEvent(run);
      const stepId = String(currentStepEvent?.payload?.step_id || "").trim();
      if (stepId && (run.status === "running" || run.status === "awaiting_agent")) {
        return stageKeyForStep(stepId);
      }
      const checksResolved = latestProgressEventOfType("checks_resolved");
      if (run.status === "queued" || (!checksResolved && runIsActive(run))) {
        return "checks";
      }
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
      const runFinished = runIsTerminal(run);
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
          stateLabel: run?.status === "queued"
            ? localeText("排队中", "Queued")
            : (run?.status === "awaiting_agent" ? localeText("等待 Agent", "Awaiting Agent") : localeText("处理中", "Active")),
          durationLabel: formatStageDuration(checksLiveMs) || localeText("刚开始", "Just started"),
          meta: run?.status === "queued"
            ? localeText("等待执行槽", "Waiting for a slot")
            : (run?.status === "awaiting_agent"
              ? localeText("宿主 Agent 正在执行或准备提交下一步结果。", "The host Agent is working on or preparing to submit the next step result.")
              : localeText("正在整理检查集", "Resolving checks")),
        };
      } else if (currentStage !== "checks" && runIsActive(run)) {
        snapshots.checks = {
          state: "complete",
          stateLabel: localeText("已冻结", "Ready"),
          durationLabel: localeText("已就绪", "Ready"),
          meta: localeText("来自已审查的 Loop 契约", "From reviewed Loop contract"),
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

        if (currentStage === stage.key && (run?.status === "running" || run?.status === "awaiting_agent")) {
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
              ? localeText("本次运行没有进入这个引导步骤。", "This run did not enter this Guide step.")
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

      const terminalOutcome = terminalTaskOutcome(run);
      snapshots.finished = {
        state: runFinished ? (terminalOutcome?.state || "failed") : "pending",
        stateLabel: runFinished
          ? (terminalOutcome?.stateLabel || translateStatus(run?.status || "draft"))
          : localeText("进行中", "Open"),
        durationLabel: runFinished
          ? formatDuration(run?.started_at, run?.finished_at)
          : localeText("进行中", "In progress"),
        meta: runFinished
          ? (terminalOutcome?.meta || `${localeText("生命周期", "Lifecycle")}: ${translateStatus(run?.status || "draft")}`)
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
        && (event.payload?.iter === undefined || event.payload?.iter === null
          ? true
          : nonNegativeInteger(event.payload.iter) === iter)
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
          detail: localeText("还在等待运行位置，前面的工作结束后会开始。", "It is waiting for a run slot and will start when earlier work clears."),
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
          metaLeft: localeText(`第 ${displayIter(currentIterValue(run))} 轮 · ${stageDisplayName(stage, run)}`, `Round ${displayIter(currentIterValue(run))} · ${stageDisplayName(stage, run)}`),
          metaRight: latestSignal,
        };
      }
      if (status === "awaiting_agent") {
        return {
          title: localeText("等待宿主 Agent 提交结果", "Waiting for host Agent result"),
          detail: localeText("Loopora 已冻结下一步上下文；宿主 Agent 完成该角色后会把结构化结果提交回来。", "Loopora has frozen the next-step context; the host Agent will submit structured output after completing that role."),
          duration: snapshots[stage]?.durationLabel || formatDuration(run?.started_at, null),
          metaLeft: localeText(`第 ${displayIter(currentIterValue(run))} 轮 · ${stageDisplayName(stage, run)}`, `Round ${displayIter(currentIterValue(run))} · ${stageDisplayName(stage, run)}`),
          metaRight: formatRelativeAge(run?.updated_at),
        };
      }
      if (runIsTerminal(run)) {
        const terminalOutcome = terminalTaskOutcome(run);
        return {
          title: terminalOutcome?.title || localeText("运行已收束", "Run closed"),
          detail: terminalOutcome?.detail || localeText(
            "生命周期已经结束；Loop 裁决需要单独查看。",
            "The lifecycle has ended; inspect the task verdict separately."
          ),
          duration: formatDuration(run?.started_at, run?.finished_at),
          metaLeft: localeText(`第 ${displayIter(currentIterValue(run))} 轮 · ${stageDisplayName(stage, run)}`, `Round ${displayIter(currentIterValue(run))} · ${stageDisplayName(stage, run)}`),
          metaRight: terminalOutcome?.meta || `${localeText("生命周期", "Lifecycle")}: ${translateStatus(status)}`,
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
        metaLeft: localeText(`第 ${displayIter(currentIterValue(run))} 轮`, `Round ${displayIter(currentIterValue(run))}`),
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
      runIsTerminal,
      terminalTaskOutcome,
    };
  }

  window.LooporaRunDetailProgress = {createProgressProjector};
})();
