"""Baja del Banco Nación las cotizaciones del dólar que faltan, y del Ministerio del Interior los feriados, y arma «Tipos de cambio.html».

    python herramientas/tipos-de-cambio/actualizar.py                      # lo que falta, desde la última cotización guardada
    python herramientas/tipos-de-cambio/actualizar.py --desde 01/01/2025   # desde otra fecha
    python herramientas/tipos-de-cambio/actualizar.py --copiar-a CARPETA   # además deja una copia de la página en esa carpeta
    python herramientas/tipos-de-cambio/actualizar.py --csv-billetes b.csv --csv-divisas d.csv   # sin internet: los .csv bajados a mano
    pythonw herramientas/tipos-de-cambio/actualizar.py --programado        # lo que corre la tarea programada (programar_tipos_de_cambio.bat):
                                                                           # sin ventana; lo que pasó queda en registro.txt

Qué sale de la máquina: pedidos a www.bna.com.ar, a la descarga «por rango de fechas» de su página de cotizaciones, con la moneda
(Dolar U.S.A), la clase (billetes o divisas) y las dos fechas; y pedidos a www.argentina.gob.ar por el calendario de feriados de cada año
(el archivo que usa su página de feriados), con el año. Nada más: ni datos de la empresa ni de quien lo corre.
Si algo de lo que contesta el BNA no cierra, no se cambia nada y se dice por qué. Si el calendario de un año no se puede bajar o no tiene
la forma de siempre, queda el que estaba y se avisa. Al final contrasta las dos cosas: un día hábil en que el BNA no publicó y que no figura
como feriado, o un feriado con cotización, se avisan para revisar.
Usa solo lo que trae Python (no hay que instalar nada).
Hecho por Elvis Chatzky.
"""
import argparse
import importlib.util
import traceback
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

AQUI = Path(__file__).resolve().parent
DATOS = AQUI / "cotizaciones.json"
FERIADOS = AQUI / "feriados.json"
REGISTRO = AQUI / "registro.txt"   # lo que pasó en las corridas programadas (no va al repositorio)
RENGLONES_REGISTRO = 600
SALIDA = AQUI.parent / "Tipos de cambio.html"
DIRECCION = "https://www.bna.com.ar/Cotizador/DescargarPorFecha"
FUENTE = "Banco de la Nación Argentina (bna.com.ar): descarga por rango de fechas, Dolar U.S.A, billetes y divisas"
# el calendario de feriados de argentina.gob.ar/feriados: un archivo por año (JSON-LD de schema.org), el que lee esa misma página
DIRECCION_FERIADOS = "https://www.argentina.gob.ar/sites/default/files/holidays-{anio}-es.json"
FUENTE_FERIADOS = "Ministerio del Interior (argentina.gob.ar/feriados): feriados nacionales y días no laborables"
# cómo pide el BNA cada clase: el número de la moneda (Dolar U.S.A) y el nombre de la solapa
CLASES = {"billete": {"idMonedaDescarga": "22", "id": "billetes"}, "divisa": {"idMonedaDescarga": "55", "id": "monedas"}}
NOMBRE = {"billete": "Dólar billete", "divisa": "Dólar divisa"}
QUIEN_PIDE = "tipos-de-cambio/1.0 (tabla de cotizaciones; Python-urllib)"
PRIMER_DIA = date(2025, 1, 1)
REPASO = 10      # días hacia atrás que se vuelven a pedir, por si el BNA corrigió alguno
TRAMO = 180      # días por pedido
ESPERA = 30      # segundos


class Falla(Exception):
    """Algo no salió: el mensaje es para quien lo corre."""


def _numero(x) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".")


def _dma(d: date) -> str:
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def _importe(texto: str):
    """«1495,0000», «1191,00» o «1.495,00» → número; otra cosa → None."""
    t = texto.strip()
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", t):
        t = t.replace(".", "")
    if not re.fullmatch(r"\d+(?:,\d+)?", t):
        return None
    return float(t.replace(",", "."))


