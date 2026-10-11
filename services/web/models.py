from typing import Literal, Optional
from urllib.parse import urlsplit
import ipaddress
from pydantic import BaseModel, Field, SecretStr, field_validator
from services.common.models import AssemblePaperRequest, TrustTier

DEFAULT_BASE_URL = 'https://api.deepseek.com'
DEFAULT_MODEL = 'deepseek-flash'


class ModelConfig(BaseModel):
    base_url: str = DEFAULT_BASE_URL
    model: str = Field(default=DEFAULT_MODEL, min_length=1, max_length=120)
    api_key: SecretStr = SecretStr('')

    @field_validator('base_url')
    @classmethod
    def https_endpoint(cls, value):
        value = value.strip().rstrip('/')
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.port not in (None, 443)):
            raise ValueError('请填写 HTTPS Base URL，不含密码、查询参数或完整 chat/completions 路径')
        if parsed.hostname.lower() in ('localhost',) or parsed.path.endswith('/chat/completions'):
            raise ValueError('请填写模型服务的公网 Base URL')
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            address = None
        if address and not address.is_global:
            raise ValueError('模型服务必须使用公网地址')
        return value


class WebContext(BaseModel):
    user_id: str = Field(default='local-learner', min_length=1, max_length=100)
    exam_type: Literal['NTCE', 'CET-4', 'CET-6'] = 'NTCE'
    school_level: Optional[str] = None
    subject: Optional[str] = None
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL


class ChatRequest(WebContext):
    message: str = Field(min_length=1, max_length=8000)
    session_id: Optional[str] = None
    question_id: Optional[str] = None
    model_config_input: Optional[ModelConfig] = None
    history: list[dict] = Field(default_factory=list, max_length=8)
    action_payload: Optional[dict] = None


class WebPracticeRequest(AssemblePaperRequest):
    item_count: int = Field(default=5, ge=1, le=100)


class SubmitRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=100)
    paper_id: str
    question_id: str
    answer: str = Field(min_length=1, max_length=12000)
    trust_tier: TrustTier = TrustTier.RESEARCH_INTERNAL
    time_spent_seconds: float = Field(default=30, ge=0, le=86400)
    option_flip_count: int = Field(default=0, ge=0, le=1000)


class FeedbackRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=100)
    question_id: str
    detail: str = Field(min_length=5, max_length=2000)
