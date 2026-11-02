import json

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from nexus import agent
from nexus.agent import citation_aliases, normalize_citations, verified_citation_fallback
from nexus.config import settings
from nexus.db import transaction
from nexus.graph_resources import resources
from nexus.models import Chunk, Document, Message, Run
from nexus.worker import claim_run, process_run
from sqlalchemy import select
from test_graph import FakeModel, setup_run

ID = '11111111-1111-1111-1111-111111111111'
EVIDENCE = [{'id':ID, 'citation':'[source:r12345678-s1]', 'filename':'Lecture.pdf', 'excerpt':'Speedup equals serial time divided by parallel time.'}]


def test_short_reference_resolves_to_exact_authorized_chunk():
    assert normalize_citations('Formula [Source:{R12345678-S1}]', {ID}, aliases=citation_aliases(EVIDENCE)) == f'Formula [source:{ID}]'


@pytest.mark.parametrize('separator', [', ', '; ', ',', ', source:', '; source: '])
def test_grouped_references_expand_only_exact_known_members(separator):
    second = '22222222-2222-2222-2222-222222222222'
    aliases = {'r12345678-s1':ID,'r12345678-s2':second}
    draft = f'Formula [source: r12345678-s1{separator}r12345678-s2]'
    assert normalize_citations(draft,{ID,second},aliases=aliases) == f'Formula [source:{ID}] [source:{second}]'
    bad = f'Formula [source: r12345678-s1{separator}foreign]'
    assert normalize_citations(bad,{ID},aliases=aliases) == bad


@pytest.mark.parametrize('draft', ['Wrong [source:made-up]', 'Wrong [source unavailable]', 'Wrong [source:rOTHER-s1]'])
def test_failed_repair_returns_actual_excerpts_not_guessed_sources(draft):
    result = verified_citation_fallback(draft, EVIDENCE)
    assert 'not a complete summary' in result
    assert EVIDENCE[0]['excerpt'] in result
    assert f'[source:{ID}]' in result
    assert 'Wrong' not in result
    assert '[source unavailable]' not in result


def test_no_evidence_returns_clear_limitation():
    assert 'could not verify' in verified_citation_fallback('Claim [source:unknown]', []).lower()


def test_valid_answer_keeps_content():
    draft = f'Formula [source:{ID}]'
    assert verified_citation_fallback(draft, EVIDENCE) == draft


@pytest.mark.parametrize('prefix', ['source','url','Source'])
def test_web_references_resolve_exact_returned_urls_without_document_error(prefix):
    url='https://example.com/Schedule?team=AUS'
    result=verified_citation_fallback(f'Match details [{prefix}: {url}]',[{'url':url,'excerpt':'Schedule'}])
    assert result==f'Match details [Source ↗]({url})'
    assert 'document' not in result


def test_unknown_web_reference_is_not_accepted_or_given_document_instructions():
    result=verified_citation_fallback('Claim [source: https://unknown.example/]',[
        {'url':'https://example.com/','excerpt':'Known web excerpt'}])
    assert 'retrieved web excerpts' in result
    assert 'unknown.example' not in result
    assert 'select the document' not in result


def test_grouped_web_urls_resolve_exactly_and_preserve_commas_in_paths():
    first='https://example.com/Team,AUS'
    second='https://example.com/ENG'
    sources=[{'url':first},{'url':second}]
    assert verified_citation_fallback(f'Answer [source: {first}, source: {second}]',sources)==f'Answer [Source ↗]({first}) [Source ↗]({second})'
    result=verified_citation_fallback(f'Answer [source: {first}, source: https://unknown.example/]',sources)
    assert 'retrieved web excerpts' in result
    assert 'unknown.example' not in result


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['auto','web'])
async def test_web_only_graph_preserves_answer_and_links(client,monkeypatch,mode):
    _,thread,run=setup_run(client,monkeypatch)
    run.input={'message':'When is the AUS versus ENG ODI match?', 'mode':mode,'document_ids':[]}
    with transaction() as db:
        db.get(Run,run.id).input=run.input
        db.scalar(select(Message).where(Message.run_id==run.id)).content=run.input['message']
    url='https://example.com/Schedule?team=AUS'
    async def lookup(name,args,ctx):
        assert name=='web_search'
        return {'sources':[{'url':url,'title':'Synthetic fixture schedule','excerpt':'A fictional match takes place on 13 November 2026.'}]}
    monkeypatch.setattr(agent,'read_tool',lookup)
    responses=[] if mode=='web' else [{'content':'','tool_calls':[{'id':'lookup','name':'web_search','args':{'query':'AUS ENG ODI'}}]}]
    responses.append({'content':f'In this synthetic fixture, the match is on 13 November 2026 [source: {url}]'})
    async with resources() as (saver,store):
        await process_run(run,'test-worker',saver,store,FakeModel(responses))
    history=client.get(f"/conversations/{thread['id']}/history").json()
    assert history['runs'][-1]['status']=='completed'
    assert history['messages'][-1]['content']==f'In this synthetic fixture, the match is on 13 November 2026 [Source ↗]({url})'
    assert history['messages'][-1]['sources'][0]['url']==url


