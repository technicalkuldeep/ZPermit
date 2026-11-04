import { render,screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { it,expect,vi } from 'vitest'
import App from './App'
const workspace={agent_id:'shopping-agent',owner_id:'owner',auth_mode:'local_development',checkout:{execution_available:false,blocker:'maximum_debit_unbounded',live_gate_enabled:false},public_reads_enabled:false,permits:[],purchases:[],previews:[],executions:[],mobile_requests:[],observations:[]}
it('starts without fabricated balances or stored credentials',()=>{render(<App/>);expect(screen.getByText('Make the connection.')).toBeInTheDocument();expect(screen.getByText(/Never enter a Bitrefill key/)).toBeInTheDocument();expect(screen.queryByText('$25.00')).not.toBeInTheDocument()})
it('connects to the actual contract and separates unpaid invoice from success',async()=>{const user=userEvent.setup();vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{const path=String(input);if(path==='/api/workspace')return new Response(JSON.stringify(workspace));if(path==='/api/bitrefill/balance')return new Response(JSON.stringify({amount_cents:2500}));if(path.includes('/invoices/'))return new Response(JSON.stringify({invoice_id:'1f81dedb-ea5d-4065-9332-81d573e98f3a',payment_status:'unpaid',invoice_status:'not_delivered',payment_price_raw:'682',payment_currency:'BTC',payment_method:'balance',orders:[]}));throw new Error('Unexpected path '+path)}));render(<App/>);await user.type(screen.getByLabelText('Development owner credential'),'owner-test');await user.click(screen.getByRole('button',{name:'Connect workspace'}));expect(await screen.findByText('Available to agents')).toBeInTheDocument();expect(await screen.findByText('$25.00')).toBeInTheDocument();await user.click(screen.getByRole('button',{name:'Evidence & activity'}));await user.type(screen.getByLabelText('Bitrefill invoice ID'),'1f81dedb-ea5d-4065-9332-81d573e98f3a');await user.click(screen.getByRole('button',{name:'Read invoice'}));expect(await screen.findByText('682 · BTC')).toBeInTheDocument();expect(screen.getByText('unpaid')).toBeInTheDocument();expect(screen.getByText(/An unpaid invoice is not a purchase/)).toBeInTheDocument();expect(screen.queryByText('Purchase successful')).not.toBeInTheDocument()})

it('loads saved phone QR with authorization, not a token in the image URL',async()=>{
 // Deliberately invalid test-only address: no live recipient or provider call.
 const user=userEvent.setup()
 const payment={id:'unit-request',destination:'unit-test-recipient-not-an-address',amount_zatoshis:100000,amount_taz:'0.001',memo:null,payment_uri:'zcash:unit-test-recipient-not-an-address?amount=0.001',qr_path:'/api/zcash/mobile/payment-requests/unit-request/qr.png',observation_id:null,created_at:'2026-11-04T12:00:00Z',state:'prepared_for_external_wallet'}
 const create=vi.fn(()=> 'blob:unit-test-qr'),revoke=vi.fn()
 class TestURL extends URL { static createObjectURL=create; static revokeObjectURL=revoke }
 vi.stubGlobal('URL',TestURL)
 const fetch=vi.fn(async(input:RequestInfo|URL)=>{
   if(String(input)==='/api/workspace')return new Response(JSON.stringify({...workspace,mobile_requests:[payment]}))
   if(String(input)==='/api/bitrefill/balance')return new Response(JSON.stringify({amount_cents:2500}))
   if(String(input)===payment.qr_path)return new Response(new Blob(['unit-test-image'],{type:'image/png'}))
   throw new Error('Unexpected test path')
 })
 vi.stubGlobal('fetch',fetch)
 render(<App/>);await user.type(screen.getByLabelText('Development owner credential'),'unit-owner-token');await user.click(screen.getByRole('button',{name:'Connect workspace'}));await screen.findByText('Available to agents')
 await user.click(screen.getByRole('button',{name:'Zcash payments'}))
 const qr=await screen.findByRole('img',{name:'ZIP-321 payment request QR for your phone'})
 expect(qr.getAttribute('src')).toBe('blob:unit-test-qr')
 expect(screen.getByText('prepared not paid')).toBeInTheDocument()
 expect(screen.getByText(/If the installed Zingo version does not support/)).toBeInTheDocument()
 const qrCall=fetch.mock.calls.find(c=>String(c[0])===payment.qr_path)
 expect(qrCall).toBeDefined()
 expect((qrCall as unknown as [string,RequestInit])[1].headers).toMatchObject({Authorization:'Bearer unit-owner-token'})
 await user.click(screen.getByRole('button',{name:'Overview'}))
 expect(revoke).toHaveBeenCalledWith('blob:unit-test-qr')
})

it('marks stale public evidence and does not claim a verified private receipt',async()=>{
 // Non-txid string is intentional; this fixture never reaches a network endpoint.
 const user=userEvent.setup()
 const observation={id:'unit-observation',txid:'unit-test-not-a-real-txid',evidence:{status:'pending',confirmations:0,pool:'ironwood'},last_check_succeeded:false,error_code:'public_testnet_unavailable',created_at:'2026-11-04T12:00:00Z',last_checked_at:'2026-11-04T12:00:00Z'}
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>new Response(JSON.stringify(String(input)==='/api/workspace'?{...workspace,observations:[observation]}:{amount_cents:2500}))))
 render(<App/>);await user.type(screen.getByLabelText('Development owner credential'),'unit-owner-token');await user.click(screen.getByRole('button',{name:'Connect workspace'}));await screen.findByText('Available to agents')
 await user.click(screen.getByRole('button',{name:'Zcash payments'}))
 expect(screen.getByText('stale check failed')).toBeInTheDocument()
 expect(screen.getByText(/Recipient, amount, memo and sender remain unverified/)).toBeInTheDocument()
 expect(screen.queryByText('Payment successful')).not.toBeInTheDocument()
})


it('creates an isolated public demo session without asking for real credentials',async()=>{
 const user=userEvent.setup()
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
   const path=String(input)
   if(path==='/api/mode')return new Response(JSON.stringify({mode:'public_demo'}))
   if(path==='/api/demo/sessions')return new Response(JSON.stringify({base:'',owner:'demo-owner-cap',agent:'demo-agent-cap',demo:true}))
   if(path==='/api/workspace')return new Response(JSON.stringify({...workspace,demo:true,agent_id:'demo-agent'}))
   if(path==='/api/workspace/identity')return new Response(JSON.stringify({role:'agent',subject:'demo-agent'}))
   return new Response(JSON.stringify({detail:'Public demo has no real account'}),{status:403})
 }))
 render(<App/>);await user.click(await screen.findByRole('button',{name:'Start isolated demo'}))
 expect(await screen.findByText('ISOLATED PUBLIC DEMO · SAMPLE DATA')).toBeInTheDocument()
 expect(screen.queryByLabelText('Development owner credential')).not.toBeInTheDocument()
 await user.click(screen.getByRole('button',{name:'Create permit'}))
 expect(screen.getByLabelText('Agent identifier')).toHaveValue('demo-agent')
 expect(screen.getByLabelText('Agent identifier')).toHaveAttribute('readonly')
})
