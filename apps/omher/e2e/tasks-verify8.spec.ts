import {test,expect,type Page} from '@playwright/test';
const PORT=Number(process.env.OMHER_MOCK_PORT||5596), REPO='rlaope/oh-my-hermes', CWD='/home/you/code/oh-my-hermes';
async function mock(op:string,params:Record<string,unknown>={}) { const ws=new WebSocket(`ws://127.0.0.1:${PORT}/?token=e2e`); await new Promise<void>((r,j)=>{ws.onopen=()=>r();ws.onerror=()=>j(Error('ws'));}); const out=await new Promise<any>(r=>{ws.onmessage=m=>{const x=JSON.parse(String(m.data));if(x.id==='v8')r(x);};ws.send(JSON.stringify({id:'v8',op,...params}));}); ws.close();expect(out.ok).toBe(true);return out.result; }
async function setup(page:Page,body:string) {
 await mock('mock.reset'); await mock('mock.threads',{bot:'kami',threads:[{title:'Verify8',ago:60,cwd:CWD}]});
 await page.addInitScript(({repo,cwd,body})=>{
  localStorage.setItem('omher.theme','dark');localStorage.removeItem('omher.tasks');
  const row={number:1,title:'Independent neighbour',state:'open',url:`https://github.com/${repo}/issues/1`,labels:[],author:'tester',created:1700000000,updated:1700000000,checks:null};
  (window as any).__omherTasks={status:{github:{installed:true,signed_in:true}},items:{[`github:${repo}:issues`]:[row]},details:{[`github:${repo}:issues:1`]:{body,comments:[{author:'tester',body,created:1700000000}],checks:[]}},remotes:{[cwd]:{source:'github',repo}}};
 },{repo:REPO,cwd:CWD,body});
 await page.goto('/');await expect(page.getByTestId('bot-kami')).toBeVisible();await page.getByTestId('bot-kami').click();
 await page.locator('[role="treeitem"][aria-level="2"]',{hasText:'Verify8'}).click();await page.getByTestId('tasks-bar-github').click();await page.getByTestId('tasks-row-1').click();
}
test('v8 code block and actual link href masked with readable neighbours',async({page})=>{
 const fake='ghp_'+'X'.repeat(36);let logged=false;page.on('console',m=>{if(m.text().includes(fake))logged=true;});
 await setup(page,`before readable\n\n\`\`\`sh\n${fake}\n\`\`\`\n\n[docs](https://example.org/?token=${fake})\n\nafter readable`);
 const body=page.getByTestId('tasks-drawer-body');await expect(body).toContainText('before readable');await expect(body).toContainText('after readable');await expect(body.locator('code')).toContainText('••••');
 expect(await body.locator('a').getAttribute('href')).not.toContain(fake);await expect(page.getByTestId('tasks-drawer')).not.toContainText(fake);
 if(process.env.OMHER_SHOTS)await page.screenshot({path:process.env.OMHER_SHOTS+'/verify8-code-link.png'});
 await page.getByTestId('tasks-start').click();await expect.poll(async()=>((await mock('mock.calls')).calls as any[]).filter(c=>c.op==='chat.send').length).toBe(1);
 const sent=(await mock('mock.calls')).calls.find((c:any)=>c.op==='chat.send').params.text;expect(sent).not.toContain(fake);expect(sent).toContain('before readable');expect(sent).toContain('after readable');expect(logged).toBe(false);
 console.log('V8 code/link href/comments/thread masked; surrounding words readable; console leak=false');
});
test('v8 split-line synthetic token masked in drawer and thread',async({page})=>{
 const fake='ghp_'+'X'.repeat(36), split='ghp_XXXX\n'+'X'.repeat(32);
 await setup(page,`before ${split} after`);const body=page.getByTestId('tasks-drawer-body');await expect(body).toContainText('before');await expect(body).toContainText('after');
 const retained=((await body.textContent())||'').replace(/\s/g,'').includes(fake);console.log('V8 split token drawer retained='+retained);
 if(process.env.OMHER_SHOTS)await page.screenshot({path:process.env.OMHER_SHOTS+'/verify8-split-token.png'});
 await page.getByTestId('tasks-start').click();await expect.poll(async()=>((await mock('mock.calls')).calls as any[]).filter(c=>c.op==='chat.send').length).toBe(1);
 const sent=(await mock('mock.calls')).calls.find((c:any)=>c.op==='chat.send').params.text;const sentRetained=sent.replace(/\s/g,'').includes(fake);console.log('V8 split token thread retained='+sentRetained);
 expect.soft(retained,'drawer exposes split token').toBe(false);expect.soft(sentRetained,'thread receives split token').toBe(false);
});
