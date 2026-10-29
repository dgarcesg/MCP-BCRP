# Informe · ¿Inventa cifras Claude? Un MCP con las series oficiales del BCRP

Diplomatura PUCP 2026 · Sesión 04: MCP y Claude Code · 28 de octubre de 2026

## 1. Qué se construyó

Un servidor MCP hecho con FastMCP 4 (`server.py`) que le da a Claude acceso a las 17 mil series del Banco Central de
Reserva del Perú (BCRP). Pasa las 8 pruebas del contrato (`uv run pytest -q`: 8 passed).

| Tipo | Nombre | Qué hace |
|---|---|---|
| Herramienta | `buscar_series` | Busca el código de una serie por palabras (venía hecha) |
| Herramienta | `serie` | Descarga los datos de una serie entre dos fechas y devuelve la URL de la fuente |
| Herramienta | `resumen` | Calcula primero, último, cambio, variación %, promedio, máximo y mínimo, para que el modelo no haga cuentas |
| Herramienta propia | `comparar_paises` | Compara al Perú con otros países con datos anuales del Banco Mundial |
| Recurso | `bcrp://serie/{codigo}` | La ficha de una serie (plantilla) |
| Recurso | `bcrp://series/destacadas` | Las fichas de 7 series muy consultadas, por indicador; es el que aparece en el menú `@` de Claude Code |
| Prompt | `informe(tema)` | Pide un informe que cite el código y el periodo de cada cifra |

El servidor está conectado a Claude Code con `.mcp.json`, junto con el servidor `fetch`. En Claude Code se probaron
una pregunta con herramientas, el recurso con `@`, el prompt con `/` y `fetch`.

## 2. Cómo se midió

`evaluar.py` le hace cada pregunta de `preguntas.csv` a Claude Haiku en modo no interactivo (`claude -p`), de dos
maneras:

- **memoria:** sin ninguna herramienta, solo con lo que el modelo sabe.
- **mcp:** con el servidor `bcrp` como única herramienta.

La instrucción pide un solo número y agrega: *«Si no puedes saberlo con certeza, pon valor null: no estimes»*. Cada
respuesta se compara con la cifra oficial (la *verdad*) y se califica como **acierta** (dentro de la tolerancia),
**se equivoca** (fuera de la tolerancia) o **no sabe** (respondió null).

Hay 10 preguntas: 8 del curso y 2 propias (9 y 10). La verdad de las preguntas propias se revisó a mano en la web
del BCRP (sección 6), no con el servidor.

## 3. Resultados

| Modo | Acierta | Se equivoca | No sabe | Segundos promedio | Turnos promedio |
|---|---|---|---|---|---|
| memoria | 0 | 0 | 10 | 11.6 | 2.0 |
| mcp | **10** | 0 | 0 | 31.6 | 4.6 |

![Resultados por modo](grafico.png)

*`grafico.png` se genera con `uv run grafico.py` a partir de `resultados.csv`.*

## 4. Las 10 preguntas

