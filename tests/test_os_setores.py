import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "compras_app"))

from os_setores import (
    enriquecer_composicao,
    filtrar_linhas_preparacao,
    propagar_setor_preparacao,
)


class PreparacaoFilterTests(unittest.TestCase):
    def test_preparacao_nao_explode_insumo_de_conjunto_nao_preparacao(self):
        catalogo = {
            "30180004": {
                "descricao": "CJ REVESTIMENTO E/S/J TB",
                "grupo": "30 - CONJUNTO / KIT",
                "categoria": "18 - REVESTIMENTO",
                "unidade": "cj",
            },
            "10440013": {
                "descricao": "REFORCO U ACO GALVANIZADO FIXACAO TETO E/S/J",
                "grupo": "10 - INSUMO",
                "categoria": "44 - REFORCO",
                "unidade": "pc",
            },
            "30140027": {
                "descricao": "CJ PISO CN 12 MM E/S/J TB",
                "grupo": "30 - CONJUNTO / KIT",
                "categoria": "14 - PISO",
                "unidade": "cj",
            },
        }
        linhas = [
            {
                "item": "40340049",
                "codigo": "30180004",
                "descricao": "CJ REVESTIMENTO E/S/J TB",
                "unidade": "cj",
                "qtd": 1,
                "level": 0,
            },
            {
                "item": "30180004",
                "codigo": "10440013",
                "descricao": "REFORCO U ACO GALVANIZADO FIXACAO TETO E/S/J",
                "unidade": "pc",
                "qtd": 1,
                "level": 1,
            },
            {
                "item": "40340049",
                "codigo": "30140027",
                "descricao": "CJ PISO CN 12 MM E/S/J TB",
                "unidade": "cj",
                "qtd": 1,
                "level": 0,
            },
            {
                "item": "40340049",
                "codigo": "10440013",
                "descricao": "REFORCO U ACO GALVANIZADO FIXACAO TETO E/S/J",
                "unidade": "pc",
                "qtd": 1,
                "level": 0,
            },
        ]

        preparacao = filtrar_linhas_preparacao(
            propagar_setor_preparacao(
                enriquecer_composicao(linhas, catalogo),
                catalogo,
                {"30180004": [{}], "30140027": [{}]},
            )
        )

        codigos = [linha["codigo"] for linha in preparacao]
        self.assertNotIn("30180004", codigos)
        self.assertIn("30140027", codigos)
        self.assertEqual(codigos.count("10440013"), 1)


if __name__ == "__main__":
    unittest.main()
