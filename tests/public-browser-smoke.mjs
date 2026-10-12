// Public runtime integration uses real Gunicorn, SQLite and an isolated browser.
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {mkdtemp, rm, mkdir} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {chromium} from 'playwright';
import {randomUUID} from 'node:crypto';

const temporary = await mkdtemp(path.join(os.tmpdir(), 'signal-public-browser-'));
const database = path.join(temporary, 'public.sqlite3');
const port = process.env.SIGNAL_PUBLIC_TEST_PORT || '8097';
const base = `http://127.0.0.1:${port}`;
execFileSync('python3', ['-c', `import sys;sys.path.insert(0,'backend')
from pathlib import Path
from local_server import initialize,connect
p=Path(sys.argv[1]);initialize(p)
with connect(p) as db: db.executescript(Path('tests/fixtures/public-jobs.sql').read_text())`, database]);
const python = process.env.SIGNAL_PUBLIC_PYTHON || '.venv-public/bin/python';
const server = spawn(python, ['-m', 'gunicorn', '--config', 'deploy/gunicorn.conf.py', '--chdir', 'backend', 'public_server:create_app()'], {
  env: {...process.env, SIGNAL_DB_PATH: database, SIGNAL_BIND: `127.0.0.1:${port}`}, stdio: 'pipe',
});
let logs = '', spawnError;
server.on('error', error => {spawnError = error;});
server.stdout.on('data', bytes => logs += bytes);
server.stderr.on('data', bytes => logs += bytes);
let browser;
try {
  let ready = false;
  for (let i=0; i<100; i++) {
    if (spawnError) throw spawnError;
    if (server.exitCode !== null) throw Error(logs);
    try { const response = await fetch(base + '/api/v1/health'); if(response.ok) {ready=true;break;} } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert(ready, 'Public test server did not start');
  browser = await chromium.launch({headless: true, executablePath: process.env.SIGNAL_BROWSER_EXECUTABLE || undefined});
  const page = await browser.newPage({viewport: {width:1440, height:1000}});
  const errors=[];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => {if(message.type()==='error' && /Content Security Policy|Refused to/.test(message.text())) errors.push(message.text());});
  await page.goto(base);
  await page.getByRole('link', {name:'AI Engineer 100%', exact:true}).waitFor();
  assert.equal(await page.getByText('Development identity').count(), 0);
  assert.equal(await page.locator('a[href^="/employer"]').count(), 0);
  const saved = Array.from({length:200}, () => randomUUID());
  execFileSync('python3', ['-c', `import json,sqlite3,sys
with sqlite3.connect(sys.argv[1]) as db:
 for i,identity in enumerate(json.loads(sys.argv[2])):
  db.execute("INSERT INTO employer_jobs(id,employer_user_id,title,company_name,description,apply_url,location,country_code,work_mode,status,published_at,expires_at) VALUES(?,'owner',?,'Saved company',?,'https://example.test/apply','Stockholm','SE','remote','published','2026-01-01T00:00:00Z','2099-01-01')",(identity,f'AI saved role {i}', '🤖'*200))`, database, JSON.stringify(saved)]);
  await page.evaluate(ids => localStorage.setItem('signal.savedJobs.v2', JSON.stringify(ids)), saved);
  await page.goto(base+'/?saved=1');
  await page.getByText('200 roles', {exact:true}).waitFor();
  assert.equal(await page.locator('.job-card').count(), 20);
  const firstSavedPage = await page.locator('.job-card h2 a').evaluateAll(nodes => nodes.map(node => node.href));
  await page.getByRole('link', {name:'Next →', exact:true}).click();
  await page.getByText('21–40 of 200', {exact:true}).waitFor();
  const secondSavedPage = await page.locator('.job-card h2 a').evaluateAll(nodes => nodes.map(node => node.href));
  assert(secondSavedPage.every(url => !firstSavedPage.includes(url)), 'Saved pagination repeats jobs');
  await page.goto(base+'/?saved=1&country=SE&q='+encodeURIComponent('🤖'.repeat(200)));
  await page.getByText('200 roles', {exact:true}).waitFor();
  await page.evaluate(() => localStorage.removeItem('signal.savedJobs.v2'));
  await page.goto(base);
  await page.getByRole('link', {name:'AI Engineer 100%', exact:true}).waitFor();
  await page.getByLabel('Search jobs', {exact:true}).fill('100%');
  await page.getByRole('button', {name:'Search jobs', exact:true}).click();
  await page.getByRole('link', {name:'AI Engineer 100%', exact:true}).waitFor();
  assert.equal(await page.locator('.job-card').count(), 1);
  await page.getByRole('button', {name:'Save job', exact:true}).click();
  await page.getByRole('link', {name:'Saved jobs', exact:true}).click();
  await page.getByRole('link', {name:'AI Engineer 100%', exact:true}).click();
  await page.getByRole('heading', {name:'AI Engineer 100%', exact:true}).waitFor();
  assert.equal(await page.getByRole('link', {name:'Apply for this role ↗'}).getAttribute('href'), 'https://example.test/sweden');
  await page.reload();
  await page.getByRole('heading', {name:'AI Engineer 100%', exact:true}).waitFor();
  await page.goto(base+'/?country=DE&currency=EUR&salary_min=70000');
  await page.getByRole('link', {name:'AI Developer_under_score', exact:true}).waitFor();
  await mkdir('artifacts', {recursive:true});
  await page.screenshot({path:'artifacts/public-desktop.png', fullPage:true});
  await page.setViewportSize({width:390, height:844});
  await page.screenshot({path:'artifacts/public-mobile.png', fullPage:true});
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Public mobile overflow');
  const missing = await page.goto(base+'/jobs/draft');
  assert.equal(missing.status(), 404);
  await page.getByRole('heading', {name:'This opportunity is no longer available.'}).waitFor();
  for (const route of ['/api/v1/employer/jobs','/api/v1/admin/sources','/web/employer.js','/signal.sqlite3']) {
    assert.equal((await fetch(base+route, {headers:{'X-Local-Admin':'true','X-Local-User-Id':'owner'}})).status,404);
  }
  execFileSync('python3',['-c',`import sqlite3,sys
with sqlite3.connect(sys.argv[1]) as db:
 db.execute("UPDATE employer_jobs SET status='withdrawn'")
 db.execute("UPDATE imported_jobs SET status='removed'")`,database]);
  await page.goto(base+'/');
  await page.getByRole('heading',{name:'Fresh opportunities are on their way'}).waitFor();
  assert.equal(await page.locator('a[href^="/employer"]').count(),0);
  await page.route('**/api/v1/health', route => route.fulfill({status:503,contentType:'application/json',body:'{"error":"Temporarily unavailable"}'}));
  await page.reload();
  await page.getByRole('heading',{name:'We couldn’t load this page.'}).waitFor();
  assert.deepEqual(errors,[]);
  console.log('PASS public Gunicorn/browser flow: search, filters, details, saved jobs, mobile, empty/unavailable states, and private-route isolation.');
} finally {
  await browser?.close();
  if(!spawnError && server.exitCode===null) {
    server.kill('SIGTERM');
    await new Promise(resolve => server.once('exit',resolve));
  }
  await rm(temporary,{recursive:true,force:true});
}
