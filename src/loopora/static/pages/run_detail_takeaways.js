(function () {
  function defaultEscapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function createTakeawayProjector(deps = {}) {
    const localeText = deps.localeText || ((zh, en) => en || zh || "");
    const escapeHtml = deps.escapeHtml || defaultEscapeHtml;
    const formatAbsoluteDate = deps.formatAbsoluteDate || (() => "-");

    function nonNegativeInteger(value) {
      return Number.isInteger(value) && value >= 0 ? value : null;
    }

    function displayCount(value, fallback = 0) {
      const count = nonNegativeInteger(value);
      return count === null ? fallback : count;
    }

    function firstDisplayCount(...values) {
      for (const value of values) {
        const count = nonNegativeInteger(value);
        if (count !== null) {
          return count;
        }
      }
      return 0;
    }

    function takeawayStatusLabel(status) {
      switch (status) {
        case "passed":
          return localeText("已通过", "Passed");
        case "completed":
          return localeText("已收口", "Finished");
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
      const numeric = typeof value === "number" && Number.isFinite(value) ? value : null;
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
      return bucketItems(snapshot, bucketName).length;
    }

    function bucketPayload(value) {
      return value && typeof value === "object" && !Array.isArray(value) ? value : {};
    }

    function bucketItems(snapshot, bucketName) {
      const verdictBuckets = bucketPayload(snapshot?.task_verdict?.buckets);
      const verdictItems = verdictBuckets[bucketName];
      if (Array.isArray(verdictItems) && verdictItems.length) {
        return verdictItems;
      }
      const evidenceBuckets = bucketPayload(snapshot?.evidence_buckets);
      const evidenceItems = evidenceBuckets[bucketName];
      if (Array.isArray(evidenceItems)) {
        return evidenceItems;
      }
      return Array.isArray(verdictItems) ? verdictItems : [];
    }

    function hasBucketProjection(snapshot) {
      return [bucketPayload(snapshot?.task_verdict?.buckets), bucketPayload(snapshot?.evidence_buckets)].some((buckets) =>
        Object.values(buckets).some((items) => Array.isArray(items))
      );
    }

    function firstBucketText(snapshot, ...bucketNames) {
      for (const bucketName of bucketNames) {
        const items = bucketItems(snapshot, bucketName);
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

    function bucketTraceText(snapshot, bucketName) {
      const evidenceRefs = new Set();
      const artifactRefs = new Set();
      for (const item of bucketItems(snapshot, bucketName)) {
        if (Array.isArray(item?.evidence_refs)) {
          item.evidence_refs.forEach((ref) => {
            const value = String(ref || "").trim();
            if (value) {
              evidenceRefs.add(value);
            }
          });
        }
        if (Array.isArray(item?.artifact_refs)) {
          item.artifact_refs.forEach((ref) => {
            const value = String(ref?.workspace_path || ref?.relative_path || ref?.absolute_path || ref?.label || JSON.stringify(ref || {})).trim();
            if (value) {
              artifactRefs.add(value);
            }
          });
        }
      }
      const bits = [];
      if (evidenceRefs.size) {
        bits.push(localeText(`证据引用 ${evidenceRefs.size} 条`, `${evidenceRefs.size} evidence ref${evidenceRefs.size === 1 ? "" : "s"}`));
      }
      if (artifactRefs.size) {
        bits.push(localeText(`产物 ${artifactRefs.size} 个`, `${artifactRefs.size} artifact${artifactRefs.size === 1 ? "" : "s"}`));
      }
      return bits.join(" · ");
    }

    function bucketDetailText(snapshot, bucketName, fallback = "") {
      return [firstBucketText(snapshot, bucketName) || fallback, bucketTraceText(snapshot, bucketName)]
        .filter(Boolean)
        .join(" · ");
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

    function judgmentContractDetail(contract) {
      const bits = [];
      const sourceBundle = contract?.source_bundle;
      if (sourceBundle && typeof sourceBundle === "object" && sourceBundle.id) {
        const sourceBits = [sourceBundle.name || sourceBundle.id];
        const revision = nonNegativeInteger(sourceBundle.revision);
        if (revision && revision > 0) {
          sourceBits.push(localeText(`版本 ${revision}`, `rev ${revision}`));
        }
        if (sourceBundle.bundle_sha256) {
          sourceBits.push(`sha ${String(sourceBundle.bundle_sha256).slice(0, 12)}`);
        }
        if (sourceBundle.imported_from_path) {
          sourceBits.push(sourceBundle.imported_from_path);
        }
        bits.push(localeText(`来源方案：${sourceBits.join(" · ")}`, `Source plan: ${sourceBits.join(" · ")}`));
      }
      if (contract?.collaboration_summary) {
        bits.push(contract.collaboration_summary);
      }
      if (contract?.workflow_collaboration_intent && contract.workflow_collaboration_intent !== contract?.collaboration_summary) {
        bits.push(contract.workflow_collaboration_intent);
      }
      if (Array.isArray(contract?.loop_fit_reasons) && contract.loop_fit_reasons.length) {
        bits.push(localeText(`Loopora 适配：${contract.loop_fit_reasons[0]}`, `Loopora fit: ${contract.loop_fit_reasons[0]}`));
      }
      if (Array.isArray(contract?.success_surface) && contract.success_surface.length) {
        bits.push(localeText(`成功面：${contract.success_surface[0]}`, `Success: ${contract.success_surface[0]}`));
      }
      if (Array.isArray(contract?.execution_strategy) && contract.execution_strategy.length) {
        bits.push(localeText(`执行策略：${contract.execution_strategy[0]}`, `Execution strategy: ${contract.execution_strategy[0]}`));
      }
      if (Array.isArray(contract?.local_governance) && contract.local_governance.length) {
        bits.push(localeText(`本地治理：${contract.local_governance[0]}`, `Local governance: ${contract.local_governance[0]}`));
      }
      if (Array.isArray(contract?.role_postures) && contract.role_postures.length) {
        bits.push(localeText(`角色姿态：${contract.role_postures[0]}`, `Role posture: ${contract.role_postures[0]}`));
      }
      if (Array.isArray(contract?.judgment_tradeoffs) && contract.judgment_tradeoffs.length) {
        bits.push(localeText(`判断取舍：${contract.judgment_tradeoffs[0]}`, `Tradeoff: ${contract.judgment_tradeoffs[0]}`));
      }
      if (Array.isArray(contract?.evidence_preferences) && contract.evidence_preferences.length) {
        bits.push(localeText(`证据偏好：${contract.evidence_preferences[0]}`, `Evidence: ${contract.evidence_preferences[0]}`));
      }
      if (Array.isArray(contract?.fake_done_states) && contract.fake_done_states.length) {
        bits.push(localeText(`假完成：${contract.fake_done_states[0]}`, `Fake done: ${contract.fake_done_states[0]}`));
      }
      if (contract?.residual_risk) {
        bits.push(localeText(`残余风险：${contract.residual_risk}`, `Residual risk: ${contract.residual_risk}`));
      }
      if (!bits.length && contract?.goal) {
        bits.push(contract.goal);
      }
      return bits.slice(0, 12).join(" · ");
    }

    function evidenceCoverageHtml(snapshot, runId) {
      const coverage = snapshot?.evidence_coverage || {};
      const manifest = snapshot?.evidence_manifest || {};
      const judgmentContract = snapshot?.judgment_contract || {};
      const evidenceCount = firstDisplayCount(coverage.evidence_count, snapshot?.evidence_count);
      const checkCount = displayCount(coverage.check_count);
      const coveredChecks = displayCount(coverage.covered_check_count);
      const coveragePath = String(coverage.coverage_path || "");
      const manifestPath = String(manifest.manifest_path || "");
      const taskVerdictPath = String(snapshot?.task_verdict_path || "");
      const contractPath = String(judgmentContract.contract_path || "");
      const gatekeeperRefs = Array.isArray(coverage.latest_gatekeeper?.evidence_refs)
        ? coverage.latest_gatekeeper.evidence_refs.length
        : 0;
      const primaryGap = Array.isArray(coverage.top_gaps) && coverage.top_gaps.length ? coverage.top_gaps[0] : null;
      const statusReason = coverage.summary?.reason || "";
      const traceAction = coveragePath
        ? `<a class="takeaway-evidence-link" href="/api/runs/${encodeURIComponent(runId)}/artifacts/evidence-coverage" target="_blank" rel="noreferrer">${escapeHtml(localeText("查看证据链", "View trace"))}</a>`
        : "";
      const manifestAction = manifestPath
        ? `<a class="takeaway-evidence-link" href="/api/runs/${encodeURIComponent(runId)}/artifacts/evidence-manifest" target="_blank" rel="noreferrer">${escapeHtml(localeText("查看证据清单", "View manifest"))}</a>`
        : "";
      const verdictAction = taskVerdictPath
        ? `<a class="takeaway-evidence-link" href="/api/runs/${encodeURIComponent(runId)}/artifacts/task-verdict" target="_blank" rel="noreferrer">${escapeHtml(localeText("查看裁决", "View verdict"))}</a>`
        : "";
      const contractAction = contractPath
        ? `<a class="takeaway-evidence-link" href="/api/runs/${encodeURIComponent(runId)}/artifacts/run-contract" target="_blank" rel="noreferrer">${escapeHtml(localeText("查看契约", "View contract"))}</a>`
        : "";
      const statusDetail = statusReason
        ? statusReason
        : coverage.ledger_path
          ? localeText(`${evidenceCount} 条证据 · 账本 ${coverage.ledger_path}`, `${evidenceCount} evidence item${evidenceCount === 1 ? "" : "s"} · Ledger ${coverage.ledger_path}`)
          : localeText("运行开始后会写入证据账本。", "The ledger appears after the run starts.");
      const claimCount = displayCount(manifest.claim_count);
      const directProofCount = displayCount(manifest.direct_proof_claim_count);
      const workspaceArtifactCount = displayCount(manifest.workspace_artifact_claim_count);
      const runArtifactCount = displayCount(manifest.run_artifact_claim_count);
      const ledgerOnlyCount = displayCount(manifest.ledger_only_claim_count);
      const unverifiedCount = displayCount(manifest.unverified_claim_count);
      const proofDetail = manifestPath
        ? localeText(
          `直接证明 ${directProofCount} · 工作区产物 ${workspaceArtifactCount} · 运行产物 ${runArtifactCount} · 仅账本 ${ledgerOnlyCount} · 未验证 ${unverifiedCount}`,
          `Direct ${directProofCount} · workspace ${workspaceArtifactCount} · run artifact ${runArtifactCount} · ledger-only ${ledgerOnlyCount} · unverified ${unverifiedCount}`
        )
        : localeText("证据清单会在证据账本落账后生成。", "The evidence manifest appears after ledger claims are written.");
      const provenCount = evidenceBucketCount(snapshot, "proven");
      const weakBucketCount = evidenceBucketCount(snapshot, "weak");
      const unprovenCount = evidenceBucketCount(snapshot, "unproven");
      const blockingCount = evidenceBucketCount(snapshot, "blocking");
      const riskCount = evidenceBucketCount(snapshot, "residual_risk") || (hasBucketProjection(snapshot) ? 0 : displayCount(coverage.residual_risk_count));
      return [
        evidenceCoverageCard("裁决状态", "Verdict status", taskVerdictStatusLabel(snapshot?.task_verdict?.status), statusDetail, `${verdictAction}${traceAction}`),
        evidenceCoverageCard("已证明", "Proven", String(provenCount || coveredChecks || 0), bucketDetailText(snapshot, "proven", checkCount ? `${coveredChecks}/${checkCount}` : "")),
        evidenceCoverageCard("偏弱", "Weak", String(weakBucketCount), bucketDetailText(snapshot, "weak")),
        evidenceCoverageCard("未证明", "Unproven", String(unprovenCount), bucketDetailText(snapshot, "unproven", primaryGap?.text || "")),
        evidenceCoverageCard(
          "阻断",
          "Blocking",
          String(blockingCount),
          bucketDetailText(snapshot, "blocking", gatekeeperRefs ? localeText("守门者已引用上游证据。", "GateKeeper cited upstream evidence.") : "")
        ),
        evidenceCoverageCard("残余风险", "Residual risk", String(riskCount), bucketDetailText(snapshot, "residual_risk")),
        evidenceCoverageCard("证明强度", "Proof strength", claimCount ? `${directProofCount}/${claimCount}` : "-", proofDetail, manifestAction),
        evidenceCoverageCard(
          "判断契约",
          "Judgment contract",
          contractPath ? localeText("已冻结", "Frozen") : "-",
          judgmentContractDetail(judgmentContract),
          contractAction
        ),
      ].join("");
    }

    function evidenceOutcome(snapshot, currentRun) {
      const taskVerdict = snapshot?.task_verdict || currentRun?.task_verdict || {};
      const taskStatus = String(taskVerdict.status || "not_evaluated").toLowerCase();
      const coverage = snapshot?.evidence_coverage || {};
      const coverageStatus = String(coverage.status || "").toLowerCase();
      const weakCount = displayCount(coverage.weak_target_count);
      const missingCount = displayCount(coverage.missing_target_count);
      const blockedCount = displayCount(coverage.blocked_target_count);
      const primaryGap = Array.isArray(coverage.top_gaps) && coverage.top_gaps.length ? coverage.top_gaps[0] : null;
      if (taskStatus === "passed_with_residual_risk") {
        return {
          soft: false,
          title: taskVerdictStatusLabel(taskStatus),
          detail: taskVerdict.summary || firstBucketText(snapshot, "residual_risk") || localeText(
            "Loop 裁决已通过，但仍保留可见且已接受的残余风险。",
            "The task verdict passed, with accepted residual risk still visible."
          ),
        };
      }
      if (taskStatus === "passed") {
        return {
          soft: true,
          title: taskVerdictStatusLabel(taskStatus),
          detail: taskVerdict.summary || localeText(
            "Loop 裁决由证据桶支撑；可继续查看已证明 / 残余风险的明细。",
            "The task verdict is backed by evidence buckets; inspect proven and residual-risk details as needed."
          ),
        };
      }
      if (taskStatus === "failed" || ["blocked", "partial"].includes(coverageStatus) || blockedCount > 0 || missingCount > 0) {
        return {
          soft: false,
          title: taskVerdictStatusLabel(taskStatus === "failed" ? "failed" : "insufficient_evidence"),
          detail: taskVerdict.summary || firstBucketText(snapshot, "blocking", "unproven", "weak") || primaryGap?.text || localeText(
            "守门裁决、证据缺口和阻塞项已保留在本次运行的证据材料里。",
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
          "角色交接、证据账本或 GateKeeper 裁决写出后，这里会收敛成证据结论。",
          "Once role handoffs, the evidence ledger, or the GateKeeper verdict lands, this will settle into an evidence outcome."
        ),
      };
    }

    function takeawayIterationMeta(iteration, snapshot) {
      const bits = [];
      if (iteration?.composite_score !== null && iteration?.composite_score !== undefined) {
        bits.push(localeText(`综合分 ${formatScore(iteration.composite_score)}`, `Composite ${formatScore(iteration.composite_score)}`));
      }
      const evidenceProgressMode = String(iteration?.evidence_progress_mode || "none");
      const coveredChecks = displayCount(iteration?.covered_check_count);
      const missingChecks = displayCount(iteration?.missing_check_count);
      const noCoverageDelta = displayCount(iteration?.consecutive_no_required_coverage_delta);
      if (evidenceProgressMode !== "none") {
        bits.push(localeText("证据进展停滞", "Evidence progress stalled"));
      }
      if (coveredChecks || missingChecks) {
        bits.push(localeText(`覆盖 ${coveredChecks} 已证明 / ${missingChecks} 缺口`, `Coverage ${coveredChecks} covered / ${missingChecks} missing`));
      }
      if (noCoverageDelta > 0) {
        bits.push(localeText(`${noCoverageDelta} 轮无新增覆盖`, `${noCoverageDelta} no-coverage-delta iter${noCoverageDelta === 1 ? "" : "s"}`));
      }
      const roleCount = displayCount(iteration?.role_count);
      if (roleCount) {
        bits.push(localeText(`${roleCount} 条角色结论`, `${roleCount} role conclusion${roleCount === 1 ? "" : "s"}`));
      }
      const evidenceCount = displayCount(snapshot?.evidence_count);
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
      const displayIter = displayCount(iteration?.display_iter, 1);
      const bits = [localeText(`第 ${displayIter} 轮`, `Iter ${displayIter}`)];
      const statusLabel = takeawayStatusLabel(iteration?.status);
      if (statusLabel) {
        bits.push(statusLabel);
      }
      const roleCount = displayCount(iteration?.role_count);
      if (roleCount) {
        bits.push(
          localeText(
            `${roleCount} 条角色结论`,
            `${roleCount} role conclusion${roleCount === 1 ? "" : "s"}`
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
      const displayIter = displayCount(iteration?.display_iter, 1);
      return `
        <article class="takeaway-iteration-card takeaway-iteration-card--${escapeHtml(iteration.status || "pending")}">
          <div class="takeaway-iteration-head">
            <div class="takeaway-iteration-copy">
              <span class="takeaway-iteration-label">${escapeHtml(localeText(`第 ${displayIter} 轮`, `Iter ${displayIter}`))}</span>
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
                      <span class="takeaway-role-order">${escapeHtml(String(displayCount(role.step_order) + 1).padStart(2, "0"))}</span>
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
      const latestIter = nonNegativeInteger(snapshot?.latest_display_iter);
      const roleCount = displayCount(snapshot?.role_conclusion_count);
      const evidenceCount = displayCount(snapshot?.evidence_count);
      return latestIter
        ? localeText(
          `最近到第 ${latestIter} 轮 · ${roleCount} 条角色结论 · ${evidenceCount} 条证据`,
          `Up to iter ${latestIter} · ${roleCount} role conclusions · ${evidenceCount} evidence items`
        )
        : localeText("角色交接写出来后，这里会自动更新。", "This updates as soon as the first role handoff lands.");
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