def leer_csv(texto: str):
    """El .csv del BNA («Moneda;Fecha cotizacion;Compra;Venta;») → ({"AAAA-MM-DD": [compra, venta]}, filas del dólar que no se entienden).
    Las otras monedas se saltean. Si no es un .csv del BNA, ValueError."""
    lineas = [x.strip() for x in texto.lstrip("﻿").splitlines() if x.strip()]
    if not lineas or not re.match(r"Moneda;Fecha\s+cotizaci", lineas[0], re.I):
        raise ValueError("no es un .csv de cotizaciones del BNA (tiene que empezar con «Moneda;Fecha cotizacion;Compra;Venta;»)")
    dias, malas = {}, []
    for linea in lineas[1:]:
        campos = [c.strip() for c in linea.split(";")]
        if not re.fullmatch(r"dolar\s+u\.?\s?s\.?\s?a\.?", campos[0], re.I):
            continue
        f = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", campos[1]) if len(campos) >= 4 else None
        compra, venta = (_importe(campos[2]), _importe(campos[3])) if f else (None, None)
        try:
            dia = date(int(f.group(3)), int(f.group(2)), int(f.group(1))) if f else None
        except ValueError:
            dia = None
        if dia is None or compra is None or venta is None or compra <= 0 or venta < compra or venta > compra * 1.5:
            malas.append(linea)
            continue
        dias[dia.isoformat()] = [compra, venta]
    return dias, malas


def pedir(clase: str, desde: date, hasta: date, direccion: str = DIRECCION) -> str:
    """Le pide al BNA las cotizaciones de esa clase entre las dos fechas; devuelve el texto del .csv."""
    consulta = urllib.parse.urlencode({"idMonedaDescarga": CLASES[clase]["idMonedaDescarga"], "fechaDesde": _dma(desde), "fechaHasta": _dma(hasta),
                                       "id": CLASES[clase]["id"], "descargar": ""})
    pedido = urllib.request.Request(f"{direccion}?{consulta}", headers={"User-Agent": QUIEN_PIDE, "Accept": "text/csv,*/*"})
    ultima = None
    for intento in (1, 2):
        try:
            with urllib.request.urlopen(pedido, timeout=ESPERA) as r:
                crudo = r.read()
            break
        except urllib.error.HTTPError as e:
            raise Falla(f"El BNA contestó con el error {e.code} al pedir {NOMBRE[clase].lower()} del {_dma(desde)} al {_dma(hasta)}.") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            ultima = e
            if intento == 1:
                time.sleep(3)
    else:
        raise Falla(f"No se pudo llegar a www.bna.com.ar ({getattr(ultima, 'reason', ultima)}). ¿Hay internet en esta máquina?") from ultima
    try:
        return crudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        return crudo.decode("latin-1")


