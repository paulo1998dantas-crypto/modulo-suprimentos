-- Itens e necessidades explodidas do Forecast.
-- Aditiva: nao altera estoque, saldos, movimentos, O.C., O.S. ou B.O.M. existentes.
-- Cada Forecast passa a representar uma demanda planejada multi-SKU. A explosao
-- e uma fotografia de planejamento para MRP; nao gera reserva ou baixa fisica.

begin;
set local lock_timeout = 5000;
set local statement_timeout = 60000;

create table if not exists public.suprimentos_forecast_itens (
    id uuid primary key default gen_random_uuid(),
    forecast_id uuid not null references public.suprimentos_forecasts(id) on delete restrict,
    numero_linha integer not null check (numero_linha > 0),
    sku_id integer not null references public.skus(id) on delete restrict,
    sku_codigo text not null,
    descricao text not null default '',
    unidade text not null default '',
    quantidade_por_veiculo numeric not null check (quantidade_por_veiculo > 0),
    quantidade_planejada numeric not null check (quantidade_planejada > 0),
    possui_bom boolean not null default false,
    bom_explodida_em timestamptz null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint suprimentos_forecast_itens_linha_uk unique (forecast_id, numero_linha),
    constraint suprimentos_forecast_itens_sku_uk unique (forecast_id, sku_id)
);

create table if not exists public.suprimentos_forecast_necessidades (
    id uuid primary key default gen_random_uuid(),
    forecast_id uuid not null references public.suprimentos_forecasts(id) on delete restrict,
    forecast_item_id uuid not null references public.suprimentos_forecast_itens(id) on delete restrict,
    sku_id integer not null references public.skus(id) on delete restrict,
    sku_codigo text not null,
    descricao text not null default '',
    unidade text not null default '',
    quantidade_planejada numeric not null check (quantidade_planejada > 0),
    nivel_maximo integer not null default 0 check (nivel_maximo >= 0),
    origem text not null check (origem in ('SKU_SEM_BOM', 'BOM')),
    caminho_bom text[] not null default array[]::text[],
    created_at timestamptz not null default now(),
    constraint suprimentos_forecast_necessidades_uk unique (forecast_item_id, sku_id)
);

create index if not exists suprimentos_forecast_itens_forecast_idx
    on public.suprimentos_forecast_itens(forecast_id, numero_linha);
create index if not exists suprimentos_forecast_necessidades_forecast_idx
    on public.suprimentos_forecast_necessidades(forecast_id, sku_id);

