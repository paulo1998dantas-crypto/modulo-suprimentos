# HANDOFF DE CONTINUIDADE — ERP JI MONTADORA

Última atualização: **2026-08-03 22:41 BRT (America/Sao_Paulo)**
Responsável pelo registro: Codex
Escopo: integração entre **Cadastro, Suprimentos/Compras/PCP, Estoque, MES/Produção e Portal Operacional**.

> Este documento contém somente nomes de variáveis, IDs públicos de projetos/serviços, URLs e hashes de commits. Não contém senhas, connection strings, tokens, chaves Supabase, service role ou credenciais de usuários.

## 0. Regras invioláveis para a continuidade

1. O Supabase pago `rodtxswtqbsbtukmvobn` é a fonte de verdade da operação atual.
2. Dados gerados localmente, planilhas importadas em testes, SQLite/PostgreSQL Docker e arquivos em `data/` não são fonte de verdade e não podem ser promovidos para produção.
3. Nunca recalcular saldo a partir de O.C., planilhas ou recebimentos históricos. O livro operacional é `movements` e o saldo vigente é `stock_balances`.
4. Não executar `db reset`, `DROP`, `TRUNCATE`, seed, fixture ou carga de demonstração no Supabase de produção.
5. Não repetir o SQL de reconciliação histórica sem uma nova auditoria. O script é fail-closed e a segunda execução deve abortar.
6. Não limpar, restaurar ou incluir em commit os arquivos locais sujos listados na seção 4.6.
7. Toda mutação de estoque precisa ser transacional, auditável e idempotente. Conclusão técnica ou financeira não movimenta saldo.
8. Não usar número visível de O.C., chassi reduzido ou descrição como chave primária. Os vínculos canônicos usam UUID.

## 1. Objetivo geral e arquitetura atual

O objetivo é transformar os módulos operacionais existentes em um ERP industrial integrado para transformação de vans, furgões e vitrês, substituindo gradualmente as planilhas de compras, controle de produção e agenda sem interromper a operação.

Arquitetura vigente:

- serviços separados no Render;
- um PostgreSQL/Supabase compartilhado para Cadastro, Estoque, Suprimentos e MES;
- tabelas legadas preservadas;
- novas entidades ERP adicionadas de forma aditiva em tabelas `erp_*`;
- comunicação entre backends protegida por token interno e identificação do ator;
- autenticação e autorização compartilhadas pelas tabelas de RBAC;
- Portal Operacional mantido como **static site**, sem banco próprio;
- MES legado preservado somente como contingência/histórico, sem upload legado no fluxo atual.

Responsabilidades:

| Módulo | Responsabilidade canônica | Stack |
|---|---|---|
| ModuloCadastro | SKU, descrições, unidades, pessoas, fornecedores, clientes, B.O.M., processos e parâmetros mestres | FastAPI + Supabase REST |
| modulo-suprimentos | emissão e gestão de O.C.; gestão de O.S.; Forecast; OP de modificação; documentos e dashboards | Flask + Supabase REST + APIs internas |
| ModuloEstoque | entrada, inspeção, recebimento, saldo, empenho, baixa, inventário, etiquetas, OP e auditoria | Flask + SQLAlchemy + PostgreSQL/Supabase |
| projeto_final-main | entrada de veículo, ITEM, etapas, apontamentos, programação, WIP, finalização, entrega e histórico | FastAPI + SQLAlchemy + PostgreSQL/Supabase |
| portal-acesso-ji | atalhos visuais para os módulos | site estático no Render |

Fluxos integrados atuais:

1. O.C. emitida em Suprimentos → `erp_purchase_orders/lines` → pendência no Estoque → inspeção → recebimento atômico → movimento único → status refletido em Compras.
2. Entrada de veículo no MES → ITEM sequencial → O.S. aberta/ativada em Suprimentos → etapas MES → apontamentos → WIP → finalização/entrega/histórico.
3. O.S. → composição/B.O.M. → necessidade de materiais → empenhos/baixas vinculados → pendência real exibida em Suprimentos.
4. Forecast firme ou preditivo → múltiplos SKU → explosão de B.O.M. para planejamento → conversão/alocação em O.S. quando o veículo chega.
5. OP de modificação → SKU origem empenhado → transformação → baixa do insumo → entrada única do SKU final.

## 2. Repositórios, branches e commits

Raiz de trabalho:

`C:\Users\PRODUCAO-2.0\OneDrive - J I MONTADORA DE VEICULOS ESPECIAIS LTDA\Documentos\PROJETO FINAL`

A raiz acima possui `.git`, branch `master`, **sem commit e sem remote**. Ela funciona somente como pasta coordenadora. Não tentar publicar tudo como um monorepo.

| Repositório | Branch local atual | HEAD relevante | Estado remoto |
|---|---|---|---|
| `paulo1998dantas-crypto/ModuloEstoque` | `codex/erp-integration-20260729` | `9b32534f54cdefdf6aab62682064ad720ef6b650` | `origin/main` e a branch de integração no mesmo commit |
| `paulo1998dantas-crypto/modulo-suprimentos` | `codex/erp-integration-20260729` | `182ef6c4576c7b2bed5668feef9b217c3143f282` | `origin/main` e a branch de integração no mesmo commit antes deste handoff |
| `paulo1998dantas-crypto/projeto_final-main` | `codex/erp-integration-20260729` | `88c5f4ac3aeea5bb7f8edfbe6f8a1f77cdf0e50b` | código de produção já integrado; worktree limpo |
| `paulo1998dantas-crypto/ModuloCadastro` | `main` | `1cfc72c091e3dc6dfe0da9654adca9d4340fd315` | sincronizado com `origin/main` |
| `paulo1998dantas-crypto/portal-acesso-ji` | `main` | `47c0d99ca682605ac65111f23b051bd70ceb4bde` | sincronizado com `origin/main`; site estático |

