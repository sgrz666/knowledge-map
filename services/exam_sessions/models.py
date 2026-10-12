from typing import Optional

from pydantic import ConfigDict, Field

from services.web.models import WebContext


class ExamStartRequest(WebContext):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(min_length=1, max_length=120)
    spec_id: Optional[str] = None


class ExamContext(WebContext):
    """No client clock or arbitrary stage index is accepted by state mutations."""
    model_config = ConfigDict(extra='forbid')
