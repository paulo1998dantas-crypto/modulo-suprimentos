-- Forecast de demanda para MRP e planejamento comercial.
-- Aditiva: nao altera O.S., veiculos, estoque, movimentos ou documentos existentes.
-- Aplicar uma unica vez no Supabase compartilhado, antes do deploy do modulo.

begin;
set local lock_timeout = 5000;
set local statement_timeout = 60000;

create table if not exists public.suprimentos_forecast_contador (
    singleton boolean primary key default true check (singleton),
    ultimo_numero bigint not null default 0 check (ultimo_numero >= 0),
    updated_at timestamptz not null default now()
);

insert into public.suprimentos_forecast_contador(singleton, ultimo_numero)
values (true, 0)
on conflict (singleton) do nothing;

create table if not exists public.suprimentos_forecasts (
    id uuid primary key default gen_random_uuid(),
    numero_forecast bigint not null unique,
    codigo text not null unique,
    tipo_demanda text not null,
    status text not null default 'ATIVO',
    proposta_numero text not null default '',
    cliente_id text null,
    cliente_nome text not null default '',
    vendedor text not null default '',
    mercado text not null default '',
    data_confirmacao date null,
    data_prevista_chegada date null,
    data_entrega_prevista date null,
    quantidade_planejada numeric not null default 1 check (quantidade_planejada > 0),
    unidade text not null default 'VEICULO',
    tipo_servico text not null default 'TRANSFORMACAO',
    tipo_veiculo text not null default '',
    linha text not null default '',
    transformacao_codigo text not null default '',
    transformacao text not null default '',
    produto_planejado_sku text not null default '',
    produto_planejado_descricao text not null default '',
    probabilidade smallint not null default 100 check (probabilidade between 0 and 100),
    origem text not null default '',
    observacoes text not null default '',
    dados_planejamento jsonb not null default '{}'::jsonb,
    vehicle_entry_id uuid null,
    work_order_id uuid null,
    convertido_at timestamptz null,
    convertido_por text null,
    idempotency_key text null unique,
    criado_por text not null default '',
    atualizado_por text not null default '',
    version integer not null default 1 check (version > 0),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint suprimentos_forecasts_tipo_check
        check (tipo_demanda in ('AGUARDANDO_CHEGADA', 'PREVISAO_DEMANDA')),
    constraint suprimentos_forecasts_status_check
        check (status in ('ATIVO', 'CONVERTIDO', 'CANCELADO')),
    constraint suprimentos_forecasts_confirmado_proposta_check
        check (
            tipo_demanda <> 'AGUARDANDO_CHEGADA'
            or nullif(btrim(proposta_numero), '') is not null
        ),
    constraint suprimentos_forecasts_convertido_check
        check (
            status <> 'CONVERTIDO'
            or vehicle_entry_id is not null
        ),
    constraint suprimentos_forecasts_vehicle_entry_fk
        foreign key (vehicle_entry_id)
        references public.erp_vehicle_entries(id)
        on delete restrict,
    constraint suprimentos_forecasts_work_order_fk
        foreign key (work_order_id)
        references public.erp_work_orders(id)
        on delete restrict
);

create index if not exists suprimentos_forecasts_planejamento_idx
    on public.suprimentos_forecasts(tipo_demanda, status, data_entrega_prevista, data_prevista_chegada);

create index if not exists suprimentos_forecasts_cliente_idx
    on public.suprimentos_forecasts(cliente_nome);

create index if not exists suprimentos_forecasts_produto_idx
    on public.suprimentos_forecasts(produto_planejado_sku)
    where produto_planejado_sku <> '';

create or replace function public.suprimentos_proximo_numero_forecast()
returns bigint
language sql
security invoker
set search_path = ''
as $$
    update public.suprimentos_forecast_contador
       set ultimo_numero = ultimo_numero + 1,
           updated_at = now()
     where singleton = true
    returning ultimo_numero;
$$;

create or replace function public.suprimentos_forecast_touch_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    new.updated_at = now();
    new.version = old.version + 1;
    return new;
end;
$$;

drop trigger if exists suprimentos_forecasts_touch_updated_at on public.suprimentos_forecasts;
create trigger suprimentos_forecasts_touch_updated_at
before update on public.suprimentos_forecasts
for each row execute function public.suprimentos_forecast_touch_updated_at();

alter table public.suprimentos_forecast_contador enable row level security;
alter table public.suprimentos_forecasts enable row level security;

revoke all on table public.suprimentos_forecast_contador,
                    public.suprimentos_forecasts
from anon, authenticated;
grant select, insert, update, delete on table
    public.suprimentos_forecast_contador,
    public.suprimentos_forecasts
to service_role;

revoke all on function public.suprimentos_proximo_numero_forecast() from public, anon, authenticated;
grant execute on function public.suprimentos_proximo_numero_forecast() to service_role;
revoke all on function public.suprimentos_forecast_touch_updated_at() from public, anon, authenticated;
grant execute on function public.suprimentos_forecast_touch_updated_at() to service_role;

commit;

-- Rollback operacional seguro: defina SUPRIMENTOS_FORECAST_ENABLED=0 no Render.
-- Nao remova a tabela em producao depois de gravar forecasts, pois ela preserva
-- o historico de planejamento e os vinculos para entradas/O.S. convertidas.
