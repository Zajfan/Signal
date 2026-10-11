// Uses an isolated database/server. Never changes the developer's Signal data.
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {mkdtemp, rm, mkdir} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {chromium} from 'playwright';
const temporary = await mkdtemp(path.join(os.tmpdir(),'signal-browser-'));
const port = process.env.SIGNAL_TEST_PORT || '8096';
const base = `http://127.0.0.1:${port}`;
const server = spawn('python3',['-u','backend/local_server.py','--port',port,'--db',path.join(temporary,'test.sqlite3')],{stdio:'pipe'});
let logs=''; server.stdout.on('data',b=>logs+=b); server.stderr.on('data',b=>logs+=b);
let browser;
try {
  let ready = false;
  for(let i=0;i<100;i++) {
    if(server.exitCode!==null)throw Error(logs);
    try { const r=await fetch(base+'/api/v1/health');if(r.ok){ready=true;break;} }catch{}
    await new Promise(r=>setTimeout(r,100));
  }
  assert(ready,'Test server did not start');
  browser=await chromium.launch({headless:true, executablePath:process.env.SIGNAL_BROWSER_EXECUTABLE || undefined});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/employer');
  await page.getByRole('heading',{name:'Your hiring workspace.',exact:true}).waitFor();
  await page.getByRole('link',{name:'Company profile →'}).click();
  await page.getByLabel('Company name',{exact:true}).fill('Signal Test Company');
  await page.getByLabel('Company website',{exact:true}).fill('https://example.test');
  await page.getByRole('button',{name:'Submit for verification'}).click();
  await page.getByText('Verification pending',{exact:true}).waitFor();
  await page.goto(base+'/admin');
  await page.getByRole('button',{name:'Verify company'}).click();
  await page.getByText('No companies waiting for review.').waitFor();
  await page.goto(base+'/employer?view=new');
  await page.getByLabel('Job title',{exact:true}).fill('AI Platform Engineer');
  await page.getByLabel('Location',{exact:true}).fill('Stockholm, Sweden');
  await page.getByLabel('Country',{exact:true}).selectOption('SE');
  await page.getByLabel('Job description',{exact:true}).fill('Build AI systems with Claude Code and carefully review generated software.\nWork with a global product team.');
  await page.getByLabel('Application URL',{exact:true}).fill('https://example.test/jobs/ai');
  await page.getByLabel('Minimum annual salary',{exact:true}).fill('600000');
  await page.getByLabel('Maximum annual salary',{exact:true}).fill('900000');
  await page.getByLabel('Currency (3-letter code)',{exact:true}).fill('SEK');
  await page.getByRole('button',{name:'Save draft',exact:true}).click();
  await page.getByRole('heading',{name:'Edit your draft.'}).waitFor();
  await page.getByLabel('Job title',{exact:true}).fill('Senior AI Platform Engineer');
  await page.getByRole('button',{name:'Save changes',exact:true}).click();
  await page.getByText('Draft saved.',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Start simulated checkout'}).click();
  await page.getByRole('button',{name:'Complete simulated payment'}).click();
  await page.getByText('Your post is in review.',{exact:true}).waitFor();
  await page.goto(base+'/admin');
  await page.getByRole('button',{name:'Approve and publish'}).click();
  await page.getByText('No paid posts waiting for review.').waitFor();
  const response=await fetch(base+'/api/v1/jobs');
  const data=await response.json();
  assert.equal(data.jobs.length,1);assert.equal(data.jobs[0].title,'Senior AI Platform Engineer');
  await page.goto(base+'/employer');
  await page.getByRole('link',{name:'Senior AI Platform Engineer',exact:true}).waitFor();
  await mkdir('artifacts',{recursive:true});
  await page.screenshot({path:'artifacts/employer-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'artifacts/employer-mobile.png',fullPage:true});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Employer mobile overflow');
  await page.setViewportSize({width:1440,height:1000});
  await page.goto(base+'/');
  await page.getByRole('link',{name:'Senior AI Platform Engineer',exact:true}).waitFor();
  await page.getByRole('button',{name:'Save job',exact:true}).click();
  await page.goto(base+'/?saved=1');
  await page.getByRole('link',{name:'Senior AI Platform Engineer',exact:true}).click();
  await page.getByRole('heading',{name:'Senior AI Platform Engineer',exact:true}).waitFor();
  assert.equal(await page.getByRole('link',{name:'Apply for this role ↗'}).getAttribute('href'),'https://example.test/jobs/ai');
  await page.screenshot({path:'artifacts/job-detail-desktop.png',fullPage:true});
  await page.goto(base+'/?country=SE&currency=SEK&salary_min=500000');
  await page.getByRole('link',{name:'Senior AI Platform Engineer',exact:true}).waitFor();
  await page.screenshot({path:'artifacts/search-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'artifacts/search-mobile.png',fullPage:true});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Candidate mobile overflow');
  await page.goto(base+'/?q=no-such-job');
  await page.getByRole('heading',{name:'No roles match these filters'}).waitFor();
  await page.goto(base+'/jobs/not-found');
  await page.getByRole('heading',{name:'This opportunity is no longer available.'}).waitFor();
  await page.route('**/api/v1/jobs?*',route=>route.abort());
  await page.goto(base+'/');
  await page.getByRole('heading',{name:'We couldn’t load this page.'}).waitFor();
  await page.unroute('**/api/v1/jobs?*');
  await page.goto(base+'/sources');
  await page.getByRole('heading',{name:'Sources & discovery.'}).waitFor();
  await page.getByText('No imported jobs waiting for review.').waitFor();
  execFileSync('python3',['-c',`import sys;sys.path.insert(0,'backend')
from ingestion import run_once
from pathlib import Path
source={'source_id':'browser-fixture','ats':'lever','board':'example','label':'Browser fixture','enabled':True,'permission_basis':'Test fixture permission','auto_publish':False}
job={'id':'lever:example:fixture','title':'AI Research Scientist','company':'Fixture Labs','description':'Research AI systems and machine learning for a meaningful product.','url':'https://example.test/research','location':'Berlin','country_code':'DE','ai_explicit':True,'work_mode':'Remote','type':'Full-time'}
run_once(Path(sys.argv[1]),[source],fetcher=lambda _:[job])`,path.join(temporary,'test.sqlite3')]);
  await page.reload();
  await page.locator('summary').filter({hasText:'AI Research Scientist'}).click();
  await page.getByRole('button',{name:'Publish import'}).click();
  await page.getByText('No imported jobs waiting for review.').waitFor();
  assert.equal((await fetch(base+'/api/v1/admin/sources')).status,403);
  await page.goto(base+'/?country=DE');
  await page.getByRole('link',{name:'AI Research Scientist',exact:true}).click();
  await page.getByRole('heading',{name:'AI Research Scientist',exact:true}).waitFor();
  await page.getByText('Imported from Browser fixture and reviewed for publication.').waitFor();

  assert.deepEqual(errors,[]);
  console.log('PASS employer browser flow: company → draft/edit → simulated payment → moderation → publication; candidate filters/details/saving/empty/error states; desktop/mobile layout.');
} finally {
  await browser?.close();server.kill('SIGTERM');
  await new Promise(resolve=>server.exitCode!==null?resolve():server.once('exit',resolve));
  await rm(temporary,{recursive:true,force:true});
}