Commits funcionais mais importantes desta evolução:

- Estoque: `4c2a6e5`, `952b259`, `2c63535`, `3e4f23e`, `787e88c`, `41d71d7`, `116cd7c`, `ec409d3`, `2731f90`, `9b32534`.
- Suprimentos: `6da2676`, `0db9025`, `bb348eb`, `e0fe0b8`, `01f61fd`, `20652fc`, `7ca7b48`, `818342d`, `1caca1a`, `182ef6c`.
- MES: `2ecb3e4`, `5a9bc40`, `4b13534`, `5e7176e`, `793791b`, `fedf58b`, `c653db5`, `a8f4b3a`, `5f5eebf`, `e1b41d4`, `88c5f4a`.
- Cadastro: `362279a`, `1cfc72c`.
- Portal: `26f1d1a`, `4195044`, `4108bbf`, `47c0d99`.

## 3. Tudo que foi implementado nesta conversa

### 3.1 Compras e recebimento

- modelo relacional de O.C., linhas, recebimentos e vínculos com movimentos;
- UUID interno e idempotência, mantendo número visível apenas como número de negócio;
- O.C. multi-linha, emissão, edição controlada, cancelamento, conclusão técnica e financeira;
- status físico `EMITIDA`, `PARCIALMENTE_RECEBIDA`, `RECEBIDA` e `CANCELADA`, separado das conclusões;
- recebimento parcial, total, aprovado, aprovado condicional e devolvido;
- apenas quantidade `A` aprovada aumenta o disponível; `AC` não vira saldo disponível e `D` não aumenta saldo;
- estorno vinculado ao recebimento e ao movimento original;
- entrada manual permanece, usando o mesmo serviço de movimentação;
- sugestão de O.C. pendente quando uma entrada direta usa SKU com pedido aberto;
- sincronismo de pedidos abertos e ocultação de O.C. tecnicamente concluída;
- correção controlada/auditada do número da O.C.; sequência de compras ajustada;
- recebimento de conjunto com B.O.M. gera entrada nos componentes; sem B.O.M., entra no conjunto;
- relatório consolidado Compras + Inspeção;
- relatório **Trânsito Pendente**, com situação `ATRASADA`, `VENCE HOJE`, `A VENCER` ou `SEM DATA`;
- data de necessidade/remessa por linha da O.C., permitindo várias datas no mesmo pedido;
- documento DOCX de O.C. exibe a remessa de cada linha;
- valores e quantidades formatados corretamente, sem `1.000` quando o valor é uma peça e com duas casas monetárias.

### 3.2 Estoque, empenho, baixa e necessidade da O.S.

- `movements` ganhou origem, UUID de origem/linha, idempotência, contexto, O.S., setor, referência, operação-pai e auditoria;
- correção do erro PostgreSQL `source_id UUID x VARCHAR`;
- empenho vinculado por O.S./ITEM/chassi e consulta dos materiais dentro da O.S.;
- baixa por empenho, cancelamento/estorno e backflush atômicos;
- O.S. terminal ou tecnicamente concluída não aparece como opção de empenho;
- relatório de necessidades por O.S. explode B.O.M., abate empenho/baixa e exclui O.S. terminal;
- conjunto ou produto final empenhado cobre sua necessidade e seus descendentes de B.O.M., sem duplicar componentes;
- nova leitura de saldo compartilhado: empenhos ativos sem O.S. são candidatos de fluxo, mas não reduzem automaticamente várias ordens;
- apropriação explícita do saldo compartilhado para uma O.S. cria **uma única BAIXA real**, exige ADMIN, motivo e chave idempotente;
- relatório de empenhos pendentes ganhou a aba `Necessidades O.S.` e as colunas `SALDO_EM_FLUXO_NAO_APROPRIADO` e `EMPENHOS_EM_FLUXO`;
- baixa direta por `ID_EMPENHO`, correção em massa e apropriação de saldo compartilhado ficaram exclusivas para ADMIN;
- baixa manual operacional normal continua disponível conforme perfil;
- reconciliação histórica reconhece O.S./ITEM, número isolado, chassi completo, últimos 8 e últimos 4 caracteres, sem diferenciar caixa;
- números rotulados como NF, nota, O.C., P.C. ou pedido são ignorados para não criar vínculo falso;
- chassi repetido escolhe a ocorrência com maior ITEM/O.S.;
- horário exibido normalizado para `America/Sao_Paulo`;
- correção do erro de interface `'entry_draft' is undefined`;
- OP de modificação integrada ao empenho e transformação de SKU;
- entrada de item fabricado internamente confirma o consumo real da B.O.M. antes do backflush;
- etiquetas, inventário, relatórios e extrato de movimentações preservados.

### 3.3 Entrada, O.S., Forecast e MES

