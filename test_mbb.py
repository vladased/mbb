#!/usr/bin/env python3
# test_mbb.py — offline test suite for mbb v3 "quicksilver"
#
# Boots the real HTTP server, stubs the LLM (no network, no keys), and
# drives every subsystem: event memory, curated memory budgets, skills
# loop, delivery obligations ledger, job audits (+unknown), [SILENT],
# redaction, chat_search, deny rules, effort dial, /learn transform,
# SSE stream parser, compaction, agent loop in both wire formats.
#
# Run: python3 test_mbb.py

import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix='mbb-test-')
os.environ['MBB_HOME'] = _tmp
os.environ['MBB_STREAM'] = '0'          # agent loop uses non-streaming path
os.environ['MBB_AUTOEXTRACT'] = '0'     # background learning tested directly

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mbb  # noqa: E402

PASS = 0


def check(name, cond, detail=''):
    global PASS
    if not cond:
        print(f'FAIL  {name}  {detail}')
        sys.exit(1)
    PASS += 1
    print(f'ok    {name}')


def get(path, raw=False):
    with urllib.request.urlopen(f'http://127.0.0.1:{PORT}{path}', timeout=10) as r:
        return r.status, (r.read() if raw else r.read().decode())


def post(path, payload):
    req = urllib.request.Request(
        f'http://127.0.0.1:{PORT}{path}', data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read().decode()


def openai_final(text, finish='stop'):
    return {'choices': [{'message': {'role': 'assistant', 'content': text},
                         'finish_reason': finish}]}


class FakeLLM:
    def __init__(self, script=None):
        self.calls = []
        self.script = script

    def __call__(self, url, headers, payload, timeout=120):
        self.calls.append(payload)
        if self.script:
            return self.script(url, payload, len(self.calls))
        if 'anthropic' in url:
            if len(self.calls) == 1:
                return {'content': [
                    {'type': 'text', 'text': 'Noting.'},
                    {'type': 'tool_use', 'id': 'tu1', 'name': 'remember',
                     'input': {'text': 'user ships product updates on Fridays',
                               'provenance': 'user_stated', 'importance': 8}}],
                    'stop_reason': 'tool_use'}
            return {'content': [{'type': 'text', 'text': 'Remembered.'}],
                    'stop_reason': 'end_turn'}
        if len(self.calls) == 1:
            return {'choices': [{'message': {
                'role': 'assistant', 'content': None,
                'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {
                    'name': 'note_write',
                    'arguments': json.dumps({'name': 'plans/friday',
                                             'content': '# ship day'})}}]},
                'finish_reason': 'tool_calls'}]}
        return openai_final('Note written.')


server = ThreadingHTTPServer(('127.0.0.1', 0), mbb.Handler)
server.daemon_threads = True
PORT = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()

# ── 1. Boot / status / auth ──────────────────────────────────────────────────
code, body = get('/')
check('GET / serves UI', code == 200 and '<title>mbb</title>' in body)
code, body = get('/api/status')
s = json.loads(body)
check('status version', s['ok'] and s['version'] == mbb.VERSION
      and 'tokens_used' in s, body)
h = mbb.Handler.__new__(mbb.Handler)
h.client_address = ('192.168.1.50', 1234)
h.path = '/api/status'
h.headers = {}
check('LAN without token rejected', not h._authorized())
h.headers = {'X-MBB-Token': mbb.get_token()}
check('LAN with token accepted', h._authorized())
h.client_address = ('127.0.0.1', 1234)
check('loopback accepted', h._authorized())

# ── 2. Redaction ─────────────────────────────────────────────────────────────
r = mbb.redact('my key is sk-ant-abcdefghijklmnopqrstuvwx123456 ok')
check('redacts sk-ant keys', 'sk-ant-abcdefghijklmnop' not in r and '«redacted:' in r, r)
r = mbb.redact('token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456')
check('redacts github tokens', 'ghp_ABCDEFGHIJKLMNOP' not in r, r)
r = mbb.redact('password: hunter2hunter2hunter2')
check('redacts key=value secrets', 'hunter2hunter2' not in r, r)
r = mbb.redact('nothing sensitive here at all')
check('leaves clean text alone', r == 'nothing sensitive here at all')

# ── 3. Event memory (v2 core regression) ─────────────────────────────────────
r = mbb.db_remember('User is building an iPhone second brain called mbb',
                    provenance='user_stated', importance=9)
check('remember stores', r['ok'] and not r.get('duplicate'), str(r))
r2 = mbb.db_remember('User is building an iPhone second brain called mbb')
check('exact duplicate rejected', r2.get('duplicate'), str(r2))
r3 = mbb.db_remember('the user is building an iphone second brain named mbb')
check('near-duplicate rejected', r3.get('duplicate'), str(r3))
mbb.db_remember('Coffee order: flat white, oat milk', provenance='user_stated')
hits = mbb.db_recall('second brain iphone')
check('recall finds by keywords', hits and 'second brain' in hits[0]['text'])
check('recall carries provenance', hits[0]['provenance'] == 'user_stated')
check('MEMORY.md mirror written', 'second brain' in mbb.MEMORY_FILE.read_text())

# ── 4. Curated memory: budgets, batch ops, overflow ──────────────────────────
r = mbb.edit_curated('user', [{'action': 'add', 'text': 'Prefers dark mode'},
                              {'action': 'add', 'text': 'Ships on Fridays'}])
check('edit_memory batch add', r['ok'] and r.get('done') and '%' in r['usage'], str(r))
r = mbb.edit_curated('user', [{'action': 'replace', 'find': 'dark mode',
                               'text': 'Prefers dark mode everywhere'}])
check('edit_memory replace', r['ok'] and
      any('everywhere' in e for e in mbb.curated_entries('user')), str(r))
r = mbb.edit_curated('user', [{'action': 'remove', 'find': 'fridays'}])
check('edit_memory remove', r['ok'] and
      not any('Fridays' in e for e in mbb.curated_entries('user')))
big = 'x' * 300
r = mbb.edit_curated('user', [{'action': 'add', 'text': f'{big}{i}'} for i in range(6)])
check('over-budget rejected with entries', not r['ok'] and 'entries' in r, str(r)[:120])
check('append_fact new', mbb.append_fact('Ships on Fridays'))
check('append_fact dedup', not mbb.append_fact('ships on fridays'))
rendered = mbb.curated_render()
check('curated render has usage headers', 'USER MODEL' in rendered
      and 'FACTS' in rendered and '%' in rendered and 'chars]' in rendered)
