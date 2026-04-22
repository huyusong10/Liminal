from __future__ import annotations

SEARCH_DOCS = [
    {
        "id": "hc_rotate_personal_token",
        "title": "Rotate personal access token",
        "body": "Create a new token, test it, and revoke the old credential after verification.",
        "tags": ["token", "access", "credentials", "rotation"],
        "visibility": "public",
    },
    {
        "id": "hc_saml_domain_claim",
        "title": "Verify your SAML sign-in domain",
        "body": "Upload the verification record and confirm the domain inside the SAML settings panel.",
        "tags": ["saml", "sso", "domain", "verification"],
        "visibility": "public",
    },
    {
        "id": "hc_billing_export_csv",
        "title": "Export billing history as CSV",
        "body": "Choose a billing date range, then export invoice and payment history into a CSV file.",
        "tags": ["billing", "invoices", "csv", "export"],
        "visibility": "public",
    },
    {
        "id": "api_filter_parameters",
        "title": "Filter search queries by domain",
        "body": "The query API supports domain, locale, and updated_after filters for staged rollout checks.",
        "tags": ["filters", "domain", "query", "api"],
        "visibility": "public",
    },
    {
        "id": "manual_shadow_rollout_checklist",
        "title": "Shadow rollout checklist",
        "body": "Internal checklist for widening the hybrid-search rollout without exposing employee-only content.",
        "tags": ["rollout", "shadow", "permissions", "internal"],
        "visibility": "employee",
    },
]

BENCHMARK_CASES = [
    {"query": "rotate developer credential", "expected_id": "hc_rotate_personal_token", "viewer": "public"},
    {"query": "validate login domain", "expected_id": "hc_saml_domain_claim", "viewer": "public"},
    {"query": "invoice spreadsheet export", "expected_id": "hc_billing_export_csv", "viewer": "public"},
    {"query": "limit results by source type", "expected_id": "api_filter_parameters", "viewer": "public"},
]

HOLDOUT_CASES = [
    {"query": "swap developer secret", "expected_id": "hc_rotate_personal_token", "viewer": "public"},
    {"query": "confirm sso ownership record", "expected_id": "hc_saml_domain_claim", "viewer": "public"},
    {"query": "billing history comma export", "expected_id": "hc_billing_export_csv", "viewer": "public"},
    {"query": "narrow search by docs source", "expected_id": "api_filter_parameters", "viewer": "public"},
]
