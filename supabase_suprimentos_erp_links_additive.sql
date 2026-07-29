-- Vínculos estruturais entre documentos legados e entidades operacionais ERP.
-- Aditiva: não altera JSON, número, status ou qualquer registro existente.
-- Aplicar somente depois de 20260728_erp_operational_integration.sql.
begin;

do $$
begin
    if to_regclass('public.suprimentos_documentos') is null then
        raise exception 'Tabela public.suprimentos_documentos não existe.';
    end if;
    if to_regclass('public.erp_purchase_orders') is null
       or to_regclass('public.erp_work_orders') is null then
        raise exception 'Tabelas ERP ainda não existem. Aplique primeiro a migration operacional.';
    end if;
end
$$;

alter table public.suprimentos_documentos
    add column if not exists erp_purchase_order_id uuid null,
    add column if not exists erp_work_order_id uuid null;

do $$
begin
    if not exists (
        select 1 from pg_constraint
         where conname = 'suprimentos_documentos_erp_purchase_order_fk'
           and conrelid = 'public.suprimentos_documentos'::regclass
    ) then
        alter table public.suprimentos_documentos
            add constraint suprimentos_documentos_erp_purchase_order_fk
            foreign key (erp_purchase_order_id)
            references public.erp_purchase_orders(id)
            not valid;
    end if;

    if not exists (
        select 1 from pg_constraint
         where conname = 'suprimentos_documentos_erp_work_order_fk'
           and conrelid = 'public.suprimentos_documentos'::regclass
    ) then
        alter table public.suprimentos_documentos
            add constraint suprimentos_documentos_erp_work_order_fk
            foreign key (erp_work_order_id)
            references public.erp_work_orders(id)
            not valid;
    end if;
end
$$;

create unique index if not exists suprimentos_documentos_erp_purchase_order_uidx
    on public.suprimentos_documentos(erp_purchase_order_id)
    where erp_purchase_order_id is not null;

create unique index if not exists suprimentos_documentos_erp_work_order_uidx
    on public.suprimentos_documentos(erp_work_order_id)
    where erp_work_order_id is not null;

commit;

-- Depois do backfill e da reconciliação em staging:
-- alter table public.suprimentos_documentos
--     validate constraint suprimentos_documentos_erp_purchase_order_fk;
-- alter table public.suprimentos_documentos
--     validate constraint suprimentos_documentos_erp_work_order_fk;
