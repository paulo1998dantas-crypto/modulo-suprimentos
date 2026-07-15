import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "compras_app"))

from os_setores import (
    enriquecer_composicao,
    filtrar_linhas_preparacao,
    linhas_layout_preparacao,
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

    def test_preparacao_mostra_conjunto_3024_sem_explodir_composicao(self):
        catalogo = {
            "30240062": {
                "descricao": "CJ MOVEL LATERAL PRETO E/S/J C-CLASS 1 VAO LE",
                "grupo": "30 - CONJUNTO / KIT",
                "categoria": "24 - ACESSORIO",
                "unidade": "cj",
            },
            "10440013": {
                "descricao": "REFORCO U ACO GALVANIZADO FIXACAO TETO E/S/J",
                "grupo": "10 - INSUMO",
                "categoria": "44 - REFORCO",
                "unidade": "pc",
            },
        }
        linhas = [
            {
                "item": "40340049",
                "codigo": "30240062",
                "descricao": "CJ MOVEL LATERAL PRETO E/S/J C-CLASS 1 VAO LE",
                "unidade": "cj",
                "qtd": 1,
                "level": 0,
            },
            {
                "item": "30240062",
                "codigo": "10440013",
                "descricao": "REFORCO U ACO GALVANIZADO FIXACAO TETO E/S/J",
                "unidade": "pc",
                "qtd": 2,
                "level": 1,
            },
        ]

        preparacao = filtrar_linhas_preparacao(
            propagar_setor_preparacao(
                enriquecer_composicao(linhas, catalogo),
                catalogo,
                {"30240062": [{}]},
            )
        )

        codigos = [linha["codigo"] for linha in preparacao]
        self.assertEqual(codigos, ["30240062"])
        self.assertTrue(preparacao[0].get("layout_preparacao"))
        self.assertEqual(preparacao[0].get("setor"), "PREPARACAO")

    def test_preparacao_inclui_3024_da_lista_original(self):
        catalogo = {
            "30240062": {
                "descricao": "CJ MOVEL LATERAL PRETO E/S/J C-CLASS 1 VAO LE",
                "grupo": "30 - CONJUNTO / KIT",
                "categoria": "24 - ACESSORIO",
                "unidade": "cj",
            },
        }
        linhas = linhas_layout_preparacao(
            [
                {
                    "codigo": "30240062",
                    "descricao": "CJ MOVEL LATERAL PRETO E/S/J C-CLASS 1 VAO LE",
                    "qtd": 1,
                },
                {"codigo": "30180004", "descricao": "CJ REVESTIMENTO E/S/J TB", "qtd": 1},
            ],
            catalogo,
        )

        self.assertEqual([linha["codigo"] for linha in linhas], ["30240062"])
        self.assertEqual(linhas[0]["unidade"], "cj")
        self.assertEqual(linhas[0]["setor"], "PREPARACAO")


if __name__ == "__main__":
    unittest.main()
