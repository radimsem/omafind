import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { load } from './load.mjs';
import { plain, freeze } from './fixtures.mjs';
const fixture = name => freeze(JSON.parse(readFileSync(new URL(`../fixtures/setup/${name}.json`, import.meta.url))));
const s = load('setup.js');
const discover = fixture('discover'), runtime = fixture('runtime'), progress = fixture('progress');
const values = tokens => plain(tokens).map(({k, v}) => [k, v]);

test('step derives from daemon facts and local back', () => {
  assert.equal(s.step({}), 1);
  assert.equal(s.step({runtimeProgress: runtime, progress}), 1);
  assert.equal(s.step({runtimeProgress: {state: 'done'}}), 2);
  assert.equal(s.step({runtimeProgress: {state: 'done'}, progress}), 3);
  assert.equal(s.step({runtimeProgress: {state: 'done'}, progress, back: true}), 1);
  assert.equal(s.engineReady(null), false);
});
test('chips and panel sizes follow each step', () => {
  assert.deepEqual(plain(s.chips(2)), [{label:'Search engine',state:'done',mark:'✓'}, {label:'Folders',state:'cur',mark:'2'}, {label:'Index',state:'todo',mark:'3'}]);
  assert.equal(s.stepLabel(2), 'Step 2 of 3');
  for (const [step, sub, size] of [[1,'',[760,474]], [2,'',[1120,992]], [2,'tree',[1120,948]], [3,'',[920,574]]]) {
    assert.deepEqual(Object.values(plain(s.panelSize(step,sub))), size);
  }
});
test('formatters use specified rounding and whole-name home prefixes', () => {
  assert.equal(s.count(1209), '1,209');
  assert.equal(s.displayPath('/home/u/Documents','/home/u'), '~/Documents');
  assert.equal(s.displayPath('/home/user','/home/u'), '/home/user');
  assert.equal(s.displayPath('/home/u','/home/u'), '~');
  assert.equal(s.mb(999999), '< 1 MB'); assert.equal(s.mb(9e6), '9 MB');
  assert.equal(s.minutes(59), '< 1 min'); assert.equal(s.approxMinutes(420), '~7 min');
  assert.deepEqual([.3,40,120,5400].map(s.treeTime), ['< 1 s','40 s','2 min','1.5 h']);
  assert.equal(s.buildTime(192), '3 min 12 s'); assert.equal(s.buildTime(45), '45 s');
});
test('engine controls depend on runtime state and helper readiness', () => {
  for (const [state,text,action,visible] of [['idle','Download','install',true],['running','Pause','pause',true],['paused','Resume','install',true],['failed','Resume','install',true],['done','Download','install',false]]) {
    assert.deepEqual(plain(s.engineButton({state},true)), {text,action,visible,enabled:true});
  }
  assert.equal(s.engineButton(null,false).enabled, false);
  assert.equal(s.totalFraction(runtime), 512/865);
  assert.equal(s.totalFraction({done:100,total:10}), 1);
  assert.equal(s.totalFraction(null), 0);
  assert.equal(s.engineHint(runtime), 'You can close this. The download keeps going.');
  assert.equal(s.engineHint({state:'failed',reason:'Try again.'}), 'Try again.');
  assert.equal(s.engineHint({state:'done'}), 'Everything is installed. Folders are next.');
});
test('model task uses progress facts and omits unknown time', () => {
  assert.deepEqual(values(s.modelTask(runtime).got), [['got','512/865 MB'],['left','~1 min']]);
  assert.deepEqual(values(s.modelTask({...runtime,left_seconds:null}).got), [['got','512/865 MB'],['verify','sha256']]);
  assert.equal(s.modelTask({state:'done'}).value, 'Verified');
  assert.equal(s.modelTask({state:'paused'}).value, 'Paused');
  assert.equal(s.modelTask(null).value, 'Queued');
});
test('helper and server tasks expose installation and build facts', () => {
  assert.equal(s.helperTask({unit:"enabled",socket:"ready"}).value, 'Installed');
  assert.equal(s.helperTask({unit:"missing",socket:"closed"}).install, true);
  assert.deepEqual(values(s.helperTask({unit:"enabled",socket:"ready"}).tokens), [['unit','omafind.service active'],['venv','~/.local/share/omafind']]);
  assert.equal(s.serverTask(runtime).value, 'Built in 3 min 12 s');
  assert.equal(s.serverTask({...runtime,build:{...runtime.build,seconds:null}}).value, 'Installed');
  assert.equal(s.serverTask({state:'running',build:{state:'run',seconds:65}}).value, 'Building · 1 min 05 s');
  assert.equal(s.serverTask({state:'failed',build:{state:'failed'}}).mark, 'failed');
  assert.equal(s.serverTask(null).value, 'Starting');
});
test('file lines distinguish wait run verify and verified', () => {
  for (const [state,icon,text,done] of [['wait','·','555 MB · queued',false],['run','↓','202 of 555 MB',false],['verify','↓','555 MB · checking sha256',false],['ok','✓','555 MB · verified',true]]) {
    const line=s.fileLines({...runtime,files:{mmproj:{name:'m',state,done:202,total:555}}})[0];
    assert.equal(line.icon,icon); assert.equal(line.mb,text); assert.equal(line.done,done);
    assert.equal(line.fraction, done ? 1 : 202/555);
  }
});
test('scan and not-proposed facts omit zero groups', () => {
  assert.deepEqual(values(s.scanFacts(discover)), [['scan','0.8 s'],['roots','$HOME'],['volumes','0'],['dirs','4,812'],['read','names only']]);
  assert.deepEqual(values(s.scanningFacts()), [['roots','$HOME'],['read','names only']]);
  assert.deepEqual(values(s.notProposed(discover.not_proposed,discover.home)), [['not proposed',''],['no-kind','~/Music'],['dot','212 dirs'],['heavy','14 dirs'],['dataset','2 dirs']]);
  assert.deepEqual(plain(s.notProposed({dot:0,heavy:0,dataset:0,no_kind:[]},'/h')), []);
});
test('home row facts match the board ledger', () => {
  const expected=[[['dirs','1,550'],['kept','793/899'],['left out','4']], [['dirs','3'],['.png','388']], [['dirs','4'],['left out','1']], [['dirs','2'],['.mp4','6']]];
  discover.candidates.slice(0,4).forEach((c,i) => assert.deepEqual(values(s.rowFacts(c,i===0?{found:899,kept:793,entries:[1,2,3,4]}:null)),expected[i]));
  assert.deepEqual(values(s.rowFacts(discover.candidates[4])), [['dirs','8'],['rule','dense'],['.md','118'],['.png','31']]);
  assert.deepEqual(values(s.repoFacts(discover.repos[0])), [['git','tracked 1,842'],['rule','secrets, generated']]);
});
test('totals only include checked content and recompute estimates', () => {
  const rows=discover.candidates.map((c,i)=>({...c,counts:i===0?{text:731,pdf:45,image:17,video:0,audio:0}:c.counts}));
  const totals=s.totals(rows,discover.rates,'gpu');
  assert.deepEqual(plain(totals), {files:1209,bytes:13606000,seconds:147.51});
  assert.deepEqual(values(s.totalFacts(totals,'gpu')), [['selected','1,209 files'],['index','14 MB'],['time','~2 min'],['device','GPU']]);
  assert.deepEqual(plain(s.estimate({text:2,pdf:0,image:0,video:0,audio:0},discover.rates,'cpu')), {bytes:22000,seconds:.26});
});
test('kind rows show per-kind progress and soundtrack-only audio', () => {
  assert.deepEqual(plain(s.kindRows(progress)).map(r=>r.text), ['734 of 734 done','31 of 49 · 412 pages',"51 of 420 · 63 OCR'd",'0 of 6 · queued','soundtracks of 6 videos']);
  assert.equal(s.kindRows(progress)[0].done,true);
  assert.equal(s.kindRows({...progress,kinds:{video:{done:1,total:6},audio:{done:1,total:2}}})[3].text, '1 of 6 · running');
});
test('index header derives total and remaining time from kind rates', () => {
  const head=s.indexHead(progress,discover.rates);
  assert.equal(head.count,'612'); assert.equal(head.fraction,612/1209); assert.equal(head.spinning,true);
  assert.deepEqual(values(head.facts), [['of','1,209 files'],['left','~1 min']]);
  assert.deepEqual(values(head.side), [['device','GPU'],['vram','0.9 GB']]);
  assert.deepEqual(values(s.indexHead({...progress,device:null,vram_gb:null,running:false},discover.rates).side), []);
  assert.deepEqual(values(s.problemFacts(progress)), [['skipped',''],['secrets','4'],['size-cap','2'],['failed',''],['encrypted-pdf','1']]);
});
test('shortcut checks handle free ours conflict pending and cycling', () => {
  const checks={'SUPER + E':'free','SUPER + D':'free','SUPER + U':'free'};
  assert.deepEqual(plain(s.shortcutLine(checks,'SUPER + E')), {tone:'ok',text:'Free. Also free: Super D, Super U.'});
  assert.equal(s.shortcutLine({...checks,'SUPER + E':'ours'},'SUPER + E').text,'Bound by omafind.');
  assert.deepEqual(plain(s.shortcutLine({'SUPER + E':{conflict:'Taken'}},'SUPER + E')), {tone:'warn',text:'Taken'});
  assert.equal(s.shortcutLine({},'SUPER + E').tone,'busy');
  assert.deepEqual(plain(s.chordKeys('SUPER + SHIFT + E')), ['Super','Shift','E']);
  assert.equal(s.nextChord(checks,'SUPER + E'),'SUPER + D');
  assert.equal(s.nextChord(checks,'SUPER + D'),'SUPER + U');
  assert.equal(s.nextChord(checks,'SUPER + U'),'SUPER + E');
  assert.equal(s.nextChord({...checks,'SUPER + D':{conflict:'taken'}},'SUPER + E'),'SUPER + U');
});

