from __future__ import annotations

import re

from loopora.specs import SpecError, compile_markdown_spec
from loopora.structured_booleans import structured_bool_is_true


def preview_list_items(markdown_text: str, *, limit: int = 4) -> list[str]:
    items = []
    for line in str(markdown_text or "").splitlines():
        cleaned = re.sub(r"^\s*[-*]\s+", "", line).strip()
        cleaned = re.sub(r"^\s*\d+[.)]\s+", "", cleaned).strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        items.append(cleaned)
        if len(items) >= limit:
            break
    if items:
        return items
    compact = re.sub(r"\s+", " ", str(markdown_text or "")).strip()
    return [compact[:180]] if compact else []


def build_bundle_control_summary(bundle: dict) -> dict:
    compiled_spec = _compile_bundle_spec(bundle)
    raw_sections = _raw_sections(compiled_spec)
    roles = list(bundle.get("role_definitions") or [])
    workflow = dict(bundle.get("workflow") or {})
    steps = list(workflow.get("steps") or [])
    role_lookup = _role_lookup(roles=roles, workflow_roles=list(workflow.get("roles") or []))
    workflow_projection = _workflow_projection(steps, role_lookup)
    gatekeeper = _gatekeeper_projection(steps, role_lookup)
    controls = _control_summaries(workflow, role_lookup)
    traceability = _traceability_projection(
        {
            "bundle": bundle,
            "raw_sections": raw_sections,
            "roles": roles,
            "workflow": workflow,
            "workflow_projection": workflow_projection,
            "gatekeeper": gatekeeper,
            "controls": controls,
        }
    )
    diagnostics = _diagnostics_projection(
        bundle=bundle,
        steps=steps,
        role_lookup=role_lookup,
        traceability=traceability,
    )

    return {
        "risks": preview_list_items(
            str(raw_sections.get("Fake Done") or "") + "\n" + str(raw_sections.get("Residual Risk") or ""),
            limit=4,
        ),
        "evidence": _evidence_titles(compiled_spec),
        "workflow": workflow_projection,
        "gatekeeper": gatekeeper,
        "traceability": traceability,
        "diagnostics": diagnostics,
        "controls": controls,
    }


def _compile_bundle_spec(bundle: dict) -> dict:
    try:
        compiled_spec = compile_markdown_spec(str(bundle.get("spec", {}).get("markdown") or ""))
    except SpecError:
        return {"raw_sections": {}}
    return compiled_spec if isinstance(compiled_spec, dict) else {"raw_sections": {}}


def _raw_sections(compiled_spec: dict) -> dict:
    raw_sections = compiled_spec.get("raw_sections")
    return raw_sections if isinstance(raw_sections, dict) else {}


def _evidence_titles(compiled_spec: dict) -> list[str]:
    return [
        str(check.get("title") or "").strip()
        for check in list(compiled_spec.get("checks") or [])[:4]
        if isinstance(check, dict) and str(check.get("title") or "").strip()
    ]


def _role_lookup(*, roles: list[dict], workflow_roles: list[dict]) -> dict:
    role_definition_by_key = {str(role.get("key") or ""): role for role in roles if isinstance(role, dict)}
    workflow_role_by_id = {
        str(role.get("id") or ""): role
        for role in workflow_roles
        if isinstance(role, dict) and str(role.get("id") or "").strip()
    }
    return {
        "role_definition_by_key": role_definition_by_key,
        "workflow_role_by_id": workflow_role_by_id,
    }


def _role_for_step(step: dict, role_lookup: dict) -> dict:
    workflow_role = role_lookup["workflow_role_by_id"].get(str(step.get("role_id") or ""), {})
    return role_lookup["role_definition_by_key"].get(str(workflow_role.get("role_definition_key") or ""), {})


def _step_label(step: dict, role_lookup: dict) -> str:
    role = _role_for_step(step, role_lookup)
    return str(role.get("name") or step.get("role_id") or step.get("id") or "").strip()


def _workflow_projection(steps: list[dict], role_lookup: dict) -> dict:
    return {
        "step_count": len(steps),
        "parallel_groups": _parallel_groups(steps),
        "summary": " -> ".join(item for item in _grouped_step_labels(steps, role_lookup) if item),
    }


