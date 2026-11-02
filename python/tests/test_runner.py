import json
import sys
from pathlib import Path
import pytest
from dsh_harnessmm_rsi.runner import normalize_events, NativeCallbacks, run_lifecycle, route_policy


def test_native_cache_exclusive_counters_convert_to_author_inclusive():
    receipt={'type':'harnessmm.receipt','status':'completed','answer':'ok','usage':{'uncachedInputTokens':10,'outputTokens':3,'totalTokens':20,'cacheReadTokens':5,'cacheWriteTokens':2}}
    answer,usage=normalize_events(json.dumps(receipt))
    assert answer=='ok'
    assert usage['input_tokens']==17
    assert usage['total_tokens']==20
    assert usage['cache_read_tokens']==5
    assert normalize_events('')[1]['total_tokens'] is None


def test_sdk_task_uses_isolated_home_and_no_oracle(tmp_path):
    seen=[]
    def launch(argv,*,cwd,input_text,timeout,env):
        request=json.loads(input_text);seen.append((argv,request,env))
        assert Path(request['dshHome']).is_dir()
        return {'status':'completed','returncode':0,'stdout':json.dumps({'type':'harnessmm.receipt','status':'completed','answer':'done','usage':None}),'stderr':''}
    tasks={'x':{'seed_files':{'solution.py':'x=1'},'verifier_argv':[sys.executable,'-c','assert True # PRIVATE_ORACLE']}}
    callback=NativeCallbacks(tasks,dsh='dsh',model='deepseek-v4-flash',provider='bharatcode',artifact_dir=tmp_path,launch=launch)
    result=callback.execute({'request_id':'x','task':{'task_id':'x'},'identity':{'runtime':'official_deepseek_harness_sdk','model':'deepseek-v4-flash'},'codex_prompt':'Fix function','phase':'train','arm':'baseline'})
    assert result['native_score']==1
    assert 'PRIVATE_ORACLE' not in json.dumps(seen)
    assert not Path(seen[0][1]['dshHome']).exists()
    assert 'reasoningEffort' not in seen[0][1]


@pytest.mark.parametrize('provider,model,effort',[('provider-alpha','model-a',None),('provider-beta','model-b','high')])
def test_full_authors_lifecycle(tmp_path,provider,model,effort):
    class Fake:
        def execute(self,r):
            return {'request_id':r['request_id'],'identity':r['identity'],'task_id':r['task']['task_id'],'execution_status':'completed','native_score':1.0,'success':True,'usage':dict.fromkeys(['input_tokens','output_tokens','total_tokens','cache_read_tokens','cache_write_tokens','cost_usd'])}
        def optimize(self,r):
            return {'request_id':r['request_id'],'identity':r['identity'],'execution_status':'completed','instruction':'','supporting_task_ids':[],'usage':dict.fromkeys(['input_tokens','output_tokens','total_tokens','cache_read_tokens','cache_write_tokens','cost_usd'])}
    corpus=Path(__file__).parents[2]/'corpora/synthetic-python-v1.json'
    report=run_lifecycle(corpus,tmp_path/'run',dsh=sys.executable,model=model,provider=provider,reasoning_effort=effort,iterations=1,callbacks=Fake())
    assert report['state']=='complete'
    policy=tmp_path/'run/policy.json'
    value=json.loads(policy.read_text())
    assert value['sources']['execution_identity']['runtime']=='official_deepseek_harness_sdk'
    routed=route_policy(policy,'Fix function')
    assert routed['instruction']==''
    assert routed['activation_route']=={'provider':provider,'model':model,'reasoning_effort':effort}
    assert routed['cross_route_transfer_validated'] is False
    identity=value['sources']['execution_identity']
    assert identity['provider']==provider and identity['model']==model
    assert identity['reasoning_effort']==(effort or 'provider-default')
    assert len(identity['source_contract_sha256'])==64
    manifest=json.loads((tmp_path/'run/run.json').read_text())
    assert manifest['activation_route']==routed['activation_route']


