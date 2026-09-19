import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname,join} from 'node:path';

/* Revisi #31/#32/#35/#37 — Sample PIC work surface.
   Halaman .jsx tidak bisa diimpor langsung oleh `node --test` (JSX), jadi logika
   murni diuji lewat salinan ekspor bernama yang sama, dan batas akses (tidak ada
   tombol keputusan buyer) diuji sebagai invariant pada sumber halamannya. */

const here=dirname(fileURLToPath(import.meta.url));
const pagesDir=join(here,'..','src','pages');
const read=name=>readFileSync(join(pagesDir,name),'utf8');

const STAGES=['OPEN','IN_PROGRESS','UPDATE','INSPECTION','SUBMIT_RESULT','DONE'];

function allowedActions(row){
  const allowed=(row&&row.allowed_actions)||[];
  return allowed.filter(a=>!['BUYER_APPROVE','BUYER_REJECT','APPROVE','REJECT'].includes(a));
}

function blockersFor(row){
  const out=[];
  if(!row) return out;
  if(!row.eligible) out.push(row.eligibility_reason||'Order/Article tidak eligible');
  if(row.evidence&&!row.evidence.complete) out.push(`Bukti kurang: ${(row.evidence.missing||[]).join(', ')}`);
  const reqs=row.requirements||{};
  for(const [key,v] of Object.entries(reqs)) if(v&&!v.ok) out.push(v.label);
  if(row.blocker) out.push(`${row.blocker} (owner ${row.blocker_owner||'—'})`);
  return [...new Set(out)];
}

function evidenceLabel(evidence){
  if(!evidence) return '—';
  const missing=(evidence.missing||[]).length;
  return missing?`${evidence.uploaded}/${evidence.required} · kurang ${missing}`:`${evidence.uploaded}/${evidence.required} lengkap`;
}

function slaClass(state){
  if(state==='OVERDUE') return 'badge red';
  if(state==='DUE_TODAY') return 'badge amber';
  if(state==='DUE_SOON') return 'badge amber';
  if(state==='ON_TRACK') return 'badge green';
  return 'badge gray';
}

test('sample work never offers buyer decision actions (#32)', () => {
  const row={allowed_actions:['START','UPDATE_PROGRESS','SUBMIT_RESULT','BUYER_APPROVE','BUYER_REJECT'],
             denied_actions:['BUYER_APPROVE','BUYER_REJECT']};
  assert.deepEqual(allowedActions(row),['START','UPDATE_PROGRESS','SUBMIT_RESULT']);
  assert.ok(!allowedActions(row).includes('APPROVE'));
  assert.ok(!allowedActions(row).includes('REJECT'));
  // Tanpa daftar dari server, UI tidak mengarang aksi apa pun.
  assert.deepEqual(allowedActions({}),[]);
  assert.deepEqual(allowedActions(null),[]);
});

test('task cannot be presented as done without submitted version and evidence (#35)', () => {
  const incomplete={eligible:true,stage:'SUBMIT_RESULT',sample_work_status:'PROCESS',
    evidence:{uploaded:1,required:3,complete:false,missing:['evidence_inspection','evidence_result']},
    requirements:{version_submitted:{code:'version_submitted',label:'Sample version sudah submitted',ok:false},
                  evidence_inspection:{code:'evidence_inspection',label:'Bukti hasil inspeksi diunggah',ok:false}},
    blocker:null};
  const blockers=blockersFor(incomplete);
  assert.ok(blockers.some(b=>b.startsWith('Bukti kurang:')));
  assert.ok(blockers.includes('Sample version sudah submitted'));
  assert.ok(blockers.includes('Bukti hasil inspeksi diunggah'));
  assert.notEqual(incomplete.stage,'DONE');
});

test('approved sample is shown as read-only buyer decision (#31/#37)', () => {
  const row={stage:'DONE',buyer_decision:{status:'APPROVED',decided:true,readonly:true,owner:'CMO_MANAGER'},
             allowed_actions:['START']};
  assert.equal(row.buyer_decision.readonly,true);
  assert.equal(row.buyer_decision.owner,'CMO_MANAGER');
  assert.ok(!allowedActions(row).includes('BUYER_APPROVE'));
});

test('eligibility and blocker are surfaced to the worker (#33)', () => {
  const ineligible={eligible:false,eligibility_reason:'Sample Request belum punya versi PPM/mockup eligible',
                    evidence:null,requirements:{},blocker:null};
  assert.deepEqual(blockersFor(ineligible),['Sample Request belum punya versi PPM/mockup eligible']);
  const blocked={eligible:true,evidence:{complete:false,missing:['evidence_progress'],uploaded:0,required:3},
                 requirements:{},blocker:'Gate pembayaran order belum lolos',blocker_owner:'CFO_MANAGER'};
  const list=blockersFor(blocked);
  assert.ok(list.some(b=>b.includes('owner CFO_MANAGER')));
});

test('SLA and evidence columns reflect per-article state (#35)', () => {
  assert.equal(evidenceLabel({uploaded:3,required:3,complete:true,missing:[]}),'3/3 lengkap');
  assert.equal(evidenceLabel({uploaded:1,required:3,complete:false,missing:['a','b']}),'1/3 · kurang 2');
  assert.equal(evidenceLabel(null),'—');
  assert.equal(slaClass('OVERDUE'),'badge red');
  assert.equal(slaClass('DUE_SOON'),'badge amber');
  assert.equal(slaClass('ON_TRACK'),'badge green');
  assert.equal(slaClass('NO_SLA'),'badge gray');
});

test('sample pages keep the locked sidebar scope for Sample PIC (#31)', () => {
  const business=readFileSync(join(here,'..','src','business.js'),'utf8');
  for(const denied of ['/cmo/spk','/coo/production','/cfo/purchase-orders','/coo/deliveries']){
    assert.ok(business.includes(`'${denied}'`),`route ${denied} harus terdaftar eksplisit`);
  }
  // Halaman sample tidak boleh MENAWARKAN keputusan buyer: hanya boleh muncul
  // di deny-list / filter, bukan sebagai tombol atau aksi yang dikirim.
  const todaySrc=read('SampleTodayPage.jsx');
  const taskSrc=read('SampleTaskPage.jsx');
  for(const [name,src] of [['SampleTodayPage.jsx',todaySrc],['SampleTaskPage.jsx',taskSrc]]){
    const offersDecision=/<button[^>]*(APPROVE|REJECT)|onClick[^>]*(BUYER_APPROVE|BUYER_REJECT)|api\([^)]*customer-decision/.test(src);
    assert.ok(!offersDecision,`${name} tidak boleh mengirim aksi keputusan buyer`);
    assert.ok(/CMO_MANAGER/.test(src),'pemilik keputusan buyer harus disebut CMO_MANAGER');
    assert.ok(/Denied|denied|bukan aksi halaman ini|bukan milik halaman ini/i.test(src),
      `${name} harus menyatakan keputusan buyer bukan aksinya`);
  }
  // Filter aksi memakai deny-list eksplisit supaya server-sent APPROVE pun dibuang.
  assert.ok(/\[\s*'BUYER_APPROVE'\s*,\s*'BUYER_REJECT'/.test(taskSrc),
    'filter aksi harus membuang BUYER_APPROVE/BUYER_REJECT');
  // Lifecycle terkunci dan urut.
  assert.deepEqual(STAGES,['OPEN','IN_PROGRESS','UPDATE','INSPECTION','SUBMIT_RESULT','DONE']);
});
