from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
import threading
from contextlib import contextmanager

PINNED_REVISION = 'c8f19947e59feaa8103c05155bd79ef3eb084730'
USAGE_FIELDS = ('input_tokens','output_tokens','total_tokens','cache_read_tokens','cache_write_tokens','cost_usd')


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
    temp.replace(path)


def validate_route(provider,model,reasoning_effort):
    if not isinstance(provider,str) or not provider.strip() or not isinstance(model,str) or not model.strip():
        raise ValueError('explicit provider and model are required; inherit the current session route when invoked by extension')
    if reasoning_effort is not None and not isinstance(reasoning_effort,str):
        raise ValueError('reasoning_effort must be a string or omitted')


def load_corpus(path):
    value=json.loads(Path(path).read_text())
    if value.get('schema')!='dsh-harnessmm-corpus/v1' or not isinstance(value.get('name'),str) or not value['name'].startswith('local-'):
        raise ValueError('corpus must have local- name: original historical author benchmark reuse prohibited')
    tasks=value.get('tasks',[])
    ids=set()
    for task in tasks:
        if not isinstance(task.get('id'),str) or not task['id'] or task['id'] in ids:
            raise ValueError('unique nonempty task id required')
        ids.add(task['id'])
        if not isinstance(task.get('unit_id'),str) or not task['unit_id'] or not isinstance(task.get('public_prompt'),str) or not task['public_prompt'].strip():
            raise ValueError('unit_id and public_prompt required')
        for name, content in task.get('seed_files',{}).items():
            p=PurePosixPath(name)
            if (not isinstance(content,str) or p.is_absolute() or '..' in p.parts or not p.parts or '\\' in name or ':' in name or PureWindowsPath(name).drive or PureWindowsPath(name).root or any(part.rstrip(' .').upper().split('.')[0] in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))} for part in p.parts) or any(part.endswith((' ','.')) for part in p.parts)):
                raise ValueError('unsafe seed file path')
        argv=task.get('verifier_argv')
        if not isinstance(argv,list) or not argv or not all(isinstance(s,str) and s for s in argv):
            raise ValueError('verifier_argv must be nonempty strings')
    if not tasks:
        raise ValueError('empty corpus')
    return value


def normalize_events(stdout):
    receipts=[]
    for line in stdout.splitlines():
        try: event=json.loads(line)
        except json.JSONDecodeError: continue
        if isinstance(event,dict) and event.get('type')=='harnessmm.receipt': receipts.append(event)
    if len(receipts)>1: raise ValueError('duplicate native SDK receipt')
    usage=dict.fromkeys(USAGE_FIELDS)
    if not receipts: return '',usage
    receipt=receipts[0];raw=receipt.get('usage')
    if isinstance(raw,dict):
        total=raw.get('totalTokens');output=raw.get('outputTokens')
        if type(total) is int and type(output) is int and 0<=output<=total:
            usage['total_tokens']=total;usage['output_tokens']=output;usage['input_tokens']=total-output
        for dest,source in [('cache_read_tokens','cacheReadTokens'),('cache_write_tokens','cacheWriteTokens')]:
            if type(raw.get(source)) is int and 0<=raw[source]: usage[dest]=raw[source]
    return receipt.get('answer',''),usage


@contextmanager
def cancellation_signals():
    if threading.current_thread() is not threading.main_thread():
        yield;return
    initial_parent=os.getppid()
    stop_monitor=threading.Event()
    def monitor_parent():
        while not stop_monitor.wait(.25):
            if os.getppid()!=initial_parent:
                os.kill(os.getpid(),signal.SIGTERM);return
    monitor=threading.Thread(target=monitor_parent,name='harnessmm-parent-monitor',daemon=True)
    old={sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGINT)}
    def cancel(signum,frame): raise KeyboardInterrupt('RSI cancelled by signal '+str(signum))
    try:
        for sig in old: signal.signal(sig,cancel)
        monitor.start()
        yield
    finally:
        stop_monitor.set()
        for sig,handler in old.items(): signal.signal(sig,handler)


