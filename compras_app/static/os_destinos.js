(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.osDestinos = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const validos = new Set(['EXPEDICAO', 'PREPARACAO', 'F.D', 'NULO']);
  const nulos = new Set(['10240301', '10240299', '10320035', '10240131', '30240102', '30240032']);
  const texto = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .toUpperCase().replace(/_/g, ' ').trim().replace(/\s+/g, ' ');
  const codigo = value => String(value || '').split(' - ', 1)[0].trim();
  const manual = line => line.setor_manual === true || ['1', 'true', 'sim'].includes(String(line.setor_manual).toLowerCase().trim());
  function info(line, catalogo) {
    const result = {...((catalogo || {})[codigo(line.codigo)] || {})};
    Object.entries(line).forEach(([key, value]) => { if (value !== '' && value != null) result[key] = value; });
    result.codigo = codigo(line.codigo);
    return result;
  }
  function classificar(line, catalogo) {
    const item = info(line || {}, catalogo);
    const cod = item.codigo, grupo = texto(item.grupo), categoria = texto(item.categoria);
    const descricao = texto(item.descricao || item.nome), referencia = `${categoria} ${grupo} ${descricao}`;
    if (nulos.has(cod)) return 'NULO';
    if (cod.startsWith('20') || /^20\b/.test(grupo) || /\bPP\b|\bPRODUTO(?: EM)? PROCESSO\b/.test(grupo)
        || /\bPP\b/.test(descricao) || /\bCJ MOVE(?:L|IS)\b/.test(descricao)
        || /^MP (?:PASSADEIRA\b|CHAPA (?:DE )?COMPENSADO\b)/.test(descricao)) return 'PREPARACAO';
    if ([descricao, categoria, grupo, item.tipo_requisicao, item.setor].some(value => {
      const tokens = texto(value).match(/[A-Z0-9]+/g) || [];
      return tokens.some((token, i) => token === 'FD' || token === 'F' && tokens[i + 1] === 'D'
        || token === 'FATURAMENTO' && tokens[i + 1] === 'DIRETO');
    })) return 'F.D';
    const ppOuCj = ['20', '30'].includes(cod.slice(0, 2)) || /CONJUNTO|KIT|PRODUTO EM PROCESSO/.test(grupo);
    if (descricao.startsWith('CJ TETO') && ppOuCj) return 'PREPARACAO';
    if (/TRILHO|REFORCO|ISOLAMENTO/.test(referencia)) return 'PREPARACAO';
    if (descricao.includes('ACESSORIO ACABAMENTO PLASTICO')) return 'EXPEDICAO';
    if (['20', '30'].includes(cod.slice(0, 2)) && /PISO|ACABAMENTO/.test(categoria)) return 'PREPARACAO';
    if (cod.startsWith('3020') && referencia.includes('BANCO')) return 'PREPARACAO';
    return 'EXPEDICAO';
  }
  function propagar(rows, catalogo) {
    const result = (rows || []).map(line => ({...line}));
    const porCodigo = new Map(result.map(line => [codigo(line.codigo), line]));
    const cache = new Map();
    function resolver(cod, visitados, atual) {
      const original = atual || porCodigo.get(cod);
      const chave = original || cod;
      if (cache.has(chave)) return cache.get(chave);
      const line = original || {codigo: cod};
      const automatico = classificar(line, catalogo);
      if (manual(line) && validos.has(line.setor)) return [line.setor, true];
      if (visitados.has(cod) || ['NULO', 'F.D'].includes(automatico)) return [automatico, false];
      const proximos = new Set([...visitados, cod]);
      const pais = [line.item, ...(Array.isArray(line.pais_origem) ? line.pais_origem : [])]
        .map(codigo).filter(pai => pai && pai !== cod).map(pai => resolver(pai, proximos));
      const manuais = pais.filter(([destino, editado]) => editado && ['PREPARACAO', 'EXPEDICAO'].includes(destino));
      const resolved = manuais.length
        ? [manuais.some(([destino]) => destino === 'PREPARACAO') ? 'PREPARACAO' : 'EXPEDICAO', true]
        : [automatico === 'PREPARACAO' || pais.some(([destino]) => destino === 'PREPARACAO') ? 'PREPARACAO' : 'EXPEDICAO', false];
      cache.set(chave, resolved);
      return resolved;
    }
    result.forEach(line => {
      line.setor = resolver(codigo(line.codigo), new Set(), line)[0];
      line.setor_origem = line.setor;
      line.tipo_requisicao = line.setor === 'F.D' ? 'FATURAMENTO DIRETO' : 'MATERIAL';
    });
    return result;
  }
  return {classificar, propagar};
});
