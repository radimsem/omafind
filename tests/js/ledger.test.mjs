import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { load } from './load.mjs';
import { plain, freeze } from './fixtures.mjs';
const l=load('ledger.js');
const tree=freeze(JSON.parse(readFileSync(new URL('../fixtures/setup/documents-tree.json',import.meta.url))));
const discover=JSON.parse(readFileSync(new URL('../fixtures/setup/discover.json',import.meta.url)));
const excludes=freeze([{path:'tax/2024',rule:'user',added:0},{path:'vault/exports',rule:'generated'},{path:'archive/old-backups',rule:'no-kind'}]);
const values=tokens=>plain(tokens).map(({k,v})=>[k,v]);

test('Documents ledger partitions found counts once including nested secrets',()=>{
  const result=l.compute(tree,excludes);
  assert.deepEqual(plain(result.found),{text:806,pdf:67,image:26,video:0,audio:0,total:899});
  assert.deepEqual(plain(result.kept),{text:731,pdf:45,image:17,video:0,audio:0,total:793});
  assert.deepEqual(plain(result.leftOut),{text:75,pdf:22,image:9,video:0,audio:0,total:106});
  assert.deepEqual(plain(result.entries).map(e=>[e.path,e.rule,e.files]), [['tax/2024','user',45],['vault/exports','generated',58],['archive/old-backups','no-kind',0],['**','secrets',3]]);
  assert.equal(result.dirs,3); assert.equal(result.secrets.files,3);
  assert.deepEqual(plain(result.entries[0].evidence),{files:45,added:0});
});
test('owner uses rule precedence then outermost path on ties',()=>{
  const es=[{path:'a',rule:'no-kind'},{path:'a/b',rule:'generated'},{path:'a/b/c',rule:'user'}];
  assert.equal(l.owner('a/b/c/d',es).rule,'user');
  assert.equal(l.owner('a/bc',es).path,'a');
  assert.equal(l.owner('ab',es),null);
  assert.equal(l.owner('a/b',[{path:'a/b',rule:'user'},{path:'a',rule:'user'}]).path,'a');
  assert.equal(l.owner('a/b',[{path:'a',rule:'user'},{path:'a/b',rule:'secrets'}]).rule,'secrets');
});
test('random nested ledgers preserve per-kind accounting and ownership',()=>{
  let seed=5; const rand=n=>(seed=(Math.imul(seed,1664525)+1013904223)>>>0)%n;
  const kinds=['text','pdf','image','video','audio'];
  for(let trial=0;trial<200;trial++){
    const dirs=Array.from({length:20},(_,i)=>({path:`d${i%4}/s${i}`,own:Object.fromEntries(kinds.map(k=>[k,rand(12)])),rule:null,evidence:null}));
    const es=Array.from({length:8},()=>({path:rand(2)?`d${rand(4)}`:dirs[rand(20)].path,rule:['user','generated','no-kind'][rand(3)]}));
    const secrets={counts:Object.fromEntries(kinds.map(k=>[k,rand(4)])),evidence:{exts:[],in:[]}};
    secrets.files=Object.values(secrets.counts).reduce((a,b)=>a+b,0);
    const r=l.compute({dirs,secrets},es);
    for(const k of kinds){
      assert.equal(r.found[k],r.kept[k]+r.leftOut[k]);
      assert.equal(r.leftOut[k],r.entries.reduce((n,e)=>n+e.counts[k],0));
      const expected=dirs.filter(d=>!es.some(e=>d.path===e.path||d.path.startsWith(e.path+'/'))).reduce((n,d)=>n+d.own[k],0);
      assert.equal(r.kept[k],expected);
    }
  }
});
test('ledger header footer and summary expose board accounting',()=>{
  const r=l.compute(tree,excludes);
  assert.equal(l.header(r),'4 entries · 106 files');
  const footer=l.footer(r,discover.rates,'gpu','/home/u/Documents','/home/u');
  assert.deepEqual(plain(footer),{found:'899',leftOut:'106',kept:'793',leftSub:'3 dirs · 3 secrets',keptLabel:'Kept in ~/Documents',keptSub:'index 10 MB · time ~1 min'});
  const summary=l.summary(r); assert.equal(summary.found,899);assert.equal(summary.kept,793);assert.equal(summary.entries.length,4);
});
test('evidence tokens are specific to each rule',()=>{
  const entries=l.compute(tree,excludes).entries;
  assert.equal(values(l.entryFacts(entries[0])).at(-1)[1],'45');
  assert.deepEqual(values(l.entryFacts(entries[1])),[['pattern','inv-YYYYMMDD.txt'],['match','58/58'],['dataset limit','300']]);
  assert.deepEqual(values(l.entryFacts(entries[2])),[['files','37'],['.zip','31'],['.tar.gz','6'],['searchable','0']]);
  assert.equal(l.entryFacts(entries[2]).at(-1).tone,'strong');
  assert.deepEqual(values(l.entryFacts(entries[3])),[['.env','3'],['.kdbx','1'],['in','tax/2024, work/clients']]);
});
test('exclude edits are immutable and timestamps format local time',()=>{
  const next=l.addExclude(excludes,'tax/2023','user',100);
  assert.equal(next.length,4);assert.equal(excludes.length,3);
  assert.equal(l.addExclude(next,'tax/2023','user',200).length,4);
  assert.equal(l.removeExclude(next,'tax/2023').length,3);
  assert.equal(l.formatAdded(new Date(2026,9,11,10,7).getTime()),'2026-10-11 10:07');
});

test('overlapping rules allocate to the highest priority without double counting',()=>{
  const c={text:2,pdf:0,image:0,video:0,audio:0};
  const result=l.compute({dirs:[{path:'a/b',own:c,evidence:null}],secrets:null},[
    {path:'a',rule:'no-kind'},{path:'a/b',rule:'generated'},{path:'a',rule:'user'}]);
  assert.deepEqual(plain(result.entries).map(e=>e.files),[0,0,2]);
  assert.equal(result.leftOut.total,2);assert.equal(result.kept.total,0);
});
test('no-content secret matches remain evidence without changing totals',()=>{
  const c={text:0,pdf:0,image:0,video:0,audio:0};
  const result=l.compute({dirs:[],secrets:{counts:c,files:0,evidence:{exts:[['.kdbx',1]],in:['tax']}}},[]);
  assert.equal(result.found.total,0);assert.equal(result.entries.length,1);
  assert.deepEqual(values(l.entryFacts(result.entries[0])),[['.kdbx','1'],['in','tax']]);
});