def launch_process(argv, *, cwd, input_text, timeout, env):
    start=time.monotonic()
    proc=subprocess.Popen(argv,cwd=cwd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env,start_new_session=(os.name!='nt'),creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0))
    status=None
    try:
        stdout,stderr=proc.communicate(input_text,timeout=timeout)
    except BaseException as error:
        status='timeout' if isinstance(error,subprocess.TimeoutExpired) else 'cancelled'
        def send(sig):
            if os.name == 'nt':
                # Windows has no os.killpg: terminate the process tree with taskkill /T.
                system_root=os.environ.get('SystemRoot',r'C:\Windows')
                taskkill=Path(system_root)/'System32'/'taskkill.exe'
                executable=str(taskkill) if taskkill.is_file() else 'taskkill'
                try:
                    result=subprocess.run([executable,'/PID',str(proc.pid),'/T','/F'],capture_output=True,timeout=8,check=False)
                    if result.returncode and proc.poll() is None: proc.kill()
                except (OSError,subprocess.TimeoutExpired):
                    if proc.poll() is None: proc.kill()
            else:
                try: os.killpg(proc.pid,sig)
                except ProcessLookupError: pass
        send(signal.SIGTERM)
        try: stdout,stderr=proc.communicate(timeout=4)
        except BaseException:
            send(signal.SIGKILL);stdout,stderr=proc.communicate()
        finally:
            # Terminate remaining descendants, even if their parent has exited.
            send(signal.SIGKILL)
        if not isinstance(error,(subprocess.TimeoutExpired,KeyboardInterrupt)): raise
    return {'returncode':proc.returncode,'stdout':stdout,'stderr':stderr,'status':status or ('completed' if proc.returncode==0 else 'failed'),'elapsed_seconds':time.monotonic()-start}


