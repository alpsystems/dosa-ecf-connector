from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    dosa_base_url = fields.Char(
        related="company_id.dosa_base_url", readonly=False,
        string="URL base de Dosasystems")
    dosa_api_key = fields.Char(
        related="company_id.dosa_api_key", readonly=False, string="Dosa API Key")
    dosa_recibidas_api_key = fields.Char(
        related="company_id.dosa_recibidas_api_key", readonly=False,
        string="Dosa API Key (producción, solo recibidas)")
    dosa_user_id = fields.Char(
        related="company_id.dosa_user_id", readonly=False, string="Dosa User ID")
    dosa_default_forma_pago = fields.Selection(
        related="company_id.dosa_default_forma_pago", readonly=False,
        string="Forma de pago por defecto (e-CF)")
    dosa_auto_emit = fields.Boolean(
        related="company_id.dosa_auto_emit", readonly=False,
        string="Emitir e-CF automáticamente al validar")
    dosa_auto_sync_recibidas = fields.Boolean(
        related="company_id.dosa_auto_sync_recibidas", readonly=False,
        string="Sincronizar facturas recibidas automáticamente")
    dosa_recibidas_journal_id = fields.Many2one(
        related="company_id.dosa_recibidas_journal_id", readonly=False,
        string="Diario para facturas recibidas")
    dosa_recibidas_last_sync = fields.Datetime(
        related="company_id.dosa_recibidas_last_sync", string="Última sincronización de recibidas")
