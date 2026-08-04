-- Reconciliação controlada dos documentos de O.S. com a O.S. operacional.
--
-- Escopo autorizado em 2026-08-04:
--   * preencher somente suprimentos_documentos.erp_work_order_id;
--   * exatamente 20 documentos O.S. EMITIDOS hoje ligados apenas pelo número;
--   * número da O.S. idêntico, correspondência única e chassi compatível pelos
--     oito últimos caracteres normalizados;
--   * preservar os documentos 206, 208 e 210 (AG CHEGADA concluídos) sem link;
--   * não alterar estoque, saldos, movimentos, itens, veículos, O.S. ou etapas.
--
-- Este arquivo é um script de reconciliação de dados, não uma migration de
-- schema. Ele é fail-closed e idempotente: a primeira execução atualiza os 20
-- vínculos; uma segunda execução reconhece os 20 eventos de auditoria e não
-- altera nenhuma linha. Qualquer estado parcial ou divergente aborta tudo.
--
-- Execute primeiro em staging restaurado do backup e só então no SQL Editor do
-- projeto correto. O rollback correspondente está no arquivo:
-- supabase_os_document_work_order_link_backfill_20260804_rollback.sql

begin;
set transaction isolation level repeatable read;
set local lock_timeout = '5s';
set local statement_timeout = '60s';

-- Impede criação/edição simultânea de documentos durante a reconciliação. O
-- bloqueio é curto e não bloqueia consultas.
lock table public.suprimentos_documentos in share row exclusive mode;

do $$
begin
    if to_regclass('public.suprimentos_documentos') is null
       or to_regclass('public.erp_work_orders') is null
       or to_regclass('public.erp_vehicle_entries') is null
       or to_regclass('public.erp_vehicles') is null
       or to_regclass('public.erp_work_order_stages') is null
       or to_regclass('public.erp_work_order_stage_events') is null
       or to_regclass('public.movements') is null
       or to_regclass('public.stock_balances') is null
       or to_regclass('public.erp_audit_events') is null then
        raise exception 'Contrato ERP incompleto. Nenhuma alteração foi aplicada.';
    end if;

    if not exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'suprimentos_documentos'
          and column_name = 'erp_work_order_id'
          and data_type = 'uuid'
    ) then
        raise exception 'suprimentos_documentos.erp_work_order_id ausente ou não UUID.';
    end if;

    if not exists (
        select 1
        from pg_indexes
        where schemaname = 'public'
          and tablename = 'suprimentos_documentos'
          and indexname = 'suprimentos_documentos_erp_work_order_uidx'
    ) then
        raise exception 'Índice único canônico do vínculo de O.S. não está instalado.';
    end if;
end
$$;

-- Fotografia de todas as entidades que não podem mudar. Para documentos, o
-- hash exclui somente erp_work_order_id e updated_at: o primeiro é o vínculo
-- autorizado e o segundo é atualizado automaticamente pelo trigger da tabela.
create temporary table _os_link_integrity_before (
    entity_name text primary key,
    row_count bigint not null,
    fingerprint text not null
) on commit drop;

insert into _os_link_integrity_before(entity_name, row_count, fingerprint)
select 'documents_payload', count(*),
       md5(coalesce(string_agg(md5((to_jsonb(d) - 'erp_work_order_id' - 'updated_at')::text), '' order by d.id::text), ''))
  from public.suprimentos_documentos d
union all
select 'vehicles', count(*),
       md5(coalesce(string_agg(md5(to_jsonb(v)::text), '' order by v.id::text), ''))
  from public.erp_vehicles v
union all
select 'vehicle_entries', count(*),
       md5(coalesce(string_agg(md5(to_jsonb(e)::text), '' order by e.id::text), ''))
  from public.erp_vehicle_entries e
union all
select 'work_orders', count(*),
       md5(coalesce(string_agg(md5(to_jsonb(w)::text), '' order by w.id::text), ''))
  from public.erp_work_orders w
union all
select 'work_order_stages', count(*),
       md5(coalesce(string_agg(md5(to_jsonb(s)::text), '' order by s.id::text), ''))
  from public.erp_work_order_stages s
union all
select 'work_order_stage_events', count(*),
       md5(coalesce(string_agg(md5(to_jsonb(se)::text), '' order by se.id::text), ''))
  from public.erp_work_order_stage_events se
union all
select 'movements', count(*),
       md5(coalesce(string_agg(md5(to_jsonb(m)::text), '' order by m.id::text), ''))
  from public.movements m