- veículo físico separado de entrada operacional e O.S.; chassi não é chave da O.S.;
- ITEM sequencial transacional; último marco informado durante o desenvolvimento: 3112, com dados reais posteriormente importados;
- mesmo chassi pode gerar nova entrada, novo ITEM e nova O.S.;
- abertura de O.S. com rascunho, edição, ativação, parâmetros de veículo, transformação, bancos, ar-condicionado, acessórios e data inicial;
- fornecedor do ar, tipo de ar e ar quente separados;
- lista de vendedores, mercado, linha, tipo de veículo e transformações;
- geração parametrizada de etapas e estados `N`, `P`, `S`, `N/A`;
- apontamentos persistem no banco compartilhado e refletem em todas as visões;
- WIP considera pátio + produção; qualquer etapa `P` ou `S` inicia o ciclo e `LIBERAÇÃO=S` encerra o ciclo;
- removido conceito operacional de etapa bloqueada;
- sequenciamento WIP persistente por data de entrega, semana e critérios configuráveis;
- histórico ilimitado de reprogramações;
- estados de transformação, pós-venda e outros preservados na finalização e entrega;
- Gestão de O.S. mostra percentual, materiais, documento, edição e conclusão técnica;
- conclusão técnica canônica remove O.S. de buscas operacionais sem apagar histórico;
- Forecast criado com frente firme `AGUARDANDO CHEGADA` e frente preditiva;
- Forecast multi-SKU explode B.O.M. para MRP, sem criar movimento/reserva;
- registros legados `AG CHEGADA` migrados para Forecast;
- Forecast pode ser selecionado ao alocar/abrir O.S.; dados de chassi podem ser corrigidos na chegada;
- OP de modificação com documento próprio e transformação SKU origem → SKU final;
- exportações MES: controle diário, logs e tempos;
- consulta O.S./Histórico, visão geral, gerencial, completa, resumida e Kanban;
- relatórios usam chassi completo internamente e últimos 8 caracteres nas visões solicitadas;
- importadores idempotentes para compras/produção/agenda, com dry-run e normalização de valores legados;
- carga real do MES importada no banco compartilhado, preservando histórico.

### 3.4 Cadastro, usuários e portal

- Cadastro confirmado como fonte de SKU/B.O.M./pessoas/processos;
- RBAC compartilhado para ADMIN, OPERADOR, COMPRADOR, FINANCEIRO, PCP e ENGENHARIA, com permissões e exceções individuais;
- gestão central de usuários no Estoque;
- autenticação compartilhada no MES e demais backends;
- suporte técnico a ticket curto HMAC do Portal foi implementado, porém o Portal foi deliberadamente devolvido a **static site** no commit `47c0d99`;
- Portal publicado com atalhos para Cadastro, Estoque, Compras, PCP, Controle de Produção e MES;
- instruções operacionais e apresentações por perfil foram geradas em `outputs/`.

## 4. Arquivos criados, alterados ou excluídos

### 4.1 ModuloEstoque — principais grupos

- `estoque_app/app.py`: rotas ERP, recebimentos, O.C., materiais, OP, correção/admin e apropriação compartilhada.
- `estoque_app/auth.py`, `portal_sso.py`: RBAC compartilhado, permissão ADMIN e SSO opcional.
- `estoque_app/models.py`, `database.py`, `config.py`: modelos PostgreSQL/SQLite, tipos UUID, pools e configurações.
- `estoque_app/services/erp_service.py`: transações de O.C./recebimento/auditoria.
- `estoque_app/services/estoque_service.py`: movimento, idempotência, baixa e apropriação do saldo compartilhado.
- `estoque_app/services/commitment_correction_service.py`: resolução histórica por número/chassi e correções auditadas.
- `estoque_app/services/work_order_needs_service.py`: necessidade O.S., B.O.M., cobertura e saldo em fluxo.
- `estoque_app/services/production_order_service.py`: OP de transformação SKU → SKU.
- `estoque_app/services/excel_service.py`, `purchase_report.py`: exportações de empenho, necessidade, compras e inspeção.
- `estoque_app/templates/erp_recebimentos.html`, `commitment_correction.html`, `consumption_import.html`, `movements.html` e demais templates: interfaces operacionais.
- `estoque_app/timezone_utils.py`: conversão de timestamps para São Paulo.
- `estoque_app/legacy_import_compras.py`, `reconcile_erp.py`, validadores: importação/reconciliação controlada.
- `supabase/migrations/*.sql`: estrutura ERP, RLS, RBAC, vínculos, OP, conclusões e permissão ADMIN.
- `supabase/rollbacks/*.sql`: rollback lógico/forward-fix das migrations críticas.
- `tests/test_*.py`: cobertura de recebimento, concorrência, UUID, O.S., OP, RBAC, necessidade, correção e fuso.
- `README.md`, `estoque_app/README.md`, `.env.example`, `render.yaml`: operação e configuração sem segredos.

Último commit `9b32534`: alterou `README.md`, `estoque_app/README.md`, `app.py`, `auth.py`, `commitment_correction_service.py`, `estoque_service.py`, `excel_service.py`, `work_order_needs_service.py`, `consumption_import.html`, `movements.html`, cinco arquivos de teste e criou `202608031200_admin_commitment_reconciliation_permission.sql` e `test_commitment_admin_routes.py`.

### 4.2 modulo-suprimentos — principais grupos

