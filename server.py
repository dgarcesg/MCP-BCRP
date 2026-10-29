"""Servidor MCP del BCRP. Empiecen aquí: buscar_series ya funciona; completen los TODO hasta que pasen las pruebas.

    uv run pytest                                           # el contrato: las 8 pruebas deben pasar
    uv run server.py                                        # el servidor, por stdio
    claude mcp add --scope project bcrp -- uv run server.py # conectarlo a Claude Code

Las cuentas las hace Python, no el modelo: así cada cifra sale de una llamada que se puede repetir.
"""
import json
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
    sin dato) y la URL de la fuente, que hay que citar. Para variaciones, promedios o extremos usen resumen.
    """
    ficha = _ficha(codigo)
    frecuencia = ficha["frecuencia"]
    url = f"{API}/{codigo}/json/{_fecha_api(desde, frecuencia)}/{_fecha_api(hasta, frecuencia)}"
    datos = [{"periodo": _periodo(p["name"], frecuencia), "valor": float(p["values"][0])}
             for p in _descargar(url) if p["values"][0] != "n.d."]
    return {"codigo": codigo, "nombre": ficha["nombre"], "frecuencia": frecuencia, "datos": datos, "fuente": url}

# TODO 2 · resumen: las cuentas las hace Python, a partir de serie, para que el modelo nunca calcule a mano.
@mcp.tool(annotations=SOLO_LECTURA)
def resumen(codigo: str, desde: str, hasta: str) -> dict:
    """Las cuentas de una serie del BCRP entre dos fechas, ya hechas: primer y último dato, cambio, variación
    porcentual, promedio, máximo y mínimo (los datos con su periodo). Úsenla siempre que la pregunta pida una
    variación, un promedio o un extremo, en vez de calcularlos a mano.

    Las fechas se escriben como en serie: "2026-10-15" (diaria), "2025-01" (mensual), "2025-T1" (trimestral) o
    "2025" (anual). cambio va en la unidad de la serie: si la serie ya es un porcentaje (como la inflación),
    cambio son puntos porcentuales y variacion_pct es la variación de esa tasa, que casi nunca es lo que se pregunta.
    """
    s = serie(codigo, desde, hasta)
    datos = s["datos"]
    if not datos:
        raise ToolError(f"La serie {codigo} no tiene datos entre {desde} y {hasta}.")
    primero, ultimo = datos[0], datos[-1]
    valores = [d["valor"] for d in datos]
    cambio = ultimo["valor"] - primero["valor"]
    return {"codigo": codigo, "nombre": s["nombre"], "frecuencia": s["frecuencia"], "n_datos": len(datos),
            "primero": primero, "ultimo": ultimo, "cambio": round(cambio, 4),
            # abs: si el primer valor es negativo, el signo sigue diciendo si la serie subió o bajó
            "variacion_pct": round(100 * cambio / abs(primero["valor"]), 2) if primero["valor"] else None,
            "promedio": round(sum(valores) / len(valores), 4),
            "maximo": max(datos, key=lambda d: d["valor"]),
            "minimo": min(datos, key=lambda d: d["valor"]),
            "fuente": s["fuente"]}

# TODO 3 · comparar_paises: el Perú frente a otros países, con la API del Banco Mundial (tampoco pide clave).
BANCO_MUNDIAL = "https://api.worldbank.org/v2/country"


@mcp.tool(annotations=SOLO_LECTURA)
def comparar_paises(paises: str = "PER;CHL;COL", indicador: str = "NY.GDP.MKTP.KD.ZG",
                    desde: int = 2015, hasta: int = 2025) -> dict:
    """Compara al Perú con otros países con datos anuales del Banco Mundial, que el BCRP no publica. Úsenla para
    preguntas como "¿creció más el Perú que Chile?" o "¿cómo está la inflación del Perú frente a la región?".

    paises: códigos ISO de 3 letras separados por ";", por ejemplo "PER;CHL;COL;MEX;BRA".
    indicador: código del Banco Mundial. Los más usados: "NY.GDP.MKTP.KD.ZG" (crecimiento del PBI real, %),
    "FP.CPI.TOTL.ZG" (inflación anual, %), "SL.UEM.TOTL.ZS" (desempleo, % de la fuerza laboral),
    "NY.GDP.PCAP.CD" (PBI per cápita, US$ corrientes) y "NE.EXP.GNFS.ZS" (exportaciones, % del PBI).
    Devuelve, por país, el valor de cada año y el promedio del periodo, y la URL de la fuente. Para cifras del
    Perú de fuente oficial peruana usen serie o resumen.
    """
    codigos = paises.upper().replace(",", ";").replace(" ", "")
    url = f"{BANCO_MUNDIAL}/{codigos}/indicator/{indicador}?format=json&date={desde}:{hasta}&per_page=1000"
    respuesta = httpx.get(url, timeout=60).json()
    filas = respuesta[1] if len(respuesta) > 1 and respuesta[1] else []  # si hay un error, solo llega un aviso
    por_pais = {}
    for fila in sorted(filas, key=lambda f: f["date"]):  # llegan del año más reciente al más antiguo
        if fila["value"] is not None:
            por_pais.setdefault(fila["country"]["value"], []).append(
                {"anio": int(fila["date"]), "valor": round(fila["value"], 4)})
    if not por_pais:
        raise ToolError(f"El Banco Mundial no tiene datos de {indicador!r} para {paises!r} entre {desde} y {hasta}. "
                        "Revisen los códigos: países como 'PER;CHL;COL' e indicadores como 'NY.GDP.MKTP.KD.ZG'.")
    return {"indicador": filas[0]["indicator"]["value"],
            "paises": {pais: {"datos": datos, "promedio": round(sum(d["valor"] for d in datos) / len(datos), 4)}
                       for pais, datos in por_pais.items()},
            "fuente": url}

# TODO 4 · Recurso: la ficha de una serie. En Claude Code se adjunta con @bcrp:bcrp://serie/PN01273PM
@mcp.resource("bcrp://serie/{codigo}", mime_type="application/json")
def ficha_serie(codigo: str) -> str:
    """La ficha de una serie del BCRP: nombre, categoría, frecuencia, desde cuándo hay datos y última actualización."""
    return json.dumps(_ficha(codigo), ensure_ascii=False, indent=2)


# TODO 5 · Prompt: un informe que cita el código y el periodo de cada cifra. En Claude Code: /mcp__bcrp__informe inflación
@mcp.prompt
def informe(tema: str) -> str:
    """Un informe breve sobre un tema de la economía peruana, con cada cifra sacada del BCRP y citada."""
    return (f"Escribe un informe breve sobre {tema} en el Perú con datos oficiales del BCRP. Usa los últimos 12 meses "
            "disponibles, salvo que el tema pida otro periodo.\n"
            "1. Busca las series que correspondan con buscar_series.\n"
            "2. Saca las cifras con resumen (variaciones, promedios y extremos) o con serie (datos puntuales). "
            "No calcules nada a mano.\n"
            "3. Si ayuda compararlo con otros países, usa comparar_paises.\n"
            "4. Cita cada cifra con el código de la serie y el periodo, por ejemplo: 4.55 % (PN01273PM, 2026-09).\n"
            "5. Termina con la lista de fuentes (URL) y di qué no encontraste, en vez de estimarlo.")


if __name__ == "__main__":
    mcp.run()
