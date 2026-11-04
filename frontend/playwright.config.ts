import { defineConfig } from '@playwright/test'
import { randomBytes } from 'node:crypto'
process.env.ZPERMIT_BROWSER_OWNER ??= randomBytes(24).toString('hex')
process.env.ZPERMIT_BROWSER_AGENT ??= randomBytes(24).toString('hex')
export default defineConfig({
 testDir:'./tests',workers:1,timeout:90000,retries:0,
 use:{baseURL:'http://127.0.0.1:8011',viewport:{width:1440,height:1000},headless:true},
 webServer:{command:'cd ../backend && PYTHONPATH=. .venv/bin/python ../frontend/tests/serve_backend.py',url:'http://127.0.0.1:8011/health',reuseExistingServer:false,timeout:30000},
 reporter:'list',
})
