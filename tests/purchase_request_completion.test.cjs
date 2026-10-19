const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../compras_app/static/purchase_requests.js'), 'utf8');
function section(start, end) { return source.slice(source.indexOf(start), source.indexOf(end)); }
class Element {
  constructor(tag, text) { this.tag = tag; this.textContent = text; this.children = []; this.dataset = {}; this.classList = {add() {}}; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
}
const row = (overrides = {}) => ({id:'abcd1234-1234-1234-1234-123456789abc', sku_codigo:'10260092', descricao:'Material', quantity:2, unidade:'PC', status:'SOLICITADA', request_type:'COMPRA_NOVA', version:7, ...overrides});
function context() {
  const elements = new Map();
  const calls = [];
  const ctx = vm.createContext({cfg:{can_manage:true}, completingRow:null, allocatingOrderRow:null,
    $:id => { if (!elements.has(id)) elements.set(id, new Element('div')); return elements.get(id); },
    node:(tag,text) => new Element(tag,text), button:(text,fn) => Object.assign(new Element('button',text),{onclick:fn}),
    qty:String, date:String, today:()=>'2026-10-19', page:1, total:1, rows:[], labels:{},
    openOrderAllocation:r=>calls.push(['order',r]), openAnticipationConfirmation:r=>calls.push(['date',r]),
    showDetails(){}, showHistory(){}, openEdit(){}, excludeRequest(){}, act(){},
    encodeURIComponent, message:(...args)=>calls.push(['message',...args]), load:async()=>calls.push(['reload']),
    api:async(...args)=>{calls.push(['api',...args]); return {items:[]};}, calls});
  vm.runInContext(section('function openCompletion(row)', 'async function openOrderAllocation(row)'), ctx);
  return ctx;
}
function buttons(element) { return element.children.flatMap(child => [child, ...buttons(child)]).filter(child=>child.tag==='button'); }
test('Concluir fica visível para comprador em ambas as classificações e estados pendentes', () => {
  for (const status of ['SOLICITADA','EM_COMPRAS']) for (const request_type of ['COMPRA_NOVA','ANTECIPACAO']) {
    const ctx = context(); ctx.rows = [row({status,request_type})];
    vm.runInContext(section('function render(){', 'async function load(){'),ctx);
    ctx.render();
    const complete = buttons(ctx.$('pr-rows')).find(b=>b.textContent==='Concluir');
    assert.ok(complete, JSON.stringify(ctx.$('pr-rows'))); complete.onclick();
    assert.equal(ctx.completingRow.id,ctx.rows[0].id);
    assert.equal(ctx.$('pr-complete-dialog').open,true);
    assert.equal(ctx.calls.length,0); // Abrir não muda status nem grava dados.
  }
});
test('não há conclusão para não compradores nem para linhas concluídas ou canceladas', () => {
  for (const [can_manage,status] of [[false,'SOLICITADA'],[true,'CONCLUIDA'],[true,'CANCELADA']]) {
    const ctx = context(); ctx.cfg.can_manage=can_manage; ctx.rows=[row({status})];
    vm.runInContext(section('function render(){', 'async function load(){'),ctx);
    ctx.render();
    assert.equal(buttons(ctx.$('pr-rows')).some(b=>b.textContent==='Concluir'),false);
    ctx.openCompletion(ctx.rows[0]); assert.equal(ctx.completingRow,null);
  }
});
test('conclusão por pedido usa o fluxo existente com a linha e versão originais', () => {
  const ctx=context(), selected=row(); ctx.openCompletion(selected); ctx.chooseCompletion('order');
  assert.equal(ctx.$('pr-complete-dialog').open,false);
  assert.equal(ctx.completingRow,null);
  assert.equal(ctx.calls[0][0],'order'); assert.equal(ctx.calls[0][1],selected);
});
test('data negociada só está disponível para antecipação em compras', () => {
  for (const status of ['SOLICITADA','EM_COMPRAS']) for (const request_type of ['COMPRA_NOVA','ANTECIPACAO']) {
    const ctx=context(), selected=row({status,request_type}); ctx.openCompletion(selected);
    const allowed=status==='EM_COMPRAS'&&request_type==='ANTECIPACAO';
    assert.equal(ctx.$('pr-complete-date').hidden,!allowed);
    ctx.chooseCompletion('date'); assert.equal(ctx.calls.length,allowed?1:0);
    if(allowed) assert.equal(ctx.calls[0][0],'date');
  }
});
test('cancelar ou usar Escape não registra conclusão', () => {
  const ctx=context(); ctx.openCompletion(row());
  const cancel=source.match(/\$\("pr-complete-cancel"\)\.onclick=\(\)=>\{([^}]+)\};/)[1];
  vm.runInContext(cancel,ctx);
  assert.equal(ctx.completingRow,null); assert.equal(ctx.calls.length,0);
  assert.match(source,/pr-complete-dialog"\)\.addEventListener\("cancel",\(\)=>\{completingRow=null;\}\)/);
});
test('alocar e concluir exige pedido e motivo, enviando versão para auditoria e concorrência', async () => {
  const ctx=context(); ctx.allocatingOrderRow=row();
  vm.runInContext(section('async function allocateExistingOrder(){','async function act(row,action){'),ctx);
  ctx.$('pr-allocate-order').value=''; ctx.$('pr-allocate-reason').value='';
  await ctx.allocateExistingOrder(); assert.equal(ctx.calls.some(c=>c[0]==='api'),false);
  ctx.$('pr-allocate-order').value='oc-123'; ctx.$('pr-allocate-reason').value='Pedido atende';
  await ctx.allocateExistingOrder(); const call=ctx.calls.find(c=>c[0]==='api');
  assert.equal(call[1],'/'+row().id+'/action');
  assert.deepEqual(JSON.parse(JSON.stringify(call[2])),{action:'ALOCAR_PEDIDO',version:7,purchase_order_id:'oc-123',reason:'Pedido atende'});
  assert.equal(ctx.calls.some(c=>c[0]==='reload'),true);
});
test('erro de validação do pedido não fecha a confirmação nem informa sucesso', async () => {
  const ctx=context(); ctx.allocatingOrderRow=row(); ctx.api=async()=>{throw Error('Pedido sem saldo');};
  vm.runInContext(section('async function allocateExistingOrder(){','async function act(row,action){'),ctx);
  ctx.$('pr-allocate-order').value='oc-123'; ctx.$('pr-allocate-reason').value='Pedido atende';
  ctx.$('pr-allocate-dialog').showModal(); await ctx.allocateExistingOrder();
  assert.equal(ctx.$('pr-allocate-dialog').open,true);
  assert.equal(ctx.allocatingOrderRow.id,row().id);
  assert.equal(ctx.calls.some(c=>c[0]==='reload'),false);
  assert.deepEqual(ctx.calls[0],['message','Pedido sem saldo',true]);
});
