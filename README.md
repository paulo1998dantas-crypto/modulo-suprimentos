# modulo-suprimentos

Aplicativo Flask para compras e producao, com emissao de pedidos, O.S., cadastro de itens/fornecedores e composicao B.O.M.

## Render com catalogo Supabase

Configure estas variaveis no Render para o modulo buscar os SKUs direto do ModuloCadastro:

- `SUPRIMENTOS_CATALOG_MODE=supabase`
- `SUPABASE_URL=https://rodtxswtqbsbtukmvobn.supabase.co`
- `SUPABASE_SERVICE_ROLE_KEY=<service role key do projeto>`

Com isso, os produtos deixam de depender do arquivo local de SKUs. O ModuloCadastro continua sendo o ponto de criacao/edicao dos itens, e o ModuloSuprimentos apenas consome a tabela `cadastro_registros`.

## Gestao de documentos

O modulo permite salvar O.C. e O.S. sem gerar arquivos, editar registros existentes, emitir/reemitir, concluir tecnicamente, cancelar, excluir e exportar relatorios detalhados em Excel. Rascunhos do navegador e importacoes temporarias sao isolados pelo login; o dashboard e a base emitida continuam compartilhados.

Em uma base de producao que ja possui documentos, execute somente `supabase_suprimentos_gestao_documentos_additive.sql` no SQL Editor. Essa atualizacao incremental preserva os registros existentes e apenas adiciona status, auditoria, idempotencia contra duplo envio e numeracao atomica de O.C./O.S. O arquivo `supabase_suprimentos_migration.sql` continua sendo a migracao-base para instalacoes novas e nao deve ser reaplicado na producao existente. Depois publique o codigo no Render. O aplicativo falha de forma explicita se a numeracao atomica ainda nao estiver instalada, evitando gravacoes duplicadas silenciosas.