- `compras_app/app.py`: O.C./O.S./Forecast/OP, proxies para Estoque/MES, relatórios e RBAC.
- `compras_app/supabase_data.py`, `supabase_catalog.py`: persistência, catálogo, trânsito de compras, Forecast e leituras ERP.
- `compras_app/gerar_oc.py`, `gerar_op.py`: documentos O.C. com remessa por linha e OP de modificação.
- `compras_app/templates/index.html`: formulário O.C./O.S., importação, data por linha e navegação.
- `erp_ordens_compra.html`: Gestão de Compras e trânsito pendente.
- `erp_gestao_os.html`: Gestão de O.S., materiais, saldo compartilhado e ação ADMIN.
- `erp_forecast.html`, `erp_ordens_producao.html`: Forecast e OP.
- `portal_sso.py`: SSO opcional.
- `supabase_*migration.sql`: vínculos ERP e Forecast.
- `tests/`: documentos, timeout MES, Forecast, OP, trânsito e RBAC.
- `README.md`, `.env.example`, `render.yaml`: documentação/configuração sem segredos.

Último commit `182ef6c`: alterou `app.py`, `gerar_oc.py`, `supabase_data.py`, `erp_gestao_os.html`, `erp_ordens_compra.html`, `index.html`, `test_shared_rbac.py` e criou `test_purchase_transit.py`.

### 4.3 projeto_final-main

- `main.py`, `erp_service.py`, `erp_catalogs.py`: API e interface MES sobre tabelas ERP.
- `erp_report.py`: controle diário, logs e tempos.
- `authz.py`, `portal_sso.py`: identidade e autorização compartilhadas.
- `templates/index.html`, `gestao_os.html`, `sequenciamento.html`, `detalhes.html`, `usuarios.html`: Kanban, histórico, sequência e apontamentos.
- `legacy_import*.py`, `mes_legacy_reconciliation.py`, `executar_reconciliacao_mes_segura.ps1`: carga/dry-run legado.
- `migrations/*.sql`: consulta geral, sequência WIP e alocação de Forecast.
- `test_*.py`, `validate_*.py`: corte, relatórios, sequência, Forecast e RBAC.
- `.env.example`, `.env.local.example`, `.gitignore`, `README.md`: configuração segura.

### 4.4 ModuloCadastro

- `main.py`: RBAC compartilhado e consumo do SSO opcional.
- `portal_sso.py`: validação de ticket curto.
- `test_shared_rbac.py`: permissões.
- `.env.example`, `README.md`, `render.yaml`: configuração sem segredos.

### 4.5 portal-acesso-ji

Arquivos atuais: `index.html`, `styles.css`, `render.yaml`, `README.md`, `design-qa.md` e imagens em `assets/`. O commit `47c0d99` excluiu `app.py`, `requirements.txt`, `.env.example` e templates Flask para preservar o Portal como static site, decisão solicitada pelo usuário.

### 4.6 Alterações locais não commitadas que devem ser preservadas

**Raiz coordenadora:** branch `master`, sem commits/remoto; arquivos `.idea` estão staged e quase todo o workspace está untracked. Não fazer commit geral.

**ModuloEstoque:** oito XLSX rastreados/modificados pelo usuário:

- `estoque_app/dados_exemplo.xlsx`
- `estoque_app/template_baixa_consumo.xlsx`
- `estoque_app/template_bom.xlsx`
- `estoque_app/template_contagem_inventario.xlsx`
- `estoque_app/template_empenhos.xlsx`
- `estoque_app/template_etiquetas_lote.xlsx`
- `estoque_app/template_importacao_skus.xlsx`
- `estoque_app/template_somar_saldo_inventario.xlsx`

**modulo-suprimentos:** `compras_app/.env.local`, `__pycache__/*.pyc`, logs `emissor_documentos.log*`, `data/historico_oc.json` e `data/oc_counter.txt`; `emissor_documentos.log.2` está removido localmente e `.log.3` é novo. São artefatos locais/operacionais, não código concluído.

**portal-acesso-ji:** `__pycache__/` não versionado.

Não houve exclusão deliberada de código produtivo nos últimos commits de Estoque/Suprimentos. A única exclusão local pendente é o log citado.

## 5. Estrutura dos módulos, banco de dados, APIs e integrações

### 5.1 Supabase

- Projeto compartilhado pago: `rodtxswtqbsbtukmvobn`.
- Projeto MES legado: `rfjgwjtykqmriijsqlac`, preservado; o MCP atual não tem permissão para listar migrations nele.
- Entidades mestres: `cadastro_registros`, `cadastro_bom_cabecalhos`, `cadastro_bom_componentes`, pessoas/processos/regras.
- Compras: `erp_purchase_orders`, `erp_purchase_order_lines`, `erp_goods_receipts`, linhas de recebimento e vínculos de movimento.
- Estoque: `skus`, `stock_balances`, `movements`, B.O.M., inventário, etiquetas e OP.
- Produção: `erp_vehicles`, `erp_vehicle_entries`, `erp_work_orders`, históricos, etapas, eventos, programações e importações.
- Planejamento: documentos Suprimentos, Forecast, itens e necessidades.
- Segurança: `users`, `erp_roles`, `erp_permissions`, relacionamentos, overrides e auditoria.

Snapshot somente leitura em 2026-08-03 22:40 BRT:

