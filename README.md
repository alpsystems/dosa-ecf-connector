# Dosa e-CF Connector — Odoo 19 ↔ Dosasystems (DGII)

Conector de Odoo 19 (Community) para el régimen de Comprobantes Fiscales
Electrónicos (e-CF) de la DGII, República Dominicana, vía **Dosa Invoice
Cloud** (`dosasystem.com`).

- **Emite** facturas de venta (E31 crédito fiscal / E32 consumo), notas de
  crédito (E34) y exportaciones (E46, con `OtraMoneda`) desde `account.move`
  hacia la API de Dosasystems.
- Soporta **Norma 07-07** (sector construcción): recalcula la base gravada
  de ITBIS a partir del impuesto real de la factura, en vez de asumir un
  porcentaje fijo. Ver [docs/ESCENARIOS_EXPORTACION_CONSTRUCCION.md](dosa_ecf_connector/docs/ESCENARIOS_EXPORTACION_CONSTRUCCION.md).
- **Sincroniza** cada 2 horas las facturas electrónicas recibidas
  (`GET /api/facturas/recibidas`) y las **contabiliza automáticamente** como
  facturas de proveedor en Odoo.
- Inserta el **QR de verificación de la DGII** en el reporte de factura
  nativo de Odoo (`account.report_invoice_document`), sin tocar ningún
  formato/logo personalizado — aparece en cualquier Odoo que instale el
  módulo.

El código del módulo vive en [`dosa_ecf_connector/`](dosa_ecf_connector/) y
está listo para usarse como repo de addons de Odoo.sh (el módulo está en la
raíz del repositorio, que es justo lo que Odoo.sh espera).

## 1. Publicar este repo en GitHub

Este directorio ya es un repositorio git local. Para conectarlo a Odoo.sh
necesitas un repo en GitHub:

```bash
gh repo create dosa-odoo-ecf-connector --private --source=. --remote=origin
git add -A
git commit -m "Módulo conector Odoo <-> Dosasystems (e-CF DGII)"
git push -u origin main
```

(Dime si quieres que yo cree el repo y haga el push — lo hago en cuanto lo
confirmes.)

## 2. Crear el ambiente Odoo 19 en Odoo.sh (free trial)

1. Entra a https://www.odoo.com/odoo-sh y pulsa **Try now free** / **Start
   now**, con tu cuenta de odoo.com.
2. Autoriza a Odoo.sh a acceder a tu cuenta de GitHub y selecciona el
   repositorio `dosa-odoo-ecf-connector`.
3. Elige la versión **Odoo 19.0** para la rama `main` (Odoo.sh la detecta
   como *Production* por defecto; puedes crear luego ramas de *Development*
   para probar sin afectar producción).
4. Espera el primer build. Odoo.sh instala Odoo 19 Community/Enterprise
   trial y expone tu addon automáticamente porque está en la raíz del repo.

## 3. Instalar el módulo

1. Entra a la base de datos (botón **Connect** en el panel de Odoo.sh).
2. Activa el **modo desarrollador** (Ajustes > General > Developer Tools).
3. Ve a **Aplicaciones**, quita el filtro "Apps" para ver también módulos,
   busca **"Dosa e-CF Connector"** e instálalo.

## 4. Configurar la compañía

La forma más directa es **Contabilidad/Facturación > Configuración > Ajustes**
— busca el bloque **"Dosasystems (e-CF DGII)"** al final de la página; ahí
están las mismas credenciales y el interruptor de emisión automática/manual,
sin salir de la pantalla de ajustes estándar de facturación. También puedes
editarlas por compañía en **Ajustes > Usuarios y Compañías > Compañías**, en
la pestaña **"Dosasystems (e-CF)"** (útil en multicompañía):

| Campo | Valor |
| --- | --- |
| URL base de Dosasystems | `https://dosasystem.com` (por defecto) |
| Dosa API Key | El API Key **de pruebas o producción** para emitir (header `X-API-KEY`) |
| Dosa API Key (producción, solo recibidas) | El API Key **de producción** — el ambiente de pruebas no tiene facturas recibidas. Si lo dejas vacío, se usa el de arriba. |
| Dosa User ID | Tu `userId` en Dosasystems (si tu integración lo requiere) |
| Forma de pago por defecto | P. ej. "Transferencia" |
| Emitir e-CF automáticamente al validar | Activado por defecto |
| Sincronizar facturas recibidas automáticamente | Activado por defecto |
| Diario para facturas recibidas | Tu diario de Compras |

