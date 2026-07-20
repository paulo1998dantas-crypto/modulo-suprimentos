-- Atualizacao incremental do ModuloSuprimentos para uma base ja existente.
-- Preserva integralmente suprimentos_documentos e seus JSONs.
-- Nao contem DELETE, TRUNCATE, DROP TABLE nem recriacao da tabela de documentos.

begin;

do $$
begin
    if to_regclass('public.suprimentos_documentos') is null then
        raise exception 'Tabela public.suprimentos_documentos nao existe. Execute primeiro a migracao-base em uma instalacao nova.';
    end if;
end
$$;

alter table public.suprimentos_documentos
    add column if not exists status text not null default 'emitido',
    add column if not exists submit_token text null,
    add column if not exists criado_por text not null default '',
    add column if not exists atualizado_por text not null default '';

alter table public.suprimentos_documentos
    alter column status set default 'emitido',
    alter column criado_por set default '',
    alter column atualizado_por set default '';

do $$
begin
    if exists (
        select 1
        from public.suprimentos_documentos
        where status is not null
          and status not in ('rascunho', 'emitido', 'cancelado', 'concluido')
    ) then
        raise exception 'Existem status fora do conjunto permitido. Nenhuma alteracao foi aplicada.';
    end if;

    if exists (
        select submit_token
        from public.suprimentos_documentos
        where submit_token is not null
        group by submit_token
        having count(*) > 1
    ) then
        raise exception 'Existem submit_token duplicados. Nenhuma alteracao foi aplicada.';
    end if;

    if not exists (
        select 1
        from pg_constraint
        where conname = 'suprimentos_documentos_status_check'
          and conrelid = 'public.suprimentos_documentos'::regclass
    ) then
        alter table public.suprimentos_documentos
            add constraint suprimentos_documentos_status_check
            check (status in ('rascunho', 'emitido', 'cancelado', 'concluido'));
    end if;

    if not exists (
        select 1
        from pg_constraint
        where conname = 'suprimentos_documentos_submit_token_key'
          and conrelid = 'public.suprimentos_documentos'::regclass
    ) then
        alter table public.suprimentos_documentos
            add constraint suprimentos_documentos_submit_token_key unique (submit_token);
    end if;
end
$$;

create table if not exists public.suprimentos_documento_contadores (
    tipo text primary key check (tipo in ('oc', 'os')),
    ultimo_numero bigint not null default 0,
    updated_at timestamptz not null default now()
);

insert into public.suprimentos_documento_contadores (tipo, ultimo_numero)
select tipo, coalesce(max(numero::bigint) filter (where numero ~ '^[0-9]+$'), 0)
from public.suprimentos_documentos
where tipo in ('oc', 'os')
group by tipo
on conflict (tipo) do update
set ultimo_numero = greatest(
    public.suprimentos_documento_contadores.ultimo_numero,
    excluded.ultimo_numero
);

insert into public.suprimentos_documento_contadores (tipo, ultimo_numero)
values ('oc', 0), ('os', 0)
on conflict (tipo) do nothing;

create or replace function public.suprimentos_proximo_numero(p_tipo text)
returns bigint
language sql
security invoker
set search_path = ''
as $$
    insert into public.suprimentos_documento_contadores as contador (tipo, ultimo_numero, updated_at)
    values (lower(p_tipo), 1, now())
    on conflict (tipo) do update
    set ultimo_numero = contador.ultimo_numero + 1,
        updated_at = now()
    returning ultimo_numero;
$$;

alter table public.suprimentos_documento_contadores enable row level security;

grant select, insert, update, delete
on table public.suprimentos_documentos, public.suprimentos_documento_contadores
to service_role;

revoke all on function public.suprimentos_proximo_numero(text) from public, anon, authenticated;
grant execute on function public.suprimentos_proximo_numero(text) to service_role;

notify pgrst, 'reload schema';

commit;

-- Verificacao somente-leitura sugerida depois da execucao:
-- select count(*) as documentos_preservados from public.suprimentos_documentos;
-- select tipo, ultimo_numero from public.suprimentos_documento_contadores order by tipo;
-- select column_name, data_type, column_default
-- from information_schema.columns
-- where table_schema = 'public'
--   and table_name = 'suprimentos_documentos'
--   and column_name in ('status', 'submit_token', 'criado_por', 'atualizado_por')
-- order by column_name;
