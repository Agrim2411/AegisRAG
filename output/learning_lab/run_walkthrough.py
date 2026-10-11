"""Run from the repository root. Uses local providers and a fresh database per run."""
import json
import math
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
RUN_DIR = Path(tempfile.mkdtemp(prefix='run_', dir=ROOT / 'output' / 'learning_lab'))
os.environ.update({
    'AEGIS_RAG_DATABASE_URL': f'sqlite:///{RUN_DIR / "knowledge.db"}',
    'AEGIS_RAG_ANSWER_PROVIDER': 'local',
    'AEGIS_RAG_QDRANT_URL': '',
    'AEGIS_RAG_REDIS_URL': '',
    'AEGIS_RAG_CHECKPOINT_PATH': '',
    'AEGIS_RAG_OTEL_ENABLED': 'false',
    'AEGIS_RAG_EMBEDDING_DIMENSIONS': '256',
})
from fastapi.testclient import TestClient
from aegis_rag.api import app
from aegis_rag.retrieval import _tokens, _bm25
from aegis_rag.embeddings import cosine

state = app.state.lattice
client = TestClient(app)
TENANT = 'interview-lab'
QUESTION = 'Why is payments returning HTTP 503 and db_pool_timeout?'
CONTENT = (
    '# Connection pool exhaustion\n\n'
    'HTTP 503 and db_pool_timeout indicate PostgreSQL connection pool exhaustion.\n\n'
    '# Safe remediation\n\n'
    'Stop the rollout and reduce payments concurrency before retrying requests.\n\n'
    '# Other\n\n'
    'The cafeteria menu changes every Friday.'
)
headers = {'x-tenant-id': TENANT, 'x-request-id': 'req_learning'}
payload = {'title': 'Payments learning runbook', 'source_uri': 'lab://payments', 'content': CONTENT}
first = client.post('/v1/ingest', headers=headers, json=payload)
first.raise_for_status()
second = client.post('/v1/ingest', headers=headers, json=payload)
second.raise_for_status()
rows = state.store.chunks(TENANT)
searchable = [(row, _tokens(f'{row[1]} {row[1]} {row[0].section} {row[0].text}')) for row in rows]
qt = _tokens(QUESTION)
qv = state.embedder.embed(QUESTION)
df = {token: sum(token in set(tokens) for _, tokens in searchable) for token in set(qt)}
avg = sum(len(tokens) for _, tokens in searchable) / len(searchable)
lexical = sorted([(_bm25(qt, tokens, df, len(searchable), avg), row[0].id) for row, tokens in searchable], reverse=True)
dense = sorted([(cosine(qv, row[0].embedding), row[0].id) for row, _ in searchable], reverse=True)
lex_ranks = {cid: i for i, (_, cid) in enumerate(lexical, 1)}
dense_ranks = {cid: i for i, (_, cid) in enumerate(dense, 1)}
hits, _, candidates = state.retriever.search(TENANT, QUESTION, 2)
ranking = []
for row, tokens in searchable:
 c = row[0]
 ranking.append({'section': c.section, 'chunk_id': c.id, 'text': c.text, 'token_count': len(tokens),
                 'bm25': dict((cid, score) for score, cid in lexical)[c.id],
                 'cosine': dict((cid, score) for score, cid in dense)[c.id],
                 'lexical_rank': lex_ranks[c.id], 'dense_rank': dense_ranks[c.id],
                 'rrf': 1/(60+lex_ranks[c.id])+1/(60+dense_ranks[c.id])})
# Stream the actual graph without replacing any node. Record readable state summaries.
initial = {'tenant_id': TENANT, 'original_question': QUESTION, 'question': QUESTION,
           'top_k': 2, 'attempts': 0, 'trace': []}
current = dict(initial)
states = [{'after': 'input', 'state': dict(current)}]
for update in state.workflow.graph.stream(initial, config={'configurable': {'thread_id': TENANT+':learning-stream'}}, stream_mode='updates'):
 for node, values in update.items():
  current.update(values)
  summary = {k: v for k, v in current.items() if k not in ['hits', 'retrieval_latency_ms']}
  summary['hit_sections'] = [h['chunk']['section'] for h in current.get('hits', [])]
  states.append({'after': node, 'state': summary})
