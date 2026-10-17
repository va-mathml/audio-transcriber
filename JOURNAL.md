# JOURNAL — Bitácora técnica del proyecto audio-transcriber

Registro de incidentes, diagnósticos y lecciones del proyecto, con análisis conceptual
para reutilizar en cursos teórico-prácticos sobre creación de automatizaciones,
APIs y despliegue en la nube.

---

## Entrada 001 — 2026-07-14 — Error de conexión que no era de conexión (CORS)

### 1. Síntoma

Al subir un audio .ogg de WhatsApp desde la interfaz web, aparecía:

> Error: No se pudo conectar con el servidor. Verifica tu conexion.

Todo "parecía estar bien": había internet, el backend en Railway estaba desplegado
y el healthcheck (`GET /health`) respondía HTTP 200 con las dos keys de Groq activas.

### 2. Diagnóstico (paso a paso, replicable)

El método fue **aislar capas**: separar "el servidor está roto" de "el navegador
bloquea la petición". Cada prueba descarta una hipótesis:

| Paso | Prueba | Resultado | Conclusión |
|------|--------|-----------|------------|
| 1 | `curl GET /health` | HTTP 200, keys OK | El servidor está vivo |
| 2 | `curl POST /transcribe` con un .ogg de prueba | HTTP 200, transcribe bien | El motor completo funciona |
| 3 | `curl OPTIONS /transcribe` con cabecera `Origin:` simulando el navegador | HTTP 400 "Disallowed CORS origin" | **El navegador es el bloqueado, no la red** |

Punto clave: si el backend responde a `curl` pero el navegador dice "no se pudo
conectar", el sospechoso número uno es **CORS**. El mensaje de error del frontend
era engañoso porque `fetch` reporta cualquier bloqueo CORS como un genérico
`Failed to fetch`, indistinguible de una caída de red real.

### 3. Causa raíz

En `backend/main.py` la configuración CORS era:

```python
ALLOWED_ORIGINS = "http://localhost:3000,http://localhost:8000,https://*.onrender.com"

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS.split(","),
    allow_credentials=True,
    ...
)
```

El error conceptual: **`allow_origins` de FastAPI/Starlette NO soporta comodines**.
La cadena `https://*.onrender.com` se compara de forma literal, carácter por
carácter, contra el origen que envía el navegador. Ningún origen real contiene
un asterisco, así que ese "patrón" nunca coincidía con nada. Además, al abrir el
`index.html` local con doble clic, el origen es `null`, que tampoco estaba en la lista.

### 4. Corrección

Como esta API no usa cookies ni sesiones (es *stateless*: recibe archivo, devuelve
texto), se abrió CORS a todos los orígenes, que en este caso es seguro:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,   # obligatorio: "*" no es compatible con credenciales
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Alternativa si se quisiera restringir por dominio con patrón:
`allow_origin_regex=r"https://.*\.onrender\.com"` (regex sí soporta comodines).

Se hizo commit, push a GitHub, Railway redesplegó automáticamente, y se verificó
con `curl OPTIONS` que el preflight ya respondía HTTP 200.

---

## Análisis conceptual (material para curso)

### A. ¿Qué es CORS y por qué existe?

CORS (*Cross-Origin Resource Sharing*) es un mecanismo de seguridad **del navegador**,
no del servidor. Por defecto, el navegador aplica la *Same-Origin Policy*: una página
cargada desde el origen A no puede leer respuestas de peticiones al origen B.

Un **origen** es la tripleta `protocolo + dominio + puerto`. Ejemplos:
- `https://miapp.onrender.com` y `https://miapi.railway.app` → orígenes distintos
- `http://localhost:3000` y `http://localhost:8000` → orígenes distintos (puerto)
- Archivo abierto con doble clic (`file://...`) → origen `null`

CORS es la forma en que el servidor le dice al navegador "confío en estos orígenes":
responde con la cabecera `Access-Control-Allow-Origin`. Si falta o no coincide,
el navegador **descarta la respuesta** y la página ve un fallo genérico.

### B. El preflight (petición OPTIONS)

Para peticiones "no simples" el navegador envía primero una petición `OPTIONS`
preguntando "¿puedo hacer esto?". Solo si el servidor la aprueba, envía la petición
real. Por eso en el diagnóstico se probó con `curl -X OPTIONS`: simula exactamente
lo que hace el navegador antes de subir el archivo.

### C. Tres ideas transferibles a cualquier automatización

1. **CORS no protege la API, protege al usuario del navegador.** Cualquier script,
   `curl` o bot puede llamar la API igual; CORS solo limita qué *páginas web* pueden
   leerla. Por eso abrir CORS en una API sin sesiones no agrega riesgo real: la
   protección de recursos (keys, cuotas) debe vivir en el servidor, nunca en CORS.