| Indicador | Valor |
|---|---:|
| `stock_balances` | 2.236 |
| saldo total | 63.568,704 |
| saldos negativos | 0 |
| movimentos | 2.447 |
| O.C. ERP | 74 |
| recebimentos | 7 |
| veículos | 650 |
| entradas de veículo | 683 |
| O.S. | 664 |
| etapas | 7.968 |
| eventos de etapa | 219 |

### 5.2 APIs internas

- Autenticação: `X-ERP-Backend-Token`.
- Identidade: `X-ERP-Actor` e opcionalmente `X-ERP-Actor-ID`.
- Sem token ou token incorreto: HTTP 401.
- Ação sem perfil ADMIN quando exigido: HTTP 403.

Suprimentos → Estoque:

- O.C., sincronização, conclusão/reabertura/correção/financeiro;
- consulta/confirmacão/estorno de recebimentos;
- materiais e necessidades de O.S.;
- OP de modificação;
- apropriação compartilhada: `POST /api/erp/internal/work-orders/<work_order_id>/materials/shared-consumption`.

Suprimentos → MES:

- entradas, O.S., catálogos, ativação, atualização, programação, conclusão e reabertura.

APIs próprias relevantes em Suprimentos:

- `/erp/ordens-compra`, `/api/erp/purchase-orders/*`;
- `/api/erp/purchase-orders/transit`;
- `/erp/relatorios/compras-transito.xlsx`;
- `/erp/gestao-os`, `/api/erp/os-management/*`;
- `/erp/forecast`, `/api/erp/forecasts/*`;
- `/erp/ordens-producao`, `/api/erp/production-orders/*`;
- `/atualizar_bom_os_abertas`, `/healthz`.

## 6. Migrações executadas e pendentes

### 6.1 Confirmadas no histórico do Supabase pago

O MCP retornou as seguintes versões registradas:

`20260729234217 vehicle_full_chassis_promotion`; `20260730001933 validate_vehicle_full_chassis_consistency`; `20260730002330 vehicle_chassis_constraint_hardening`; `20260730002346 erp_foreign_key_indexes`; `20260730002730 mes_auth_compatibility`; `20260730123803 mes_real_production_fields_20260730`; `20260730124210 fix_mes_real_production_field_comments_utf8_20260730`; `20260730141154 reconcile_active_suprimentos_purchase_orders_202607301200`; `20260730165916 shared_rbac_movement_context_20260730`; `20260730165940 harden_stock_backend_tables_20260730`; `20260730170717 reconcile_shared_user_roles_cutover_20260730`; `20260730173138 harden_cross_module_relationships_20260730`; `20260730183623 production_orders_sku_transformation`; `20260730192844 mes_consulta_geral_roles`; `20260730194319 purchase_order_numbering_correction_20260730`; `20260730195851 mes_sequenciamento_persistente`; `20260730200018 mes_sequenciamento_backfill_wip_fix`; `20260730200127 mes_sequenciamento_backfill_wip_underscore_fix`; `20260731134931 forecast_demand_planning`; `20260731142245 add_forecast_multi_sku_bom_requirements`; `20260731144132 canonical_conclusion_status`; `20260731160107 migrate_legacy_ag_chegada_to_forecast`; `20260731161459 enforce_forecast_allocation_links`; `20260804010409 admin_commitment_reconciliation_permission`.

As migrations iniciais de 2026-07-28/29 foram aplicadas pelo SQL Editor e reconciliadas, mas algumas não aparecem com o mesmo nome no histórico MCP. O schema e os health checks confirmam sua presença. Não reaplicá-las cegamente.

### 6.2 Estado atual

- A migration local `ModuloEstoque/supabase/migrations/202608031200_admin_commitment_reconciliation_permission.sql` foi aplicada no Supabase como versão `20260804010409`.
- A funcionalidade de trânsito por linha não exige migration adicional.
- O saldo compartilhado usa estruturas já existentes; a única mudança de autorização necessária já foi aplicada.
- Não há migration pendente para o escopo concluído.
- Pendência futura: auditoria separada de RLS/tabelas legadas e políticas; não ativar políticas novas diretamente em produção sem staging.
- A lista de migrations do MES legado não pôde ser consultada por falta de permissão MCP; não é bloqueio do fluxo atual.

## 7. Variáveis de ambiente necessárias

Nunca registrar valores reais.

Comuns/internas: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `ERP_FEATURE_FLAG`, `ERP_BACKEND_TOKEN`, `ERP_SHARED_RBAC_ENABLED`, `ERP_PORTAL_SSO_ENABLED`, `ERP_PORTAL_URL`, `ERP_PORTAL_SSO_SECRET`.

Estoque: `ESTOQUE_DATABASE_MODE`, `ESTOQUE_DB_SSLMODE`, `ESTOQUE_SECRET_KEY`, `ESTOQUE_ADMIN_USER`, `ESTOQUE_ADMIN_PASSWORD`, `ERP_PO_SUGGESTION_ENABLED`, `ERP_MOVEMENT_CONTEXT_ENABLED`, `ERP_SUPRIMENTOS_URL`, `ERP_RBAC_SCHEMA_CACHE_TTL_SECONDS`, `ESTOQUE_CADASTRO_SYNC_MODE`, `ESTOQUE_CADASTRO_SYNC_INTERVAL_SECONDS`, `ZEBRA_PRINTER_NAME`.

