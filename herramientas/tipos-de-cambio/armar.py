"""Arma «Tipos de cambio.html»: un solo archivo, con las cotizaciones, los feriados y las letras adentro y sin nada externo.

    python herramientas/tipos-de-cambio/armar.py

Mete adentro de fuente.html:
  - las cotizaciones de cotizaciones.json (las baja del Banco Nación actualizar.py), en forma corta: «AAMMDD compra venta|…»;
  - el calendario de feriados.json: los feriados nacionales y días no laborables que publica el Ministerio del Interior (también los baja
    actualizar.py) y los días sin bancos que no están ahí: el Día del Bancario (6 de noviembre) y los feriados bancarios del BCRA;
  - las letras Barlow y Barlow Semi Condensed 5.3.0 (de @fontsource, licencia SIL Open Font 1.1: vendor/LICENSE-barlow.txt).
La página no se conecta a nada: quien la abre ve lo que trae el archivo.
Hecho por Elvis Chatzky.
"""
import base64
import json
import re
from datetime import date
from pathlib import Path

AQUI = Path(__file__).resolve().parent
HERRAMIENTAS = AQUI.parent
FUENTE = AQUI / "fuente.html"
DATOS = AQUI / "cotizaciones.json"
FERIADOS = AQUI / "feriados.json"
VENDOR = AQUI / "vendor"
SALIDA = HERRAMIENTAS / "Tipos de cambio.html"
CLASES = ("billete", "divisa")
LETRAS = (  # familia, peso, archivo
    ("Barlow", 400, "barlow-5.3.0-latin-400.woff2"),
    ("Barlow", 500, "barlow-5.3.0-latin-500.woff2"),
    ("Barlow", 600, "barlow-5.3.0-latin-600.woff2"),
    ("Barlow Semi Condensed", 600, "barlow-semi-condensed-5.3.0-latin-600.woff2"),
    ("Barlow Semi Condensed", 700, "barlow-semi-condensed-5.3.0-latin-700.woff2"),
)
# tipo del calendario oficial → (clase, cómo se lo llama, si ese día no abren los bancos)
TIPOS = {
    "inamovible": ("nacional", "Feriado nacional", True),
    "trasladable": ("nacional", "Feriado nacional", True),
    "turistico": ("turistico", "Feriado turístico", True),
    "no_laborable": ("no_laborable", "Día no laborable", True),
    "especial": ("regional", "Feriado regional", False),
    "bancario": ("bancario", "Feriado bancario", True),
}
# los días no laborables que el calendario marca con (a), (b) o (c) son optativos (para una comunidad): los bancos abren
_OPTATIVO = re.compile(r"\s*\(([abc])\)\s*$")
DIA_DEL_BANCARIO = ("Día del Bancario", "art. 50 de la Convención Colectiva de Trabajo 18/75: los bancos no atienden al público")
_FRASES = {"nacional": "feriado nacional ({})", "no_laborable": "día no laborable ({})", "bancario": "feriado bancario ({})"}


def _numero(x: float) -> str:
    """1520.0 → «1520»; 1536.5 → «1536.5» (el BNA publica hasta 4 decimales)."""
    return f"{x:.4f}".rstrip("0").rstrip(".")


def compacto(dias: dict) -> str:
    """{"2026-11-05": [1520, 1570], …} → «261105 1520 1570|…», en orden de fecha."""
    return "|".join(f"{d[2:4]}{d[5:7]}{d[8:10]} {_numero(dias[d][0])} {_numero(dias[d][1])}" for d in sorted(dias))


def _frase(clase: str, nombre: str) -> str:
    """Cómo se dice en la página: «Ayer … fue <frase>»."""
    if nombre == DIA_DEL_BANCARIO[0]:
        return "Día del Bancario (no abren los bancos)"
    if clase == "turistico":
        return "feriado turístico (día no laborable con fines turísticos)"
    if clase in _FRASES:
        return _FRASES[clase].format(nombre)
    return nombre[:1].lower() + nombre[1:]


