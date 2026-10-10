// All source timestamps are converted to Beijing calendar dates.
// Jobs process one API page per invocation to keep free-plan work bounded.
export const CONFIG = {
  'discord-latam': {platform:'Discord', region:'LATAM'},
  'discord-global': {platform:'Discord', region:'Global'},
  x: {platform:'X', region:'North America'},
  'youtube-mary': {platform:'YouTube', region:'Mary'},
};
export const dayAt = (value) => new Date(new Date(value).getTime()+8*3600e3).toISOString().slice(0,10);
export const shiftDay = (day, offset) => new Date(Date.parse(day+'T00:00:00Z')+offset*86400e3).toISOString().slice(0,10);
export const snowflake = (ms) => ((BigInt(ms)-1420070400000n)<<22n).toString();
export const messageDay = (id) => dayAt(Number((BigInt(id)>>22n)+1420070400000n));
export function xCreatedAt(value) {
  const match=String(value).match(/^\w{3} (\w{3}) (\d{1,2}) (\d{2}:\d{2}:\d{2}) ([+-]\d{4}) (\d{4})$/);
  if(!match)return value;
  const [,month,day,time,offset,year]=match;
  const index=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'].indexOf(month)+1;
  return `${year}-${String(index).padStart(2,'0')}-${day.padStart(2,'0')}T${time}${offset.slice(0,3)}:${offset.slice(3)}`;
}
export function deltas(previous, current, date) {
  const adjacent = previous?.date === shiftDay(date,-1);
  return {
    netGrowth: adjacent && previous.audience != null && current.audience != null ? current.audience-previous.audience : null,
    views: adjacent && previous.monthViews != null && current.monthViews != null && previous.date.slice(0,7)===date.slice(0,7) ? current.monthViews-previous.monthViews : (date.endsWith('-01') ? current.monthViews : null),
    interactions: adjacent && previous.monthInteractions != null && current.monthInteractions != null && previous.date.slice(0,7)===date.slice(0,7) ? current.monthInteractions-previous.monthInteractions : (date.endsWith('-01') ? current.monthInteractions : null),
  };
}
export function publicationCounts(dates, date) {
  return {publishedCount:dates.filter(d=>d===date).length, monthPublished:dates.filter(d=>d.slice(0,7)===date.slice(0,7) && d<=date).length};
}
const now = () => new Date().toISOString();
const json = (data,status=200) => Response.json(data,{status,headers:{'Access-Control-Allow-Origin':'https://social-media-daily-report.pages.dev','Cache-Control':'no-store'}});
async function request(url, init={}) {
  const response=await fetch(url,{...init,signal:AbortSignal.timeout(20000)});
  if (!response.ok) {
    const error=new Error(`Source HTTP ${response.status}`);
    error.status=response.status;
    error.retry=Math.max(1,Number(response.headers.get('retry-after')||60));
    throw error;
  }
  return response.json();
}
const discord=(env,path)=>request('https://discord.com/api/v10'+path,{headers:{Authorization:`Bot ${env.DISCORD_BOT_TOKEN}`}});
const youtube=(env,resource,params)=>request('https://www.googleapis.com/youtube/v3/'+resource+'?'+new URLSearchParams({...params,key:env.YOUTUBE_API_KEY}));
async function enqueue(env,id,entity,date,kind,payload) {
  await env.DB.prepare('INSERT OR IGNORE INTO jobs(id,entity,date,kind,payload,updated_at) VALUES(?,?,?,?,?,?)').bind(id,entity,date,kind,JSON.stringify(payload),now()).run();
}
async function readPoint(env,entity,date) {
  const row=await env.DB.prepare('SELECT data FROM metrics WHERE entity=? AND date=?').bind(entity,date).first();
  return row ? JSON.parse(row.data) : null;
}
async function savePoint(env,entity,date,patch) {
  const old=await readPoint(env,entity,date);
  const point={date,audience:null,netGrowth:null,views:null,interactions:null,monthViews:null,monthInteractions:null,activeMembers:null,activeRate:null,publishedCount:null,monthPublished:null,...old,...patch};
  await env.DB.prepare('INSERT INTO metrics(entity,date,data,collected_at) VALUES(?,?,?,?) ON CONFLICT(entity,date) DO UPDATE SET data=excluded.data,collected_at=excluded.collected_at').bind(entity,date,JSON.stringify(point),now()).run();
}
async function savePart(env,job,key,data) {
  await env.DB.prepare('INSERT OR REPLACE INTO parts(job_id,page_key,data) VALUES(?,?,?)').bind(job.id,key,JSON.stringify(data)).run();
}
async function parts(env,id) {
  const result=await env.DB.prepare('SELECT data FROM parts WHERE job_id=?').bind(id).all();
  return result.results.map(row=>JSON.parse(row.data));
}
async function continueJob(env,job,payload,delay=0) {
  await env.DB.prepare("UPDATE jobs SET payload=?,state='pending',attempts=0,ready_at=?,lease_until=0,updated_at=? WHERE id=?").bind(JSON.stringify(payload),Date.now()+delay,now(),job.id).run();
  return false;
}
async function startDay(env,date) {
  const servers=[['discord-latam',env.DISCORD_GUILD_ID],['discord-global','1041526489247653958']];
  for (const [entity,guild] of servers) await enqueue(env,`${entity}:${date}`,entity,date,'guild',{guild});
  await enqueue(env,`x:${date}`,'x',date,'x-start',{});
  await enqueue(env,`youtube-mary:${date}`,'youtube-mary',date,'yt-channel',{});
}
async function guildJob(env,job,p) {
  const guild=await discord(env,`/guilds/${p.guild}?with_counts=true`);
  if (!Number.isInteger(guild.approximate_member_count) || guild.approximate_member_count<=0) throw new Error('Discord member count unavailable');
  const audience=guild.approximate_member_count, previous=await readPoint(env,job.entity,shiftDay(job.date,-1));
  await savePoint(env,job.entity,job.date,{audience,...deltas(previous,{audience},job.date),status:'collecting_messages',collectedAt:now(),audiencePrecision:'approximate'});
  await enqueue(env,job.id+':channels',job.entity,job.date,'dc-channels',p);
  return true;
}
async function channelsJob(env,job,p) {
  const channels=await discord(env,`/guilds/${p.guild}/channels`);
  const ids=channels.filter(c=>[0,5].includes(c.type)).map(c=>c.id);
  if (!ids.length) throw new Error('Discord text channels unavailable');
  const history=await env.DB.prepare('SELECT date,data FROM metrics WHERE entity=? AND date>=? AND date<?').bind(job.entity,job.date.slice(0,7)+'-01',job.date).all();
  const known=new Map(history.results.map(r=>[r.date,JSON.parse(r.data)]));
  let earliest=job.date;
  for(let day=job.date.slice(0,7)+'-01';day<job.date;day=shiftDay(day,1))if(known.get(day)?.publishedCount==null||known.get(day)?.activeMembers==null){earliest=day;break;}
  const start=Date.parse(earliest+'T00:00:00+08:00'),end=Date.parse(shiftDay(job.date,1)+'T00:00:00+08:00');
  await env.DB.batch(ids.map(id=>env.DB.prepare('INSERT OR IGNORE INTO jobs(id,entity,date,kind,payload,updated_at) VALUES(?,?,?,?,?,?)').bind(`${job.entity}:${job.date}:message:${id}`,job.entity,job.date,'dc-messages',JSON.stringify({channel:id,cursor:snowflake(start),end}),now())));
  await enqueue(env,`${job.entity}:${job.date}:finish`,job.entity,job.date,'dc-finish',{earliest});
  return true;
}
async function messagesJob(env,job,p) {
  let messages;
  try {messages=await discord(env,`/channels/${p.channel}/messages?limit=100&after=${p.cursor}`);}
  catch(e) {
    if ([403,404].includes(e.status)) {await savePart(env,job,'skipped',{skipped:true}); return true;}
    throw e;
  }
  messages.sort((a,b)=>BigInt(a.id)<BigInt(b.id)?-1:1);
  const days={};let stop=false;
  for (const message of messages) {
    const ms=Number((BigInt(message.id)>>22n)+1420070400000n);
    if(ms>=p.end){stop=true;break;}
    if (!message.author?.id || message.author.bot) continue;
    const day=messageDay(message.id);days[day]??={count:0,users:[]};days[day].count++;
    if(!days[day].users.includes(message.author.id))days[day].users.push(message.author.id);
  }
  await savePart(env,job,p.cursor,{days});
  const next=messages.at(-1)?.id;
  if (!stop && messages.length===100 && BigInt(next)>BigInt(p.cursor)) return continueJob(env,job,{...p,cursor:next});
  return true;
}
async function finishDiscord(env,job,p) {
  const status=await env.DB.prepare("SELECT state,COUNT(*) AS n FROM jobs WHERE entity=? AND date=? AND kind='dc-messages' GROUP BY state").bind(job.entity,job.date).all();
  if(status.results.some(r=>r.state==='failed')) throw new Error('Discord history scan incomplete');
  if(status.results.some(r=>r.state!=='done')) return continueJob(env,job,p,60000);
  const result=await env.DB.prepare("SELECT p.data FROM parts p JOIN jobs j ON p.job_id=j.id WHERE j.entity=? AND j.date=? AND j.kind='dc-messages'").bind(job.entity,job.date).all();
  const days={};let skipped=0;
  for(const row of result.results) {
    const part=JSON.parse(row.data);if(part.skipped){skipped++;continue;}
    for(const [date,data] of Object.entries(part.days||{})){days[date]??={count:0,users:new Set()};days[date].count+=data.count;for(const id of data.users)days[date].users.add(id);}
  }
  if(skipped===status.results.reduce((n,r)=>n+r.n,0))throw new Error('No Discord channels readable');
  const history=await env.DB.prepare('SELECT date,data FROM metrics WHERE entity=? AND date>=? AND date<=?').bind(job.entity,job.date.slice(0,7)+'-01',job.date).all();
  const known=new Map(history.results.map(r=>[r.date,JSON.parse(r.data)]));
  let cumulative=0;const updates=[];
  for(let date=job.date.slice(0,7)+'-01';date<=job.date;date=shiftDay(date,1)) {
    const old=known.get(date);
    const day=days[date]||{count:0,users:new Set()};cumulative+=date<p.earliest?old.publishedCount:day.count;
    if(date<p.earliest)continue;
    const patch={};
    if(date===job.date || old?.publishedCount==null)patch.publishedCount=day.count;
    if(date===job.date || old?.monthPublished==null)patch.monthPublished=cumulative;
    if(date===job.date || old?.activeMembers==null)patch.activeMembers=day.users.size;
    if(old?.audience!=null && (date===job.date || old.activeRate==null))patch.activeRate=day.users.size/old.audience;
    patch.status=date===job.date?'success':old?.status||'partial_historical_no_snapshot';
    const point={date,audience:null,netGrowth:null,views:null,interactions:null,monthViews:null,monthInteractions:null,activeMembers:null,activeRate:null,publishedCount:null,monthPublished:null,...old,...patch};
    updates.push(env.DB.prepare('INSERT INTO metrics(entity,date,data,collected_at) VALUES(?,?,?,?) ON CONFLICT(entity,date) DO UPDATE SET data=excluded.data,collected_at=excluded.collected_at').bind(job.entity,date,JSON.stringify(point),now()));
  }
  if(updates.length)await env.DB.batch(updates);
  return true;
}
async function ytChannel(env,job) {
  const data=await youtube(env,'channels',{part:'snippet,statistics,contentDetails',id:env.YOUTUBE_CHANNEL_ID});
  const channel=data.items?.[0];if(!channel)throw new Error('YouTube channel unavailable');
  const audience=channel.statistics.hiddenSubscriberCount?null:Number(channel.statistics.subscriberCount);
  if(audience!=null && !Number.isFinite(audience))throw new Error('YouTube subscriber count unavailable');
  const uploads=channel.contentDetails?.relatedPlaylists?.uploads;if(!uploads)throw new Error('YouTube uploads unavailable');
  await savePart(env,job,'channel',{audience});
  return continueJob(env,job,{stage:'playlist',uploads,token:'',audience});
}
async function ytPlaylist(env,job,p) {
  const data=await youtube(env,'playlistItems',{part:'contentDetails',playlistId:p.uploads,maxResults:'50',...(p.token?{pageToken:p.token}:{})});
  const items=(data.items||[]).map(x=>({id:x.contentDetails.videoId,date:dayAt(x.contentDetails.videoPublishedAt)}));
  await savePart(env,job,'playlist:'+p.token,{items});
  const cutoff=shiftDay(job.date,-29).slice(0,7)+'-01';
  if(data.nextPageToken && !items.some(x=>x.date<cutoff))return continueJob(env,job,{...p,token:data.nextPageToken});
  const all=(await parts(env,job.id)).flatMap(x=>x.items||[]).filter(x=>x.date>=cutoff && x.date<=job.date);
  return continueJob(env,job,{stage:'videos',ids:[...new Set(all.map(x=>x.id))],offset:0,audience:p.audience});
}
async function ytVideos(env,job,p) {
  const ids=p.ids.slice(p.offset,p.offset+50);
  if(ids.length) {
    const data=await youtube(env,'videos',{part:'snippet,statistics',id:ids.join(',')});
    const videos=(data.items||[]).map(v=>({id:v.id,date:dayAt(v.snippet.publishedAt),views:Number(v.statistics.viewCount||0),interactions:Number(v.statistics.likeCount||0)+Number(v.statistics.commentCount||0)}));
    await savePart(env,job,'videos:'+p.offset,{videos});
  }
  if(p.offset+50<p.ids.length)return continueJob(env,job,{...p,offset:p.offset+50});
  const videos=(await parts(env,job.id)).flatMap(x=>x.videos||[]);
  const month=videos.filter(v=>v.date.slice(0,7)===job.date.slice(0,7)&&v.date<=job.date);
  const current={audience:p.audience,monthViews:month.reduce((n,v)=>n+v.views,0),monthInteractions:month.reduce((n,v)=>n+v.interactions,0),...publicationCounts(videos.map(v=>v.date),job.date)};
  const prev=await readPoint(env,job.entity,shiftDay(job.date,-1));
  await savePoint(env,job.entity,job.date,{...current,...deltas(prev,current,job.date),status:'success',collectedAt:now()});
  await fillPublicationHistory(env,job,videos.map(v=>v.date));
  return true;
}
async function fillPublicationHistory(env,job,dates) {
  const history=await env.DB.prepare('SELECT date,data FROM metrics WHERE entity=? AND date>=? AND date<?').bind(job.entity,shiftDay(job.date,-28),job.date).all();
  const known=new Map(history.results.map(r=>[r.date,JSON.parse(r.data)]));const updates=[];
  for(let date=shiftDay(job.date,-28);date<job.date;date=shiftDay(date,1)) {
    const old=known.get(date),counts=publicationCounts(dates,date),patch={};
    if(old?.publishedCount==null)patch.publishedCount=counts.publishedCount;
    if(old?.monthPublished==null)patch.monthPublished=counts.monthPublished;
    if(Object.keys(patch).length)updates.push(env.DB.prepare('INSERT INTO metrics(entity,date,data,collected_at) VALUES(?,?,?,?) ON CONFLICT(entity,date) DO UPDATE SET data=excluded.data,collected_at=excluded.collected_at').bind(job.entity,date,JSON.stringify({date,...old,...patch,status:old?.status||'partial_historical_no_snapshot'}),now()));
  }
  if(updates.length)await env.DB.batch(updates);
}
async function xStart(env,job) {
  const start=shiftDay(job.date,-28).slice(0,7)+'-01';
  const cap=Math.min(Number(env.APIFY_MAX_CHARGE_USD||0.005),0.005);
  const data=await request(`https://api.apify.com/v2/acts/kaitoeasyapi~twitter-x-data-tweet-scraper-pay-per-result-cheapest/runs?build=latest0225&maxTotalChargeUsd=${cap}`,{method:'POST',headers:{Authorization:`Bearer ${env.APIFY_API_TOKEN}`,'Content-Type':'application/json'},body:JSON.stringify({twitterContent:`from:${env.X_USERNAME} since:${start} until:${shiftDay(job.date,1)}`,queryType:'Latest',maxItems:1000})});
  // Persist run ID before polling; never restart a paid run while waiting.
  return continueJob(env,job,{stage:'poll',runId:data.data.id,started:Date.now()},60000);
}
async function xPoll(env,job,p) {
  const data=await request(`https://api.apify.com/v2/actor-runs/${p.runId}`,{headers:{Authorization:`Bearer ${env.APIFY_API_TOKEN}`}});
  const run=data.data;
  if(['READY','RUNNING','TIMING-OUT','ABORTING'].includes(run.status)) {
    if(Date.now()-p.started>30*60000)throw new Error('Apify run timed out; inspect existing run before restarting');
    return continueJob(env,job,p,60000);
  }
  if(run.status!=='SUCCEEDED')throw new Error('Apify run failed');
  if(Number(run.usageTotalUsd||0)>=Math.min(Number(env.APIFY_MAX_CHARGE_USD||0.005),0.005)*0.98)throw new Error('Apify charge cap reached; incomplete data');
  return continueJob(env,job,{...p,stage:'dataset',dataset:run.defaultDatasetId});
}
async function xDataset(env,job,p) {
  const raw=await request(`https://api.apify.com/v2/datasets/${p.dataset}/items?clean=true&format=json`,{headers:{Authorization:`Bearer ${env.APIFY_API_TOKEN}`}});
  const items=[...new Map(raw.filter(x=>x.id&&!x.noResults).map(x=>[String(x.id),x])).values()];
  if(items.length>=1000)throw new Error('X post safety limit reached');
  const posts=items.filter(x=>x.createdAt).map(x=>({...x,date:dayAt(xCreatedAt(x.createdAt))})).filter(x=>x.date<=job.date);
  const author=posts.find(x=>Number(x.author?.followers)>0)?.author;
  if(!author)throw new Error('X follower count unavailable');
  const month=posts.filter(x=>x.date.slice(0,7)===job.date.slice(0,7));
  const current={audience:Number(author.followers),monthViews:month.reduce((n,x)=>n+Number(x.viewCount||0),0),monthInteractions:month.reduce((n,x)=>n+['likeCount','replyCount','retweetCount','quoteCount'].reduce((sum,k)=>sum+Number(x[k]||0),0),0),...publicationCounts(posts.map(x=>x.date),job.date)};
  const prev=await readPoint(env,job.entity,shiftDay(job.date,-1));
  await savePoint(env,job.entity,job.date,{...current,...deltas(prev,current,job.date),status:'success',collectedAt:now()});
  await fillPublicationHistory(env,job,posts.map(x=>x.date));return true;
}
async function processJob(env,id) {
  const claimed=await env.DB.prepare("UPDATE jobs SET state='running',lease_until=?,updated_at=? WHERE id=? AND ready_at<=? AND (state='pending' OR (state='running' AND lease_until<?)) RETURNING *").bind(Date.now()+90000,now(),id,Date.now(),Date.now()).first();
  if(!claimed)return;
  const p=JSON.parse(claimed.payload);let done=false;
  try {
    switch(claimed.kind){
      case 'guild':done=await guildJob(env,claimed,p);break;
      case 'dc-channels':done=await channelsJob(env,claimed,p);break;
      case 'dc-messages':done=await messagesJob(env,claimed,p);break;
      case 'dc-finish':done=await finishDiscord(env,claimed,p);break;
      case 'yt-channel':done=p.stage==='playlist'?await ytPlaylist(env,claimed,p):p.stage==='videos'?await ytVideos(env,claimed,p):await ytChannel(env,claimed);break;
      case 'x-start':done=p.stage==='poll'?await xPoll(env,claimed,p):p.stage==='dataset'?await xDataset(env,claimed,p):await xStart(env,claimed);break;
      default:throw new Error('Unknown job');
    }
    if(done)await env.DB.prepare("UPDATE jobs SET state='done',error=NULL,lease_until=0,updated_at=? WHERE id=?").bind(now(),id).run();
  }catch(e){
    const attempts=claimed.attempts+1;
    // Do not blindly retry a start POST: a network timeout can conceal a paid run.
    const unsafeStart=claimed.kind==='x-start'&&!p.stage;
    const failed=attempts>=5||unsafeStart;
    await env.DB.prepare('UPDATE jobs SET state=?,attempts=?,ready_at=?,lease_until=0,error=?,updated_at=? WHERE id=?').bind(failed?'failed':'pending',attempts,Date.now()+Math.max(60000,(e.retry||60)*1000),String(e.message).slice(0,160),now(),id).run();
  }
}
async function drain(env) {
  const jobs=await env.DB.prepare("SELECT id FROM jobs WHERE ready_at<=? AND (state='pending' OR (state='running' AND lease_until<?)) ORDER BY CASE kind WHEN 'guild' THEN 0 WHEN 'dc-finish' THEN 2 ELSE 1 END,updated_at LIMIT 12").bind(Date.now(),Date.now()).all();
  // Each child invocation has its own CPU and subrequest allowance.
  await Promise.all(jobs.results.map(row=>env.SELF.fetch('https://internal/internal/job',{method:'POST',headers:{Authorization:`Bearer ${env.ADMIN_TOKEN}`,'Content-Type':'application/json'},body:JSON.stringify({id:row.id})}).then(r=>r.body?.cancel())));
}
async function publicData(env) {
  const [rows,status]=await Promise.all([env.DB.prepare('SELECT entity,data,collected_at FROM metrics ORDER BY date').all(),env.DB.prepare("SELECT entity,date,state,error,updated_at FROM jobs j WHERE state!='done' AND date=(SELECT MAX(date) FROM jobs latest WHERE latest.entity=j.entity) ORDER BY date DESC LIMIT 100").all()]);
  const entities=Object.keys(CONFIG).map(id=>({id,...CONFIG[id],points:rows.results.filter(row=>row.entity===id).map(row=>JSON.parse(row.data))}));
  return {generatedAt:rows.results.map(x=>x.collected_at).sort().at(-1)||null,timezone:'Asia/Shanghai',entities,health:status.results.map(x=>({...x,error:x.state==='failed'?x.error:null}))};
}
export default {
  async scheduled(event,env,ctx) {
    const stamp=new Date(event.scheduledTime);
    if(stamp.getUTCHours()===1&&stamp.getUTCMinutes()===10){
      const cutoff=shiftDay(dayAt(stamp),-35);
      await env.DB.batch([
        env.DB.prepare("DELETE FROM parts WHERE job_id IN (SELECT id FROM jobs WHERE state='done' AND date<?)").bind(cutoff),
        env.DB.prepare("DELETE FROM jobs WHERE state='done' AND date<?").bind(cutoff),
      ]);
    }
    if(stamp.getUTCHours()===1&&stamp.getUTCMinutes()===40)await startDay(env,shiftDay(dayAt(stamp),-1));
    ctx.waitUntil(drain(env));
  },
  async fetch(req,env,ctx) {
    const path=new URL(req.url).pathname;
    if(req.method==='GET'&&path==='/metrics')return json(await publicData(env));
    if(req.method==='GET'&&path==='/health')return json({service:'social-media-collector',schedule:'09:40 Asia/Shanghai',jobs:(await publicData(env)).health});
    if(req.method!=='POST'||!env.ADMIN_TOKEN||req.headers.get('Authorization')!==`Bearer ${env.ADMIN_TOKEN}`)return json({error:'Unauthorized'},401);
    const body=await req.json();
    if(path==='/internal/job'){await processJob(env,body.id);return json({ok:true});}
    if(path==='/admin/run'){await startDay(env,shiftDay(dayAt(new Date()),-1));ctx.waitUntil(drain(env));return json({ok:true});}
    if(path==='/admin/drain'){ctx.waitUntil(drain(env));return json({ok:true});}
    if(path==='/admin/seed') {
      for(const entity of body.entities||[])if(CONFIG[entity.id])for(const point of entity.points||[]) {
        await env.DB.prepare('INSERT OR IGNORE INTO metrics(entity,date,data,collected_at) VALUES(?,?,?,?)').bind(entity.id,point.date,JSON.stringify(point),body.generatedAt||now()).run();
      }
      return json({ok:true});
    }
    return json({error:'Not found'},404);
  },
};
