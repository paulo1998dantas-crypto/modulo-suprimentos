const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../compras_app/templates/erp_gestao_os.html'), 'utf8');
const payloadSource = html.split('\n').find(line => line.startsWith('function workPayload(){'));

function payloadFor(proposal, edit) {
  const entries = [['proposta_numero', proposal], ['entry_id', 'entry-1'],
    ['work_order_id', edit ? 'work-1' : ''], ['codigo_banco', 'N/A'],
    ['tipo_servico', 'TRANSFORMAÇÃO'], ['entry_chassi', 'VIN-UNCHANGED']];
  const context = vm.createContext({
    FormData: class { entries() { return entries[Symbol.iterator](); } },
    form: {},
    syncBankFields() {},
    document: { getElementById(id) {
      assert.equal(id, 'transformation-select', 'saving must not access any commercial selector');
      return {value: '40340028'};
    } },
    state: {bankOriginal: {code: 'N/A', description: 'N/A'}, selectedBanks: [], creatingRevision: false},
    transformationDescription: () => 'TRANSFORMAÇÃO TESTE',
    norm: value => String(value).trim().toUpperCase(),
  });
  vm.runInContext(payloadSource, context);
  return JSON.parse(JSON.stringify(context.workPayload()));
}

test('abertura e edição preservam proposta livre e revisões sem acessar o Comercial', () => {
  for (const edit of [false, true]) {
    const result = payloadFor('LEGADO-10060.2 > COMPL-77', edit);
    assert.equal(result.proposta_numero, 'LEGADO-10060.2 > COMPL-77');
    assert.equal(result.transformacao_codigo, '40340028');
    assert.equal(result.codigo_banco, 'N/A');
    for (const key of ['commercial_program_id', 'commercial_program_version', 'work_order_id', 'entry_id', 'entry_chassi']) {
      assert.equal(key in result, false, key);
    }
  }
});

test('campo opcional permite referência vazia sem criar vínculo', () => {
  assert.equal(payloadFor('', false).proposta_numero, null);
});

test('tela mostra campo editável e não carrega propostas automaticamente', () => {
  const input = html.match(/<input\s+name="proposta_numero"[^>]*>/)[0];
  assert.match(input, /type="text"/);
  assert.match(input, /maxlength="80"/);
  assert.doesNotMatch(input, /readonly|disabled/);
  assert.doesNotMatch(html, /allocation-proposal-select|loadAllocationProposals|proposalSelectionPayload/);
});
