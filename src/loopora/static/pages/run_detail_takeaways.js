(function () {
  function createTakeawayProjector(deps = {}) {
    const localeText = deps.localeText || ((zh, en) => en || zh || "");
    const escapeHtml = deps.escapeHtml || ((value) => String(value || ""));
    const formatAbsoluteDate = deps.formatAbsoluteDate || (() => "-");

    function takeawayStatusLabel(status) {
      switch (status) {
        case "passed":
          return localeText("已通过", "Passed");
        case "completed":
          return localeText("已完成", "Completed");
        case "blocked":
          return localeText("待继续", "Needs another pass");
        case "failed":
          return localeText("失败", "Failed");
        case "running":
          return localeText("进行中", "Running");
        case "advisory":
          return localeText("建议", "Advisory");
        default:
          return localeText("待生成", "Pending");
      }
    }

    function takeawayHeadline(iteration) {
      switch (iteration?.status) {
        case "passed":
          return localeText("这一轮已经通过", "This round passed");
        case "blocked":
          return localeText("这一轮还需要继续修正", "This round needs another pass");
        case "failed":
          return localeText("这一轮执行失败", "This round failed");
        case "running":
          return localeText("这一轮仍在推进", "This round is still moving");
        case "completed":
          return localeText("这一轮已经收口", "This round finished");
        case "advisory":
          return localeText("这一轮给出了建议", "This round produced guidance");
        default:
          return localeText("等待第一个稳定结论", "Waiting for the first stable takeaway");
      }
    }

    function formatScore(value) {
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) {
        return "";
      }
      return numeric.toFixed(numeric >= 1 ? 0 : 2);
    }

    function takeawayRoleSupport(role) {
      if (role?.blocking_item) {
        return localeText(`阻塞：${role.blocking_item}`, `Blocker: ${role.blocking_item}`);
      }
      if (role?.next_action) {
        return localeText(`建议动作：${role.next_action}`, `Suggested action: ${role.next_action}`);
      }
      return "";
    }

    function takeawayRoleMeta(role) {
      const bits = [];
      if (role?.composite_score !== null && role?.composite_score !== undefined && role?.archetype === "gatekeeper") {
        bits.push(localeText(`综合分 ${formatScore(role.composite_score)}`, `Composite ${formatScore(role.composite_score)}`));
      }
      if (Array.isArray(role?.evidence_refs) && role.evidence_refs.length) {
        bits.push(localeText(`证据 ${role.evidence_refs.length} 条`, `${role.evidence_refs.length} evidence ref${role.evidence_refs.length === 1 ? "" : "s"}`));
      }
      return bits.join(" · ");
    }

    function evidenceBucketCount(snapshot, bucketName) {
      const buckets = snapshot?.task_verdict?.buckets || snapshot?.evidence_buckets || {};
      return Array.isArray(buckets[bucketName]) ? buckets[bucketName].length : 0;
    }

    function firstBucketText(snapshot, ...bucketNames) {
      const buckets = snapshot?.task_verdict?.buckets || snapshot?.evidence_buckets || {};
      for (const bucketName of bucketNames) {
        const items = Array.isArray(buckets[bucketName]) ? buckets[bucketName] : [];
        const item = items[0];
        if (!item) {
          continue;
        }
        const text = item.text || item.label || item.reason || "";
        if (String(text).trim()) {
          return String(text).trim();
        }
      }
      return "";
    }

    function taskVerdictStatusLabel(status) {
      const normalized = String(status || "not_evaluated").toLowerCase();
      const labels = {
        not_evaluated: localeText("未评估", "Not evaluated"),
        passed: localeText("已通过", "Passed"),
        failed: localeText("未通过", "Failed"),
        insufficient_evidence: localeText("证据不足", "Insufficient evidence"),
        passed_with_residual_risk: localeText("有残余风险地通过", "Passed with residual risk"),
      };
      return labels[normalized] || normalized;
    }

    function evidenceCoverageCard(labelZh, labelEn, value, detail, actionHtml) {
      return `
        <article class="takeaway-evidence-card">
          <span class="takeaway-evidence-label">${escapeHtml(localeText(labelZh, labelEn))}</span>
          <strong>${escapeHtml(String(value || "-"))}</strong>
          ${detail ? `<p>${escapeHtml(detail)}</p>` : ""}
          ${actionHtml || ""}
        </article>
      `;
    }

    function evidenceCoverageHtml(snapshot, runId) {
      const coverage = snapshot?.evidence_coverage || {};
      const evidenceCount = Number(coverage.evidence_count || snapshot?.evidence_count || 0);
      const checkCount = Number(coverage.check_count || 0);
      const coveredChecks = Number(coverage.covered_check_count || 0);
      const coveragePath = String(coverage.coverage_path || "");
      const gatekeeperRefs = Array.isArray(coverage.latest_gatekeeper?.evidence_refs)
        ? coverage.latest_gatekeeper.evidence_refs.length
        : 0;
      const primaryGap = Array.isArray(coverage.top_gaps) && coverage.top_gaps.length ? coverage.top_gaps[0] : null;
      const statusReason = coverage.summary?.reason || "";
      const traceAction = coveragePath
        ? `<a class="takeaway-evidence-link" href="/api/runs/${encodeURIComponent(runId)}/artifacts/evidence-coverage" target="_blank" rel="noreferrer">${escapeHtml(localeText("查看证据链", "View trace"))}</a>`
        : "";
      const statusDetail = statusReason
        ? statusReason
        : coverage.ledger_path
          ? localeText(`${evidenceCount} 条证据 · 账本 ${coverage.ledger_path}`, `${evidenceCount} evidence item${evidenceCount === 1 ? "" : "s"} · Ledger ${coverage.ledger_path}`)
          : localeText("run 开始后会写入证据账本。", "The ledger appears after the run starts.");
      const provenCount = evidenceBucketCount(snapshot, "proven");
      const weakBucketCount = evidenceBucketCount(snapshot, "weak");
      const unprovenCount = evidenceBucketCount(snapshot, "unproven");
      const blockingCount = evidenceBucketCount(snapshot, "blocking");
      const riskCount = evidenceBucketCount(snapshot, "residual_risk") || Number(coverage.residual_risk_count || 0);
      return [
        evidenceCoverageCard("裁决状态", "Verdict status", taskVerdictStatusLabel(snapshot?.task_verdict?.status), statusDetail, traceAction),
        evidenceCoverageCard("已证明", "Proven", String(provenCount || coveredChecks || 0), firstBucketText(snapshot, "proven") || (checkCount ? `${coveredChecks}/${checkCount}` : "")),
        evidenceCoverageCard("偏弱", "Weak", String(weakBucketCount), firstBucketText(snapshot, "weak")),
        evidenceCoverageCard("未证明", "Unproven", String(unprovenCount), firstBucketText(snapshot, "unproven") || primaryGap?.text || ""),
        evidenceCoverageCard("阻断 / 风险", "Blockers / risk", `${blockingCount}/${riskCount}`, firstBucketText(snapshot, "blocking", "residual_risk") || (gatekeeperRefs ? localeText("GateKeeper 已引用上游证据。", "GateKeeper cited upstream evidence.") : "")),
      ].join("");
    }

    function evidenceOutcome(snapshot, currentRun) {
      const taskVerdict = snapshot?.task_verdict || currentRun?.task_verdict || {};
      const taskStatus = String(taskVerdict.status || "not_evaluated").toLowerCase();
      const coverage = snapshot?.evidence_coverage || {};
      const coverageStatus = String(coverage.status || "").toLowerCase();
      const weakCount = Number(coverage.weak_target_count || 0);
      const missingCount = Number(coverage.missing_target_count || 0);
      const blockedCount = Number(coverage.blocked_target_count || 0);
      const primaryGap = Array.isArray(coverage.top_gaps) && coverage.top_gaps.length ? coverage.top_gaps[0] : null;
      if (taskStatus === "passed" || taskStatus === "passed_with_residual_risk") {
        return {
          soft: taskStatus === "passed",
          title: taskVerdictStatusLabel(taskStatus),
          detail: taskVerdict.summary || localeText(
            "任务裁决由证据桶支撑；可继续查看 proven / residual risk 的明细。",
            "The task verdict is backed by evidence buckets; inspect proven and residual-risk details as needed."
          ),
        };
      }
      if (taskStatus === "failed" || ["blocked", "partial"].includes(coverageStatus) || blockedCount > 0 || missingCount > 0) {
        return {
          soft: false,
          title: taskVerdictStatusLabel(taskStatus === "failed" ? "failed" : "insufficient_evidence"),
          detail: taskVerdict.summary || firstBucketText(snapshot, "blocking", "unproven", "weak") || primaryGap?.text || localeText(
            "GateKeeper 裁决、证据缺口和阻塞项已保留在本次 run 的证据材料里。",
            "The verdict, evidence gaps, and blockers are preserved in this run's evidence material."
          ),
        };
      }
      if (taskStatus === "insufficient_evidence" || coverageStatus === "weak" || weakCount > 0) {
        return {
          soft: false,
          title: taskVerdictStatusLabel("insufficient_evidence"),
          detail: taskVerdict.summary || firstBucketText(snapshot, "weak", "unproven") || primaryGap?.text || localeText(
            "本轮已经留下弱覆盖信号；请查看证据链判断哪些完成条件仍缺直接证明。",
            "This run preserved weak-coverage signals; inspect the evidence trace to see which completion targets still lack direct proof."
          ),
        };
      }
      return {
        soft: true,
        title: taskVerdictStatusLabel(taskStatus),
        detail: taskVerdict.summary || localeText(
          "角色 handoff、证据账本或 GateKeeper 裁决写出后，这里会收敛成证据结论。",
          "Once role handoffs, the evidence ledger, or the GateKeeper verdict lands, this will settle into an evidence outcome."
        ),
      };
    }

    function takeawayIterationMeta(iteration, snapshot) {
      const bits = [];
      if (iteration?.composite_score !== null && iteration?.composite_score !== undefined) {
        bits.push(localeText(`综合分 ${formatScore(iteration.composite_score)}`, `Composite ${formatScore(iteration.composite_score)}`));
      }
      if (iteration?.role_count) {
        bits.push(localeText(`${iteration.role_count} 条角色结论`, `${iteration.role_count} role conclusion${iteration.role_count === 1 ? "" : "s"}`));
      }
      const evidenceCount = Number(snapshot?.evidence_count || 0);
      if (evidenceCount > 0) {
        bits.push(localeText(`${evidenceCount} 条证据`, `${evidenceCount} evidence item${evidenceCount === 1 ? "" : "s"}`));
      }
      if (iteration?.timestamp) {
        bits.push(formatAbsoluteDate(iteration.timestamp));
      }
      return bits.join(" · ");
    }

    function takeawayIterationKey(iteration) {
      if (!iteration || typeof iteration !== "object") {
        return "";
      }
      const raw = iteration.iter ?? iteration.display_iter ?? "";
      return raw === null || raw === undefined ? "" : String(raw);
    }

    function takeawayIterationOptionLabel(iteration) {
      const bits = [localeText(`第 ${iteration.display_iter || 1} 轮`, `Iter ${iteration.display_iter || 1}`)];
      const statusLabel = takeawayStatusLabel(iteration?.status);
      if (statusLabel) {
        bits.push(statusLabel);
      }
      if (iteration?.role_count) {
        bits.push(
          localeText(
            `${iteration.role_count} 条角色结论`,
            `${iteration.role_count} role conclusion${iteration.role_count === 1 ? "" : "s"}`
          )
        );
      }
      return bits.join(" · ");
    }

    function resolveSelectedIteration(iterations, selectedKey) {
      if (!Array.isArray(iterations) || !iterations.length) {
        return {iteration: null, selectedKey: null};
      }
      const hasSelected = iterations.some((iteration) => takeawayIterationKey(iteration) === selectedKey);
      const nextKey = hasSelected ? selectedKey : takeawayIterationKey(iterations[0]);
      return {
        selectedKey: nextKey,
        iteration: iterations.find((iteration) => takeawayIterationKey(iteration) === nextKey) || iterations[0],
      };
    }

    function renderTakeawayIterationCard(iteration, snapshot) {
      return `
        <article class="takeaway-iteration-card takeaway-iteration-card--${escapeHtml(iteration.status || "pending")}">
          <div class="takeaway-iteration-head">
            <div class="takeaway-iteration-copy">
              <span class="takeaway-iteration-label">${escapeHtml(localeText(`第 ${iteration.display_iter || 1} 轮`, `Iter ${iteration.display_iter || 1}`))}</span>
              <strong class="takeaway-iteration-title">${escapeHtml(takeawayHeadline(iteration))}</strong>
            </div>
            <span class="takeaway-status-pill takeaway-status-pill--${escapeHtml(iteration.status || "pending")}">${escapeHtml(takeawayStatusLabel(iteration.status))}</span>
          </div>
          <p class="takeaway-iteration-note">${escapeHtml(iteration.summary || localeText("这一轮还没有可用结论。", "This round does not have a stable takeaway yet."))}</p>
          <div class="takeaway-iteration-meta">${escapeHtml(takeawayIterationMeta(iteration, snapshot))}</div>
          <div class="takeaway-role-grid">
            ${(iteration.roles || []).map((role) => {
              const support = takeawayRoleSupport(role);
              const meta = takeawayRoleMeta(role);
              return `
                <article class="takeaway-role-card takeaway-role-card--${escapeHtml(role.status || "pending")}">
                  <div class="takeaway-role-head">
                    <div class="takeaway-role-chip">
                      <span class="takeaway-role-order">${escapeHtml(String((Number(role.step_order) || 0) + 1).padStart(2, "0"))}</span>
                      <strong class="takeaway-role-name">${escapeHtml(role.role_name || "-")}</strong>
                    </div>
                    <span class="takeaway-status-pill takeaway-status-pill--${escapeHtml(role.status || "pending")}">${escapeHtml(takeawayStatusLabel(role.status))}</span>
                  </div>
                  <div class="takeaway-role-body">
                    <p class="takeaway-role-summary">${escapeHtml(role.summary || localeText("这个角色还没有稳定结论。", "This role has no stable takeaway yet."))}</p>
                    ${support ? `<p class="takeaway-role-support">${escapeHtml(support)}</p>` : ""}
                  </div>
                  ${meta ? `<div class="takeaway-role-meta">${escapeHtml(meta)}</div>` : ""}
                </article>
              `;
            }).join("")}
          </div>
        </article>
      `;
    }

    function iterationOptionsHtml(iterations, selectedKey) {
      return iterations.map((iteration) => {
        const value = takeawayIterationKey(iteration);
        const selected = value === selectedKey ? ' selected="selected"' : "";
        return `<option value="${escapeHtml(value)}"${selected}>${escapeHtml(takeawayIterationOptionLabel(iteration))}</option>`;
      }).join("");
    }

    function takeawayMeta(snapshot) {
      const latestIter = snapshot?.latest_display_iter;
      return latestIter
        ? localeText(
          `最近到第 ${latestIter} 轮 · ${snapshot.role_conclusion_count || 0} 条角色结论 · ${snapshot.evidence_count || 0} 条证据`,
          `Up to iter ${latestIter} · ${snapshot.role_conclusion_count || 0} role conclusions · ${snapshot.evidence_count || 0} evidence items`
        )
        : localeText("角色 handoff 写出来后，这里会自动更新。", "This updates as soon as the first role handoff lands.");
    }

    return {
      evidenceCoverageHtml,
      evidenceOutcome,
      iterationOptionsHtml,
      renderTakeawayIterationCard,
      resolveSelectedIteration,
      takeawayIterationKey,
      takeawayMeta,
      taskVerdictStatusLabel,
    };
  }

  window.LooporaRunDetailTakeaways = {createTakeawayProjector};
})();