Suprimentos: `SUPRIMENTOS_REQUIRE_LOGIN`, `SUPRIMENTOS_DATA_MODE`, `SUPRIMENTOS_CATALOG_MODE`, `SUPRIMENTOS_SESSION_SECRET`, `SUPRIMENTOS_FORECAST_ENABLED`, `ERP_STOCK_API_URL`, `ERP_STOCK_PUBLIC_URL`, `ERP_MES_API_URL`, `ERP_MES_PUBLIC_URL`, `ERP_MES_API_TIMEOUT_SECONDS`, `SUPRIMENTOS_FILE_LOG`.

MES: `MES_AUTH_MODE`, `MES_USER_MANAGEMENT_URL`, `MES_LEGACY_SCHEMA_AUTO_MIGRATE`, `ERP_MES_LEGACY_UPLOAD_ENABLED`, `MES_BOOTSTRAP_ADMIN_USER`, `MES_BOOTSTRAP_ADMIN_PASSWORD`, `OPEN_BROWSER`. Somente para reconciliação fora do app: `MES_LEGACY_DATABASE_URL` e `ERP_TARGET_DATABASE_URL`.

Cadastro: variáveis atuais `SUPABASE_*`, `CADASTRO_*` e as variáveis opcionais de Portal/RBAC.

## 8. Feature flags e estado

| Flag/comportamento | Produção atual | Evidência/observação |
|---|---|---|
| `ERP_FEATURE_FLAG` Estoque | ativa | integração em uso; health 200 |
| `ERP_FEATURE_FLAG` Suprimentos | ativa | APIs/tabelas ERP habilitadas |
| `ERP_FEATURE_FLAG` MES | ativa | `/healthz`: `erp_feature=true` |
| `ERP_SHARED_RBAC_ENABLED` Estoque | ativa e pronta | `/healthz`: true/true |
| `ERP_SHARED_RBAC_ENABLED` Suprimentos | ativa e pronta | `/healthz`: true/true |
| RBAC Cadastro | ativo e pronto | `/healthz`: true/true |
| `MES_AUTH_MODE` | `shared_users` | `/healthz` |
| `ERP_MES_LEGACY_UPLOAD_ENABLED` | desativada | corte concluído |
| `MES_LEGACY_SCHEMA_AUTO_MIGRATE` | desativada | schema legado não usado |
| `SUPRIMENTOS_FORECAST_ENABLED` | funcional/ativo | Forecast publicado |
| Portal SSO | não confirmar como ativo | Portal permanece static site; exemplos usam padrão desligado |
| sugestão de O.C./contexto de movimento | funcional no fluxo | não exposta individualmente no health; não alterar sem teste |

## 9. Comandos e resultados importantes

- `python -m unittest discover -s tests -v` em ModuloEstoque: **70/70**.
- `python -m unittest discover -s tests -v` em modulo-suprimentos: **101/101**.
- `git ls-remote --heads origin main codex/erp-integration-20260729`: confirmou `9b32534` no Estoque e `182ef6c` em Suprimentos tanto em `main` quanto na branch de integração.
- `GET /healthz`: Estoque, Suprimentos, MES e Cadastro retornaram HTTP 200; Portal retornou HTTP 200.
- Render: deploy Estoque `dep-d9ojtoe417fc73fvndl0` e Suprimentos `dep-d9ojtobbc2fs739iqgbg`, ambos `live`.
- Logs Render filtrados por `type=app` e `level=error` após o deploy: nenhum erro.
- Supabase `list_migrations`: confirmou a migration ADMIN e o histórico listado na seção 6.
- SQL somente leitura de contagens: snapshot da seção 5.1.
- Reconciliação histórica: 1.353 empenhos ativos sem vínculo analisados; 1.083 vinculados; 270 ignorados; 41 duplicidades direcionadas à O.S. mais recente; 1.083 registros de auditoria.
- Reconciliação de saldo: movimentos 2.447 antes/depois; saldo 63.568,704 antes/depois; zero diferença e zero saldo negativo.

Script auditável: `outputs/20260803_reconcile_historical_commitments_PRODUCTION.sql`.

## 10. Testes realizados e pendentes

Aprovados:

- O.C. multi-linha e remessa por linha;
- trânsito pendente, filtros e exportação;
- recebimento parcial/total/A/AC/D, excesso, idempotência, estorno e concorrência;
- movimento UUID e origem;
- conclusão técnica/financeira sem movimento;
- empenho e baixa ligados à O.S.;
- B.O.M., OP e backflush;
- necessidade da O.S., conjunto cobrindo descendentes e saldo compartilhado;
- restrição ADMIN em correção/baixa por ID/apropriação;
- Forecast multi-SKU, conversão/alocação e migração `AG CHEGADA`;
- WIP, sequência, relatórios MES e RBAC;
- health e ausência de erro de deploy.

Ainda precisa de validação humana autenticada em produção:

1. entrar com uma credencial ADMIN vigente;
2. abrir Gestão de Compras e conferir visualmente o painel/exportação de trânsito;
3. criar uma O.C. controlada com duas linhas e duas datas distintas, sem confirmar recebimento se não houver NF real;
4. confirmar que OPERADOR/COMPRADOR não veem nem executam baixa por ID/correção;
5. fazer uma apropriação controlada de saldo compartilhado em uma O.S. real, com motivo e idempotency key, e conferir exatamente uma BAIXA;
6. validar exportações XLSX no Excel real;
7. validar o login atual de cada perfil e suas exceções individuais.