query = client.post('/v1/query', headers=headers, json={'question': QUESTION, 'top_k': 2, 'thread_id': 'learning-query'})
query.raise_for_status()
empty = client.post('/v1/query', headers={'x-tenant-id': 'empty-lab', 'x-request-id': 'req_empty'}, json={'question': QUESTION})
empty.raise_for_status()
off_topic = client.post('/v1/query', headers=headers, json={'question': 'What is the capital of France?', 'top_k': 1})
off_topic.raise_for_status()
invalid = client.post('/v1/query', headers=headers, json={'question': QUESTION, 'top_k': 0})
missing = client.post('/v1/query', json={'question': QUESTION})
scenario_headers = {'x-tenant-id': 'acme-payments', 'x-request-id': 'req_learning_scenario'}
scenario = client.post('/v1/scenarios/run', headers=scenario_headers, json={'scenario_id': 'payments-pool-exhaustion'})
scenario.raise_for_status()
scenario_body = scenario.json()
incident_id = scenario_body['incident']['incident_id']
reload = client.get('/v1/incidents/'+incident_id, headers=scenario_headers)
reload.raise_for_status()
other = client.get('/v1/incidents/'+incident_id, headers={'x-tenant-id': 'other-lab'})
with state.store.connection() as db:
 counts = {t: db.execute(f'SELECT COUNT(*) FROM {t} WHERE tenant_id=?', (TENANT,)).fetchone()[0] for t in ['documents','chunks','audit_events','telemetry_events','incidents']}
 scenario_counts = {t: db.execute(f'SELECT COUNT(*) FROM {t} WHERE tenant_id=?', ('acme-payments',)).fetchone()[0] for t in ['documents','chunks','audit_events','telemetry_events','incidents']}
 metadata = [dict(r) for r in db.execute('SELECT id,title,source_uri,content_hash FROM documents WHERE tenant_id=?',(TENANT,))]
 chunk_rows = [dict(r) for r in db.execute('SELECT id,ordinal,section,start_char,end_char FROM chunks WHERE tenant_id=? ORDER BY ordinal',(TENANT,))]
 mmr_inputs = sorted(ranking,key=lambda r:r['rrf'], reverse=True)
high = max(r['rrf'] for r in mmr_inputs);low = min(r['rrf'] for r in mmr_inputs)
first_hit = hits[0]
mmr = []
for r in mmr_inputs:
 c = next(row[0] for row in rows if row[0].id==r['chunk_id'])
 normalized = (r['rrf']-low)/max(high-low,1e-9)
 similarity = max(0.0,cosine(c.embedding,first_hit.chunk.embedding))
 mmr.append({'section':r['section'],'normalized_relevance':normalized,'first_round_value':0.75*normalized,'similarity_to_first':similarity,'second_round_value':0.75*normalized-0.25*similarity})
result = {'question':QUESTION,'content':CONTENT,'ingest':first.json(),'duplicate':second.json(),
          'query_tokens':qt,'query_vector_nonzero':sum(x!=0 for x in qv),'query_vector_norm':math.sqrt(sum(x*x for x in qv)),
          'ranking':ranking,'mmr':mmr,'selected_sections':[h.chunk.section for h in hits],'candidates':candidates,
          'states':states,'query_response':query.json(),'empty_response':empty.json(),'off_topic_response':off_topic.json(),
          'invalid_status':invalid.status_code,'missing_tenant_status':missing.status_code,
          'document_rows':metadata,'chunk_rows':chunk_rows,'query_tenant_counts':counts,
          'scenario_response':scenario_body,'scenario_counts':scenario_counts,
          'reload_status':reload.status_code,'other_tenant_reload_status':other.status_code}
assert first.json()['chunks']==3 and second.json()['deduplicated']
assert query.json()['workflow']['nodes']==['retrieve','grade_evidence','generate','verify_citations']
assert empty.json()['workflow']['rewrites']==1 and empty.json()['abstained']
assert invalid.status_code==422 and missing.status_code==400
assert scenario_body['status']=='incident_created' and scenario_body['generated_events']==6
assert reload.status_code==200 and other.status_code==404
out = RUN_DIR/'evidence.json'
out.write_text(json.dumps(result,indent=2))
print('All learning checks passed. Evidence:',out.relative_to(ROOT))
print('Selected:',result['selected_sections'])
print('Scores:',[(r['section'],round(r['bm25'],6),round(r['cosine'],6),round(r['rrf'],6)) for r in ranking])
print('Query counts:',counts,'Scenario counts:',scenario_counts)
print('Off-topic answer:',result['off_topic_response']['answer'])