Verifica también que el **RNC de la compañía** esté en el campo *NIF/RNC* del
formulario de la compañía — se usa como `rncEmisor` y como `rncComprador` al
buscar recibidas.

**Emisión automática vs. manual.** "Emitir e-CF automáticamente al validar"
decide el flujo de toda la compañía:

- **Activado** (por defecto): cada factura/nota de crédito se envía sola a la
  DGII al contabilizarla, sin que nadie tenga que acordarse de hacer nada.
- **Desactivado**: la factura queda contabilizada en Odoo normalmente, sin
  e-CF, y **cualquier usuario de Facturación** la emite cuando quiera con el
  botón **"Emitir e-CF"** — está en el header de la propia factura (vista
  estándar de `account.move`, no en una pantalla aparte) y también como
  botón inteligente en la barra de estadísticas junto al total. Una vez
  emitido, otro botón inteligente muestra el eNCF y el Estado DGII a simple
  vista; si la DGII rechaza el comprobante o falla el envío, aparece un
  aviso rojo ("ribbon") en la esquina de la factura.

## 5. Configurar los rangos de eNCF

Ve a **Facturación DGII > Rangos de eNCF** (no hace falta modo desarrollador)
para ver las cuatro secuencias que el módulo crea automáticamente:

- `Dosa e-CF E31 - Factura de Crédito Fiscal`
- `Dosa e-CF E32 - Factura de Consumo`
- `Dosa e-CF E34 - Nota de Crédito`
- `Dosa e-CF E46 - Exportaciones`

Ahí mismo, en línea, edita para cada una:

- **Número siguiente**: el próximo eNCF que se va a usar.
- **Rango autorizado desde/hasta**: el rango que la DGII autorizó a tu RNC.
  Es solo de validación — si "Número siguiente" cae fuera de ese rango, el
  conector bloquea la emisión con un error claro en vez de usar un eNCF
  inválido.
- **Fecha de vencimiento (DGII)**: la fecha límite del rango (requerida para
  E31 y E46; no aplica a E32/E34).

## 6. Impuestos

El conector usa los impuestos de venta/compra de tipo "Porcentaje" con tasas
**18%, 16% o 0%** para mapear a los buckets ITBIS I1/I2/I3 de la DGII.
Confirma que existan esos impuestos en tu plan de cuentas (Contabilidad >
Configuración > Impuestos) antes de emitir. Para las facturas recibidas, el
impuesto de **compra** se elige automáticamente por línea según el
`IndicadorFacturacion` del e-CF real (18%/16%/0%/exento) — no hay que
configurar nada especial para eso.

Para facturas del **sector construcción bajo la Norma 07-07**, crea además
un impuesto que refleje el ITBIS efectivo a remitir (p. ej. 1.8% plano en
vez del 18% general) y úsalo en esas líneas — ver el detalle y el porqué en
[docs/ESCENARIOS_EXPORTACION_CONSTRUCCION.md](dosa_ecf_connector/docs/ESCENARIOS_EXPORTACION_CONSTRUCCION.md).

## 7. Probar el flujo

1. Crea una factura de cliente normal en Odoo, con un cliente que tenga RNC
   (o sin RNC, para E32/consumidor final) y valídala.
2. Si "Emitir e-CF automáticamente" está activo, el conector la envía a
   Dosasystems al contabilizar; revisa la pestaña **"DGII e-CF"** de la
   factura para ver el eNCF, estado y mensajes de la DGII.
3. Si algo falla, el estado queda en `error`/`rechazado` y el detalle se
   registra en el chatter de la factura — corrígelo y usa el botón **"Emitir
   e-CF"** para reintentar.
4. Para probar recibidas sin esperar el cron, ve a **Ajustes > Técnico >
   Acciones programadas**, abre *"Dosasystems: sincronizar facturas
   recibidas"* y pulsa **Run Manually** — necesitas el API Key de
   producción configurado (paso 4).
