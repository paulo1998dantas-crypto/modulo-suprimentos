import io
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


APP_DIR = Path(__file__).resolve().parents[1] / "compras_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
os.environ["SUPRIMENTOS_FILE_LOG"] = "0"

import app as app_module  # noqa: E402
from gerar_os import gerar_os_docx  # noqa: E402
from processos_os import PROCESSOS_ORDEM  # noqa: E402


class WorkOrderImportCopyTests(unittest.TestCase):
    def test_generated_os_round_trip_keeps_processes_service_and_nested_composition(self):
        data = {
            "cliente": "CLIENTE TESTE",
            "chassis": "CHASSI-123",
            "municipio": "SAO PAULO",
            "mmv": "MMV-01",
            "previsao_inicio": "2026-09-24T08:00",
            "previsao_termino": "2026-09-25T18:00",
            "descricao_servico": "INSTALACAO E ACABAMENTO",
            "processo_conjunto": "TRANSFORMACAO A",
            "obs_materiais": "OBSERVACAO DE MATERIAL",
            "obs": "OBSERVACAO FINAL",
        }
        processos = {nome: [] for nome in PROCESSOS_ORDEM}
        processos["CORTE"] = [{"atividade": "Cortar perfil", "responsavel": "PAULO"}]
        composition = [
            {"item": "SKU-OS", "codigo": "COMP-PAI", "descricao": "Conjunto pai", "qtd": 2, "unidade": "CJ", "level": 0},
            {"item": "COMP-PAI", "codigo": "COMP-FILHO", "descricao": "Componente filho", "qtd": 4, "unidade": "PC", "level": 1},
        ]
        path = gerar_os_docx(
            "OS-TESTE",
            data,
            [{"codigo": "SKU-OS", "descricao": "PRODUTO TESTE", "qtd": 2, "serie": "SERIE-9", "unidade": "UN"}],
            {},
            processos,
            composicao_resolvida=composition,
        )
        try:
            parsed = app_module.parse_os_docx_atualizado(
                SimpleNamespace(stream=io.BytesIO(Path(path).read_bytes()))
            )
        finally:
            try:
                os.remove(path)
                os.rmdir(os.path.dirname(path))
            except OSError:
                pass

        self.assertEqual("INSTALACAO E ACABAMENTO", parsed["descricao_servico"])
        self.assertEqual("TRANSFORMACAO A", parsed["processo_conjunto"])
        self.assertEqual([{"atividade": "Cortar perfil", "responsavel": "PAULO"}], parsed["processos"]["CORTE"])
        self.assertEqual("COMP-PAI", parsed["composicao"][1]["item"])
        self.assertEqual(1, parsed["composicao"][1]["level"])
        self.assertEqual("Componente filho", parsed["composicao"][1]["descricao"])
        self.assertEqual("SERIE-9", parsed["itens"][0]["serie"])

    def test_import_route_persists_source_composition_instead_of_discarding_it(self):
        parsed_source = {
            "itens": [{"codigo": "SKU-OS", "descricao": "PRODUTO", "qtd": "1", "unidade": "UN"}],
            "processos": {"CORTE": [{"atividade": "Cortar", "responsavel": "PAULO"}]},
            "composicao": [{"item": "SKU-OS", "codigo": "COMP-1", "descricao": "COMPONENTE", "qtd": "2", "unidade": "PC", "level": 0}],
        }
        salvo = {}
        file_data = {"arquivo_os_template": (io.BytesIO(b"docx"), "ordem.docx")}
        with app_module.app.test_request_context("/importar_os_documento", method="POST", data=file_data):
            with (
                patch.object(app_module, "parse_os_docx_atualizado", return_value=parsed_source),
                patch.object(app_module, "salvar_json", side_effect=lambda _path, data: salvo.update(data)),
                patch.object(app_module, "_user_scoped_file", return_value="os-import-test.json"),
            ):
                response = app_module.importar_os_documento.__wrapped__()

        self.assertEqual(302, response.status_code)
        self.assertEqual("COMP-1", salvo["composicao"][0]["codigo"])
        self.assertTrue(salvo["composicao"][0]["line_id"].startswith("os-comp"))
        self.assertEqual("PAULO", salvo["processos"]["CORTE"][0]["responsavel"])

    def test_pdf_import_ignores_process_table_headers_and_reads_responsible(self):
        texto = """ORDEM DE SERVICO
PRODUTOS:
SKU-OS PRODUTO TESTE 1 UN
COMPOSICAO:
COMP-1 > CONJUNTO PAI 2 CJ
COMP-2 > > COMPONENTE FILHO 4 PC
PROCESSOS DE PRODUCAO ELETRICA 1:
OK/NOK | OK/NOK | RESPONSAVEL | DATA | HORA INICIO | HORA FIM
_________ | ______________________ | _______________
# | ATIVIDADE | ATIVIDADE
1 Instalar chicote
RESPONSÁVEL: CARLOS
"""
        with patch.object(app_module, "_extract_pdf_text", return_value=texto):
            parsed = app_module.parse_os_pdf(SimpleNamespace(stream=io.BytesIO(b"pdf")))

        self.assertEqual("Instalar chicote", parsed["processos"]["ELÉTRICA 1"][0]["atividade"])
        self.assertEqual("CARLOS", parsed["processos"]["ELÉTRICA 1"][0]["responsavel"])
        self.assertEqual(2, parsed["composicao"][1]["level"])
        self.assertEqual("COMP-1", parsed["composicao"][1]["item"])
        self.assertEqual("COMPONENTE FILHO", parsed["composicao"][1]["descricao"])


if __name__ == "__main__":
    unittest.main()
