# ⚽ Quiniela Mundialista 2026

Aplicación web de quiniela (porra/prode) para el **Mundial 2026** entre un grupo
cerrado de amigos. Cada jugador predice el marcador de los partidos del día,
y la app puntúa automáticamente cuando los partidos terminan, manteniendo una
tabla de posiciones en vivo.

Es una app **single-process** construida con **NiceGUI** (UI + servidor en uno),
**SQLAlchemy 2.0 + SQLite** para persistencia, y **APScheduler** para sincronizar
calendarios, refrescar resultados y disparar la puntuación en segundo plano.
Los datos de los partidos se obtienen de **API-Football** a través de una interfaz
de proveedor intercambiable.

> Diseño de arquitectura por Claude; implementación asistida con DeepSeek + Hermes + Kanban.
> La especificación técnica completa está en `quinielamundialistaarquitectura.md`.

---

## Características

- **Login simple** con dropdown de nombres + contraseña de 4 dígitos. En el primer
  ingreso, cada jugador elige una bandera como avatar.
- **Tab "Hoy"** — partidos del día (hora El Salvador). Inputs de marcador 0–100,
  botón Guardar/Editar. La edición se **bloquea automáticamente al iniciar el partido**
  (kickoff). Al finalizar muestra marcador real, tu predicción y puntos obtenidos.
- **Tab "Tabla"** — posiciones ordenadas por puntos totales, con columna **+Hoy**
  (puntos ganados hoy) y **Δ** (cambio de posición vs. el snapshot del día anterior).
- **Tab "Mañana"** — partidos del día siguiente. Los equipos por definir (eliminatorias)
  se muestran como **TBD** con los inputs deshabilitados hasta que se resuelvan.
- **Tab "Apuestas"** — vista pública (solo lectura) para todos: por cada partido
  cerrado muestra el marcador real y la predicción + puntos de los 11 jugadores,
  ordenados por puntos. No revela apuestas de partidos aún abiertos.
- **Tab "Admin"** — solo para jugadores `is_admin`: corrige la predicción de un
  jugador en un partido cerrado, re-puntúa al instante (borra y recalcula el
  `match_score`) y registra cada cambio en un log de auditoría.
- **Puntuación automática** en background cuando un partido pasa a finalizado.
- **Tema oscuro** integrado.

## Reglas de puntuación

Reglas excluyentes (`scoring/quiniela.py`):

| Resultado de la predicción | Puntos |
|---|---|
| Marcador exacto | **4** |
| Acierta el resultado (ganador/empate), marcador distinto | **2** |
| No acierta **o** sin predicción | **0** |

**Penales:** se usa el marcador reglamentario / de prórroga (`goals`), **sin** contar
penales. Un 1-1 que se define por penales cuenta como **empate** para la puntuación.

---

## Stack