def test_failed_optimizer_retains_native_cost(tmp_path):
    def launch(*args,**kwargs):
        return {'returncode':0,'status':'completed','stderr':'','stdout':json.dumps({'type':'harnessmm.receipt','status':'failed','answer':'bad json','usage':{'uncachedInputTokens':10,'outputTokens':2,'totalTokens':17,'cacheReadTokens':5,'cacheWriteTokens':0}})}
    cb=NativeCallbacks({},dsh='dsh',model='test',provider='bharatcode',artifact_dir=tmp_path,launch=launch)
    result=cb.optimize({'request_id':'bad','identity':{'model':'test'},'training_evidence':[]})
    assert result['execution_status']=='failed'
    assert result['instruction']==''
    assert result['usage']['input_tokens']==15
    assert result['usage']['total_tokens']==17


def test_duplicate_receipt_rejected_and_missing_usage_unknown():
    receipt=json.dumps({'type':'harnessmm.receipt','answer':'ok','usage':None})
    assert normalize_events(receipt)[1]['total_tokens'] is None
    with pytest.raises(ValueError,match='duplicate'): normalize_events(receipt+'\n'+receipt)


@pytest.mark.parametrize('provider,model,effort',[('provider-alpha','model-a',None),('provider-beta','model-b','high')])
def test_arbitrary_route_and_optional_reasoning(tmp_path,provider,model,effort):
    seen=[]
    def launch(argv,*,cwd,input_text,timeout,env):
        seen.append(json.loads(input_text))
        return {'status':'completed','returncode':0,'stdout':json.dumps({'type':'harnessmm.receipt','status':'completed','answer':'{"instruction":"","supporting_task_ids":[]}','usage':{'uncachedInputTokens':10,'outputTokens':3,'totalTokens':20}}),'stderr':''}
    cb=NativeCallbacks({},dsh='dsh',model=model,provider=provider,reasoning_effort=effort,artifact_dir=tmp_path,launch=launch)
    result=cb.optimize({'request_id':'route','identity':{'provider':provider,'model':model},'training_evidence':[]})
    assert seen[0]['provider']==provider and seen[0]['model']==model
    if effort is None: assert 'reasoningEffort' not in seen[0]
    else: assert seen[0]['reasoningEffort']==effort
    assert result['usage']['input_tokens']==17
    assert result['usage']['cache_read_tokens'] is None
    assert result['usage']['cache_write_tokens'] is None


def test_exact_prompt_suffix_from_author_render(tmp_path,monkeypatch):
    from dsh_harnessmm_rsi import runner
    class Policy:
        policy_sha256='policy';source_sha256='source'
        def apply(self,prompt): return {'codex_prompt':prompt+'\nAUTHOR DELIMITER\nSelected instruction','decision':{'residual_id':'candidate'}}
        def to_dict(self): return {'candidate':{'instruction':'Selected instruction'},'config':{'application':'prompt_suffix'},'sources':{'execution_identity':{'provider':'p','model':'m'}}}
    class Core:
        class FrozenPolicy:
            @staticmethod
            def from_dict(value): return Policy()
    monkeypatch.setattr(runner,'upstream_modules',lambda:(Core,None,None))
    path=tmp_path/'policy';path.write_text('{}')
    result=runner.route_policy(path,'PUBLIC')
    assert result['prompt_suffix']=='\nAUTHOR DELIMITER\nSelected instruction'


def test_extension_and_profile_sources_are_frozen(tmp_path):
    from dsh_harnessmm_rsi.runner import collect_native_contract
    extension=tmp_path/'extension';extension.mkdir();(extension/'vendor').mkdir()
    for name in ['index.mjs','controller.mjs','vendor/sar_v2.mjs','package.json']:
        (extension/name).write_text('original')
    home=tmp_path/'home';profile=home/'profiles/training';profile.mkdir(parents=True)
    (profile/'cordis.patch.yml').write_text('native: true')
    before=collect_native_contract(extension,home,'training')
    assert str(extension/'index.mjs') in before
    assert str(extension/'vendor/sar_v2.mjs') in before
    assert str(profile/'cordis.patch.yml') in before
    (extension/'controller.mjs').write_text('changed')
    assert collect_native_contract(extension,home,'training')!=before
    stable=collect_native_contract(extension,home,'training')
    runtime=extension/'extension-data'/'request';runtime.mkdir(parents=True)
    (runtime/'stats.json').write_text('runtime changes')
    assert collect_native_contract(extension,home,'training')==stable