5. Usa **Facturación DGII > Monitor de Emisiones** para ver todos los e-CF
   emitidos en una sola lista (eNCF, estado con color, mensajes de la DGII)
   con filtros para "Rechazados / Error", "Con observaciones" y **"Falló
   consulta de estado"** — este último es distinto del Estado DGII: indica
   que Dosasystems no respondió al refrescar el estado, no que el e-CF haya
   sido rechazado.
6. El botón **"Consultar estado DGII"** no llama a `ConsultaEstado` (ver
   más abajo): reenvía el mismo comprobante a `EnviarFactura`/
   `NotaDesdeFactura`, y Dosasystems responde con el último estado que
   tiene guardado en vez de tramitarlo de nuevo con la DGII.
7. En el **Monitor de Emisiones**, cada fila con eNCF tiene botones
   **PDF / XML / JSON** para reimprimir o descargar el comprobante
   directamente desde Dosasystems, sin abrir la factura. Requieren que
   **"Dosa User ID"** esté configurado (Ajustes > Facturación >
   Dosasystems) — a diferencia de emitir, estas descargas sí lo necesitan
   porque usan `GET /api/facturas/lista` + `GET
   /api/facturas/documento/{id}` (no documentados como obligatorios en el
   swagger, pero devuelven `400 "userId o apiKey inválido"` sin él). El
   conector resuelve y cachea el `facturaElectronicaID` interno de
   Dosasystems automáticamente la primera vez.
8. Para una **nota de crédito**, usa el botón **"Añadir nota de crédito"**
   desde la factura original (así Odoo la vincula automáticamente vía
   `reversed_entry_id`, que el conector necesita para reenviar el JSON
   original a `NotaDesdeFactura`). En la pestaña **"DGII e-CF"** de la nota
   de crédito revisa/ajusta el campo **"Código de modificación (DGII)"**
   antes de emitir — se sugiere automáticamente (`1` anulación total si el
   monto coincide con el de la factura original, `3` corrección de montos
   si es parcial) según la tabla oficial de la DGII, pero es editable.

## Alcance y límites conocidos (v1)

- Tipos de e-CF cubiertos: **E31, E32** (emisión), **E34** (notas de
  crédito, vía `NotaDesdeFactura`, con `Código de modificación` según la
  tabla oficial de la DGII: 1 anulación total, 2 corrección de texto, 3
  corrección de montos, 4 reemplazo por contingencia, 5 referencia a
  Factura de Consumo Electrónica) y **E46** (exportaciones, con
  `OtraMoneda`). E33 (nota de débito) y E41/E43/E45/E47 quedan fuera; el
  código está estructurado para añadirlos en `models/account_move.py` y
  `models/dosa_common.py` sin rehacer el conector.
- Las facturas recibidas se contabilizan con el impuesto de compra que
  corresponda **por línea**, según el `IndicadorFacturacion` del e-CF real
  (18%/16%/0%/exento) — probado con **301 facturas reales** de producción,
  53 importadas en el rango de prueba y **las 53 contabilizadas
  automáticamente**, 0 en borrador.
- El PDF que se adjunta automáticamente al comprobante tras una emisión
  exitosa, y el que genera el botón "Reimprimir PDF"/"PDF" del Monitor de
  Emisiones, es el **reporte de factura nativo de Odoo** (el mismo del
  botón "Imprimir" estándar, con el QR/eNCF/código de seguridad ya
  insertados) — no `GET /api/facturas/generate_pdf` de Dosasystems, que
  responde `HTTP 500` de forma consistente (ver más abajo). Usar el PDF
  propio de Odoo evita depender de ese endpoint.
- Norma 07-07 (construcción) y B11/retenciones a maestros constructores:
  ver [docs/ESCENARIOS_EXPORTACION_CONSTRUCCION.md](dosa_ecf_connector/docs/ESCENARIOS_EXPORTACION_CONSTRUCCION.md)
  para el detalle de qué cubre el conector y qué queda fuera (el flujo de
  B11 no pasa por e-CF, es otro trámite DGII).

### Validado contra la API real de Dosasystems (pruebas y producción)

