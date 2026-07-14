# modulo-suprimentos

Aplicativo Flask para compras e producao, com emissao de pedidos, O.S., cadastro de itens/fornecedores e composicao B.O.M.

## Render com catalogo Supabase

Configure estas variaveis no Render para o modulo buscar os SKUs direto do ModuloCadastro:

- `SUPRIMENTOS_CATALOG_MODE=supabase`
- `SUPABASE_URL=https://rodtxswtqbsbtukmvobn.supabase.co`
- `SUPABASE_SERVICE_ROLE_KEY=<service role key do projeto>`

Com isso, os produtos deixam de depender do arquivo local de SKUs. O ModuloCadastro continua sendo o ponto de criacao/edicao dos itens, e o ModuloSuprimentos apenas consome a tabela `cadastro_registros`.
