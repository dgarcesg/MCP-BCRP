"""Servidor MCP del BCRP. Empiecen aquí: buscar_series ya funciona; completen los TODO hasta que pasen las pruebas.

    uv run pytest                                           # el contrato: las 8 pruebas deben pasar
    uv run server.py                                        # el servidor, por stdio
    claude mcp add --scope project bcrp -- uv run server.py # conectarlo a Claude Code

Las cuentas las hace Python, no el modelo: así cada cifra sale de una llamada que se puede repetir.
"""
import re
import time
import unicodedata
from datetime import date
from functools import cache
from pathlib import Path

import httpx
import pandas as pd
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

AQUI = Path(__file__).parent
CATALOGO = AQUI / "datos" / "catalogo_bcrp.csv"
URL_CATALOGO = "https://estadisticas.bcrp.gob.pe/estadisticas/series/metadata"
API = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api"
SOLO_LECTURA = {"readOnlyHint": True, "openWorldHint": True}

mcp = FastMCP("bcrp", instructions=(
    "Series oficiales del Banco Central de Reserva del Perú (BCRP). Primero busca el código con buscar_series; "
    "luego usa resumen para variaciones, promedios y extremos, y serie para los datos. No calcules a mano: "
    "cita siempre el código de la serie y el periodo."))


def _sin_tildes(s):
    return unicodedata.normalize("NFD", str(s).lower()).encode("ascii", "ignore").decode()


@cache
def catalogo():
    """El catálogo oficial: 17 mil series en unos 7 MB. Se baja una vez y queda en datos/."""
    if not CATALOGO.exists():
        CATALOGO.parent.mkdir(exist_ok=True)
        r = httpx.get(URL_CATALOGO, timeout=120)
        r.raise_for_status()
        CATALOGO.write_text(r.content.decode("latin-1"), encoding="utf-8")
    df = pd.read_csv(CATALOGO, sep=";", dtype=str).fillna("")
    df = df.rename(columns={"Código de serie": "codigo", "Categoría de serie": "categoria", "Grupo de serie": "grupo",
                            "Nombre de serie": "nombre", "Frecuencia": "frecuencia",
                            "Fecha de actualización": "actualizada", "Fecha de inicio": "inicio"})
    df["texto"] = (df.categoria + " " + df.grupo + " " + df.nombre).map(_sin_tildes)
    return df


def _ficha(codigo):
    fila = catalogo().query("codigo == @codigo")
    if fila.empty:
        raise ToolError(f"No existe el código de serie {codigo!r}. Búsquenlo con buscar_series.")
    f = fila.iloc[0]
    return {"codigo": f.codigo, "nombre": f"{f.grupo} - {f.nombre}", "categoria": f.categoria,
            "frecuencia": f.frecuencia, "inicio": f.inicio, "actualizada": f.actualizada}


@mcp.tool(annotations=SOLO_LECTURA)
def buscar_series(texto: str, frecuencia: str | None = None, limite: int = 10) -> list[dict]:
    """Busca series del BCRP por palabras: todas deben aparecer en la categoría, el grupo o el nombre.

    Ejemplos: "ipc 12 meses", "tipo de cambio interbancario venta", "reservas internacionales netas",
    "tasa de referencia", "cobre precio". frecuencia: "Diaria", "Mensual", "Trimestral" o "Anual".
    Devuelve el código, el nombre completo, la frecuencia y desde cuándo hay datos. Si no hay resultados,
    prueben con menos palabras.
    """
    df = catalogo()
    m = pd.Series(True, index=df.index)
    for palabra in _sin_tildes(texto).split():
        m &= df.texto.str.contains(re.escape(palabra))
    if frecuencia:
        m &= df.frecuencia.str.lower() == frecuencia.lower()
    # primero las series vigentes y, entre ellas, las de nombre más corto (las más generales)
    sel = df[m]
    orden = sel.assign(vieja=sel.actualizada < "2025", largo=(sel.grupo + sel.nombre).str.len())
    return [_ficha(c) for c in orden.sort_values(["vieja", "largo"]).head(limite).codigo]


# TODO 1 · serie: traduce las fechas a lo que pide la API, descarga con reintentos y traduce los periodos de vuelta.
MESES = {"Ene": 1, "Feb": 2, "Mar": 3, "Abr": 4, "May": 5, "Jun": 6,
         "Jul": 7, "Ago": 8, "Set": 9, "Sep": 9, "Oct": 10, "Nov": 11, "Dic": 12}  # setiembre llega como Set o Sep