def _parallel_groups(steps: list[dict]) -> list[str]:
    return sorted(
        {
            str(step.get("parallel_group") or "").strip()
            for step in steps
            if str(step.get("parallel_group") or "").strip()
        }
    )


def _grouped_step_labels(steps: list[dict], role_lookup: dict) -> list[str]:
    grouped_steps: list[str] = []
    index = 0
    while index < len(steps):
        step = steps[index]
        group = str(step.get("parallel_group") or "").strip()
        if group:
            grouped = []
            while index < len(steps) and str(steps[index].get("parallel_group") or "").strip() == group:
                grouped.append(_step_label(steps[index], role_lookup))
                index += 1
            grouped_steps.append("[" + " + ".join(item for item in grouped if item) + "]")
            continue
        grouped_steps.append(_step_label(step, role_lookup))
        index += 1
    return grouped_steps


def _gatekeeper_projection(steps: list[dict], role_lookup: dict) -> dict:
    gatekeeper_steps = [
        step
        for step in steps
        if str(_role_for_step(step, role_lookup).get("archetype") or "").strip().lower() == "gatekeeper"
    ]
    return {
        "enabled": bool(gatekeeper_steps),
        "roles": _gatekeeper_role_names(gatekeeper_steps, role_lookup),
        "finish_steps": [
            str(step.get("id") or "").strip()
            for step in gatekeeper_steps
            if str(step.get("on_pass") or "").strip() == "finish_run"
        ],
        "requires_evidence_refs": True,
    }


def _gatekeeper_role_names(gatekeeper_steps: list[dict], role_lookup: dict) -> list[str]:
    gatekeeper_roles = []
    for step in gatekeeper_steps:
        role_name = _step_label(step, role_lookup)
        if role_name and role_name not in gatekeeper_roles:
            gatekeeper_roles.append(role_name)
    return gatekeeper_roles


def _control_summaries(workflow: dict, role_lookup: dict) -> list[dict]:
    control_summaries = []
    for control in list(workflow.get("controls") or []):
        if not isinstance(control, dict):
            continue
        role_id = str((control.get("call") or {}).get("role_id") or "").strip()
        workflow_role = role_lookup["workflow_role_by_id"].get(role_id, {})
        role_definition = role_lookup["role_definition_by_key"].get(str(workflow_role.get("role_definition_key") or ""), {})
        control_summaries.append(
            {
                "id": str(control.get("id") or "").strip(),
                "signal": str((control.get("when") or {}).get("signal") or "").strip(),
                "after": str((control.get("when") or {}).get("after") or "").strip(),
                "role_id": role_id,
                "role_name": str(role_definition.get("name") or role_id).strip(),
                "role_archetype": str(role_definition.get("archetype") or "").strip(),
                "mode": str(control.get("mode") or "").strip(),
                "max_fires_per_run": _control_max_fires_per_run(control.get("max_fires_per_run")),
            }
        )
    return control_summaries


