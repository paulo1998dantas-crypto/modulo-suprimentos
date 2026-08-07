-- Consumo parcial de Forecast por documento de O.S.
-- Aditiva: nao altera Forecasts, O.S., estoque, empenhos, baixas ou movimentos existentes.
-- Aplicar antes de publicar a versao que habilita a conversao documental de Forecast.
-- O saldo e protegido pela funcao transacional abaixo; nao calcule o abatimento somente no frontend.

begin;
set local lock_timeout = 5000;
set local statement_timeout = 60000;

create table if not exists public.suprimentos_forecast_consumos_os (
    id uuid primary key default gen_random_uuid(),
    forecast_id uuid not null
        references public.suprimentos_forecasts(id)
        on delete restrict,
    -- Nao ha FK para suprimentos_documentos de proposito: um documento excluido
    -- preserva este registro como auditoria cancelada, sem apagar o historico do Forecast.
    documento_os_id bigint not null check (documento_os_id > 0),
    quantidade numeric not null check (quantidade > 0),
    status text not null default 'ATIVO'
        check (status in ('ATIVO', 'CANCELADO')),
    idempotency_key text not null unique,
    criado_por text not null default '',
    cancelado_por text null,
    motivo_cancelamento text null,
    created_at timestamptz not null default now(),
    cancelled_at timestamptz null,
    constraint suprimentos_forecast_consumos_os_documento_unique unique (documento_os_id)
);

create index if not exists suprimentos_forecast_consumos_os_ativos_idx
    on public.suprimentos_forecast_consumos_os(forecast_id, created_at desc)
    where status = 'ATIVO';

