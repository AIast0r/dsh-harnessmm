/** Keyless native DSH SDK integration fixture. No provider/network requests. */
import fs from 'node:fs';
import {LlmAdapter} from '@deepseek-ai/dsh-llm';
export const name='harnessmm-native-graph-fixture';
export const inject=['llm','tools'];
const command=label=>`echo ${label} >> sequence.txt; printf ${label}_OK`;
const args=label=>({command:command(label),description:`Native keyless fixture ${label}`});
const node=(id,predecessor,label)=>({candidate_id:id,predecessor_id:predecessor,tool:'bash',arguments:args(label),guard:{return_code:0},required_receipt_fields:['return_code'],expected_local_cost:{selector_upper_tokens:8192},dependency_ids:[]});
class FixtureAdapter extends LlmAdapter{
 async resolveModel(provider,model){return {provider,id:model,name:model,contextWindow:128000};}
 async *stream(options){
  const file=process.env.HARNESSMM_FIXTURE_REQUESTS;
  const previous=fs.existsSync(file)?fs.readFileSync(file,'utf8').trim().split('\n').filter(Boolean).length:0;
  fs.appendFileSync(file,JSON.stringify({provider:options.provider,model:options.model,purpose:options.purpose??null,index:previous+1})+'\n');
  const text=previous===0?`<CHISEL_PLAN>${JSON.stringify({candidates:[node('A','root','A'),node('B','A','B')]})}</CHISEL_PLAN>`:'NATIVE_GRAPH_FIXTURE_DONE';
  yield {type:'block-start',index:0,blockType:'text'};
  yield {type:'text-delta',index:0,text};
  yield {type:'block-end',index:0,block:{type:'text',text}};
  if(previous===0){const argumentsText=JSON.stringify(args('root'));
   yield {type:'block-start',index:1,blockType:'tool-call'};
   yield {type:'tool-call-delta',index:1,id:'root',name:'bash',argumentsDelta:argumentsText};
   yield {type:'block-end',index:1,block:{type:'tool-call',id:'root',name:'bash',arguments:argumentsText}};
  }
  yield {type:'usage',usage:{inputTokens:35000,outputTokens:5000,totalTokens:40000,cacheReadTokens:0,cacheWriteTokens:0}};
  yield {type:'finish',reason:{kind:previous===0?'tool-calls':'stop'}};
 }
}
export function apply(ctx){
 ctx.llm.registerAdapter(['fixture-alpha','fixture-beta'],new FixtureAdapter());
 if(process.env.HARNESSMM_FIXTURE_DENY_A==='1')ctx.on('tools/pre-execute',async(exec,next)=>exec.name==='bash'&&exec.arguments.description==='Native keyless fixture A'?{kind:'deny',reason:'native fixture policy denied A'}:next());
}