2. **Los mensajes de error de la capa superior mienten por diseño.** El navegador
   oculta deliberadamente el detalle del bloqueo CORS a JavaScript (para no filtrar
   información entre sitios). El error real solo aparece en la consola del navegador
   (F12) o probando la capa de abajo directamente. Lección general: cuando un error
   es genérico, baja una capa (UI → HTTP → servidor → logs).

3. **Verificar la sintaxis exacta que la librería soporta.** El bug nació de asumir
   que `allow_origins` aceptaba comodines "porque parece razonable". Cada librería
   define su propio contrato: FastAPI usa comparación literal en `allow_origins`
   y ofrece `allow_origin_regex` para patrones. Un patrón que "no coincide nunca"
   no lanza error: falla en silencio.

### D. Método de diagnóstico general (esquema para clase)

```
Síntoma vago ("error de conexión")
        |
        v
¿El servidor está vivo?  -----> curl GET /health
        |
        v
¿El endpoint funciona sin navegador?  -----> curl POST (petición real)
        |
        v
¿El navegador es el que bloquea?  -----> curl OPTIONS con Origin (preflight)
        |
        v
Causa raíz en configuración, no en infraestructura
```

La idea pedagógica: cada flecha descarta una capa completa. Nunca se tocó código
hasta tener evidencia de la capa exacta que fallaba.

### E. Contexto de arquitectura del proyecto (para referencia)

- **Frontend**: HTML/JS estático (Render o archivo local) que hace `fetch` a la API.
- **Backend**: FastAPI en Railway. Endpoints `/transcribe`, `/webhook` (Telegram), `/health`.
- **Motor**: Groq Whisper API con dos keys en rotación (turbo → large-v3 como fallback).
- **Despliegue**: push a GitHub → Railway redespliega automáticamente.
- El propio backend sirve una copia de la UI en `/` (mismo origen, inmune a CORS):
  útil como plan B cuando el frontend externo falla.

> Nota (2026-10-15): desde octubre el despliegue es un solo servicio en Render
> (`render.yaml`) que sirve UI, API y bot; el frontend externo y la config de
> Railway se eliminaron del repo.

---

## Entrada 002 — 2026-10-15 — 502 con audios largos: el servidor se bloqueaba a sí mismo

### 1. Síntoma

Un audio de 3 s se transcribía en 5 s, pero uno de 29 min (MP3 de 14 MB) devolvió
`HTTP 502` con el cuerpo vacío a los ~50 s. Al repetirlo, la misma petición sí
respondió 200. Fallo intermitente, dependiente de la duración.

### 2. Diagnóstico (paso a paso, replicable)

1. **¿Llaves?** `/health` decía `groq_key1: true`, pero eso solo prueba que la
   variable existe. Un audio sintético (tono de 3 s) respondió 200: llaves válidas
   en Render. (Las del `.env` local sí estaban vencidas: 401 `invalid_api_key`.
   Era otro problema, solo local.)
2. **¿Quién respondió el 502?** Cuerpo vacío: no fue FastAPI (que responde JSON),
   fue el proxy de Render. La instancia dejó de contestar.
3. **Experimento clave:** subir el audio largo y, en paralelo, consultar `/health`
   cada 5 s. Resultado: `/health` respondió 200 al inicio, luego **timeouts y 502
   durante ~25 s** mientras se transcribía, y volvió a 200 al terminar.
4. **Reproducción local:** servidor con una transcripción falsa de 8 s.
   Sin arreglo, `/health` daba `ReadTimeout`; con arreglo, 200 en 0,2 s.

### 3. Causa raíz

`transcribe()` (ffmpeg + llamada HTTP a Groq) es **síncrona**, y se llamaba
directamente dentro de endpoints `async def` (`/transcribe` y el handler del bot).
En asyncio hay un solo hilo de event loop: una función bloqueante dentro de una
corrutina congela **todo** el servidor, incluido el healthcheck y el webhook de
Telegram. Con audios cortos no se nota; con largos, el proxy da la instancia por
caída.

### 4. Corrección

```python
from starlette.concurrency import run_in_threadpool
result = await run_in_threadpool(transcribe, tmp_path)
```

En `main.py` y `bot.py`. La transcripción corre en un hilo del pool y el event
loop sigue atendiendo peticiones. Commit `6d5fad0`.

### 5. Idea transferible (para curso)

**`async def` no hace asíncrono lo que hay adentro.** Solo cede el control en cada
`await`. Una llamada bloqueante (requests, subprocess, SDK síncrono, `time.sleep`)
dentro de una corrutina bloquea al servidor entero. Opciones: versión async de la
librería, `run_in_threadpool` / `asyncio.to_thread`, o declarar el endpoint con
`def` (FastAPI lo corre en un hilo). Prueba de diagnóstico universal: medir un
endpoint trivial mientras otro trabaja.