@pytest.mark.asyncio
@pytest.mark.parametrize('repair', ['not-needed', 'valid', 'invalid'])
async def test_graph_persists_verified_citations_and_source_opens(client, monkeypatch, repair):
    user, thread, run = setup_run(client, monkeypatch)
    with transaction() as db:
        doc = Document(user_id=user['id'],filename='Lecture.pdf',blob='synthetic.pdf',
            sha256=run.id,size=1,media_type='application/pdf',status='ready',
            embedding_model=settings.embedding_model,embedding_dimensions=1536)
        db.add(doc)
        db.flush()
        chunk = Chunk(user_id=user['id'],document_id=doc.id,position=0,page=7,section='Performance metrics',
            content='Speedup equals serial time divided by parallel time.',embedding=[1.0]+[0.0]*1535)
        db.add(chunk)
        db.flush()
        source_id = chunk.id
        evidence = {'id':source_id,'citation':f'[source:{source_id}]','filename':doc.filename,
            'document_id':doc.id,'page':7,'excerpt':chunk.content}
        run.input={'message':'Summarize the selected lecture.', 'mode':'auto','document_ids':[doc.id]}
        db.get(Run,run.id).input=run.input
        db.scalar(select(Message).where(Message.run_id==run.id)).content=run.input['message']
    searches=[]
    async def read_tool(name, args, ctx):
        searches.append(args)
        return {'sources':[dict(evidence)],'text':'Authorized lecture passage'}
    monkeypatch.setattr(agent,'read_tool',read_tool)
    class CitationModel(FakeModel):
        async def astream(self, messages):
            tool_results = [m for m in messages if isinstance(m, ToolMessage)]
            if not tool_results:
                yield AIMessageChunk(content='',tool_calls=[{'id':'search','name':'search_documents','args':{'query':'speedup'}}])
            else:
                source = json.loads(tool_results[-1].content)['sources'][0]
                assert source['citation'] != f'[source:{source_id}]'
                yield AIMessageChunk(content='Speedup is serial time divided by parallel time. ' +
                    (source['citation'] if repair == 'not-needed' else '[source:invented]'))
        async def ainvoke(self, messages):
            return AIMessage(content=f'Speedup is serial time divided by parallel time. [source:{source_id}]'
                if repair == 'valid' else 'Unsupported draft [source:still-invented]')
    async with resources() as (saver, store):
        await process_run(run,'test-worker',saver,store,CitationModel([]))
    history = client.get(f"/conversations/{thread['id']}/history").json()
    assert history['runs'][-1]['status'] == 'completed', history['runs'][-1]
    message = history['messages'][-1]
    assert f'[source:{source_id}]' in message['content']
    assert '[source unavailable]' not in message['content']
    assert 'invented' not in message['content']
    assert message['sources'][0]['id'] == source_id
    assert client.get(f'/sources/{source_id}').status_code == 200
    assert searches[0].get('coverage') is True
    if repair == 'not-needed':
        response=client.post(f"/conversations/{thread['id']}/runs",json={
            'message':'Using the selected document, explain speedup.', 'mode':'auto','document_ids':[doc.id]})
        assert response.status_code==202,response.text
        async with resources() as (saver,store):
            await process_run(claim_run('test-worker'),'test-worker',saver,store,CitationModel([]))
        followup=client.get(f"/conversations/{thread['id']}/history").json()
        assert len(searches)==2
        assert followup['messages'][-1]['sources'][0]['id']==source_id
        assert f'[source:{source_id}]' in followup['messages'][-1]['content']
    if repair == 'invalid':
        assert 'not a complete summary' in message['content']
    from conftest import register
    client.post('/auth/logout')
    register(client, 'citation-other-user@example.com')
    assert client.get(f'/sources/{source_id}').status_code == 404
