from odoo import fields, models


class IrSequence(models.Model):
    _inherit = "ir.sequence"

    dosa_fecha_vencimiento = fields.Date(
        string="Fecha de vencimiento (DGII)",
        help="Fecha límite autorizada por la DGII para este rango de eNCF. "
             "Requerida por todos los tipos de e-CF excepto E32 y E34.")
    dosa_rango_desde = fields.Integer(
        string="Rango autorizado desde",
        help="Primer número del rango de eNCF que la DGII autorizó para este "
             "tipo. Solo informativo/de validación: el 'Número siguiente' "
             "sigue siendo el que realmente controla el próximo eNCF.")
    dosa_rango_hasta = fields.Integer(
        string="Rango autorizado hasta",
        help="Último número del rango de eNCF que la DGII autorizó para este "
             "tipo. Si el 'Número siguiente' lo supera, el conector bloquea "
             "la emisión con un error claro en vez de usar un eNCF fuera de "
             "rango.")