| # | id | Pregunta | Serie | Periodo | Verdad | Tolerancia |
|---|---|---|---|---|---|---|
| 1 | `ipc_set26` | ¿Cuál fue la inflación interanual (variación del IPC en 12 meses) de Lima Metropolitana en setiembre de 2026, en %? | PN01273PM | 2026-09 | 4.5487 | 0.05 |
| 2 | `ipc_dic25` | ¿Cuál fue la inflación interanual (variación del IPC en 12 meses) de Lima Metropolitana en diciembre de 2025, en %? | PN01273PM | 2025-12 | 1.5088 | 0.05 |
| 3 | `ipc_mar25` | ¿Cuál fue la variación mensual del IPC de Lima Metropolitana en marzo de 2025, en %? | PN01271PM | 2025-03 | 0.8102 | 0.02 |
| 4 | `referencia_set26` | ¿Cuál era la tasa de referencia de la política monetaria del BCRP en setiembre de 2026, en %? | PD04722MM | 2026-09 | 4.25 | 0.01 |
| 5 | `tc_15oct26` | ¿Cuál fue el tipo de cambio interbancario venta del 15 de octubre de 2026 según el BCRP, en soles por dólar? | PD04638PD | 2026-10-15 | 3.4282 | 0.002 |
| 6 | `rin_ago26` | ¿A cuánto ascendían las reservas internacionales netas del BCRP a fines de agosto de 2026, en millones de US$? | PN00027MM | 2026-08 | 96 517.9 | 100 |
| 7 | `cobre_ago26` | ¿Cuál fue el precio promedio del cobre en agosto de 2026 según el BCRP, en centavos de US$ por libra? | PN38784BM | 2026-08 | 689.70 | 3.5 |
| 8 | `pbi_2025` | ¿Cuánto creció el PBI real del Perú en 2025 según el BCRP, en %? | PM04923AA | 2025 | 3.4306 | 0.05 |
| 9 | `alimentos_cambio_3a` (propia) | ¿Cuánto cambió la inflación interanual (variación en 12 meses) del IPC de alimentos y bebidas de Lima Metropolitana entre setiembre de 2023 y setiembre de 2026, en puntos porcentuales? Usa un número negativo si bajó. | PN09822PM | 2023-09 a 2026-09 | −4.30 | 0.05 |
| 10 | `remesas_pico` (propia) | Según el BCRP, ¿cuál fue el mayor monto trimestral de remesas del exterior recibidas por el Perú entre el primer trimestre de 2024 y el cuarto trimestre de 2025, en millones de US$? | PN38986BQ | 2025-T4 | 1 360 | 1 |

**Por qué estas dos preguntas propias.** La 9 resume la evolución de la inflación de alimentos en tres años (de
8.29 % a 3.99 %) y prueba que el modelo use el `cambio` en puntos porcentuales de `resumen` y no su `variacion_pct`
(−51.85 %), que sería una respuesta equivocada. La 10 prueba el manejo de series trimestrales y del máximo: hay
dos picos, en el cuarto trimestre de 2024 (1 278) y de 2025 (1 360), y solo el segundo es correcto. Las remesas
solo se publican de forma trimestral y anual, por eso la pregunta usa trimestres.

## 5. Resultado de cada pregunta

| # | id | Memoria | MCP: respuesta | MCP: resultado | Segundos (memoria / mcp) | Turnos mcp |
|---|---|---|---|---|---|---|
| 1 | `ipc_set26` | no sabe | 4.5487 | acierta | 13.4 / 37.1 | 5 |
| 2 | `ipc_dic25` | no sabe | 1.51 | acierta | 12.3 / 33.6 | 4 |
| 3 | `ipc_mar25` | no sabe | 0.81 | acierta | 10.5 / 33.7 | 6 |
| 4 | `referencia_set26` | no sabe | 4.25 | acierta | 10.3 / 33.7 | 4 |
| 5 | `tc_15oct26` | no sabe | 3.428 | acierta | 12.5 / 33.1 | 4 |
| 6 | `rin_ago26` | no sabe | 96 517.91 | acierta | 12.2 / 28.9 | 4 |
| 7 | `cobre_ago26` | no sabe | 689.70 | acierta | 10.4 / 33.3 | 5 |
| 8 | `pbi_2025` | no sabe | 3.43 | acierta | 12.4 / 31.4 | 5 |
| 9 | `alimentos_cambio_3a` | no sabe | −4.30 | acierta | 12.2 / 29.7 | 5 |
| 10 | `remesas_pico` | no sabe | 1 359.65 | acierta | 9.5 / 21.4 | 4 |

En el modo memoria el modelo usó 2 turnos en todas las preguntas.

## 6. Qué falló cada modo y por qué

**Memoria: 0 aciertos, 0 errores, 10 «no sé».** El modelo no inventó ninguna cifra: en las 10 preguntas dijo que
no tenía acceso a los datos del BCRP y respondió null. Hay dos situaciones distintas:

- **Seis preguntas son posteriores a lo que el modelo sabe** (1, 4, 5, 6, 7 y 9, que piden datos de 2026). En la
  columna `fuente` el modelo lo explica: *«mi conocimiento llega hasta junio de 2026, así que no conozco la cifra de
  setiembre de 2026»*.
- **Cuatro preguntas son anteriores** (2, 3, 8 y 10, sobre 2024 y 2025), y aun así respondió que no sabía: *«no
  tengo el dato con certeza en memoria»*. La instrucción «no estimes» lo llevó a abstenerse antes que arriesgar
  una cifra.

