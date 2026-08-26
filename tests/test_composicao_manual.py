import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "compras_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from composicao import (
    expandir_composicao_itens,
    expandir_composicao_manual,
    mesclar_raizes_adicionais,
)


def test_manual_root_with_bom_is_kept_before_its_components():
    componentes = {
        "30180032": [
            {"codigo": "10100001", "descricao": "Componente A", "unidade": "pc", "quantidade": 2},
            {"codigo": "10100002", "descricao": "Componente B", "unidade": "pc", "quantidade": 3},
        ]
    }
    linhas = [
        {
            "codigo": "30180032",
            "descricao": "Conjunto manual",
            "unidade": "cj",
            "qtd": "1",
            "item": "",
        }
    ]

    resultado = expandir_composicao_manual(linhas, componentes)

    assert [linha["codigo"] for linha in resultado] == ["30180032", "10100001", "10100002"]
    assert [linha["item"] for linha in resultado] == ["30180032", "30180032", "30180032"]
    assert [linha["qtd"] for linha in resultado] == ["1", 2.0, 3.0]
    assert [linha["level"] for linha in resultado] == [0, 1, 1]


def test_manual_root_with_item_equal_to_its_code_is_also_expanded():
    componentes = {"30180032": [{"codigo": "10100001", "quantidade": 2}]}

    resultado = expandir_composicao_manual(
        [{"item": "30180032", "codigo": "30180032", "qtd": 1}],
        componentes,
    )

    assert resultado == [
        {"item": "30180032", "codigo": "30180032", "descricao": "", "unidade": "", "qtd": 1, "level": 0},
        {"item": "30180032", "codigo": "10100001", "descricao": "", "unidade": "", "qtd": 2.0, "level": 1},
    ]


def test_existing_child_and_manual_item_without_bom_are_not_duplicated():
    componentes = {"30180032": [{"codigo": "10100001", "quantidade": 2}]}
    linhas = [
        {"item": "30180032", "codigo": "10100001", "qtd": 2},
        {"item": "", "codigo": "99999999", "descricao": "Item avulso", "qtd": 1},
    ]

    resultado = expandir_composicao_manual(linhas, componentes)

    assert len(resultado) == 2
    assert resultado[0]["codigo"] == "10100001"
    assert resultado[1]["item"] == "99999999"


def test_item_already_contained_in_transformation_does_not_explode_twice():
    componentes = {
        "TRANSFORMACAO": [
            {"codigo": "CJ-EXTINTOR", "quantidade": 1},
            {"codigo": "OUTRO", "quantidade": 2},
        ],
        "CJ-EXTINTOR": [
            {"codigo": "EXTINTOR", "quantidade": 1},
            {"codigo": "SUPORTE", "quantidade": 1},
        ],
    }

    resultado = expandir_composicao_itens(
        [
            {"codigo": "TRANSFORMACAO", "qtd": 1},
            {"codigo": "CJ-EXTINTOR", "qtd": 1},
        ],
        componentes,
    )

    codigos = [linha["codigo"] for linha in resultado]
    assert codigos == ["CJ-EXTINTOR", "EXTINTOR", "SUPORTE", "OUTRO"]
    assert len(codigos) == len(set(codigos))


def test_shared_leaf_from_independent_bom_branches_is_summed_once():
    componentes = {
        "TRANSFORMACAO": [
            {"codigo": "SUB-A", "quantidade": 1},
            {"codigo": "SUB-B", "quantidade": 1},
        ],
        "SUB-A": [{"codigo": "PARAFUSO", "quantidade": 2}],
        "SUB-B": [{"codigo": "PARAFUSO", "quantidade": 3}],
    }

    resultado = expandir_composicao_itens(
        [{"codigo": "TRANSFORMACAO", "qtd": 1}],
        componentes,
    )

    parafusos = [linha for linha in resultado if linha["codigo"] == "PARAFUSO"]
    assert len(parafusos) == 1
    assert parafusos[0]["qtd"] == 5.0


def test_manual_readded_root_keeps_only_one_copy_of_existing_subtree():
    componentes = {"CJ-EXTINTOR": [{"codigo": "EXTINTOR", "quantidade": 1}]}
    linhas = [
        {"item": "TRANSFORMACAO", "codigo": "CJ-EXTINTOR", "qtd": 1},
        {"item": "CJ-EXTINTOR", "codigo": "EXTINTOR", "qtd": 1},
        {"item": "CJ-EXTINTOR", "codigo": "CJ-EXTINTOR", "qtd": 1},
    ]

    resultado = expandir_composicao_manual(linhas, componentes)

    assert [linha["codigo"] for linha in resultado] == ["CJ-EXTINTOR", "EXTINTOR"]


def test_extra_root_already_covered_by_main_bom_is_not_reexploded():
    componentes = {"CJ-EXTINTOR": [{"codigo": "EXTINTOR", "quantidade": 1}]}
    base = [
        {"item": "TRANSFORMACAO", "codigo": "CJ-EXTINTOR", "qtd": 1},
        {"item": "CJ-EXTINTOR", "codigo": "EXTINTOR", "qtd": 1},
    ]

    resultado = mesclar_raizes_adicionais(
        base,
        [{"item": "TRANSFORMACAO", "codigo": "CJ-EXTINTOR", "qtd": 1}],
        componentes,
    )

    assert [linha["codigo"] for linha in resultado] == ["CJ-EXTINTOR", "EXTINTOR"]
    assert resultado[1]["qtd"] == 1


def test_independent_extra_root_sums_shared_component_in_one_line():
    componentes = {"KIT-B": [{"codigo": "PARAFUSO", "quantidade": 3}]}
    base = [{"item": "KIT-A", "codigo": "PARAFUSO", "qtd": 2}]

    resultado = mesclar_raizes_adicionais(
        base,
        [{"item": "TRANSFORMACAO", "codigo": "KIT-B", "qtd": 1}],
        componentes,
    )

    parafusos = [linha for linha in resultado if linha["codigo"] == "PARAFUSO"]
    assert len(parafusos) == 1
    assert parafusos[0]["qtd"] == 5.0