union all
select 'stock_balances', count(*),
       md5(coalesce(string_agg(md5(to_jsonb(sb)::text), '' order by sb.id::text), ''))
  from public.stock_balances sb;

create temporary table _os_link_candidates on commit drop as
with exact_matches as (
    select
        d.id as document_id,
        d.numero,
        d.dados ->> 'chassis' as document_chassis,
        w.id as work_order_id,
        w.numero_os,
        e.item_number,
        v.chassi as vehicle_chassis,
        regexp_replace(upper(coalesce(d.dados ->> 'chassis', '')), '[^A-Z0-9]', '', 'g') as document_chassis_norm,
        regexp_replace(upper(coalesce(v.chassi, '')), '[^A-Z0-9]', '', 'g') as vehicle_chassis_norm,
        count(*) over (partition by d.id) as exact_match_count
    from public.suprimentos_documentos d
    join public.erp_work_orders w
      on w.numero_os = d.numero
    join public.erp_vehicle_entries e
      on e.id = w.vehicle_entry_id
    join public.erp_vehicles v
      on v.id = e.vehicle_id
    where d.tipo = 'os'
      and d.status = 'emitido'
      and d.erp_work_order_id is null
)
select
    em.document_id,
    em.numero,
    em.document_chassis,
    em.work_order_id,
    em.numero_os,
    em.item_number,
    em.vehicle_chassis
from exact_matches em
where em.exact_match_count = 1
  and length(em.document_chassis_norm) >= 8
  and length(em.vehicle_chassis_norm) >= 8
  and right(em.document_chassis_norm, 8) = right(em.vehicle_chassis_norm, 8)
  and not exists (
      select 1
      from public.suprimentos_documentos other_document
      where other_document.id <> em.document_id
        and other_document.erp_work_order_id = em.work_order_id
  );

do $$
declare
    v_unlinked_emitted bigint;
    v_exact_match_rows bigint;
    v_candidate_count bigint;
    v_distinct_work_orders bigint;
    v_direct_active bigint;
    v_backfill_audits bigint;
    v_valid_audit_links bigint;
    v_preserved_ag bigint;
begin
    select count(*)
      into v_unlinked_emitted
      from public.suprimentos_documentos d
     where d.tipo = 'os'
       and d.status = 'emitido'
       and d.erp_work_order_id is null;

    select count(*)
      into v_exact_match_rows
      from public.suprimentos_documentos d
      join public.erp_work_orders w on w.numero_os = d.numero
     where d.tipo = 'os'
       and d.status = 'emitido'
       and d.erp_work_order_id is null;

    select count(*), count(distinct work_order_id)
      into v_candidate_count, v_distinct_work_orders
      from _os_link_candidates;

    select count(*)
      into v_direct_active
      from public.suprimentos_documentos d
      join public.erp_work_orders w on w.id = d.erp_work_order_id
     where d.tipo = 'os'
       and d.status = 'emitido';

    select count(*)
      into v_backfill_audits
      from public.erp_audit_events a
     where a.origin = 'RECONCILIACAO_SUPRIMENTOS_20260804'
       and a.action = 'VINCULO_DOCUMENTO_OS_UUID_BACKFILL';

    select count(*)
      into v_valid_audit_links
      from public.erp_audit_events a
      join public.suprimentos_documentos d
        on d.id = (a.after_data ->> 'document_id')::bigint
     where a.origin = 'RECONCILIACAO_SUPRIMENTOS_20260804'
       and a.action = 'VINCULO_DOCUMENTO_OS_UUID_BACKFILL'
       and d.erp_work_order_id = a.entity_id;

    select count(*)
      into v_preserved_ag
      from public.suprimentos_documentos d
     where d.id in (206, 208, 210)
       and d.tipo = 'os'
       and d.status = 'concluido'
       and d.erp_work_order_id is null;

    if v_preserved_ag <> 3 then
        raise exception 'Os três AG CHEGADA históricos não estão no estado protegido esperado.';
    end if;

    if v_candidate_count = 20
       and v_unlinked_emitted = 20
       and v_exact_match_rows = 20
       and v_distinct_work_orders = 20
       and v_direct_active = 27
       and v_backfill_audits = 0 then
        -- Primeira execução no snapshot auditado: pode prosseguir.
        null;
    elsif v_candidate_count = 0
          and v_direct_active >= 47
          and v_backfill_audits = 20
          and v_valid_audit_links = 20 then
        -- Reexecução idempotente: os 20 alvos continuam comprovados. Novos
        -- documentos ainda aguardando abertura operacional ficam fora deste
        -- backfill histórico e seguem o fluxo normal da Gestão de O.S.
        null;
    else
        raise exception using
            message = format(
                'Estado divergente: unlinked=%s exact=%s candidates=%s distinct_wo=%s direct=%s audits=%s valid_audit_links=%s. Nenhuma alteração foi aplicada.',
                v_unlinked_emitted, v_exact_match_rows, v_candidate_count,
                v_distinct_work_orders, v_direct_active, v_backfill_audits,
                v_valid_audit_links
            );
    end if;