def _control_max_fires_per_run(value: object) -> int | str:
    if value is None or value == "":
        return 1
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _traceability_projection(context: dict) -> dict:
    bundle = dict(context.get("bundle") or {})
    raw_sections = dict(context.get("raw_sections") or {})
    roles = list(context.get("roles") or [])
    workflow = dict(context.get("workflow") or {})
    workflow_projection = dict(context.get("workflow_projection") or {})
    gatekeeper = dict(context.get("gatekeeper") or {})
    controls = list(context.get("controls") or [])
    items: list[dict] = []
    collaboration_summary = str(bundle.get("collaboration_summary") or "").strip()
    _append_trace_item(
        items,
        key="collaboration_story",
        label="Collaboration story",
        surfaces=["collaboration_summary"],
        evidence=preview_list_items(collaboration_summary, limit=2),
    )
    _append_trace_item(
        items,
        key="task_scope",
        label="Task scope",
        surfaces=["spec.markdown#Task"],
        evidence=preview_list_items(str(raw_sections.get("Task") or ""), limit=2),
    )
    _append_trace_item(
        items,
        key="success_surface",
        label="Success surface",
        surfaces=["spec.markdown#Done When", "spec.markdown#Success Surface"],
        evidence=preview_list_items(
            str(raw_sections.get("Done When") or "") + "\n" + str(raw_sections.get("Success Surface") or ""),
            limit=3,
        ),
    )
    _append_trace_item(
        items,
        key="fake_done_risks",
        label="Fake done risks",
        surfaces=["spec.markdown#Fake Done"],
        evidence=preview_list_items(str(raw_sections.get("Fake Done") or ""), limit=3),
    )
    _append_trace_item(
        items,
        key="evidence_preferences",
        label="Evidence preferences",
        surfaces=["spec.markdown#Evidence Preferences"],
        evidence=preview_list_items(str(raw_sections.get("Evidence Preferences") or ""), limit=3),
    )
    _append_trace_item(
        items,
        key="residual_risk_policy",
        label="Residual risk policy",
        surfaces=["spec.markdown#Residual Risk"],
        evidence=preview_list_items(str(raw_sections.get("Residual Risk") or ""), limit=2),
    )
    _append_trace_item(
        items,
        key="role_posture",
        label="Role posture",
        surfaces=["role_definitions[].prompt_markdown", "role_definitions[].posture_notes"],
        evidence=_role_posture_trace(roles),
    )
    _append_trace_item(
        items,
        key="workflow_judgment",
        label="Workflow judgment",
        surfaces=["workflow.collaboration_intent", "workflow.steps[].inputs"],
        evidence=_workflow_trace(workflow, workflow_projection),
    )
    _append_trace_item(
        items,
        key="gatekeeper_closure",
        label="GateKeeper closure",
        surfaces=["workflow.steps[].on_pass", "workflow.steps[].inputs.evidence_query"],
        evidence=_gatekeeper_trace(gatekeeper),
    )
    if controls:
        _append_trace_item(
            items,
            key="runtime_controls",
            label="Runtime controls",
            surfaces=["workflow.controls[]"],
            evidence=_control_trace(controls),
        )

    mapped_items = [item for item in items if item["mapped"]]
    return {
        "items": items,
        "mapped_count": len(mapped_items),
        "required_count": len(items),
        "missing": [item["key"] for item in items if not item["mapped"]],
        "surfaces": sorted({surface for item in mapped_items for surface in item["surfaces"]}),
    }


def _append_trace_item(
    items: list[dict],
    *,
    key: str,
    label: str,
    surfaces: list[str],
    evidence: list[str],
) -> None:
    cleaned_evidence = [str(item).strip() for item in evidence if str(item).strip()]
    items.append(
        {
            "key": key,
            "label": label,
            "surfaces": surfaces,
            "evidence": cleaned_evidence[:4],
            "mapped": bool(cleaned_evidence),
        }
    )


def _role_posture_trace(roles: list[dict]) -> list[str]:
    traces: list[str] = []
    for role in roles:
        if not isinstance(role, dict):
            continue
        role_name = str(role.get("name") or role.get("key") or "").strip()
        archetype = str(role.get("archetype") or "").strip()
        posture = preview_list_items(str(role.get("posture_notes") or role.get("description") or ""), limit=1)
        if role_name or archetype:
            base = f"{role_name or 'Role'} ({archetype or 'custom'})"
            traces.append(f"{base}: {posture[0]}" if posture else base)
    return traces[:4]


def _workflow_trace(workflow: dict, workflow_projection: dict) -> list[str]:
    traces = preview_list_items(str(workflow.get("collaboration_intent") or ""), limit=2)
    summary = str(workflow_projection.get("summary") or "").strip()
    if summary:
        traces.append(summary)
    return traces[:4]


def _gatekeeper_trace(gatekeeper: dict) -> list[str]:
    if not structured_bool_is_true(gatekeeper.get("enabled")):
        return []
    roles = ", ".join(str(item) for item in gatekeeper.get("roles") or [] if str(item).strip())
    finish_steps = ", ".join(str(item) for item in gatekeeper.get("finish_steps") or [] if str(item).strip())
    trace = "GateKeeper"
    if roles:
        trace = f"{trace}: {roles}"
    if finish_steps:
        trace = f"{trace}; finish steps: {finish_steps}"
    return [trace]


