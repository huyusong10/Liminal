from __future__ import annotations

HELP_CENTER_REVISIONS = [
    {
        "canonical_id": "hc_rotate_personal_token",
        "revision": 1,
        "updated_at": "2025-01-11",
        "title": "Reset API token",
        "body": "Open Legacy Access, reset the token, and copy the old token format into your local secrets file.",
        "visibility": "public",
    },
    {
        "canonical_id": "hc_rotate_personal_token",
        "revision": 2,
        "updated_at": "2025-03-18",
        "title": "Rotate personal access token",
        "body": "Open Settings, create a new personal access token, test it, and revoke the old token after verification.",
        "visibility": "public",
    },
    {
        "canonical_id": "hc_saml_domain_claim",
        "revision": 1,
        "updated_at": "2025-01-08",
        "title": "Claim your SSO domain",
        "body": "Upload the domain verification record and confirm the SSO claim in the identity settings page.",
        "visibility": "public",
    },
    {
        "canonical_id": "hc_saml_domain_claim",
        "revision": 2,
        "updated_at": "2025-03-21",
        "title": "Verify your SAML sign-in domain",
        "body": "Upload the new verification record, wait for propagation, then confirm the domain in the SAML settings panel.",
        "visibility": "public",
    },
]


def pick_current_revision(rows: list[dict]) -> dict:
    """Pick the version that should reach the shadow index.

    Shadow traffic is currently regressing on freshness-sensitive queries. The
    regression is somewhere in the early pipeline: ingestion, revision
    selection, indexing, or query serving.
    """

    return sorted(rows, key=lambda item: item["updated_at"])[0]