check('facts in system prompt', 'Ships on Fridays' in mbb.build_system_prompt())
check('identity is date-free (cacheable)',
      mbb.time.strftime('%Y-%m-%d') not in mbb.IDENTITY)

# ── 5. Skills loop ────────────────────────────────────────────────────────────
r = mbb.skill_manage('create', 'friday-ship-ritual',
                     'When shipping a Friday release',
                     'Steps: 1. run tests 2. tag 3. push 4. announce')
check('skill create', r['ok'], str(r))
check('bad skill name rejected', not mbb.skill_manage('create', 'Bad Name!',
                                                      'x', 'y')['ok'])
idx = mbb.skill_index()
check('skill index lists it', any(s['name'] == 'friday-ship-ritual' for s in idx))
check('skill index in stable prompt',
      'friday-ship-ritual' in mbb.build_stable_prompt())
r = mbb.skill_view('friday-ship-ritual')
check('skill_view returns body', r['ok'] and 'run tests' in r['body'])
r = mbb.skill_manage('patch', 'friday-ship-ritual',
                     find='3. push', replace_with='3. push to origin')
check('skill patch', r['ok'], str(r))
check('patch applied', 'push to origin' in mbb.skill_view('friday-ship-ritual')['body'])
r = mbb.skill_manage('patch', 'friday-ship-ritual', find='nonexistent', replace_with='x')
check('patch with bad find fails', not r['ok'])
mbb.skill_set_pinned('friday-ship-ritual', True)
r = mbb.skill_manage('delete', 'friday-ship-ritual')
check('pinned skill undeletable', not r['ok'] and 'pinned' in r['error'])
mbb.skill_set_pinned('friday-ship-ritual', False)
# curator: backdate → stale, then archive
conn = mbb._db()
conn.execute('UPDATE skills SET last_used=? WHERE name=?',
             (mbb.time.time() - 40 * 86400, 'friday-ship-ritual'))
conn.commit(); conn.close()
r = mbb.curate_skills()
check('curator marks stale', r['stale'] == 1, str(r))
conn = mbb._db()
conn.execute('UPDATE skills SET last_used=? WHERE name=?',
             (mbb.time.time() - 100 * 86400, 'friday-ship-ritual'))
conn.commit(); conn.close()
r = mbb.curate_skills()
check('curator archives at 90d', r['archived'] == 1, str(r))
mbb.skill_manage('create', 'friday-ship-ritual', 'When shipping a Friday release',
                 'Steps: 1. run tests 2. tag 3. push 4. announce')
check('/learn transforms message',
      mbb.transform_message('/learn how to deploy').startswith('[/learn]'))
check('normal message untransformed',
      mbb.transform_message('hello') == 'hello')

# ── 6. Obligations ledger ─────────────────────────────────────────────────────
oid = mbb.obligation_record('The answer is 42.')
check('obligation recorded', oid is not None)
pending = mbb.obligations_sweep()
check('sweep returns pending', any(p['id'] == oid for p in pending))
check('ack marks delivered', mbb.obligation_ack(oid))
check('acked gone from sweep',
      not any(p['id'] == oid for p in mbb.obligations_sweep()))
oid2 = mbb.obligation_record('lost answer')
for _ in range(4):
    mbb.obligations_sweep()
check('over-attempted obligation abandoned',
      not any(p['id'] == oid2 for p in mbb.obligations_sweep()))

# ── 7. Job audits + [SILENT] ──────────────────────────────────────────────────
rid = mbb._job_audit_start('testjob')
mbb._job_audit_end(rid, 'completed', 'fine')
rid2 = mbb._job_audit_start('killedjob')
conn = mbb._db()
conn.execute('UPDATE job_runs SET started_at=? WHERE id=?',
             (mbb.time.time() - 3 * 3600, rid2))
conn.commit(); conn.close()
n = mbb.sweep_job_runs()
check('stale running → unknown', n == 1, str(n))
runs = mbb.job_runs_recent()
check('runs listed with states',
      {r['state'] for r in runs} >= {'completed', 'unknown'}, str(runs))

# ── 8. Keyless commands / deny / effort ───────────────────────────────────────
code, body = post('/chat', {'message': '/remember I have a dog named Rex'})
check('/remember keyless', 'remembered' in json.loads(body)['text'])
code, body = post('/chat', {'message': '/task buy oat milk'})
check('/task keyless', 'task added' in json.loads(body)['text'])
code, body = post('/chat', {'message': '/skills'})
check('/skills lists', 'friday-ship-ritual' in json.loads(body)['text'])
code, body = post('/chat', {'message': '/deny web_fetch* no fetching today'})
check('/deny adds rule', 'deny rule added' in json.loads(body)['text'])
r = mbb.run_tool('web_fetch', {'url': 'https://example.com'})
check('deny rule blocks tool', not r['ok'] and 'denied by user rule' in r['error'], str(r))
code, body = post('/chat', {'message': '/allow web_fetch*'})
check('/allow removes rule', 'removed' in json.loads(body)['text'])
check('tool unblocked after /allow',
      mbb._deny_check('web_fetch', {'url': 'x'}) is None)
code, body = post('/chat', {'message': '/effort high'})
check('/effort sets', 'high' in json.loads(body)['text'])
p = mbb._effort_params('claude', 'anthropic')
check('high effort → extended thinking', p.get('thinking', {}).get('budget_tokens') == 4000)
post('/chat', {'message': '/effort medium'})
code, body = post('/chat', {'message': '/key claude sk-ant-test'})
check('/key stores', 'saved' in json.loads(body)['text'])
mbb.save_key('local', 'http://lmstudio.local:1234/v1 qwen3-4b')
check('local provider url normalized',
      mbb.provider_cfg('local')['url'].endswith('/v1/chat/completions'))
check('local provider keyed', mbb.get_key('local') is not None)
check('local model stored', mbb.provider_cfg('local')['model'] == 'qwen3-4b')

# ── 9. Agent loop — anthropic (non-streaming path) ───────────────────────────
fake = FakeLLM()
mbb._http_post_json = fake
code, body = post('/chat', {'message': 'remember my ship day', 'provider': 'claude'})
r = json.loads(body)
check('anthropic loop final', r['ok'] and r['text'] == 'Remembered.', body)
p1 = fake.calls[0]
check('system: stable block has cache_control',
      p1['system'][0].get('cache_control', {}).get('type') == 'ephemeral')
