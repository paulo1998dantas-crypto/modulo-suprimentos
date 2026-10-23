# Destinos dos materiais da O.S.

## Preparação

O destino sugerido é PREPARAÇÃO para todo cadastro do grupo PP (grupo estrutural
20, Produto Processo/Produto em Processo ou PP) e para descrições com a palavra
PP. A regra vale para cadastros atuais e futuros, sem uma lista fixa de SKUs.
Também se aplica a CJ MÓVEL/CJ MÓVEIS, MP PASSADEIRA, MP CHAPA DE COMPENSADO e
MP CHAPA DE COMPENSADO RETALHO. As regras anteriores para piso, trilho, reforço,
isolamento, acabamento, teto e bancos continuam válidas.

O pacote de um pai de preparação acompanha seu destino em todos os níveis da
composição salva, mesmo que os componentes não tenham essas palavras-chave.
A filtragem da via de preparação usa o destino resolvido, sem eliminar novamente
matérias-primas, itens indiretos ou componentes dos conjuntos de bancos.
Não reexpande nem substitui a composição editada pela engenharia vigente.

Uma escolha manual da linha prevalece sobre a sugestão. Uma alteração manual
para Preparação/Expedição em um pai acompanha seus descendentes, exceto linhas
com escolha manual própria. Faturamento direto mantém seu fluxo independente.
As mesmas regras são usadas na tela e no processamento do formulário.

Quando a mesma peça aparece em mais de uma árvore, a quantidade continua
consolidada por SKU, sem nova soma. O metadado `pais_origem` conserva os vínculos
das árvores que foram consolidadas. Se alguma origem é de preparação, a linha
consolidada acompanha preparação, salvo escolha manual explícita.

## Nulo

NULO é um destino de visibilidade documental, não cancelamento de necessidade
nem inativação do cadastro. Defaults iniciais: 10240301, 10240299 e 10320035.
Também pode ser selecionado manualmente na abertura/edição da O.S.

A linha continua na composição persistida, com SKU, unidade, quantidade,
vínculos e identificador da linha. Continua disponível para a demanda, cockpit
e relatórios; a planilha de requisição de materiais do pacote inclui a linha
com destino NULO. Não aparece nos DOCX, nem na composição impressa da O.S.
completa, nem nas vias de preparação/expedição/faturamento direto.
Selecionar NULO em uma linha de F.D. também impede gerar uma via para ela.

Nenhuma O.S. histórica é alterada em lote. A nova classificação é aplicada na
abertura, no salvamento/na emissão solicitada ou na atualização explícita da BOM.
Sem migração, atualização de cadastros ou movimentação automática de estoque.

## Verificação

- Casos compartilhados entre Python e JavaScript em `tests/fixtures/os_destinos.json`.
- Grupo PP sem prefixo na descrição, futuros códigos, acentos e subníveis.
- Pais ausentes da lista, composição fora de ordem, ciclos e peças compartilhadas.
- Destinos manuais e persistência no formulário JSON, legado e snapshot.
- Emissão real em teste isolado: DOCX sem NULOs e planilha com NULOs/quantidades.
- Demais testes de O.S., importação, revisão, equivalência e diário preservados.
