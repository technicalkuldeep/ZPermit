export type Credentials = {base:string; owner:string; agent:string;demo?:boolean}
export class ApiError extends Error { status:number; constructor(message:string,status:number){super(message);this.status=status} }
export function localBase(value:string){
  if (!value.trim()) return ''
  const url=new URL(value)
  if(!['http:','https:'].includes(url.protocol)||!['localhost','127.0.0.1','[::1]'].includes(url.hostname)||url.username||url.password||url.pathname!=='/'||url.search||url.hash) throw new Error('Use a loopback backend URL, such as http://127.0.0.1:8000.')
  return url.origin
}
export class Api {
  constructor(private credentials:Credentials){}
  async request<T>(path:string,body?:unknown,role:'owner'|'agent'='owner',blob=false):Promise<T>{
    if(!/^\/(api(?:\/|$)|health$)/.test(path)||path.includes('://')) throw new Error('Unsupported API path')
    const token=this.credentials[role]
    if(path!='/health'&&!token) throw new Error(`Enter the development ${role} credential in Connection.`)
    let response:Response
    try { response=await fetch(localBase(this.credentials.base)+path,{method:body===undefined?'GET':'POST',headers:{...(token?{Authorization:`Bearer ${token}`} :{}),...(body===undefined?{}:{'Content-Type':'application/json'})},...(body===undefined?{}:{body:JSON.stringify(body)}),cache:'no-store',redirect:'error',signal:AbortSignal.timeout(45000)}) }
    catch {throw new Error('Backend unavailable or request timed out. Check the local server. No automatic retry was made; refresh records before resubmitting.')}
    if(!response.ok){
      const data=await response.json().catch(()=>({}))
      const detail=data.detail
      const message=typeof detail==='string'?detail:Array.isArray(detail)?detail.map((x:{loc?:string[];msg?:string})=>`${x.loc?.slice(1).join('.')??'Input'}: ${x.msg}`).join('; '):detail?.code??`Request failed (${response.status})`
      throw new ApiError(message,response.status)
    }
    return (blob?await response.blob():await response.json()) as T
  }
}
export const usd=(cents:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(cents/100)
export const label=(code:string)=>code.replaceAll('_',' ')
export function cents(text:string){
  if(!/^\d+(\.\d{1,2})?$/.test(text))throw new Error('Enter a USD amount with at most two decimal places.')
  const [whole,fraction='']=text.split('.')
  const n=Number(whole)*100+Number(fraction.padEnd(2,'0'))
  if(!Number.isSafeInteger(n)||n>1e12)throw new Error('Amount is too large.')
  return n
}
export function zatoshis(text:string){
  if(!/^\d+(\.\d{1,8})?$/.test(text))throw new Error('Enter TAZ with at most eight decimal places.')
  const [whole,fraction='']=text.split('.')
  const n=Number(whole)*100000000+Number(fraction.padEnd(8,'0'))
  if(!Number.isSafeInteger(n)||n<1||n>100000000)throw new Error('Amount must be greater than zero and at most 1 TAZ.')
  return n
}