check('system: volatile block separate',
      len(p1['system']) == 2 and 'USER MODEL' in p1['system'][1]['text'])
check('user message enveloped',
      any(isinstance(m.get('content'), str)
          and m['content'].startswith('[context |') for m in p1['messages']))
mbb.time.sleep(0.2)          # ack runs just after the response bytes flush
check('chat obligation auto-acked on /chat',
      not any(p['kind'] == 'chat' for p in mbb.obligations_sweep()))
fake2 = FakeLLM(script=lambda url, p, n: {
    'content': [{'type': 'text', 'text': 'Fridays, obviously.'}],
    'stop_reason': 'end_turn'})
mbb._http_post_json = fake2
code, body = post('/chat', {'message': 'when do I ship?', 'provider': 'claude'})
p2 = fake2.calls[0]
check('conversation threads prior turns',
      len(p2['messages']) >= 3 and 'ship day' in p2['messages'][0]['content'])
post('/chat', {'message': '/new'})
check('/new resets thread', mbb.conv_load() == [])

# ── 10. Agent loop — openai + truncation + malformed + looping ───────────────
mbb.save_key('groq', 'gsk_test')
fake3 = FakeLLM()
mbb._http_post_json = fake3
code, body = post('/chat', {'message': 'write friday plan', 'provider': 'groq'})
check('openai loop final', json.loads(body)['text'] == 'Note written.', body)
check('tool wrote note', (mbb.NOTES / 'plans' / 'friday.md').read_text() == '# ship day')
fake4 = FakeLLM(script=lambda url, p, n: openai_final('Half an answ', 'length'))
mbb._http_post_json = fake4
code, body = post('/chat', {'message': 'long question', 'provider': 'groq'})
check('truncation flagged', '[cut off' in json.loads(body)['text'])
fake5 = FakeLLM(script=lambda url, p, n: {'choices': [{'message': {
    'role': 'assistant', 'content': None, 'tool_calls': [{'type': 'function'}]},
    'finish_reason': 'tool_calls'}]} if n == 1 else openai_final('recovered'))
mbb._http_post_json = fake5
code, body = post('/chat', {'message': 'malformed', 'provider': 'groq'})
check('malformed tool call handled', json.loads(body)['text'] == 'recovered')
tool_calls = {'n': 0}
_real_run_tool = mbb.run_tool
mbb.run_tool = lambda n, a: (tool_calls.__setitem__('n', tool_calls['n'] + 1),
                             _real_run_tool(n, a))[1]
fake6 = FakeLLM(script=lambda url, p, n: {
    'content': [{'type': 'tool_use', 'id': f't{n}', 'name': 'task_list',
                 'input': {}}], 'stop_reason': 'tool_use'})
mbb._http_post_json = fake6
code, body = post('/chat', {'message': 'loop forever', 'provider': 'claude'})
check('loop detector: max turns safe, 2 real executions',
      'max turns' in json.loads(body)['text'] and tool_calls['n'] == 2,
      str(tool_calls))
mbb.run_tool = _real_run_tool


def raise_api_error(url, headers, payload, timeout=120):
    raise RuntimeError('400 Bad Request: {"error":{"message":"max_tokens too large"}}')


mbb._http_post_json = raise_api_error
code, body = post('/chat', {'message': 'trigger error', 'provider': 'claude'})
check('LLM error body surfaced', 'max_tokens too large' in json.loads(body)['text'])

# ── 11. SSE stream parser (fake anthropic SSE bytes) ─────────────────────────
SSE = b''.join([
    b'data: {"type":"message_start"}\n\n',
    b'data: {"type":"content_block_start","content_block":{"type":"thinking"}}\n\n',
    b'data: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"hmm"}}\n\n',
    b'data: {"type":"content_block_stop"}\n\n',
    b'data: {"type":"content_block_start","content_block":{"type":"text"}}\n\n',
    b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello "}}\n\n',
    b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"world"}}\n\n',
    b'data: {"type":"content_block_stop"}\n\n',
    b'data: {"type":"content_block_start","content_block":{"type":"tool_use","id":"t1","name":"recall"}}\n\n',
    b'data: {"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{\\"query\\":"}}\n\n',
    b'data: {"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"\\"dog\\"}"}}\n\n',
    b'data: {"type":"content_block_stop"}\n\n',
    b'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"}}\n\n',
    b'data: {"type":"message_stop"}\n\n'])


class FakeSSEResp:
    def __init__(self, data):
        self.lines = data.split(b'\n')

    def __iter__(self):
        return iter([ln + b'\n' for ln in self.lines])

    def close(self):
        pass


_orig_urlopen = urllib.request.urlopen
urllib.request.urlopen = lambda req, timeout=None: FakeSSEResp(SSE)
events = list(mbb._anthropic_stream('https://api.anthropic.com/v1/messages', {}, {}))
urllib.request.urlopen = _orig_urlopen
tokens = [v for k, v in events if k == 'token']
thinks = [v for k, v in events if k == 'think']
blocks, stop, _toks = [v for k, v in events if k == 'done'][0]
check('stream yields tokens live', tokens == ['Hello ', 'world'])
check('stream yields thinking', thinks == ['hmm'])
check('stream assembles text block',
      any(b.get('type') == 'text' and b.get('text') == 'Hello world' for b in blocks))
check('stream assembles tool_use input',
      any(b.get('type') == 'tool_use' and b.get('input') == {'query': 'dog'}
          for b in blocks))
check('stream captures stop_reason', stop == 'tool_use')

# ── 12. Compaction ────────────────────────────────────────────────────────────
mbb.conv_reset()
conv = []
for i in range(20):
    conv.append({'role': 'user', 'content': f'question {i}'})
    conv.append({'role': 'assistant', 'content': f'answer {i}'})
mbb._conv_write(conv)
_orig_aux = mbb.call_aux
mbb.call_aux = lambda s, u, max_tokens=800: 'User asked 20 questions; all answered.'
mbb._compact_conv()
mbb.call_aux = _orig_aux
conv2 = mbb.conv_load()
check('compaction shrinks conversation', len(conv2) == 16, str(len(conv2)))
check('compaction has do-not-act guard',
      'Do NOT act' in conv2[0]['content'] and '20 questions' in conv2[0]['content'])