test('formatting boundaries and empty progress stay finite',()=>{
  assert.equal(s.treeTime(.5),'1 s'); assert.equal(s.treeTime(90),'2 min');
  assert.equal(s.mb(1e6),'1 MB'); assert.equal(s.minutes(60),'1 min');
  assert.equal(s.indexHead(null,discover.rates).fraction,0);
  assert.equal(s.kindRows(null).length,5);
  assert.deepEqual(plain(s.fileLines(null)),[]);
  assert.equal(s.nextChord({},'SUPER + E'),'SUPER + E');
  assert.equal(s.shortcutLine({'SUPER + E':'free'},'SUPER + E').text,'Free.');
});
test('paused build presents a stationary task while verified server stays installed',()=>{
  const paused=s.serverTask({state:'paused',build:{state:'run',seconds:65}});
  assert.equal(paused.mark,'wait');assert.equal(paused.value,'Paused');
  assert.equal(s.serverTask({...runtime,state:'paused'}).mark,'ok');
});
test('estimates and problem facts tolerate data that has not arrived', () => {
  assert.deepEqual(plain(s.estimate(null, discover.rates, 'gpu')), {bytes: 0, seconds: 0});
  assert.deepEqual(plain(s.estimate({text: 1}, null, 'gpu')), {bytes: 0, seconds: 0});
  assert.deepEqual(plain(s.totals(null, null, 'gpu')), {files: 0, bytes: 0, seconds: 0});
  assert.deepEqual(plain(s.problemFacts(null)), []);
});

test('index failure prefers the daemon sentence, then a failed exit code',()=>{
  assert.equal(s.indexFailure({running:false,exit:2},'Indexing stopped. See ~/.local/state/omafind/index.log.'),'Indexing stopped. See ~/.local/state/omafind/index.log.');
  assert.equal(s.indexFailure({running:false,exit:2},''),'exit 2');
  assert.equal(s.indexFailure({running:false,exit:0},''),'');
  assert.equal(s.indexFailure({running:true},''),'');assert.equal(s.indexFailure(null,''),'');
});
