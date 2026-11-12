/* MIT; Copyright (c) 2026 Minho Hwang (revfactory).
 * Modified for OMH from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6 scripts/render.mjs.
 * Explicit local Puppeteer adapter; realpath allowlist replaces prefix server. Upstream quality
 * flags kept: --scale (deviceScaleFactor; >1 supersamples back to the page size), --sub/--shutter
 * (sub-frame motion blur), --crf 16, --preset, --from/--to, --every; serial capture piped to FFmpeg.
 * Frame-clock throttling is off (browserArgs): capture waits on the seek, not on a vsync tick.
 * Full permission/warranty: ../LICENSE.upstream. Not imported or executed by OMH core. */
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {glyphChecker,assertGlyphs} from './font-coverage.mjs';

const hash=data=>crypto.createHash('sha256').update(data).digest('hex');
const MIME={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.json':'application/json','.ttf':'font/ttf','.otf':'font/otf','.woff':'font/woff','.woff2':'font/woff2','.png':'image/png','.jpg':'image/jpeg','.svg':'image/svg+xml','.css':'text/css','.wav':'audio/wav'};

export function systemAlias(component) {
  // macOS ships /etc, /tmp and /var (home of the default temp dir) as links into /private. Only
  // root can create a top-level entry, so trust exactly those three, linked to the same name.
  const name=path.basename(component);
  if(process.platform!=='darwin'||path.dirname(component)!=='/'||!['etc','tmp','var'].includes(name))return false;
  try {return ['private/'+name,'/private/'+name].includes(fs.readlinkSync(component));}
  catch {return false;}
}

export function noLinks(candidate,root) {
  // The root's own parent, the root and every component below it. Without a root the path's
  // folder is the root; above it is the operator's own layout (macOS temp dirs sit under /var).
  const absolute=path.resolve(candidate),base=root===undefined?path.dirname(absolute):path.resolve(root);
  const rel=path.relative(base,absolute);
  if(rel==='..'||rel.startsWith('..'+path.sep)||path.isAbsolute(rel))throw Error('path escapes its root: '+absolute);
  const chain=[path.dirname(base),base];let cursor=base;
  for(const part of rel?rel.split(path.sep):[]){cursor=path.join(cursor,part);chain.push(cursor);}
  for(const component of chain) {
    try {if(fs.lstatSync(component).isSymbolicLink()&&!systemAlias(component))throw Error('symlink refused: '+component);}
    catch(e){if(e.code!=='ENOENT')throw e;}
  }
  return absolute;
}

export function resolveAsset(root,relative,allowed) {
  if(typeof relative!=='string'||!relative||relative.length>512||relative.split('/').some(p=>!p||p==='.'||p==='..'||!/^[-A-Za-z0-9._]+$/.test(p)))throw Error('unsafe asset path');
  if(!allowed.has(relative))throw Error('undeclared asset: '+relative);
  const base=fs.realpathSync(noLinks(root)),target=fs.realpathSync(noLinks(path.join(base,relative),base));
  const rel=path.relative(base,target);
  if(rel.startsWith('..'+path.sep)||rel==='..'||path.isAbsolute(rel)||!fs.statSync(target).isFile())throw Error('asset escapes root');
  if(fs.statSync(target).size>32*1024*1024)throw Error('asset exceeds 32 MiB');
  // The caller's spelling of the root, not its realpath: above the root is the operator's layout.
  return path.join(path.resolve(root),relative);
}

export function snapshotAssets(root,names,maxTotal=268435456){
  const allowed=new Set(names),buffers={},inputs={};let total=0;
  for(const name of allowed){
    const file=resolveAsset(root,name,allowed);
    total+=fs.statSync(file).size;if(total>maxTotal)throw Error('asset total byte limit');
    const data=fs.readFileSync(file);buffers[name]=data;inputs[name]=hash(data);
  }
  return {buffers,inputs,total_bytes:total};
}

export function validateConfig(c) {
  const finite=(x,lo,hi)=>typeof x==='number'&&Number.isFinite(x)&&x>=lo&&x<=hi;
  if(!finite(c.duration,1/60,600)||!finite(c.fps,1,60)||!Number.isInteger(c.duration*c.fps)||c.duration*c.fps>36000)throw Error('invalid duration/fps/frames');
  if(![c.width,c.height].every(x=>finite(x,16,4096)&&Number.isInteger(x)&&x%2===0)||c.width*c.height*c.duration*c.fps>20e9)throw Error('invalid dimensions/pixel budget');
  if(!Array.isArray(c.render_files)||!c.render_files.length||c.render_files.length>512||new Set(c.render_files.map(x=>x.toLowerCase())).size!==c.render_files.length)throw Error('explicit unique render_files required');
  if(c.cuts!==undefined&&(!Array.isArray(c.cuts)||c.cuts.length>4096||
    c.cuts.some((cut,i)=>!finite(cut,0,c.duration)||cut<=0||cut>=c.duration||(i>0&&cut<=c.cuts[i-1]))))throw Error('invalid cuts: strictly increasing numbers inside duration required (max 4096)');
}

export function shutterTimes(t, fps, sub, shutter, cuts, end) {
  // Preserve the original arithmetic and edge clamping for projects without cuts.
  if(!cuts?.length)return Array.from({length:sub},(_,k)=>Math.max(0,Math.min(end-1e-4,t+((k+.5)/sub-.5)*shutter/fps)));
  let start=0,stop=end;
  for(const cut of cuts){if(cut<=t)start=cut;else {stop=Math.min(stop,cut);break;}}
  // Move the whole exposure, not individual samples, to preserve uniform spacing.
  // A short shot uses its full interval; equality at a cut belongs to the new shot.
  const width=Math.min(shutter/fps,stop-start);
  const left=Math.max(start,Math.min(stop-width,t-width/2));
  // The guard keeps rounded midpoints strictly below a cut, even for tiny shots.
  const upper=Math.max(start,Math.min(end-1e-4,stop-Number.EPSILON*Math.max(1,Math.abs(stop))));
  return Array.from({length:sub},(_,k)=>Math.max(start,Math.min(upper,left+(k+.5)*width/sub)));
}

export function browserArgs(origin,port) {
  // Every capture already waits on the seek, fonts, images and a compositor screenshot. Without the
  // last two flags each screenshot also waits for the next vsync tick, which costs ~120 ms a frame
  // at 1080p even on a blank page. A seek captured on its own gives the same pixels either way.
  return [`--proxy-server=${origin}`,`--proxy-bypass-list=<-loopback>;127.0.0.1:${port}`,'--force-color-profile=srgb','--hide-scrollbars','--disable-lcd-text','--font-render-hinting=none','--disable-background-networking','--disable-component-update','--disable-sync','--no-first-run','--disable-default-apps','--mute-audio',
    '--disable-gpu-vsync','--disable-frame-rate-limit'];
}

export function captureSettings(options,config) {
  const num=(key,fallback)=>options[key]===undefined?fallback:Number(options[key]);
  const scale=num('scale',1),sub=num('sub',1),shutter=num('shutter',.5),crf=num('crf',16),preset=options.preset??'medium',color=options.color??'zscale';
  if(!Number.isFinite(scale)||scale<.25||scale>4||!Number.isInteger(sub)||sub<1||sub>16||!Number.isFinite(shutter)||shutter<0||shutter>1||!Number.isInteger(crf)||crf<0||crf>51)throw Error('invalid scale/sub/shutter/crf');
  if(!['ultrafast','superfast','veryfast','faster','fast','medium','slow','slower','veryslow'].includes(preset)||!['zscale','swscale'].includes(color))throw Error('invalid preset/color');
  const from=num('from',0),to=num('to',config.duration);
  if(!Number.isFinite(from)||!Number.isFinite(to)||from<0||to>config.duration||to<=from)throw Error('invalid --from/--to');
  // Supersampling (scale>1) resamples back to the page size; a draft (scale<1) stays small like upstream.
  const even=x=>2*Math.max(8,Math.round(x/2));
  const outWidth=scale>=1?config.width:even(config.width*scale),outHeight=scale>=1?config.height:even(config.height*scale);
  return {scale,sub,shutter,crf,preset,color,from,to,outWidth,outHeight};
}

export async function render(options) {
  // Execution currently verified on macOS. Refuse unexercised process cleanup paths rather than advertise portability.
  if(process.platform!=='darwin')throw Error('HOLD: optional rendering execution validated only on macOS; data installation remains portable');
  // As upstream, the served root is the reel folder's parent (the project), so scenes reach ../assets and ../audio.
  const reel=fs.realpathSync(noLinks(options.dir)),root=path.dirname(reel),out=noLinks(options.out);
  const page=path.relative(root,path.join(reel,'index.html')).split(path.sep).join('/');
  const seconds=Number(options.timeout??1800),maxBytes=Number(options['max-output-bytes']??536870912);
  if(!Number.isFinite(seconds)||seconds<1||seconds>21600||!Number.isInteger(maxBytes)||maxBytes<1024||maxBytes>536870912)throw Error('invalid timeout/output limit');
  for(const suffix of ['', '.receipt.json', '.failure.json'])if(fs.existsSync(out+suffix))throw Error('existing output/receipt refused; no exists-only resume');
  if(out===root)throw Error('output must not be the served root');
  const config=JSON.parse(fs.readFileSync(resolveAsset(root,'project.json',new Set(['project.json'])),'utf8'));
  validateConfig(config);
  const allowed=new Set(config.render_files),snapshot=snapshotAssets(root,config.render_files),inputs=snapshot.inputs;
  if(!allowed.has(page))throw Error('render_files must declare the page: '+page);
  if(allowed.has(path.relative(root,out).split(path.sep).join('/')))throw Error('output must not be a declared render file');
  const capture=captureSettings(options,config);
  const frames=Math.round((capture.to-capture.from)*config.fps),first=Math.round(capture.from*config.fps);
  if(config.width*config.height*capture.scale**2*frames*capture.sub>100e9)throw Error('capture pixel budget exceeded (scale/sub)');
  for(const [name,digest] of Object.entries(config.input_sha256||{}))if(inputs[name]!==digest)throw Error('stale asset/font digest: '+name);
  if(!config.fonts?.length)throw Error('HOLD: explicit fonts required');
  const glyphChecks=config.fonts.map(f=>{if(!snapshot.buffers[f.file])throw Error('undeclared font');return glyphChecker(snapshot.buffers[f.file]);});
  for(const run of config.texts||[])assertGlyphs(run.text,glyphChecks);
  const sourceDigest=hash(JSON.stringify(Object.entries(inputs).sort()));
  const require=createRequire(path.join(path.resolve(options['dependency-root']),'omh-explicit-adapter.cjs'));
  const puppeteer=require('puppeteer-core');
  const dependencyVersion=require('puppeteer-core/package.json').version;
  const stills=Boolean(options.stills||options.every);
  let times;
  if(options.stills)times=options.stills.split(',').map(Number);
  else if(options.every){const step=Number(options.every);if(!Number.isFinite(step)||step<=0)throw Error('invalid --every');times=[];for(let t=capture.from;t<capture.to-1e-6&&times.length<=36000;t+=step)times.push(Number(t.toFixed(3)));}
  else times=Array.from({length:frames},(_,i)=>(first+i)/config.fps);
  if(!times.length||times.length>36000||times.some(t=>!Number.isFinite(t)||t<0||t>=config.duration))throw Error('invalid still times');
  // Average sub-frame captures within the output frame's own shot, never across a cut.
  const shots=stills?times:times.flatMap(t=>shutterTimes(t,config.fps,capture.sub,capture.shutter,config.cuts,capture.to));
  fs.mkdirSync(path.dirname(out),{recursive:true});
  const partial=fs.mkdtempSync(out+'.partial-');
  let server,browser,child,encoder,encoderDone,deadline,timeoutReject,launching;
  let browserPid=null,loopbackPort=null,cancelled=false;
  let error=null,receipt=null,bytes=0;
  const cleanup={browser_closed:false,server_closed:false,children_reaped:false};
  const failures=[];
  const timeout=new Promise((_,reject)=>{timeoutReject=reject;deadline=setTimeout(()=>reject(Error('render timeout')),seconds*1000);});
  const interrupt=signal=>timeoutReject(Error('cancelled: '+signal));
  const sigint=()=>interrupt('SIGINT'),sigterm=()=>interrupt('SIGTERM');
  process.once('SIGINT',sigint);process.once('SIGTERM',sigterm);
  async function run(executable,args) {
    if(cancelled)throw Error('cancelled before subprocess');
    return await new Promise((resolve,reject)=>{
      child=spawn(executable,args,{stdio:['ignore','pipe','pipe']});let stdout='',stderr='';
      child.stdout.on('data',b=>{stdout+=b;if(stdout.length>2e6){child.kill('SIGKILL');reject(Error('subprocess output bound'));}});
      child.stderr.on('data',b=>{stderr+=b;if(stderr.length>2e6){child.kill('SIGKILL');reject(Error('subprocess stderr bound'));}});
      child.once('error',reject);child.once('close',code=>{child=null;code===0?resolve(stdout):reject(Error('subprocess failed '+code+': '+stderr.slice(-4000)));});
    });
  }
  async function execute(){
    server=http.createServer((req,res)=>{
      try {
        if(!req.url.startsWith('/'))throw Error('proxy request refused');
        if(req.url==='/favicon.ico'){res.writeHead(204);res.end();return;}
        const pathname=new URL(req.url,'http://127.0.0.1').pathname;
        const name=pathname==='/'?page:pathname.slice(1);
        const file=resolveAsset(root,name,allowed),data=snapshot.buffers[name];
        if(req.method!=='GET'||req.headers.range)throw Error('only bounded full GET supported; range requests refused');
        res.writeHead(200,{'Content-Type':MIME[path.extname(file)]||'application/octet-stream','Content-Length':data.length,'Cache-Control':'no-store','Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self'; connect-src 'self'; media-src 'self'; frame-src 'none'; worker-src 'none'"});
        res.end(data);
      }catch(e){failures.push(String(e));res.writeHead(403);res.end('refused');}
    });
    // Browser-wide denying proxy: popups/other targets cannot bypass the primary
    // page interceptor. Only this exact loopback asset origin bypasses it.
    server.on('connect',(request,socket)=>{failures.push('proxy CONNECT refused');socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n');});
    await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
    loopbackPort=server.address().port;
    const origin=`http://127.0.0.1:${loopbackPort}`;
    launching=puppeteer.launch({executablePath:noLinks(options.browser),headless:true,timeout:Math.min(seconds*1000,30000),protocolTimeout:Math.min(seconds*1000,30000),
      args:browserArgs(origin,loopbackPort)});
    browser=await launching;browserPid=browser.process().pid;
    if(cancelled)throw Error('cancelled after browser launch');
    const browserVersion=await browser.version();
    const tab=await browser.newPage();
    await tab.setViewport({width:config.width,height:config.height,deviceScaleFactor:capture.scale});
    await tab.setRequestInterception(true);
    tab.on('request',request=>{
      if(!request.url().startsWith(origin+'/')){failures.push('external request refused: '+request.url());request.abort();}
      else request.continue();
    });
    tab.on('pageerror',e=>failures.push('pageerror: '+String(e)));
    tab.on('requestfailed',r=>failures.push('requestfailed: '+r.url()));
    tab.on('console',m=>{if(m.type()==='error')failures.push('console: '+m.text());});
    await tab.goto(origin+'/'+page+'?render=1',{waitUntil:'load',timeout:Math.min(seconds*1000,30000)});
    await tab.waitForFunction(()=>globalThis.__ready===true||globalThis.__error,{timeout:Math.min(seconds*1000,30000)});
    const state=await tab.evaluate(()=>({error:globalThis.__error,meta:globalThis.__meta}));
    if(state.error)throw Error(state.error);
    if(['width','height','duration','fps'].some(k=>state.meta[k]!==config[k]))throw Error('page/source metadata mismatch');
    const staged=path.join(partial,'encoded.mp4');
    if(!stills){
      const blur=capture.sub>1?`format=gbrp,tmix=frames=${capture.sub},select='not(mod(n+1\\,${capture.sub}))',setpts=N/(${config.fps}*TB),`:'';
      const resample=capture.scale!==1?`scale=${capture.outWidth}:${capture.outHeight}:flags=lanczos,`:'';
      const color=capture.color==='zscale'?'zscale=pin=bt709:tin=iec61966-2-1:min=gbr:rin=full:p=bt709:t=bt709:m=bt709:r=limited,format=yuv420p,setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709'
        :'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709';
      encoder=spawn(options.ffmpeg,['-v','error','-nostdin','-n','-f','image2pipe','-c:v','png','-framerate',String(config.fps*capture.sub),'-i','-','-vf',blur+resample+color,'-r',String(config.fps),'-frames:v',String(times.length),'-c:v','libx264','-preset',capture.preset,'-crf',String(capture.crf),'-pix_fmt','yuv420p','-color_range','tv','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-movflags','+faststart','-fs',String(maxBytes),staged],{stdio:['pipe','ignore','pipe']});
      child=encoder;let stderr='';
      encoder.stderr.on('data',b=>{stderr+=b;if(stderr.length>2e6)encoder.kill('SIGKILL');});
      encoder.stdin.on('error',e=>failures.push('encoder stdin: '+String(e)));
      encoderDone=new Promise((resolve,reject)=>{encoder.once('error',reject);encoder.once('close',code=>{child=null;code===0?resolve():reject(Error('encoder failed '+code+': '+stderr.slice(-4000)));});});
      encoderDone.catch(()=>{});
    }
    for(let i=0;i<shots.length;i++){
      if(failures.length)throw Error(failures.join('; '));
      await tab.evaluate(async t=>{
        await globalThis.__seek(t);
        await document.fonts.ready;
        if([...document.fonts].some(f=>f.status!=='loaded'))throw Error('font not ready');
        await Promise.all([...document.images].map(im=>im.decode()));
        if([...document.images].some(im=>!im.naturalWidth))throw Error('image missing');
        document.body.getBoundingClientRect();
        // screenshot() flushes the synchronous canvas/DOM mutations through compositor capture.
        if(document.getAnimations().some(a=>a.playState==='running'))throw Error('nondeterministic running animation refused');
      },shots[i]);
      if(stills||i%capture.sub===0)assertGlyphs(await tab.evaluate(()=>document.body.innerText),glyphChecks);
      const buffer=await tab.screenshot({type:'png',captureBeyondViewport:false,omitBackground:false,optimizeForSpeed:true});
      if(stills){
        bytes+=buffer.length;if(bytes>maxBytes)throw Error('capture output byte limit');
        fs.writeFileSync(path.join(partial,`${String(i).padStart(6,'0')}.png`),buffer,{flag:'wx'});
      }else if(!encoder.stdin.write(buffer))await Promise.race([once(encoder.stdin,'drain'),encoderDone]);
    }
    if(!stills){encoder.stdin.end();await encoderDone;}
    if(failures.length)throw Error(failures.join('; '));
    const versions={node:process.version,puppeteer_core:dependencyVersion,browser:browserVersion,
      adapter_sha256:hash(fs.readFileSync(fileURLToPath(import.meta.url))),
      node_sha256:hash(fs.readFileSync(process.execPath)),browser_sha256:hash(fs.readFileSync(options.browser)),
      ffmpeg:(await run(options.ffmpeg,['-version'])).split('\n')[0],ffprobe:(await run(options.ffprobe,['-version'])).split('\n')[0],
      ffmpeg_sha256:hash(fs.readFileSync(options.ffmpeg)),ffprobe_sha256:hash(fs.readFileSync(options.ffprobe))};
    if(stills){
      receipt={status:'PASS',mode:'stills',times,scale:capture.scale,source_sha256:sourceDigest,inputs,versions,limitations:['No artistic/playback/listening/native-language approval']};
    }else{
      if(fs.statSync(staged).size>maxBytes)throw Error('encoded output byte limit');
      const probed=JSON.parse(await run(options.ffprobe,['-v','error','-count_frames','-show_streams','-show_format','-of','json',staged]));
      const v=probed.streams.find(s=>s.codec_type==='video');
      if(!v||Number(v.nb_read_frames)!==times.length||v.width!==capture.outWidth||v.height!==capture.outHeight)throw Error('decoded frame/dimension mismatch');
      const colorTags={range:v.color_range,space:v.color_space,transfer:v.color_transfer,primaries:v.color_primaries};
      if(JSON.stringify(colorTags)!==JSON.stringify({range:'tv',space:'bt709',transfer:'bt709',primaries:'bt709'}))throw Error('encoded color mismatch');
      await run(options.ffmpeg,['-v','error','-xerror','-nostdin','-i',staged,'-f','null','-']);
      const {outWidth,outHeight,...quality}=capture;
      receipt={status:'PASS',mode:'video',decoded_frames:Number(v.nb_read_frames),width:outWidth,height:outHeight,quality,color:colorTags,source_sha256:sourceDigest,inputs,versions,artifact_sha256:hash(fs.readFileSync(staged)),bytes:fs.statSync(staged).size,limitations:['Technical verification only; artistic/playback/listening/native-language review not observed','Serial capture piped to FFmpeg; no resume/chunks/workers']};
    }
  }
  try {await Promise.race([execute(),timeout]);}
  catch(e){error=Error(String(e)+'; '+failures.join('; '));}
  finally {
    cancelled=true;
    clearTimeout(deadline);
    if(launching&&!browser){try{browser=await launching;browserPid=browser.process().pid;}catch(e){error=error||e;}}
    process.removeListener('SIGINT',sigint);process.removeListener('SIGTERM',sigterm);
    if(child){const active=child;active.kill('SIGKILL');await new Promise(resolve=>active.once('close',resolve));}
    cleanup.children_reaped=true;
    if(browser){await browser.close().catch(e=>{error=error||e;browser.process()?.kill('SIGKILL');});}
    cleanup.browser_closed=true;
    if(server){server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
    cleanup.server_closed=true;
  }
  if(!error&&failures.length)error=Error(failures.join('; '));
  if(error){
    fs.writeFileSync(out+'.failure.json',JSON.stringify({status:'HOLD',error:String(error),partial,source_sha256:sourceDigest,cleanup,browser_pid:browserPid,loopback_port:loopbackPort},null,2)+'\n',{flag:'wx'});
    throw error;
  }
  receipt.cuts=config.cuts?.length??0;
  receipt.cleanup=cleanup;
  if(stills)fs.renameSync(partial,out);
  else {fs.renameSync(path.join(partial,'encoded.mp4'),out);fs.rmdirSync(partial);}
  fs.writeFileSync(out+'.receipt.json',JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});
  // Stills stay as PNGs for cut/seek QA; video frames stream to the encoder and are not retained.
  return {...receipt,partial_frames:stills?out:null};
}

async function main(){
  const allowed=new Set(['dir','out','browser','dependency-root','ffmpeg','ffprobe','timeout','max-output-bytes','stills','every','from','to','scale','sub','shutter','crf','preset','color']);
  const opts={};
  for(let i=2;i<process.argv.length;i+=2){const key=process.argv[i].replace(/^--/,'');if(!process.argv[i].startsWith('--')||!allowed.has(key)||!process.argv[i+1]||opts[key])throw Error('unknown/missing/duplicate option: '+process.argv[i]);opts[key]=process.argv[i+1];}
  for(const key of ['dir','out','browser','dependency-root','ffmpeg','ffprobe'])if(!opts[key])throw Error('explicit --'+key+' required; no dependency bootstrap');
  console.log(JSON.stringify(await render(opts)));
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))main().catch(e=>{console.error(String(e));process.exitCode=1;});
