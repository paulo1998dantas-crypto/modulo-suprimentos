import unicodedata


PROCESSOS_OS = [
    {
        "nome": "CORTE",
        "key": "corte",
        "titulo": "Corte",
        "aliases": [
            "CORTE",
            "10 - CORTE",
        ],
    },
    {
        "nome": "AR CONDICIONADO",
        "key": "ar",
        "titulo": "Ar Condicionado",
        "aliases": [
            "AR CONDICIONADO",
            "20 - AR CONDICIONADO",
        ],
    },
    {
        "nome": "PREPARAÇÃO DE PEÇAS",
        "key": "preparacao",
        "titulo": "Preparação de Peças",
        "aliases": [
            "PREPARAÇÃO DE PEÇAS",
            "PREPARACAO DE PECAS",
            "PREPARAÃ‡ÃƒO DE PEÃ‡AS",
            "PREPARAÃƒâ€¡ÃƒÆ’O DE PEÃƒâ€¡AS",
            "30 - PREPARAÇÃO DE PEÇAS",
            "30 - PREPARACAO DE PECAS",
            "30 - PREPARAÃ‡ÃƒO DE PEÃ‡AS",
        ],
    },
    {
        "nome": "ELÉTRICA 1",
        "key": "eletrica1",
        "titulo": "Elétrica 1",
        "aliases": [
            "ELÉTRICA 1",
            "ELETRICA 1",
            "ELÃ‰TRICA 1",
            "ELÃƒâ€°TRICA 1",
            "40 - ELÉTRICA 1",
            "40 - ELETRICA 1",
            "40 - ELÃ‰TRICA 1",
        ],
    },
    {
        "nome": "ISOLAMENTO",
        "key": "desmontagem",
        "titulo": "Isolamento",
        "aliases": [
            "ISOLAMENTO",
            "DESMONTAGEM",
            "DESMONTAGEM (ISOLAMENTO)",
            "DESMONTAGEM E ISOLAMENTO",
            "50 - ISOLAMENTO",
            "50 - DESMONTAGEM",
            "50 - DESMONTAGEM (ISOLAMENTO)",
        ],
    },
    {
        "nome": "REVESTIMENTO 1",
        "key": "revestimento1",
        "titulo": "Revestimento 1",
        "aliases": [
            "REVESTIMENTO 1",
            "REVESTIMENTO",
            "60 - REVESTIMENTO 1",
            "60 - REVESTIMENTO",
        ],
    },
    {
        "nome": "REVESTIMENTO 2",
        "key": "revestimento2",
        "titulo": "Revestimento 2",
        "aliases": [
            "REVESTIMENTO 2",
            "70 - REVESTIMENTO 2",
        ],
    },
    {
        "nome": "ELÉTRICA 2",
        "key": "eletrica2",
        "titulo": "Elétrica 2",
        "aliases": [
            "ELÉTRICA 2",
            "ELETRICA 2",
            "ELÃ‰TRICA 2",
            "ELÃƒâ€°TRICA 2",
            "ELÉTRICA",
            "ELETRICA",
            "80 - ELÉTRICA 2",
            "80 - ELETRICA 2",
            "80 - ELÃ‰TRICA 2",
        ],
    },
    {
        "nome": "BANCO",
        "key": "banco",
        "titulo": "Banco",
        "aliases": [
            "BANCO",
            "BANCOS",
            "100 - BANCO",
            "100 - BANCOS",
        ],
    },
    {
        "nome": "LIMPEZA/LIBERAÇÃO",
        "key": "limpeza",
        "titulo": "Limpeza/Liberação",
        "aliases": [
            "LIMPEZA/LIBERAÇÃO",
            "LIMPEZA/LIBERACAO",
            "LIMPEZA/LIBERAÃ‡ÃƒO",
            "LIMPEZA/LIBERAÃƒâ€¡ÃƒÆ’O",
            "90 - LIMPEZA/LIBERAÇÃO",
            "90 - LIMPEZA/LIBERACAO",
            "90 - LIMPEZA/LIBERAÃ‡ÃƒO",
        ],
    },
    {
        "nome": "ACESSÃ“RIOS",
        "key": "acessorios",
        "titulo": "AcessÃ³rios",
        "aliases": [
            "ACESSÃ“RIOS",
            "ACESSORIOS",
            "ACESSÃƒâ€°RIOS",
            "ACESSÃƒÆ’Ã¢â‚¬Â°RIOS",
            "95 - ACESSÃ“RIOS",
            "95 - ACESSORIOS",
            "95 - ACESSÃƒâ€°RIOS",
        ],
    },
]

PROCESSOS_ORDEM = [processo["nome"] for processo in PROCESSOS_OS]
PROCESSOS_POR_KEY = {processo["key"]: processo["nome"] for processo in PROCESSOS_OS}


def normalizar_texto(valor):
    texto = str(valor or "").strip().upper()
    if not texto:
        return ""
    texto = texto.replace("â€“", "-").replace("â€”", "-").replace("_", " ")
    texto = " ".join(texto.split())
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(ch for ch in texto if not unicodedata.combining(ch))


_ALIAS_TO_PROCESSO = {}
_ALIASES_ORDENADOS = []
for processo in PROCESSOS_OS:
    for alias in processo["aliases"]:
        alias_norm = normalizar_texto(alias)
        if not alias_norm:
            continue
        _ALIAS_TO_PROCESSO[alias_norm] = processo["nome"]
        _ALIASES_ORDENADOS.append((alias_norm, processo["nome"]))

_ALIASES_ORDENADOS.sort(key=lambda item: len(item[0]), reverse=True)


def normalizar_nome_processo(nome):
    nome_limpo = str(nome or "").strip()
    if not nome_limpo:
        return ""
    nome_norm = normalizar_texto(nome_limpo)
    processo = _ALIAS_TO_PROCESSO.get(nome_norm)
    if processo:
        return processo
    processo = identificar_nome_processo(nome_limpo)
    if processo:
        return processo
    return nome_limpo


def identificar_nome_processo(texto):
    texto_norm = normalizar_texto(texto)
    if not texto_norm:
        return None
    for alias_norm, nome in _ALIASES_ORDENADOS:
        if alias_norm and alias_norm in texto_norm:
            return nome
    return None
