import pytest
from nexus.agent import memory_candidate
from nexus.db import transaction
from nexus.graph_resources import resources
from nexus.models import Message, Run
from nexus.worker import process_run
from sqlalchemy import select
from test_graph import FakeModel, setup_run


@pytest.mark.parametrize('text', [
    'iam a gold medalist of Fast 4th Semester SE',
    'my cgpa is 3.6',
    'i like short answers but complete',
    'I am a FAST University student',
    'I prefer detailed explanations',
])
def test_durable_self_disclosures_offer_review(text):
    assert memory_candidate(text)


@pytest.mark.parametrize('text', [
    'What is my cgpa?',
    'Do not save this: my cgpa is 3.6',
    'Hypothetically my cgpa is 3.6',
    'My friend is a university student',
    'Explain CGPA in short answers',
    'I like pizza',
])
def test_other_inputs_do_not_force_memory_review(text):
    assert not memory_candidate(text)


@pytest.mark.asyncio
@pytest.mark.parametrize('query', [
    'iam a gold medalist of Fast 4th Semester SE', 'my cgpa is 3.6',
    'i like short answers but complete',
])
async def test_acknowledgement_retries_into_memory_review(client, monkeypatch, query):
    _, thread, run = setup_run(client, monkeypatch)
    run.input = {'message': query}
    with transaction() as db:
        db.get(Run, run.id).input = run.input
        db.scalar(select(Message).where(Message.run_id == run.id)).content = query
    model = FakeModel([
        {'content':'Understood.'},
        {'content':'Please review this memory.', 'tool_calls':[{
            'id':'memory-fact', 'name':'propose_action', 'args':{
                'action':'memories.create', 'payload':{'items':[{
                    'title':'User preference or profile', 'content':query, 'category':'profile'
                }]}
            }
        }]}
    ])
    async with resources() as (saver, store):
        await process_run(run, 'test-worker', saver, store, model)
    history = client.get(f"/conversations/{thread['id']}/history").json()
    assert history['runs'][-1]['status'] == 'waiting', history['runs'][-1]
    assert history['proposals'][-1]['action'] == 'memories.create'
    assert history['proposals'][-1]['status'] == 'pending'
    assert client.get('/memories').json() == []