def test_sigterm_cleans_real_worker_process_tree(tmp_path):
    import os,subprocess,time
    pid_file=tmp_path/'pids.json'
    worker=tmp_path/'worker.py'
    worker.write_text('import subprocess,sys,json,os,time\nchild=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"])\nopen(sys.argv[1],"w").write(json.dumps([os.getpid(),child.pid]))\nprint("started",flush=True)\ntime.sleep(60)\n')
    script=tmp_path/'parent.py'
    script.write_text('import os,sys\nfrom dsh_harnessmm_rsi.runner import launch_process,cancellation_signals\nwith cancellation_signals():\n result=launch_process([sys.executable,sys.argv[1],sys.argv[2]],cwd="/tmp",input_text="",timeout=60,env=os.environ.copy())\n assert result["status"]=="cancelled"\n')
    parent=subprocess.Popen([sys.executable,str(script),str(worker),str(pid_file)],env=os.environ.copy())
    try:
        deadline=time.monotonic()+5
        while not pid_file.exists() and time.monotonic()<deadline: time.sleep(.02)
        assert pid_file.exists()
        pids=json.loads(pid_file.read_text())
        parent.terminate();parent.wait(timeout=8)
        assert parent.returncode==0
        for pid in pids:
            path=Path('/proc')/str(pid)/'stat'
            assert not path.exists() or path.read_text().split()[2]=='Z'
    finally:
        if parent.poll() is None: parent.kill();parent.wait()


def test_native_sdk_params_serialization_and_native_meter(tmp_path):
    """Native wire shape from sdk-client.spec.ts:97 and token-meter turn-usage.spec.ts:25-65."""
    import subprocess
    root=Path('/home/sushi/Applications/deepseek-harness-source')
    source=(root/'packages/sdk/client/tests/sdk-client.spec.ts').read_text()
    assert "params: { sessionId: 'owned', event:" in source
    module=Path(__file__).parents[1]/'sdk_meter.mjs'
    js=f'''import {{meterNotifications}} from {json.dumps(module.as_uri())};
import {{deriveTurnTokenUsage}} from {json.dumps((root/'packages/llm/token-meter/lib/types/turn-usage.js').as_uri())};
const event=(seq,type,data)=>({{seq,time:seq,type,data}});
const usage={{inputTokens:100,outputTokens:20,totalTokens:170,cacheReadTokens:50,cacheWriteTokens:0}};
const events=[event(1,'turn/start',{{turn:1}}),event(2,'step/start',{{turn:1,step:1}}),event(3,'assistant/message',{{turn:1,step:1,stream:[{{type:'chunk',time:3,chunk:{{type:'usage',usage}}}}],message:{{id:'message-3',role:'assistant',content:[{{type:'text',text:'done'}}],source:{{kind:'model',provider:'deepseek',model:'deepseek-chat'}}}},usage}}),event(90,'step/end',{{turn:1,step:1}}),event(91,'turn/end',{{turn:1,reason:{{kind:'completed'}}}})];
// JSON serialization matches the SDK's real HarnessNotification.params envelope.
const wire=JSON.parse(JSON.stringify(events.map(event=>({{method:'session.event',params:{{sessionId:'owned',event}}}}))));
console.log(JSON.stringify(meterNotifications(wire,deriveTurnTokenUsage)));
'''
    result=subprocess.run(['node','--input-type=module','-e',js],capture_output=True,text=True,check=True)
    usage=json.loads(result.stdout)
    assert usage=={'uncachedInputTokens':100,'outputTokens':20,'totalTokens':170,'cacheReadTokens':50,'cacheWriteTokens':0}


def test_actual_sdk_worker_native_wire_notifications(tmp_path):
    """Exercise real native SDK client using upstream's own fake RPC runtime (no model)."""
    import os,subprocess
    root=Path('/home/sushi/Applications/deepseek-harness-source')
    launcher=tmp_path/'native-fixture-runtime.mjs'
    launcher.write_text('import '+json.dumps((root/'packages/sdk/client/tests/fake-runtime.ts').as_uri())+';\n')
    launcher.chmod(0o755)
    home=tmp_path/'home';home.mkdir()
    worker=Path(__file__).parents[1]/'sdk_worker.mjs'
    request={'prompt':'test native fixture','cwd':str(tmp_path),'dshHome':str(home),'dshBin':str(launcher),'profile':'sdk','provider':'fixture-provider','model':'fixture-model','timeoutMs':5000}
    result=subprocess.run(['node',str(worker)],input=json.dumps(request),capture_output=True,text=True,timeout=15,check=True,env=os.environ.copy())
    (tmp_path/'worker-output.jsonl').write_text(result.stdout)
    (tmp_path/'worker-stderr.txt').write_text(result.stderr)
    frames=[json.loads(line) for line in result.stdout.splitlines()]
    native=[f['notification'] for f in frames if f['type']=='harnessmm.notification']
    assert any(n.get('method')=='session.event' and n['params']['event']['type']=='turn/end' for n in native)
    assert all('payload' not in n for n in native)
    receipt=[f for f in frames if f['type']=='harnessmm.receipt'][0]
    assert receipt['status']=='completed'
    assert receipt['finishReason']=='completed'
    assert receipt['answer']=='hello from fake runtime'
    # Native fixture has no complete step usage lifecycle, so accounting must abstain.
    assert receipt['usage'] is None


