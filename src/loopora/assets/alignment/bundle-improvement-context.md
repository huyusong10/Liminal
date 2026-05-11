## Bundle Improvement Context

This alignment session starts from a user-selected Loopora source. Help the user improve the candidate bundle through dialogue, but do not present this as a required product lifecycle stage.

- Source type: {{source_type}}
- Source alignment session id: {{source_alignment_session_id}}
- Source bundle id: {{source_bundle_id}}
- Source loop id: {{source_loop_id}}
- Source run id: {{source_run_id}}
- Source run status: {{run_status}}
- Source completion mode: {{source_completion_mode}}
- Reason: {{reason}}

Rules:
- Treat the Current Bundle as the base candidate.
- Do not merely polish wording. Identify which governance surface should change: `spec`, `roles`, `workflow`, evidence expectations, or GateKeeper strictness.
- The working agreement must name both sides of the improvement: what stable source intent / workdir / executor defaults / useful role posture should be preserved, and what feedback-driven delta should change.
- Encode the improvement delta in existing readiness evidence: `task_scope` should state preserved scope plus revision boundary, `evidence_preferences` should state source or run evidence to trust, `role_posture` / `workflow_shape` should name which governance surface changes and which stays stable.
- If the source completion mode is not `gatekeeper`, treat the move to evidence-backed GateKeeper task verdicts as an explicit governance delta. Do not silently describe that as preserving the source completion behavior.
- The improved bundle should remain a complete standalone bundle. Prefer leaving `metadata.bundle_id` empty or new; never reuse the source bundle id as the candidate `bundle_id`. Do not set `metadata.source_bundle_id` or `metadata.revision`.
- If run evidence is present, cite it in reasoning and translate it into bundle changes, not just code advice.
- This is an optional Web capability for user-directed improvement. Do not describe it as Loopora's required lifecycle or as a built-in stage after every run.

Artifact paths:
```json
{{artifact_paths_json}}
```

Coverage summary:
```json
{{coverage_summary_json}}
```

Task verdict:
```json
{{task_verdict_json}}
```

Recent evidence summary:
```json
{{evidence_summary_json}}
```

GateKeeper verdict:
```json
{{gatekeeper_verdict_json}}
```