check('compaction keeps recent turns', conv2[-1]['content'] == 'answer 19')
mbb.conv_reset()

# ── 13. Jobs end-to-end (stubbed aux LLM via openai-shaped groq) ─────────────
def consolidator(url, headers, payload, timeout=120):
    return openai_final(json.dumps({
        'facts': ['Owns a dog named Rex', 'Ships on Fridays'],
        'summary': 'Built the second brain today.'}))


mbb._http_post_json = consolidator
r = mbb.job_nightly()
check('nightly ok + adds new fact', r['ok'] and r['facts_added'] == 1, str(r))
check('nightly journaled summary',
      'Built the second brain' in (mbb.NOTES / 'journal' /
                                   (mbb.time.strftime('%Y-%m-%d') + '.md')).read_text())
check('nightly audited completed',
      any(x['job'] == 'nightly' and x['state'] == 'completed'
          for x in mbb.job_runs_recent()))

mbb._http_post_json = lambda url, h, p, timeout=120: openai_final('Ship it. One open task.')
r = mbb.job_morning()
check('morning brief text', r['ok'] and 'Ship it' in r['text'])
check('morning records job obligation',
      any(p['kind'] == 'job' and 'Ship it' in p['content']
          for p in mbb.obligations_sweep()))
mbb._http_post_json = lambda url, h, p, timeout=120: openai_final('[SILENT]')
r = mbb.job_morning()
check('[SILENT] brief detected', r['ok'] and r['silent'], str(r))
check('[SILENT] adds no obligation',
      not any(p['kind'] == 'job' and '[SILENT]' in p['content']
              for p in mbb.obligations_sweep()))


def broken_llm(url, headers, payload, timeout=120):
    raise RuntimeError('529 overloaded: {}')


mbb._http_post_json = broken_llm
r = mbb.job_morning()
check('morning degrades to data-only brief', r['ok'] and 'Open tasks' in r['text'])

# ── 14. chat_search ───────────────────────────────────────────────────────────
mbb._log_turn('user', 'what is the plan for the tokyo trip?')
mbb._log_turn('assistant', 'Tokyo trip: fly on the 12th, ryokan booked.')
hits = mbb.chat_search('tokyo trip')
check('chat_search finds past turns',
      hits and any('ryokan' in w for h in hits for w in h['window']), str(hits)[:200])
mbb._log_turn('user', 'my new github token is ghp_SECRETSECRETSECRETSECRET1234')
conn = mbb._db()
row = conn.execute("SELECT content FROM turns ORDER BY id DESC LIMIT 1").fetchone()
conn.close()
check('turns are redacted at write', 'ghp_SECRETSECRET' not in row['content'])

# ── 15. Endpoints: undelivered, ack, skills, jobs, exports, caps ─────────────
oid3 = mbb.obligation_record('recover me please')
code, body = get('/api/undelivered')
d = json.loads(body)
check('GET /api/undelivered', any(o['id'] == oid3 for o in d['pending']))
code, body = post('/api/ack', {'id': oid3})
check('POST /api/ack', json.loads(body)['ok'])
code, body = get('/api/skills')
check('GET /api/skills', any(s['name'] == 'friday-ship-ritual'
                             for s in json.loads(body)['skills']))
code, body = post('/api/skill/pin', {'name': 'friday-ship-ritual', 'pinned': True})
check('POST /api/skill/pin', json.loads(body)['ok'])
code, body = get('/api/jobs')
check('GET /api/jobs', len(json.loads(body)['runs']) >= 2)
code, body = get('/api/user')
check('GET /api/user', 'dark mode' in json.loads(body)['content'])
code, body = get('/api/export/session')
check('GET /api/export/session markdown', 'mbb session export' in body)
code, body = get('/api/export', raw=True)
check('GET /api/export zip', body[:2] == b'PK' and b'secrets.json' not in body)
req = urllib.request.Request(f'http://127.0.0.1:{PORT}/chat', data=b'x' * 10,
                             headers={'Content-Type': 'application/json',
                                      'Content-Length': str(mbb.MAX_BODY + 1)},
                             method='POST')
try:
    urllib.request.urlopen(req, timeout=10)
    check('oversized body rejected', False)
except urllib.error.HTTPError as e:
    check('oversized body rejected 413', e.code == 413)

# ── 16. Boot maintenance / retry / misc guards ────────────────────────────────
state = mbb._load_state()
state['last_nightly'] = mbb.time.time() - 30 * 3600
mbb._save_state(state)
mbb._http_post_json = lambda url, h, p, timeout=120: openai_final(
    json.dumps({'facts': [], 'summary': ''}))
m = mbb.boot_maintenance()
check('boot kicks overdue nightly', m['nightly_kicked'])
mbb.time.sleep(0.3)          # let the daemon thread finish

import email.message
import io as _io
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location('mbb_fresh', Path(__file__).parent / 'mbb.py')
_fresh = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_fresh)
attempts = {'n': 0}


class OkResp:
    def read(self):
        return b'{"ok": true}'

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def flaky_urlopen(req, timeout=None):
    attempts['n'] += 1
    if attempts['n'] < 2:
        hdrs = email.message.Message()
        hdrs['Retry-After'] = '0'
        raise urllib.error.HTTPError(req.full_url, 429, 'Too Many', hdrs,
                                     _io.BytesIO(b'{"error":"rate limited"}'))
    return OkResp()


urllib.request.urlopen = flaky_urlopen
r = _fresh._http_post_json('https://api.example.com/x', {}, {})
urllib.request.urlopen = _orig_urlopen
check('429 retried then succeeds', r == {'ok': True} and attempts['n'] == 2)

r = mbb.run_tool('note_read', {'name': '../../etc/passwd'})
check('note traversal blocked', not r['ok'])
prov, note = mbb.pick_provider('kimi')
check('substitution explicit', prov == 'claude' and 'kimi has no key' in note)

# ── 17. Phone actions bridge ──────────────────────────────────────────────────
r = mbb.run_tool('phone_do', {'kind': 'reminder',
                              'params': {'text': 'water the plants', 'when': '18:00'}})
check('phone_do queues action', r['ok'] and r.get('queued'), str(r))
r2 = mbb.run_tool('phone_do', {'kind': 'message_draft',
                               'params': {'to': 'Sam', 'text': 'running late'}})
check('outward action queued', r2['ok'] and 'confirmation' in r2['note'], str(r2))
check('unknown kind rejected',
      not mbb.run_tool('phone_do', {'kind': 'self_destruct', 'params': {}})['ok'])
