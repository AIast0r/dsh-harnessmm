import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {bestEffortStatsWrite, safeAuditEvent} from '../security_utils.mjs';
import {ImprovementJobs} from '../jobs.mjs';

test('Windows EPERM replacing stats is nonfatal and temp file is removed',()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'harnessmm-hardening-'));
 try{
  const target=path.join(dir,'stats.json');fs.writeFileSync(target,'{"old":true}');
  const warnings=[];
  const proxy={...fs,renameSync(){const e=new Error('Windows sharing violation');e.code='EPERM';throw e;}};
  assert.equal(bestEffortStatsWrite(proxy,target,{turns:100},message=>warnings.push(message)),false);
  assert.equal(fs.readFileSync(target,'utf8'),'{"old":true}');
  assert.equal(fs.readdirSync(dir).length,1);
  assert.equal(warnings.length,1);
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});

test('statistics can still be persisted on success',()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'harnessmm-hardening-'));
 try{
  const target=path.join(dir,'stats.json');
  assert.equal(bestEffortStatsWrite(fs,target,{turns:10}),true);
  assert.equal(JSON.parse(fs.readFileSync(target,'utf8')).turns,10);
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});

test('audit drops private tool payloads, model replies, errors and session id',()=>{
 const event=safeAuditEvent('private-session',{kind:'sar/substitution-certificate',
  exact_arguments:{command:'cat .env; echo SUPERSECRET'},native_receipt:{stdout:'SUPERSECRET'},
  request:{apiKey:'SUPERSECRET'},response:'SUPERSECRET',error:'SUPERSECRET',
  bank_sha256:'f'.repeat(64),slow_requests_at_boundary:0,valid_substitution:true});
 const serialized=JSON.stringify(event);
 assert.equal(serialized.includes('SUPERSECRET'),false);
 assert.equal(serialized.includes('private-session'),false);
 assert.equal(event.bank_sha256,'f'.repeat(64));
 assert.equal(event.valid_substitution,true);
 assert.equal(safeAuditEvent('id',{kind:'secret token value'}).kind,'unknown');
});

test('unsandboxed training cannot start without opt-in',()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'harnessmm-rsi-gate-'));
 try{
  const jobs=new ImprovementJobs({dataDirectory:dir,allowUnsafeCodeExecution:false},()=>{});
  assert.throws(()=>jobs.start({provider:'test',model:'model'}),/sandbox|Explicitly/i);
  assert.equal(fs.readdirSync(dir).length,0);
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