def _control_trace(controls: list[dict]) -> list[str]:
    traces: list[str] = []
    for control in controls:
        control_id = str(control.get("id") or "").strip()
        signal = str(control.get("signal") or "").strip()
        role_name = str(control.get("role_name") or control.get("role_id") or "").strip()
        traces.append(f"{control_id or 'control'}: {signal or 'signal'} -> {role_name or 'role'}")
    return traces[:4]


def _diagnostics_projection(
    *,
    bundle: dict,
    steps: list[dict],
    role_lookup: dict,
    traceability: dict,
) -> list[dict]:
    diagnostics: list[dict] = []
    _append_traceability_diagnostics(diagnostics, traceability)
    _append_completion_mode_diagnostics(diagnostics, bundle)
    _append_workflow_input_diagnostics(diagnostics, steps, role_lookup)
    return diagnostics


def _append_traceability_diagnostics(diagnostics: list[dict], traceability: dict) -> None:
    missing = [str(item).strip() for item in list(traceability.get("missing") or []) if str(item).strip()]
    if not missing:
        return
    _append_diagnostic(
        diagnostics,
        {
            "code": "traceability_missing",
            "severity": "warning",
            "title_en": "Judgment projection is incomplete",
            "title_zh": "判断投影不完整",
            "message_en": "Some confirmed judgment areas do not map to a runnable bundle surface.",
            "message_zh": "部分已确认判断没有映射到可运行的方案表面。",
            "surfaces": ["collaboration_summary", "spec.markdown", "role_definitions[]", "workflow"],
            "details": {"missing": missing},
        },
    )


def _append_completion_mode_diagnostics(diagnostics: list[dict], bundle: dict) -> None:
    completion_mode = str((bundle.get("loop") or {}).get("completion_mode") or "").strip().lower()
    if completion_mode == "gatekeeper":
        return
    _append_diagnostic(
        diagnostics,
        {
            "code": "completion_not_gatekeeper",
            "severity": "info",
            "title_en": "Run closes without evidence-backed GateKeeper mode",
            "title_zh": "运行不是由证据守门模式收束",
            "message_en": "Expert bundles may use this, but the task verdict will lean more on runtime lifecycle than GateKeeper evidence closure.",
            "message_zh": "专家方案可以这样运行，但任务裁决会更依赖运行生命周期，而不是 GateKeeper 的证据收口。",
            "surfaces": ["loop.completion_mode"],
        },
    )


def _append_workflow_input_diagnostics(
    diagnostics: list[dict],
    steps: list[dict],
    role_lookup: dict,
) -> None:
    state = {
        "prior_step_ids": [],
        "prior_archetypes": set(),
        "latest_builder_step": "",
        "review_steps_since_builder": [],
        "guide_steps_since_builder": [],
        "parallel_review_groups": [],
    }
    for step in steps:
        step_context = _workflow_step_diagnostic_context(step, role_lookup)
        _diagnose_guide_step(diagnostics, step_context, state)
        _diagnose_review_step(diagnostics, step_context, state)
        _diagnose_builder_step(diagnostics, step_context, state)
        _diagnose_gatekeeper_step(diagnostics, step_context, state)
        _advance_workflow_diagnostic_state(step_context, state)


def _workflow_step_diagnostic_context(step: dict, role_lookup: dict) -> dict:
    return {
        "step": step,
        "step_id": str(step.get("id") or "").strip(),
        "archetype": str(_role_for_step(step, role_lookup).get("archetype") or "").strip().lower(),
        "inputs": step.get("inputs") if isinstance(step.get("inputs"), dict) else {},
        "on_pass": str(step.get("on_pass") or "").strip(),
    }


