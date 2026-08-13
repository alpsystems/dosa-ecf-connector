# Escenarios: Exportación (E46) y Norma 07-07 (sector construcción)

Guía para una empresa de construcción que **exporta** (factura E46 a
clientes en el extranjero) y que **también factura en RD bajo la Norma
07-07** (régimen especial de ITBIS para el sector construcción). Ambos
escenarios ya están implementados y probados en vivo contra la API de
Dosasystems (ver "Resultados de las pruebas" al final de cada sección).

## 1. Exportación (E46)

### Cómo se activa

El conector detecta automáticamente el tipo E46: si el **país del cliente**
es distinto al **país de la compañía**, `dosa_tipo_ecf` pasa a `46`
(`models/account_move.py::_compute_dosa_tipo_ecf`). Puedes cambiarlo a mano
en la pestaña "DGII e-CF" de la factura antes de emitir si el cálculo
automático no aplica en algún caso puntual.

### Qué hace distinto el conector para E46

- **Comprador**: usa `identificadorExtranjero` (con E mayúscula — así lo
  llama tanto el swagger de Dosasystems como el Formato e-CF v1.0 oficial
  de la DGII) en vez de `rncComprador`, tomado del campo NIF/RNC del
  contacto.
- **Totales**: el monto va como **"gravado a tasa 3 (0%)"**
  (`montoGravadoI3`), no como `montoExento` — la DGII declara la
  exportación como "gravada a tasa cero", no como "exenta"; son categorías
  distintas en su modelo de datos (confirmado en la tabla de obligatoriedad
  oficial: `MontoExento` tiene código 0 = "no corresponde" para el tipo 46,
  mientras que `MontoGravadoI3` tiene código 2 = condicional). Cada ítem
  lleva `indicadorFacturacion=3`, obligatorio por norma para E46.
  `MontoExento` e `MontoImpuestoAdicional` se omiten del payload para este
  tipo, igual que `MontoGravadoI1`/`I2`.
- **Moneda extranjera**: si la factura está en una moneda distinta a la de
  la compañía (normalmente USD), arma el bloque `OtraMoneda` con el tipo de
  cambio del día (`res.currency._get_conversion_rate`) y los montos en la
  moneda original, además de `otraMonedaDetalle` en cada línea. Los
  **Totales principales siempre van en DOP** (moneda legal para la DGII);
  `OtraMoneda` es la misma factura expresada en la moneda original.
- **Fecha de vencimiento de secuencia**: obligatoria para E46, igual que
  E31 — configúrala en Facturación DGII > Rangos de eNCF.

### Escenario de ejemplo

Empresa de construcción que exporta componentes prefabricados a un cliente
en EE. UU., factura en USD:

| Campo | Valor |
| --- | --- |
| Cliente | International Trading Co LLC (país: Estados Unidos) |
| NIF del cliente | `TAXUS123456789` (identificadorextranjero) |
| Moneda de la factura | USD |
| Línea | 100 unidades × $250.00 = $25,000.00 |
| Tipo de e-CF | E46 (automático, por país distinto) |

**Resultado real de la prueba** (RNC de prueba `133306001`, eNCF
`E460000000007`): la DGII **aceptó el comprobante limpio, sin
observaciones** (`dosa_estado = aceptado`), con `OtraMoneda.tipoMoneda =
USD`, `montoGravadoI3 = 25,000.00` (DOP, tras conversión) y
`montoGravado3OtraMoneda = 25,000.00` (USD, monto original).

## 2. Norma 07-07 (sector construcción)

### Qué establece la norma (resumen)