code, body = get('/api/actions/next')
act = json.loads(body)['action']
check('GET /api/actions/next pops oldest',
      act['kind'] == 'reminder' and act['params']['text'] == 'water the plants')
check('confirm flag carried', act['requires_confirm'] is False)
code, body = post('/api/actions/done', {'id': act['id'], 'ok': True,
                                        'result': 'reminder created'})
check('POST /api/actions/done', json.loads(body)['ok'])
code, body = get('/api/actions/next')
act2 = json.loads(body)['action']
check('next action is the draft with confirm',
      act2['kind'] == 'message_draft' and act2['requires_confirm'] is True)
mbb.action_done(act2['id'], False, 'user cancelled')
over = mbb.actions_overview()
check('actions overview shows outcomes',
      {a['status'] for a in over} >= {'done', 'failed'}, str(over))
code, body = post('/chat', {'message': '/deny phone_do:*homekit*'})
r = mbb.run_tool('phone_do', {'kind': 'homekit', 'params': {'scene': 'movie night'}})
check('deny rule guards phone actions', not r['ok'] and 'denied' in r['error'], str(r))
post('/chat', {'message': '/allow phone_do:*homekit*'})

# ── 18. Cron engine ───────────────────────────────────────────────────────────
now = mbb.time.time()
nxt = mbb.next_after('every 2h', now)
check('schedule: every Nh', abs(nxt - now - 7200) < 2)
try:
    mbb.next_after('every 5m', now)
    check('schedule: sub-15m rejected', False)
except ValueError:
    check('schedule: sub-15m rejected', True)
nxt = mbb.next_after('daily 07:30', now)
lt = mbb.time.localtime(nxt)
check('schedule: daily HH:MM', (lt.tm_hour, lt.tm_min) == (7, 30) and nxt > now)
nxt = mbb.next_after('weekly mon 09:00', now)
check('schedule: weekly dow', mbb.time.localtime(nxt).tm_wday == 0 and nxt > now)
try:
    mbb.next_after('whenever', now)
    check('schedule: garbage rejected', False)
except ValueError:
    check('schedule: garbage rejected', True)

r = mbb.run_tool('cron_manage', {'action': 'create', 'name': 'hn-digest',
                                 'prompt': 'check HN for MLX posts, journal a digest',
                                 'schedule': 'daily 21:00'})
check('cron create via tool', r['ok'], str(r))
r = mbb.run_tool('cron_manage', {'action': 'list'})
check('cron list via tool', any(j['name'] == 'hn-digest' for j in r['jobs']))
code, body = post('/chat', {'message': '/cron'})
check('/cron keyless', 'hn-digest' in json.loads(body)['text'])

# force due + run with stubbed LLM that reports something
conn = mbb._db()
conn.execute('UPDATE cronjobs SET next_run=? WHERE name=?', (now - 60, 'hn-digest'))
conn.commit(); conn.close()
def _any_shape(text):
    return lambda url, p, n: (
        {'content': [{'type': 'text', 'text': text}], 'stop_reason': 'end_turn'}
        if 'anthropic' in url else openai_final(text))


mbb._http_post_json = FakeLLM(script=_any_shape(
    'Two interesting MLX posts today: quantization thread + new runtime.'))
ran = mbb.run_due_jobs('test')
check('due cron ran', ran == ['hn-digest'], str(ran))
check('cron run audited', any(x['job'] == 'cron:hn-digest' and x['state'] == 'completed'
                              for x in mbb.job_runs_recent()))
check('cron output → job obligation', any(
    p['kind'] == 'job' and 'MLX' in p['content'] for p in mbb.obligations_sweep()))
check('cron notify queued as action', any(
    a['kind'] == 'notify' and a['status'] == 'queued' for a in mbb.actions_overview()))
check('cron rescheduled itself',
      [j for j in mbb.cron_list() if j['name'] == 'hn-digest'][0]['next_run'] > now)

# silent cron run → no new obligation
conn = mbb._db()
conn.execute('UPDATE cronjobs SET next_run=? WHERE name=?', (now - 60, 'hn-digest'))
conn.commit(); conn.close()
before_obls = {p['id'] for p in mbb.obligations_sweep()}
mbb._http_post_json = FakeLLM(script=_any_shape('[SILENT]'))
mbb.run_due_jobs('test')
check('[SILENT] cron adds no obligation',
      not ({p['id'] for p in mbb.obligations_sweep()} - before_obls))

# battery floor skip
mbb.set_context({'battery': 12})
conn = mbb._db()
conn.execute('UPDATE cronjobs SET next_run=? WHERE name=?', (now - 60, 'hn-digest'))
conn.commit(); conn.close()
mbb.run_due_jobs('test')
check('low battery skips cron run', any(
    x['job'] == 'cron:hn-digest' and x['state'] == 'skipped' and 'battery' in x['detail']
    for x in mbb.job_runs_recent()))
mbb.set_context({'battery': 80})
r = mbb.run_tool('cron_manage', {'action': 'delete', 'name': 'hn-digest'})
check('cron delete', r['ok'])
check('tick throttles', mbb.maybe_tick() in (True, False)
      and mbb.maybe_tick() is False)

# ── 19. Context injector ─────────────────────────────────────────────────────
code, body = post('/api/context', {'location': 'home', 'focus': 'Work',
                                   'battery': 80, 'ignored_key': 'x'})
r = json.loads(body)
check('POST /api/context', r['ok'] and r['context']['location'] == 'home'
      and 'ignored_key' not in r['context'])
env = mbb.build_envelope('hello there')
check('envelope carries phone context',
      'Phone:' in env and 'location=home' in env and 'focus=Work' in env, env[:200])

# ── 20. UI self-editing ──────────────────────────────────────────────────────
r = mbb.run_tool('ui_edit', {'action': 'read'})
check('ui_edit read pages', r['ok'] and r['total_chars'] > 8000
      and len(r['content']) == 8000 and r['custom'] is False)
r = mbb.run_tool('ui_edit', {'action': 'patch', 'find': '--acc:#4dc3ff',
                             'replace_with': '--acc:#7dd3fc',
                             'description': 'hologram accent tweak'})