def _diagnose_guide_step(diagnostics: list[dict], step_context: dict, state: dict) -> None:
    if step_context["archetype"] != "guide" or not state["prior_step_ids"]:
        return
    state["guide_steps_since_builder"].append(step_context["step_id"])
    if not _input_names_any_handoff(step_context["inputs"], state["prior_step_ids"]):
        _append_diagnostic(
            diagnostics,
            {
                "code": "guide_missing_upstream_handoff",
                "severity": "warning",
                "title_en": "Guide does not read upstream handoff",
                "title_zh": "Guide 没有读取上游交接",
                "message_en": "An explicit Guide step should be grounded in the handoff it is redirecting, not only in latent chat context.",
                "message_zh": "显式 Guide 步骤应读取它要重定向的上游 handoff，而不是只依赖隐含上下文。",
                "surfaces": ["workflow.steps[].inputs.handoffs_from"],
                "step_ids": [step_context["step_id"]],
            },
        )
    if not _input_queries_any_archetype(step_context["inputs"], state["prior_archetypes"]):
        _append_diagnostic(
            diagnostics,
            {
                "code": "guide_missing_upstream_evidence",
                "severity": "warning",
                "title_en": "Guide does not query upstream evidence",
                "title_zh": "Guide 没有查询上游证据",
                "message_en": "A Guide can be a normal workflow step, but it should read the evidence behind the gap or shift.",
                "message_zh": "Guide 可以是普通工作流步骤，但应读取造成缺口或转向的证据。",
                "surfaces": ["workflow.steps[].inputs.evidence_query"],
                "step_ids": [step_context["step_id"]],
            },
        )


def _diagnose_review_step(diagnostics: list[dict], step_context: dict, state: dict) -> None:
    if step_context["archetype"] not in {"inspector", "custom"} or not state["latest_builder_step"]:
        return
    if not _input_names_any_handoff(step_context["inputs"], [state["latest_builder_step"]]):
        _append_diagnostic(
            diagnostics,
            {
                "code": "review_missing_builder_handoff",
                "severity": "warning",
                "title_en": "Review step does not read Builder handoff",
                "title_zh": "检视步骤没有读取 Builder 交接",
                "message_en": "A review after Builder should consume the Builder handoff so the evidence checks the actual produced slice.",
                "message_zh": "Builder 之后的检视应读取 Builder handoff，确保取证针对真实产出。",
                "surfaces": ["workflow.steps[].inputs.handoffs_from"],
                "step_ids": [step_context["step_id"]],
            },
        )
    if not _input_queries_any_archetype(step_context["inputs"], {"builder"}):
        _append_diagnostic(
            diagnostics,
            {
                "code": "review_missing_builder_evidence",
                "severity": "warning",
                "title_en": "Review step does not query Builder evidence",
                "title_zh": "检视步骤没有查询 Builder 证据",
                "message_en": "Without a Builder evidence query, review can drift into general advice instead of proof checking.",
                "message_zh": "缺少 Builder evidence query 时，检视容易变成泛泛建议，而不是证明检查。",
                "surfaces": ["workflow.steps[].inputs.evidence_query"],
                "step_ids": [step_context["step_id"]],
            },
        )
    state["review_steps_since_builder"].append(step_context["step_id"])


def _diagnose_builder_step(diagnostics: list[dict], step_context: dict, state: dict) -> None:
    if step_context["archetype"] != "builder":
        return
    if state["guide_steps_since_builder"] and not _input_names_any_handoff(step_context["inputs"], state["guide_steps_since_builder"]):
        _append_diagnostic(
            diagnostics,
            {
                "code": "builder_missing_guide_handoff",
                "severity": "warning",
                "title_en": "Builder after Guide does not read Guide handoff",
                "title_zh": "Guide 后的 Builder 没有读取 Guide 交接",
                "message_en": "A Builder that follows explicit guidance should consume the Guide handoff that narrowed the next move.",
                "message_zh": "跟在显式 Guide 后面的 Builder 应读取 Guide handoff，承接被收窄的下一步。",
                "surfaces": ["workflow.steps[].inputs.handoffs_from"],
                "step_ids": [step_context["step_id"]],
            },
        )
    if state["review_steps_since_builder"] and not _input_names_any_handoff(step_context["inputs"], state["review_steps_since_builder"]):
        _append_diagnostic(
            diagnostics,
            {
                "code": "builder_missing_review_handoff",
                "severity": "warning",
                "title_en": "Builder after review does not read review handoff",
                "title_zh": "检视后的 Builder 没有读取检视交接",
                "message_en": "Repair or second-phase Builder steps should consume the review or Guide handoff that shaped the next move.",
                "message_zh": "修复或第二阶段 Builder 应读取塑造下一步的检视或 Guide handoff。",
                "surfaces": ["workflow.steps[].inputs.handoffs_from"],
                "step_ids": [step_context["step_id"]],
            },
        )
    state["latest_builder_step"] = step_context["step_id"]
    state["review_steps_since_builder"] = []
    state["guide_steps_since_builder"] = []


