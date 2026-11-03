/** Background RSI jobs and exact-route frozen-policy selection. */
import fs from 'node:fs';import path from 'node:path';import {spawn,spawnSync} from 'node:child_process';import {createHash,randomUUID} from 'node:crypto';import {fileURLToPath} from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url));
export const routeKey=r=>createHash('sha256').update(JSON.stringify([r.provider,r.model,r.reasoning_effort??null])).digest('hex').slice(0,24);
export function sameRoute(a,b){return !!a&&!!b&&a.provider===b.provider&&a.model===b.model&&(a.reasoning_effort??null)===(b.reasoning_effort??null);}
const alive=pid=>{if(!Number.isSafeInteger(pid)||pid<1)return false;try{process.kill(pid,0);return true;}catch(e){if(e.code==='ESRCH')return false;if(e.code==='EPERM')return true;throw e;}};
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const save=(p,v)=>{fs.mkdirSync(path.dirname(p),{recursive:true,mode:0o700});const t=p+'.'+randomUUID()+'.tmp';fs.writeFileSync(t,JSON.stringify(v,null,2)+'\n',{mode:0o600});fs.renameSync(t,p);};
export function deployable(report,policy){const t=report.test;return report.state==='complete'&&policy.candidate.enabled&&t?.baseline.complete_native_scores===true&&t?.chisel.complete_native_scores===true&&t.baseline.mean_native_score>0&&t.chisel.mean_native_score>=t.baseline.mean_native_score&&Number.isFinite(t.baseline.measured_total_tokens)&&Number.isFinite(t.chisel.measured_total_tokens)&&t.chisel.measured_total_tokens<t.baseline.measured_total_tokens;}
export class ImprovementJobs{
 constructor(config,record){this.config=config;this.record=record;this.child=null;this.cache=new Map();this.disposed=false;this.statePath=path.join(config.dataDirectory,'improvement.json');this.lockPath=path.join(config.dataDirectory,'improvement.lock');this.lockToken=null;try{this.state=read(this.statePath);}catch(e){if(e.code!=='ENOENT')throw e;this.state={status:'idle',routes:{}};}if(this.state.status==='running'&&!alive(this.state.pid)){this.state.status='interrupted';save(this.statePath,this.state);}}
 environment(){return {...process.env,PYTHONPATH:[path.join(root,'python'),path.join(root,'vendor/harnessmm'),process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),DSH_HARNESSMM_EXTENSION_ROOT:root,DSH_HARNESSMM_TRAINING:'1',DSH_HARNESSMM_NO_POLICY:'1'};}
 status(){if(!this.child&&fs.existsSync(this.statePath))this.state=read(this.statePath);return {...this.state,active:!!this.child||(this.state.status==='running'&&alive(this.state.pid))};}
 start(route,reason='manual'){
  if(this.disposed)throw Error('Extension is unloading');if(!this.config.allowUnsafeCodeExecution)throw Error('RSI executes generated code without a sandbox. Explicitly set allowUnsafeCodeExecution=true to opt in');if(this.child)throw Error('A HarnessMM improvement run is already active');
  if(!route?.provider||!route?.model)throw Error('Select a native provider/model before starting improvement');
  const directory=path.join(this.config.dataDirectory,'runs',new Date().toISOString().replaceAll(':','-')+'-'+randomUUID().slice(0,8));fs.mkdirSync(directory,{recursive:true,mode:0o700});
  const args=['-m','dsh_harnessmm_rsi','train','--corpus',this.config.corpusPath,'--output',directory,'--dsh-bin',this.config.dshExecutable,'--dsh-home',this.config.dshHome,'--profile',this.config.trainingProfile,'--provider',route.provider,'--model',route.model,'--iterations',String(this.config.iterations),'--timeout',String(this.config.episodeTimeoutMs/1000)];if(route.reasoning_effort)args.push('--reasoning-effort',route.reasoning_effort);
  this.lockToken=randomUUID();
  const acquire=()=>{const fd=fs.openSync(this.lockPath,'wx',0o600);fs.writeFileSync(fd,JSON.stringify({token:this.lockToken,hostPid:process.pid}));fs.closeSync(fd);};
  try{acquire();}catch(e){if(e.code!=='EEXIST')throw e;let lock;try{lock=read(this.lockPath);}catch{throw Error('An existing HarnessMM lock is not readable; inspect its owner before retrying');}if(alive(lock.hostPid))throw Error('Another DSH process already owns a HarnessMM improvement run');fs.unlinkSync(this.lockPath);acquire();}
  const log=fs.openSync(path.join(directory,'runner.log'),'a',0o600);
  const child=spawn(this.config.pythonExecutable,args,{env:this.environment(),stdio:['ignore',log,log],detached:process.platform!=='win32'});fs.closeSync(log);this.child=child;
  this.state={...this.state,status:'running',directory,route,reason,startedAt:Date.now(),pid:child.pid??null,error:null};save(this.statePath,this.state);this.record({kind:'harnessmm/rsi-started',route,directory,reason});
  child.once('error',error=>this.finish(child,directory,route,null,error.message));child.once('exit',(code,signal)=>this.finish(child,directory,route,code,signal?`terminated by ${signal}`:null));return this.status();
 }
 finish(child,directory,route,code,error){if(this.child!==child)return;this.child=null;try{if(read(this.lockPath).token===this.lockToken)fs.unlinkSync(this.lockPath);}catch(e){if(e.code!=='ENOENT')this.record({kind:'harnessmm/lock-release-error',error:e.message});}let activated=false;
  try{if(code===0){const run=read(path.join(directory,'run.json'));const report=read(path.join(directory,'report.json'));const policy=read(path.join(directory,'policy.json'));if(!sameRoute(run.activation_route,route))throw Error('RSI output route changed');
   if(deployable(report,policy)){const pointer={directory,route,policy_sha256:policy.policy_sha256,source_sha256:policy.source_sha256,activatedAt:Date.now()};save(path.join(this.config.dataDirectory,'policies',routeKey(route)+'.json'),pointer);this.cache.clear();activated=true;}
  }}catch(e){error=e.message;code=1;}
  this.state={...this.state,status:code===0?'complete':'failed',finishedAt:Date.now(),error:error??null,activated,routes:{...this.state.routes,[routeKey(route)]:Date.now()}};save(this.statePath,this.state);this.record({kind:'harnessmm/rsi-finished',route,directory,code,error:error??null,activated});
 }
 route(route,prompt){
  if(process.env.DSH_HARNESSMM_NO_POLICY==='1')return '';
  const key=routeKey(route)+':'+createHash('sha256').update(prompt).digest('hex');
  const pointerPath=path.join(this.config.dataDirectory,'policies',routeKey(route)+'.json');if(!fs.existsSync(pointerPath))return '';
  const pointer=read(pointerPath);if(!sameRoute(pointer.route,route))return '';
  const result=spawnSync(this.config.pythonExecutable,['-m','dsh_harnessmm_rsi','route','--policy',path.join(pointer.directory,'policy.json')],{input:prompt,encoding:'utf8',timeout:10000,maxBuffer:1048576,env:this.environment()});
  if(result.status!==0)throw Error('Frozen HarnessMM policy verification failed: '+String(result.stderr).slice(0,600));const value=JSON.parse(result.stdout);
  if(!sameRoute(value.activation_route,route)||value.policy_sha256!==pointer.policy_sha256||value.source_sha256!==pointer.source_sha256)throw Error('Frozen HarnessMM policy identity changed');
  if(typeof value.instruction!=='string')throw Error('Invalid policy instruction');if(value.application!=='prompt_suffix'||typeof value.prompt_suffix!=='string')throw Error('Policy deployment must match evaluated prompt_suffix');this.cache.set(key,value.prompt_suffix);return value.prompt_suffix;
 }
 async dispose(){this.disposed=true;await this.cancel();}
 async cancel(){
  const child=this.child;
  if(!child){if(this.status().active)throw Error('This improvement run is owned by another DSH instance; cancel it in that instance');return;}
  if(child.exitCode!==null||child.signalCode!==null)return;
  await new Promise(resolve=>{
    let timer;
    const done=()=>{if(timer)clearTimeout(timer);resolve();};
    child.once('exit',done);
    const stop=(force)=>{
      try{
        if(process.platform==='win32'){
          // Stop the complete SDK/Python subtree, not just the top-level process.
          const systemRoot=process.env.SystemRoot||'C:\\Windows';
          const exe=path.join(systemRoot,'System32','taskkill.exe');
          const cmd=fs.existsSync(exe)?exe:'taskkill';
          const result=spawnSync(cmd,['/PID',String(child.pid),'/T','/F'],{windowsHide:true,timeout:8000,stdio:'ignore'});
          if(result.error)throw result.error;
          if(result.status!==0&&child.exitCode===null)child.kill('SIGKILL');
        }else process.kill(-child.pid,force?'SIGKILL':'SIGTERM');
      }catch(error){
        if(error.code!=='ESRCH'){
          this.record({kind:'harnessmm/rsi-stop-error',error_code:error.code||'unknown'});
          try{child.kill('SIGKILL');}catch{}
        }
      }
    };
    stop(false);
    timer=setTimeout(()=>{if(child.exitCode===null)stop(true);},5000);
    timer.unref();
  });
 }
}
