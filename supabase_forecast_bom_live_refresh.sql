-- Mantém a explosão dos Forecasts ativos alinhada à B.O.M. oficial do Cadastro.
-- A projeção é somente MRP: não reserva, empenha, baixa ou movimenta estoque.

create or replace function public.suprimentos_recalcular_necessidades_forecast(p_forecast_id uuid)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
begin
    delete from public.suprimentos_forecast_necessidades
     where forecast_id = p_forecast_id;

    -- cadastro_bom_componentes é a fonte oficial mantida pelo Módulo Cadastro.
    -- A CTE percorre todos os níveis até as folhas e agrega componentes
    -- repetidos, com proteção contra ciclos e limite técnico de profundidade.
    with recursive exploded as (
        select
            fi.id as forecast_item_id,
            fi.forecast_id,
            fi.sku_id as root_sku_id,
            fi.sku_id,
            fi.sku_codigo,
            fi.quantidade_planejada as quantidade_planejada,
            0 as nivel,
            array[fi.sku_id]::integer[] as caminho_ids,
            array[fi.sku_codigo]::text[] as caminho_codigos
        from public.suprimentos_forecast_itens fi
        where fi.forecast_id = p_forecast_id

        union all

        select
            e.forecast_item_id,
            e.forecast_id,
            e.root_sku_id,
            component.id,
            component.sku,
            e.quantidade_planejada * bom.quantidade,
            e.nivel + 1,
            e.caminho_ids || component.id,
            e.caminho_codigos || component.sku
        from exploded e
        join public.cadastro_bom_componentes bom
          on upper(trim(bom.parent_sku)) = upper(trim(e.sku_codigo))
        join public.skus component
          on upper(trim(component.sku)) = upper(trim(bom.component_sku))
         and component.active is true
        where e.nivel < 12
          and not (component.id = any(e.caminho_ids))
    ), leaves as (
        select e.*
        from exploded e
        where not exists (
            select 1
            from public.cadastro_bom_componentes bom
            join public.skus child
              on upper(trim(child.sku)) = upper(trim(bom.component_sku))
             and child.active is true
            where upper(trim(bom.parent_sku)) = upper(trim(e.sku_codigo))
        )
    )
    insert into public.suprimentos_forecast_necessidades (
        forecast_id, forecast_item_id, sku_id, sku_codigo, descricao, unidade,
        quantidade_planejada, nivel_maximo, origem, caminho_bom
    )
    select
        l.forecast_id,
        l.forecast_item_id,
        l.sku_id,
        sku.sku,
        sku.descricao,
        coalesce(sku.unidade, ''),
        sum(l.quantidade_planejada),
        max(l.nivel),
        case when max(l.nivel) = 0 then 'SKU_SEM_BOM' else 'BOM' end,
        array[]::text[]
    from leaves l
    join public.skus sku on sku.id = l.sku_id
    group by l.forecast_id, l.forecast_item_id, l.sku_id, sku.sku, sku.descricao, sku.unidade;

    update public.suprimentos_forecast_itens fi
       set possui_bom = exists (
               select 1
               from public.cadastro_bom_componentes bom
               where upper(trim(bom.parent_sku)) = upper(trim(fi.sku_codigo))
           ),
           bom_explodida_em = now(),
           updated_at = now()
     where fi.forecast_id = p_forecast_id;
end;
$$;

create or replace function public.suprimentos_recalcular_forecasts_ativos()
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_forecast_id uuid;
    v_total integer := 0;
begin
    for v_forecast_id in
        select id
        from public.suprimentos_forecasts
        where upper(coalesce(status, 'ATIVO')) = 'ATIVO'
        order by id
    loop
        perform public.suprimentos_recalcular_necessidades_forecast(v_forecast_id);
        v_total := v_total + 1;
    end loop;
    return v_total;
end;
$$;

create or replace function public.suprimentos_refresh_forecast_bom_after_change()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    perform public.suprimentos_recalcular_forecasts_ativos();
    return null;
end;
$$;

drop trigger if exists cadastro_bom_componentes_refresh_forecasts
    on public.cadastro_bom_componentes;
create trigger cadastro_bom_componentes_refresh_forecasts
after insert or update or delete on public.cadastro_bom_componentes
for each statement
execute function public.suprimentos_refresh_forecast_bom_after_change();

revoke all on function public.suprimentos_recalcular_forecasts_ativos() from public, anon, authenticated;
revoke all on function public.suprimentos_refresh_forecast_bom_after_change() from public, anon, authenticated;
grant execute on function public.suprimentos_recalcular_forecasts_ativos() to service_role;