def _diagnose_gatekeeper_step(diagnostics: list[dict], step_context: dict, state: dict) -> None:
    if step_context["archetype"] != "gatekeeper" or step_context["on_pass"] != "finish_run":
        return
    if state["prior_step_ids"] and not _input_names_any_handoff(step_context["inputs"], state["prior_step_ids"]):
        _append_diagnostic(
            diagnostics,
            {
                "code": "gatekeeper_missing_handoff_fan_in",
                "severity": "warning",
                "title_en": "GateKeeper lacks handoff fan-in",
                "title_zh": "GateKeeper 缺少 handoff 汇入",
                "message_en": "A finishing GateKeeper should name upstream handoffs so the final verdict is traceable.",
                "message_zh": "负责收束的 GateKeeper 应明确读取上游 handoff，让最终裁决可追溯。",
                "surfaces": ["workflow.steps[].inputs.handoffs_from"],
                "step_ids": [step_context["step_id"]],
            },
        )
    if not _input_queries_any_archetype(step_context["inputs"], state["prior_archetypes"]):
        _append_diagnostic(
            diagnostics,
            {
                "code": "gatekeeper_missing_evidence_fan_in",
                "severity": "warning",
                "title_en": "GateKeeper lacks evidence fan-in",
                "title_zh": "GateKeeper 缺少证据汇入",
                "message_en": "A finishing GateKeeper should query upstream evidence instead of judging from role narrative alone.",
                "message_zh": "负责收束的 GateKeeper 应查询上游 evidence，而不是只看角色叙述。",
                "surfaces": ["workflow.steps[].inputs.evidence_query"],
                "step_ids": [step_context["step_id"]],
            },
        )
    _diagnose_gatekeeper_parallel_review_fan_in(diagnostics, step_context, state)


def _advance_workflow_diagnostic_state(step_context: dict, state: dict) -> None:
    _record_parallel_review_group(step_context, state)
    if step_context["step_id"]:
        state["prior_step_ids"].append(step_context["step_id"])
    if step_context["archetype"]:
        state["prior_archetypes"].add(step_context["archetype"])


def _diagnose_gatekeeper_parallel_review_fan_in(diagnostics: list[dict], step_context: dict, state: dict) -> None:
    groups = [group for group in list(state.get("parallel_review_groups") or []) if group.get("step_ids")]
    if not groups:
        return
    parallel_step_ids = _unique_in_order(
        step_id
        for group in groups
        for step_id in list(group.get("step_ids") or [])
    )
    missing_handoffs = _input_missing_handoffs(step_context["inputs"], parallel_step_ids)
    if missing_handoffs:
        _append_diagnostic(
            diagnostics,
            {
                "code": "gatekeeper_missing_parallel_review_handoff",
                "severity": "warning",
                "title_en": "GateKeeper misses parallel review handoffs",
                "title_zh": "GateKeeper 缺少并行检视交接",
                "message_en": "A finishing GateKeeper after parallel review should name every peer review handoff, not only the last branch.",
                "message_zh": "并行检视后的收束 GateKeeper 应读取每条 peer review handoff，而不是只读取最后一支。",
                "surfaces": ["workflow.steps[].inputs.handoffs_from"],
                "step_ids": [step_context["step_id"]],
                "details": {"missing_handoffs": missing_handoffs, "parallel_groups": [group["parallel_group"] for group in groups]},
            },
        )
    expected_archetypes = {
        archetype
        for group in groups
        for archetype in set(group.get("archetypes") or set())
        if archetype
    }
    if "builder" in set(state.get("prior_archetypes") or set()):
        expected_archetypes.add("builder")
    missing_archetypes = _input_missing_evidence_archetypes(step_context["inputs"], expected_archetypes)
    if missing_archetypes:
        _append_diagnostic(
            diagnostics,
            {
                "code": "gatekeeper_missing_parallel_review_evidence",
                "severity": "warning",
                "title_en": "GateKeeper misses parallel review evidence",
                "title_zh": "GateKeeper 缺少并行检视证据",
                "message_en": "A finishing GateKeeper after parallel review should query Builder and peer review evidence before closing.",
                "message_zh": "并行检视后的收束 GateKeeper 应查询 Builder 和 peer review 证据后再收口。",
                "surfaces": ["workflow.steps[].inputs.evidence_query"],
                "step_ids": [step_context["step_id"]],
                "details": {"missing_archetypes": missing_archetypes, "parallel_groups": [group["parallel_group"] for group in groups]},
            },
        )


