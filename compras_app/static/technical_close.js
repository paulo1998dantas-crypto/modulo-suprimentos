(() => {
  const requests = new Map();
  const number = value => new Intl.NumberFormat('pt-BR', {maximumFractionDigits: 3}).format(Number(value));

  async function submit(url, payload) {
    let command = {...payload};
    while (true) {
      const response = await fetch(url, {
        method: 'POST', headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
        body: JSON.stringify(command)
      });
      const result = await response.json().catch(() => ({}));
      if (response.status === 409 && result.code === 'CONFIRM_NEGATIVE_STOCK') {
        const rows = (result.negative_stock || []).map(row =>
          `${row.codigo}: saldo ${number(row.saldo_atual)} − baixa ${number(row.quantidade_baixar)} = ${number(row.saldo_final)}`
        );
        if (!rows.length || !result.confirmation_token) throw new Error('Não foi possível conferir os saldos. Atualize e tente novamente.');
        if (!window.confirm(`Os seguintes itens ficarão com saldo físico NEGATIVO:\n\n${rows.join('\n')}\n\nConfirma as baixas e a conclusão técnica da O.S.?`)) return null;
        command = {...payload, confirm_negative_stock: true, confirmation_token: result.confirmation_token};
        continue;
      }
      if (!response.ok || result.ok !== true) throw new Error(result.error || result.erro || `Falha na operação (${response.status}).`);
      return result;
    }
  }

  window.concluirOSComMateriais = (url, payload) => {
    if (!requests.has(url)) requests.set(url, submit(url, payload).finally(() => requests.delete(url)));
    return requests.get(url);
  };
})();
