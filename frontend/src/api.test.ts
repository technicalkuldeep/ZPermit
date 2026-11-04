import { describe,it,expect,vi } from 'vitest'
import { Api,cents,zatoshis,localBase } from './api'
describe('exact amount handling',()=>{
 it('keeps USD and TAZ units independent',()=>{expect(cents('0.55')).toBe(55);expect(cents('50')).toBe(5000);expect(zatoshis('0.001')).toBe(100000);expect(zatoshis('0.00000001')).toBe(1)})
 it.each(['NaN','0.555','1e3','-1','true'])('rejects invalid USD input %s',v=>expect(()=>cents(v)).toThrow())
 it.each(['0','1.00000001','0.000000001','1e-8'])('rejects invalid TAZ input %s',v=>expect(()=>zatoshis(v)).toThrow())
 it('does not send development credentials to arbitrary hosts',()=>{expect(localBase('')).toBe('');expect(localBase('http://127.0.0.1:8000')).toBe('http://127.0.0.1:8000');for(const v of ['https://evil.example','http://localhost.evil.example','http://u:p@localhost','http://localhost/path'])expect(()=>localBase(v)).toThrow()})
 it('never retries a network failure',async()=>{const fetch=vi.fn().mockRejectedValue(new Error('timeout'));vi.stubGlobal('fetch',fetch);const api=new Api({base:'',owner:'owner-test',agent:'agent-test'});await expect(api.request('/api/purchase-requests',{},'agent')).rejects.toThrow('No automatic retry');expect(fetch).toHaveBeenCalledTimes(1)})
 it('uses role-separated authorization with no credentials in URL',async()=>{const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify({state:'denied'})));vi.stubGlobal('fetch',fetch);await new Api({base:'',owner:'owner-test',agent:'agent-test'}).request('/api/purchase-requests',{},'agent');const [url,init]=fetch.mock.calls[0];expect(url).toBe('/api/purchase-requests');expect(init.headers.Authorization).toBe('Bearer agent-test');expect(init.redirect).toBe('error')})
})
