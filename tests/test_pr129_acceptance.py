"""Retained positive probes from the independent PR129 audit.

Defect-expecting probes are preserved in .audit/pr129 and superseded by the
mentor, synchronous replay and Telegram remediation regression suites.

Run only in the disposable audit environment. External models and Telegram are fake;
HTTP routes, services, SQL, graph workers and dispatcher are production code.
"""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from aiogram import Bot, types
from sqlalchemy import select

from app.config import settings
from bot import copilot_flow as flow, backend
from bot.handlers import mentor
from tests.postgresql_support import mvp_database
from tests.test_telegram_copilot import started
from tests.test_marketing_mvp_postgresql import setup_mvp, request as fixed_request, actor_id


def test_independent_real_dispatcher_mixed_action_and_text(monkeypatch):
    from bot.main import create_dispatcher
    monkeypatch.setattr(Bot, '__call__', AsyncMock(return_value=True))
    api = SimpleNamespace(execute=AsyncMock(return_value=started()))
    monkeypatch.setattr(flow, 'client', api)
    async def check():
        dp, bot = create_dispatcher(), Bot('123456:offline-audit')
        user = types.User(id=123, is_bot=False, first_name='Audit')
        msg = types.Message(message_id=1,date=datetime.now(timezone.utc),chat=types.Chat(id=123,type='private'),from_user=user,text='Стратегия https://own.example')
        try:
            await dp.feed_update(bot,types.Update(update_id=1,message=msg))
            fsm = dp.fsm.get_context(bot=bot,chat_id=123,user_id=123)
            p = (await fsm.get_data())['copilot_pending']
            async def click(i):
                q = types.CallbackQuery(id=str(i),from_user=user,chat_instance='audit',message=msg,data=flow.action(p,'own' if i%2 else 'market'))
                await dp.feed_update(bot,types.Update(update_id=i,callback_query=q))
            text = msg.model_copy(update={'message_id':100, 'text':'Уточнение во время выбора'})
            await asyncio.gather(*(click(i) for i in range(2,12)),dp.feed_update(bot,types.Update(update_id=100,message=text)))
            # Two logical text messages may start two requests; stale callbacks must not.
            assert api.execute.await_count == 2
            keys = [c.args[1].request_key for c in api.execute.call_args_list]
            assert len(set(keys)) == 2
            assert sum(c.args[1].request_key.endswith(':1') for c in api.execute.call_args_list) == 1
        finally:
            await bot.session.close()
            await dp.storage.close()
            await dp.fsm.events_isolation.close()
            for router in dp.sub_routers: router._parent_router=None
    asyncio.run(check())


@pytest.mark.parametrize('status',[400,401,403,404,409,422,429,500,502,503,504])
def test_independent_http_statuses_do_not_expose_body(monkeypatch,status):
    original=httpx.AsyncClient
    monkeypatch.setattr(settings,'API_BASE_URL','http://offline')
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw: original(transport=httpx.MockTransport(lambda r:httpx.Response(status,text='AUDIT_SECRET_SQL')),**kw))
    async def check():
        with pytest.raises(backend.BackendError) as exc: await backend.request('GET','/workflows',123)
        assert 'AUDIT_SECRET_SQL' not in str(exc.value)
    asyncio.run(check())


@pytest.mark.parametrize('error',[httpx.ConnectError,httpx.ReadTimeout,httpx.WriteTimeout])
def test_independent_transport_failures_safe(monkeypatch,error):
    original=httpx.AsyncClient
    def fail(request): raise error('AUDIT_SECRET_TRANSPORT')
    monkeypatch.setattr(settings,'API_BASE_URL','http://offline')
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw: original(transport=httpx.MockTransport(fail),**kw))
    async def check():
        with pytest.raises(backend.BackendError) as exc: await backend.request('POST','/workflows',123,payload={})
        assert 'мог быть принят' in str(exc.value) and 'AUDIT_SECRET' not in str(exc.value)
    asyncio.run(check())


