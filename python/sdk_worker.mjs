// One native DSH SDK activity interval. NDJSON output preserves partial events.
import { pathToFileURL } from 'node:url';
import { readFileSync } from 'node:fs';
import {meterNotifications} from './sdk_meter.mjs';
const input=JSON.parse(readFileSync(0,'utf8'));
const sourceRoot=process.env.DSH_SOURCE_ROOT || '/home/sushi/Applications/deepseek-harness-source';
const {DeepSeekHarness}=await import(pathToFileURL(input.sdkModule || `${sourceRoot}/packages/sdk/client/lib/index.js`).href);
const {deriveTurnTokenUsage}=await import(pathToFileURL(input.meterModule || `${sourceRoot}/packages/llm/token-meter/lib/types/turn-usage.js`).href);
const emit=value=>process.stdout.write(JSON.stringify(value)+'\n');
if(typeof input.provider!=='string'||!input.provider.trim()||typeof input.model!=='string'||!input.model.trim()) throw new Error('explicit provider/model required');
// The native TypeScript SDK expects a JS entry, never a shell launcher.
const explicitDsh=input.dshBin && !/^#!.*(?:sh|bash)/.test(readFileSync(input.dshBin,'utf8').split('\n')[0]) ? input.dshBin : undefined;
const notifications=[];
let harness;
let interrupted=false;
const initialParent=process.ppid;
const parentMonitor=setInterval(()=>{if(process.ppid!==initialParent){interrupted=true;void harness?.close();}},250);
parentMonitor.unref();
process.on('SIGTERM',()=>{interrupted=true;void harness?.close();});
process.on('SIGINT',()=>{interrupted=true;void harness?.close();});

try{
  harness=new DeepSeekHarness({...(explicitDsh?{dshBin:explicitDsh}:{}),dshHome:input.dshHome,profile:input.profile||'sdk',patches:input.patches||[],cwd:input.cwd,processCwd:input.cwd,provider:input.provider,model:input.model,...(input.reasoningEffort?{reasoningEffort:input.reasoningEffort}:{}),initializeTimeoutMs:30000,requestTimeoutMs:input.timeoutMs,env:{...process.env,DSH_HOME:input.dshHome}});
  const result=await harness.run(input.prompt,{onNotification:notification=>{notifications.push(notification);emit({type:'harnessmm.notification',notification});}});
  const lastEnd=[...result.events].reverse().find(e=>e.type==='turn/end');
  const reason=lastEnd?.data?.reason?.kind;
  emit({type:'harnessmm.receipt',status:interrupted?'blocked':reason==='completed'?'completed':'failed',answer:result.finalResponse,usage:meterNotifications(notifications,deriveTurnTokenUsage),finishReason:reason||null,sessionId:result.sessionId,accounting:'native deriveTurnTokenUsage across all observed root and descendant turns',samplingSeedSupported:false});
}catch(error){
  emit({type:'harnessmm.receipt',status:interrupted?'blocked':/timeout/i.test(String(error))?'timeout':'failed',answer:'',usage:meterNotifications(notifications,deriveTurnTokenUsage),error:{name:error.name,message:String(error.message)},samplingSeedSupported:false});
}finally{
  clearInterval(parentMonitor);
  if(harness) await harness.close();
}
