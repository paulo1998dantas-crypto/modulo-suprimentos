from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "compras_app"))

from gerar_os import _resumir_composicao_os_completa


def test_os_completa_mantem_conjunto_e_oculta_seus_niveis_internos():
    componentes = {
        "TRANSFORMACAO": [{"codigo": "CJ-BANCO"}, {"codigo": "ITEM-SOLTO"}],
        "CJ-BANCO": [{"codigo": "BANCO-1"}],
        "BANCO-1": [{"codigo": "ESPUMA-1"}],
    }
    composicao = [
        {"codigo": "CJ-BANCO", "descricao": "Conjunto banco", "level": 0},
        {"codigo": "BANCO-1", "descricao": "Banco unitário", "level": 1},
        {"codigo": "ESPUMA-1", "descricao": "Espuma", "level": 2},
        {"codigo": "ITEM-SOLTO", "descricao": "Item solto", "level": 0},
    ]

    resultado = _resumir_composicao_os_completa(composicao, componentes)

    assert [linha["codigo"] for linha in resultado] == ["CJ-BANCO", "ITEM-SOLTO"]


def test_os_completa_explode_item_principal_ate_encontrar_subconjunto():
    componentes = {
        "ITEM-PRINCIPAL": [{"codigo": "PECA-1"}, {"codigo": "CJ-VIDRO"}],
        "CJ-VIDRO": [{"codigo": "VIDRO-1"}],
    }
    composicao = [
        {"codigo": "PECA-1", "descricao": "Peça direta", "level": 0},
        {"codigo": "CJ-VIDRO", "descricao": "Conjunto vidro", "level": 0},
        {"codigo": "VIDRO-1", "descricao": "Vidro interno", "level": 1},
    ]

    resultado = _resumir_composicao_os_completa(composicao, componentes)

    assert [linha["codigo"] for linha in resultado] == ["PECA-1", "CJ-VIDRO"]