def test_independent_mentor_command_route_does_not_call_question(monkeypatch):
    from bot.main import create_dispatcher
    monkeypatch.setattr(Bot,'__call__',AsyncMock(return_value=True))
    request=AsyncMock(return_value=[])
    monkeypatch.setattr(backend,'request',request)
    async def check():
        dp,bot=create_dispatcher(),Bot('123456:offline-audit')
        fsm=dp.fsm.get_context(bot=bot,chat_id=123,user_id=123)
        await fsm.set_state(mentor.MentorStates.question)
        await fsm.update_data(mentor_run_id='a'*64)
        try:
            msg=types.Message(message_id=1,date=datetime.now(timezone.utc),chat=types.Chat(id=123,type='private'),from_user=types.User(id=123,is_bot=False,first_name='Audit'),text='/runs')
            await dp.feed_update(bot,types.Update(update_id=1,message=msg))
            request.assert_awaited_once_with('GET','/workflows',123)
        finally:
            await bot.session.close()
            await dp.storage.close()
            await dp.fsm.events_isolation.close()
            for router in dp.sub_routers: router._parent_router=None
    asyncio.run(check())


def test_independent_lost_ack_after_send_real_delivery_lease_recovery(setup_mvp,monkeypatch):
    from datetime import timedelta
    from sqlalchemy import update
    from app.models import WorkflowDelivery
    from app.workflows.service import utcnow
    from bot.delivery import deliver_once
    ctx=setup_mvp
    async def check():
        actor=actor_id()
        saved=await ctx.service.start(actor,fixed_request())
        item=await ctx.service.claim(saved['jobs'][0]['job_id'])
        artifact=await ctx.executors.execute(item)
        assert await ctx.service.finish(item,artifact,[{'kind':'text','text':'AUDIT_SAVED_RESULT'}])
        bot=SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=100)))
        inner=httpx.ASGITransport(app=ctx.app)
        class LostAck(httpx.AsyncBaseTransport):
            async def handle_async_request(self,request):
                if request.url.path.endswith('/ack'):
                    raise httpx.ReadTimeout('ACK lost before durable save')
                return await inner.handle_async_request(request)
        async with httpx.AsyncClient(transport=LostAck(),base_url='http://test') as client:
            with pytest.raises(httpx.ReadTimeout): await deliver_once(bot,client)
        assert bot.send_message.await_count==1
        async with ctx.sessions() as session,session.begin():
            rows=(await session.scalars(select(WorkflowDelivery).where(WorkflowDelivery.job_id==item.job_id))).all()
            assert len(rows)==1 and rows[0].status=='sending'
            await session.execute(update(WorkflowDelivery).where(WorkflowDelivery.job_id==item.job_id).values(lease_until=utcnow()-timedelta(seconds=1)))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ctx.app),base_url='http://test') as client:
            assert await deliver_once(bot,client)
        assert bot.send_message.await_count==2
        assert bot.send_message.call_args_list[0].args==bot.send_message.call_args_list[1].args
        assert len(ctx.model.calls)==1
        async with ctx.sessions() as session:
            row=await session.scalar(select(WorkflowDelivery).where(WorkflowDelivery.job_id==item.job_id))
            assert row.status=='delivered' and row.attempts==2
    asyncio.run(check())


@pytest.mark.parametrize('response',[httpx.Response(200,headers={'content-length':'broken'},content=b'png'),httpx.Response(200,content=b'')])
def test_independent_media_invalid_length_and_empty(monkeypatch,response):
    monkeypatch.setattr(settings,'API_BASE_URL','http://test')
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:response)) as client:
            with pytest.raises(backend.BackendError): await backend.fetch_image(client,'/images/a.png',123)
    asyncio.run(check())


def test_independent_media_stream_enforces_cap_before_reading_remainder(monkeypatch):
    monkeypatch.setattr(settings,'API_BASE_URL','http://test')
    monkeypatch.setattr(backend,'MAX_IMAGE_BYTES',65536)
    read=[]
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for i in range(20):
                read.append(i)
                yield b'x'*65536
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,stream=Stream()))) as client:
            with pytest.raises(backend.BackendError): await backend.fetch_image(client,'/images/a.png',123)
        assert read==[0,1]
    asyncio.run(check())


def test_independent_media_cancel_propagates_and_closes_stream(monkeypatch):
    monkeypatch.setattr(settings,'API_BASE_URL','http://test')
    closed=[]
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise asyncio.CancelledError()
            yield b''
        async def aclose(self): closed.append(True)
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,stream=Stream()))) as client:
            with pytest.raises(asyncio.CancelledError): await backend.fetch_image(client,'/images/a.png',123)
        assert closed==[True]
    asyncio.run(check())
