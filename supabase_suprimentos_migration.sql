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

alter table public.suprimentos_pessoas enable row level security;
alter table public.suprimentos_processos enable row level security;
alter table public.suprimentos_regras_popup_item enable row level security;
alter table public.suprimentos_relacoes_processo_item enable row level security;
