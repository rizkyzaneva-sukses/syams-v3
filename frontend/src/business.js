export const groups={cmo:['CMO_MANAGER','CMO_SUPPORT'],cfo:['CFO_MANAGER','FINANCE_SUPPORT'],coo:['COO_MANAGER','PRODUCTION_PIC','PRINTING_PIC','SHIPMENT_ADMIN'],hr:['CHRO_MANAGER','HR_SUPPORT']};
const routeRoles={
  '/master':['CEO',...groups.cmo,...groups.cfo,...groups.coo,'SAMPLE_PIC'],
  '/cmo':groups.cmo,'/cmo/priority':[...groups.cmo,'CEO'],'/cmo/orders':groups.cmo,'/cmo/orders/new':groups.cmo,'/cmo/po-inbox':['CMO_MANAGER','CMO_SUPPORT','CEO'],'/cmo/customers':groups.cmo,
  '/cmo/quotations':[...groups.cmo,'CFO_MANAGER','CEO'],'/cmo/samples':[...groups.cmo,'SAMPLE_PIC'],'/cmo/spk':groups.cmo,
  '/cfo':[...groups.cfo,'CEO'],'/cfo/invoices':[...groups.cfo,'CEO'],'/cfo/purchase-orders':[...groups.cfo,'CEO'],'/cfo/shipments':[...groups.cfo,'COO_MANAGER','SHIPMENT_ADMIN','CMO_MANAGER','CEO'],
  '/coo':groups.coo,'/coo/material-requests':['COO_MANAGER','PRODUCTION_PIC'],'/coo/bom-cost':['CEO','COO_MANAGER','PRODUCTION_PIC','CFO_MANAGER'],'/coo/production':groups.coo,'/coo/wip':groups.coo,
  '/coo/qc':['COO_MANAGER','PRODUCTION_PIC'],'/coo/planning':['COO_MANAGER'],'/coo/deliveries':['CMO_MANAGER',...groups.cfo,'COO_MANAGER','SHIPMENT_ADMIN','CEO'],
  '/coo/closing':['CMO_MANAGER','CFO_MANAGER','COO_MANAGER','CEO'], '/chro':groups.hr,'/chro/employees':groups.hr,'/chro/training':groups.hr,
  '/chro/performance':['CHRO_MANAGER'],'/chro/issues':['CHRO_MANAGER'],'/ceo':['CEO'],'/ceo/decisions':['CEO'],'/ceo/business-policy':['CEO'],'/audit-log':['CEO'],
};
export function canAccess(role,path){if(!role)return false;if(path.startsWith('/orders/'))return !['CHRO_MANAGER','HR_SUPPORT'].includes(role);if(path.startsWith('/cmo/po-inbox'))return ['CMO_MANAGER','CMO_SUPPORT','CEO'].includes(role);return !(path in routeRoles)||routeRoles[path].includes(role);}
export function nullableNumber(value){return value==null||value===''?null:Number(value);}
export function normalizeDates(value){
  if(Array.isArray(value)) return value.map(normalizeDates);
  if(value&&typeof value==='object') return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,v===''&&(/_date$/.test(k)||['valid_until','buyer_deadline','projected_shipment'].includes(k))?null:normalizeDates(v)]));
  return value;
}
export function statusTone(value){
  if(['PAID','READY','ACTIVE','CLEAR','APPROVED','ON_TRACK','CLOSED','CONFIRMED','DONE','PASS'].includes(value)) return 'green';
  if(['PARTIAL','PENDING','PREPARING','AT_RISK'].includes(value)) return 'amber';
  if(['UNPAID','DELAYED','HOLD','REJECTED','LATE_RISK','FAIL'].includes(value)) return 'red';
  return 'gray';
}
export function matchesSearch(record,query,fields){const term=query.trim().toLowerCase();return !term||fields.some(field=>String(record[field]??'').toLowerCase().includes(term));}
export function movementWip(m){return Number(m.qty_in||0)-Number(m.qty_done||0)-Number(m.qty_reject||0);}
export function orderWip(orders,movements){
  const articleOrders=new Map(orders.flatMap(o=>(o.articles||[]).map(a=>[a.id,o]))),byOrder=new Map();
  for(const m of movements){const order=articleOrders.get(m.article_id)||orders.find(o=>o.id===m.order_fk);if(!order)continue;
    if(!byOrder.has(order.id))byOrder.set(order.id,{order_id:order.order_id,buyer:order.buyer,totalWIP:0,processes:[]});
    const row=byOrder.get(order.id),qty=movementWip(m);let process=row.processes.find(p=>p.process===m.process);
    if(!process){process={process:m.process,wip:0,status:'DONE'};row.processes.push(process);}
    process.wip+=qty;if(m.status!=='DONE')process.status='IN_PROCESS';row.totalWIP+=qty;
  }return [...byOrder.values()];
}
export function flowGates(data){const steps=data?.progress?.steps||[],current=steps.findIndex(s=>s.key===data?.current_step);
  return steps.flatMap((s,i)=>{if(i===current)return [];const validation=data.next_steps?.find(n=>n.step===s.key);return [{step:s.key,label:s.label,role:s.gate,status:i<current?'completed':validation?.can_advance?'ready':'blocked',reason:validation?.reason,canAdvance:validation?.can_advance&&validation?.authorized!==false}];});
}
export function roleOwnsGate(role,gate){const owners={CMO:['CMO_MANAGER'],CFO:['CFO_MANAGER'],COO:['COO_MANAGER'],SAMPLE_PIC:['SAMPLE_PIC','CMO_MANAGER'],PRODUCTION_PIC:['PRODUCTION_PIC','COO_MANAGER'],SHIPMENT_ADMIN:['SHIPMENT_ADMIN','COO_MANAGER']};return String(gate||'').split('+').some(g=>(owners[g]||[g]).includes(role));}