FECHAS = {  # cómo se escribe la fecha según la frecuencia de la serie: (patrón, ejemplo)
    "Diaria": (r"\d{4}-\d{2}-\d{2}", "2026-10-15"),
    "Mensual": (r"\d{4}-\d{1,2}", "2025-01"),
    "Trimestral": (r"\d{4}-T?[1-4]", "2025-T1"),
    "Anual": (r"\d{4}", "2025"),
}


def _fecha_api(fecha, frecuencia):
    """La fecha como la pide la API: "2025-01" → "2025-1", "2025-T1" → "2025-1"; diarias y anuales no cambian."""
    patron, ejemplo = FECHAS[frecuencia]
    if not re.fullmatch(patron, fecha):
        raise ToolError(f"La serie es {frecuencia.lower()}: escriban las fechas como {ejemplo!r}, no {fecha!r}.")
    if frecuencia in ("Mensual", "Trimestral"):
        anio, n = fecha.split("-")
        return f"{anio}-{int(n.lstrip('T'))}"
    return fecha


def _anio(aa):
    """Los años de dos dígitos de la API: "26" → 2026, "97" → 1997."""
    anio = 2000 + int(aa)
    return anio if anio <= date.today().year else anio - 100


def _periodo(nombre, frecuencia):
    """El periodo de la API en formato estándar: "Ene.2025" → "2025-01", "01.Oct.26" → "2026-10-01",
    "T1.25" → "2025-T1"; los anuales ("2025") no cambian."""
    partes = nombre.split(".")
    if frecuencia == "Mensual":
        mes, anio = partes
        return f"{anio}-{MESES[mes]:02d}"
    if frecuencia == "Diaria":
        dia, mes, aa = partes
        return f"{_anio(aa)}-{MESES[mes]:02d}-{dia}"
    if frecuencia == "Trimestral":
        trimestre, aa = partes
        return f"{_anio(aa)}-{trimestre}"
    return nombre


@cache
def _descargar(url):
    """Los periodos que devuelve la API. Si responde una página HTML en vez de JSON (pasa cuando recibe muchos
    pedidos seguidos), espera y reintenta. @cache guarda lo ya bajado para no pedirlo dos veces."""
    for espera in (1, 3, 6, 0):
        try:
            return httpx.get(url, timeout=60).json()["periods"]
        except ValueError:  # no era JSON
            time.sleep(espera)
    raise ToolError("El BCRP no respondió con datos. Esperen unos segundos y vuelvan a intentar.")


@mcp.tool(annotations=SOLO_LECTURA)
def serie(codigo: str, desde: str, hasta: str) -> dict:
    """Datos oficiales de una serie del BCRP entre dos fechas, ambas incluidas. Primero busquen el código con
    buscar_series.

    Las fechas siguen la frecuencia de la serie: "2026-10-15" (diaria), "2025-01" (mensual), "2025-T1" (trimestral)
    o "2025" (anual). Devuelve el nombre, la frecuencia, los datos como [{"periodo", "valor"}] (sin los periodos
    sin dato) y la URL de la fuente, que hay que citar.
    """
    ficha = _ficha(codigo)
    frecuencia = ficha["frecuencia"]
    url = f"{API}/{codigo}/json/{_fecha_api(desde, frecuencia)}/{_fecha_api(hasta, frecuencia)}"
    datos = [{"periodo": _periodo(p["name"], frecuencia), "valor": float(p["values"][0])}
             for p in _descargar(url) if p["values"][0] != "n.d."]
    return {"codigo": codigo, "nombre": ficha["nombre"], "frecuencia": frecuencia, "datos": datos, "fuente": url}

# TODO 2 · resumen(codigo, desde, hasta): primero, ultimo, cambio, variacion_pct, promedio, maximo y minimo
#   (los tres últimos con su periodo). Úsenla para que el modelo nunca haga cuentas a mano.

# TODO 3 · Una herramienta suya, bien descrita. Ideas:
#   - comparar_paises con la API del Banco Mundial, que tampoco pide clave:
#     https://api.worldbank.org/v2/country/PER;CHL;COL/indicator/NY.GDP.MKTP.KD.ZG?format=json&date=2015:2025
#   - correlacion(codigo_a, codigo_b, desde, hasta)
#   - grafico(codigo, desde, hasta) que guarde un PNG en salidas/ y devuelva la ruta

# TODO 4 · Un recurso, por ejemplo la plantilla bcrp://serie/{codigo} con la ficha de la serie.

# TODO 5 · Un prompt, por ejemplo informe(tema) que pida citar el código y el periodo de cada cifra.


if __name__ == "__main__":
    mcp.run()
