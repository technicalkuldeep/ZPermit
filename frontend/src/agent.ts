import { Api } from './api'
import type { Product,Purchase,Preview } from './types'
export function parseTask(task:string){
  const brand=task.match(/swiggy(?: money)?|flipkart|google play/i)?.[0]
  const value=task.match(/(?:₹|INR\s*)(\d+(?:\.\d+)?)/i)?.[1]
  if(!brand||!value)throw new Error('Use a supported task: “Find a ₹50 Swiggy Money gift card”. Swiggy, Flipkart and Google Play in India are supported. Other products can be selected in Shop.')
  return {query:brand,denomination:value,country:'IN'}
}
export async function discoverTask(api:Api,task:string){
  const parsed=parseTask(task)
  const products=await api.request<Product[]>(`/api/bitrefill/products?${new URLSearchParams({query:parsed.query,country:parsed.country,intent:task})}`,undefined,'agent')
  const tokens=parsed.query.toLowerCase().split(/\s+/)
  const matches=products.filter(p=>tokens.every(token=>`${p.id} ${p.name??''}`.toLowerCase().includes(token))&&p.id.endsWith('-india'))
  if(matches.length!==1)throw new Error('Search did not find one unambiguous India product. Select the exact product in Shop.')
  const product=await api.request<Product>(`/api/bitrefill/products/${encodeURIComponent(matches[0].id)}`,undefined,'agent')
  return {product,denomination:parsed.denomination}
}
export async function propose(api:Api,input:{product:Product;denomination:string;permit_id:string;agent_id:string;category:string;requestKey:string},onDecision:(p:Purchase)=>void){
  const pack=input.product.denominations.find(p=>p.package_value===input.denomination)
  if(pack?.payment_currency!=='USD'||!pack.payment_price_cents)throw new Error('No verified indicative USD price is available for this denomination. No request submitted.')
  const purchase=await api.request<Purchase>('/api/purchase-requests',{permit_id:input.permit_id,agent_id:input.agent_id,merchant:input.product.id,category:input.category,product_id:input.product.id,amount_cents:pack.payment_price_cents,currency:'USD',external_request_id:input.requestKey},'agent')
  onDecision(purchase)
  let preview:Preview|undefined
  if(['authorized','pending_approval'].includes(purchase.state)) preview=await api.request<Preview>('/api/bitrefill/purchase-previews',{purchase_request_id:purchase.id,denomination:input.denomination},'agent')
  return {purchase,preview}
}