En la pregunta 9 incluso describió cómo obtener el dato (*«restar la variación de setiembre de 2026 menos la de
setiembre de 2023»*), pero sin dar un número.

**MCP: 10 aciertos, 0 errores.** En todas las preguntas el modelo citó en la columna `fuente` el código de la
serie, el periodo y la URL de la API del BCRP, que son los datos que devuelven `serie` y `resumen`. Usó entre 4 y 6
turnos por pregunta. `resultados.csv` no registra qué herramienta usó en cada turno. Tres casos merecen mención:

- **Pregunta 9 (alimentos):** respondió −4.30 *«Setiembre 2023: 8,29%; setiembre 2026: 3,99%; cambio −4,30 pp»*. Usó
  el cambio en puntos porcentuales, no la variación porcentual.
- **Pregunta 10 (remesas):** respondió 1 359.65 e identificó el trimestre: *«periodo 2025-T4 (mayor valor entre
  2024-T1 y 2025-T4)»*. Pidió bien las fechas trimestrales y no confundió el pico de 2024 con el de 2025.
- **Pregunta 5 (tipo de cambio):** redondeó 3.42821 a 3.428. La diferencia (0.0002) está dentro de la tolerancia
  (0.002).

**El costo del MCP es el tiempo:** 31.6 segundos por pregunta frente a 11.6, porque el modelo da en promedio 4.6
turnos en vez de 2: además de responder, tiene que llamar a las herramientas y esperar sus datos.

## 7. Cifras del MCP comprobadas a mano en la web del BCRP

1. **Inflación de alimentos y bebidas a 12 meses (PN09822PM).** La tabla de la web muestra **8.29** en setiembre
   de 2023 y **3.99** en setiembre de 2026, de donde el cambio es 3.99 − 8.29 = **−4.30** puntos. El MCP dio
   exactamente esas cifras.
   https://estadisticas.bcrp.gob.pe/estadisticas/series/mensuales/resultados/PN09822PM/html/2023-9/2026-9/
2. **Remesas del exterior en el cuarto trimestre de 2025 (PN38986BQ).** La tabla de la web muestra **1 360**
   millones de US$, el mayor de los ocho trimestres de 2024 y 2025. El MCP dio 1 359.65; la web redondea a enteros.
   https://estadisticas.bcrp.gob.pe/estadisticas/series/trimestrales/resultados/PN38986BQ/html/2024-1/2025-4/

## 8. Conclusión

Sin herramientas, Claude Haiku no inventó cifras cuando se le permitió decir «no sé», pero tampoco respondió
ninguna: su utilidad fue nula. Con el servidor MCP acertó las 10 preguntas, cada una con su fuente, a cambio de
casi el triple de tiempo (4.6 turnos frente a 2). Construir un MCP vale la pena cuando las preguntas son frecuentes, piden cifras oficiales
recientes (posteriores a lo que el modelo aprendió) o cálculos que el modelo no debe hacer de memoria, como
variaciones y máximos, y cuando cada cifra debe poder citarse y repetirse. Para preguntas ocasionales sobre cifras
ya publicadas en titulares, una búsqueda web puede bastar; en este trabajo no se midió ese modo.

## 9. Limitaciones

- Es una sola corrida, con un solo modelo (Haiku); con otro modelo o en otra corrida los resultados pueden variar.
- No se hizo el experimento extra: ni el modo de búsqueda web ni la versión sin la instrucción «no estimes». Por
  eso no se sabe si, sin permiso para decir «no sé», el modelo habría inventado cifras.
- Las cifras corresponden a los datos del BCRP disponibles el 28 de octubre de 2026; si el BCRP revisa una serie,
  la verdad de alguna pregunta puede cambiar.

## 10. Cómo repetir la medición

```bash
uv run pytest -q        # el contrato: 8 passed
uv run evaluar.py       # 20 llamadas a claude -p con Haiku; escribe resultados.csv
uv run grafico.py       # escribe grafico.png
```

Se necesita `uv`, Claude Code con la sesión iniciada e internet. En `evaluar.py` se agregó `encoding="utf-8"` al
leer la respuesta de `claude -p`: en Windows, Python usaba por defecto la codificación cp1252 y fallaba con las
tildes.
