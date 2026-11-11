# Tipos de cambio del dólar (BNA)

La tabla de cotizaciones del **Banco de la Nación Argentina**: dólar **billete** y dólar **divisa**, **comprador** y **vendedor**, día por día, con el calendario de feriados de Argentina.

**La tabla: https://elvischatzky.github.io/tipos-de-cambio/**

- Se actualiza sola de lunes a viernes, cada hora de 10 a 19 (hora argentina): un trabajo programado de GitHub (`.github/workflows/actualizar.yml`) corre `herramientas/tipos-de-cambio/actualizar.py`, que baja del BNA las cotizaciones que faltan y del Ministerio del Interior el calendario de feriados, y publica la página.
- Las cotizaciones y los feriados son públicos. Fuentes: [bna.com.ar](https://www.bna.com.ar/Personas) y [argentina.gob.ar/feriados](https://www.argentina.gob.ar/feriados), más los días sin bancos que no están en el calendario oficial (el Día del Bancario y los feriados bancarios del BCRA, escritos a mano en `feriados.json` con su fuente). La cotización oficial es la que publica el banco.
- La página es un solo archivo, sin nada externo: no se conecta a ningún lado; los datos van adentro. Se puede guardar y abrir sin internet (muestra lo que traía).
- Si algo de lo que contesta el BNA no cierra, no se publica nada nuevo y la corrida queda en rojo en «Actions».

Hecho por Elvis Chatzky · GAyGC, Dioxitek.
