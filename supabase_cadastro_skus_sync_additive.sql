begin;

create or replace function public.sync_cadastro_registro_to_operational_sku()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    normalized_sku text := upper(btrim(coalesce(new.sku, '')));
    normalized_description text := nullif(btrim(coalesce(new.descricao_primaria, '')), '');
    normalized_group text;
begin
    if normalized_sku = '' then
        return new;
    end if;

    normalized_group := case left(normalized_sku, 2)
        when '10' then '10 - INSUMO'
        when '20' then '20 - PRODUTO EM PROCESSO'
        when '30' then '30 - CONJUNTO / KIT'
        when '40' then '40 - TRANSFORMACAO'
        when '50' then '50 - MRO'
        else null
    end;

    insert into public.skus (
        sku,
        descricao,
        unidade,
        categoria,
        grupo,
        active,
        created_at,
        updated_at
    ) values (
        normalized_sku,
        coalesce(normalized_description, normalized_sku),
        nullif(btrim(coalesce(new.unidade, '')), ''),
        nullif(btrim(coalesce(new.category_label, '')), ''),
        normalized_group,
        coalesce(new.ativo, true),
        clock_timestamp() at time zone 'America/Sao_Paulo',
        clock_timestamp() at time zone 'America/Sao_Paulo'
    )
    on conflict (sku) do update set
        descricao = excluded.descricao,
        unidade = excluded.unidade,
        categoria = excluded.categoria,
        grupo = coalesce(public.skus.grupo, excluded.grupo),
        active = excluded.active,
        updated_at = excluded.updated_at;

    return new;
end;
$$;

drop trigger if exists cadastro_registros_sync_operational_sku on public.cadastro_registros;

create trigger cadastro_registros_sync_operational_sku
after insert or update of sku, descricao_primaria, unidade, category_label, ativo
on public.cadastro_registros
for each row
execute function public.sync_cadastro_registro_to_operational_sku();

insert into public.skus (
    sku,
    descricao,
    unidade,
    categoria,
    grupo,
    active,
    created_at,
    updated_at
)
select
    upper(btrim(c.sku)),
    coalesce(nullif(btrim(coalesce(c.descricao_primaria, '')), ''), upper(btrim(c.sku))),
    nullif(btrim(coalesce(c.unidade, '')), ''),
    nullif(btrim(coalesce(c.category_label, '')), ''),
    case left(upper(btrim(c.sku)), 2)
        when '10' then '10 - INSUMO'
        when '20' then '20 - PRODUTO EM PROCESSO'
        when '30' then '30 - CONJUNTO / KIT'
        when '40' then '40 - TRANSFORMACAO'
        when '50' then '50 - MRO'
        else null
    end,
    coalesce(c.ativo, true),
    clock_timestamp() at time zone 'America/Sao_Paulo',
    clock_timestamp() at time zone 'America/Sao_Paulo'
from public.cadastro_registros c
where btrim(coalesce(c.sku, '')) <> ''
  and not exists (
      select 1
      from public.skus s
      where s.sku = upper(btrim(c.sku))
  );

commit;