end
$$;

create temporary table _os_link_updated on commit drop as
with updated as (
    update public.suprimentos_documentos d
       set erp_work_order_id = c.work_order_id
      from _os_link_candidates c
     where d.id = c.document_id
       and d.erp_work_order_id is null
    returning d.id as document_id, d.erp_work_order_id as work_order_id
)
select * from updated;

insert into public.erp_audit_events (
    id, entity_type, entity_id, action, actor, origin,
    before_data, after_data, reason
)
select
    (
        substr(h.hash_value, 1, 8) || '-' ||
        substr(h.hash_value, 9, 4) || '-' ||
        substr(h.hash_value, 13, 4) || '-' ||
        substr(h.hash_value, 17, 4) || '-' ||
        substr(h.hash_value, 21, 12)
    )::uuid,
    'WORK_ORDER',
    c.work_order_id,
    'VINCULO_DOCUMENTO_OS_UUID_BACKFILL',
    'sistema:reconciliacao:20260804',
    'RECONCILIACAO_SUPRIMENTOS_20260804',
    jsonb_build_object(
        'document_id', c.document_id,
        'numero', c.numero,
        'erp_work_order_id', null
    ),
    jsonb_build_object(
        'document_id', c.document_id,
        'numero', c.numero,
        'erp_work_order_id', c.work_order_id,
        'item_number', c.item_number,
        'document_chassis', c.document_chassis,
        'vehicle_chassis', c.vehicle_chassis
    ),
    'Conversão do vínculo legado por número para UUID canônico, após match único e validação dos oito últimos caracteres do chassi.'
from _os_link_candidates c
join _os_link_updated u
  on u.document_id = c.document_id
 and u.work_order_id = c.work_order_id
cross join lateral (
    select md5(
        '20260804-os-document-work-order-link:' ||
        c.document_id::text || ':' || c.work_order_id::text
    ) as hash_value
) h
on conflict (id) do nothing;

create temporary table _os_link_integrity_after on commit drop as
select 'documents_payload'::text as entity_name, count(*) as row_count,
       md5(coalesce(string_agg(md5((to_jsonb(d) - 'erp_work_order_id' - 'updated_at')::text), '' order by d.id::text), '')) as fingerprint
  from public.suprimentos_documentos d
union all
select 'vehicles', count(*),
       md5(coalesce(string_agg(md5(to_jsonb(v)::text), '' order by v.id::text), ''))
  from public.erp_vehicles v
union all
select 'vehicle_entries', count(*),
       md5(coalesce(string_agg(md5(to_jsonb(e)::text), '' order by e.id::text), ''))
  from public.erp_vehicle_entries e
union all
select 'work_orders', count(*),
       md5(coalesce(string_agg(md5(to_jsonb(w)::text), '' order by w.id::text), ''))
  from public.erp_work_orders w
union all
select 'work_order_stages', count(*),
       md5(coalesce(string_agg(md5(to_jsonb(s)::text), '' order by s.id::text), ''))
  from public.erp_work_order_stages s
union all
select 'work_order_stage_events', count(*),
       md5(coalesce(string_agg(md5(to_jsonb(se)::text), '' order by se.id::text), ''))
  from public.erp_work_order_stage_events se
union all
select 'movements', count(*),
       md5(coalesce(string_agg(md5(to_jsonb(m)::text), '' order by m.id::text), ''))
  from public.movements m
union all
select 'stock_balances', count(*),
       md5(coalesce(string_agg(md5(to_jsonb(sb)::text), '' order by sb.id::text), ''))
  from public.stock_balances sb;

do $$
declare
    v_updated bigint;
    v_audits bigint;
    v_active_direct_valid bigint;
    v_active_unlinked bigint;
    v_preserved_ag bigint;
    v_valid_audit_links bigint;