A credencial anteriormente informada `1 / 2410` foi recusada no login de Suprimentos. Não repetir tentativas nem alterar senha sem autorização.

## 11. Erros encontrados e resoluções

| Erro | Resolução |
|---|---|
| `source_id is uuid but expression is varchar` | tipos UUID alinhados entre SQLAlchemy/PostgreSQL e campos de origem |
| `'entry_draft' is undefined` no empenho | contexto do rascunho restaurado e testado |
| MES local sem `DATABASE_URL` | launcher/configuração por ambiente; nenhum segredo no código |
| shell preso ao iniciar Uvicorn | identificado como sessão vinculada ao filho; saúde/porta/logs testados separadamente |
| WIP mostrava somente pátio | classificação passou a considerar pátio + produção e status derivado das etapas |
| etapa A/C e botões não persistiam | mapeamento de status/ações corrigido no backend e nas visões |
| conclusão de O.C./O.S. não refletia | status canônico e conclusão técnica/financeira separados |
| conjunto recebido entrava no SKU pai | explosão inversa de B.O.M.; fallback para pai sem B.O.M. |
| horários divergentes no Estoque | timezone São Paulo centralizado |
| quantidades `1.000` para uma peça | formatação por unidade corrigida |
| timeout parser em migrations | valores de timeout corrigidos e migrations reaplicadas de forma transacional |
| Portal deixou de ser static site ao testar login central | commit `47c0d99` removeu backend do Portal e restaurou o site estático |
| risco de dupla cobertura por empenho solto | pool ficou informativo; só cobre O.S. após apropriação ADMIN com BAIXA real |

## 12. Decisões técnicas e motivos

- **Banco compartilhado, serviços separados:** simplifica FKs e transações sem criar monólito/deploy único.
- **Migrações aditivas:** preserva dados operacionais e permite rollback de código por flag.
- **UUID interno:** números visíveis e chassis podem repetir historicamente.
- **Chassi completo armazenado:** últimos 8/4 apenas para busca/exibição.
- **Recebimento e movimento na mesma transação:** evita saldo sem recebimento ou recebimento sem saldo.
- **Conclusões não movimentam estoque:** somente o almoxarife/serviço de recebimento altera saldo.
- **Correção histórica ADMIN-only:** evita reclassificação/baixa em massa por perfis operacionais.
- **Saldo compartilhado não reduz necessidade automaticamente:** o mesmo pool não pode cobrir vários veículos simultaneamente.
- **B.O.M. mestre no Cadastro:** consumidores não mantêm estrutura concorrente.
- **Produção usa `work_order_id`:** chassi identifica veículo físico, não ocorrência operacional.
- **Fonte de verdade remota:** dados locais de testes são descartáveis.
- **Portal estático preservado:** solicitação explícita; SSO central permanece suporte técnico opcional, não estado presumido.

## 13. Riscos, limitações e débitos técnicos

- Produção continua ativa durante mudanças; sempre registrar contagens antes/depois.
- 270 empenhos históricos permaneceram sem correspondência e foram corretamente ignorados.
- Saldo compartilhado exige decisão humana ADMIN para apropriação; ainda não é rateio automático.
- Login visual final não foi completado porque a credencial fornecida não é válida em produção.
- Não existe staging remoto dedicado confirmado. Testes locais/Docker não substituem staging com snapshot real.
- O projeto MES está em outro projeto/workspace Render e não apareceu na listagem MCP do workspace principal.
- Portal não centraliza login enquanto permanecer static site puro.
- A raiz coordenadora não tem remote e contém repositórios aninhados; não transformar em monorepo por acidente.
- Arquivos de dados/logs/binários sujos podem sobrescrever artefatos do usuário se alguém executar reset/clean.
- RLS legado e superfícies REST devem continuar sendo auditados separadamente; service role nunca pode ir ao navegador.
- Rotacionar todas as chaves/tokens/senhas que tenham sido compartilhados durante o desenvolvimento.
- `INICIAR_CADASTRO.cmd` da raiz ainda aponta para um diretório antigo fora de `ERP_BASELINE_20260728`; corrigir somente após confirmar qual cópia é a oficial.
- Main local de Estoque/Suprimentos está desatualizada; a branch de integração e `origin/main` contêm o código vigente.

## 14. Serviços de produção, staging e desenvolvimento

Produção:

| Serviço | ID Render | Plano/Tipo | URL |
|---|---|---|---|
| Portal | `srv-d9lsj72jnfac73b6q020` | static site | `https://ji-portal-operacional.onrender.com` |
| Suprimentos | `srv-d9aolkucjfls73d9nlm0` | web/free | `https://modulo-suprimentos.onrender.com` |
| Cadastro | `srv-d98ioed7vvec739mvte0` | web/free | `https://modulocadastro.onrender.com` |
| Estoque | `srv-d93tpi9o3t8c739qlu5g` | web/standard | `https://moduloestoque-cni2.onrender.com` |
| MES | `srv-d6scqbn5gffc738hd1m0` | web em projeto Render separado | `https://projeto-final-main.onrender.com` |

Workspace Render principal: `tea-d8qq5nj6sc1c73acac6g`. MES pertence ao projeto Render `prj-d63sqacr85hc73bfaqu0`. Nenhum serviço/configuração foi alterado ao gerar este handoff.

