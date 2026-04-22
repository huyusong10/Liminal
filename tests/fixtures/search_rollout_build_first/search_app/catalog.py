from __future__ import annotations

HELP_CENTER_DOCS = [
    {
        "id": "hc_rotate_personal_token",
        "title": "Rotate personal access token",
        "body": "Open Settings, choose Personal access tokens, create a new token, test it, then revoke the old one.",
        "tags": ["tokens", "access", "credentials"],
        "visibility": "public",
        "domain": "help_center",
    },
    {
        "id": "hc_saml_domain_claim",
        "title": "Verify your SAML sign-in domain",
        "body": "Upload the new verification record, wait for propagation, then confirm the domain in the SAML settings panel.",
        "tags": ["saml", "sso", "domain"],
        "visibility": "public",
        "domain": "help_center",
    },
    {
        "id": "hc_billing_export_csv",
        "title": "Export billing history as CSV",
        "body": "Go to Billing history, choose a date range, and export the invoice and payment rows as a CSV file.",
        "tags": ["billing", "csv", "export"],
        "visibility": "public",
        "domain": "help_center",
    },
    {
        "id": "hc_search_permissions_runbook",
        "title": "Search permission rollout checklist",
        "body": "Internal checklist for shadow rollout: keep employee-only scoring rules out of the public help-center slice.",
        "tags": ["search", "permissions", "rollout"],
        "visibility": "employee",
        "domain": "help_center",
    },
]