def calendario(feriados: dict, anios_extra=()) -> list:
    """Todos los días del calendario, en orden: {"fecha", "clase", "nombre", "etiqueta", "cierra", "frase", "fuente"}.
    Junta los años del calendario oficial (sin repetir: el 1° de enero viene en el año que termina y en el que empieza), los feriados
    bancarios escritos a mano y el Día del Bancario de cada año (el del calendario y los de `anios_extra`) que cae en un día hábil."""
    out, vistos = [], set()

    def sumar(fecha, clase, nombre, etiqueta, cierra, fuente=""):
        clave = (fecha, clase, nombre.lower())
        if clave not in vistos:
            vistos.add(clave)
            out.append({"fecha": fecha, "clase": clase, "nombre": nombre, "etiqueta": etiqueta, "cierra": cierra, "frase": _frase(clase, nombre), "fuente": fuente})

    anios = feriados.get("años") or {}
    # primero los días de cada año en su propio calendario; después lo que un calendario trae del año siguiente
    propios = [(f, t, n) for a in sorted(anios) for f, t, n in anios[a]["dias"] if f[:4] == a]
    ajenos = [(f, t, n) for a in sorted(anios) for f, t, n in anios[a]["dias"] if f[:4] != a]
    for fecha, tipo, nombre in propios + ajenos:
        limpio = re.sub(r"\s+", " ", _OPTATIVO.sub("", nombre)).strip()
        clase, etiqueta, cierra = TIPOS.get(tipo, (tipo, tipo.replace("_", " ").capitalize(), False))
        if tipo == "no_laborable" and _OPTATIVO.search(nombre):
            clase, etiqueta, cierra = "optativo", "Día no laborable optativo", False
        sumar(fecha, clase, limpio, etiqueta, cierra)
    for b in feriados.get("bancarios") or []:
        sumar(b["fecha"], "bancario", b["nombre"], "Feriado bancario", True, b.get("fuente", ""))
    for anio in sorted({int(a) for a in anios} | {int(a) for a in anios_extra}):
        d = date(anio, 11, 6)
        if d.weekday() < 5:
            sumar(d.isoformat(), "bancario", DIA_DEL_BANCARIO[0], "Feriado bancario", True, DIA_DEL_BANCARIO[1])
    return sorted(out, key=lambda x: x["fecha"])


def leer_feriados(ruta: Path) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else {"años": {}, "bancarios": []}


def _letras() -> str:
    reglas = []
    for familia, peso, archivo in LETRAS:
        dato = base64.b64encode((VENDOR / archivo).read_bytes()).decode("ascii")
        reglas.append(f'@font-face {{ font-family: "{familia}"; font-style: normal; font-weight: {peso}; font-display: swap; '
                      f'src: url(data:font/woff2;base64,{dato}) format("woff2"); }}')
    return "/* Barlow y Barlow Semi Condensed 5.3.0 · licencia SIL Open Font 1.1 (tipos-de-cambio/vendor/LICENSE-barlow.txt) */\n" + "\n".join(reglas)


def _datos(ruta: Path, ruta_feriados: Path) -> str:
    d = json.loads(ruta.read_text(encoding="utf-8"))
    f = leer_feriados(ruta_feriados)
    anios_cotizacion = {int(k[:4]) for c in CLASES for k in d[c]}
    cal = calendario(f, anios_cotizacion)
    feriados = {
        "fuente": f.get("fuente", ""),
        "años": sorted(int(a) for a in f.get("años") or {}),
        "modificado": {a: v.get("modificado", "") for a, v in sorted((f.get("años") or {}).items())},
        "dias": [[x["fecha"], x["clase"], x["nombre"], x["etiqueta"], 1 if x["cierra"] else 0, x["frase"], x["fuente"]] for x in cal],
    }
    corto = {"fuente": d["fuente"], "actualizado": d["actualizado"], **{c: compacto(d[c]) for c in CLASES}, "feriados": feriados}
    return json.dumps(corto, ensure_ascii=False).replace("<", "\\u003c")


def armar(datos: Path = DATOS, feriados: Path = FERIADOS) -> str:
    html = FUENTE.read_text(encoding="utf-8")
    piezas = {
        "/*FUENTES*/": _letras(),
        '<script type="application/json" id="datos">/*DATOS*/</script>': '<script type="application/json" id="datos">' + _datos(datos, feriados) + "</script>",
    }
    for marca, contenido in piezas.items():
        if html.count(marca) != 1:
            raise SystemExit(f"No encuentro {marca} en {FUENTE.name}")
        html = html.replace(marca, contenido)
    return html


if __name__ == "__main__":
    SALIDA.write_text(armar(), encoding="utf-8", newline="\n")
    print(f"Listo: {SALIDA} ({SALIDA.stat().st_size // 1024} KB)")
