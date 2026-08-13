{
    "name": "Dosa e-CF Connector",
    "version": "19.0.1.0.0",
    "summary": "Emite e-CF a la DGII vía Dosa Invoice Cloud y contabiliza automáticamente las facturas recibidas",
    "description": """
Conector entre Odoo y Dosa Invoice Cloud (dosasystem.com) para el régimen de
Comprobantes Fiscales Electrónicos (e-CF) de la DGII, República Dominicana.

- Emite facturas de venta (E31/E32), notas de crédito (E34) y
  exportaciones (E46, con bloque OtraMoneda) desde account.move hacia la
  API de Dosasystems.
- Soporte para Norma 07-07 (sector construcción): recalcula la base
  gravada de ITBIS a partir del impuesto real de la factura.
- Sincroniza periódicamente las facturas electrónicas recibidas
  (GET /api/facturas/recibidas) y las contabiliza automáticamente como
  facturas de proveedor en Odoo.
- Inserta el QR de verificación de la DGII en el reporte de factura
  nativo de Odoo, sin depender de ningún formato personalizado.
""",
    "author": "DOSA Technologies",
    "website": "https://dosasystem.com",
    "support": "soporte@dosasystem.com",
    "license": "LGPL-3",
    "category": "Accounting/Localizations",
    "images": ["static/description/banner.png"],
    "depends": ["account"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "data/ir_cron_data.xml",
        "views/res_company_views.xml",
        "views/res_config_settings_views.xml",
        "views/dosa_ecf_sequence_views.xml",
        "views/account_move_views.xml",
        "views/report_invoice_dosa.xml",
        "views/dosa_menus.xml",
    ],
    "installable": True,
    "application": False,
}
