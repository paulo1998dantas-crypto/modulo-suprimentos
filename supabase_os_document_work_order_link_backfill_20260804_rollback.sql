-- Rollback lógico e controlado da reconciliação de vínculos de O.S. de
-- 2026-08-04. Não apaga auditoria: registra um evento inverso por documento.
--
-- O rollback só aceita exatamente os 20 pares document_id/work_order_id
-- registrados pelo backfill e somente se número e chassi continuarem
-- compatíveis. Se qualquer O.S. tiver sido relincada ou editada depois, toda a
-- transação é abortada para evitar desfazer uma correção operacional legítima.
-- Uma segunda execução é um no-op validado.

begin;
set transaction isolation level repeatable read;
set local lock_timeout = '5s';
set local statement_timeout = '60s';

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
end
$$;

create temporary table _os_link_rollback_integrity_before (
    entity_name text primary key,
    row_count bigint not null,
    fingerprint text not null
) on commit drop;

-- updated_at é excluído junto com o vínculo porque o trigger da tabela o
-- atualiza automaticamente; todos os demais campos do documento ficam no hash.
insert into _os_link_rollback_integrity_before(entity_name, row_count, fingerprint)
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

create temporary table _os_link_rollback_candidates on commit drop as
select
    d.id as document_id,
    d.numero,
    d.erp_work_order_id as work_order_id,
    e.item_number,
    d.dados ->> 'chassis' as document_chassis,
    v.chassi as vehicle_chassis
from public.erp_audit_events a
join public.suprimentos_documentos d
  on d.id = (a.after_data ->> 'document_id')::bigint
join public.erp_work_orders w
  on w.id = a.entity_id
join public.erp_vehicle_entries e
  on e.id = w.vehicle_entry_id
join public.erp_vehicles v
  on v.id = e.vehicle_id
where a.origin = 'RECONCILIACAO_SUPRIMENTOS_20260804'
  and a.action = 'VINCULO_DOCUMENTO_OS_UUID_BACKFILL'
  and d.erp_work_order_id = a.entity_id
  -- O backfill histórico alterou somente a coluna canônica. Se o fluxo novo
  -- já espelhou o UUID no JSON, houve uso posterior legítimo e o rollback
  -- inteiro deve ser recusado em vez de apagar essa associação silenciosamente.
  and nullif(btrim(d.dados ->> 'erp_work_order_id'), '') is null
  and w.numero_os = d.numero
  and length(regexp_replace(upper(coalesce(d.dados ->> 'chassis', '')), '[^A-Z0-9]', '', 'g')) >= 8
  and length(regexp_replace(upper(coalesce(v.chassi, '')), '[^A-Z0-9]', '', 'g')) >= 8
  and right(regexp_replace(upper(coalesce(d.dados ->> 'chassis', '')), '[^A-Z0-9]', '', 'g'), 8)
      = right(regexp_replace(upper(coalesce(v.chassi, '')), '[^A-Z0-9]', '', 'g'), 8);

do $$
declare
    v_original_audits bigint;
    v_rollback_audits bigint;
    v_candidates bigint;
    v_distinct_documents bigint;
    v_distinct_work_orders bigint;
    v_already_null bigint;
    v_preserved_ag bigint;
begin
    select count(*)
      into v_original_audits
      from public.erp_audit_events a
     where a.origin = 'RECONCILIACAO_SUPRIMENTOS_20260804'
       and a.action = 'VINCULO_DOCUMENTO_OS_UUID_BACKFILL';

    select count(*)
      into v_rollback_audits
      from public.erp_audit_events a
     where a.origin = 'RECONCILIACAO_SUPRIMENTOS_20260804'
       and a.action = 'VINCULO_DOCUMENTO_OS_UUID_BACKFILL_ROLLBACK';

    select count(*), count(distinct document_id), count(distinct work_order_id)
      into v_candidates, v_distinct_documents, v_distinct_work_orders
      from _os_link_rollback_candidates;

    select count(*)
      into v_already_null
      from public.erp_audit_events a
      join public.suprimentos_documentos d
        on d.id = (a.after_data ->> 'document_id')::bigint
     where a.origin = 'RECONCILIACAO_SUPRIMENTOS_20260804'
       and a.action = 'VINCULO_DOCUMENTO_OS_UUID_BACKFILL'
       and d.erp_work_order_id is null;

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

    if v_original_audits = 20
       and v_candidates = 20
       and v_distinct_documents = 20
       and v_distinct_work_orders = 20
       and v_rollback_audits = 0 then
        -- Primeira execução do rollback.
        null;
    elsif v_original_audits = 20
          and v_candidates = 0
          and v_already_null = 20
          and v_rollback_audits = 20 then
        -- Reexecução idempotente: rollback já concluído.
        null;
    else
        raise exception using
            message = format(
                'Rollback recusado: original_audits=%s candidates=%s distinct_docs=%s distinct_wo=%s already_null=%s rollback_audits=%s.',
                v_original_audits, v_candidates, v_distinct_documents,
                v_distinct_work_orders, v_already_null, v_rollback_audits
            );
    end if;
