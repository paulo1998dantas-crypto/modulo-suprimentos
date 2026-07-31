-- Migra os marcadores legados “AG CHEGADA” de documentos O.S. para Forecast.
-- Seguro para reexecução: a chave de idempotência é o ID do documento legado.
-- Não cria veículo, ITEM, O.S. real, reserva, empenho, recebimento ou movimento.

begin;
set local lock_timeout = 5000;
set local statement_timeout = 60000;

alter table public.suprimentos_forecasts
    drop constraint if exists suprimentos_forecasts_confirmado_proposta_check;
alter table public.suprimentos_forecasts
    add constraint suprimentos_forecasts_confirmado_proposta_check
    check (
        tipo_demanda <> 'AGUARDANDO_CHEGADA'
        or nullif(btrim(proposta_numero), '') is not null
        or origem = 'MIGRACAO_AG_CHEGADA'
    );

-- Cria uma demanda ativa por documento ainda não migrado. Os três legados não
-- tinham proposta nem SKU: ambos ficam explicitamente pendentes para revisão.
with source as (
    select d.*,
           d.dados ->> 'cliente' as cliente_nome,
           d.dados ->> 'mmv' as legacy_mmv,
           d.dados ->> 'chassis' as legacy_chassis,
           d.dados ->> 'municipio' as legacy_municipio,
           d.dados ->> 'processo_conjunto' as legacy_processo_conjunto
      from public.suprimentos_documentos d
     where d.tipo = 'os'
       and (
            upper(d.numero) like '%AG%CHEGADA%'
            or upper(coalesce(d.search_text, '')) like '%AG%CHEGADA%'
            or upper(d.dados::text) like '%AG%CHEGADA%'
       )
       and not exists (
            select 1
              from public.suprimentos_forecasts f
             where f.idempotency_key = 'migracao-ag-chegada:' || d.id::text
       )
), numbered as (
    select s.*, public.suprimentos_proximo_numero_forecast() as numero_forecast
      from source s
)
insert into public.suprimentos_forecasts (
    numero_forecast, codigo, tipo_demanda, status, proposta_numero,
    cliente_nome, data_confirmacao, quantidade_planejada, unidade,
    tipo_servico, origem, observacoes, dados_planejamento,
    idempotency_key, criado_por, atualizado_por
)
select
    n.numero_forecast,
    format('FCT-%s', lpad(n.numero_forecast::text, 5, '0')),
    'AGUARDANDO_CHEGADA',
    'ATIVO',
    '',
    coalesce(n.cliente_nome, ''),
    n.data_criacao,
    1,
    'VEICULO',
    'TRANSFORMACAO',
    'MIGRACAO_AG_CHEGADA',
    'Migrado do marcador legado ' || n.numero || '. Completar proposta e SKUs para MRP.',
    jsonb_build_object(
        'legacy_source_document_id', n.id,
        'legacy_source_document_number', n.numero,
        'legacy_mmv', coalesce(n.legacy_mmv, ''),
        'legacy_chassis', coalesce(n.legacy_chassis, ''),
        'legacy_municipio', coalesce(n.legacy_municipio, ''),
        'legacy_processo_conjunto', coalesce(n.legacy_processo_conjunto, ''),
        'migration_note', 'AG CHEGADA migrado sem proposta/SKU; revisão operacional pendente.'
    ),
    'migracao-ag-chegada:' || n.id::text,
    coalesce(n.criado_por, 'MIGRACAO_ERP'),
    'MIGRACAO_ERP'
from numbered n;

-- O documento legado deixa de ser uma O.S. operacional, porém continua
-- íntegro no histórico e aponta para o Forecast que o substituiu.
update public.suprimentos_documentos d
   set status = 'concluido',
       dados = jsonb_set(
           coalesce(d.dados, '{}'::jsonb),
           '{migracao_forecast}',
           jsonb_build_object(
               'migrado_em', now(),
               'motivo', 'Marcador AG CHEGADA substituído por Forecast aguardando chegada.',
               'forecast_id', f.id,
               'forecast_codigo', f.codigo
           ),
           true
       ),
       atualizado_por = 'MIGRACAO_ERP',
       updated_at = now()
  from public.suprimentos_forecasts f
 where f.idempotency_key = 'migracao-ag-chegada:' || d.id::text
   and d.tipo = 'os'
   and f.origem = 'MIGRACAO_AG_CHEGADA';

commit;

-- Rollback operacional: desative SUPRIMENTOS_FORECAST_ENABLED se necessário.
-- Não apague Forecasts criados; cada um mantém a trilha para o documento legado.