@pytest.mark.parametrize('provider,denied,installed',[('fixture-alpha',False,False),('fixture-beta',False,False),('fixture-alpha',True,False),('fixture-alpha',False,True),('fixture-beta',False,True),('fixture-alpha',True,True)])
def test_actual_native_graph_executes_banked_actions_without_provider_calls(tmp_path,provider,denied,installed):
    import os,subprocess
    extension=Path(__file__).parents[2]
    fixture=Path(__file__).with_name('native_graph_fixture.mjs')
    data=tmp_path/'extension-data';home=tmp_path/'home';home.mkdir()
    patch=tmp_path/'fixture.patch.yml'
    fixture_row='- insert:\n    - id: harnessmm-fixture-model\n      name: '+json.dumps(str(fixture))+'\n'
    if installed:
        profile=home/'profiles/sdk';profile.mkdir(parents=True)
        desktop_modules=Path('/home/sushi/.local/share/deepseek-harness/home/profiles/desktop/node_modules')
        (profile/'node_modules/@local').mkdir(parents=True)
        (profile/'node_modules/@local/dsh-harnessmm').symlink_to(desktop_modules/'@local/dsh-harnessmm',target_is_directory=True)
        manifest={'name':'native-installed-graph-fixture','private':True,'dependencies':{'@deepseek-ai/dsh-base':'0.2.1-rc.2','@deepseek-ai/dsh-sdk-app':'0.2.1-rc.2','@local/dsh-harnessmm':'*'},'dsh':{'profile':{'bundles':['@deepseek-ai/dsh-base','@deepseek-ai/dsh-sdk-app','@local/dsh-harnessmm']}}}
        (profile/'package.json').write_text(json.dumps(manifest))
        (profile/'cordis.yml').write_text('[]\n')
        (profile/'cordis.patch.yml').write_text('[]\n')
        harness_row='- id: harnessmm\n  config:\n    enabled: true\n    autoImprove: false\n    dataDirectory: '+json.dumps(str(data))+'\n'
    else:
        harness_row='- insert:\n    - id: harnessmm\n      name: '+json.dumps(str(extension/'index.mjs'))+'\n      config:\n        enabled: true\n        autoImprove: false\n        dataDirectory: '+json.dumps(str(data))+'\n'
    patch.write_text(fixture_row+harness_row)
    requests=tmp_path/'requests.jsonl'
    env={**os.environ,'DSH_HARNESSMM_ENABLED':'1','DSH_HARNESSMM_NO_POLICY':'1','DSH_HARNESSMM_TRAINING':'1','DSH_PERMISSION_MODE':'danger-full-access','DSH_TELEMETRY_DISABLED':'1','HARNESSMM_FIXTURE_REQUESTS':str(requests),'HARNESSMM_FIXTURE_DENY_A':'1' if denied else '0'}
    worker=Path(__file__).parents[1]/'sdk_worker.mjs'
    request={'prompt':'Run the deterministic fixture procedure.','cwd':str(tmp_path),'dshHome':str(home),'profile':'sdk','patches':[str(patch)],'provider':provider,'model':'fixture-model','timeoutMs':30000}
    result=subprocess.run(['node',str(worker)],input=json.dumps(request),capture_output=True,text=True,timeout=45,env=env,check=True)
    (tmp_path/'worker-output.jsonl').write_text(result.stdout)
    (tmp_path/'worker-stderr.txt').write_text(result.stderr)
    frames=[json.loads(line) for line in result.stdout.splitlines()]
    receipt=[f for f in frames if f['type']=='harnessmm.receipt'][0]
    assert receipt['status']=='completed',receipt
    (tmp_path/'fixture-case.json').write_text(json.dumps({'provider':provider,'denied':denied,'installed':installed,'installed_package':str(desktop_modules/'@local/dsh-harnessmm') if installed else None}))
    assert receipt['answer']=='NATIVE_GRAPH_FIXTURE_DONE'
    assert (tmp_path/'sequence.txt').read_text().splitlines()==(['root'] if denied else ['root','A','B'])
    calls=[json.loads(line) for line in requests.read_text().splitlines()]
    assert len(calls)==2 and all(c['provider']==provider for c in calls)
    events=[f['notification']['params']['event'] for f in frames if f['type']=='harnessmm.notification' and f['notification']['method']=='session.event']
    tools=[e for e in events if e['type']=='tool/result']
    signed=[block['text'] for e in tools for block in e['data']['message'].get('content',[]) if block['type']=='text' and '<HARNESSMM_RECEIPT>' in block['text']]
    assert len(signed)==(1 if denied else 3)
    for text in signed:
        metadata=json.loads(text.split('<HARNESSMM_RECEIPT>')[-1].split('</HARNESSMM_RECEIPT>')[0])
        assert len(metadata['signature'])==64 and metadata['return_code']==0
    audit=[json.loads(line) for path in (data/'audit').glob('*.jsonl') for line in path.read_text().splitlines()]
    assert sum(e['kind']=='sar/substitution-certificate' for e in audit)==(0 if denied else 2)
    assert receipt['usage']['totalTokens']==80000
    # The deterministic adapter emitted two real native requests; synthetic
    # graph decisions are separate zero-provider-traffic native steps.
    assert sum(e['type']=='assistant/message' for e in events)==(3 if denied else 4)
    if denied:
        assert any(e['type']=='tool/result' and e['data']['message'].get('isError') for e in events)