def _record_parallel_review_group(step_context: dict, state: dict) -> None:
    parallel_group = str(step_context["step"].get("parallel_group") or "").strip()
    if not parallel_group or step_context["archetype"] not in {"inspector", "custom"} or not step_context["step_id"]:
        return
    groups = list(state.get("parallel_review_groups") or [])
    group = next((item for item in groups if item.get("parallel_group") == parallel_group), None)
    if group is None:
        group = {"parallel_group": parallel_group, "step_ids": [], "archetypes": set()}
        groups.append(group)
        state["parallel_review_groups"] = groups
    group["step_ids"].append(step_context["step_id"])
    group["archetypes"].add(step_context["archetype"])


def _unique_in_order(values) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _input_missing_handoffs(inputs: dict, expected_step_ids: list[str]) -> list[str]:
    actual = _input_handoff_ids(inputs)
    return [step_id for step_id in expected_step_ids if step_id and step_id not in actual]


def _input_names_any_handoff(inputs: dict, expected_step_ids: list[str]) -> bool:
    actual = _input_handoff_ids(inputs)
    return bool(actual.intersection({item for item in expected_step_ids if item}))


def _input_handoff_ids(inputs: dict) -> set[str]:
    handoffs_from = inputs.get("handoffs_from") if isinstance(inputs, dict) else []
    return {str(item or "").strip() for item in list(handoffs_from or []) if str(item or "").strip()}


def _input_queries_any_archetype(inputs: dict, expected_archetypes: set[str]) -> bool:
    actual = _input_evidence_query_archetypes(inputs)
    expected = {item for item in expected_archetypes if item}
    return bool(actual.intersection(expected))


def _input_missing_evidence_archetypes(inputs: dict, expected_archetypes: set[str]) -> list[str]:
    actual = _input_evidence_query_archetypes(inputs)
    expected = {item for item in expected_archetypes if item}
    return sorted(expected.difference(actual))


def _input_evidence_query_archetypes(inputs: dict) -> set[str]:
    evidence_query = inputs.get("evidence_query") if isinstance(inputs, dict) else {}
    if not isinstance(evidence_query, dict):
        return set()
    return {
        str(item or "").strip().lower()
        for item in list(evidence_query.get("archetypes") or [])
        if str(item or "").strip()
    }


def _append_diagnostic(
    diagnostics: list[dict],
    spec: dict,
) -> None:
    code = str(spec.get("code") or "").strip()
    step_ids = [str(item).strip() for item in list(spec.get("step_ids") or []) if str(item).strip()]
    key = (code, tuple(step_ids or ()))
    existing_keys = {
        (str(item.get("code") or ""), tuple(item.get("step_ids") or ()))
        for item in diagnostics
        if isinstance(item, dict)
    }
    if key in existing_keys:
        return
    diagnostics.append(
        {
            "code": code,
            "severity": str(spec.get("severity") or "warning").strip(),
            "title": str(spec.get("title_en") or "").strip(),
            "title_zh": str(spec.get("title_zh") or spec.get("title_en") or "").strip(),
            "title_en": str(spec.get("title_en") or "").strip(),
            "message": str(spec.get("message_en") or "").strip(),
            "message_zh": str(spec.get("message_zh") or spec.get("message_en") or "").strip(),
            "message_en": str(spec.get("message_en") or "").strip(),
            "surfaces": [str(item).strip() for item in list(spec.get("surfaces") or []) if str(item).strip()],
            "step_ids": step_ids,
            "details": dict(spec.get("details") or {}),
        }
    )
