// Only public summaries are exposed. Administrative routes stay inaccessible.
export async function onRequestGet({params,env}) {
  const path=Array.isArray(params.path)?params.path.join('/'):params.path;
  if(!['metrics','health'].includes(path))return new Response('Not found',{status:404});
  return env.COLLECTOR.fetch(new Request('https://internal/'+path));
}
