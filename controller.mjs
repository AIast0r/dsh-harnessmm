/** Provider-independent native adapter around the authors' unmodified graph controller. */
import {createHash,createHmac,randomBytes} from 'node:crypto';
import {ExecutableSubdag,deterministicAdmission} from './vendor/sar_v2.mjs';
import {planInstruction} from './vendor/cot_jev.mjs';
const hash=x=>createHash('sha256').update(JSON.stringify(x)).digest('hex');
const receiptKey=randomBytes(32);
const sign=(body,meta)=>createHmac('sha256',receiptKey).update(JSON.stringify([body,meta])).digest('hex');
const MARKER='\n<HARNESSMM_RECEIPT>';
/** Decode logged receipts. Unknown fields remain absent; no success is inferred from arbitrary output. */
export function decodeReceipt(text,{requireAttestation=false}={}){
 const result={stdout:text,native_text:text};
 const at=text.lastIndexOf(MARKER);
 if(at>=0&&text.endsWith('</HARNESSMM_RECEIPT>')){
  try{const meta=JSON.parse(text.slice(at+MARKER.length,-'</HARNESSMM_RECEIPT>'.length));
   const {signature,...fields}=meta;
   if(requireAttestation&&signature!==sign(text.slice(0,at),fields))return result;
   if(Number.isSafeInteger(meta.return_code))result.return_code=meta.return_code;
   if(typeof meta.stderr==='string'||meta.stderr===null)result.stderr=meta.stderr;
   result.stdout=text.slice(0,at);
  }catch(error){if(!(error instanceof SyntaxError))throw error;}
  return result;
 }
 if(requireAttestation)return result;
 try{const v=JSON.parse(text);if(v&&typeof v==='object'&&!Array.isArray(v)){
  if(Number.isSafeInteger(v.return_code))result.return_code=v.return_code;
  else if(Number.isSafeInteger(v.exitCode)&&v.kind!=='background'&&v.kind!=='promoted'&&!v.aborted&&!v.timedOut&&v.signal==null)result.return_code=v.exitCode;
  if(typeof v.stdout==='string')result.stdout=v.stdout;
  else if(typeof v.stdout?.text==='string')result.stdout=v.stdout.text;
  if(typeof v.stderr==='string'||v.stderr===null)result.stderr=v.stderr;
  else if(typeof v.stderr?.text==='string')result.stderr=v.stderr.text;
 }}catch(error){if(!(error instanceof SyntaxError))throw error;}
 return result;
}
/** Add logged, actual foreground exit metadata without duplicating large stdout. */
export function appendReceiptMetadata(exec,result,decision){
 if(decision.kind!=='accept'||decision.content!==undefined||decision.value!==undefined||result.isError||!['bash','pwsh'].includes(exec.name))return decision;
 const v=result.value;
 if(v?.kind!=='foreground'||!Number.isSafeInteger(v.exitCode)||v.aborted||v.timedOut||v.signal!==null||result.content.length!==1||result.content[0].type!=='text')return decision;
 const meta={return_code:v.exitCode};
 if(typeof v.stderr?.text==='string'&&!v.stderr.truncated)meta.stderr=v.stderr.text;
 return {...decision,content:[{type:'text',text:result.content[0].text+MARKER+JSON.stringify({...meta,signature:sign(result.content[0].text,meta)})+'</HARNESSMM_RECEIPT>'}]};
}
/** Keep the authors' exact graph schema while adapting their terminal example to DSH's catalog. */
export function graphInstruction(policy){
 return planInstruction(policy)+'\nDSH integration: choose exact names and literal arguments from the native tool catalog; the example terminal tool is not a required tool name. DSH bash uses {command:"..."}. For bash/pwsh, the logged HARNESSMM_RECEIPT provides an actual foreground return_code; no marker means that field is unknown. The adapter stdout is the original displayed result body before that marker. Use stdout_contains only for an explicit literal, and do not infer success from arbitrary text. Other tools may use literal text guards. Unknown fields, errors, changed instructions and ambiguous eligible actions return to the original reasoning model. Do not bank harnessmm_improve or control tools.\n';
}
export class SessionController{
 constructor({policy,record}){this.policy=policy;this.record=record;this.route=null;this.controller=null;this.seen=new Set();this.pendingCalls=new Map();this.slowTokens=0;this.count=0;}
 setSlowUsage(total){if(Number.isSafeInteger(total)&&total>=0)this.slowTokens=total;}
 reset(){this.route=null;this.controller=null;this.seen.clear();this.pendingCalls.clear();this.slowTokens=0;}
 ensure(options){const key=JSON.stringify([options.provider,options.model,options.reasoningEffort??'']);if(key===this.route)return;
  this.reset();this.route=key;
  this.controller=new ExecutableSubdag({policy:this.policy,model:options.model,record:e=>{if(e.kind==='jev/compiled-native-action')this.pendingCalls.set(e.call.id,e.call);this.record(e);},request:()=>{throw Error('No verified native finite-label interface; selector must abstain');}});
  const prepare=this.controller.prepare.bind(this.controller);
  this.controller.router.prepareContext=context=>{
   const a=deterministicAdmission(context,this.controller.slowTokens,true);
   if(a.eligible.length!==1){this.record({kind:'harnessmm/selector-abstention',reason:'no_verified_finite_label_readout',eligible:a.eligible.length});return null;}
   const id=`chisel_${context.bank.sha256.slice(0,24)}_${a.eligible[0].candidate.label}`;
   if(this.seen.has(id))return null;
   return prepare(context);
  };
 }
 observe(event){if(!this.controller||!this.pendingCalls.has(event.call_id))return;
  this.controller.observeTool(event);this.pendingCalls.delete(event.call_id);
 }
 async *stream(options,next,attemptId){
  if(options.signal?.aborted)return;
  const key=JSON.stringify([options.provider,options.model,options.reasoningEffort??'']);
  const prior=this.route===null||this.route===key?this.slowTokens:0;this.ensure(options);this.setSlowUsage(prior);this.controller.slowTokens=this.slowTokens;
  const names=new Map(options.messages.flatMap(m=>(m.content??[]).filter(c=>c.type==='tool-call').map(c=>[c.id,c.name])));
  const messages=options.messages.map(m=>m.role==='tool'&&m.content?.length===1&&m.content[0].type==='text'?{...m,content:[{type:'text',text:JSON.stringify(decodeReceipt(m.content[0].text,{requireAttestation:['bash','pwsh'].includes(names.get(m.toolCallId))}))}]}:m);
  const self=this;
  const slow=async function*(){for await(const chunk of next()){
   if(chunk.type==='usage'&&Number.isSafeInteger(chunk.usage.totalTokens))self.setSlowUsage(chunk.usage.totalTokens);
   yield chunk;
  }};
  for await(const chunk of this.controller.stream({...options,messages},slow,attemptId??`boundary-${++this.count}`)){
   if(options.signal?.aborted)return;
   if(chunk.type==='block-end'&&chunk.block.type==='tool-call'&&chunk.block.id.startsWith('chisel_'))this.seen.add(chunk.block.id);
   yield chunk;
  }
 }
}