- **Python 3.12+**, gestionado con [`uv`](https://github.com/astral-sh/uv)
- **NiceGUI 3.x** — UI y servidor web (puerto 8091)
- **SQLAlchemy 2.0 + SQLite** (modo WAL)
- **APScheduler** — jobs async en proceso
- **httpx** — cliente async para el proveedor de datos
- **Docker / docker-compose** — despliegue (target: Oracle Cloud ARM64)

## Arquitectura

```
┌──────────────────────────────────────────────────────────┐
│ Proceso NiceGUI (async)                                   │
│                                                           │
│  UI (Tabs Hoy/Tabla/Mañana)   Auth (app.storage.user)     │
│            │                          │                    │
│            ▼                          ▼                    │
│  ┌─────────────────────────────────────────┐  APScheduler │
│  │ Acceso a datos (SQLAlchemy 2.0)          │  - sync      │
│  └──────────────────┬──────────────────────┘  - poll      │
│                     │            ▲              - snapshot  │
│                     ▼            │                          │
│              ┌─────────────┐  ┌──┴───────────┐             │
│              │ SQLite (WAL)│  │ Scoring (puro)│             │
│              └─────────────┘  └──────────────┘             │
└───────────────────────────────────┬───────────────────────┘
                                     │ HTTPS (poll)
                                     ▼
                        MatchProvider (API-Football)
```

Capas: **UI → datos → BD**. El **scoring** es un módulo puro y testeable. El
**scheduler** es el único componente que habla con el proveedor externo — la UI
nunca llama a la API directamente. La interfaz `MatchProvider` desacopla la fuente
de datos, así se puede cambiar de proveedor sin tocar lógica de negocio.

Todos los timestamps se guardan en **UTC** y se convierten a `America/El_Salvador`
(UTC-6, sin horario de verano) solo para mostrar y para agrupar por "día".

### Estructura del proyecto

```
main.py                 # Entrypoint NiceGUI: páginas, scheduler, tema oscuro
auth/
  __init__.py           # session_guard() — protege rutas, redirige a /login
  login.py              # Página /login + selección de bandera (primer login)
data/
  models.py             # Modelos SQLAlchemy: Player, Match, Prediction, MatchScore, StandingsSnapshot
  database.py           # Engine, WAL, init_db(), seed_players() desde CSV
provider/
  base.py               # Protocolo MatchProvider
  models.py             # DTOs: ProviderMatch, ProviderResult
  api_football.py       # ApiFootballProvider (proveedor primario)
  balldontlie.py        # BalldontlieProvider (fallback)
scheduler/
  sync.py               # sync_fixtures — pobla/actualiza partidos, resuelve TBD
  poll_results.py       # poll_results — detecta finalizados y dispara scoring
scoring/
  quiniela.py           # score() / outcome() — módulo puro
ui/
  hoy.py                # Tab "Hoy"
  standings.py          # Tab "Tabla"
  manana.py             # Tab "Mañana"
  apuestas.py           # Tab "Apuestas" (vista pública de partidos cerrados)
  admin.py              # Tab "Admin" + apply_correction (re-scoring + auditoría)
scripts/
  init_db.py            # Crear/verificar tablas
  daily_snapshot.py     # Snapshot diario de posiciones (cron 00:00 ES)
  cron_daily_snapshot.sh
tests/
  test_quiniela.py      # Tests del scoring
  test_poll_results.py  # Tests de poll + scoring sobre BD en memoria
```

### Modelo de datos

- **`players`** — `name` (único), `password` (texto plano, fase dev), `avatar_flag`, `is_setup`, `initial_points` (handicap que se suma al total), `is_admin`.
- **`matches`** — `external_id` (id del proveedor), `home`/`away` (null = TBD), banderas,
  `kickoff_utc`, `match_date_local` (fecha ES), `stage`, `status`, `goals_home`/`goals_away`.
- **`predictions`** — `pred_home`/`pred_away` (0–100), único por `(player_id, match_id)`.
- **`match_scores`** — `points` (0/2/4), único por `(player_id, match_id)`. Se escribe
  al finalizar el partido para **los 11 jugadores** (quien no predijo recibe 0).
- **`standings_snapshots`** — `total_points` + `rank` por jugador por día, para el
  cálculo de Δ posición.
- **`admin_audit_log`** — registro de cada corrección de admin: quién, cuándo, qué
  partido y jugador, predicción y puntos viejos → nuevos.

### Scheduler (jobs en background)

| Job | Frecuencia | Qué hace |
|---|---|---|
| `sync_fixtures` | cada 6 h (+ al arranque) | Refresca partidos de hoy y mañana; resuelve equipos TBD |
| `poll_results` | cada 10 min | Consulta solo partidos vencidos no finalizados; al finalizar guarda goles y dispara scoring |
| `daily_snapshot` | 00:00 ES | Guarda el snapshot diario (total + rank) |

`poll_results` solo consulta partidos con `kickoff + ~2h <= ahora` y estado distinto
de finalizado, para respetar el rate limit (~100 req/día del tier gratuito).

---

## Puesta en marcha (local)

### 1. Requisitos

- Python 3.12+ y [`uv`](https://github.com/astral-sh/uv)
- Una API key de [API-Football](https://www.api-football.com/) (tier gratuito)

### 2. Configuración

Copiá el ejemplo de variables de entorno y completá los valores:

```bash
cp .env.example .env
```

Variables principales (`.env`):

```ini
STORAGE_SECRET=<string-aleatorio-fuerte>   # requerido por app.storage.user de NiceGUI
DB_PATH=/data/quiniela.db                  # ruta del archivo SQLite
PLAYERS_CSV=/config/players.csv            # CSV de jugadores (no se commitea)
MATCH_PROVIDER=api_football                # api_football | balldontlie
APIFOOTBALL_KEY=<tu-api-key>               # API key del proveedor primario
BALLDONTLIE_API_KEY=                       # opcional, proveedor fallback
TZ=America/El_Salvador
```

### 3. Jugadores (`players.csv`)

Las credenciales se cargan desde un CSV **que no se commitea** (`.gitignore`).
El seed hace *upsert* por `name`, así que re-correrlo no duplica. Formato:

```csv
name,password,initial_points,is_admin
Cuestas,1234,0,
Vega,5678,10,
Josue,4321,5,true
```

- `initial_points` es **opcional** (handicap inicial por jugador). Si la columna
  no está, todos arrancan en 0. Se **suma al total** en la Tabla y en el snapshot
  diario, y se actualiza por *upsert* si cambiás el valor en el CSV.
- `is_admin` es **opcional**; valor truthy (`true`/`1`/`yes`) da acceso al panel
  Admin. Vacío/ausente = no admin. También se actualiza por *upsert*.

> Las contraseñas se guardan en **texto plano** (4 dígitos) — esto es una fase de
> desarrollo, **no producción**. Si el proyecto se publica, hay que cambiar a hash.

### 4. Instalar y correr

```bash
uv sync                          # instala dependencias
uv run python scripts/init_db.py # crea las tablas
uv run python main.py            # levanta la app en http://localhost:8091
```

Al arrancar, `main.py` llama a `init_db()` y `seed_players()` automáticamente, y
arranca los jobs del scheduler.

### Datos de demostración (probar sin API key)

Para ver la app poblada sin conectarte al proveedor, hay un seed de demostración
con la ronda de **dieciseisavos** (round of 32). Calcula las fechas relativas a
"hoy" en El Salvador, así que siempre llena las pestañas **Hoy** y **Mañana**:

```bash
uv run python scripts/seed.py    # ⚠️ reinicia la BD e inserta datos de demo
uv run python main.py            # ingresá con, p.ej., Cuestas / 1234
```

Incluye los 11 jugadores, el cierre de fase de grupos hoy (2 partidos finalizados
con marcador, 1 en juego bloqueado y 1 editable), **los 16 dieciseisavos completos**
(32 equipos, repartidos 4 por día durante 4 días desde mañana, todos editables), los
8 octavos con equipos **TBD** para completar el bracket, predicciones, puntuaciones
ya calculadas y un snapshot del día anterior para ver la columna Δ. El comando imprime
credenciales de ejemplo al terminar.

### 5. Tests

```bash
uv run pytest
```

Cubren el módulo de scoring (`test_quiniela.py`) y el flujo de poll + puntuación
sobre una BD SQLite en memoria (`test_poll_results.py`).

---

## Despliegue con Docker

Antes de levantar, creá el `.env` (es obligatorio por `env_file`):

```bash
cp .env.example .env          # editá STORAGE_SECRET (y APIFOOTBALL_KEY si usás API real)
docker compose up -d --build
```

`docker-compose.yml` levanta un único servicio en el puerto **8091** con:

- Volúmenes persistentes para la BD (`./data/db` → `/data`) y el storage de NiceGUI.
- Carpeta de config montada **read-only** (`./data/config` → `/config`). Poné tu
  `players.csv` en `./data/config/players.csv` para uso real; si está vacía, el
  seed de jugadores se omite sin error.
- `TZ=America/El_Salvador` y `restart: unless-stopped`.
- Healthcheck HTTP contra el puerto 8091.

La imagen base es `python:3.12-slim`, compatible con ARM64 (Oracle Cloud).

### Probar la demo en Docker (sin API key ni players.csv)

Poné `SEED_DEMO=1` en el `.env` y levantá: si la BD está vacía, se cargan los
datos de demostración (dieciseisavos) automáticamente al arrancar. No borra datos
existentes, así que en reinicios posteriores se respeta lo que ya haya.

```bash
echo "SEED_DEMO=1" >> .env
docker compose up -d --build
# Abrí http://<host>:8091 e ingresá con, p.ej., Cuestas / 1234
```

Para volver a empezar de cero: `docker compose down && rm -rf data/db && docker compose up -d`.

El snapshot diario también puede ejecutarse fuera del proceso vía cron usando
`scripts/cron_daily_snapshot.sh`, aunque por defecto el job ya corre dentro de la
app vía APScheduler.

---

## Notas y seguridad

- **Sin encriptación de contraseñas en esta fase.** Pensada para un grupo cerrado de
  amigos en una red de confianza, no para uso público. El único punto a tocar para
  endurecerla es reemplazar el texto plano por hash en `players` y en el login.
- **Secretos fuera de git:** `.env` y `players.csv` están en `.gitignore`/`.dockerignore`.
- **Rate limit:** el proveedor primario tiene contador local (~100 req/día) que se
  resetea a medianoche UTC. Si queda corto, subí el intervalo de `poll_results` o
  cambiá de proveedor (la interfaz lo permite).
- **Seed:** en producción los jugadores vienen de `players.csv` (`seed_players()`,
  upsert por nombre). Para pruebas locales, `scripts/seed.py` reinicia la BD e
  inserta datos de demostración completos (ver sección de arriba).
</content>
</invoke>
