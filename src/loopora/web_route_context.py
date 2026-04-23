from __future__ import annotations

from loopora.web_route_context_base import WebRouteContextBase
from loopora.web_route_context_help_pages import WebRouteHelpPagesMixin
from loopora.web_route_context_loop_pages import WebRouteLoopPagesMixin
from loopora.web_route_context_role_pages import WebRouteRolePagesMixin


class WebRouteContext(
    WebRouteLoopPagesMixin,
    WebRouteRolePagesMixin,
    WebRouteHelpPagesMixin,
    WebRouteContextBase,
):
    """Aggregate page/rendering context for web route registration."""
