// The verifier's Tasks probes on PR #2908 (missing gh, repository attacks, terminal here, a 50 KB body, and a
// token-like string in an issue: masked in the list, the drawer, the error line and Start in thread's text).
import {test,expect,type Page} from '@playwright/test';
const PORT=Number(process.env.OMHER_MOCK_PORT||5308);
const REPO='rlaope/oh-my-hermes', CWD='/home/you/code/oh-my-hermes';
async function mock(op:string,params:Record<string,unknown>={}) { const ws=new WebSocket(`ws://127.0.0.1:${PORT}/?token=e2e`); await new Promise<void>((r,j)=>{ws.onopen=()=>r();ws.onerror=()=>j(Error('ws'));}); const out=await new Promise<any>(r=>{ws.onmessage=m=>{const x=JSON.parse(String(m.data));if(x.id==='v7')r(x);};ws.send(JSON.stringify({id:'v7',op,...params}));});ws.close();expect(out.ok).toBe(true);return out.result; }
async function setup(page:Page, opts:{missing?:boolean,body?:string,title?:string,error?:string}={}) {
 await mock('mock.reset'); await mock('mock.threads',{bot:'kami',threads:[{title:'Verify7 folder',ago:60,cwd:CWD}]});
 await page.addInitScript(({repo,cwd,opts})=>{
 localStorage.setItem('omher.theme','dark');localStorage.removeItem('omher.tasks');
 const row={number:1,title:opts.title||'Independent probe',state:'open',url:`https://github.com/${repo}/issues/1`,labels:[],author:'tester',created:1700000000,updated:1700000000,checks:null};
 (window as any).__omherTasks={status:{github:{installed:!opts.missing,signed_in:!opts.missing}},items:{[`github:${repo}:issues`]:[row]},details:{[`github:${repo}:issues:1`]:{body:opts.body||'body',comments:[{author:'p',body:opts.body||'c',created:1700000000}],checks:[]}},remotes:{[cwd]:{source:'github',repo}},errors:opts.error?{[`github:${repo}`]:opts.error}:{}};
 },{repo:REPO,cwd:CWD,opts});
 await page.goto('/');await expect(page.getByTestId('bot-kami')).toBeVisible();await page.getByTestId('bot-kami').click();
 await page.locator('[role="treeitem"][aria-level="2"]',{hasText:'Verify7 folder'}).click();
 await page.getByTestId('tasks-bar-github').click();
}
test('independent missing gh and malformed repositories',async({page})=>{
 await setup(page,{missing:true});await expect(page.getByTestId('tasks-missing')).toContainText('gh');
 await page.getByTestId('tasks-repo').click();
 for(const r of ['o/r;touch','o/r space','o/..','../r']){await page.getByTestId('tasks-repo-input').fill(r);await expect(page.getByTestId('tasks-repo-go')).toBeDisabled();}
 expect(await page.evaluate(()=>(window as any).__omherTaskCalls.some((c:any)=>c.op==='list'))).toBe(false);
});
test('independent terminal here starts a shell in cloned repo',async({page})=>{
 await setup(page);await page.getByTestId('tasks-row-1').click();await page.getByTestId('tasks-terminal').click();
 await expect(page.getByTestId('termpanel')).toBeVisible();
 await expect.poll(()=>page.evaluate(()=>((window as any).__omherShellCalls??[]).filter((c:any)=>c.op==='start').length)).toBe(1);
 const starts=await page.evaluate(()=>(window as any).__omherShellCalls.filter((c:any)=>c.op==='start'));
 console.log('TERMINAL START',JSON.stringify(starts));expect(starts).toHaveLength(1);expect(starts[0].cwd).toBe(CWD);
});
test('independent 50 KB unicode body is trimmed in thread send',async({page})=>{
 await setup(page,{body:'한글 '.repeat(7500)});await page.getByTestId('tasks-row-1').click();await expect(page.getByTestId('tasks-drawer-body')).toContainText('한글');
 await page.getByTestId('tasks-start').click();await expect.poll(async()=>((await mock('mock.calls')).calls as any[]).filter(c=>c.op==='chat.send').length).toBe(1);
 const sent=(await mock('mock.calls')).calls.find((c:any)=>c.op==='chat.send').params;
 const body=sent.text.split('\n\n')[2];console.log('BODY BYTES',new TextEncoder().encode(body).length);expect(new TextEncoder().encode(body).length).toBeLessThanOrEqual(4096);expect(sent.text).toContain('Work on this issue.');expect(sent.session).toBeTruthy();
});
test('independent fake token is masked in the list, the drawer and Start in thread',async({page})=>{
 const fake='ghp_'+'X'.repeat(36);let logged=false;page.on('console',m=>{if(m.text().includes(fake))logged=true;});
 await setup(page,{title:`leak ${fake}`,body:`example credential ${fake}\n\n\`\`\`sh\nexport GH_TOKEN=${fake}\n\`\`\`\n\n[docs](https://example.com/?token=abc123)`});
 await expect(page.getByTestId('tasks-row-1')).toContainText('leak ••••');
 await expect(page.getByTestId('tasks-row-1')).not.toContainText(fake);
 await page.getByTestId('tasks-row-1').click();await expect(page.getByTestId('tasks-drawer-body')).toContainText('example credential ••••');
 if(process.env.OMHER_SHOTS) await page.screenshot({path:process.env.OMHER_SHOTS+'/tasks-fake-token-masked.png'});
 const drawer=page.getByTestId('tasks-drawer');
 await expect(drawer).not.toContainText(fake);await expect(drawer).not.toContainText('abc123');
 await expect(page.getByTestId('tasks-drawer-body')).toContainText('GH_TOKEN=••••');
 expect(logged).toBe(false);
 await page.getByTestId('tasks-start').click();await expect.poll(async()=>((await mock('mock.calls')).calls as any[]).filter(c=>c.op==='chat.send').length).toBe(1);
 const calls=(await mock('mock.calls')).calls as any[];
 const sent=calls.find(c=>c.op==='chat.send').params.text as string;const made=calls.find(c=>c.op==='thread.create').params.title as string;
 expect(sent).not.toContain(fake);expect(made).not.toContain(fake);expect(sent).toContain('example credential ••••');expect(made).toBe('#1 leak ••••');
});
test('independent fake token in an error line is masked',async({page})=>{
 const fake='ghp_'+'X'.repeat(36);
 await setup(page,{error:`failure credential=${fake}`});
 await expect(page.getByTestId('tasks-error')).toContainText('failure credential=••••');
 await expect(page.getByTestId('tasks-error')).not.toContainText(fake);
});
