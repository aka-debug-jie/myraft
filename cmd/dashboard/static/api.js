export function parseJSON(text) {
  return JSON.parse(text, (key,value,context) => {
    if(typeof value==='number'&&Number.isInteger(value)&&!Number.isSafeInteger(value)) {
      if(context?.source===undefined)throw new RangeError('浏览器无法精确读取超出安全范围的整数');
      return context.source;
    }
    return value;
  });
}
export async function request(path,options={}) {
  const deadline=AbortSignal.timeout(10000);
  const response=await fetch(path,{cache:'no-store',...options,signal:options.signal?AbortSignal.any([deadline,options.signal]):deadline});
  const text=await response.text();
  let data;
  try {data=parseJSON(text);} catch(error) {
    if(response.ok)throw error;
    data={error:text};
  }
  if(!response.ok) {const error=new Error(data.error||`HTTP ${response.status}`);error.status=response.status;throw error;}
  if(path==='/api/session')data.read_only_transport=response.headers.get('X-MyRaft-Read-Only')==='1';
  return data;
}
export function bootstrap() {return request('/api/session');}
export function operate(kind,state,params={}) {
  if(params.seed!==undefined&&!Number.isSafeInteger(params.seed))throw new RangeError('页面随机种子须为安全整数；完整 int64 种子可用 CLI');
  return request('/api/operations',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.bootstrap?.csrf_token||''},
    body:JSON.stringify({kind,controller_id:state.frame?.controller_id||state.bootstrap?.controller_id,session_id:state.frame?.session?.id||'',generation:state.frame?.generation||state.bootstrap?.generation||1,...params})});
}
export function logs(id,from,limit,session,generation,signal) {
  return request('/api/nodes/'+id+'/logs?'+new URLSearchParams({from,limit,session_id:session,generation}),{signal});
}
