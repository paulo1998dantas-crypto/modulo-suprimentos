import sys
import unittest
from pathlib import Path

from docx import Document


APP_DIR = Path(__file__).resolve().parents[1] / "compras_app"
sys.path.insert(0, str(APP_DIR))

from gerar_op import build_production_order_docx  # noqa: E402


class ProductionOrderDocumentTest(unittest.TestCase):
    def test_human_quantity_hides_internal_three_decimal_scale(self):
        output = build_production_order_docx(
            {
                "numero_op": "OP-TESTE",
                "status": "LIBERADA",
                "quantidade_planejada": "1.000",
                "unidade": "PC",
                "target_sku": "FINAL",
                "target_descricao": "Produto final",
                "inputs": [
                    {
                        "sku": "ORIGEM",
                        "descricao": "Produto origem",
                        "quantidade_planejada": "1.000",
                        "unidade": "PC",
                    }
                ],
            }
        )
        document = Document(output)
        text = "\n".join(cell.text for table in document.tables for row in table.rows for cell in row.cells)
        self.assertIn("Quantidade:\n1 PC", text)
        self.assertNotIn("1.000 PC", text)


if __name__ == "__main__":
    unittest.main()
