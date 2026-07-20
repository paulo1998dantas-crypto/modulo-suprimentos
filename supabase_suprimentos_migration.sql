-- ModuloSuprimentos Supabase migration
-- Safe for the shared production database: creates only suprimentos_* objects.

create table if not exists public.suprimentos_pessoas (
    id bigserial primary key,
    identificador text not null unique,
    data_registro timestamptz null,
    pessoa_fisica boolean not null default false,
    nome_fantasia text not null default '',
    razao_social text not null default '',
    cnpj_cpf text not null default '',
    codigo_identificador_unico text not null default '',
    rg text not null default '',
    ie text not null default '',
    logradouro text not null default '',
    logradouro_numero text not null default '',
    complemento text not null default '',
    bairro text not null default '',
    cidade text not null default '',
    codigo_municipio text not null default '',
    pais text not null default '',
    codigo_pais text not null default '',
    cep text not null default '',
    uf text not null default '',
    codigo_uf text not null default '',
    telefone text not null default '',
    whatsapp text not null default '',
    celular text not null default '',
    email text not null default '',
    site text not null default '',
    cliente boolean not null default false,
    fornecedor boolean not null default false,
    colaborador boolean not null default false,
    transportadora boolean not null default false,
    pessoa_grupo text not null default '',
    vendedor_padrao text not null default '',
    categoria text not null default '',
    tabela_preco text not null default '',
    observacoes text not null default '',
    limite_credito numeric not null default 0,
    periodicidade_venda_compra_dias numeric not null default 0,
    validation text not null default '',
    valor_minimo_compra numeric not null default 0,
    data_nascimento_fundacao date null,
    payload jsonb not null default '{}'::jsonb,
    search_text text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.suprimentos_processos (
    id bigserial primary key,
    conjunto text not null default 'PADRAO',
    processo text not null,
    ordem integer not null default 0,
    atividade text not null,
    responsavel text not null default '',
    search_text text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.suprimentos_regras_popup_item (
    rule_id text primary key,
    gatilho text not null,
    opcoes jsonb not null default '[]'::jsonb,
    quantidade numeric not null default 1,
    quantidade_editavel boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.suprimentos_relacoes_processo_item (
    item_codigo text primary key,
    processos jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.suprimentos_documentos (
    id bigserial primary key,
    tipo text not null,
    numero text not null,
    data_criacao date not null default current_date,
    status text not null default 'emitido',
    submit_token text null,
    criado_por text not null default '',
    atualizado_por text not null default '',
    dados jsonb not null default '{}'::jsonb,
    itens jsonb not null default '[]'::jsonb,
    processos jsonb not null default '{}'::jsonb,
    componentes jsonb not null default '{}'::jsonb,
    composicao jsonb not null default '[]'::jsonb,
    valor_total numeric not null default 0,
    itens_count integer not null default 0,
    search_text text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.suprimentos_documentos
    add column if not exists status text not null default 'emitido',
    add column if not exists submit_token text null,
    add column if not exists criado_por text not null default '',
    add column if not exists atualizado_por text not null default '';

do $$
begin
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

create index if not exists suprimentos_pessoas_nome_idx
    on public.suprimentos_pessoas (nome_fantasia);

create index if not exists suprimentos_pessoas_documento_idx
    on public.suprimentos_pessoas (cnpj_cpf);

create index if not exists suprimentos_pessoas_tipo_idx
    on public.suprimentos_pessoas (cliente, fornecedor, colaborador, transportadora);

create index if not exists suprimentos_pessoas_search_idx
    on public.suprimentos_pessoas using gin (to_tsvector('simple', search_text));

create index if not exists suprimentos_processos_conjunto_idx
    on public.suprimentos_processos (conjunto, processo, ordem);

create index if not exists suprimentos_processos_search_idx
    on public.suprimentos_processos using gin (to_tsvector('simple', search_text));

create index if not exists suprimentos_regras_gatilho_idx
    on public.suprimentos_regras_popup_item (gatilho);

create index if not exists suprimentos_relacoes_item_idx
    on public.suprimentos_relacoes_processo_item (item_codigo);

create index if not exists suprimentos_documentos_tipo_data_idx
    on public.suprimentos_documentos (tipo, data_criacao desc);

create index if not exists suprimentos_documentos_numero_idx
    on public.suprimentos_documentos (numero);

create index if not exists suprimentos_documentos_search_idx
    on public.suprimentos_documentos using gin (to_tsvector('simple', search_text));

create or replace function public.suprimentos_touch_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists suprimentos_pessoas_touch_updated_at on public.suprimentos_pessoas;
create trigger suprimentos_pessoas_touch_updated_at
before update on public.suprimentos_pessoas
for each row execute function public.suprimentos_touch_updated_at();

drop trigger if exists suprimentos_processos_touch_updated_at on public.suprimentos_processos;
create trigger suprimentos_processos_touch_updated_at
before update on public.suprimentos_processos
for each row execute function public.suprimentos_touch_updated_at();

drop trigger if exists suprimentos_regras_touch_updated_at on public.suprimentos_regras_popup_item;
create trigger suprimentos_regras_touch_updated_at
before update on public.suprimentos_regras_popup_item
for each row execute function public.suprimentos_touch_updated_at();

drop trigger if exists suprimentos_relacoes_touch_updated_at on public.suprimentos_relacoes_processo_item;
create trigger suprimentos_relacoes_touch_updated_at
before update on public.suprimentos_relacoes_processo_item
for each row execute function public.suprimentos_touch_updated_at();

drop trigger if exists suprimentos_documentos_touch_updated_at on public.suprimentos_documentos;
create trigger suprimentos_documentos_touch_updated_at
before update on public.suprimentos_documentos
for each row execute function public.suprimentos_touch_updated_at();

alter table public.suprimentos_pessoas enable row level security;
alter table public.suprimentos_processos enable row level security;
alter table public.suprimentos_regras_popup_item enable row level security;
alter table public.suprimentos_relacoes_processo_item enable row level security;
alter table public.suprimentos_documentos enable row level security;
alter table public.suprimentos_documento_contadores enable row level security;

-- O aplicativo acessa estas tabelas exclusivamente no servidor com a service role.
-- Grants explicitos mantem compatibilidade com projetos que nao expoem novas tabelas automaticamente.
grant select, insert, update, delete on table
    public.suprimentos_pessoas,
    public.suprimentos_processos,
    public.suprimentos_regras_popup_item,
    public.suprimentos_relacoes_processo_item,
    public.suprimentos_documentos,
    public.suprimentos_documento_contadores
to service_role;

grant usage, select on all sequences in schema public to service_role;
revoke all on function public.suprimentos_proximo_numero(text) from public, anon, authenticated;
grant execute on function public.suprimentos_proximo_numero(text) to service_role;