Los flujos de emisión E31, E32, E46 (con `OtraMoneda` en USD) y Norma 07-07
se probaron de punta a punta contra `dosasystem.com` real (RNC de prueba
`133306001`) y quedaron **Aceptados limpios, sin observaciones**, con
trackId, código de seguridad y URL de QR reales. La sincronización de
recibidas se probó contra el ambiente de **producción** real (301
facturas). En el camino se corrigieron bugs que solo un envío real —y el
[Formato e-CF v1.0 oficial de la DGII](https://dgii.gov.do/cicloContribuyente/facturacion/comprobantesFiscalesElectronicosE-CF/Documentacin%20sobre%20eCF/Formatos%20XML/Formato%20Comprobante%20Fiscal%20Electr%C3%B3nico%20(e-CF)%20v1.0.pdf)—
podían revelar:

- **`IndicadorMontoGravado` no significa "hay algo gravado"** — significa
  "¿`MontoItem` ya incluye el ITBIS?" (0 = no, 1 = sí). Este conector
  siempre envía `line.price_subtotal` (sin impuesto), así que ahora siempre
  manda `0`; antes mandaba `1` cuando había monto gravado, lo que hacía que
  la DGII dividiera el monto entre 1.18 y descuadrara `MontoGravadoI1`
  contra el detalle en **todas** las facturas gravadas (era la causa de la
  advertencia recurrente "no coincide con la sumatoria del detalle").
- **`IndicadorFacturacion` no distingue "producto vs. servicio"** (eso es
  `IndicadorBienoServicio`) — indica la **tasa de ITBIS del ítem**: 1=18%,
  2=16%, 3=0%, 4=exento, 0=no facturable. Se corrigió para calcularlo desde
  el impuesto real de cada línea en vez de si el producto es un servicio.
- `IndicadorBienoServicio` estaba invertido: 1=Bien, 2=Servicio (no al
  revés).
- El eNCF debe tener **13 caracteres** (`E` + tipo de 2 dígitos + secuencia
  de **10** dígitos, no 11 como decía la documentación en texto).
- `Totales.MontoDescuento` / `MontoRecargo` no son válidos para el XSD de la
  DGII en esa posición aunque el DTO de Dosasystems los declare como
  opcionales — se eliminaron del payload (E31/E32/E34).
- E46 usa un esquema `Totales`/`OtraMoneda` reducido: solo la variante "3"
  (0%) — `MontoExento` e `MontoImpuestoAdicional` **no aplican** a E46 (la
  exportación se declara "gravada a tasa cero", no "exenta" — confirmado en
  la tabla de obligatoriedad oficial de la DGII, pág. 19-20 del formato).
  El campo del comprador es `identificadorExtranjero` (con E mayúscula, no
  `rncComprador`) — swagger y el formato oficial coinciden en esto.
- `GET /api/facturas/recibidas` espera `fechaDesde`/`fechaHasta` en
  **ISO 8601** (`YYYY-MM-DD`), y responde `{"data": [...], "totalItems": N}`
  (no una lista plana ni `{"items": [...]}`). Cada registro trae `encF`
  (con E minúscula) y el e-CF completo como XML firmado en `xml`, no como
  JSON — el conector lo parsea con `xml.etree.ElementTree`.
- `ConsultaEstado`/`ConsultaEstadoFCex` (ver abajo) no se usan más: se
  reemplazaron por un reenvío del mismo payload a `EnviarFactura`.
- **La URL de verificación (QR) que devuelve Dosasystems para e-CF sin RNC
  comprador (E46) viene rota**: trae `RncComprador=N/A` literal en el query
  string. Con ese parámetro, el portal real de la DGII
  (`ecf.dgii.gov.do/testecf/consultatimbre`) responde *"No fue encontrada
  la factura"* — pero **el e-CF sí fue aceptado de verdad por la DGII**:
  quitando ese único parámetro, la misma URL confirma "Aceptado" (probado
  en vivo, comparando con y sin el parámetro para el mismo eNCF). El
  conector limpia esa URL automáticamente
  (`_dosa_clean_qr_url`) antes de guardarla y de generar el QR impreso, así
  que el QR de la factura sí verifica correctamente — pero vale la pena que
  reporten el bug a Dosasystems, porque cualquier integración que use su
  URL tal cual la reciba mostrará un QR roto para todas las exportaciones.
- **La misma URL de verificación también viene rota cuando el código de
  seguridad contiene un `+`** (p. ej. `CodigoSeguridad=3G+3dM`, visto en
  vivo en `E310000065510` y `E310000065506`): sin escapar, ese `+` se
  interpreta como espacio (`application/x-www-form-urlencoded`), así que
  el código que llega al portal de la DGII ya no coincide con el
  registrado, y responde *"No fue encontrada la factura"* para un e-CF que
  sí fue aceptado — mismo síntoma que el bug de `RncComprador=N/A`, causa
  distinta. `_dosa_clean_qr_url` también lo corrige (escapa a `%2B`),
  probado en vivo contra `ecf.dgii.gov.do` confirmando "Aceptado" tras la
  corrección.

**Problemas del lado de Dosasystems, no del conector (para reportarles):**

- `GET /fe/api/emision/ecf/ConsultaEstado` y su variante
  `ConsultaEstadoFCex` responden siempre `HTTP 500` (`"BaseAddress must be
  set"` / `"Value cannot be null (Parameter 'path')"`), sin importar qué
  combinación de parámetros se envíe.
- `GET /api/facturas/generate_pdf` responde `HTTP 500` de forma consistente
  en las pruebas — el conector reintenta 3 veces y sigue sin bloquear la
  emisión si falla.
- La URL de verificación con `RncComprador=N/A` para E46 y con `+` sin
  escapar en `CodigoSeguridad` (ver arriba).

## 8. Publicar en la Odoo Apps Store

El módulo está empaquetado para cumplir los requisitos técnicos de
[apps.odoo.com](https://apps.odoo.com) y para instalarse sin fricción tanto
descargado a mano como desplegado en Odoo.sh:

- **`static/description/icon.png`** — ícono de 128×128 que se usa en el
  listado y en el menú de Aplicaciones de cualquier Odoo.
- **`static/description/index.html`** — página de descripción/marketing que
  Odoo muestra en la ficha de la app (autocontenida, sin recursos externos).
- **`LICENSE`** — texto completo de la LGPL-3, coincide con el
  `"license": "LGPL-3"` declarado en `__manifest__.py`.
- **`__manifest__.py`** — incluye `website`, `support` y `category`
  (`Accounting/Localizations`) además de los campos ya existentes.
- **`tests/test_dosa_helpers.py`** — pruebas unitarias (sin llamadas a la
  API real) de las funciones más sensibles: cálculo de `Totales` para E46 y
  Norma 07-07, y la limpieza de la URL del QR. Corren con
  `--test-tags=/dosa_ecf_connector`.

**Verificado en este ambiente Docker** (equivalente a lo que hace Odoo.sh o
una instalación manual desde la Apps Store):

- Instalación limpia en una base de datos nueva y vacía
  (`odoo -i dosa_ecf_connector --without-demo=all`), 0 errores.
- Las 5 pruebas unitarias pasan (`0 failed, 0 error(s)`).
- La dependencia externa declarada (`requests`) ya viene incluida en las
  dependencias estándar de Odoo — no requiere instalar nada aparte ni en
  Odoo.sh ni en un hosting propio.
- Actualización del módulo sobre una base con datos reales, sin warnings.

**Lo que sigue siendo un paso tuyo:** publicar en apps.odoo.com requiere una
cuenta de partner/desarrollador de Odoo y se hace desde su propio sitio (subir
el .zip del módulo o conectar el repo) — es una acción ligada a tu cuenta que
no puedo ejecutar por ti. Antes de enviarlo, conviene que confirmes/ajustes
el email de `support` en `__manifest__.py` (dejé `soporte@dosasystem.com`
como valor por defecto) y que revises la ficha de `static/description/index.html`
por si quieres agregar capturas de pantalla reales del módulo funcionando.

## Referencia de la API

- Documentación funcional (Dosasystems): https://github.com/alapaix13/DosaInvoicecloud-Documentation
- [Formato Comprobante Fiscal Electrónico (e-CF) v1.0 — DGII, oficial (PDF, 89 pág.)](https://dgii.gov.do/cicloContribuyente/facturacion/comprobantesFiscalesElectronicosE-CF/Documentacin%20sobre%20eCF/Formatos%20XML/Formato%20Comprobante%20Fiscal%20Electr%C3%B3nico%20(e-CF)%20v1.0.pdf) — la fuente autoritativa para nombres de campos, obligatoriedad por tipo de e-CF y reglas de cálculo; varias veces más precisa que la documentación de Dosasystems.
