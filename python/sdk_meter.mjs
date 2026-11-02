export function meterNotifications(all,deriveTurnTokenUsage){
  const bySession=new Map();
  for(const n of all){
    if(n.method!=='session.event' || !n.params?.event) continue;
    const id=n.params.sessionId;
    const events=bySession.get(id)||[];events.push(n.params.event);bySession.set(id,events);
  }
  const usages=[];
  for(const events of bySession.values()){
    let turn;
    for(const event of events){
      if(event.type==='turn/start'){
        if(turn) return null;
        turn=[event];
      }else if(turn){
        turn.push(event);
        if(event.type==='turn/end'){
          const usage=deriveTurnTokenUsage(turn);
          if(!usage) return null;
          usages.push(usage);turn=undefined;
        }
      }
    }
    if(turn) return null;
  }
  if(!usages.length) return null;
  const sum=key=>usages.every(u=>Number.isSafeInteger(u[key]) && u[key]>=0)?usages.reduce((n,u)=>n+u[key],0):undefined;
  const usage={uncachedInputTokens:sum('uncachedInputTokens'),outputTokens:sum('outputTokens'),totalTokens:sum('totalTokens'),cacheReadTokens:sum('cacheReadTokens'),cacheWriteTokens:sum('cacheWriteTokens')};
  return [usage.uncachedInputTokens,usage.outputTokens,usage.totalTokens].every(Number.isSafeInteger)?usage:null;
}
