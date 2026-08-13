# Catálogos DGII usados por Dosasystems (ver README de
# https://github.com/alapaix13/DosaInvoicecloud-Documentation)

TIPO_ECF_SELECTION = [
    ("31", "E31 - Factura de Crédito Fiscal"),
    ("32", "E32 - Factura de Consumo"),
    ("33", "E33 - Nota de Débito"),
    ("34", "E34 - Nota de Crédito"),
    ("46", "E46 - Exportaciones"),
]

# Tipos que este conector es capaz de emitir automáticamente desde una
# factura/NC de Odoo. E33/41/43/45/47 quedan fuera del alcance inicial.
TIPO_ECF_EMITIBLES = ("31", "32", "46")
TIPO_ECF_NOTA_CREDITO = "34"
TIPO_ECF_EXPORTACION = "46"

# Tipos que requieren fechaVencimientoSecuencia (todos excepto E32 y E34,
# ver README de Dosasystems).
TIPO_ECF_REQUIERE_VENCIMIENTO = ("31", "46")

# Tabla oficial DGII de códigos de modificación para Notas de Crédito/Débito
# (Formato e-CF v1.0 / Informe Técnico e-CF, sección NotaDesdeFactura).
CODIGO_MODIFICACION_SELECTION = [
    ("1", "1 - Anulación total del e-CF"),
    ("2", "2 - Corrección de texto (no afecta montos)"),
    ("3", "3 - Corrección de montos (devolución, descuento, bonificación)"),
    ("4", "4 - Reemplazo de e-CF emitido en contingencia"),
    ("5", "5 - Referencia a Factura de Consumo Electrónica"),
]

FORMA_PAGO_SELECTION = [
    ("1", "Efectivo"),
    ("2", "Cheque"),
    ("3", "Transferencia"),
    ("4", "Tarjeta de Crédito"),
    ("5", "Tarjeta de Débito"),
    ("6", "Permuta"),
    ("7", "Nota de Crédito"),
    ("8", "Bonos o Certificados de Regalo"),
    ("9", "Otras Formas de Pago"),
]

UNIDAD_MEDIDA_DEFAULT = 1  # "Unidad" — catálogo completo en la documentación de Dosasystems

ESTADO_SELECTION = [
    ("no_enviado", "No enviado"),
    ("enviado", "Enviado"),
    ("aceptado", "Aceptado"),
    ("aceptado_observaciones", "Aceptado con Observaciones"),
    ("aceptado_condicional", "Aceptado Condicional"),
    ("rechazado", "Rechazado"),
    ("error", "Error de comunicación"),
]

# codigo de respuesta de Dosasystems -> estado interno. Se mantiene la
# granularidad exacta de la DGII (1 y 2 NO son lo mismo: 2 = aceptado pero
# con mensajes de advertencia que hay que revisar) en vez de colapsarlos.
CODIGO_ESTADO_MAP = {
    "0": "rechazado",
    "1": "aceptado",
    "2": "aceptado_observaciones",
    "4": "aceptado_condicional",
}

ITBIS_RATES = (18.0, 16.0, 0.0)  # I1, I2, I3
