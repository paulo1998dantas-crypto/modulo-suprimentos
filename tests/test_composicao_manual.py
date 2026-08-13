import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "compras_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from composicao import expandir_composicao_manual


def test_manual_root_with_bom_is_replaced_by_its_components():
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

    assert [linha["codigo"] for linha in resultado] == ["10100001", "10100002"]
    assert [linha["item"] for linha in resultado] == ["30180032", "30180032"]
    assert [linha["qtd"] for linha in resultado] == [2.0, 3.0]


def test_manual_root_with_item_equal_to_its_code_is_also_expanded():
    componentes = {"30180032": [{"codigo": "10100001", "quantidade": 2}]}

    resultado = expandir_composicao_manual(
        [{"item": "30180032", "codigo": "30180032", "qtd": 1}],
        componentes,
    )

    assert resultado == [
        {"item": "30180032", "codigo": "10100001", "descricao": "", "unidade": "", "qtd": 2.0, "level": 0}
    ]


def test_existing_child_and_manual_item_without_bom_are_not_duplicated():
    componentes = {"30180032": [{"codigo": "10100001", "quantidade": 2}]}
    linhas = [
        {"item": "30180032", "codigo": "10100001", "qtd": 2},
        {"item": "", "codigo": "99999999", "descricao": "Item avulso", "qtd": 1},
    ]

    resultado = expandir_composicao_manual(linhas, componentes)

    assert len(resultado) == 2
    assert resultado[0]["item"] == "30180032"
    assert resultado[1]["item"] == "99999999"
