"""La figura del informe: cuántas preguntas acertó Claude en cada modo, a partir de resultados.csv.

    uv run grafico.py    # escribe grafico.png
"""
from pathlib import Path

import pandas as pd
from matplotlib.figure import Figure
from matplotlib.patches import Patch

AQUI = Path(__file__).parent
RESULTADOS = ["acierta", "se equivoca", "no sabe"]
COLORES = {"acierta": "#0ca30c", "se equivoca": "#d03b3b", "no sabe": "#b9b7b0"}
EN_LA_BARRA = {"acierta": "aciertos", "se equivoca": "errores", "no sabe": "«no sé»"}
TINTA, TINTA_SUAVE, FONDO, GRILLA = "#0b0b0b", "#52514e", "#fcfcfb", "#e4e2dc"

res = pd.read_csv(AQUI / "resultados.csv")
conteo = res.groupby("modo").resultado.value_counts().unstack(fill_value=0).reindex(columns=RESULTADOS, fill_value=0)
segundos = res.groupby("modo").segundos.mean()
total = res.id.nunique()
modos = {"mcp": "Con el servidor bcrp (MCP)", "memoria": "Sin herramientas (memoria)"}  # de abajo hacia arriba

fig = Figure(figsize=(9, 3.4), facecolor=FONDO, layout="constrained")
ax = fig.add_subplot(facecolor=FONDO)
for y, (modo, nombre) in enumerate(modos.items()):
    izquierda = 0
    for resultado in RESULTADOS:
        n = conteo.loc[modo, resultado]
        if n:
            ax.barh(y, n, left=izquierda, height=0.55, color=COLORES[resultado], edgecolor=FONDO, linewidth=2)
            ax.text(izquierda + n / 2, y, f"{n} {EN_LA_BARRA[resultado]}", ha="center", va="center", color=TINTA, fontsize=11)
            izquierda += n
ax.set_yticks(range(len(modos)), [f"{nombre}\n{segundos[m]:.0f} s por pregunta" for m, nombre in modos.items()],
              color=TINTA, fontsize=10)
ax.set_xlim(0, total)
ax.set_xticks(range(0, total + 1, 2))
ax.set_xlabel(f"Preguntas (de {total})", color=TINTA_SUAVE)
ax.tick_params(colors=TINTA_SUAVE, length=0)
ax.grid(axis="x", color=GRILLA, linewidth=1)
ax.set_axisbelow(True)
for borde in ax.spines.values():
    borde.set_visible(False)
ax.legend(handles=[Patch(color=COLORES[r], label=r) for r in RESULTADOS], loc="lower left", bbox_to_anchor=(0, 1.02),
          ncol=3, frameon=False, labelcolor=TINTA)
fig.suptitle(f"¿Acierta Claude cifras oficiales del BCRP? ({total} preguntas, modelo Haiku)", x=0.01, ha="left",
             color=TINTA, fontsize=13)
fig.savefig(AQUI / "grafico.png", dpi=150)
print("grafico.png listo")