create or replace function public.suprimentos_consumir_forecast_em_os_documento(
    p_forecast_id uuid,
    p_documento_os_id bigint,
    p_quantidade numeric,
    p_idempotency_key text,
    p_actor text default ''
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_forecast public.suprimentos_forecasts%rowtype;
    v_existente public.suprimentos_forecast_consumos_os%rowtype;
    v_consumido numeric := 0;
    v_saldo numeric := 0;
    v_novo_consumo_id uuid;
begin
    if p_forecast_id is null or p_documento_os_id is null or p_documento_os_id <= 0 then
        raise exception 'Forecast e documento de O.S. sao obrigatorios.';
    end if;
    if p_quantidade is null or p_quantidade <= 0 then
        raise exception 'A quantidade a converter deve ser maior que zero.';
    end if;
    if nullif(btrim(coalesce(p_idempotency_key, '')), '') is null then
        raise exception 'A chave de idempotencia e obrigatoria.';
    end if;

    -- Serializa clique duplo / retentativa do mesmo documento antes de consultar
    -- a tabela (uma linha ainda inexistente nao poderia receber FOR UPDATE).
    perform pg_catalog.pg_advisory_xact_lock(p_documento_os_id);

    -- A mesma O.S. nao pode consumir dois Forecasts diferentes. A verificacao
    -- vem antes do saldo para permitir retentativas seguras da mesma emissao.
    select *
      into v_existente
      from public.suprimentos_forecast_consumos_os
     where documento_os_id = p_documento_os_id
     for update;

    if found then
        if v_existente.forecast_id <> p_forecast_id then
            raise exception 'Esta O.S. documental ja esta vinculada a outro Forecast.';
        end if;
        if v_existente.status <> 'ATIVO' then
            raise exception 'O consumo deste documento foi cancelado; emita uma nova O.S. ou reabra o consumo de forma controlada.';
        end if;
        if abs(v_existente.quantidade - p_quantidade) > 0.000001 then
            raise exception 'Esta O.S. ja consumiu % unidade(s) deste Forecast; a quantidade nao pode ser alterada apos a emissao.', v_existente.quantidade;
        end if;
        select coalesce(sum(quantidade), 0)
          into v_consumido
          from public.suprimentos_forecast_consumos_os
         where forecast_id = p_forecast_id
           and status = 'ATIVO';
        select quantidade_planejada - v_consumido
          into v_saldo
          from public.suprimentos_forecasts
         where id = p_forecast_id;
        return jsonb_build_object(
            'id', v_existente.id,
            'forecast_id', p_forecast_id,
            'documento_os_id', p_documento_os_id,
            'quantidade', v_existente.quantidade,
            'quantidade_consumida', v_consumido,
            'quantidade_saldo', greatest(coalesce(v_saldo, 0), 0),
            'idempotente', true
        );
    end if;

    -- Lock por Forecast: dois compradores nao conseguem ultrapassar o saldo
    -- ao emitirem documentos ao mesmo tempo.
    select *
      into v_forecast
      from public.suprimentos_forecasts
     where id = p_forecast_id
     for update;

    if not found then
        raise exception 'Forecast nao encontrado.';
    end if;
    if v_forecast.status <> 'ATIVO' then
        raise exception 'Somente Forecasts ativos podem ser convertidos em O.S. documental.';
    end if;
    if v_forecast.tipo_demanda <> 'AGUARDANDO_CHEGADA' then
        raise exception 'A conversao documental e permitida apenas para Forecast aguardando chegada.';
    end if;

    select coalesce(sum(quantidade), 0)
      into v_consumido
      from public.suprimentos_forecast_consumos_os
     where forecast_id = p_forecast_id
       and status = 'ATIVO';
    v_saldo := v_forecast.quantidade_planejada - v_consumido;

    if p_quantidade > v_saldo + 0.000001 then
        raise exception 'Quantidade acima do saldo do Forecast. Saldo disponivel: %.', greatest(v_saldo, 0);
    end if;

    insert into public.suprimentos_forecast_consumos_os (
        forecast_id,
        documento_os_id,
        quantidade,
        idempotency_key,
        criado_por
    )
    values (
        p_forecast_id,
        p_documento_os_id,
        p_quantidade,
        p_idempotency_key,
        coalesce(p_actor, '')
    )
    returning id into v_novo_consumo_id;

    return jsonb_build_object(
        'id', v_novo_consumo_id,
        'forecast_id', p_forecast_id,
        'documento_os_id', p_documento_os_id,
        'quantidade', p_quantidade,
        'quantidade_consumida', v_consumido + p_quantidade,
        'quantidade_saldo', greatest(v_saldo - p_quantidade, 0),
        'idempotente', false
    );
end;
$$;

create or replace function public.suprimentos_cancelar_consumo_forecast_em_os_documento(
    p_documento_os_id bigint,
    p_actor text default '',
    p_motivo text default ''
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_consumo public.suprimentos_forecast_consumos_os%rowtype;
begin
    select *
      into v_consumo
      from public.suprimentos_forecast_consumos_os
     where documento_os_id = p_documento_os_id
     for update;

    if not found then
        return jsonb_build_object('cancelado', false, 'motivo', 'SEM_CONSUMO');
    end if;
    if v_consumo.status = 'CANCELADO' then
        return jsonb_build_object('cancelado', false, 'motivo', 'JA_CANCELADO', 'id', v_consumo.id);
    end if;

    update public.suprimentos_forecast_consumos_os
       set status = 'CANCELADO',
           cancelado_por = coalesce(p_actor, ''),
           motivo_cancelamento = nullif(btrim(coalesce(p_motivo, '')), ''),
           cancelled_at = now()
     where id = v_consumo.id;

    return jsonb_build_object(
        'cancelado', true,
        'id', v_consumo.id,
        'forecast_id', v_consumo.forecast_id,
        'quantidade_liberada', v_consumo.quantidade
    );
end;
$$;

-- Exclusao so e permitida para cenarios que ainda nao geraram efeito
-- operacional ou documental.  A operacao fica atomica: ou remove cabecalho,
-- itens e necessidades juntos, ou nao remove nada.
create or replace function public.suprimentos_excluir_forecast_sem_historico(
    p_forecast_id uuid,
    p_expected_version integer default null,
    p_actor text default ''
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_forecast public.suprimentos_forecasts%rowtype;
begin
    select *
      into v_forecast
      from public.suprimentos_forecasts
     where id = p_forecast_id
     for update;

    if not found then
        raise exception 'Forecast nao encontrado.' using errcode = 'P0002';
    end if;

    if p_expected_version is not null and v_forecast.version <> p_expected_version then
        raise exception 'O Forecast foi alterado por outro usuario. Atualize a tela e tente novamente.' using errcode = '40001';
    end if;

    if v_forecast.vehicle_entry_id is not null
       or v_forecast.work_order_id is not null
       or v_forecast.convertido_at is not null
       or v_forecast.status = 'CONVERTIDO' then
        raise exception 'Este Forecast ja foi convertido em entrada/O.S. e nao pode ser excluido. Preserve o historico e use Cancelar quando aplicavel.' using errcode = '55000';
    end if;

    if exists (
        select 1
          from public.suprimentos_forecast_consumos_os consumo
         where consumo.forecast_id = p_forecast_id
    ) then
        raise exception 'Este Forecast ja possui O.S. documental vinculada e nao pode ser excluido. Cancele o Forecast para preservar a rastreabilidade.' using errcode = '55000';
    end if;

    delete from public.suprimentos_forecast_necessidades
     where forecast_id = p_forecast_id;
    delete from public.suprimentos_forecast_itens
     where forecast_id = p_forecast_id;
    delete from public.suprimentos_forecasts
     where id = p_forecast_id;

    return jsonb_build_object(
        'excluido', true,
        'forecast_id', p_forecast_id,
        'codigo', v_forecast.codigo,
        'excluido_por', coalesce(p_actor, '')
    );
end;
$$;

alter table public.suprimentos_forecast_consumos_os enable row level security;

revoke all on table public.suprimentos_forecast_consumos_os from public, anon, authenticated;
grant select, insert, update, delete on table public.suprimentos_forecast_consumos_os to service_role;

revoke all on function public.suprimentos_consumir_forecast_em_os_documento(uuid, bigint, numeric, text, text)
    from public, anon, authenticated;
revoke all on function public.suprimentos_cancelar_consumo_forecast_em_os_documento(bigint, text, text)
    from public, anon, authenticated;
revoke all on function public.suprimentos_excluir_forecast_sem_historico(uuid, integer, text)
    from public, anon, authenticated;
grant execute on function public.suprimentos_consumir_forecast_em_os_documento(uuid, bigint, numeric, text, text)
    to service_role;
grant execute on function public.suprimentos_cancelar_consumo_forecast_em_os_documento(bigint, text, text)
    to service_role;
grant execute on function public.suprimentos_excluir_forecast_sem_historico(uuid, integer, text)
    to service_role;

commit;

-- Rollback operacional seguro: defina SUPRIMENTOS_FORECAST_ENABLED=0 para ocultar
-- o fluxo. Nao remova a tabela em producao: ela e a trilha de auditoria dos
-- documentos ja emitidos. Para desfazer uma emissao, cancele a O.S.; o saldo
-- volta a ficar disponivel sem afetar estoque ou MRP fisico.