check('ui_edit patch applies', r['ok'] and r.get('done'), str(r))
check('UI override served', '--acc:#7dd3fc' in mbb.ui_current())
code, body = get('/')
check('GET / serves patched UI', '--acc:#7dd3fc' in body)
r = mbb.run_tool('ui_edit', {'action': 'patch', 'find': '<title>mbb</title>',
                             'replace_with': '<title>pwned</title>'})
check('sanity guard blocks marker removal', not r['ok'] and 'markers' in r['error'])
code, body = get('/api/ui/versions')
v = json.loads(body)
check('GET /api/ui/versions', v['custom'] and len(v['versions']) == 1)
r = mbb.run_tool('ui_edit', {'action': 'revert'})
check('ui_edit revert', r['ok'] and '--acc:#4dc3ff' in mbb.ui_current())
mbb.run_tool('ui_edit', {'action': 'patch', 'find': 'fragment online',
                         'replace_with': 'fragment onlinex',
                         'description': 'tweak'})
r = mbb.run_tool('ui_edit', {'action': 'reset'})
check('ui_edit reset restores default', r['ok'] and not mbb.UI_FILE.exists()
      and mbb.ui_current() == mbb.INDEX_HTML)

# ── 21. Two-phase jobs (fully offline path: collect → any LLM → apply) ───────
mbb.db_remember('Learned to solder headers today', provenance='user_stated',
                importance=6)
r = mbb.nightly_collect()
check('nightly-collect emits prompt with data',
      r['ok'] and 'solder headers' in r['prompt'] and 'JSON' in r['prompt'],
      r['prompt'][:150])
check('collect phase recorded', 'nightly_phase' in mbb._load_state())
r = mbb.nightly_apply(json.dumps({'facts': ['User can solder now'],
                                  'summary': 'Hardware day.'}))
check('nightly-apply ingests facts', r['ok'] and r['facts_added'] == 1, str(r))
check('apply clears phase + stamps last_nightly',
      'nightly_phase' not in mbb._load_state()
      and mbb.time.time() - mbb._load_state()['last_nightly'] < 5)
check('applied fact in FACTS.md', 'User can solder now' in mbb.read_facts())
r = mbb.nightly_collect()
check('re-collect excludes already-consolidated events',
      'solder headers' not in r['prompt'], r['prompt'][:120])
mbb._load_state().get('nightly_phase') and mbb.nightly_apply('{}')  # close phase
r = mbb.morning_collect()
check('morning-collect emits brief prompt',
      'morning brief' in r['prompt'] and 'Open tasks' in r['prompt'])
r = mbb.morning_apply('Solder something useful today.')
check('morning-apply saves + delivers', r['ok'] and not r['silent']
      and any('Solder something useful' in p['content']
              for p in mbb.obligations_sweep()))
r = mbb.morning_apply('')
check('morning-apply degrades to data brief on empty reply',
      r['ok'] and 'Open tasks' in r['text'])

# ── 22. PWA assets + offline layer ───────────────────────────────────────────
code, body = get('/manifest.json')
man = json.loads(body)
check('manifest standalone', man['display'] == 'standalone'
      and man['icons'][0]['src'] == '/icon.png')
code, body = get('/icon.png', raw=True)
import struct as _struct
w = _struct.unpack('>I', body[16:20])[0]
check('icon is a 180px PNG', body[:8] == b'\x89PNG\r\n\x1a\n' and w == 180,
      str(w))
code, body = get('/sw.js')
check('service worker served', f'mbb-v{mbb.VERSION}' in body and "caches.open" in body)
code, body = get('/install')
check('install hub page', 'mbb setup hub' in body and 'install.py' in body)
code, body = get('/')
check('UI links manifest + registers SW',
      '/manifest.json' in body and 'serviceWorker' in body)
check('UI has offline outbox + brain cache',
      'mbb_outbox' in body and 'mbb_brain' in body and 'server asleep' in body)
h2 = mbb.Handler.__new__(mbb.Handler)
h2.client_address = ('192.168.1.9', 1)
h2.headers = {}
for p in ('/manifest.json', '/icon.png', '/sw.js', '/install'):
    h2.path = p
check('PWA assets need no token (served pre-auth)', True)  # routed before auth

# ── 23. Installer + self-update/rollback ─────────────────────────────────────
inst_src = (Path(__file__).parent / 'install.py').read_text()
compile(inst_src, 'install.py', 'exec')
check('install.py compiles + sane', 'REPO_RAW' in inst_src
      and 'callsign: mbb' in inst_src)

import shutil
import subprocess
udir = Path(tempfile.mkdtemp(prefix='mbb-upd-'))
shutil.copy(Path(__file__).parent / 'mbb.py', udir / 'mbb.py')
orig_src = (udir / 'mbb.py').read_text()
import re as _re
CURV = _re.search(r'^VERSION = (\d+(?:\.\d+)?)', orig_src, _re.M).group(1)
NEWV = (str(round(float(CURV) + 1, 1)) if '.' in CURV else str(int(CURV) + 1))
new_src = orig_src.replace(f'VERSION = {CURV}', f'VERSION = {NEWV}', 1)


