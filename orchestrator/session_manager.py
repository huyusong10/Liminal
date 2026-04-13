from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def new_session_id() -> str:
    return f"sess-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
