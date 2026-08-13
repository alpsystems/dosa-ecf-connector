import logging
import time

import requests

_logger = logging.getLogger(__name__)

RETRY_DELAYS = (1, 3, 5)  # segundos, backoff incremental (ver docs Dosasystems)
DEFAULT_TIMEOUT = 30


class DosaApiError(Exception):
    """Error al comunicarse con la API de Dosasystems.

    status_code es None cuando el fallo fue de red/timeout (no hubo respuesta HTTP).
    """

    def __init__(self, message, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class DosaApiClient:
    """Wrapper delgado sobre la API REST de Dosa Invoice Cloud (dosasystem.com).

    Referencia: https://github.com/alapaix13/DosaInvoicecloud-Documentation
    y https://dosasystem.com/swagger/index.html
    """

    def __init__(self, base_url, api_key, user_id=None, timeout=DEFAULT_TIMEOUT):
        if not base_url:
            raise DosaApiError("Falta configurar la URL base de Dosasystems.")
        if not api_key:
            raise DosaApiError("Falta configurar el API Key de Dosasystems.")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.user_id = user_id
        self.timeout = timeout
        self._session = requests.Session()

    def _url(self, path):
        return f"{self.base_url}{path}"

    def _request(self, method, path, *, headers=None, params=None, json_body=None,
                 expect_json=True, retryable=True):
        url = self._url(path)
        attempts = len(RETRY_DELAYS) + 1 if retryable else 1
        last_exc = None
        for attempt in range(attempts):
            try:
                response = self._session.request(
                    method, url, headers=headers, params=params,
                    json=json_body, timeout=self.timeout,
                )
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if attempt < attempts - 1:
                    _logger.warning(
                        "Dosasystems %s %s: error de red (%s), reintentando en %ss",
                        method, url, exc, RETRY_DELAYS[attempt],
                    )
                    time.sleep(RETRY_DELAYS[attempt])
                    continue
                raise DosaApiError(
                    f"No se pudo contactar a Dosasystems ({method} {path}): {exc}"
                ) from exc

            if response.status_code >= 500 and attempt < attempts - 1:
                _logger.warning(
                    "Dosasystems %s %s: HTTP %s, reintentando en %ss",
                    method, url, response.status_code, RETRY_DELAYS[attempt],
                )
                time.sleep(RETRY_DELAYS[attempt])
                continue

            if not response.ok:
                body = self._safe_body(response)
                raise DosaApiError(
                    f"Dosasystems respondió HTTP {response.status_code} en {method} {path}: {body}",
                    status_code=response.status_code,
                    payload=body,
                )

            if not expect_json:
                return response.content
            return self._safe_body(response)

        # No debería alcanzarse: o se retorna o se lanza dentro del loop.
        raise DosaApiError(f"Fallo desconocido llamando a Dosasystems: {last_exc}")

    @staticmethod
    def _safe_body(response):
        try:
            return response.json()
        except ValueError:
            return response.text

    # ------------------------------------------------------------------
    # Emisión
    # ------------------------------------------------------------------
    def enviar_factura(self, json_post):
        """POST /fe/api/emision/ecf/EnviarFactura — emite un e-CF (factura o NC/ND armada a mano)."""
        return self._request(
            "POST", "/fe/api/emision/ecf/EnviarFactura",
            headers={"X-API-KEY": self.api_key},
            json_body=json_post,
        )

    def nota_desde_factura(self, json_post, nuevo_encf, tipo_ecf="34",
                            codigo_modificacion=None, razon_modificacion=None,
                            fecha_emision=None, fecha_vencimiento_secuencia=None):
        """POST /fe/api/emision/ecf/NotaDesdeFactura — transforma el JSON de una
        factura ya emitida en una Nota de Crédito (34) o Débito (33)."""
        params = {"nuevoENCF": nuevo_encf, "tipoeCF": tipo_ecf}
        if codigo_modificacion is not None:
            params["codigoModificacion"] = codigo_modificacion
        if razon_modificacion:
            params["razonModificacion"] = razon_modificacion
        if fecha_emision:
            params["fechaEmision"] = fecha_emision
        if fecha_vencimiento_secuencia:
            params["fechaVencimientoSecuencia"] = fecha_vencimiento_secuencia
        return self._request(
            "POST", "/fe/api/emision/ecf/NotaDesdeFactura",
            headers={"X-API-KEY": self.api_key},
            params=params,
            json_body=json_post,
        )

    # NOTA: ConsultaEstado y ConsultaEstadoFCex responden HTTP 500 de forma
    # consistente en el servidor de Dosasystems (confirmado probando varias
    # combinaciones de parámetros) — no se usan. Para refrescar el estado,
    # account.move._dosa_check_status() reenvía el mismo payload a
    # enviar_factura()/nota_desde_factura(), que Dosasystems reconoce como
    # ya procesado y responde con el último estado guardado en su base.

    # ------------------------------------------------------------------
    # Consulta / recepción
    # ------------------------------------------------------------------
    def facturas_recibidas(self, rnc_comprador, fecha_desde=None, fecha_hasta=None):
        """GET /api/facturas/recibidas — e-CF recibidos por el RNC de la compañía."""
        params = {"rncComprador": rnc_comprador, "apiKey": self.api_key}
        if fecha_desde:
            params["fechaDesde"] = fecha_desde
        if fecha_hasta:
            params["fechaHasta"] = fecha_hasta
        result = self._request("GET", "/api/facturas/recibidas", params=params)
        # La respuesta viene envuelta como {"data": [...], "totalItems": N}
        # (confirmado en producción), no como lista plana ni bajo "items".
        if isinstance(result, dict):
            return result.get("data") or []
        return result or []

    def generate_pdf(self, rnc, encf):
        """GET /api/facturas/generate_pdf — representación impresa (PDF) del e-CF."""
        return self._request(
            "GET", "/api/facturas/generate_pdf",
            params={"rnc": rnc, "encf": encf},
            expect_json=False,
        )
