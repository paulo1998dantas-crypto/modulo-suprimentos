# Checklist por atividade e diário de bordo da O.S.

Alteração restrita à apresentação dos documentos gerados pelo Suprimentos.

- Tabelas de processo: cada atividade possui duas marcações independentes,
  OK e NOK. Responsável, data, hora de início e fim continuam no cabeçalho.
- O.S. completa: página inteira de diário de bordo após o layout, identificada
  com número da O.S. e chassi; 16 linhas para data/hora, setor/operador e anotações.
- Produção e preparação reutilizam o checklist por atividade. Diário não é
  acrescentado às requisições, faturamentos diretos, máscaras ou versões resumidas.
- Os DOCX binários originais permanecem preservados; o gerador aplica a
  formatação durante a emissão, incluindo reemissões. Documentos já emitidos
  não são sobrescritos automaticamente.
- A importação DOCX/PDF é compatível com modelos antigos e com o checklist
  novo; marcações impressas e diário não são importados como atividades ou
  nomes de operadores. Marcação em papel não gera apontamento no MES.

Não exige migração, configuração ou dependência adicional. Não altera cadastros,
composição de materiais, estoque, vínculo comercial ou histórico de produção.

Validações: suíte `test_os*.py`, testes de grade/mesclagens, preservação das
tabelas anteriores, idempotência do diário, todos os modos de geração e
reimportação. Exemplo VJ687280 conferido no Word, sete páginas, com layout na
sexta página e diário inteiro na sétima, sem página em branco adicional.