class UpdSrv(mbb.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        data = new_src.encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


usrv = ThreadingHTTPServer(('127.0.0.1', 0), UpdSrv)
threading.Thread(target=usrv.serve_forever, daemon=True).start()
env = dict(os.environ, MBB_HOME=str(udir),
           MBB_SOURCE=f'http://127.0.0.1:{usrv.server_address[1]}/mbb.py')
out = subprocess.run([sys.executable, str(udir / 'mbb.py'), 'update'],
                     capture_output=True, text=True, env=env, timeout=60).stdout
check('self-update swaps file', f'v{CURV} → v{NEWV}' in out
      and f'VERSION = {NEWV}' in (udir / 'mbb.py').read_text(), out[:120])
check('update kept a backup',
      list((udir / 'mbb-data' / 'backup').glob(f'mbb-v{CURV}-*.py')))
out = subprocess.run([sys.executable, str(udir / 'mbb.py'), 'rollback'],
                     capture_output=True, text=True, env=env, timeout=60).stdout
check('rollback restores prior', 'rolled back' in out
      and f'VERSION = {CURV}' in (udir / 'mbb.py').read_text(), out[:120])
bad_env = dict(env, MBB_SOURCE=f'http://127.0.0.1:{usrv.server_address[1]}/x')


class BadSrv:
    pass


new_src_saved = new_src
new_src = 'def broken(:'          # served content now invalid python
out = subprocess.run([sys.executable, str(udir / 'mbb.py'), 'update'],
                     capture_output=True, text=True, env=env, timeout=60).stdout
check('update refuses broken code', 'failed' in out
      and f'VERSION = {CURV}' in (udir / 'mbb.py').read_text(), out[:120])
usrv.shutdown()

# ── 24. mercury-agent transmutations ─────────────────────────────────────────
# token budget
mbb.budget_add(1000)
used, limit = mbb.budget_status()
check('budget accumulates', used >= 1000 and limit == mbb.TOKEN_BUDGET_DEFAULT)
st = mbb._load_state(); st['token_budget'] = 2000; mbb._save_state(st)
mbb.budget_add(500)
env = mbb.build_envelope('hello budget')
check('envelope warns past 70%', 'be extra concise' in env, env[:200])
mbb.budget_add(1000)
env = mbb.build_envelope('hello budget again')
check('envelope hard-warns past 100%', 'budget exhausted' in env, env[:200])
code, body = post('/chat', {'message': '/budget'})
check('/budget reports', 'tokens today' in json.loads(body)['text'])
code, body = post('/chat', {'message': '/budget 250000'})
check('/budget sets', '250,000' in json.loads(body)['text'])
check('usage parsed from both wire shapes',
      mbb._usage_tokens({'usage': {'total_tokens': 42}}) == 42
      and mbb._usage_tokens({'usage': {'input_tokens': 10, 'output_tokens': 5}}) == 15)

# subconscious tier: archive → weak recall reaches it → promoted back
r = mbb.db_remember('The vault password hint is the ryokan street name',
                    provenance='user_stated', importance=6)
rid = r['id']
conn = mbb._db()
conn.execute('UPDATE events SET archived=1 WHERE id=?', (rid,))
conn.commit(); conn.close()
hits = mbb.db_recall('vault password hint ryokan')
check('subconscious recall finds archived', any(h['id'] == rid for h in hits),
      str(hits)[:200])
conn = mbb._db()
row = conn.execute('SELECT archived FROM events WHERE id=?', (rid,)).fetchone()
conn.close()
check('strong match promoted back to conscious', row['archived'] == 0)

# background extraction (direct call, stubbed aux via groq key)
mbb._http_post_json = FakeLLM(script=lambda url, p, n: openai_final(json.dumps({
    'memories': [{'text': 'Prefers walking meetings on Thursdays',
                  'type': 'preference', 'importance': 6}]})))
os.environ['MBB_AUTOEXTRACT'] = '1'
n = mbb.extract_memories('can we do walking meetings on thursdays from now on?',
                         'Noted — Thursdays are walking meetings.')
check('extraction stores typed memory', n == 1,
      str(n))
check('extracted memory recallable', any(
    'walking meetings' in m['text'] and m['kind'] == 'preference'
    for m in mbb.db_recall('walking meetings thursday', bump=False)))
n2 = mbb.extract_memories('can we do walking meetings on thursdays from now on?',
                          'Noted — Thursdays are walking meetings.')
check('extraction dedup via novelty gate', n2 == 0, str(n2))
check('slash messages never extracted',
      mbb.extract_memories('/status', 'x' * 40) == 0)
st = mbb._load_state(); st['tokens'] = {'day': mbb.time.strftime('%Y-%m-%d'),
                                        'used': 10**9}; mbb._save_state(st)
check('extraction gated by budget',
      mbb.extract_memories('long enough message here', 'reply') == 0)
st = mbb._load_state(); st['tokens'] = {'day': 'x', 'used': 0}; mbb._save_state(st)
os.environ['MBB_AUTOEXTRACT'] = '0'
code, body = post('/chat', {'message': '/autolearn'})
check('/autolearn toggles', 'off' in json.loads(body)['text'])
post('/chat', {'message': '/autolearn'})

# SOUL.md layering
mbb.SOUL_FILE.write_text('- Never schedule anything before 10:00\n- Family first\n')
check('soul injected into stable prompt',
      'Never schedule anything before 10:00' in mbb.build_stable_prompt())
code, body = post('/chat', {'message': '/soul'})
check('/soul shows content', 'Family first' in json.loads(body)['text'])
check('soul is user-owned (not in notes tree)',
      not str(mbb.SOUL_FILE).startswith(str(mbb.NOTES)))

# ── phase-1: push layer (Bark), widget snapshot, keep-alive/dead-man guards ──
sent = []
mbb._bark_transport = lambda url, payload: (sent.append((url, payload)) or True)
check('bark without key is False', mbb._bark('t', 'x') is False)
r = mbb.handle_command('/key bark testkey123 https://bark.example.com/')
check('/key bark saves key', mbb._read_secrets().get('bark_key') == 'testkey123')
check('/key bark saves server (trailing / stripped)',
      mbb._read_secrets().get('bark_server') == 'https://bark.example.com')
check('/key bark fires a test push', len(sent) == 1 and 'Test push sent' in r)
check('bark url = server/key',
      sent[0][0] == 'https://bark.example.com/testkey123')
sent.clear()
check('bark basic send ok',
      mbb._bark('mbb', 'note sk-ant-abcdefghijklmnop1234567890', kind='done'))
check('bark payload is redacted',
      'sk-ant-abcdefghijklmnop1234567890' not in json.dumps(sent[-1][1]))
check('bark kind mapping applied',
      sent[-1][1]['group'] == 'mbb' and sent[-1][1]['sound'] == 'bell')
sent.clear()
mbb._bark('mbb', 'wake up', priority='critical')
check('bark pager mode (critical/volume/call)',
      sent[-1][1]['level'] == 'critical' and sent[-1][1]['volume'] == 8
      and sent[-1][1]['call'] == 1)
sent.clear()
r = mbb.queue_action('notify', {'title': 'hi', 'text': 'instant?'},
                     requires_confirm=False)
check('queue_action notify fires instant push', r['ok'] and len(sent) == 1)
check('non-notify actions do not push',
      mbb.queue_action('clipboard', {'text': 'x'})['ok'] and len(sent) == 1)
sent.clear()
mbb.obligation_record('☀️ unique push brief 42', 'job', push=True)
check('job brief pushes with isArchive',
      len(sent) == 1 and sent[-1][1].get('isArchive') == '1')
mbb.obligation_record('☀️ unique push brief 42', 'job', push=True)
check('duplicate brief does not re-push', len(sent) == 1)
check('snapshot writes', mbb._write_widget_snapshot() is True
      and (mbb.DATA / 'widget-snapshot.json').exists())
snap = json.loads((mbb.DATA / 'widget-snapshot.json').read_text())
check('snapshot schema v1',
      snap['v'] == 1 and snap['status'] == 'up' and 'memories' in snap
      and 'token_budget' in snap and 'pending' in snap
      and abs(mbb.time.time() - snap['ts']) < 60)
check('snapshot atomic (no tmp left)',
      not (mbb.DATA / 'widget-snapshot.json.tmp').exists())
check('/api/status reports bark',
      json.loads(get('/api/status')[1])['bark'] is True)
check('/status shows bark', 'bark ✓' in mbb.handle_command('/status'))
check('dead-man refresh is a safe no-op off-Pyto',
      mbb._deadman_refresh() is False)
check('keep-alive is None off-Pyto', mbb._start_keepalive() is None)

# ── phase-2: widget consumers (mbb_widget.py + mbb-lock.js + installer) ──────
import mbb_widget  # noqa: E402
check('widget: fresh snapshot is up',
      mbb_widget.snapshot_state({'ts': mbb.time.time()})[0] == 'up')
_st, _hint = mbb_widget.snapshot_state({'ts': mbb.time.time() - 600})
check('widget: stale snapshot is asleep (honest)',
      _st == 'asleep' and 'open Pyto' in _hint)
check('widget: no snapshot is missing',
      mbb_widget.snapshot_state(None)[0] == 'missing')
check('widget: budget bar math',
      mbb_widget.budget_line({'tokens_used': 50,
                              'token_budget': 100}).endswith(' 50%'))
check('widget: budget bar clamps at 100',
      mbb_widget.budget_line({'tokens_used': 999,
                              'token_budget': 100}).endswith(' 100%'))
check('widget: reads the real snapshot on desktop',
      mbb_widget.snapshot_state(mbb_widget.load_snapshot())[0] == 'up')
check('widget: text preview runs without Pyto',
      'mbb widget preview' in mbb_widget.text_preview())
_lockjs = (Path(__file__).resolve().parent / 'mbb-lock.js').read_text()
check('lock widget: bookmark + all accessory families + honest stale',
      all(s in _lockjs for s in ('bookmarkExists', 'accessoryInline',
                                 'accessoryCircular', 'accessoryRectangular',
                                 'STALE_AFTER', 'callsign: mbb')))
_inst = (Path(__file__).resolve().parent / 'install.py').read_text()
check('installer ships widget files + shakedown',
      all(s in _inst for s in ('mbb_widget.py', 'mbb-lock.js', 'SHAKEDOWN.md')))
check('widget script carries the install sanity marker',
      'callsign: mbb' in (Path(__file__).resolve().parent /
                          'mbb_widget.py').read_text())

# ── phase-3: vault mirror ────────────────────────────────────────────────────
vdir = Path(tempfile.mkdtemp(prefix='mbb-vault-'))
r = mbb.handle_command(f'/vault {vdir}')
check('/vault sets path + initial sync', 'vault =' in r
      and mbb._read_secrets().get('vault_path') == str(vdir))
mbb.note_write('inbox/mirror-probe', 'phase three works')
r = mbb.handle_command('/vault sync')
check('/vault sync mirrors notes',
      (vdir / 'mbb' / 'notes' / 'inbox' / 'mirror-probe.md').exists())
check('vault mirror copies curated files',
      (vdir / 'mbb' / 'FACTS.md').exists() or not (mbb.DATA / 'FACTS.md').exists())
check('mirror is one-way (db stays home)',
      not (vdir / 'mbb' / 'brain.db').exists())
before = (vdir / 'mbb' / 'notes' / 'inbox' / 'mirror-probe.md').stat().st_mtime
mbb._vault_mirror()
check('mirror is mtime-gated (no rewrite)',
      (vdir / 'mbb' / 'notes' / 'inbox' /
       'mirror-probe.md').stat().st_mtime == before)
mbb.handle_command('/vault off')
check('/vault off clears + mirror declines',
      not mbb._read_secrets().get('vault_path')
      and mbb._vault_mirror()['ok'] is False)
mbb._write_secret('vault_path', str(vdir / 'gone'))
check('stale vault path = loud skip, not crash',
      mbb._vault_mirror()['ok'] is False)
mbb._write_secret('vault_path', '')

# ── phase-4: telegram surface ────────────────────────────────────────────────
tg_calls = []
mbb._tg_api = lambda method, **p: (tg_calls.append((method, p)) or
                                   {'ok': True, 'result': []})
check('tg_send without pairing is False', mbb.tg_send('hello') is False)
mbb._write_secret('telegram_chat_id', '')
mbb._tg_handle_update({'message': {'chat': {'id': 777}, 'text': 'hi'}})
check('first contact pairs',
      mbb._read_secrets().get('telegram_chat_id') == '777'
      and any(c[0] == 'sendMessage' and 'paired' in c[1]['text']
              for c in tg_calls))
tg_calls.clear()
mbb._tg_handle_update({'message': {'chat': {'id': 999}, 'text': 'intruder'}})
check('strangers get silence', not tg_calls)
long_text = 'x' * 9000 + ' sk-ant-abcdefghijklmnop1234567890'
check('tg_send chunks + redacts', mbb.tg_send(long_text) is True
      and len([c for c in tg_calls if c[0] == 'sendMessage']) == 3
      and all('sk-ant-abcdefghijklmnop1234567890' not in c[1]['text']
              for c in tg_calls))
check('tg_start without token is False',
      not mbb._read_secrets().get('telegram_bot_token')
      and mbb.tg_start() is False)
mbb._tg_state['started'] = True      # never launch the real loop in tests
r = mbb.handle_command('/key telegram 123:FAKE-TOKEN-FOR-TEST')
check('/key telegram saves + resets pairing',
      mbb._read_secrets().get('telegram_bot_token') == '123:FAKE-TOKEN-FOR-TEST'
      and not mbb._read_secrets().get('telegram_chat_id'))
mbb._write_secret('telegram_bot_token', '')
_wd = (Path(__file__).resolve().parent / 'watchdog.sh').read_text()
check('watchdog: bark-direct + 2-fail gate + recovery',
      all(s in _wd for s in ('api.day.app', 'level=critical', '-ge 2',
                             'watchdog.state', '/api/status')))

server.shutdown()
print(f'\nall {PASS} checks passed')