def test_every_callback_gets_unique_external_extension_state(tmp_path):
    seen=[]
    def launch(argv,*,cwd,input_text,timeout,env):
        path=Path(env['DSH_HARNESSMM_DATA_DIRECTORY'])
        assert path.is_dir()
        assert not path.is_relative_to(Path(cwd))
        seen.append(path)
        return {'returncode':0,'status':'completed','stdout':json.dumps({'type':'harnessmm.receipt','status':'completed','answer':'{"instruction":"","supporting_task_ids":[]}','usage':None}),'stderr':''}
    cb=NativeCallbacks({'t':{'seed_files':{},'verifier_argv':[sys.executable,'-c','pass']}},dsh='dsh',provider='fake',model='fake',artifact_dir=tmp_path/'episodes',launch=launch)
    for request_id in ['first','second']:
        cb.optimize({'request_id':request_id,'identity':{'provider':'fake','model':'fake'},'training_evidence':[]})
    cb.execute({'request_id':'third','identity':{'provider':'fake','model':'fake'},'task':{'task_id':'t'},'phase':'train','arm':'baseline','codex_prompt':'test'})
    assert len(set(seen))==3
    assert all(path.parent==tmp_path/'episodes/extension-data' for path in seen)

def test_parent_timeout_is_not_relabelled_as_graceful_worker_block(tmp_path):
    def launch(*args,**kwargs):
        return {'status':'timeout','returncode':0,'stdout':json.dumps({'type':'harnessmm.receipt','status':'blocked','answer':'','usage':None}),'stderr':''}
    cb=NativeCallbacks({},dsh='dsh',model='test',provider='any',artifact_dir=tmp_path,launch=launch)
    result=cb.optimize({'request_id':'timed-out','identity':{'model':'test'},'training_evidence':[]})
    assert result['execution_status']=='timeout'
    assert result['usage']['total_tokens'] is None


def test_generated_python_bytecode_is_not_part_of_source_contract(tmp_path):
    from dsh_harnessmm_rsi.runner import collect_native_contract
    (tmp_path/'vendor').mkdir();(tmp_path/'vendor/source.py').write_text('x=1\n')
    before=collect_native_contract(tmp_path,None,'sdk')
    cache=tmp_path/'vendor/__pycache__';cache.mkdir();(cache/'source.cpython-314.pyc').write_bytes(b'generated cache')
    assert collect_native_contract(tmp_path,None,'sdk')==before
