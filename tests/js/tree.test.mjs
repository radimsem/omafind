import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { load } from './load.mjs';
import { plain, freeze } from './fixtures.mjs';
const t=load('tree.js');
const tree=freeze(JSON.parse(readFileSync(new URL('../fixtures/setup/documents-tree.json',import.meta.url))));
const es=freeze([{path:'tax/2024',rule:'user',added:1}]);

test('marks compare whole names and root contains all descendants',()=>{
  assert.equal(t.isInside('tax/2024','tax'),true);assert.equal(t.isInside('taxes','tax'),false);assert.equal(t.isInside('tax',''),true);
  assert.equal(t.mark('',es),'mixed');assert.equal(t.mark('tax',es),'mixed');assert.equal(t.mark('tax/2023',es),'on');assert.equal(t.mark('tax/2024/deep',es),'off');
  assert.deepEqual(plain(t.keptDirs(tree,'tax',es)),{kept:1,total:2});
});
test('toggle records leave restore and undo without mutating previous state',()=>{
  const initial=t.initial(tree,es);const left=t.toggle(initial,'tax/2023',100);const restored=t.toggle(left,'tax/2023',200);
  assert.equal(t.mark('tax/2023',left.excludes),'off');assert.equal(t.mark('tax/2023',restored.excludes),'on');
  assert.deepEqual(plain(restored.last),{path:'tax/2023',action:'restore',at:200});
  assert.deepEqual(plain(t.undo(restored).excludes),plain(left.excludes));assert.equal(t.undo(restored).last,null);
  assert.deepEqual(plain(initial.excludes),plain(es));assert.equal(initial.history.length,0);
});
test('restoring a child of an excluded ancestor keeps sibling exclusions',()=>{
  const state=t.initial(tree,[{path:'',rule:'user',added:1}]);
  const restored=t.toggle(state,'tax/2024',100);
  assert.deepEqual(plain(restored.excludes),[{path:'',rule:'user',added:1}]);assert.deepEqual(plain(restored.chosen),['tax/2024']);
  assert.equal(t.mark('tax/2024',restored.excludes,restored.chosen),'on');
  for(const path of ['tax/2023','work','notes','archive','vault','manuals']) assert.equal(t.mark(path,restored.excludes,restored.chosen),'off');
  assert.equal(t.mark('tax',restored.excludes,restored.chosen),'mixed');
  assert.deepEqual(plain(t.undo(restored).excludes),[{path:'',rule:'user',added:1}]);assert.deepEqual(plain(t.undo(restored).chosen),[]);
});
test('mixed toggle restores entire subtree including nested excludes',()=>{
  const restored=t.toggle(t.initial(tree,es),'tax',100);
  assert.equal(t.mark('tax',restored.excludes),'on');assert.equal(restored.excludes.length,0);
});
test('rule selection is one undo step and reports proposals',()=>{
  const initial=t.initial(tree,[]);const selected=t.selectByRule(initial,'no-kind',100);
  assert.deepEqual(plain(selected.excludes),[{path:'archive/old-backups',rule:'no-kind',added:100}]);
  assert.equal(selected.history.length,1);assert.equal(t.undo(selected).excludes.length,0);
  assert.deepEqual(plain(t.ruleCounts(tree,es)),{'no-kind':1,generated:1,big:0});
});
test('rows expose top-level dirs and expansion reveals direct children',()=>{
  const initial=t.initial(tree,es);const rows=t.rows(tree,initial);
  assert.equal(rows.some(r=>r.path==='tax/2024'),false);assert.equal(rows.length,6);
  const expanded=t.expand(initial,'tax',true);const tax=t.rows(tree,expanded).find(r=>r.path==='tax');
  assert.equal(tax.expanded,true);assert.equal(tax.mark,'mixed');assert.equal(tax.depth,0);
  assert.deepEqual(plain(tax.facts),[{k:'kept',v:'1/2 dirs',tone:'plain'}]);
  assert.equal(t.rows(tree,expanded).find(r=>r.path==='tax/2024').out,true);
  assert.equal(initial.expanded.tax,undefined);
});
test('filter shows case-insensitive path matches and their ancestors',()=>{
  const state=t.setFilter(t.initial(tree,es),'2024');const rows=t.rows(tree,state);
  assert.deepEqual(plain(rows).map(r=>r.path),['tax','tax/2024']);assert.equal(rows[0].expanded,true);
  assert.deepEqual(plain(t.rows(tree,t.setFilter(state,'WORK/CLIENT'))).map(r=>r.path),['work','work/clients']);
});
test('restored row is hot with restore facts and undo clears it',()=>{
  const restored=t.expand(t.toggle(t.initial(tree,es),'tax/2024',100),'tax',true);
  const row=t.rows(tree,restored).find(r=>r.path==='tax/2024');
  assert.equal(row.hot,true);assert.deepEqual(plain(row.facts),[{k:'restored',v:'just now',tone:'plain'}]);
  assert.equal(t.rows(tree,t.undo(restored)).some(r=>r.hot),false);
});
test('composition and bar widths use content counts',()=>{
  assert.deepEqual([415,214,45,18,0].map(t.barWidth),[84,77,60,50,18]);
  const row=t.rows(tree,t.initial(tree,[])).find(r=>r.path==='notes');
  assert.equal(row.files,415);assert.equal(row.barWidth,84);
  assert.deepEqual(plain(row.segments),[{kind:'text',n:412},{kind:'image',n:3}]);
});
test('toRoots makes excludes relative and splits chosen descendants of skips',()=>{
  const roots=t.toRoots(['/a','/a/skipped/chosen','/a/covered'],['/a/skipped','/a/skipped/chosen/no','/ab/no'],()=> 'v');
  assert.deepEqual(plain(roots),[{path:'/a',volume:'v',excludes:['skipped','skipped/chosen/no']},{path:'/a/skipped/chosen',volume:'v',excludes:['no']}]);
});