begin
    if exists (
        select 1
        from _os_link_integrity_before b
        full join _os_link_integrity_after a using (entity_name)
        where b.entity_name is null
           or a.entity_name is null
           or b.row_count is distinct from a.row_count
           or b.fingerprint is distinct from a.fingerprint
    ) then
        raise exception 'Reconciliação alteraria estoque, itens, veículos, O.S. ou etapas. Transação abortada.';
    end if;

    select count(*) into v_updated from _os_link_updated;

    select count(*)
      into v_audits
      from public.erp_audit_events a
     where a.origin = 'RECONCILIACAO_SUPRIMENTOS_20260804'
       and a.action = 'VINCULO_DOCUMENTO_OS_UUID_BACKFILL';

    select count(*)
      into v_active_direct_valid
      from public.suprimentos_documentos d
      join public.erp_work_orders w on w.id = d.erp_work_order_id
      join public.erp_vehicle_entries e on e.id = w.vehicle_entry_id
      join public.erp_vehicles v on v.id = e.vehicle_id
     where d.tipo = 'os'
       and d.status = 'emitido'
       and length(regexp_replace(upper(coalesce(d.dados ->> 'chassis', '')), '[^A-Z0-9]', '', 'g')) >= 8
       and right(regexp_replace(upper(coalesce(d.dados ->> 'chassis', '')), '[^A-Z0-9]', '', 'g'), 8)
           = right(regexp_replace(upper(coalesce(v.chassi, '')), '[^A-Z0-9]', '', 'g'), 8);

    select count(*)
      into v_active_unlinked
      from public.suprimentos_documentos d
     where d.tipo = 'os'
       and d.status = 'emitido'
       and d.erp_work_order_id is null;

    select count(*)
      into v_preserved_ag
      from public.suprimentos_documentos d
     where d.id in (206, 208, 210)
       and d.tipo = 'os'
       and d.status = 'concluido'
       and d.erp_work_order_id is null;

    select count(*)
      into v_valid_audit_links
      from public.erp_audit_events a
      join public.suprimentos_documentos d
        on d.id = (a.after_data ->> 'document_id')::bigint
     where a.origin = 'RECONCILIACAO_SUPRIMENTOS_20260804'
       and a.action = 'VINCULO_DOCUMENTO_OS_UUID_BACKFILL'
       and d.erp_work_order_id = a.entity_id;

    if v_updated not in (0, 20)
       or v_audits <> 20
       or v_preserved_ag <> 3
       or v_valid_audit_links <> 20
       or (v_updated = 20 and (v_active_direct_valid <> 47 or v_active_unlinked <> 0))
       or (v_updated = 0 and v_active_direct_valid < 47) then
        raise exception using
            message = format(
                'Pós-validação falhou: updated=%s audits=%s valid_audit_links=%s active_direct_valid=%s active_unlinked=%s preserved_ag=%s.',
                v_updated, v_audits, v_valid_audit_links, v_active_direct_valid, v_active_unlinked,
                v_preserved_ag
            );
    end if;
end
$$;

-- Resultado operacional: 47 documentos ativos com UUID direto e os 3 AG
-- históricos preservados. Nenhum hash protegido pode apresentar diferença.
select
    (select count(*) from _os_link_updated) as links_atualizados_nesta_execucao,
    (select count(*)
       from public.erp_audit_events
      where origin = 'RECONCILIACAO_SUPRIMENTOS_20260804'
        and action = 'VINCULO_DOCUMENTO_OS_UUID_BACKFILL') as links_auditados,
    (select count(*)
       from public.suprimentos_documentos
      where tipo = 'os' and status = 'emitido' and erp_work_order_id is not null) as os_ativas_com_uuid,
    (select count(*)
       from public.suprimentos_documentos
      where tipo = 'os' and status = 'emitido' and erp_work_order_id is null) as os_ativas_sem_uuid,
    (select count(*)
       from public.suprimentos_documentos
      where id in (206, 208, 210) and status = 'concluido' and erp_work_order_id is null) as ag_chegada_preservados;

select
    d.id as document_id,
    d.numero,
    d.erp_work_order_id,
    e.item_number,
    v.chassi
from public.erp_audit_events a
join public.suprimentos_documentos d
  on d.id = (a.after_data ->> 'document_id')::bigint
join public.erp_work_orders w
  on w.id = d.erp_work_order_id
join public.erp_vehicle_entries e
  on e.id = w.vehicle_entry_id
join public.erp_vehicles v
  on v.id = e.vehicle_id
where a.origin = 'RECONCILIACAO_SUPRIMENTOS_20260804'
  and a.action = 'VINCULO_DOCUMENTO_OS_UUID_BACKFILL'
order by d.numero, d.id;

commit;