create or replace function public.suprimentos_recalcular_necessidades_forecast(p_forecast_id uuid)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
begin
    delete from public.suprimentos_forecast_necessidades
     where forecast_id = p_forecast_id;

    -- Cada SKU sem B.O.M. e uma necessidade direta. Para conjuntos, a CTE
    -- percorre os componentes ate as folhas e agrega componentes repetidos.
    with recursive exploded as (
        select
            fi.id as forecast_item_id,
            fi.forecast_id,
            fi.sku_id as root_sku_id,
            fi.sku_id,
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
            bc.component_sku_id,
            e.quantidade_planejada * bc.quantidade,
            e.nivel + 1,
            e.caminho_ids || bc.component_sku_id,
            e.caminho_codigos || component.sku
        from exploded e
        join public.bom_components bc on bc.item_sku_id = e.sku_id
        join public.skus component on component.id = bc.component_sku_id and component.active is true
        where e.nivel < 12
          and not (bc.component_sku_id = any(e.caminho_ids))
    ), leaves as (
        select e.*
        from exploded e
        where not exists (
            select 1
            from public.bom_components bc
            join public.skus child on child.id = bc.component_sku_id and child.active is true
            where bc.item_sku_id = e.sku_id
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
               select 1 from public.bom_components bc where bc.item_sku_id = fi.sku_id
           ),
           bom_explodida_em = now(),
           updated_at = now()
     where fi.forecast_id = p_forecast_id;
end;
$$;

create or replace function public.suprimentos_substituir_itens_forecast(
    p_forecast_id uuid,
    p_itens jsonb
)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
declare
    item jsonb;
    v_sku public.skus%rowtype;
    v_qtd_por_veiculo numeric;
    v_numero_linha integer := 0;
    v_quantidade_veiculos numeric;
begin
    if jsonb_typeof(coalesce(p_itens, '[]'::jsonb)) <> 'array'
       or jsonb_array_length(coalesce(p_itens, '[]'::jsonb)) = 0 then
        raise exception 'Informe ao menos um SKU na demanda planejada.' using errcode = '22023';
    end if;

    select quantidade_planejada into v_quantidade_veiculos
      from public.suprimentos_forecasts
     where id = p_forecast_id
     for update;
    if not found then
        raise exception 'Forecast nao encontrado.' using errcode = 'P0002';
    end if;

    delete from public.suprimentos_forecast_necessidades where forecast_id = p_forecast_id;
    delete from public.suprimentos_forecast_itens where forecast_id = p_forecast_id;

    for item in select value from jsonb_array_elements(p_itens) loop
        v_numero_linha := v_numero_linha + 1;
        begin
            v_qtd_por_veiculo := nullif(item ->> 'quantidade_por_veiculo', '')::numeric;
        exception when invalid_text_representation then
            raise exception 'Quantidade invalida no item %.', v_numero_linha using errcode = '22023';
        end;
        if v_qtd_por_veiculo is null or v_qtd_por_veiculo <= 0 then
            raise exception 'Quantidade do SKU na linha % deve ser maior que zero.', v_numero_linha using errcode = '22023';
        end if;

        select * into v_sku
          from public.skus
         where upper(sku) = upper(coalesce(item ->> 'sku_codigo', ''))
           and active is true;
        if not found then
            raise exception 'SKU ativo nao encontrado: %.', coalesce(item ->> 'sku_codigo', '') using errcode = '22023';
        end if;

        insert into public.suprimentos_forecast_itens (
            forecast_id, numero_linha, sku_id, sku_codigo, descricao, unidade,
            quantidade_por_veiculo, quantidade_planejada
        ) values (
            p_forecast_id, v_numero_linha, v_sku.id, v_sku.sku, v_sku.descricao,
            coalesce(v_sku.unidade, ''), v_qtd_por_veiculo,
            v_quantidade_veiculos * v_qtd_por_veiculo
        );
    end loop;

    perform public.suprimentos_recalcular_necessidades_forecast(p_forecast_id);

    update public.suprimentos_forecasts f
       set produto_planejado_sku = fi.sku_codigo,
           produto_planejado_descricao = fi.descricao
      from (
          select sku_codigo, descricao
          from public.suprimentos_forecast_itens
          where forecast_id = p_forecast_id
          order by numero_linha
          limit 1
      ) fi
     where f.id = p_forecast_id;
end;
$$;

create or replace function public.suprimentos_criar_forecast_com_itens(p_forecast jsonb)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_forecast public.suprimentos_forecasts%rowtype;
    v_numero bigint;
    v_key text := nullif(btrim(coalesce(p_forecast ->> 'idempotency_key', '')), '');
begin
    if v_key is null then
        raise exception 'Chave de idempotencia do Forecast e obrigatoria.' using errcode = '22023';
    end if;
    select * into v_forecast from public.suprimentos_forecasts where idempotency_key = v_key;
    if found then
        return to_jsonb(v_forecast);
    end if;

    update public.suprimentos_forecast_contador
       set ultimo_numero = ultimo_numero + 1, updated_at = now()
     where singleton = true
     returning ultimo_numero into v_numero;
    if v_numero is null then
        raise exception 'Contador de Forecast nao configurado.' using errcode = 'P0001';
    end if;

    insert into public.suprimentos_forecasts (
        numero_forecast, codigo, tipo_demanda, status, proposta_numero, cliente_id, cliente_nome,
        vendedor, mercado, data_confirmacao, data_prevista_chegada, data_entrega_prevista,
        quantidade_planejada, unidade, tipo_servico, tipo_veiculo, linha, transformacao_codigo,
        transformacao, probabilidade, origem, observacoes, dados_planejamento, vehicle_entry_id,
        work_order_id, convertido_at, convertido_por, idempotency_key, criado_por, atualizado_por
    ) values (
        v_numero, format('FCT-%s', lpad(v_numero::text, 5, '0')),
        coalesce(nullif(p_forecast ->> 'tipo_demanda', ''), 'PREVISAO_DEMANDA'),
        coalesce(nullif(p_forecast ->> 'status', ''), 'ATIVO'),
        coalesce(p_forecast ->> 'proposta_numero', ''), nullif(p_forecast ->> 'cliente_id', ''),
        coalesce(p_forecast ->> 'cliente_nome', ''), coalesce(p_forecast ->> 'vendedor', ''),
        coalesce(p_forecast ->> 'mercado', ''), nullif(p_forecast ->> 'data_confirmacao', '')::date,
        nullif(p_forecast ->> 'data_prevista_chegada', '')::date,
        nullif(p_forecast ->> 'data_entrega_prevista', '')::date,
        coalesce(nullif(p_forecast ->> 'quantidade_planejada', '')::numeric, 1),
        coalesce(nullif(p_forecast ->> 'unidade', ''), 'VEICULO'),
        coalesce(nullif(p_forecast ->> 'tipo_servico', ''), 'TRANSFORMACAO'),
        coalesce(p_forecast ->> 'tipo_veiculo', ''), coalesce(p_forecast ->> 'linha', ''),
        coalesce(p_forecast ->> 'transformacao_codigo', ''), coalesce(p_forecast ->> 'transformacao', ''),
        coalesce(nullif(p_forecast ->> 'probabilidade', '')::smallint, 100),
        coalesce(p_forecast ->> 'origem', ''), coalesce(p_forecast ->> 'observacoes', ''),
        coalesce(p_forecast -> 'dados_planejamento', '{}'::jsonb),
        nullif(p_forecast ->> 'vehicle_entry_id', '')::uuid, nullif(p_forecast ->> 'work_order_id', '')::uuid,
        nullif(p_forecast ->> 'convertido_at', '')::timestamptz, nullif(p_forecast ->> 'convertido_por', ''),
        v_key, coalesce(p_forecast ->> 'criado_por', ''), coalesce(p_forecast ->> 'atualizado_por', '')
    ) returning * into v_forecast;

    perform public.suprimentos_substituir_itens_forecast(v_forecast.id, p_forecast -> 'itens_planejados');
    select * into v_forecast from public.suprimentos_forecasts where id = v_forecast.id;
    return to_jsonb(v_forecast);
end;
$$;

create or replace function public.suprimentos_atualizar_forecast_com_itens(
    p_forecast_id uuid,
    p_expected_version integer,
    p_forecast jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_forecast public.suprimentos_forecasts%rowtype;
begin
    update public.suprimentos_forecasts
       set tipo_demanda = coalesce(nullif(p_forecast ->> 'tipo_demanda', ''), tipo_demanda),
           status = coalesce(nullif(p_forecast ->> 'status', ''), status),
           proposta_numero = coalesce(p_forecast ->> 'proposta_numero', ''),
           cliente_id = nullif(p_forecast ->> 'cliente_id', ''),
           cliente_nome = coalesce(p_forecast ->> 'cliente_nome', ''),
           vendedor = coalesce(p_forecast ->> 'vendedor', ''),
           mercado = coalesce(p_forecast ->> 'mercado', ''),
           data_confirmacao = nullif(p_forecast ->> 'data_confirmacao', '')::date,
           data_prevista_chegada = nullif(p_forecast ->> 'data_prevista_chegada', '')::date,
           data_entrega_prevista = nullif(p_forecast ->> 'data_entrega_prevista', '')::date,
           quantidade_planejada = coalesce(nullif(p_forecast ->> 'quantidade_planejada', '')::numeric, quantidade_planejada),
           unidade = coalesce(nullif(p_forecast ->> 'unidade', ''), unidade),
           tipo_servico = coalesce(nullif(p_forecast ->> 'tipo_servico', ''), tipo_servico),
           tipo_veiculo = coalesce(p_forecast ->> 'tipo_veiculo', ''),
           linha = coalesce(p_forecast ->> 'linha', ''),
           transformacao_codigo = coalesce(p_forecast ->> 'transformacao_codigo', ''),
           transformacao = coalesce(p_forecast ->> 'transformacao', ''),
           probabilidade = coalesce(nullif(p_forecast ->> 'probabilidade', '')::smallint, probabilidade),
           origem = coalesce(p_forecast ->> 'origem', ''),
           observacoes = coalesce(p_forecast ->> 'observacoes', ''),
           dados_planejamento = coalesce(p_forecast -> 'dados_planejamento', dados_planejamento),
           vehicle_entry_id = nullif(p_forecast ->> 'vehicle_entry_id', '')::uuid,
           work_order_id = nullif(p_forecast ->> 'work_order_id', '')::uuid,
           convertido_at = nullif(p_forecast ->> 'convertido_at', '')::timestamptz,
           convertido_por = nullif(p_forecast ->> 'convertido_por', ''),
           atualizado_por = coalesce(p_forecast ->> 'atualizado_por', atualizado_por)
     where id = p_forecast_id
       and (p_expected_version is null or version = p_expected_version)
    returning * into v_forecast;
    if not found then
        raise exception 'O Forecast foi alterado por outro usuario. Atualize a tela e tente novamente.' using errcode = 'P0001';
    end if;

    perform public.suprimentos_substituir_itens_forecast(v_forecast.id, p_forecast -> 'itens_planejados');
    select * into v_forecast from public.suprimentos_forecasts where id = v_forecast.id;
    return to_jsonb(v_forecast);
end;
$$;

alter table public.suprimentos_forecast_itens enable row level security;
alter table public.suprimentos_forecast_necessidades enable row level security;
revoke all on table public.suprimentos_forecast_itens, public.suprimentos_forecast_necessidades from anon, authenticated;
grant select, insert, update, delete on table public.suprimentos_forecast_itens, public.suprimentos_forecast_necessidades to service_role;
revoke all on function public.suprimentos_recalcular_necessidades_forecast(uuid) from public, anon, authenticated;
revoke all on function public.suprimentos_substituir_itens_forecast(uuid, jsonb) from public, anon, authenticated;
revoke all on function public.suprimentos_criar_forecast_com_itens(jsonb) from public, anon, authenticated;
revoke all on function public.suprimentos_atualizar_forecast_com_itens(uuid, integer, jsonb) from public, anon, authenticated;
grant execute on function public.suprimentos_recalcular_necessidades_forecast(uuid) to service_role;
grant execute on function public.suprimentos_substituir_itens_forecast(uuid, jsonb) to service_role;
grant execute on function public.suprimentos_criar_forecast_com_itens(jsonb) to service_role;
grant execute on function public.suprimentos_atualizar_forecast_com_itens(uuid, integer, jsonb) to service_role;

commit;

-- Rollback operacional seguro: SUPRIMENTOS_FORECAST_ENABLED=0 no Render.
-- Nao remover as tabelas apos gravar previsoes; elas constituem o historico do MRP.
