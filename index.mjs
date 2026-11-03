/** Provider-independent native HarnessMM extension and protected RSI jobs. */
import fs from 'node:fs';import path from 'node:path';import os from 'node:os';import {fileURLToPath} from 'node:url';import {createHash,randomUUID} from 'node:crypto';
import {createUserMessage,LlmError} from '@deepseek-ai/dsh-llm';
import z from '@deepseek-ai/schemastery';import {defineTool} from '@deepseek-ai/dsh-tools';
import {SessionController,graphInstruction,appendReceiptMetadata,decodeReceipt} from './controller.mjs';import {ImprovementJobs,routeKey} from './jobs.mjs';import {bestEffortStatsWrite,safeAuditEvent} from './security_utils.mjs';
const root=path.dirname(fileURLToPath(import.meta.url));
export const name='harnessmm';export const inject=['llm','tools','systemPrompt','agents'];
export const Config=z.object({enabled:z.boolean().default(true),autoImprove:z.boolean().default(false),allowManualImprove:z.boolean().default(false),allowUnsafeCodeExecution:z.boolean().default(false),autoImproveAfterTurns:z.number().step(1).min(1).default(20),autoImproveCooldownMs:z.number().step(1).min(60000).default(86400000),iterations:z.number().step(1).min(1).max(8).default(2),episodeTimeoutMs:z.number().step(1).min(10000).max(1800000).default(300000),maximumCandidates:z.number().step(1).min(1).max(16).default(16),maximumFastSteps:z.number().step(1).min(1).max(16).default(8),maximumPublicBytes:z.number().step(1).min(1024).max(65536).default(65536),dataDirectory:z.string().default(''),pythonExecutable:z.string().default('python3'),dshExecutable:z.string().default('dsh'),dshHome:z.string().default(''),trainingProfile:z.string().default('harnessmm-training'),corpusPath:z.string().default('')});
/** Mount reversible native listeners; no provider registration or core loop is replaced. */
export function apply(ctx,raw){
 const home=raw.dshHome||process.env.DSH_HOME||path.join(os.homedir(),'.dsh');const config={...raw,dshHome:home,dataDirectory:raw.dataDirectory||process.env.DSH_HARNESSMM_DATA_DIRECTORY||path.join(home,'storages/harnessmm'),corpusPath:raw.corpusPath||path.join(root,'corpora/synthetic-python-v1.json')};
 fs.mkdirSync(config.dataDirectory,{recursive:true,mode:0o700});
 const statsPath=path.join(config.dataDirectory,'stats.json');let stats={slowCalls:0,substitutions:0,graphsAuthored:0,turns:0,routeTurns:{}};try{stats={...stats,...JSON.parse(fs.readFileSync(statsPath,'utf8'))};}catch(e){if(e.code!=='ENOENT')ctx.logger.warn('HarnessMM statistics could not be loaded (%s)',e.code??'unknown');}
 const flush=()=>bestEffortStatsWrite(fs,statsPath,stats,message=>ctx.logger.warn('%s',message));
 const states=new Map(),routes=new Map(),busy=new Set(),policyBindings=new Map(),executed=new Set();let disposed=false;
 const enabled=()=>config.enabled&&process.env.DSH_HARNESSMM_ENABLED!=='0';
 const record=(id,event)=>{const audit=path.join(config.dataDirectory,'audit',createHash('sha256').update(String(id)).digest('hex')+'.jsonl');try{fs.mkdirSync(path.dirname(audit),{recursive:true,mode:0o700});fs.appendFileSync(audit,JSON.stringify(safeAuditEvent(id,event))+'\n',{mode:0o600});}catch(error){ctx.logger.warn('HarnessMM audit not saved (%s)',error.code??'unknown');}if(event.kind==='sar/substitution-certificate')stats.substitutions++;if(event.kind==='sar/slow-call')stats.slowCalls++;if(event.kind==='sar/bank-authored')stats.graphsAuthored++;flush();};
 const jobs=new ImprovementJobs(config,event=>record('improvement',event));
 const policy=()=>({version:6,enabled:true,maximum_candidates:config.maximumCandidates,maximum_fast_steps:config.maximumFastSteps,maximum_public_bytes:config.maximumPublicBytes});
 const state=id=>{if(!states.has(id))states.set(id,new SessionController({policy:policy(),record:e=>record(id,e)}));return states.get(id);};
 ctx.systemPrompt.section({name:'harnessmm:graph',order:180,interpolate:false,text:()=>enabled()?graphInstruction(policy()):''});
 ctx.on('agent/pre-step',async({agent,messages},next)=>{const decision=await next();if(decision.kind!=='enter'||!enabled()||process.env.DSH_HARNESSMM_TRAINING==='1')return decision;
  const user=messages.filter(m=>m.role==='user'&&m.source?.kind!=='harnessmm').at(-1);if(!user)return decision;policyBindings.delete(agent.id);if(user.content?.length!==1||user.content[0].type!=='text')return decision;
  const text=(user.content??[]).filter(c=>c.type==='text').map(c=>c.text).join('\n');
  const route={provider:agent.options.provider,model:agent.options.model,reasoning_effort:agent.options.reasoningEffort??null};
  const known=routes.get(agent.id);if(!known||routeKey(known)!==routeKey(route))return decision;
  try{const suffix=jobs.route(route,text);if(!suffix)return decision;
   const content=[...user.content];const last=content.findLastIndex(c=>c.type==='text');if(last<0)return decision;
   content[last]={...content[last],text:content[last].text+suffix};
   const replacement=createUserMessage({content,source:{kind:'harnessmm',form:'notice',summary:'Frozen TRAIN-derived task suffix; native route '+JSON.stringify(route)}});
   policyBindings.set(agent.id,route);record(agent.id,{kind:'harnessmm/policy-applied',route,publicTaskSha256:createHash('sha256').update(text).digest('hex')});
   return {...decision,messages:decision.messages.map(m=>m.id===user.id?replacement:m)};
  }catch(e){ctx.logger.warn('HarnessMM policy not applied: %s',e.message);record(agent.id,{kind:'harnessmm/policy-rejected',error:e.message});return decision;}
 });
 ctx.on('llm/stream',function(options,next){
  if(disposed||!enabled()||!options.sessionId||options.purpose)return next();
  const route={provider:options.provider,model:options.model,reasoning_effort:options.reasoningEffort??null};routes.set(options.sessionId,route);
  const bound=policyBindings.get(options.sessionId);if(bound&&routeKey(bound)!==routeKey(route)){policyBindings.delete(options.sessionId);throw new LlmError('HarnessMM learned policy route changed before dispatch; no provider request was sent. Retry this task to use ordinary reasoning.','harnessmm-policy-route-changed');}
  return state(options.sessionId).stream(options,next,'native-'+randomUUID());
 });
 ctx.on('tools/post-execute',async(exec,result,next)=>{const decision=await next();return enabled()?appendReceiptMetadata(exec,result,decision):decision;});
 ctx.on('tools/execute',async(exec,next)=>{executed.add(String(exec.agent?.id)+':'+exec.callId);return next();});
 ctx.on('tools/result',(exec,result)=>{const id=exec.agent?.id;const c=states.get(id);const key=String(id)+':'+exec.callId;const ran=executed.delete(key);if(!c?.pendingCalls.has(exec.callId))return;const text=result.content.length===1&&result.content[0].type==='text'?result.content[0].text:'';const observation={...decodeReceipt(text,{requireAttestation:['bash','pwsh'].includes(exec.name)}),executed:ran&&!result.isError};try{c.observe({call_id:exec.callId,name:exec.name,arguments:exec.arguments,result:{observation:JSON.stringify(observation),native_content:result.content,is_error:result.isError}});}catch(e){record(id,{kind:'harnessmm/receipt-rejected',error:e.message});c.pendingCalls.delete(exec.callId);}});
 ctx.on('agent/status',({agent,status})=>{if(status==='running'){busy.add(agent.id);states.get(agent.id)?.reset();}else{const wasBusy=busy.delete(agent.id);if(wasBusy&&process.env.DSH_HARNESSMM_TRAINING!=='1'){stats.turns++;const route=routes.get(agent.id);if(route){const key=routeKey(route);stats.routeTurns[key]=(stats.routeTurns[key]??0)+1;if(config.autoImprove&&config.allowUnsafeCodeExecution&&stats.routeTurns[key]>=config.autoImproveAfterTurns&&busy.size===0&&!jobs.child&&Date.now()-(jobs.state.routes[key]??0)>=config.autoImproveCooldownMs){try{jobs.start(route,'idle-after-completed-turns');stats.routeTurns[key]=0;}catch(e){ctx.logger.warn('HarnessMM improvement did not start: %s',e.message);}}}flush();}}});
 ctx.on('agent/disposed',({agent})=>{states.delete(agent.id);routes.delete(agent.id);policyBindings.delete(agent.id);busy.delete(agent.id);});
 const output={schema:{type:'object',additionalProperties:false,properties:{result:{type:'json',required:true}}},render:(_args,v)=>[{type:'text',text:JSON.stringify(v.result)}]};
 ctx.tools.register(defineTool({name:'harnessmm_status',description:'Inspect HarnessMM guarded execution counts, current native provider route and protected self-improvement job. Does not start model calls.',parameters:{},output,async execute(_args,exec){return {result:{enabled:enabled(),providerIndependent:true,stats,route:routes.get(exec.agent?.id)??null,improvement:jobs.status(),dataDirectory:config.dataDirectory,selector:'unique locally guarded action; otherwise original model reasoning',selfImprovement:'TRAIN feedback -> protected validation -> frozen policy -> paired TEST; no model-weight training'}};}}));
 ctx.tools.register(defineTool({name:'harnessmm_improve',description:'Start one background HarnessMM training/validation/freeze/test run on the configured isolated coding corpus using the current native provider/model, or explicit provider/model. Uses model calls and returns a run receipt; inspect harnessmm_status for outcome.',parameters:{provider:{type:'string'},model:{type:'string'},reasoningEffort:{type:'string'}},output,async execute(args,exec){if(!config.allowManualImprove)throw Error('HarnessMM manual improvement disabled: set allowManualImprove=true and allowUnsafeCodeExecution=true explicitly');if((args.provider&&!args.model)||(!args.provider&&args.model))throw Error('Supply provider and model together');const current=routes.get(exec.agent?.id);const route=args.provider?{provider:args.provider,model:args.model,reasoning_effort:args.reasoningEffort??null}:args.reasoningEffort?{...current,reasoning_effort:args.reasoningEffort}:current;return {result:jobs.start(route)};}}));
 ctx.tools.register(defineTool({name:'harnessmm_cancel',description:'Cancel the active background HarnessMM improvement run and wait for its owned native workers to stop.',parameters:{},output,async execute(){await jobs.cancel();return {result:jobs.status()};}}));
 ctx.effect(()=>async()=>{disposed=true;await jobs.dispose();states.clear();policyBindings.clear();flush();});
}
