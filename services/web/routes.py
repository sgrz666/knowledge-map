"""Authenticated web routes; FastAPI runs blocking tool/LLM work on its thread pool."""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from services.common.models import TrustTier
from services.review.queue import get_review_queue
from services.web.models import ChatRequest, ModelConfig, WebContext, WebPracticeRequest, SubmitRequest, FeedbackRequest
from services.web.provider import client_for, narrate
from services.web.service import Workbench


def build_router(auth_dependency):
    router = APIRouter(prefix='/api/v1/web', tags=['学习工作台'])
    workbench = Workbench()

    def auth(context=Depends(auth_dependency)):
        context.require(TrustTier.RESEARCH_INTERNAL)

    router.dependencies.extend([Depends(auth_dependency), Depends(auth)])

    @router.get('/bootstrap')
    def bootstrap():
        return workbench.bootstrap()

    @router.post('/model/test')
    def test_model(config: ModelConfig):
        client = client_for(config)
        model, reply = narrate(client, '请回复连接成功', {}, set(), user_id='model-connectivity')
        return {'ok': model['ok'], 'mode': model['mode'], 'message': reply or '未连接模型',
                'errors': model.get('errors', []), 'provenance': model.get('provenance', {})}

    @router.post('/chat')
    def chat(req: ChatRequest):
        return workbench.chat(req)

    @router.post('/practice')
    def practice(req: WebPracticeRequest):
        return workbench.practice(req)

    @router.post('/submit')
    def submit(req: SubmitRequest):
        return workbench.submit(req)

    @router.post('/profile')
    def profile(req: WebContext):
        return workbench.profile(req)

    @router.get('/audio/{question_id}')
    def audio(question_id: str):
        workbench.question(question_id, 'research_internal')
        path = workbench.repo.audio_path(question_id)
        if path is None:
            raise HTTPException(404, '本机没有该题绑定的音频')
        return FileResponse(path, media_type='audio/mpeg', headers={'Cache-Control': 'private'})

    @router.get('/paper/{paper_id}')
    def paper(paper_id: str, user_id: str = Query(min_length=1, max_length=100)):
        data = workbench.store.paper(user_id, paper_id)
        if data is None:
            raise HTTPException(404, '没有找到这份练习卷')
        return {'paper': data, 'submissions': workbench.store.paper_submissions(paper_id)}

    @router.post('/feedback')
    def feedback(req: FeedbackRequest):
        meta = workbench.repo.get_meta(req.question_id)
        if meta is None:
            raise HTTPException(404, '题目不在知识库内')
        row = get_review_queue().add(reason='learner_content_feedback', user_id=req.user_id,
            question_id=req.question_id, source='web_workbench', detail={
                'description': req.detail, 'review_status': meta.review_status, 'answer_status': meta.answer_status})
        return {'message': '已记录到教研待复核队列', 'entry': row}

    return router