def pedir_feriados(anio: int, direccion: str = DIRECCION_FERIADOS):
    """El calendario de feriados de ese año, como texto; None si todavía no está publicado (la página contesta 404)."""
    pedido = urllib.request.Request(direccion.format(anio=anio), headers={"User-Agent": QUIEN_PIDE, "Accept": "application/json,*/*"})
    try:
        with urllib.request.urlopen(pedido, timeout=ESPERA) as r:
            crudo = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise Falla(f"argentina.gob.ar contestó con el error {e.code} al pedir los feriados de {anio}.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Falla(f"no se pudo llegar a www.argentina.gob.ar ({getattr(e, 'reason', e)})") from e
    return crudo.decode("utf-8-sig", errors="replace")


def leer_feriados(texto: str, anio: int) -> dict:
    """El calendario oficial (JSON-LD: mainEntity.itemListElement[].item con startDate, name y la propiedad «tipo») →
    {"nombre", "modificado", "dias": [[fecha, tipo, nombre], …]}. Si no tiene esa forma, ValueError."""
    try:
        j = json.loads(texto)
    except ValueError as e:
        raise ValueError("no es el calendario de feriados (no es un JSON)") from e
    items = (j.get("mainEntity") or {}).get("itemListElement") if isinstance(j, dict) else None
    if not isinstance(items, list):
        raise ValueError("no es el calendario de feriados (no trae la lista de días)")
    if j.get("name") and str(anio) not in str(j.get("name")):
        raise ValueError(f"es el calendario de otro año («{j.get('name')}»)")
    dias = []
    for e in items:
        it = (e or {}).get("item") or {}
        props = it.get("additionalProperty")
        props = props if isinstance(props, list) else [props] if props else []
        tipo = next((p.get("value") for p in props if isinstance(p, dict) and p.get("name") == "tipo"), None)
        fecha, nombre = str(it.get("startDate") or ""), str(it.get("name") or "").strip()
        try:
            dia = date.fromisoformat(fecha)
        except ValueError:
            dia = None
        if dia is None or not tipo or not nombre or abs(dia.year - anio) > 1:
            raise ValueError(f"tiene un día que no se entiende ({fecha or '¿sin fecha?'}, «{nombre}»)")
        dias.append([fecha, str(tipo), nombre])
    if sum(1 for d in dias if d[0].startswith(str(anio))) < 8:
        raise ValueError(f"trae muy pocos días de {anio} ({len(dias)})")
    return {"nombre": str(j.get("name") or f"Feriados {anio}"), "modificado": str(j.get("dateModified") or ""), "dias": dias}


def texto_feriados(f: dict) -> str:
    """feriados.json: un día por renglón, en el orden del calendario oficial (así se ve qué cambió de una vez a la otra)."""
    j = lambda x: json.dumps(x, ensure_ascii=False)
    anios = []
    for anio in sorted(f.get("años") or {}):
        a = f["años"][anio]
        dias = ",\n".join(f"        {j(d)}" for d in a["dias"])
        anios.append(f'    {j(anio)}: {{\n      "nombre": {j(a.get("nombre", ""))},\n      "modificado": {j(a.get("modificado", ""))},\n'
                     f'      "bajado": {j(a.get("bajado", ""))},\n      "dias": [\n{dias}\n      ]\n    }}')
    bancarios = ",\n".join(f"    {j(b)}" for b in f.get("bancarios") or [])
    return ("{\n" + f'  "fuente": {j(f.get("fuente") or FUENTE_FERIADOS)},\n  "años": {{\n' + ",\n".join(anios) + "\n  },\n"
            + '  "bancarios": [\n' + bancarios + "\n  ]\n}\n")


def _bajar_feriados(guardado: dict, anios: list, direccion: str, momento: datetime, avisos: list, cada_horas: float = 0) -> dict:
    """Baja el calendario de cada año y lo reemplaza en `guardado`. Devuelve qué pasó con cada año. Un año que se bajó hace menos de
    `cada_horas` no se vuelve a pedir."""
    estado = {}
    for anio in anios:
        clave = str(anio)
        bajado = (guardado["años"].get(clave) or {}).get("bajado")
        if bajado and cada_horas > 0:
            try:
                cuando = datetime.fromisoformat(bajado)
            except ValueError:
                cuando = None
            if cuando and timedelta(0) <= momento - cuando < timedelta(hours=cada_horas):
                estado[clave] = f"al día (bajado el {cuando:%d/%m/%Y} a las {cuando:%H:%M})"
                continue
        try:
            texto = pedir_feriados(anio, direccion)
            if texto is None:
                estado[clave] = "todavía no está publicado"
                if clave in guardado["años"]:
                    avisos.append(f"Feriados de {anio}: argentina.gob.ar ya no lo publica. Queda el que estaba.")
                continue
            nuevo = leer_feriados(texto, anio)
        except (Falla, ValueError) as e:
            estado[clave] = "no se pudo bajar"
            avisos.append(f"Feriados de {anio}: {e}. Queda el que estaba{'' if clave in guardado['años'] else ' (no había ninguno)'}.")
            continue
        viejo = guardado["años"].get(clave)
        antes = {tuple(d) for d in (viejo or {}).get("dias", [])}
        ahora = {tuple(d) for d in nuevo["dias"]}
        if viejo is None:
            estado[clave] = f"nuevo ({len(ahora)} días)"
        elif antes == ahora:
            estado[clave] = "sin cambios"
        else:
            cambios = [f"+ {_dma(date.fromisoformat(d[0]))} {d[2]}" for d in sorted(ahora - antes)] + [f"− {_dma(date.fromisoformat(d[0]))} {d[2]}" for d in sorted(antes - ahora)]
            estado[clave] = "cambió: " + "; ".join(cambios)
        guardado["años"][clave] = {**nuevo, "bajado": momento.isoformat(timespec="seconds")}
    return estado


def contrastar(cotizaciones: dict, feriados: dict, hasta=None) -> list:
    """Las cotizaciones del BNA contra el calendario: los días hábiles sin cotización que no figuran como feriado ni como día sin bancos,
    y los días sin bancos con cotización. Se revisa desde la primera cotización hasta el día anterior a la última actualización (o `hasta`,
    si es antes)."""
    armar = _modulo_armar()
    con = set(cotizaciones["billete"]) | set(cotizaciones["divisa"])
    if not con:
        return []
    cal = armar.calendario(feriados, {int(k[:4]) for k in con})
    cierran = {}
    for x in cal:
        if x["cierra"]:
            cierran.setdefault(x["fecha"], x)
    anios = {int(a) for a in feriados.get("años") or {}}
    tope = date.fromisoformat(cotizaciones["actualizado"][:10]) - timedelta(days=1) if cotizaciones.get("actualizado") else date.fromisoformat(max(con))
    hasta = min(tope, hasta) if hasta else tope
    d, out = date.fromisoformat(min(con)), []
    while d <= hasta:
        k = d.isoformat()
        if d.weekday() < 5 and k not in con and k not in cierran:
            falta = "" if d.year in anios else f" (no está el calendario de feriados de {d.year})"
            out.append(f"El BNA no publicó cotización el {_dma(d)} y ese día no figura como feriado ni como día sin bancos{falta}.")
        d += timedelta(days=1)
    for k in sorted(set(cierran) & con):
        x = cierran[k]
        out.append(f"El BNA publicó cotización el {_dma(date.fromisoformat(k))}, que figura como {x['etiqueta'].lower()} ({x['nombre']}).")
    return out


def leer_datos(ruta: Path) -> dict:
    if not ruta.is_file():
        return {"fuente": FUENTE, "actualizado": None, "billete": {}, "divisa": {}}
    d = json.loads(ruta.read_text(encoding="utf-8"))
    return {"fuente": d.get("fuente") or FUENTE, "actualizado": d.get("actualizado"), "billete": dict(d.get("billete") or {}), "divisa": dict(d.get("divisa") or {})}


def texto_datos(d: dict) -> str:
    """cotizaciones.json: una fecha por renglón, en orden (así se ve qué cambió de una vez a la otra)."""
    def clase(c):
        filas = ",\n".join(f'    "{k}": [{_numero(d[c][k][0])}, {_numero(d[c][k][1])}]' for k in sorted(d[c]))
        return f'  "{c}": {{\n{filas}\n  }}' if filas else f'  "{c}": {{}}'
    return ("{\n" + f'  "fuente": {json.dumps(d["fuente"], ensure_ascii=False)},\n  "actualizado": {json.dumps(d["actualizado"])},\n'
            + clase("billete") + ",\n" + clase("divisa") + "\n}\n")


def _escribir(ruta: Path, texto: str) -> None:
    """Primero a un archivo al lado y después se cambia de nombre: si se corta, queda el anterior entero."""
    provisorio = ruta.with_name(ruta.name + ".nuevo")
    provisorio.write_text(texto, encoding="utf-8", newline="\n")
    os.replace(provisorio, ruta)


def _tramos(desde: date, hasta: date):
    while desde <= hasta:
        fin = min(desde + timedelta(days=TRAMO - 1), hasta)
        yield desde, fin
        desde = fin + timedelta(days=1)


def _modulo_armar():
    spec = importlib.util.spec_from_file_location("armar_tipos_de_cambio", AQUI / "armar.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _armar(datos: Path, feriados: Path) -> str:
    return _modulo_armar().armar(datos, feriados)


def _bajar(clase: str, guardado: dict, desde, hoy: date, direccion: str, avisos: list) -> dict:
    ultimo = max(guardado) if guardado else None
    inicio = desde or (date.fromisoformat(ultimo) - timedelta(days=REPASO) if ultimo else PRIMER_DIA)
    if inicio > hoy:
        raise Falla(f"La fecha desde ({_dma(inicio)}) es posterior a hoy ({_dma(hoy)}).")
    bajado = {}
    for n, (a, b) in enumerate(_tramos(inicio, hoy)):
        if n:
            time.sleep(1)
        try:
            dias, malas = leer_csv(pedir(clase, a, b, direccion))
        except ValueError as e:
            raise Falla(f"Lo que contestó el BNA para {NOMBRE[clase].lower()} ({_dma(a)} al {_dma(b)}) {e}.") from e
        for linea in malas:
            avisos.append(f"{NOMBRE[clase]}: no se entiende esta fila del BNA y no se cargó: «{linea}»")
        bajado.update(dias)
    futuros = [k for k in bajado if k > hoy.isoformat()]
    for k in futuros:
        avisos.append(f"{NOMBRE[clase]}: el BNA devolvió una fecha posterior a hoy ({k}) y no se cargó.")
        del bajado[k]
    # lo que ya estaba guardado tiene que volver igual (salvo alguna corrección): si no, cambió algo en el BNA y no se toca nada
    repetidos = [k for k in guardado if inicio.isoformat() <= k <= hoy.isoformat()]
    faltan = [k for k in repetidos if k not in bajado]
    distintos = [k for k in repetidos if k in bajado and list(bajado[k]) != list(guardado[k])]
    if repetidos and len(faltan) == len(repetidos):
        raise Falla(f"El BNA no devolvió ninguna de las cotizaciones de {NOMBRE[clase].lower()} que ya estaban guardadas ({_dma(inicio)} al {_dma(hoy)}). No se cambió nada.")
    if len(repetidos) >= 3 and (len(distintos) + len(faltan)) * 2 > len(repetidos):
        raise Falla(f"Lo que devolvió el BNA para {NOMBRE[clase].lower()} no coincide con lo guardado ({len(distintos) + len(faltan)} de {len(repetidos)} días). "
                    "No se cambió nada: puede haber cambiado la página del BNA.")
    for k in sorted(faltan):
        avisos.append(f"{NOMBRE[clase]}: el BNA ya no trae la cotización del {_dma(date.fromisoformat(k))}, que estaba guardada. Se dejó como estaba.")
    return bajado


def _revisar_a_mano(clase: str, nombre: str, dias: dict, guardado: dict) -> None:
    """Un .csv bajado a mano tiene que coincidir con lo guardado de su clase en los días que se repiten (y no con lo de la otra)."""
    otra = "divisa" if clase == "billete" else "billete"
    iguales = {c: sum(1 for k in dias if k in guardado[c] and list(guardado[c][k]) == list(dias[k])) for c in CLASES}
    repetidos = sum(1 for k in dias if k in guardado[clase])
    if iguales[otra] >= 3 and iguales[otra] > iguales[clase]:
        raise Falla(f"{nombre}: coincide con lo guardado de {NOMBRE[otra].lower()}, no con lo de {NOMBRE[clase].lower()}. No se cambió nada: ¿es el .csv de la otra solapa?")
    if repetidos >= 3 and (repetidos - iguales[clase]) * 2 > repetidos:
        raise Falla(f"{nombre}: no coincide con lo guardado de {NOMBRE[clase].lower()} ({repetidos - iguales[clase]} de {repetidos} días distintos). No se cambió nada.")


def actualizar(datos: Path = DATOS, salida: Path = SALIDA, desde=None, hoy=None, direccion: str = DIRECCION, csv_billetes=None, csv_divisas=None,
               copiar_a=None, ahora=None, feriados: Path = FERIADOS, direccion_feriados: str = DIRECCION_FERIADOS, sin_feriados: bool = False,
               feriados_cada_horas: float = 12) -> dict:
    """Suma a cotizaciones.json lo que trae el BNA (o los .csv bajados a mano) y a feriados.json el calendario de feriados, arma la página
    y devuelve qué cambió. Con los .csv a mano (sin internet) o con `sin_feriados` no se piden los feriados; el calendario de un año que se
    bajó hace menos de `feriados_cada_horas` tampoco."""
    hoy = hoy or date.today()
    guardado = leer_datos(datos)
    avisos, nuevo = [], {}
    a_mano = {"billete": csv_billetes, "divisa": csv_divisas}
    if any(a_mano.values()):
        momentos = []
        for clase, ruta in a_mano.items():
            if not ruta:
                nuevo[clase] = {}
                continue
            ruta = Path(ruta)
            if not ruta.is_file():
                raise Falla(f"No encuentro {ruta}.")
            crudo = ruta.read_bytes()
            try:
                texto = crudo.decode("utf-8-sig")
            except UnicodeDecodeError:
                texto = crudo.decode("latin-1")
            try:
                nuevo[clase], malas = leer_csv(texto)
            except ValueError as e:
                raise Falla(f"{ruta.name}: {e}.") from e
            if not nuevo[clase]:
                raise Falla(f"{ruta.name}: no trae cotizaciones del Dolar U.S.A.")
            _revisar_a_mano(clase, ruta.name, nuevo[clase], guardado)
            avisos.extend(f"{ruta.name}: no se entiende esta fila y no se cargó: «{linea}»" for linea in malas)
            momentos.append(datetime.fromtimestamp(ruta.stat().st_mtime).astimezone())
        momento = min(momentos)  # los datos están al día de cuando se bajaron los .csv
    else:
        for clase in CLASES:
            nuevo[clase] = _bajar(clase, guardado[clase], desde, hoy, direccion, avisos)
        momento = ahora or datetime.now().astimezone()
    if nuevo["billete"] and nuevo["billete"] == nuevo["divisa"] and len(nuevo["billete"]) >= 3:
        raise Falla("Billetes y divisas vinieron con las mismas cotizaciones, día por día. No se cambió nada: revisá de qué solapa del BNA sale cada uno.")
    resumen = {"nuevos": {}, "corregidos": {}, "avisos": avisos}
    for clase in CLASES:
        resumen["nuevos"][clase] = sorted(k for k in nuevo[clase] if k not in guardado[clase])
        resumen["corregidos"][clase] = sorted(k for k in nuevo[clase] if k in guardado[clase] and list(guardado[clase][k]) != list(nuevo[clase][k]))
        for k in resumen["corregidos"][clase]:
            antes, ahora_ = guardado[clase][k], nuevo[clase][k]
            avisos.append(f"{NOMBRE[clase]}, {_dma(date.fromisoformat(k))}: el BNA lo corrigió, de {_numero(antes[0])} / {_numero(antes[1])} a {_numero(ahora_[0])} / {_numero(ahora_[1])}.")
        guardado[clase].update(nuevo[clase])
    anterior = datetime.fromisoformat(guardado["actualizado"]) if guardado["actualizado"] else None
    if anterior is None or momento > anterior:
        guardado["actualizado"] = momento.isoformat(timespec="seconds")
    if not guardado["billete"] and not guardado["divisa"]:
        raise Falla("No hay ninguna cotización para armar la página.")
    resumen["ultimo"] = {clase: (max(guardado[clase]) if guardado[clase] else None) for clase in CLASES}
    # los feriados: el año pasado, este y el que viene (se publica hacia fin de año), y los años de las cotizaciones que falten
    fer = _modulo_armar().leer_feriados(feriados)
    fer.setdefault("años", {})
    fer.setdefault("bancarios", [])
    fer["fuente"] = fer.get("fuente") or FUENTE_FERIADOS
    resumen["feriados"] = {}
    if not (any(a_mano.values()) or sin_feriados):
        anios_cot = {int(k[:4]) for c in CLASES for k in guardado[c]}
        anios = sorted({hoy.year - 1, hoy.year, hoy.year + 1} | {a for a in anios_cot if str(a) not in fer["años"]})
        resumen["feriados"] = _bajar_feriados(fer, anios, direccion_feriados, ahora or datetime.now().astimezone(), avisos, feriados_cada_horas)
    resumen["contraste"] = contrastar(guardado, fer, hoy - timedelta(days=1))
    _escribir(datos, texto_datos(guardado))
    _escribir(feriados, texto_feriados(fer))
    _escribir(salida, _armar(datos, feriados))
    resumen["salida"] = salida
    if copiar_a:
        carpeta = Path(copiar_a)
        if not carpeta.is_dir():
            raise Falla(f"La página quedó armada en {salida}, pero no encuentro la carpeta para la copia: {carpeta}")
        shutil.copyfile(salida, carpeta / salida.name)
        resumen["copia"] = carpeta / salida.name
    return resumen


def _fecha(texto: str) -> date:
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", texto.strip())
    if not m:
        raise argparse.ArgumentTypeError("la fecha va como dd/mm/aaaa")
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"«{texto}» no es una fecha") from e


def _contar(dias: list) -> str:
    if not dias:
        return "sin días nuevos"
    f = [_dma(date.fromisoformat(k)) for k in (dias[0], dias[-1])]
    return f"1 día nuevo ({f[0]})" if len(dias) == 1 else f"{len(dias)} días nuevos ({f[0]} al {f[1]})"


def _anotar(renglones: list, registro: Path = None) -> None:
    """Suma una corrida al final del registro y deja solo los últimos renglones."""
    registro = registro or REGISTRO
    try:
        viejo = registro.read_text(encoding="utf-8").splitlines() if registro.is_file() else []
        nuevos = [linea for r in renglones for linea in str(r).splitlines()]
        _escribir(registro, "\n".join((viejo + nuevos)[-RENGLONES_REGISTRO:]) + "\n")
    except OSError:
        pass


def main(argumentos=None) -> int:
    for salida_ in (sys.stdout, sys.stderr):  # en la consola de Windows, que no se corte por un acento
        if hasattr(salida_, "reconfigure"):
            salida_.reconfigure(errors="replace")
    programado = "--programado" in (argumentos if argumentos is not None else sys.argv[1:])
    renglones = [f"== {datetime.now().astimezone():%d/%m/%Y %H:%M:%S}"]

    def decir(texto: str, error: bool = False) -> None:
        renglones.append(texto)
        destino = sys.stderr if error else sys.stdout
        if destino is not None:  # con pythonw (la tarea programada) no hay consola
            print(texto, file=destino)

    try:
        return _correr(argumentos, decir)
    except Exception:  # un error del programa: que quede anotado entero (con la tarea programada no hay nadie mirando)
        decir("Error inesperado: " + traceback.format_exc().strip(), error=True)
        return 2
    finally:
        if programado:
            _anotar(renglones)


def _correr(argumentos, decir) -> int:
    p = argparse.ArgumentParser(description="Baja del Banco Nación las cotizaciones del dólar que faltan y del Ministerio del Interior los feriados, y arma «Tipos de cambio.html».")
    p.add_argument("--desde", type=_fecha, metavar="dd/mm/aaaa", help="pedir desde esta fecha (si no, desde unos días antes de la última guardada)")
    p.add_argument("--csv-billetes", metavar="ARCHIVO", help="sin internet: el .csv de «Cotización Billetes» bajado a mano del BNA")
    p.add_argument("--csv-divisas", metavar="ARCHIVO", help="sin internet: el .csv de «Cotización Divisas» bajado a mano del BNA")
    p.add_argument("--copiar-a", metavar="CARPETA", help="dejar además una copia de la página en esta carpeta")
    p.add_argument("--sin-feriados", action="store_true", help="no pedir el calendario de feriados (queda el que estaba)")
    p.add_argument("--programado", action="store_true", help="lo usa la tarea programada: además, lo que pasó queda en registro.txt")
    a = p.parse_args(argumentos)
    try:
        r = actualizar(desde=a.desde, csv_billetes=a.csv_billetes, csv_divisas=a.csv_divisas, copiar_a=a.copiar_a, sin_feriados=a.sin_feriados)
    except Falla as e:
        decir(f"No se actualizó: {e}", error=True)
        return 1
    for clase in CLASES:
        ultimo = r["ultimo"][clase]
        decir(f"{NOMBRE[clase]}: {_contar(r['nuevos'][clase])}. Última cotización: {_dma(date.fromisoformat(ultimo)) if ultimo else 'ninguna'}.")
    for anio, estado in r["feriados"].items():
        decir(f"Feriados de {anio}: {estado}.")
    for aviso in r["avisos"]:
        decir(f"Ojo: {aviso}")
    for cosa in r["contraste"]:
        decir(f"Para revisar: {cosa}")
    if r["contraste"]:
        decir("  (si fue un feriado bancario, sumalo a «bancarios» en herramientas/tipos-de-cambio/feriados.json, con su fuente)")
    decir(f"Listo: {r['salida']}")
    if "copia" in r:
        decir(f"Copia: {r['copia']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