Staging:

- não há serviço remoto de staging confirmado;
- houve PostgreSQL Docker temporário/restauração local para smoke MES;
- o contêiner foi removido e as portas 18010, 18011 e 55439 ficaram livres.

Desenvolvimento local:

- Estoque: `http://127.0.0.1:5000` via `INICIAR_ESTOQUE.cmd`;
- Suprimentos: `http://127.0.0.1:5001` via `INICIAR_SUPRIMENTOS.cmd`;
- MES: `http://127.0.0.1:8010` via `INICIAR_MES.cmd`;
- Cadastro: script indica `http://127.0.0.1:8001`, mas o caminho local precisa ser corrigido/confirmado.

Backups preservados:

- `supabase_mes_legado_pre_cutover_20260729.dump` — SHA-256 `3BB3CAD202033D03588DD203ABCDC749E99DE4F43A7D37865968D530601E4034`;
- `supabase_compartilhado_pos_migracao_20260729.dump` — SHA-256 `EBBEB80C80F4395D25D554F39FDB0BCFE3CBBD0976A8109BBC3348A7A38953B7`.

## 15. Estado exato em que o trabalho parou

- Código das quatro solicitações mais recentes está implementado, testado, commitado, publicado em `main` e implantado no Render para Estoque/Suprimentos.
- Migration de permissão ADMIN está aplicada no Supabase.
- Reconciliação histórica foi executada e auditada sem alterar quantidade, custo ou saldo.
- Serviços estão `live`; health checks HTTP 200; logs sem erro após deploy.
- Worktrees de código-fonte estão limpos, exceto os artefatos locais listados.
- A sessão de navegador de teste foi encerrada.
- A única lacuna imediata é o smoke visual autenticado com credencial vigente e o primeiro teste humano controlado de apropriação compartilhada/remessa por linha.
- Nenhuma nova alteração de banco, Render ou configuração deve ser feita apenas para continuar a leitura deste documento.

## 16. Próxima ação recomendada

1. Ler este documento integralmente.
2. Em cada repositório, executar `git status --short --branch` e preservar os arquivos sujos.
3. Confirmar que `origin/main` ainda aponta para `9b32534` no Estoque e `182ef6c` ou para o commit de handoff posterior em Suprimentos.
4. Consultar `/healthz` dos quatro backends; não fazer mutação.
5. Solicitar ao usuário uma credencial ADMIN vigente ou pedir que ele realize o login manualmente.
6. Fazer smoke visual somente leitura do painel de Trânsito e da aba Necessidades O.S.
7. Validar que perfis não ADMIN não enxergam ações de correção/baixa por ID.
8. Com autorização operacional e um caso real controlado, apropriar parte de um único empenho compartilhado para uma O.S. usando motivo e idempotency key.
9. Reconciliar antes/depois: movimento total +1, saldo físico conforme a baixa real, vínculo correto, sem replay duplicado.
10. Criar uma O.C. controlada com duas linhas/datas distintas e validar trânsito; não receber sem documento físico.
11. Registrar resultados, commit/deploy/migration e atualizar este arquivo.
12. Tratar os 270 não vinculados somente em uma nova fase, com relatório e aprovação; não inferir vínculo automaticamente.

## 17. Prompt pronto para o próximo agente

```text
Você continuará o ERP industrial da JI Montadora exatamente do estado documentado em HANDOFF_CONTINUIDADE.md.

Antes de agir:
1. Leia o HANDOFF integralmente, AGENTS.md/README e migrations relevantes.
2. Execute git status nos repositórios ModuloEstoque, modulo-suprimentos, projeto_final-main, ModuloCadastro e portal-acesso-ji.
3. Preserve todos os arquivos locais sujos listados; não use reset, clean ou checkout em massa.
4. Considere somente o Supabase pago rodtxswtqbsbtukmvobn e os sistemas em produção como fonte de verdade. Dados locais são descartáveis.
5. Não exponha nem reutilize segredos já compartilhados no histórico. Não altere Supabase, Render ou dados reais sem necessidade e autorização dentro do escopo.

Estado esperado:
- Estoque HEAD funcional 9b32534; Suprimentos 182ef6c; MES 88c5f4a; Cadastro 1cfc72c; Portal 47c0d99, mais eventual commit posterior apenas deste HANDOFF.
- ERP e RBAC compartilhado ativos; MES no banco compartilhado; upload legado desligado.
- Reconciliação histórica concluída: 1.083 vínculos, 270 ignorados, diferença zero no saldo.
- Testes: Estoque 70/70 e Suprimentos 101/101.

Próxima tarefa:
Faça primeiro um smoke somente leitura e autenticado das novas telas de Trânsito Pendente, Necessidades O.S. e saldo compartilhado. A credencial 1/2410 foi recusada; peça uma credencial vigente ou solicite login manual. Confirme que baixa/correção por ID e apropriação compartilhada são ADMIN-only. Depois, apenas com autorização operacional, valide um caso controlado de apropriação compartilhada e uma O.C. com duas remessas, reconciliando o estoque antes/depois e garantindo idempotência.

Não repita migrations ou o SQL 20260803_reconcile_historical_commitments_PRODUCTION.sql. Não tente vincular automaticamente os 270 registros restantes. Ao concluir, atualize HANDOFF_CONTINUIDADE.md com evidências, testes, commits e qualquer nova pendência.
```