def collect_native_contract(extension_root,dsh_home,profile):
    paths=[]
    if extension_root:
        root=Path(extension_root).resolve()
        for name in ('index.mjs','controller.mjs','jobs.mjs','package.json','cordis.patch.yml'):
            path=root/name
            if path.is_file(): paths.append(path)
        if (root/'vendor').is_dir(): paths.extend(p for p in (root/'vendor').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.pyo'))
    if dsh_home:
        folder=Path(dsh_home).resolve()/'profiles'/profile
        for path in folder.iterdir() if folder.is_dir() else []:
            if not path.is_file() or 'node_modules' in path.parts: continue
            if path.suffix in ('.yml','.yaml','.json','.mjs','.js','.ts'):
                paths.append(path)
    return {str(p):digest(p.read_bytes()) for p in sorted(set(paths))}


class NativeCallbacks:
    def __init__(self,tasks,*,dsh,model,provider,artifact_dir,timeout=300,launch=launch_process,sdk_patch=None,profile="sdk",node="node",sdk_module=None,meter_module=None,dsh_home=None,reasoning_effort=None):
        self.tasks=tasks; resolved_dsh=shutil.which(dsh) or dsh
        self.dsh=str(Path(resolved_dsh).resolve()) if Path(resolved_dsh).exists() else resolved_dsh
        validate_route(provider,model,reasoning_effort)
        self.reasoning_effort=reasoning_effort or None
        self.dsh_home=dsh_home
        self.provider=provider;self.sdk_patch=sdk_patch;self.profile=profile;self.node=node
        root=Path(os.environ.get('DSH_SOURCE_ROOT','/home/sushi/Applications/deepseek-harness-source'))
        self.sdk_module=str(Path(sdk_module or root/'packages/sdk/client/lib/index.js').resolve())
        self.meter_module=str(Path(meter_module or root/'packages/llm/token-meter/lib/types/turn-usage.js').resolve())
        self.native_sources={str(path):digest(Path(path).read_bytes()) for path in (Path(__file__).parent.parent/'sdk_worker.mjs',Path(__file__).parent.parent/'sdk_meter.mjs',self.sdk_module,self.meter_module)}
        self.contract_roots=(os.environ.get('DSH_HARNESSMM_EXTENSION_ROOT') or str(Path(__file__).resolve().parents[2]),dsh_home,profile)
        for launch_file in (root/'apps/cli/src/bin.ts',root/'apps/cli/src/sdk-source.cordis.patch.yml',root/'apps/cli/tsconfig.json',root/'apps/cli/package.json'):
            if launch_file.is_file(): self.native_sources[str(launch_file.resolve())]=digest(launch_file.read_bytes())
        cli_manifest=root/'apps/cli/package.json'
        if cli_manifest.is_file():
            bin_value=json.loads(cli_manifest.read_text()).get('bin',{})
            bin_value=bin_value.get('dsh') if isinstance(bin_value,dict) else bin_value
            compiled=root/'apps/cli'/bin_value if isinstance(bin_value,str) else None
            if compiled and compiled.is_file(): self.native_sources[str(compiled.resolve())]=digest(compiled.read_bytes())
        self.native_sources.update(collect_native_contract(*self.contract_roots))
        self.initial_contract=collect_native_contract(*self.contract_roots)
        self.model=model; self.artifact_dir=Path(artifact_dir); self.timeout=timeout; self.launch=launch
        self.artifact_dir.mkdir(parents=True,exist_ok=True)
        self.cancelled=False
        self.source_sha256=digest(Path(__file__).read_bytes())
        native_path=Path(shutil.which(self.dsh) or self.dsh)
        self.binary_sha256=digest(native_path.read_bytes()) if native_path.is_file() else None

    def invoke(self,request,prompt,*,seed_files=None,actor=False):
        if collect_native_contract(*self.contract_roots)!=self.initial_contract:
            raise RuntimeError('native extension/profile contract changed during execution')
        for native_source,expected in self.native_sources.items():
            if digest(Path(native_source).read_bytes())!=expected: raise RuntimeError('native SDK source changed during execution: '+native_source)
        if self.cancelled: raise KeyboardInterrupt('previous native episode cancelled')
        if digest(Path(__file__).read_bytes())!=self.source_sha256:
            raise RuntimeError('adapter source changed during execution')
        native_path=Path(shutil.which(self.dsh) or self.dsh)
        if self.binary_sha256 is not None and digest(native_path.read_bytes())!=self.binary_sha256:
            raise RuntimeError('native DSH launcher changed during execution')
        env=os.environ.copy()
        episode_data=(self.artifact_dir/'extension-data'/request['request_id']).resolve()
        episode_data.mkdir(parents=True,exist_ok=True)
        env['DSH_HARNESSMM_DATA_DIRECTORY']=str(episode_data)
        env['DSH_HARNESSMM_ENABLED']='1' if actor and request.get('arm') not in (None,'baseline','noop') else '0'
        env['DSH_HARNESSMM_NO_POLICY']='1'
        env.pop('DSH_HARNESSMM_POLICY',None)
        with tempfile.TemporaryDirectory(prefix='dsh-harnessmm-episode-') as folder, tempfile.TemporaryDirectory(prefix='dsh-harnessmm-home-') as dsh_home:
            for name,content in (seed_files or {}).items():
                target=Path(folder)/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(content)
            worker=Path(__file__).parent.parent/'sdk_worker.mjs'
            argv=[self.node,str(worker)]
            worker_request={'prompt':prompt,'cwd':folder,'dshHome':str(Path(self.dsh_home).resolve()) if self.dsh_home else dsh_home,'dshBin':self.dsh,'profile':self.profile,'provider':self.provider,'model':self.model,'timeoutMs':int(self.timeout*1000),'patches':[str(Path(self.sdk_patch).resolve())] if self.sdk_patch else []}
            if self.reasoning_effort: worker_request['reasoningEffort']=self.reasoning_effort
            if self.sdk_module: worker_request['sdkModule']=self.sdk_module
            if self.meter_module: worker_request['meterModule']=self.meter_module
            try:
                result=self.launch(argv,cwd=folder,input_text=json.dumps(worker_request),timeout=self.timeout+10,env=env)
            except OSError as error:
                result={'returncode':None,'stdout':'','stderr':str(error),'status':'failed'}
            if result['status']=='cancelled':
                self.cancelled=True; result['status']='blocked'
            try:
                answer,usage=normalize_events(result['stdout'])
                for line in result['stdout'].splitlines():
                    try: event=json.loads(line)
                    except json.JSONDecodeError: continue
                    if isinstance(event,dict) and event.get('type')=='harnessmm.receipt' and event.get('status') in ('completed','failed','timeout','blocked'):
                        if result['status'] not in ('timeout','blocked','cancelled'):
                            result['status']=event['status'] if result['returncode']==0 or event['status']!='completed' else 'failed'
            except ValueError as error:
                answer=''; usage=dict.fromkeys(USAGE_FIELDS); result['metering_error']=str(error); result['status']='failed'
            verification=None
            if actor and self.cancelled:
                verification={'status':'blocked','returncode':None,'stdout':'','stderr':'cancelled before verifier'}
            elif actor:
                # The oracle exists only in the parent process/corpus, never the actor workspace
                # or prompt. A local trusted deterministic command executes after actor exit.
                try: verification=launch_process(self.tasks[request['task']['task_id']]['verifier_argv'],cwd=folder,input_text='',timeout=min(self.timeout,60),env=env)
                except OSError as error: verification={'status':'failed','returncode':None,'stderr':str(error),'stdout':''}
            artifact={'status':result.get('status'),'returncode':result.get('returncode'),'elapsed_seconds':result.get('elapsed_seconds'),
                      'stdout_sha256':digest(result.get('stdout','').encode()),'stderr_sha256':digest(result.get('stderr','').encode()),
                      'request_id':request['request_id'],'usage':usage,
                      'verification':None if verification is None else {'status':verification.get('status'),'returncode':verification.get('returncode'),'stdout_sha256':digest(verification.get('stdout','').encode()),'stderr_sha256':digest(verification.get('stderr','').encode())},
                      'runtime_mode':env['DSH_HARNESSMM_ENABLED'],'sampling_seed_supported':False,
                      'actor_prompt_sha256':digest(prompt.encode()),'native_runtime_contract':'official native DSH SDK; persistent HarnessMM extension when configured; author callbacks unchanged'}
            write_json(self.artifact_dir/(request['request_id']+'.json'),artifact)
        return result,answer,usage,verification

    def execute(self,request):
        task=self.tasks[request['task']['task_id']]
        result,answer,usage,verify=self.invoke(request,request['codex_prompt'],seed_files=task.get('seed_files'),actor=True)
        success=verify['returncode']==0 and verify['status']=='completed'
        value={'request_id':request['request_id'],'identity':request['identity'],'task_id':request['task']['task_id'],
               'execution_status':result['status'],'native_score':float(success),'success':success,'usage':usage,
               'provenance':{'adapter':'dsh-harnessmm/v1','artifact':request['request_id']+'.json','seed_applied':False,'verifier_result_sha256':digest(verify)}}
        if request['phase']=='train':
            value['feedback']='Native DSH SDK trajectory (TRAIN only):\n'+result['stdout']+'\nNative stderr:\n'+result['stderr']+'\nDeterministic verifier: '+('PASS' if success else 'FAIL')
        return value

    def optimize(self,request):
        prompt='You optimize a reusable procedural instruction using only the supplied TRAIN evidence. Return ONLY a JSON object with instruction (string), supporting_task_ids (array of unique task ID strings). An unsupported edit must be empty. Follow the objective and limits in this input:\n'+json.dumps(request,ensure_ascii=False)
        result,answer,usage,_=self.invoke(request,prompt)
        status=result['status']; instruction=''; support=[]; parse_error=None
        try:
            parsed=json.loads(answer)
            if set(parsed)!={'instruction','supporting_task_ids'} or not isinstance(parsed['instruction'],str) or not isinstance(parsed['supporting_task_ids'],list) or not all(isinstance(v,str) for v in parsed['supporting_task_ids']):
                raise ValueError('invalid optimizer output schema')
            instruction=parsed['instruction'];support=parsed['supporting_task_ids']
        except (ValueError,TypeError) as error:
            status='failed' if status=='completed' else status;parse_error=str(error)
        return {'request_id':request['request_id'],'identity':request['identity'],'execution_status':status,
                'instruction':instruction,'supporting_task_ids':support,'usage':usage,'provenance':{'artifact':request['request_id']+'.json','parse_error':parse_error}}


def verify_upstream():
    import phiagent
    root=Path(phiagent.__file__).parent.parent
    lock=json.loads(Path(__file__).with_name('upstream-lock.json').read_text())
    for relative,expected in lock['files'].items():
        if digest((root/relative).read_bytes())!=expected:
            raise RuntimeError('pinned upstream source changed: '+relative)
    return lock


def upstream_modules():
    verify_upstream()
    from phiagent.harness import codex_chisel as core, benchmark_partition
    from phiagent.harness.industrial_efficiency_rsi import IndustrialEfficiencyController
    return core,benchmark_partition,IndustrialEfficiencyController


def run_lifecycle(corpus_path,output,*,dsh='dsh',model=None,provider=None,iterations=2,timeout=300,run_id=None,callbacks=None,sdk_patch=None,profile='sdk',node='node',sdk_module=None,meter_module=None,dsh_home=None,reasoning_effort=None):
    validate_route(provider,model,reasoning_effort)
    core,partitioner,Controller=upstream_modules()
    corpus=load_corpus(corpus_path); output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    if any((output/name).exists() for name in ('policy.json','report.json','run.json')):
        raise ValueError('output already contains a run; use a fresh directory')
    corpus_hash=digest(Path(corpus_path).read_bytes())
    tasks=corpus['tasks']; by_id={t['id']:t for t in tasks}; groups={}
    for task in tasks: groups.setdefault(task['unit_id'],[]).append(task)
    records=[{'id':unit,'payload_sha256':digest(members),'public_task_sha256':digest([t['public_prompt'] for t in members])} for unit,members in sorted(groups.items())]
    partition=partitioner.build_partition(records,benchmark=corpus['name'],seed=20260928,independent_unit='declared coding family')
    if partition['counts']['train']<4: raise ValueError('at least 20 unique units required for two-fold support >=2')
    index=[{'task_id':t['id'],'unit_id':t['unit_id'],'public_prompt_sha256':digest(t['public_prompt'].encode())} for t in tasks]
    def split(name):
        units=set(partition['splits'][name])
        return [{'task_id':t['id'],'unit_id':t['unit_id'],'public_prompt':t['public_prompt']} for t in tasks if t['unit_id'] in units]
    native=callbacks or NativeCallbacks(by_id,dsh=dsh,model=model,provider=provider,artifact_dir=output/'episodes',timeout=timeout,sdk_patch=sdk_patch,profile=profile,node=node,sdk_module=sdk_module,meter_module=meter_module,dsh_home=dsh_home,reasoning_effort=reasoning_effort)
    dsh_path=Path(shutil.which(dsh) or dsh)
    sources={'deepseek_harness':digest(dsh_path.read_bytes()),'executor':digest(Path(__file__).read_bytes()),'optimizer':digest(Path(__file__).read_bytes()),'sdk_worker':digest((Path(__file__).parent.parent/'sdk_worker.mjs').read_bytes()),'scorer':digest(Path(corpus_path).read_bytes()),'corpus':digest(Path(corpus_path).read_bytes())}
    identity={'model':model,'runtime':'official_deepseek_harness_sdk','provider':provider,'reasoning_effort':reasoning_effort or 'provider-default','tools_contract':'native selected SDK profile; no replacement tools; fresh task workspace','provenance':'native DSH SDK with extension mode controlled per arm'}
    if hasattr(native,'native_sources'):
        sources.update({'native_'+str(index):sha for index,sha in enumerate(native.native_sources.values())})
    if hasattr(native,'native_sources'):
        identity['native_source_files_json']=json.dumps(native.native_sources,sort_keys=True,separators=(',',':'))
        identity['native_contract_roots_json']=json.dumps(native.contract_roots,separators=(',',':'))
    identity['sdk_profile']=profile
    identity['source_contract_sha256']=digest(sources)
    config=core.ChiselConfig(optimization_iterations=iterations,application='prompt_suffix')
    controller=Controller(partition=partition,task_index=index,execute=native.execute,optimize=native.optimize,execution_identity=identity,optimizer_identity={**identity,'role':'optimizer'},run_id=run_id or str(uuid.uuid4()),config=config)
    manifest={'schema':'dsh-harnessmm-run/v1','corpus_name':corpus['name'],'corpus_sha256':sources['corpus'],'upstream_revision':PINNED_REVISION,'source_hashes':sources,'partition':partition,'status':'running',
              'runtime_source_files':getattr(native,'native_sources',{}),'execution_identity':identity,'activation_route':{'provider':provider,'model':model,'reasoning_effort':reasoning_effort or None},'cross_route_transfer_validated':False,'sdk_profile':profile,'dsh_home_mode':'shared credential service; fresh explicitly owned sessions; no personal session reads' if dsh_home else 'fresh temporary home',
              'test_dispatch':'CodexChiselController.evaluate_test on IndustrialEfficiencyController; new independent local corpus only; upstream historical TEST prohibition retained in upstream source',
              'claim_scope':'Synthetic local coding corpus; no independent general coding benchmark claim; native graph availability must be verified separately'}
    write_json(output/'run.json',manifest)
    with cancellation_signals():
      try:
          controller.train(split('train'));
          if getattr(native,'cancelled',False): raise KeyboardInterrupt('native episode cancelled')
          write_json(output/'train-report.json',controller.report())
          if digest(Path(corpus_path).read_bytes())!=corpus_hash: raise RuntimeError('corpus changed after TRAIN')
          controller.select_validation(split('validation'));
          if getattr(native,'cancelled',False): raise KeyboardInterrupt('native episode cancelled')
          write_json(output/'validation-report.json',controller.report())
          policy=controller.freeze(source_hashes=sources);write_json(output/'policy.json',policy.to_dict())
          # Fresh local population only. Preserve the successor's original guard in upstream.
          core.CodexChiselController.evaluate_test(controller,lambda:split('test'),policy_sha256=policy.policy_sha256,source_sha256=policy.source_sha256)
          if getattr(native,'cancelled',False): raise KeyboardInterrupt('native episode cancelled')
          manifest['status']='complete';export_policy(output/'policy.json',output/'learned-instructions.md')
      except BaseException as error:
          manifest['status']='cancelled' if isinstance(error,KeyboardInterrupt) else 'failed';manifest['error']=type(error).__name__+': '+str(error)
          raise
      finally:
          write_json(output/'report.json',controller.report());write_json(output/'run.json',manifest)
      return controller.report()

def export_policy(policy_path, destination):
    core,_,_=upstream_modules(); raw=Path(policy_path).read_bytes(); policy=core.FrozenPolicy.from_dict(json.loads(raw)); value=policy.to_dict()
    text=value['candidate']['instruction']
    Path(destination).write_text(text+('\n' if text else ''))
    write_json(str(destination)+'.manifest.json',{'schema':'dsh-harnessmm-export/v1','policy_sha256':policy.policy_sha256,'policy_file_sha256':digest(raw),'instruction_file_sha256':digest(Path(destination).read_bytes()),'candidate_id':value['candidate']['id'],'enabled':value['candidate']['enabled'],'routing_required':True,'warning':'Plain text is for inspection. Deployment must use exact FrozenPolicy routing; do not apply globally.'})
    return value


def route_policy(policy_path, public_prompt):
    core,_,_=upstream_modules()
    raw=Path(policy_path).read_bytes()
    policy=core.FrozenPolicy.from_dict(json.loads(raw))
    frozen_identity=policy.to_dict()['sources']['execution_identity']
    frozen_files=json.loads(frozen_identity.get('native_source_files_json','{}'))
    for path,expected in frozen_files.items():
        if digest(Path(path).read_bytes())!=expected: raise RuntimeError('frozen native runtime source changed: '+path)
    roots=json.loads(frozen_identity.get('native_contract_roots_json','null'))
    if roots:
        current=collect_native_contract(*roots)
        if any(path not in frozen_files or frozen_files[path]!=sha for path,sha in current.items()):
            raise RuntimeError('frozen native extension/profile membership changed')
    applied=policy.apply(public_prompt)
    candidate=policy.to_dict()['candidate']
    instruction=candidate['instruction'] if applied['decision']['residual_id'] else ''
    rendered=applied['codex_prompt']
    if not rendered.startswith(public_prompt): raise ValueError('author prompt rendering changed public task prefix')
    prompt_suffix=rendered[len(public_prompt):]
    return {'schema':'dsh-harnessmm-route/v1','runtime_source_files':frozen_files,'instruction':instruction,'prompt_suffix':prompt_suffix,'policy_sha256':policy.policy_sha256,
            'source_sha256':policy.source_sha256,'policy_file_sha256':digest(raw),'route':applied['decision'],
            'public_prompt_sha256':digest(public_prompt.encode()),'application':policy.to_dict()['config']['application'],
            'max_residuals_per_task':1,'execution_identity':policy.to_dict()['sources']['execution_identity'],'activation_route':{'provider':policy.to_dict()['sources']['execution_identity'].get('provider'),'model':policy.to_dict()['sources']['execution_identity'].get('model'),'reasoning_effort':None if policy.to_dict()['sources']['execution_identity'].get('reasoning_effort')=='provider-default' else policy.to_dict()['sources']['execution_identity'].get('reasoning_effort')},'cross_route_transfer_validated':False}