---

## Entrada 003 — 2026-10-16 — Notas de voz de WhatsApp en `.mpeg` rechazadas

### 1. Síntoma

Al subir `WhatsApp Audio 2026-10-16 at 3.44.29 PM.mpeg` (419 KB) la web respondió:

> Error: Formato '.mpeg' no soportado. Formatos validos: .avi, .flac, .m4a, ...

### 2. Causa raíz

WhatsApp exporta algunas notas de voz con extensión `.mpeg` (contenido MPEG audio).
La validación es una lista blanca de extensiones (`ALL_FORMATS` en `transcriber.py`)
y `.mpeg` no estaba. El contenido nunca fue el problema: desde la entrada 002 todo
archivo pasa por ffmpeg (AAC 16 kHz mono) antes de ir a Groq, y ffmpeg lo lee sin
problema.

### 3. Corrección

- `AUDIO_FORMATS` ahora incluye `.mpeg`, `.mpga`, `.aac` y `.amr` (otros formatos
  frecuentes en notas de voz). El MIME de respaldo (sin ffmpeg) mapea `.mpeg`/`.mpga`
  a `audio/mpeg`.
- `index.html`: atributo `accept` del selector y texto de formatos actualizados.
- Verificación: un `.mpeg` sintético pasó `validate_file` y `extract_audio` en local;
  Víctor confirmó en producción con el audio real. Commit `8f360d4`.

### 4. Idea transferible (para curso)

**La extensión es una etiqueta, no el formato.** Una lista blanca por extensión es
simple y segura, pero rechaza archivos válidos cuyo nombre no conoce. Cuando el
pipeline normaliza todo con ffmpeg, la lista blanca puede ser generosa en audio; la
alternativa más robusta es validar por contenido (`ffprobe` o *magic bytes*) en vez
de por nombre.

---

## Ficha técnica del artefacto

### 1. ¿Qué tipo de artefacto es, en términos del mundo de la programación?

Es una **aplicación web de tres capas (three-tier) con arquitectura cliente-servidor**,
cuyo backend expone una **API REST stateless** que actúa como **fachada (facade)**
sobre un servicio de inteligencia artificial de terceros. En la taxonomía actual
se clasifica como:

- **AI wrapper / AI-powered app**: no entrena ni ejecuta el modelo de IA localmente;
  orquesta llamadas a un modelo alojado por un proveedor (Groq ejecutando Whisper).
  Esta es hoy la categoría más común de aplicación de IA en producción: el valor
  no está en el modelo sino en la integración, la experiencia de uso y el flujo.
- **Microservicio monolítico** (paradójico pero preciso): un solo proceso desplegable
  con responsabilidad única (transcribir), sin base de datos ni estado. Cabría en
  la categoría *serverless-style service* aunque corra como proceso persistente.
- **Bot de mensajería** en su segunda interfaz: el mismo backend atiende a Telegram
  vía webhook, un patrón de integración clásico de automatizaciones.

### 2. ¿Cómo se hizo y en qué plataformas se apoya?

| Capa | Tecnología | Rol |
|------|-----------|-----|
| Lenguaje | Python 3 | Todo el backend |
| Framework web | FastAPI 0.111 + Uvicorn (ASGI) | Endpoints, validación, OpenAPI/docs automáticos |
| Modelo de IA | Whisper (OpenAI) servido por **Groq** | Speech-to-text; Groq lo ejecuta en hardware propio (LPU) con latencia muy baja |
| Procesamiento de audio | ffmpeg / ffprobe (subprocesos) | Conversión de formatos no nativos (MKV, AVI, MOV) a WAV 16 kHz mono |
| Mensajería | Telegram Bot API (webhook, vía httpx) | Segunda interfaz de usuario |
| Hosting backend | **Railway** (PaaS) | Deploy automático desde GitHub, variables de entorno, HTTPS |
| Hosting frontend | **Render** (static site) + copia servida por el propio backend | UI web |
| Control de versiones | Git + GitHub | Fuente de verdad; el push dispara el deploy |

Dependencias mínimas (6 paquetes): FastAPI, Uvicorn, python-multipart, httpx,
groq, python-dotenv. La parquedad es deliberada: menos superficie de fallo.

### 3. Estilo de código, patrones y decisiones de diseño

- **Twelve-Factor App** (parcial): toda la configuración vive en variables de
  entorno (keys, modelo, idioma, tamaño máximo), nunca en el código; el proceso
  es stateless y desechable; los logs van a stdout.
