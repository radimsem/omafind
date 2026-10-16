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
  assert.equal(s.step({runtimeProgress: {state: 'done'}, progress, folders: true}), 2);
  assert.equal(s.step({runtimeProgress: {state: 'done'}, progress, folders: true, back: true}), 1);
  assert.equal(s.step({runtimeProgress: runtime, progress, folders: true}), 1);
  assert.equal(s.engineReady(null), false);
});
test('the shortcut opens setup until the engine is installed', () => {
  assert.equal(s.opensSetup('search', false, null), true);
  assert.equal(s.opensSetup('setup', true, { state: 'done' }), true);
  assert.equal(s.opensSetup('search', true, null), false);
  assert.equal(s.opensSetup('search', true, { state: 'done' }), false);
  for (const state of ['idle', 'running', 'paused', 'failed'])
    assert.equal(s.opensSetup('search', true, { state }), true, state);
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
  for (const [state,text,action,visible] of [['idle','Install','install',true],['running','Pause','pause',true],['paused','Resume','install',true],['failed','Retry','install',true],['done','Install','install',false]]) {
    assert.deepEqual(plain(s.engineButton({state},true)), {text,action,visible,enabled:true});
  }
  assert.equal(s.engineButton(null,false).enabled, false);
  assert.equal(s.totalFraction(runtime), 512/865);
  assert.equal(s.totalFraction({done:100,total:10}), 1);
  assert.equal(s.totalFraction(null), 0);
  assert.equal(s.engineHint(runtime), 'You can close this. Installing keeps going.');
  assert.equal(s.engineHint({state:'failed',reason:'Try again.'}), '');
  assert.equal(s.engineHint({state:'done'}), 'Everything is installed. Folders are next.');
});
test('model task uses progress facts and omits unknown time', () => {
  assert.deepEqual(values(s.modelTask(runtime).got), [['got','512/865 MB'],['left','~1 min']]);
  assert.deepEqual(values(s.modelTask({...runtime,left_seconds:null}).got), [['got','512/865 MB'],['verify','sha256']]);
  assert.equal(s.modelTask({state:'done'}).value, 'Installed');
  assert.equal(s.modelTask({state:'paused'}).value, 'Paused');
  assert.equal(s.modelTask(null).value, 'Not downloaded');
});
test('helper and server tasks expose installation and build facts', () => {
  assert.equal(s.helperTask({unit:"enabled",socket:"ready"}).value, 'Installed');
  assert.equal(s.helperTask({unit:"missing",socket:"closed"}).install, true);
  assert.deepEqual(values(s.helperTask({unit:"enabled",socket:"ready"}).tokens), [['unit','omafind.service active'],['venv','~/.local/share/omafind']]);
  assert.equal(s.serverTask(runtime).value, 'Built in 3 min 12 s');
  assert.equal(s.serverTask({...runtime,build:{...runtime.build,seconds:null}}).value, 'Installed');
  assert.equal(s.serverTask({state:'running',build:{state:'run',seconds:65}}).value, 'Building · 1 min 05 s');
  assert.equal(s.serverTask({state:'failed',build:{state:'failed'}}).mark, 'failed');
  assert.equal(s.serverTask(null).value, 'Not installed');
});
test('file lines distinguish wait run verify and verified', () => {
  for (const [state,icon,text,done] of [['wait','·','555 MB · queued',false],['run','↓','202 of 555 MB',false],['verify','↓','555 MB · checking sha256',false],['ok','✓','555 MB · verified',true]]) {
    const line=s.fileLines({...runtime,files:{mmproj:{name:'m',state,done:202,total:555}}})[0];
    assert.equal(line.icon,icon); assert.equal(line.mb,text); assert.equal(line.done,done);
    assert.equal(line.fraction, done ? 1 : 202/555);
  }
});
test('total facts and estimates use kind rates', () => {
  assert.deepEqual(values(s.totalFacts({files:1209,bytes:13606000,seconds:147.51},'gpu')), [['selected','1,209 files'],['index','14 MB'],['time','~2 min'],['device','GPU']]);
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

test('formatting boundaries and empty progress stay finite',()=>{
  assert.equal(s.treeTime(.5),'1 s'); assert.equal(s.treeTime(90),'2 min');
  assert.equal(s.mb(1e6),'1 MB'); assert.equal(s.minutes(60),'1 min');
  assert.equal(s.indexHead(null,discover.rates).fraction,0);
  assert.equal(s.kindRows(null).length,5);
  assert.deepEqual(plain(s.fileLines(null)),[]);
});
test('paused build presents a stationary task while verified server stays installed',()=>{
  const paused=s.serverTask({state:'paused',build:{state:'run',seconds:65}});
  assert.equal(paused.mark,'wait');assert.equal(paused.value,'Paused');
  assert.equal(s.serverTask({...runtime,state:'paused'}).mark,'ok');
});
test('estimates and problem facts tolerate data that has not arrived', () => {
  assert.deepEqual(plain(s.estimate(null, discover.rates, 'gpu')), {bytes: 0, seconds: 0});
  assert.deepEqual(plain(s.estimate({text: 1}, null, 'gpu')), {bytes: 0, seconds: 0});
  assert.deepEqual(plain(s.problemFacts(null)), []);
});

test('a failed run adds an exit token to the index header', () => {
  const stopped = {...progress, running: false, device: null, vram_gb: null};
  assert.deepEqual(values(s.indexHead({...stopped, exit: 2}, discover.rates).side), [['exit', '2']]);
  assert.deepEqual(values(s.indexHead({...stopped, exit: 0}, discover.rates).side), []);
  assert.deepEqual(values(s.indexHead({...stopped, exit: 2, running: true}, discover.rates).side), []);
  assert.equal(s.indexFailure, undefined);
});

test('step 3 title follows the run outcome', () => {
  assert.equal(s.indexTitle(null, ''), 'Indexing your files');
  assert.equal(s.indexTitle({...progress, running: true}, ''), 'Indexing your files');
  assert.equal(s.indexTitle({...progress, running: false, done: 5, queued: 0}, ''), 'Indexing finished');
  assert.equal(s.indexTitle({...progress, running: false, exit: 1}, 'exit 1'), 'Indexing stopped');
  assert.equal(s.indexTitle({...progress, running: true}, {code: 'no-roots', title: 'No folders are selected.', detail: 'Pick at least one folder to index.'}), 'Indexing stopped');
});


test('step 3 title stops for paused queues and failed exits without an error sentence', () => {
  assert.equal(s.indexTitle({...progress, running: false, done: 5, queued: 4}, ''), 'Indexing stopped');
  assert.equal(s.indexTitle({...progress, running: false, done: 5, queued: 0, exit: 1}, ''), 'Indexing stopped');
});

test('scan time shows one decimal place', () => {
  assert.equal(s.scanFacts(1, {'/h': {done: true, seconds: .84129}})[0].v, '0.8 s');
  assert.equal(s.scanFacts(1, {'/h': {done: true, seconds: 1}})[0].v, '1.0 s');
});

test('chips and panel sizes follow each step', () => {
  assert.deepEqual(plain(s.chips(2)), [{label:'Search engine',state:'done',mark:'✓'}, {label:'Folders',state:'cur',mark:'2'}, {label:'Index',state:'todo',mark:'3'}]);
  assert.equal(s.stepLabel(2), 'Step 2 of 3');
  for (const [step, size] of [[1,[760,474]], [2,[1120,992]], [3,[920,574]]]) {
    assert.deepEqual(Object.values(plain(s.panelSize(step))), size);
  }
});
test('scan facts count folders while walks run, then show the walk time', () => {
  assert.deepEqual(values(s.scanFacts(1234, {})), [['folders','1,234'],['scanning','']]);
  assert.deepEqual(values(s.scanFacts(12, {'/h': {done: true, seconds: 1.4}, '/m': {done: false}})), [['folders','12'],['scanning','']]);
  assert.deepEqual(values(s.scanFacts(12, {'/h': {done: true, seconds: 1.44}, '/m': {done: true, seconds: 0.3}})), [['scanned in','1.4 s']]);
  assert.equal(s.walkError({'/h': {done: true, error: ''}}), '');
  assert.equal(s.walkError({'/h': {done: true, error: 'fd failed: boom'}}), 'fd failed: boom');
});
test('dataset facts name the kind, the file count and the machine-named share', () => {
  assert.deepEqual(values(s.datasetFacts({kind: 'image', files: 1418, named: 96})), [['images','1,418'],['named','96%']]);
  assert.deepEqual(values(s.datasetFacts({kind: 'audio', files: 300, named: 70})), [['audio','300'],['named','70%']]);
});


test('failed walks show no scan time', () => {
  assert.deepEqual(values(s.scanFacts(12, { '/h': { done: true, seconds: 0, error: 'fd failed' } })),
    [['folders', '12']]);
});

test('the header no longer builds folder error sentences', () => {
  assert.equal(s.folderError, undefined);
});

test('problem rows show the code, the detail and the path', () => {
  assert.deepEqual(values(s.problemTokens(progress.problems[0], '/home/u')),
    [['encrypted-pdf', 'pdfinfo failed: Incorrect password'], ['path', '~/Documents/a.pdf']]);
  assert.deepEqual(values(s.problemTokens({path: '/home/u/b.pdf', reason: 'timeout'}, '/home/u')),
    [['timeout', ''], ['path', '~/b.pdf']]);
});

const idle = freeze({ ...plain(runtime), state: 'idle', step: null, file: null, done: 0, left_seconds: null,
  build: { ...runtime.build, state: 'wait', seconds: null },
  files: { model: { ...runtime.files.model, state: 'wait', done: 0 }, mmproj: { ...runtime.files.mmproj, state: 'wait', done: 0 } } });
const building = freeze({ ...idle, state: 'running', step: 'build', build: { ...idle.build, state: 'run', seconds: 72 } });
const failedBuild = freeze({ ...idle, state: 'failed', build: { ...idle.build, state: 'failed', seconds: 40 },
  error: { code: 'build-missing-packages', title: 'The search engine could not be built.',
    detail: 'Missing build packages: vulkan-headers. Install them, then press Retry.',
    fix: { kind: 'install', packages: ['vulkan-headers'] } } });
const failedDownload = freeze({ ...runtime, state: 'failed', left_seconds: null,
  error: { code: 'model-download-failed', title: 'The model could not be downloaded.',
    detail: 'HTTP 503. Check the network connection, then press Retry.', fix: { kind: 'retry' } } });
const paused = freeze({ ...building, state: 'paused' });
const installed = freeze({ ...runtime, state: 'done', step: null, file: null, done: 865, left_seconds: null,
  build: { ...runtime.build, seconds: null },
  files: { model: runtime.files.model, mmproj: { ...runtime.files.mmproj, state: 'ok', done: 555 } } });

function stepOne(rp) {
  const server = s.serverTask(rp), model = s.modelTask(rp), button = s.engineButton(rp, true);
  return { server: server.value, serverMark: server.mark, model: model.value, modelMark: model.mark,
    files: plain(s.fileLines(rp)).map(line => line.mb), hint: s.engineHint(rp),
    button: button.text, action: button.action, visible: button.visible };
}

test('step 1 rows follow the labels table for each situation', () => {
  const running = 'You can close this. Installing keeps going.';
  for (const [name, rp, expected] of [
    ['nothing pressed', idle, { server: 'Not installed', serverMark: 'wait', model: 'Not downloaded', modelMark: 'wait',
      files: ['310 MB · not downloaded', '555 MB · not downloaded'],
      hint: 'Install builds the server (about 3 min) and downloads the model (865 MB).',
      button: 'Install', action: 'install', visible: true }],
    ['building', building, { server: 'Building · 1 min 12 s', serverMark: 'run', model: 'Waiting', modelMark: 'wait',
      files: ['310 MB · queued', '555 MB · queued'], hint: running, button: 'Pause', action: 'pause', visible: true }],
    ['downloading', runtime, { server: 'Built in 3 min 12 s', serverMark: 'ok', model: null, modelMark: 'run',
      files: ['310 MB · verified', '202 of 555 MB'], hint: running, button: 'Pause', action: 'pause', visible: true }],
    ['build failed', failedBuild, { server: 'Failed', serverMark: 'failed', model: 'Not downloaded', modelMark: 'wait',
      files: ['310 MB · not downloaded', '555 MB · not downloaded'], hint: '', button: 'Retry', action: 'install', visible: true }],
    ['download failed', failedDownload, { server: 'Built in 3 min 12 s', serverMark: 'ok', model: 'Failed', modelMark: 'failed',
      files: ['310 MB · verified', '202 of 555 MB'], hint: '', button: 'Retry', action: 'install', visible: true }],
    ['paused', paused, { server: 'Paused', serverMark: 'wait', model: 'Paused', modelMark: 'wait',
      files: ['310 MB · queued', '555 MB · queued'], hint: running, button: 'Resume', action: 'install', visible: true }],
    ['done', installed, { server: 'Installed', serverMark: 'ok', model: 'Installed', modelMark: 'ok',
      files: ['310 MB · verified', '555 MB · verified'], hint: 'Everything is installed. Folders are next.',
      button: 'Install', action: 'install', visible: false }],
  ]) assert.deepEqual(stepOne(rp), expected, name);
});

test('the step 1 hint takes the model size from the daemon and the build time from one constant', () => {
  assert.equal(s.BUILD_MINUTES, 3);
  assert.equal(s.engineHint(null), 'Install builds the server (about 3 min) and downloads the model.');
  assert.equal(s.engineHint({ ...idle, total: 900 }), 'Install builds the server (about 3 min) and downloads the model (900 MB).');
  assert.equal(s.engineHint({ ...idle, build: { ...idle.build, state: 'ok' } }), 'Install downloads the model (865 MB).');
  assert.equal(s.serverTask({ ...idle, build: { ...idle.build, state: 'ok' } }).value, 'Installed');
});

test('a retried build shows Building, not the old failure', () => {
  const retried = { ...failedBuild, state: 'running', step: null, error: null };
  assert.equal(s.serverTask(retried).mark, 'run');
  assert.match(s.serverTask(retried).value, /^Building/);
  assert.equal(s.modelTask(retried).value, 'Waiting');
});

test('estimates and progress count only the five kinds', () => {
  const s = load('setup.js');
  const rates = { gpu: { text: 1, pdf: 0, image: 0, video: 0, audio: 0 },
    bytes: { text: 10, pdf: 0, image: 0, video: 0, audio: 0 } };
  assert.deepEqual(plain(s.estimate({ text: 2, code: 4 }, rates, 'gpu')), { bytes: 20, seconds: 2 });
  const run = { running: true, done: 10, queued: 0, device: 'gpu', kinds: { text: { done: 10, total: 10 } },
    code: { done: 30, total: 90 } };
  assert.deepEqual(plain(s.kindRows(run)).map(row => row.label), ['Text', 'PDF', 'Images', 'Video', 'Audio']);
  const head = s.indexHead(run, discover.rates);
  assert.equal(head.count, '10');
  assert.deepEqual(values(head.facts), [['of', '10 files'], ['left', '< 1 min']]);
});
