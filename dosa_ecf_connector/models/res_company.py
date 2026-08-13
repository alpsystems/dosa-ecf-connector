from odoo import fields, models

from ..services.dosa_api_client import DosaApiClient
from .dosa_common import FORMA_PAGO_SELECTION


class ResCompany(models.Model):
    _inherit = "res.company"

    dosa_base_url = fields.Char(
        string="URL base de Dosasystems", default="https://dosasystem.com")
    dosa_api_key = fields.Char(string="Dosa API Key")
    dosa_recibidas_api_key = fields.Char(
        string="Dosa API Key (producción, solo recibidas)",
        help="La consulta de facturas recibidas no tiene datos en el ambiente "
             "de pruebas de Dosasystems. Usa aquí el API Key de producción "
             "solo para GET /api/facturas/recibidas; si lo dejas vacío se usa "
             "el 'Dosa API Key' de arriba.")
    dosa_user_id = fields.Char(string="Dosa User ID")
    dosa_default_forma_pago = fields.Selection(
        FORMA_PAGO_SELECTION, string="Forma de pago por defecto (e-CF)", default="3")
    dosa_auto_emit = fields.Boolean(
        string="Emitir e-CF automáticamente al validar", default=True)
    dosa_auto_sync_recibidas = fields.Boolean(
        string="Sincronizar facturas recibidas automáticamente", default=True)
    dosa_recibidas_journal_id = fields.Many2one(
        "account.journal", string="Diario para facturas recibidas",
        domain="[('type', '=', 'purchase'), ('company_id', '=', id)]")
    dosa_recibidas_last_sync = fields.Datetime(
        string="Última sincronización de recibidas", copy=False)

    def get_dosa_api_client(self):
        self.ensure_one()
        return DosaApiClient(
            base_url=self.dosa_base_url,
            api_key=self.dosa_api_key,
            user_id=self.dosa_user_id,
        )

    def get_dosa_recibidas_api_client(self):
        self.ensure_one()
        return DosaApiClient(
            base_url=self.dosa_base_url,
            api_key=self.dosa_recibidas_api_key or self.dosa_api_key,
            user_id=self.dosa_user_id,
        )

    def _dosa_get_ecf_sequence(self, tipo_ecf):
        """Secuencia (ir.sequence) que asigna el número de eNCF para un tipo
        de e-CF en esta compañía. Cada tipo tiene su propio rango autorizado
        por la DGII y las secuencias nunca se reutilizan, aunque el envío
        falle (ver 'Gestión de Secuencias' en la documentación de Dosasystems).
        """
        self.ensure_one()
        code = f"dosa.ecf.{tipo_ecf}"
        sequence = self.env["ir.sequence"].sudo().search(
            [("code", "=", code), ("company_id", "=", self.id)], limit=1)
        if not sequence:
            raise ValueError(
                f"No hay una secuencia DGII configurada para el tipo de e-CF "
                f"'{tipo_ecf}' en la compañía {self.name}. Créala en "
                f"Ajustes > Técnico > Secuencias (código '{code}')."
            )
        return sequence

    def _dosa_next_encf(self, tipo_ecf):
        # El prefijo "E<tipo>" y el padding a 10 dígitos ya están definidos
        # en la propia secuencia (ver data/ir_sequence_data.xml), por lo que
        # next_by_id() devuelve el eNCF completo de 13 caracteres,
        # p. ej. "E310000000001".
        sequence = self._dosa_get_ecf_sequence(tipo_ecf)
        next_number = sequence.number_next_actual
        if sequence.dosa_rango_hasta and next_number > sequence.dosa_rango_hasta:
            raise ValueError(
                f"La secuencia '{sequence.name}' alcanzó el límite del rango "
                f"autorizado por la DGII (hasta {sequence.dosa_rango_hasta}). "
                f"Solicita un nuevo rango y actualízalo en Facturación DGII > "
                f"Rangos de eNCF."
            )
        if sequence.dosa_rango_desde and next_number < sequence.dosa_rango_desde:
            raise ValueError(
                f"El 'Número siguiente' de la secuencia '{sequence.name}' "
                f"({next_number}) está por debajo del rango autorizado (desde "
                f"{sequence.dosa_rango_desde}). Ajústalo en Facturación DGII > "
                f"Rangos de eNCF."
            )
        return sequence.next_by_id()
