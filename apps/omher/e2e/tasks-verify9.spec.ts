// The verifier's V4 probes on PR #2908 (a code block and a link href, and a token split over a line break: masked in
// the drawer and the text Start in thread sends), kept as regression tests.
import {test,expect,type Page} from '@playwright/test';
const PORT=Number(process.env.OMHER_MOCK_PORT||5308), REPO='rlaope/oh-my-hermes', CWD='/home/you/code/oh-my-hermes';
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

test('v9 crlf drawer/comments/thread',async({page})=>{
 const body="before ghp_AB12\r\nZ9Z9Z9Z9Z9Z9Z9Z9Z9Z9Z9Z9Z9Z9Z9Z9 after"; const want="before •••• after"; await setup(page,body);
 const got=await page.getByTestId("tasks-drawer-body").textContent(); console.log("V9 crlf drawer masked="+!got?.replace(/\s/g,'').includes(body.replace(/\s/g,'').split('before')[1]?.trim()||'impossible'));
 await expect.soft(page.getByTestId("tasks-drawer-body")).toContainText(want);
 await page.getByTestId("tasks-start").click(); await expect.poll(async()=>((await mock("mock.calls")).calls as any[]).filter(c=>c.op==="chat.send").length).toBe(1); const sent=(await mock("mock.calls")).calls.find((c:any)=>c.op==="chat.send").params.text; expect.soft(sent).toContain(want);
});

test('v9 two-splits drawer/comments/thread',async({page})=>{
 const body="before ghp_AB12\nZ9Z9Z9Z9Z9Z9Z9Z9\nQ8Q8Q8Q8Q8Q8Q8Q8 after"; const want="before •••• after"; await setup(page,body);
 const got=await page.getByTestId("tasks-drawer-body").textContent(); console.log("V9 two-splits drawer masked="+!got?.replace(/\s/g,'').includes(body.replace(/\s/g,'').split('before')[1]?.trim()||'impossible'));
 await expect.soft(page.getByTestId("tasks-drawer-body")).toContainText(want);
 await page.getByTestId("tasks-start").click(); await expect.poll(async()=>((await mock("mock.calls")).calls as any[]).filter(c=>c.op==="chat.send").length).toBe(1); const sent=(await mock("mock.calls")).calls.find((c:any)=>c.op==="chat.send").params.text; expect.soft(sent).toContain(want);
});

test('v9 end-body drawer/comments/thread',async({page})=>{
 const body="before ghp_AB12\nZ9Z9Z9Z9Z9Z9Z9Z9Z9Z9Z9Z9Z9Z9Z9Z9"; const want="before ••••"; await setup(page,body);
 const got=await page.getByTestId("tasks-drawer-body").textContent(); console.log("V9 end-body drawer masked="+!got?.replace(/\s/g,'').includes(body.replace(/\s/g,'').split('before')[1]?.trim()||'impossible'));
 await expect.soft(page.getByTestId("tasks-drawer-body")).toContainText(want);
 await page.getByTestId("tasks-start").click(); await expect.poll(async()=>((await mock("mock.calls")).calls as any[]).filter(c=>c.op==="chat.send").length).toBe(1); const sent=(await mock("mock.calls")).calls.find((c:any)=>c.op==="chat.send").params.text; expect.soft(sent).toContain(want);
});

test('v9 prose drawer/comments/thread',async({page})=>{
 const body="ghp_ is a prefix\nNext line"; const want="ghp_ is a prefix\nNext line"; await setup(page,body);
 const got=await page.getByTestId("tasks-drawer-body").textContent(); console.log("V9 prose drawer masked="+!got?.replace(/\s/g,'').includes(body.replace(/\s/g,'').split('before')[1]?.trim()||'impossible'));
 await expect.soft(page.getByTestId("tasks-drawer-body")).toContainText(want);
 await page.getByTestId("tasks-start").click(); await expect.poll(async()=>((await mock("mock.calls")).calls as any[]).filter(c=>c.op==="chat.send").length).toBe(1); const sent=(await mock("mock.calls")).calls.find((c:any)=>c.op==="chat.send").params.text; expect.soft(sent).toContain(want);
});

test('v9 lowercase-split drawer/comments/thread',async({page})=>{
 const body="before ghp_abcd\nxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx after"; const want="before •••• after"; await setup(page,body);
 const got=await page.getByTestId("tasks-drawer-body").textContent(); console.log("V9 lowercase-split drawer masked="+!got?.replace(/\s/g,'').includes(body.replace(/\s/g,'').split('before')[1]?.trim()||'impossible'));
 if(process.env.OMHER_SHOTS)await page.screenshot({path:process.env.OMHER_SHOTS+'/verify9-lowercase-split.png'});
 await expect.soft(page.getByTestId("tasks-drawer-body")).toContainText(want);
 await page.getByTestId("tasks-start").click(); await expect.poll(async()=>((await mock("mock.calls")).calls as any[]).filter(c=>c.op==="chat.send").length).toBe(1); const sent=(await mock("mock.calls")).calls.find((c:any)=>c.op==="chat.send").params.text; expect.soft(sent).toContain(want);
});
