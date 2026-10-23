const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const destinos = require('../compras_app/static/os_destinos.js');
const casos = require('./fixtures/os_destinos.json');
for (const caso of casos) test(caso.nome, () => {
  const original = JSON.stringify(caso);
  const result = destinos.propagar(caso.linhas, caso.catalogo || {});
  assert.deepEqual(result.map(line => line.setor), caso.destinos);
  assert.equal(JSON.stringify(caso), original, 'não altera catálogo, quantidades ou entrada');
  assert.deepEqual(destinos.propagar(result, caso.catalogo || {}).map(line => line.setor), caso.destinos, 'idempotente');
});
test('interface disponibiliza NULO e recalcula herança após escolha manual', () => {
  const html = fs.readFileSync(path.join(__dirname, '../compras_app/templates/index.html'), 'utf8');
  assert.match(html, /src="\/static\/os_destinos.js/);
  assert.match(html, /<option value="NULO"/);
  assert.match(html, /row.dataset.paisOrigem = JSON.stringify/);
  assert.match(html, /renderComposicaoRows\(coletarComposicaoTabela\(\)\)/);
  assert.match(html, /item: filho.item \|\| codigo/);
});
test('scripts da página continuam sintaticamente válidos', () => {
  const html = fs.readFileSync(path.join(__dirname, '../compras_app/templates/index.html'), 'utf8');
  for (const [, source] of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) {
    const js = source.replace(/{{[\s\S]*?}}/g, '{}').replace(/{%[\s\S]*?%}/g, '');
    assert.doesNotThrow(() => new vm.Script(js));
  }
});