- **Patrón fallback / redundancia activa-pasiva**: dos API keys de Groq en rotación;
  si la primaria falla (cuota, red), se reintenta con la secundaria y otro modelo.
  Es la versión mínima del patrón *circuit breaker* sin la parte de "abrir el circuito".
- **Separación por responsabilidad en módulos planos**: `main.py` (transporte HTTP),
  `transcriber.py` (dominio: validar, convertir, transcribir), `bot.py` (adaptador
  de Telegram), `utils.py`. No hay clases: es **programación procedural con funciones
  puras donde se puede**, estilo idiomático en servicios Python pequeños. La
  orientación a objetos habría agregado ceremonia sin beneficio a esta escala.
- **Patrón adaptador sobre procesos externos**: ffmpeg se invoca por `subprocess`
  con timeout y captura de stderr; el resto del código solo ve `extract_audio()`.
- **Manejo de errores por capas semánticas**: `ValueError` = culpa del usuario
  (HTTP 400), `RuntimeError` = culpa del sistema (HTTP 500). El endpoint traduce
  excepciones de dominio a códigos HTTP, sin que el dominio conozca HTTP.
- **Optimización de costos por conocimiento del proveedor**: solo se convierte con
  ffmpeg lo que Groq no acepta nativo (MKV/AVI/MOV); el resto se envía directo.
  Detalle pequeño pero representativo: conocer el contrato del proveedor ahorra
  cómputo y tiempo.

### 4. Estado del arte sobre este tipo de aplicación

- **Speech-to-text está comoditizado**. Desde Whisper (2022, open source) la
  transcripción de calidad dejó de ser ventaja competitiva: la ofrecen OpenAI,
  Groq, Deepgram, AssemblyAI, Google, Azure y modelos locales (whisper.cpp,
  faster-whisper). La competencia hoy es por **latencia, precio y diarización**
  (identificar hablantes), no por precisión bruta en idiomas mayoritarios.
- **La tendencia dominante es "inferencia como servicio"**: apps que, como esta,
  delegan el modelo a un proveedor y compiten en integración. La alternativa
  (self-hosting con faster-whisper en GPU propia) solo se justifica con volumen
  alto o requisitos de privacidad estrictos.
- **Groq representa la ola de hardware especializado en inferencia** (LPU vs GPU):
  su propuesta es velocidad extrema con modelos abiertos. Elegirlo aquí fue
  pragmático: free tier generoso (7200 s de audio/día por cuenta) y latencia baja.
- **El siguiente escalón del estado del arte** es la transcripción *streaming*
  (texto mientras se habla, vía WebSockets) y el post-procesamiento con LLM
  (resúmenes, actas, extracción de tareas). Esta app está a un paso natural de
  ambos: el texto ya llega a un backend que podría encadenar una segunda llamada.

### 5. Escalabilidad: qué aguanta y por dónde crecería

**Lo que ya juega a favor**: al ser stateless (sin base de datos, sin sesiones,
archivos temporales que se borran), la app es *horizontalmente escalable por
diseño*: se pueden correr N réplicas detrás de un balanceador sin cambiar una
línea de código. Esa es la propiedad de escalabilidad más valiosa y ya la tiene.

**Cuellos de botella actuales, en orden de aparición**:

1. **Cuota del proveedor**: el free tier de Groq (7200 s/día por cuenta) es el
   techo real. La rotación de dos keys lo duplica, pero es una mitigación, no una
   solución. Escalar = pagar tier de pago o multiplexar proveedores.
2. **Procesamiento síncrono**: `/transcribe` mantiene la conexión HTTP abierta
   mientras transcribe. Con archivos largos o muchos usuarios simultáneos, se
   agotan workers. La evolución canónica es el patrón **cola de trabajos**
   (job queue): el endpoint responde de inmediato con un `job_id`, un worker
   procesa en segundo plano (Celery/RQ/arq + Redis) y el cliente consulta o
   recibe webhook. Este es EL patrón a enseñar en un curso de automatizaciones.
3. **Archivos en memoria**: `await file.read()` carga todo el archivo en RAM;
   con el límite de 50 MB y pocos usuarios es irrelevante, a escala se cambiaría
   por streaming a disco o a un bucket (S3/R2).
4. **Sin persistencia**: no guarda transcripciones ni métricas. Para producto
   real haría falta base de datos (historial, usuarios, facturación) — y en ese
   momento dejaría de ser stateless la capa de datos, no la de cómputo.

**Resumen pedagógico**: la app está en el punto dulce de la escala pequeña —
arquitectura correcta para su tamaño, sin sobre-ingeniería, y con rutas de
crecimiento conocidas y estándar (colas, storage, multi-proveedor). Sirve como
caso de estudio de la máxima "haz la cosa más simple que pueda funcionar, pero
deja las costuras donde el estado del arte dice que habrá que cortar".
