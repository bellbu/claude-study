import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
const server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1'],{stdio:'ignore'});
let ready=false;
for(let i=0;i<40;i++){try{const r=await fetch('http://127.0.0.1:5173');if(r.ok){ready=true;break}}catch{} await delay(250)}
if(!ready)throw new Error('Vite server did not become ready');
const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE}:{})});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1100},deviceScaleFactor:1});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:5173',{waitUntil:'networkidle'});await page.getByRole('button',{name:/마필 설정/}).click();for(let i=0;i<3;i++)await page.locator('.settings-popover').getByRole('button',{name:'＋'}).click();if(await page.locator('.horse-card').count()!==8)throw new Error('Runner setting did not reach 8');for(let i=0;i<3;i++)await page.locator('.settings-popover').getByRole('button',{name:'−'}).click();await page.getByRole('button',{name:/마필 설정/}).click();if(await page.locator('.horse-card').count()!==5)throw new Error('Runner setting did not return to 5');await page.screenshot({path:'artifacts/lobby.png',fullPage:true});
 await page.getByRole('button',{name:/베팅하고 레이스 시작/}).click();await page.waitForSelector('.countdown-overlay');await page.waitForSelector('.ticker',{timeout:7000});await page.waitForSelector('.settlement',{timeout:20000});await page.screenshot({path:'artifacts/race-result.png',fullPage:true});
 const result={winner:await page.locator('.settle-title').innerText(),runners:await page.locator('.horse-card').count(),balance:await page.locator('.balance b').innerText(),pageErrors:errors};
 await page.waitForSelector('.settlement',{state:'detached',timeout:6000});
 const saved=JSON.parse(await page.evaluate(()=>localStorage.getItem('derby-day-v1')));
 await page.reload({waitUntil:'networkidle'});
 if(!(await page.locator('.headline').innerText()).includes('RACE 002'))throw new Error('Round did not advance on auto-return');if(!(await page.locator('.balance b').innerText()).includes(saved.balance.toLocaleString()))throw new Error('Balance did not survive reload');
 if(saved.balance<1||saved.races!==1)throw new Error('Settlement was not persisted');
 await page.screenshot({path:'artifacts/next-lobby-persisted.png',fullPage:true});
 if(errors.length)throw new Error('Browser errors: '+errors.join('; '));
 console.log(JSON.stringify({...result,autoReturned:true,reloadBalance:saved.balance,reloadRaces:saved.races},null,2));
}finally{await browser.close();server.kill()}




