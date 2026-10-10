import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import worker,{dayAt,shiftDay,snowflake,messageDay,deltas,publicationCounts} from '../src/worker.mjs';

function environment() {
  const sqlite=new DatabaseSync(':memory:');sqlite.exec(readFileSync(new URL('../schema.sql',import.meta.url),'utf8'));
  const DB={prepare(sql){let args=[];return {bind(...values){args=values;return this;},async run(){return sqlite.prepare(sql).run(...args);},async first(){return sqlite.prepare(sql).get(...args)||null;},async all(){return {results:sqlite.prepare(sql).all(...args)};}};},async batch(statements){return Promise.all(statements.map(s=>s.run()));}};
  return {env:{DB,ADMIN_TOKEN:'test-admin',DISCORD_BOT_TOKEN:'test-bot',DISCORD_GUILD_ID:'guild',WORKER_URL:'https://collector.test'},sqlite};
}
const context={waitUntil(){}};
const call=(env,path,body,authorized=true)=>worker.fetch(new Request('https://collector.test'+path,{method:'POST',headers:{'Content-Type':'application/json',...(authorized?{Authorization:'Bearer test-admin'}:{})},body:JSON.stringify(body)}),env,context);
test('Beijing midnight and snowflake calendar boundaries',()=>{
  assert.equal(dayAt('2026-10-01T16:00:00Z'),'2026-10-02');
  assert.equal(messageDay(snowflake(Date.parse('2026-10-01T16:00:00Z'))),'2026-10-02');
  assert.equal(shiftDay('2026-10-01',-1),'2026-09-30');
});
test('missing days never become one-day growth; real zero baseline works',()=>{
  assert.equal(deltas({date:'2026-10-01',audience:10},{audience:15},'2026-10-03').netGrowth,null);
  assert.deepEqual(deltas({date:'2026-10-01',audience:10,monthViews:0,monthInteractions:0},{audience:9,monthViews:5,monthInteractions:2},'2026-10-02'),{netGrowth:-1,views:5,interactions:2});
});
test('new month never subtracts previous month totals',()=>{
  assert.equal(deltas({date:'2026-09-30',monthViews:100},{monthViews:2,monthInteractions:0},'2026-10-01').views,2);
  assert.deepEqual(publicationCounts(['2026-09-30','2026-10-01','2026-10-02','2026-10-02'],'2026-10-02'),{publishedCount:2,monthPublished:3});
});
test('admin routes reject anonymous requests and public metrics contain no secret',async()=>{
  const {env}=environment();assert.equal((await call(env,'/admin/run',{},false)).status,401);
  const response=await worker.fetch(new Request('https://collector.test/metrics'),env,context);
  const text=await response.text();assert(!text.includes('test-admin'));assert(!text.includes('test-bot'));
});
test('seed is idempotent and cannot replace an existing valid snapshot',async()=>{
  const {env}=environment();
  await call(env,'/admin/seed',{entities:[{id:'x',points:[{date:'2026-10-01',audience:10,views:0}]}]});
  await call(env,'/admin/seed',{entities:[{id:'x',points:[{date:'2026-10-01',audience:20,views:null}]}]});
  const row=await env.DB.prepare('SELECT data FROM metrics WHERE entity=?').bind('x').first();assert.equal(JSON.parse(row.data).audience,10);assert.equal(JSON.parse(row.data).views,0);
});
test('Discord captures audience before scanning messages and does not overwrite on repeated dispatch',async()=>{
  const {env}=environment();const realFetch=globalThis.fetch;let count=0;
  globalThis.fetch=async()=>{count++;return Response.json({approximate_member_count:123});};
  try{
    await env.DB.prepare('INSERT INTO jobs(id,entity,date,kind,payload,updated_at) VALUES(?,?,?,?,?,?)').bind('guild-job','discord-latam','2026-10-02','guild',JSON.stringify({guild:'guild'}),'').run();
    await call(env,'/internal/job',{id:'guild-job'});await call(env,'/internal/job',{id:'guild-job'});
    assert.equal(count,1);
    const row=await env.DB.prepare('SELECT data FROM metrics WHERE entity=?').bind('discord-latam').first();const p=JSON.parse(row.data);
    assert.equal(p.audience,123);assert.equal(p.netGrowth,null);assert.equal(p.activeMembers,null);assert(p.collectedAt);
  }finally{globalThis.fetch=realFetch;}
});
test('failed source count is never saved as zero',async()=>{
  const {env}=environment();const realFetch=globalThis.fetch;globalThis.fetch=async()=>new Response('',{status:403});
  try{
    await env.DB.prepare('INSERT INTO jobs(id,entity,date,kind,payload,updated_at) VALUES(?,?,?,?,?,?)').bind('guild-job','discord-latam','2026-10-02','guild',JSON.stringify({guild:'guild'}),'').run();
    await call(env,'/internal/job',{id:'guild-job'});
    assert.equal((await env.DB.prepare('SELECT COUNT(*) AS n FROM metrics').first()).n,0);
    assert.equal((await env.DB.prepare('SELECT state FROM jobs').first()).state,'pending');
  }finally{globalThis.fetch=realFetch;}
});
test('Apify start timeouts do not automatically create another paid run',async()=>{
  const {env}=environment();const realFetch=globalThis.fetch;globalThis.fetch=async()=>{throw new Error('network timeout');};
  try{
    await env.DB.prepare('INSERT INTO jobs(id,entity,date,kind,payload,updated_at) VALUES(?,?,?,?,?,?)').bind('x-job','x','2026-10-02','x-start','{}','').run();
    await call(env,'/internal/job',{id:'x-job'});
    assert.equal((await env.DB.prepare('SELECT state FROM jobs').first()).state,'failed');
  }finally{globalThis.fetch=realFetch;}
});
test('Discord historical message fill keeps missing member snapshots empty and deduplicates active users',async()=>{
  const {env}=environment();
  await call(env,'/admin/seed',{entities:[{id:'discord-latam',points:[{date:'2026-10-02',audience:100,collectedAt:'test'}]}]});
  for(const id of ['a','b']) {
    await env.DB.prepare('INSERT INTO jobs(id,entity,date,kind,payload,state,updated_at) VALUES(?,?,?,?,?,?,?)').bind(id,'discord-latam','2026-10-02','dc-messages','{}','done','').run();
    await env.DB.prepare('INSERT INTO parts(job_id,page_key,data) VALUES(?,?,?)').bind(id,'page',JSON.stringify({days:{'2026-10-01':{count:2,users:['same']},'2026-10-02':{count:1,users:['same']}}})).run();
  }
  await env.DB.prepare('INSERT INTO jobs(id,entity,date,kind,payload,updated_at) VALUES(?,?,?,?,?,?)').bind('finish','discord-latam','2026-10-02','dc-finish',JSON.stringify({earliest:'2026-10-01'}),'').run();
  await call(env,'/internal/job',{id:'finish'});
  const old=JSON.parse((await env.DB.prepare('SELECT data FROM metrics WHERE entity=? AND date=?').bind('discord-latam','2026-10-01').first()).data);
  const current=JSON.parse((await env.DB.prepare('SELECT data FROM metrics WHERE entity=? AND date=?').bind('discord-latam','2026-10-02').first()).data);
  assert.equal(old.audience,null);assert.equal(old.activeRate,null);assert.equal(old.publishedCount,4);assert.equal(old.activeMembers,1);
  assert.equal(current.monthPublished,6);assert.equal(current.activeRate,0.01);assert.equal(current.status,'success');
});
