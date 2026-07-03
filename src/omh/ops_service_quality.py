from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from workflows.ops_service_quality import *  # noqa: F401,F403
else:
    from omh.workflows.ops_service_quality import *  # noqa: F401,F403
