"""Parent web router supplies runtime authentication."""
from fastapi import APIRouter
from services.learning.models import (DiagnosticStartRequest, DiagnosticResultRequest,
                                      InterviewAnswerRequest, InterviewStartRequest,
                                      PlanCreateRequest, PlanReplanRequest, TaskRequest)
from services.learning.workflow import LearningWorkflow
from services.web.models import WebContext


def build_router(workbench):
    flow = LearningWorkflow(workbench)
    router = APIRouter(prefix='/learning', tags=['learning'])

    @router.post('/diagnostic/start')
    def diagnostic_start(req: DiagnosticStartRequest):
        return flow.start_diagnostic(req)

    @router.post('/diagnostic/result')
    def diagnostic_result(req: DiagnosticResultRequest):
        return flow.diagnostic_result(req)

    @router.post('/plan')
    def create_plan(req: PlanCreateRequest):
        return flow.create_plan(req)

    @router.post('/plan/current')
    def current_plan(req: WebContext):
        return flow.current_plan(req)

    @router.post('/plan/replan')
    def replan(req: PlanReplanRequest):
        return flow.replan(req)

    @router.post('/task/start')
    def start_task(req: TaskRequest):
        return flow.start_task(req)

    @router.post('/task/complete')
    def complete_task(req: TaskRequest):
        return flow.complete_task(req)

    @router.post('/interview/session')
    def interview_start(req: InterviewStartRequest):
        return flow.interview.start(req)

    @router.post('/interview/session/current')
    def interview_current(req: WebContext):
        return flow.interview.current(req)

    @router.post('/interview/session/answer')
    def interview_answer(req: InterviewAnswerRequest):
        return flow.interview.answer(req)

    return router
