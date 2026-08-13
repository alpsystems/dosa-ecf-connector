from odoo import fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestDosaEcfHelpers(AccountTestInvoicingCommon):
    """Pruebas unitarias de las funciones puras del conector (sin llamadas
    a la API de Dosasystems): cálculo de totales para E46/Norma 07-07 y
    limpieza de la URL de verificación del QR."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tax_construccion = cls.env["account.tax"].create({
            "name": "ITBIS Construcción 07-07 test",
            "amount": 1.8,
            "amount_type": "percent",
            "type_tax_use": "sale",
        })
        cls.partner_us = cls.env["res.partner"].create({
            "name": "Foreign Buyer LLC",
            "country_id": cls.env.ref("base.us").id,
            "vat": "TAX123456",
        })

    def _create_invoice(self, partner, price, tax=None):
        return self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": partner.id,
            "invoice_date": fields.Date.today(),
            "invoice_line_ids": [(0, 0, {
                "name": "Línea de prueba",
                "quantity": 1,
                "price_unit": price,
                "account_id": self.company_data["default_account_revenue"].id,
                "tax_ids": [(6, 0, tax.ids if tax else [])],
            })],
        })

    def test_norma_0707_backcalculates_reduced_base(self):
        move = self._create_invoice(self.partner_a, 1_000_000.0, self.tax_construccion)
        move.dosa_norma_0707 = True
        totales, _otra_moneda = move._dosa_compute_totales()
        self.assertAlmostEqual(float(totales["montoGravadoTotal"]), 100_000.0, places=2)
        self.assertAlmostEqual(float(totales["montoExento"]), 900_000.0, places=2)
        self.assertAlmostEqual(float(totales["totalITBIS"]), 18_000.0, places=2)

    def test_e46_export_uses_gravado_i3_only(self):
        move = self._create_invoice(self.partner_us, 25_000.0)
        totales, _otra_moneda = move._dosa_compute_totales(tipo_ecf="46")
        self.assertNotIn("montoExento", totales)
        self.assertNotIn("montoGravadoI1", totales)
        self.assertNotIn("montoImpuestoAdicional", totales)
        self.assertAlmostEqual(float(totales["montoGravadoI3"]), 25_000.0, places=2)

    def test_clean_qr_url_strips_broken_rnc_comprador(self):
        dirty = ("https://ecf.dgii.gov.do/testecf/consultatimbre"
                 "?RNCEmisor=133306001&RncComprador=N/A&ENCF=E460000000007")
        cleaned = self.env["account.move"]._dosa_clean_qr_url(dirty)
        self.assertNotIn("RncComprador", cleaned)
        self.assertIn("ENCF=E460000000007", cleaned)

    def test_clean_qr_url_noop_when_already_clean(self):
        clean = ("https://ecf.dgii.gov.do/testecf/consultatimbre"
                 "?RNCEmisor=133306001&RncComprador=131219772&ENCF=E310000065506")
        self.assertEqual(self.env["account.move"]._dosa_clean_qr_url(clean), clean)

    def test_clean_vat_strips_non_digits(self):
        self.assertEqual(self.env["account.move"]._dosa_clean_vat("1-33-30600-1"), "133306001")