La [Norma General 07-07](https://dgii.gov.do/legislacion/normasGenerales/Documents/NG%20sobre%20(ITBIS),%20NG%20sobre%20(ISR),%20NG%20sobre%20Comprobantes%20Fiscales/norma07-07.pdf)
de la DGII (2007) regula el régimen fiscal de las empresas de construcción
y desarrollo inmobiliario. Para efectos de este conector, lo relevante es:

- El ITBIS se factura al **18%**, pero calculado sobre una **base
  reducida** (comúnmente el 10% del valor de la obra facturada) en vez del
  100% — en la práctica, "el 18% de ITBIS solo sobre el 10% de la
  factura", lo que da un **efecto de ~1.8% sobre el total**.
- Pagos a maestros constructores/ajusteros: exentos de ITBIS, con
  retención de ISR del 2% (pago definitivo); no requieren NCF propio si se
  aplica la retención — la empresa documenta el gasto con un B11
  (Comprobante de Compras). **Este flujo NO pasa por e-CF de Dosasystems**
  (es otro tipo de comprobante/reporte DGII), así que queda fuera del
  alcance de este conector; se contabiliza en Odoo como un gasto normal con
  la retención correspondiente.
- Ingenieros/arquitectos/agrimensores que facturan solo honorarios
  profesionales: retención de ISR del 10%.

### Cómo se activa en el conector

Marca la casilla **"Aplica Norma 07-07 (construcción)"** en la pestaña
"DGII e-CF" de la factura (campo `dosa_norma_0707`) antes de validarla.

### Cómo calcula la base gravada

En vez de asumir a ciegas que la base es "10% del total" (lo que rompería
la contabilidad si tu impuesto en Odoo no calcula exactamente eso), el
conector **parte del ITBIS que Odoo ya calculó** en la línea:

```
base_gravada = ITBIS_de_la_línea ÷ 0.18
exento_línea = subtotal_línea − base_gravada
```

Esto significa que el resultado depende de qué impuesto uses en la línea:

- Si usas un impuesto de **1.8% plano** sobre el 100% de la base (la forma
  más simple de configurarlo en Odoo — un único impuesto que ya refleja el
  monto correcto a remitir), el conector recupera automáticamente la
  base "oficial" del 10% para el e-CF.
- Si usas el impuesto normal de **18%**, el conector no puede saber que
  aplica una reducción — reportará el 100% como gravado (igual que una
  venta normal). Por eso, para facturas con Norma 07-07, la línea debe
  llevar un impuesto que refleje el monto real de ITBIS a pagar, no el 18%
  general.

### Escenario de ejemplo

Contrato de construcción, avance de obra del 20% sobre una obra de
RD$1,000,000, con el impuesto "ITBIS Construcción 07-07 (1.8%)"
configurado en la línea:

| Campo | Valor |
| --- | --- |
| Línea | Construcción de nave industrial — avance de obra 20% |
| Subtotal | RD$1,000,000.00 |
| Impuesto en Odoo | 1.8% → ITBIS = RD$18,000.00 |
| Total factura | RD$1,018,000.00 |

**Resultado real de la prueba** (eNCF `E310000065506`): el conector calculó
`montoGravadoTotal = 100,000.00` (exactamente el 10% de RD$1,000,000) y
`montoExento = 900,000.00` (el 90%), con `totalITBIS = 18,000.00` — cuadra
matemáticamente con la norma. La DGII **aceptó** el comprobante
(`aceptado_condicional`).

**Advertencia conocida (no bloqueante):** DGII compara el detalle de la
línea (que muestra el monto completo del ítem, como debe ser — el cliente
sí compró el 100% de ese avance de obra) contra el total "gravado" reducido
de la sección Totales, y marca una observación de que no cuadran
exactamente. Es inherente a cómo la norma se representa en el formato e-CF
(la reducción ocurre a nivel de Totales, no a nivel de cada línea); el
documento queda igual **aceptado**.

## Configuración necesaria antes de usar estos escenarios

1. Secuencia `dosa.ecf.46` con "Fecha de vencimiento (DGII)" configurada
   (Ajustes > Técnico > Secuencias).
2. Para Norma 07-07: crea un impuesto de venta que refleje el ITBIS
   efectivo a remitir (p. ej. 1.8% plano) y úsalo en las líneas de las
   facturas de construcción en vez del 18% general.
3. Verifica que tus clientes extranjeros tengan **país** configurado
   (distinto al de la compañía) y un **NIF/identificador fiscal** en su
   ficha de contacto — son los dos datos que activan y completan el E46.
