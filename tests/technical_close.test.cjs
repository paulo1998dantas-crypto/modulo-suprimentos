const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../compras_app/static/technical_close.js'), 'utf8');
const conflict = token => ({status:409, ok:false, json:async () => ({code:'CONFIRM_NEGATIVE_STOCK', confirmation_token:token,
  negative_stock:[{codigo:'MP', saldo_atual:'1', quantidade_baixar:'4', saldo_final:'-3'}]})});
const success = {status:200, ok:true, json:async () => ({ok:true})};
function setup(responses, confirmations) {
  const calls = [], prompts = [];
  const context = vm.createContext({Intl, Map, window:{confirm:message => {prompts.push(message); return confirmations.shift();}},
    fetch:async (url, options) => {calls.push(JSON.parse(options.body)); const r=responses.shift(); if(r instanceof Error)throw r; return r;}});
  vm.runInContext(source, context);
  return {close:context.window.concluirOSComMateriais, calls, prompts};
}
test('cancelar negativo não envia comando confirmado', async () => {
  const s=setup([conflict('one')],[false]);
  assert.equal(await s.close('/close',{}),null);
  assert.equal(s.calls.length,1);
});
test('confirmação envia token exato e flag booleana', async () => {
  const s=setup([conflict('one'),success],[true]);
  await s.close('/close',{motivo:'test'});
  assert.deepEqual(s.calls[1],{motivo:'test',confirm_negative_stock:true,confirmation_token:'one'});
});
test('saldo alterado pede nova confirmação', async () => {
  const s=setup([conflict('one'),conflict('two')],[true,false]);
  assert.equal(await s.close('/close',{}),null);
  assert.equal(s.calls.length,2); assert.equal(s.prompts.length,2);
});
test('duplo clique compartilha uma única solicitação', async () => {
  const s=setup([success],[]);
  const first=s.close('/close',{}),second=s.close('/close',{});
  assert.equal(first,second); await first; assert.equal(s.calls.length,1);
});
test('erro de rede não gera repetição automática e permite tentar depois', async () => {
  const s=setup([new Error('network'),success],[]);
  await assert.rejects(s.close('/close',{}),/network/);
  assert.equal(s.calls.length,1); await s.close('/close',{}); assert.equal(s.calls.length,2);
});
test('conflito incompleto não solicita nem autoriza baixa', async () => {
  const s=setup([{status:409,ok:false,json:async()=>({code:'CONFIRM_NEGATIVE_STOCK'})}],[]);
  await assert.rejects(s.close('/close',{}),/conferir os saldos/); assert.equal(s.prompts.length,0);
});