test('toRoots keeps a chosen folder at a skip and ignores skips equal to a root',()=>{
  assert.deepEqual(plain(t.toRoots(['/a','/a/skip'],['/a/skip'],()=> 'v')), [
    {path:'/a',volume:'v',excludes:['skip']},{path:'/a/skip',volume:'v',excludes:[]}]);
  assert.deepEqual(plain(t.toRoots(['/a','/a/child'],['/a'],()=> 'v')), [{path:'/a',volume:'v',excludes:[]}]);
  assert.deepEqual(plain(t.toRoots(['/','/a'],['/b'],()=> 'v')), [{path:'/',volume:'v',excludes:['b']}]);
});
test('tree paths that match object prototype names only expand when requested',()=>{
  const c={text:1,pdf:0,image:0,video:0,audio:0};
  const special={dirs:['','constructor','constructor/child','__proto__','__proto__/child'].map(path=>({path,own:c,sub:c,all_sub:1,dirs:1,exts:[],rule:null,evidence:null}))};
  const state=t.initial(special,[]);
  assert.deepEqual(plain(t.rows(special,state)).map(r=>r.path),['constructor','__proto__']);
  assert.equal(t.rows(special,t.expand(state,'__proto__',true)).length,3);
});
test('selecting big folders excludes with user rules and one history step',()=>{
  const big={dirs:[{path:'',sub:{text:1200}},{path:'large',sub:{text:1001},rule:null},{path:'small',sub:{text:1000},rule:null}]};
  assert.equal(t.ruleCounts(big,[]).big,1);
  const selected=t.selectByRule(t.initial(big,[]),'big',200);
  assert.deepEqual(plain(selected.excludes),[{path:'large',rule:'user',added:200}]);
  assert.equal(selected.history.length,1);
});
test('parent rows count only kept descendants and stay consistent with the ledger',()=>{
  const state=t.expand(t.expand(t.initial(tree,[...es,{path:'vault/exports',rule:'generated'}]),'tax',true),'vault',true);
  const rows=t.rows(tree,state);const row=p=>plain(rows.find(r=>r.path===p));
  assert.deepEqual(row('tax').counts,{text:10,pdf:18,image:6,video:0,audio:0});
  assert.deepEqual(row('vault').counts,{text:90,pdf:0,image:2,video:0,audio:0});
  assert.equal(row('tax').files,34);
  assert.deepEqual(row('tax').segments,[{kind:'text',n:10},{kind:'pdf',n:18},{kind:'image',n:6}]);
  assert.deepEqual(row('tax/2024').counts,{text:14,pdf:22,image:9,video:0,audio:0});
  assert.equal(row('notes').expandable,true);
});

const ledger=load('ledger.js');
const ownTax=freeze({...tree,dirs:tree.dirs.map(d=>d.path==='tax'?{...d,own:{...d.own,text:3},sub:{...d.sub,text:d.sub.text+3}}
  :d.path===''?{...d,sub:{...d.sub,text:d.sub.text+3}}:d)});
test('restoring a child of an excluded parent keeps the parent own files left out',()=>{
  const restored=t.expand(t.toggle(t.initial(ownTax,[{path:'tax',rule:'user',added:1}]),'tax/2024',100),'tax',true);
  assert.deepEqual(plain(restored.excludes),[{path:'tax',rule:'user',added:1}]);assert.deepEqual(plain(restored.chosen),['tax/2024']);
  assert.equal(t.mark('tax',restored.excludes,restored.chosen),'mixed');assert.equal(t.mark('tax/2023',restored.excludes,restored.chosen),'off');
  const rows=t.rows(ownTax,restored);const row=p=>plain(rows.find(r=>r.path===p));
  assert.deepEqual(row('tax').counts,{text:14,pdf:22,image:9,video:0,audio:0});assert.equal(row('tax').out,false);
  assert.equal(row('tax/2024').rule,null);assert.equal(row('tax/2024').out,false);
  const l=t.ledger(ownTax,restored.excludes,restored.chosen,ledger.compute);
  assert.deepEqual(plain(l.entries.find(e=>e.path==='tax').counts),{text:13,pdf:18,image:6,video:0,audio:0});
  assert.equal(l.found.total,l.kept.total+l.leftOut.total);
  assert.equal(l.found.total,ledger.compute(ownTax,[]).found.total);
  const roots=t.toRoots(['/d','/d/'+restored.chosen[0]],restored.excludes.map(e=>'/d/'+e.path),()=> 'v');
  assert.deepEqual(plain(roots),[{path:'/d',volume:'v',excludes:['tax']},{path:'/d/tax/2024',volume:'v',excludes:[]}]);
  const left=t.toggle(restored,'tax/2024',200);
  assert.deepEqual(plain(left.chosen),[]);assert.deepEqual(plain(left.excludes),[{path:'tax',rule:'user',added:1}]);
});

test('a rule that leaves out a chosen folder unchooses it',()=>{
  const restored=t.toggle(t.initial(tree,[{path:'archive',rule:'user',added:1}]),'archive/old-backups',100);
  assert.deepEqual(plain(restored.chosen),['archive/old-backups']);
  const selected=t.selectByRule(restored,'no-kind',200);
  assert.deepEqual(plain(selected.chosen),[]);
  assert.equal(t.mark('archive/old-backups',selected.excludes,selected.chosen),'off');
  assert.deepEqual(plain(t.undo(selected).chosen),['archive/old-backups']);
});