end
$$;

create temporary table _os_link_rolled_back on commit drop as
with updated as (
    update public.suprimentos_documentos d
       set erp_work_order_id = null
      from _os_link_rollback_candidates c
     where d.id = c.document_id
       and d.erp_work_order_id = c.work_order_id
    returning d.id as document_id
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
    'VINCULO_DOCUMENTO_OS_UUID_BACKFILL_ROLLBACK',
    'sistema:rollback:20260804',
    'RECONCILIACAO_SUPRIMENTOS_20260804',
    jsonb_build_object(
        'document_id', c.document_id,
        'numero', c.numero,
        'erp_work_order_id', c.work_order_id
    ),
    jsonb_build_object(
        'document_id', c.document_id,
        'numero', c.numero,
        'erp_work_order_id', null
    ),
    'Rollback lógico do vínculo canônico; estoque, itens, veículos, O.S. e etapas permanecem inalterados.'
from _os_link_rollback_candidates c
join _os_link_rolled_back r on r.document_id = c.document_id
cross join lateral (
    select md5(
        '20260804-os-document-work-order-link-rollback:' ||
        c.document_id::text || ':' || c.work_order_id::text
    ) as hash_value
) h
on conflict (id) do nothing;

create temporary table _os_link_rollback_integrity_after on commit drop as
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
    v_original_audits bigint;
    v_rollback_audits bigint;
    v_target_links_null bigint;
    v_preserved_ag bigint;
begin
    if exists (
        select 1
        from _os_link_rollback_integrity_before b
        full join _os_link_rollback_integrity_after a using (entity_name)
        where b.entity_name is null
           or a.entity_name is null
           or b.row_count is distinct from a.row_count
           or b.fingerprint is distinct from a.fingerprint
    ) then
        raise exception 'Rollback alteraria estoque, itens, veículos, O.S. ou etapas. Transação abortada.';
    end if;

    select count(*) into v_updated from _os_link_rolled_back;

    select count(*)
      into v_original_audits
      from public.erp_audit_events a
     where a.origin = 'RECONCILIACAO_SUPRIMENTOS_20260804'
       and a.action = 'VINCULO_DOCUMENTO_OS_UUID_BACKFILL';

    select count(*)
      into v_rollback_audits
      from public.erp_audit_events a
     where a.origin = 'RECONCILIACAO_SUPRIMENTOS_20260804'
       and a.action = 'VINCULO_DOCUMENTO_OS_UUID_BACKFILL_ROLLBACK';

    select count(*)
      into v_target_links_null
      from public.erp_audit_events a
      join public.suprimentos_documentos d
        on d.id = (a.after_data ->> 'document_id')::bigint
     where a.origin = 'RECONCILIACAO_SUPRIMENTOS_20260804'
       and a.action = 'VINCULO_DOCUMENTO_OS_UUID_BACKFILL'
       and d.erp_work_order_id is null;

    select count(*)
      into v_preserved_ag
      from public.suprimentos_documentos d
     where d.id in (206, 208, 210)
       and d.status = 'concluido'
       and d.erp_work_order_id is null;

    if v_updated not in (0, 20)
       or v_original_audits <> 20
       or v_rollback_audits <> 20
       or v_target_links_null <> 20
       or v_preserved_ag <> 3 then
        raise exception using
            message = format(
                'Pós-validação do rollback falhou: updated=%s original_audits=%s rollback_audits=%s target_null=%s preserved_ag=%s.',
                v_updated, v_original_audits, v_rollback_audits,
                v_target_links_null, v_preserved_ag
            );
    end if;
end
$$;

select
    (select count(*) from _os_link_rolled_back) as links_removidos_nesta_execucao,
    (select count(*)
       from public.erp_audit_events
      where origin = 'RECONCILIACAO_SUPRIMENTOS_20260804'
        and action = 'VINCULO_DOCUMENTO_OS_UUID_BACKFILL_ROLLBACK') as rollbacks_auditados,
    (select count(*)
       from public.erp_audit_events a
       join public.suprimentos_documentos d
         on d.id = (a.after_data ->> 'document_id')::bigint
      where a.origin = 'RECONCILIACAO_SUPRIMENTOS_20260804'
        and a.action = 'VINCULO_DOCUMENTO_OS_UUID_BACKFILL'
        and d.erp_work_order_id is null) as links_alvo_agora_nulos,
    (select count(*)
       from public.suprimentos_documentos
      where id in (206, 208, 210) and status = 'concluido' and erp_work_order_id is null) as ag_chegada_preservados;

commit;
