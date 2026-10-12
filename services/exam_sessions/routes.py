from fastapi import APIRouter

from services.web.models import SubmitRequest
from .models import ExamContext, ExamStartRequest


def build_router(workbench):
    """Mount below the web router so its shared authentication dependencies apply."""
    router = APIRouter(prefix='/exam', tags=['服务端计时模考'])
    service = workbench.exam_sessions

    @router.post('/start')
    def start(req: ExamStartRequest):
        return service.start(req)

    @router.post('/latest')
    def latest(req: ExamContext):
        return service.latest(req)

    @router.post('/{session_id}/state')
    def state(session_id: str, req: ExamContext):
        return service.state(session_id, req)

    @router.post('/{session_id}/advance')
    def advance(session_id: str, req: ExamContext):
        return service.advance(session_id, req)

    @router.post('/{session_id}/submit')
    def submit(session_id: str, req: SubmitRequest):
        return service.submit(session_id, req)

    @router.post('/{session_id}/finish')
    def finish(session_id: str, req: ExamContext):
        return service.finish(session_id, req)

    return router
