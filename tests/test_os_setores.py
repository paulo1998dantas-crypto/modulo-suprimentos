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
    def test_preparacao_restringe_a_trilho_piso_reforco_e_cj_bancos(self):
        catalogo = {
            "30240032": {
                "descricao": "ACESSORIO CJ EXTINTOR COM SUPORTE ABC 4KG",
                "grupo": "30 - CONJUNTO / KIT",
                "categoria": "24 - ACESSORIOS",
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
            "10280050": {
                "descricao": "MP PERFIL ALUMINIO TRILHO BANCO JI",
                "grupo": "10 - INSUMO",
                "categoria": "28 - MATERIA PRIMA",
                "unidade": "br",
            },
        }
        linhas = [
            {
                "item": "40340049",
                "codigo": "30240032",
                "descricao": "ACESSORIO CJ EXTINTOR COM SUPORTE ABC 4KG",
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
            {
                "item": "40340049",
                "codigo": "10280050",
                "descricao": "MP PERFIL ALUMINIO TRILHO BANCO JI",
                "unidade": "br",
                "qtd": 2,
                "level": 0,
            },
        ]

        preparacao = filtrar_linhas_preparacao(
            propagar_setor_preparacao(
                enriquecer_composicao(linhas, catalogo),
                catalogo,
                {"30240032": [{}], "30140027": [{}]},
            )
        )

        codigos = [linha["codigo"] for linha in preparacao]
        self.assertNotIn("30240032", codigos)
        self.assertIn("30140027", codigos)
        self.assertIn("10440013", codigos)
        self.assertIn("10280050", codigos)

    def test_preparacao_mostra_cj_bancos_sem_explodir_composicao(self):
        catalogo = {
            "30200036": {
                "descricao": "CJ BANCOS REC LE 3,3 EXECUTIVO",
                "grupo": "30 - CONJUNTO / KIT",
                "categoria": "20 - BANCOS",
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
                "item": "30200036",
                "codigo": "10440013",
                "descricao": "REFORCO U ACO GALVANIZADO FIXACAO TETO E/S/J",
                "unidade": "pc",
                "qtd": 2,
                "level": 1,
            },
            {
                "item": "30200036",
                "codigo": "10280050",
                "descricao": "MP PERFIL ALUMINIO TRILHO BANCO JI",
                "unidade": "br",
                "qtd": 1,
                "level": 1,
            },
        ]

        preparacao = filtrar_linhas_preparacao(
            propagar_setor_preparacao(
                enriquecer_composicao(linhas, catalogo),
                catalogo,
                {"30200036": [{}]},
            )
        )
        preparacao.extend(
            linhas_layout_preparacao(
                [
                    {
                        "codigo": "30200036",
                        "descricao": "CJ BANCOS REC LE 3,3 EXECUTIVO",
                        "qtd": 1,
                    }
                ],
                catalogo,
            )
        )

        codigos = [linha["codigo"] for linha in preparacao]
        self.assertEqual(codigos, ["30200036"])
        self.assertTrue(preparacao[0].get("ocultar_composicao_preparacao"))

    def test_preparacao_referencia_cj_piso_e_nao_forca_3024(self):
        catalogo = {
            "30140027": {
                "descricao": "CJ PISO CN 12 MM E/S/J TB LG BRIGHT",
                "grupo": "30 - CONJUNTO / KIT",
                "categoria": "14 - PISO",
                "unidade": "cj",
            },
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
                    "codigo": "30140027",
                    "descricao": "CJ PISO CN 12 MM E/S/J TB LG BRIGHT",
                    "qtd": 1,
                },
                {
                    "codigo": "30240062",
                    "descricao": "CJ MOVEL LATERAL PRETO E/S/J C-CLASS 1 VAO LE",
                    "qtd": 1,
                },
            ],
            catalogo,
        )

        self.assertEqual([linha["codigo"] for linha in linhas], ["30140027"])
        self.assertEqual(linhas[0]["regra_preparacao"], "PISO")

    def test_isolamento_e_acabamento_pp_cj_sao_preparacao(self):
        catalogo = {
            "30160002": {
                "descricao": "CJ ISOLAMENTO TERMICO E/S/J",
                "unidade": "cj",
                "grupo": "30 - CONJUNTO / KIT",
                "categoria": "16 - ISOLAMENTO",
            },
            "10520005": {
                "descricao": "ACESSORIO ACABAMENTO PLASTICO PARAFUSO",
                "unidade": "pc",
                "grupo": "10 - INSUMO",
                "categoria": "52 - ACABAMENTOS",
            },
            "30520001": {
                "descricao": "CJ ACABAMENTO INTERNO E/S/J",
                "unidade": "cj",
                "grupo": "30 - CONJUNTO / KIT",
                "categoria": "52 - ACABAMENTOS",
            },
        }
        linhas = enriquecer_composicao(
            [
                {
                    "item": "40340049",
                    "codigo": "30160002",
                    "descricao": "CJ ISOLAMENTO TERMICO E/S/J",
                    "qtd": 1,
                },
                {
                    "item": "40340049",
                    "codigo": "10520005",
                    "descricao": "ACESSORIO ACABAMENTO PLASTICO PARAFUSO",
                    "qtd": 4,
                },
                {
                    "item": "40340049",
                    "codigo": "30520001",
                    "descricao": "CJ ACABAMENTO INTERNO E/S/J",
                    "qtd": 1,
                },
            ],
            catalogo,
        )

        preparacao = filtrar_linhas_preparacao(propagar_setor_preparacao(linhas, catalogo, {}))
        codigos = [linha["codigo"] for linha in preparacao]
        self.assertIn("30160002", codigos)
        self.assertIn("30520001", codigos)
        self.assertNotIn("10520005", codigos)

    def test_cj_teto_revestimento_vai_para_preparacao(self):
        catalogo = {
            "30180023": {
                "descricao": "CJ TETO E/S/J VELUDO PRETO SALAO/CABINE/COLUNA B/COLUNA A/ACESSORIOS ORI TETO CABINE",
                "unidade": "cj",
                "grupo": "30 - CONJUNTO / KIT",
                "categoria": "18 - REVESTIMENTO",
            },
        }
        linhas = enriquecer_composicao(
            [
                {
                    "item": "30180025",
                    "codigo": "30180023",
                    "descricao": "CJ TETO E/S/J VELUDO PRETO SALAO/CABINE/COLUNA B/COLUNA A/ACESSORIOS ORI TETO CABINE",
                    "qtd": 1,
                },
            ],
            catalogo,
        )

        preparacao = filtrar_linhas_preparacao(propagar_setor_preparacao(linhas, catalogo, {}))
        self.assertEqual([linha["codigo"] for linha in preparacao], ["30180023"])
        self.assertEqual(preparacao[0]["regra_preparacao"], "CJ_TETO")

        layout = linhas_layout_preparacao(
            [{"codigo": "30180023", "qtd": 1}],
            catalogo,
        )
        self.assertEqual([linha["codigo"] for linha in layout], ["30180023"])
        self.assertEqual(layout[0]["regra_preparacao"], "CJ_TETO")

    def test_destino_manual_pode_incluir_ou_retirar_linha_da_preparacao(self):
        linhas = [
            {
                "item": "40340049",
                "codigo": "10240001",
                "descricao": "ACESSORIO ADESIVO IDENTIFICACAO",
                "setor": "PREPARACAO",
                "setor_manual": True,
            },
            {
                "item": "40340049",
                "codigo": "30160002",
                "descricao": "CJ ISOLAMENTO TERMICO",
                "setor": "EXPEDICAO",
                "setor_manual": True,
            },
        ]

        preparacao = filtrar_linhas_preparacao(propagar_setor_preparacao(linhas, {}, {}))
        self.assertEqual([linha["codigo"] for linha in preparacao], ["10240001"])


if __name__ == "__main__":
    unittest.main()
