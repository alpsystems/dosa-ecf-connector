import base64
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from urllib.parse import quote

from werkzeug.urls import url_quote_plus

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

from ..services.dosa_api_client import DosaApiError
from .dosa_common import (
    CODIGO_ESTADO_MAP,
    CODIGO_MODIFICACION_SELECTION,
    ESTADO_SELECTION,
    TIPO_ECF_EXPORTACION,
    TIPO_ECF_NOTA_CREDITO,
    TIPO_ECF_REQUIERE_VENCIMIENTO,
    TIPO_ECF_SELECTION,
    UNIDAD_MEDIDA_DEFAULT,
)

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    # -- Emisión (facturas y NC propias) ---------------------------------
    dosa_tipo_ecf = fields.Selection(
        TIPO_ECF_SELECTION, string="Tipo de e-CF",
        compute="_compute_dosa_tipo_ecf", store=True, readonly=False, copy=False)
    dosa_encf = fields.Char(string="eNCF", readonly=True, copy=False)
    dosa_norma_0707 = fields.Boolean(
        string="Aplica Norma 07-07 (construcción)", copy=False,
        help="Sector construcción: el ITBIS se declara al 18%, pero calculado "
             "sobre una base reducida en vez del 100% del valor facturado. El "
             "conector infiere esa base a partir del ITBIS que Odoo ya calculó "
             "en la factura (ITBIS / 18%), así que el e-CF siempre cuadra con "
             "la contabilidad real, sin asumir un porcentaje fijo a ciegas.")
    dosa_codigo_modificacion = fields.Selection(
        CODIGO_MODIFICACION_SELECTION, string="Código de modificación (DGII)",
        compute="_compute_dosa_codigo_modificacion", store=True, readonly=False, copy=False,
        help="Motivo de la Nota de Crédito/Débito según la tabla oficial de la "
             "DGII. Se sugiere automáticamente (1=anulación total si el monto "
             "coincide con el de la factura original, 3=corrección de montos "
             "si es parcial) pero puede ajustarse antes de emitir.")

    # -- Recepción (facturas de proveedor importadas) ---------------------
    dosa_recibida_encf = fields.Char(
        string="eNCF recibido", readonly=True, copy=False)
    dosa_rnc_emisor_recibido = fields.Char(
        string="RNC emisor (recibida)", readonly=True, copy=False)
    dosa_is_received = fields.Boolean(
        string="Importada de Dosasystems", default=False, copy=False)

    # -- Estado común -------------------------------------------------------
    dosa_track_id = fields.Char(string="Track ID DGII", readonly=True, copy=False)
    dosa_estado = fields.Selection(
        ESTADO_SELECTION, string="Estado DGII", default="no_enviado",
        readonly=True, copy=False)
    dosa_codigo_seguridad = fields.Char(
        string="Código de seguridad", readonly=True, copy=False)
    dosa_url_qr = fields.Char(string="URL de consulta DGII", readonly=True, copy=False)
    dosa_fecha_firma = fields.Datetime(
        string="Fecha de firma DGII", readonly=True, copy=False)
    dosa_mensajes = fields.Text(
        string="Mensajes DGII", readonly=True, copy=False)
    dosa_check_error = fields.Text(
        string="Error al consultar estado", readonly=True, copy=False,
        help="Último error de comunicación al llamar ConsultaEstado. Se limpia "
             "en la siguiente consulta exitosa; no afecta el Estado DGII, que "
             "solo cambia con una respuesta válida de Dosasystems.")
    dosa_request_payload = fields.Text(
        string="JSON enviado/recibido a Dosasystems", readonly=True, copy=False)
    dosa_electronica_id = fields.Integer(
        string="ID interno Dosasystems", readonly=True, copy=False,
        help="'facturaElectronicaID' en Dosasystems. Se resuelve automáticamente "
             "la primera vez que se descarga el XML/JSON o se reimprime el PDF "
             "de este e-CF desde el Monitor de Emisiones.")

    _dosa_encf_company_uniq = models.Constraint(
        "unique(company_id, dosa_encf)",
        "Este eNCF ya fue emitido en esta compañía.",
    )
    _dosa_recibida_uniq = models.Constraint(
        "unique(company_id, dosa_recibida_encf, dosa_rnc_emisor_recibido)",
        "Esta factura recibida ya fue importada.",
    )

    @api.depends("move_type", "partner_id", "partner_id.country_id", "company_id.country_id")
    def _compute_dosa_tipo_ecf(self):
        for move in self:
            if move.move_type == "out_refund":
                move.dosa_tipo_ecf = TIPO_ECF_NOTA_CREDITO
            elif move.move_type == "out_invoice":
                company_country = move.company_id.country_id
                partner_country = move.partner_id.country_id
                if company_country and partner_country and partner_country != company_country:
                    # Venta a un cliente fuera de RD: Comprobante de
                    # Exportación (E46), exento de ITBIS por definición.
                    move.dosa_tipo_ecf = TIPO_ECF_EXPORTACION
                else:
                    move.dosa_tipo_ecf = "31" if move.partner_id.vat else "32"
            else:
                move.dosa_tipo_ecf = False

    @api.depends("move_type", "amount_total", "reversed_entry_id.amount_total")
    def _compute_dosa_codigo_modificacion(self):
        for move in self:
            if move.move_type != "out_refund":
                move.dosa_codigo_modificacion = False
                continue
            origin = move.reversed_entry_id
            is_full_reversal = bool(origin) and float_compare(
                abs(move.amount_total), abs(origin.amount_total),
                precision_rounding=move.currency_id.rounding) == 0
            move.dosa_codigo_modificacion = "1" if is_full_reversal else "3"

    # ------------------------------------------------------------------
    # Emisión automática al validar
    # ------------------------------------------------------------------
    def action_post(self):
        res = super().action_post()
        for move in self:
            if (move.move_type in ("out_invoice", "out_refund")
                    and move.company_id.dosa_auto_emit and not move.dosa_encf):
                move._dosa_emit_ecf(raise_on_error=False)
        return res

    def action_dosa_emit_ecf(self):
        for move in self:
            move._dosa_emit_ecf(raise_on_error=True)
        return True

    def action_dosa_check_status(self):
        for move in self:
            move._dosa_check_status()

    def _dosa_check_status(self):
        """Los endpoints ConsultaEstado/ConsultaEstadoFCex de Dosasystems
        responden HTTP 500 de forma consistente (bug confirmado en su
        servidor, no depende de los parámetros enviados). En su lugar,
        reenviamos el mismo payload al endpoint de emisión: Dosasystems
        detecta el eNCF/documento ya procesado y devuelve el último estado
        que tiene en su base de datos en vez de reenviarlo a la DGII.
        """
        self.ensure_one()
        if not self.dosa_encf or not self.dosa_request_payload:
            return
        client = self.company_id.get_dosa_api_client()
        try:
            payload = json.loads(self.dosa_request_payload)
            if self.move_type == "out_refund":
                response = client.nota_desde_factura(
                    payload, self.dosa_encf, tipo_ecf=self.dosa_tipo_ecf or TIPO_ECF_NOTA_CREDITO)
            else:
                response = client.enviar_factura(payload)
            self._dosa_apply_response(response)
            self.dosa_check_error = False
        except DosaApiError as exc:
            self.dosa_check_error = str(exc)
            self.message_post(body=_("No se pudo consultar el estado en Dosasystems: %s") % exc)

    def _dosa_emit_ecf(self, raise_on_error=False):
        self.ensure_one()
        if self.move_type not in ("out_invoice", "out_refund") or self.dosa_encf:
            return
        if self.state != "posted":
            if raise_on_error:
                raise UserError(_("Solo se pueden emitir e-CF de facturas contabilizadas."))
            return
        company = self.company_id
        if not company.dosa_api_key:
            msg = _("Dosasystems no está configurado en la compañía %s (falta el API Key).") % company.name
            if raise_on_error:
                raise UserError(msg)
            _logger.warning(msg)
            return
        try:
            if self.move_type == "out_refund":
                self._dosa_emit_nota_credito()
            else:
                self._dosa_emit_factura()
        except (DosaApiError, ValueError) as exc:
            self.write({"dosa_estado": "error", "dosa_mensajes": str(exc)})
            self.message_post(body=_("Error al emitir e-CF a Dosasystems: %s") % exc)
            if raise_on_error:
                raise UserError(str(exc)) from exc

    def _dosa_emit_factura(self):
        self.ensure_one()
        company = self.company_id
        tipo_ecf = self.dosa_tipo_ecf or ("31" if self.partner_id.vat else "32")
        encf = company._dosa_next_encf(tipo_ecf)
        payload = self._dosa_build_payload(tipo_ecf, encf)
        self.write({
            "dosa_tipo_ecf": tipo_ecf,
            "dosa_encf": encf,
            "dosa_request_payload": json.dumps(payload, ensure_ascii=False),
            "dosa_estado": "enviado",
        })
        response = company.get_dosa_api_client().enviar_factura(payload)
        self._dosa_apply_response(response)
        self._dosa_attach_pdf()

    def _dosa_emit_nota_credito(self):
        self.ensure_one()
        origin = self.reversed_entry_id
        if not origin or not origin.dosa_request_payload:
            raise ValueError(_(
                "Esta nota de crédito no está vinculada a una factura emitida por "
                "Dosasystems (falta la factura original o su JSON de e-CF). Créala "
                "con el botón 'Añadir nota de crédito' desde la factura original "
                "para que Odoo la vincule automáticamente."))
        company = self.company_id
        tipo_ecf = TIPO_ECF_NOTA_CREDITO
        nuevo_encf = company._dosa_next_encf(tipo_ecf)
        codigo_modificacion = self.dosa_codigo_modificacion or "3"
        self.write({
            "dosa_tipo_ecf": tipo_ecf,
            "dosa_encf": nuevo_encf,
            "dosa_codigo_modificacion": codigo_modificacion,
            "dosa_request_payload": origin.dosa_request_payload,
            "dosa_estado": "enviado",
        })
        response = company.get_dosa_api_client().nota_desde_factura(
            json.loads(origin.dosa_request_payload),
            nuevo_encf,
            tipo_ecf=tipo_ecf,
            codigo_modificacion=int(codigo_modificacion),
            razon_modificacion=self.ref or _("Nota de crédito"),
            fecha_emision=(self.invoice_date or fields.Date.context_today(self)).strftime("%d-%m-%Y"),
        )
        self._dosa_apply_response(response)
        self._dosa_attach_pdf()

    def _dosa_apply_response(self, response):
        self.ensure_one()
        if not isinstance(response, dict):
            self.write({"dosa_estado": "error", "dosa_mensajes": str(response)})
            return
        codigo = str(response.get("codigo")) if response.get("codigo") is not None else None
        estado = CODIGO_ESTADO_MAP.get(codigo, "error")
        mensajes = response.get("mensajes")
        vals = {
            "dosa_track_id": response.get("trackId"),
            "dosa_estado": estado,
            "dosa_codigo_seguridad": response.get("codigoSeguridad"),
            "dosa_url_qr": self._dosa_clean_qr_url(response.get("url")),
            "dosa_mensajes": json.dumps(mensajes, ensure_ascii=False) if mensajes else False,
        }
        fecha_firma = response.get("fechaFirma")
        if fecha_firma:
            try:
                vals["dosa_fecha_firma"] = datetime.strptime(fecha_firma, "%d-%m-%Y %H:%M:%S")
            except ValueError:
                pass
        self.write(vals)
        if estado == "rechazado":
            self.message_post(body=_("DGII rechazó el e-CF %s: %s") % (self.dosa_encf, vals["dosa_mensajes"] or ""))
        else:
            self.message_post(body=_("e-CF %(encf)s enviado a DGII. Estado: %(estado)s (trackId %(track)s)") % {
                "encf": self.dosa_encf, "estado": estado, "track": vals["dosa_track_id"]})

    def _dosa_render_native_pdf(self):
        """Representación impresa del e-CF: se usa el reporte de factura
        nativo de Odoo (el mismo del botón "Imprimir" estándar), que ya
        trae el QR/eNCF/código de seguridad insertados
        (report_invoice_dosa.xml), en vez de GET /api/facturas/generate_pdf
        de Dosasystems — ese endpoint responde HTTP 500 de forma
        consistente en las pruebas (ver README), así que apoyarse en el
        propio PDF de Odoo es más confiable y no depende de su servidor."""
        self.ensure_one()
        report = self.env.ref("account.account_invoices")
        pdf_content, _report_type = report.sudo()._render_qweb_pdf(
            "account.report_invoice_with_payments", self.ids)
        return pdf_content

    def _dosa_attach_pdf(self):
        self.ensure_one()
        if not self.dosa_encf:
            return
        pdf_content = self._dosa_render_native_pdf()
        if pdf_content:
            self.env["ir.attachment"].create({
                "name": f"{self.dosa_encf}.pdf",
                "type": "binary",
                "datas": base64.b64encode(pdf_content),
                "res_model": "account.move",
                "res_id": self.id,
                "mimetype": "application/pdf",
            })

    # ------------------------------------------------------------------
    # Monitor de Emisiones: descargar XML/JSON e reimprimir PDF a demanda
    # (GET /api/facturas/lista + /api/facturas/documento/{id})
    # ------------------------------------------------------------------
    def _dosa_resolve_electronica_id(self):
        """El 'facturaElectronicaID' interno de Dosasystems no viene en la
        respuesta de EnviarFactura/NotaDesdeFactura, así que se resuelve
        buscando el eNCF en /api/facturas/lista (filtrado por fecha de
        emisión) y se cachea en dosa_electronica_id para no repetir la
        búsqueda cada vez."""
        self.ensure_one()
        if self.dosa_electronica_id:
            return self.dosa_electronica_id
        company = self.company_id
        if not company.dosa_user_id:
            raise UserError(_(
                "Configura 'Dosa User ID' en Contabilidad/Facturación > "
                "Configuración > Ajustes > Dosasystems (e-CF DGII): es "
                "obligatorio para descargar el XML/JSON o reimprimir el PDF "
                "desde el Monitor de Emisiones (aunque no haga falta para "
                "emitir)."))
        client = company.get_dosa_api_client()
        fecha = self.invoice_date or fields.Date.context_today(self)
        fecha_desde = (fecha - timedelta(days=1)).strftime("%Y-%m-%d")
        fecha_hasta = (fecha + timedelta(days=1)).strftime("%Y-%m-%d")
        registros = client.listar_facturas(
            company.dosa_user_id, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
        match = next((r for r in registros if r.get("eNCF") == self.dosa_encf), None)
        if not match:
            # Margen de fecha insuficiente (p. ej. reenvíos o diferencias de
            # huso horario con la fecha de firma DGII): reintenta sin filtro.
            registros = client.listar_facturas(company.dosa_user_id)
            match = next((r for r in registros if r.get("eNCF") == self.dosa_encf), None)
        if not match:
            raise UserError(_(
                "No se encontró el e-CF %s en Dosasystems (userId %s).") % (
                    self.dosa_encf, company.dosa_user_id))
        self.dosa_electronica_id = match["facturaElectronicaID"]
        return self.dosa_electronica_id

    def _dosa_fetch_documento(self):
        self.ensure_one()
        factura_id = self._dosa_resolve_electronica_id()
        client = self.company_id.get_dosa_api_client()
        return client.obtener_documento(self.company_id.dosa_user_id, factura_id)

    def _dosa_download_attachment(self, name, content, mimetype):
        self.ensure_one()
        attachment = self.env["ir.attachment"].create({
            "name": name,
            "type": "binary",
            "datas": base64.b64encode(content if isinstance(content, bytes) else content.encode("utf-8")),
            "res_model": "account.move",
            "res_id": self.id,
            "mimetype": mimetype,
        })
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    def _dosa_ensure_encf(self):
        self.ensure_one()
        if not self.dosa_encf:
            raise UserError(_("Esta factura no tiene un e-CF emitido todavía."))

    def action_dosa_download_xml(self):
        self.ensure_one()
        self._dosa_ensure_encf()
        try:
            doc = self._dosa_fetch_documento()
        except DosaApiError as exc:
            raise UserError(str(exc)) from exc
        if not doc.get("xml"):
            raise UserError(_("Dosasystems no devolvió el XML de este e-CF."))
        return self._dosa_download_attachment(f"{self.dosa_encf}.xml", doc["xml"], "application/xml")

    def action_dosa_download_json(self):
        self.ensure_one()
        self._dosa_ensure_encf()
        try:
            doc = self._dosa_fetch_documento()
        except DosaApiError as exc:
            raise UserError(str(exc)) from exc
        if not doc.get("json"):
            raise UserError(_("Dosasystems no devolvió el JSON de este e-CF."))
        return self._dosa_download_attachment(f"{self.dosa_encf}.json", doc["json"], "application/json")

    def action_dosa_print_pdf(self):
        self.ensure_one()
        self._dosa_ensure_encf()
        pdf_content = self._dosa_render_native_pdf()
        if not pdf_content:
            raise UserError(_("No se pudo generar el PDF."))
        return self._dosa_download_attachment(f"{self.dosa_encf}.pdf", pdf_content, "application/pdf")

    # ------------------------------------------------------------------
    # Construcción del payload JsonPost (ver README de Dosasystems)
    # ------------------------------------------------------------------
    def _dosa_build_payload(self, tipo_ecf, encf):
        self.ensure_one()
        company = self.company_id
        partner = self.partner_id.commercial_partner_id or self.partner_id
        es_exportacion = tipo_ecf == TIPO_ECF_EXPORTACION
        totales, otra_moneda = self._dosa_compute_totales(tipo_ecf)

        es_credito = bool(self.invoice_payment_term_id) and self.invoice_date_due and self.invoice_date_due != self.invoice_date
        tabla_formas_pago = {
            "formaDePago": [{
                "formaPago": company.dosa_default_forma_pago or "3",
                "montoPago": f"{self.amount_total:.2f}",
            }]
        }
        if es_exportacion:
            # El XSD de la DGII rechaza IndicadorMontoGravado en E46 (probado
            # en vivo: "invalid child element 'IndicadorMontoGravado'"; el
            # orden de los campos también importa para el XML generado).
            id_doc = {
                "tipoeCF": tipo_ecf,
                "encf": encf,
                "tipoIngresos": "01",
                "tipoPago": 2 if es_credito else 1,
                "tablaFormasPago": tabla_formas_pago,
            }
        else:
            id_doc = {
                "tipoeCF": tipo_ecf,
                "encf": encf,
                # Formato e-CF v1.0 DGII: indica si "montoItem" ya incluye
                # el ITBIS (1) o no (0) — NO si hay algo gravado. Este
                # conector siempre envía line.price_subtotal (sin
                # impuesto), así que siempre debe ser 0; enviar 1 hace que
                # la DGII divida el monto entre (1+tasa) y descuadre
                # MontoGravadoI1 contra el detalle (confirmado en vivo).
                "indicadorMontoGravado": 0,
                "tipoIngresos": "01",
                "tipoPago": 2 if es_credito else 1,
                "tablaFormasPago": tabla_formas_pago,
            }
        if es_credito and self.invoice_date_due:
            id_doc["fechaLimitePago"] = self.invoice_date_due.strftime("%d-%m-%Y")
        if tipo_ecf in TIPO_ECF_REQUIERE_VENCIMIENTO:
            sequence = company._dosa_get_ecf_sequence(tipo_ecf)
            if not sequence.dosa_fecha_vencimiento:
                raise ValueError(_(
                    "Configura la 'Fecha de vencimiento (DGII)' en la secuencia '%s' "
                    "(Ajustes > Técnico > Secuencias) antes de emitir e-CF tipo %s."
                ) % (sequence.name, tipo_ecf))
            id_doc["fechaVencimientoSecuencia"] = sequence.dosa_fecha_vencimiento.strftime("%d-%m-%Y")

        emisor = {
            "rncEmisor": self._dosa_clean_vat(company.vat),
            "razonSocialEmisor": company.name,
            "nombreComercial": company.partner_id.commercial_company_name or company.name,
            "direccionEmisor": self._dosa_format_address(company.partner_id),
            "numeroFacturaInterna": self.name or "",
            "fechaEmision": (self.invoice_date or fields.Date.context_today(self)).strftime("%d-%m-%Y"),
        }

        comprador = {
            "razonSocialComprador": partner.name or "CONSUMIDOR FINAL",
            "correoComprador": partner.email or "",
            "direccionComprador": self._dosa_format_address(partner),
            "codigoInternoComprador": partner.ref or "",
        }
        if es_exportacion:
            identificador_extranjero = self._dosa_clean_vat(partner.vat) or partner.vat
            if not identificador_extranjero:
                raise ValueError(_(
                    "El cliente %s no tiene identificador fiscal (campo NIF) configurado "
                    "y es obligatorio como 'identificadorextranjero' para e-CF E46."
                ) % partner.name)
            comprador["identificadorExtranjero"] = identificador_extranjero
        else:
            rnc_comprador = self._dosa_clean_vat(partner.vat)
            if tipo_ecf == "31" and not rnc_comprador:
                raise ValueError(_("El cliente %s no tiene RNC configurado y es obligatorio para e-CF E31.") % partner.name)
            if rnc_comprador:
                comprador["rncComprador"] = rnc_comprador

        items = []
        for line_no, line in enumerate(self.invoice_line_ids.filtered(lambda l: l.display_type == "product"), start=1):
            is_service = bool(line.product_id) and line.product_id.type == "service"
            item = {
                "numeroLinea": line_no,
                "indicadorFacturacion": self._dosa_line_indicador_facturacion(line, tipo_ecf),
                "nombreItem": line.name or (line.product_id.display_name if line.product_id else ""),
                "indicadorBienoServicio": 2 if is_service else 1,
                "cantidadItem": f"{line.quantity:.2f}",
                "unidadMedida": UNIDAD_MEDIDA_DEFAULT,
                "precioUnitarioItem": f"{line.price_unit:.2f}",
                "montoItem": f"{line.price_subtotal:.2f}",
            }
            if otra_moneda:
                item["otraMonedaDetalle"] = {
                    "precioOtraMoneda": f"{line.price_unit:.2f}",
                    "montoItemOtraMoneda": f"{line.price_subtotal:.2f}",
                }
            items.append(item)

        encabezado = {
            "version": "1.0",
            "idDoc": id_doc,
            "emisor": emisor,
            "comprador": comprador,
            "totales": totales,
        }
        if otra_moneda:
            encabezado["otraMoneda"] = otra_moneda

        return {
            "encabezado": encabezado,
            "detallesItems": {"items": items},
            "descuentosORecargos": {"descuentoORecargo": []},
            "paginacion": {},
            "informacionReferencia": {},
        }

    def _dosa_compute_totales(self, tipo_ecf=None):
        """Calcula el bloque 'totales' (siempre en DOP, moneda legal para la
        DGII) y, si la factura está en otra moneda, el bloque 'otraMoneda'
        con los mismos montos en la moneda original de la factura.

        Devuelve (totales_dict, otra_moneda_dict_or_None).
        """
        self.ensure_one()
        company_currency = self.company_id.currency_id
        is_foreign = self.currency_id != company_currency
        conv_date = self.invoice_date or fields.Date.context_today(self)

        def to_dop(amount):
            if not is_foreign:
                return amount
            return self.currency_id._convert(amount, company_currency, self.company_id, conv_date)

        rate_keys = {18.0: "1", 16.0: "2", 0.0: "3"}
        gravado = {"1": 0.0, "2": 0.0, "3": 0.0}
        itbis = {"1": 0.0, "2": 0.0, "3": 0.0}
        exento = 0.0
        for line in self.invoice_line_ids.filtered(lambda l: l.display_type == "product"):
            subtotal = line.price_subtotal
            if tipo_ecf == TIPO_ECF_EXPORTACION:
                # Formato e-CF v1.0 de la DGII (nota 51): el indicador de
                # facturación de todo ítem en un E46 debe ser 3 (ITBIS tasa
                # 0%), NO 4 (exento) — la exportación se declara como
                # "gravada a tasa cero", no como exenta. Por eso el monto va
                # a MontoGravadoI3, y MontoExento no aplica a este tipo
                # (tabla de obligatoriedad de la DGII: 0 = no corresponde).
                gravado["3"] += subtotal
                continue
            taxes = line.tax_ids.filtered(lambda t: t.amount_type == "percent" and t.amount > 0)
            tax_amount = line.price_total - subtotal
            if not taxes:
                exento += subtotal
                continue
            if self.dosa_norma_0707:
                # Norma 07-07 (sector construcción): el ITBIS se declara al
                # 18%, pero calculado sobre una base reducida en vez del
                # 100% del valor facturado. En vez de asumir un porcentaje
                # fijo, se recalcula esa base a partir del ITBIS que Odoo ya
                # determinó (ITBIS ÷ 18%), para que el e-CF siempre cuadre
                # con la contabilidad real de la factura.
                key = "1"
                gravado_line = tax_amount / 0.18
                gravado[key] += gravado_line
                itbis[key] += tax_amount
                exento += subtotal - gravado_line
            else:
                rate = taxes[0].amount
                key = rate_keys[min(rate_keys, key=lambda r: abs(r - rate))]
                gravado[key] += subtotal
                itbis[key] += tax_amount

        if tipo_ecf == TIPO_ECF_EXPORTACION:
            # Formato e-CF v1.0 de la DGII: para E46 solo aplican
            # MontoGravadoI3/ITBIS3/TotalITBIS3 (tabla de obligatoriedad,
            # pág. 19-20); MontoGravadoI1/I2, MontoExento y
            # MontoImpuestoAdicional no corresponden a este tipo (código 0).
            # Confirmado también en vivo: el XSD de Dosasystems rechaza esos
            # campos para E46.
            totales = {
                "montoGravadoTotal": f"{to_dop(sum(gravado.values())):.2f}",
                "montoGravadoI3": f"{to_dop(gravado['3']):.2f}",
                "itbiS3": 0,
                "totalITBIS": f"{to_dop(sum(itbis.values())):.2f}",
                "totalITBIS3": f"{to_dop(itbis['3']):.2f}",
                "montoTotal": f"{to_dop(self.amount_total):.2f}",
            }
        else:
            totales = {
                "montoGravadoTotal": f"{to_dop(sum(gravado.values())):.2f}",
                "montoGravadoI1": f"{to_dop(gravado['1']):.2f}",
                "montoGravadoI2": f"{to_dop(gravado['2']):.2f}",
                "montoGravadoI3": f"{to_dop(gravado['3']):.2f}",
                "montoExento": f"{to_dop(exento):.2f}",
                "itbiS1": 18,
                "itbiS2": 16,
                "itbiS3": 0,
                "totalITBIS": f"{to_dop(sum(itbis.values())):.2f}",
                "totalITBIS1": f"{to_dop(itbis['1']):.2f}",
                "totalITBIS2": f"{to_dop(itbis['2']):.2f}",
                "totalITBIS3": f"{to_dop(itbis['3']):.2f}",
                "montoImpuestoAdicional": "0.00",
                # MontoDescuento/MontoRecargo se omiten a propósito: el XSD
                # de la DGII no los acepta dentro de Totales en esta
                # posición (solo ImpuestosAdicionales o MontoTotal pueden
                # seguir a MontoImpuestoAdicional), aunque el DTO de
                # Dosasystems los declare como opcionales. Este conector no
                # calcula descuentos.
                "montoTotal": f"{to_dop(self.amount_total):.2f}",
            }

        otra_moneda = None
        if is_foreign:
            rate = self.currency_id._get_conversion_rate(
                self.currency_id, company_currency, self.company_id, conv_date)
            if tipo_ecf == TIPO_ECF_EXPORTACION:
                otra_moneda = {
                    "tipoMoneda": self.currency_id.name,
                    "tipoCambio": f"{rate:.4f}",
                    "montoGravadoTotalOtraMoneda": f"{sum(gravado.values()):.2f}",
                    "montoGravado3OtraMoneda": f"{gravado['3']:.2f}",
                    "totalITBISOtraMoneda": f"{sum(itbis.values()):.2f}",
                    "totalITBIS3OtraMoneda": f"{itbis['3']:.2f}",
                    "montoTotalOtraMoneda": f"{self.amount_total:.2f}",
                }
                return totales, otra_moneda
            otra_moneda = {
                "tipoMoneda": self.currency_id.name,
                "tipoCambio": f"{rate:.4f}",
                "montoGravadoTotalOtraMoneda": f"{sum(gravado.values()):.2f}",
                "montoGravado1OtraMoneda": f"{gravado['1']:.2f}",
                "montoGravado2OtraMoneda": f"{gravado['2']:.2f}",
                "montoGravado3OtraMoneda": f"{gravado['3']:.2f}",
                "montoExentoOtraMoneda": f"{exento:.2f}",
                "totalITBISOtraMoneda": f"{sum(itbis.values()):.2f}",
                "totalITBIS1OtraMoneda": f"{itbis['1']:.2f}",
                "totalITBIS2OtraMoneda": f"{itbis['2']:.2f}",
                "totalITBIS3OtraMoneda": f"{itbis['3']:.2f}",
                "montoImpuestoAdicionalOtraMoneda": "0.00",
                "montoTotalOtraMoneda": f"{self.amount_total:.2f}",
            }
        return totales, otra_moneda

    def _dosa_qr_img_src(self):
        self.ensure_one()
        if not self.dosa_url_qr:
            return False
        return "/report/barcode/?barcode_type=QR&value=%s&width=180&height=180" % url_quote_plus(self.dosa_url_qr)

    @staticmethod
    def _dosa_clean_qr_url(url):
        """La URL de verificación que arma Dosasystems no escapa bien todos
        sus parámetros — confirmado en vivo con dos bugs distintos, ambos
        causando "No fue encontrada la factura" en el portal real de la
        DGII (ecf.dgii.gov.do) para un e-CF que SÍ fue aceptado:

        1. Para e-CF sin RNC comprador (p. ej. E46), el parámetro
           RncComprador queda como 'N/A' literal — se elimina.
        2. CodigoSeguridad puede traer un '+' sin escapar (p. ej.
           'CodigoSeguridad=3G+3dM'); application/x-www-form-urlencoded
           interpreta ese '+' como espacio, así que el código que llega al
           portal no es el que la DGII tiene registrado — se escapa a
           '%2B'.

        El resto de la URL (RNCEmisor, ENCF, FechaEmision, FechaFirma, ...)
        sí viene bien formada en todos los casos probados, así que se toca
        solo lo puntual con regex en vez de reparsear toda la query string
        (evitaría doble-codificar FechaFirma, que Dosasystems ya entrega
        correctamente escapada).
        """
        if not url:
            return url
        url = re.sub(
            r"[?&]RncComprador=N(?:%2F|/)A(?=&|$)",
            lambda m: "?" if m.group(0)[0] == "?" else "",
            url,
        )
        url = re.sub(
            r"(CodigoSeguridad=)([^&]*)",
            lambda m: m.group(1) + quote(m.group(2), safe=""),
            url,
        )
        return url

    def _dosa_line_indicador_facturacion(self, line, tipo_ecf):
        """indicadorFacturacion NO distingue bien/servicio (eso es
        indicadorBienoServicio): indica la tasa de ITBIS del ítem, según el
        Formato e-CF v1.0 de la DGII —
        0 No facturable, 1 ITBIS 18%, 2 ITBIS 16%, 3 ITBIS 0%, 4 Exento.
        """
        self.ensure_one()
        if tipo_ecf == TIPO_ECF_EXPORTACION:
            # Nota 51 del formato oficial: obligatorio 3 (ITBIS tasa cero)
            # para todo ítem de un e-CF de exportación.
            return 3
        taxes = line.tax_ids.filtered(lambda t: t.amount_type == "percent" and t.amount > 0)
        if not taxes:
            return 4
        if self.dosa_norma_0707:
            return 1
        rate = taxes[0].amount
        rate_keys = {18.0: 1, 16.0: 2, 0.0: 3}
        return rate_keys[min(rate_keys, key=lambda r: abs(r - rate))]

    @staticmethod
    def _dosa_clean_vat(vat):
        return "".join(ch for ch in vat if ch.isdigit()) if vat else ""

    @staticmethod
    def _dosa_format_address(partner):
        parts = [partner.street, partner.street2, partner.city]
        return ", ".join(p for p in parts if p) or ""

    # ------------------------------------------------------------------
    # Recepción: sincronización y contabilización automática
    # ------------------------------------------------------------------
    @api.model
    def _cron_dosa_sync_recibidas(self):
        companies = self.env["res.company"].sudo().search([
            ("dosa_api_key", "!=", False),
            ("dosa_auto_sync_recibidas", "=", True),
        ])
        for company in companies:
            try:
                self.sudo()._dosa_sync_recibidas_company(company)
            except Exception:
                _logger.exception(
                    "Fallo sincronizando facturas recibidas de Dosasystems para %s", company.name)

    def _dosa_sync_recibidas_company(self, company):
        if not company.vat:
            _logger.warning("Compañía %s sin RNC configurado, no se puede sincronizar recibidas", company.name)
            return
        # Recibidas solo tiene datos en el ambiente de producción de
        # Dosasystems; el API Key de pruebas no devuelve nada ahí.
        client = company.get_dosa_recibidas_api_client()
        fecha_desde = company.dosa_recibidas_last_sync or (fields.Datetime.now() - timedelta(days=30))
        sync_started_at = fields.Datetime.now()
        registros = client.facturas_recibidas(
            self._dosa_clean_vat(company.vat),
            # A diferencia de EnviarFactura (DD-MM-YYYY), este endpoint
            # bindea fechaDesde/fechaHasta como DateTime .NET y solo acepta
            # formato ISO 8601 (confirmado por error 400 real de la API).
            fecha_desde=fecha_desde.strftime("%Y-%m-%d"),
            fecha_hasta=sync_started_at.strftime("%Y-%m-%d"),
        )
        for registro in registros or []:
            try:
                self._dosa_import_recibida(company, registro)
            except Exception:
                _logger.exception(
                    "No se pudo importar la factura recibida %s", registro.get("encF"))
        company.dosa_recibidas_last_sync = sync_started_at

    def _dosa_import_recibida(self, company, registro):
        # La respuesta real de /api/facturas/recibidas (probado en
        # producción) trae la clave "encF" (no "eNCF" como en el resto de
        # la API) y no incluye trackId ni JsonPost — el documento viene
        # como XML firmado en la clave "xml".
        encf = registro.get("encF")
        rnc_emisor = self._dosa_clean_vat(registro.get("rncEmisor"))
        if not encf or not rnc_emisor:
            return
        existing = self.search([
            ("company_id", "=", company.id),
            ("dosa_recibida_encf", "=", encf),
            ("dosa_rnc_emisor_recibido", "=", rnc_emisor),
        ], limit=1)
        if existing:
            return

        journal = company.dosa_recibidas_journal_id or self.env["account.journal"].search(
            [("type", "=", "purchase"), ("company_id", "=", company.id)], limit=1)
        if not journal:
            _logger.warning("No hay diario de compras configurado en %s, se omite %s", company.name, encf)
            return

        detalle = self._dosa_parse_recibida_xml(registro.get("xml"))
        partner = self._dosa_find_or_create_proveedor(
            rnc_emisor, (detalle or {}).get("razon_social_emisor"))
        line_vals = self._dosa_recibida_line_vals(company, detalle)
        fecha_emision = self._dosa_parse_fecha(registro.get("fechaEmision"))

        move = self.create({
            "move_type": "in_invoice",
            "company_id": company.id,
            "journal_id": journal.id,
            "partner_id": partner.id,
            "invoice_date": fecha_emision or fields.Date.context_today(self),
            "ref": encf,
            "dosa_recibida_encf": encf,
            "dosa_rnc_emisor_recibido": rnc_emisor,
            # Solo aparecen aquí e-CF ya recibidos/acusados por la DGII, así
            # que se consideran aceptados por definición.
            "dosa_estado": "aceptado",
            "dosa_is_received": True,
            "dosa_request_payload": registro.get("xml") or "",
            "invoice_line_ids": [(0, 0, vals) for vals in line_vals],
        })
        try:
            move.action_post()
        except UserError as exc:
            move.message_post(body=_(
                "No se pudo contabilizar automáticamente el e-CF recibido %(encf)s: %(error)s. "
                "Revisar cuentas/impuestos y contabilizar manualmente."
            ) % {"encf": encf, "error": exc})

    @staticmethod
    def _dosa_parse_recibida_xml(xml_str):
        """Parsea el e-CF firmado (XML) que devuelve /api/facturas/recibidas.
        Los tags son PascalCase según el Formato e-CF v1.0 de la DGII, p. ej.
        <Encabezado><Emisor><RazonSocialEmisor>."""
        if not xml_str:
            return None
        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError:
            return None

        def child_text(parent, tag):
            if parent is None:
                return None
            el = parent.find(f".//{tag}")
            return el.text.strip() if el is not None and el.text else None

        emisor = root.find(".//Emisor")
        totales = root.find(".//Totales")
        items = []
        for item_el in root.findall(".//DetallesItems/Item"):
            items.append({
                "nombre": child_text(item_el, "NombreItem"),
                "cantidad": child_text(item_el, "CantidadItem"),
                "precio_unitario": child_text(item_el, "PrecioUnitarioItem"),
                "monto": child_text(item_el, "MontoItem"),
                "indicador_facturacion": child_text(item_el, "IndicadorFacturacion"),
            })
        return {
            "razon_social_emisor": child_text(emisor, "RazonSocialEmisor"),
            "direccion_emisor": child_text(emisor, "DireccionEmisor"),
            "monto_total": child_text(totales, "MontoTotal"),
            "items": items,
        }

    def _dosa_recibida_line_vals(self, company, detalle):
        items = (detalle or {}).get("items") or []
        if not items:
            monto_total = float((detalle or {}).get("monto_total") or 0.0)
            return [{
                "name": _("Factura electrónica recibida (revisar detalle)"),
                "quantity": 1.0,
                "price_unit": monto_total,
            }]

        line_vals = []
        for item in items:
            vals = {
                "name": item.get("nombre") or _("Ítem"),
                "quantity": float(item.get("cantidad") or 1.0),
                "price_unit": float(item.get("precio_unitario") or 0.0),
            }
            tax = self._dosa_match_purchase_tax_by_indicador(company, item.get("indicador_facturacion"))
            if tax:
                vals["tax_ids"] = [(6, 0, [tax.id])]
            line_vals.append(vals)
        return line_vals

    def _dosa_match_purchase_tax_by_indicador(self, company, indicador_facturacion):
        # IndicadorFacturacion (Formato e-CF v1.0 DGII): 1=ITBIS 18%,
        # 2=ITBIS 16%, 3=ITBIS 0%, 4=Exento, 0=No facturable.
        rate_map = {"1": 18.0, "2": 16.0, "3": 0.0}
        rate = rate_map.get(str(indicador_facturacion))
        if rate is None:
            return False
        return self._dosa_match_purchase_tax(company, rate)

    def _dosa_match_purchase_tax(self, company, rate):
        return self.env["account.tax"].search([
            ("company_id", "=", company.id),
            ("type_tax_use", "=", "purchase"),
            ("amount_type", "=", "percent"),
            ("amount", "=", rate),
        ], limit=1)

    def _dosa_find_or_create_proveedor(self, rnc, razon_social):
        Partner = self.env["res.partner"].sudo()
        partner = Partner.search([("vat", "=", rnc)], limit=1)
        if partner:
            return partner
        return Partner.create({
            "name": razon_social or rnc,
            "vat": rnc,
            "company_type": "company",
            "supplier_rank": 1,
        })

    @staticmethod
    def _dosa_parse_fecha(value):
        if not value:
            return False
        value = value.strip()
        if "T" in value:
            value = value[:19]
        for pattern in ("%d-%m-%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, pattern).date()
            except ValueError:
                continue
        return False
