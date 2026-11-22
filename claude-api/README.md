# claude-api

Servicio HTTP de la casa para pedirle textos a Claude. Corre en starr-server
(en el servidor `plexserver`) y es la única pieza que habla con Anthropic: usa
la `ANTHROPIC_API_KEY` de starr-server y sale por el proxy `warp` (EE.UU.),
que es la única forma en que Claude responde desde esta red.

Cualquier app o servicio de la casa puede usarlo con una petición HTTP, sin
API key de Anthropic, sin SDK y sin proxy propios. Hoy lo usa wan-monitor para
redactar sus avisos de Telegram.

## Resumen rápido

```bash
curl -s -X POST http://plexserver:8787/ask \
  -H "Authorization: Bearer $CLAUDE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Saluda en una frase corta", "effort": "low"}'
```

```json
{"text": "¡Hola! ¿En qué te puedo ayudar?", "stop_reason": "end_turn",
 "request_id": "req_011C...", "usage": {"input_tokens": 12, "output_tokens": 48}}
```

## Dónde está

| Desde dónde llamas | URL |
|---|---|
| Un contenedor del mismo `docker-compose` de starr-server | `http://claude-api:8787` |
| Un contenedor de **otro** `docker-compose` en el mismo servidor | `http://host.docker.internal:8787` (ver nota abajo) |
| El propio servidor (SSH) | `http://localhost:8787` |
| Otro aparato de la red de la casa (Mac, etc.) | `http://plexserver:8787` o `http://192.168.0.150:8787` |

El servidor es Linux: para que `host.docker.internal` exista dentro de un
contenedor hay que declararlo en su `docker-compose.yml`:

```yaml
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

Es solo para la red local. **No abras el puerto 8787 en el router**: quien
tenga acceso puede gastar en tu cuenta de Anthropic.

## Autenticación

Cada petición a `/ask` lleva el secreto compartido en un header:

```
Authorization: Bearer <CLAUDE_API_TOKEN>
```

El valor es el `CLAUDE_API_TOKEN` del `.env` de starr-server. Cada app lo
guarda en su propio `.env` (nunca en el código ni en el repo). Si falta o no
coincide, la respuesta es `401`.

## Endpoints

### `GET /health`

Sin autenticación. Responde `200 {"ok": true}` si el servicio está arriba. No
verifica que Claude ni warp respondan: para eso hay que hacer un `/ask`.

### `POST /ask`

Manda un mensaje a Claude y devuelve el texto de la respuesta. Cuerpo JSON
(`Content-Type: application/json`), máximo 200 KB.

| Campo | Tipo | Obligatorio | Default | Qué hace |
|---|---|---|---|---|
| `prompt` | texto | **sí** | | El mensaje del usuario. |
| `system` | texto | no | (ninguno) | Instrucciones de sistema: rol, tono, formato de salida, reglas. |
| `model` | texto | no | `claude-opus-5-5` | Modelo de Claude (ver [Modelos](#modelos)). |
| `effort` | texto | no | el del modelo (`medium` en Opus 5.5) | Cuánto razona antes de responder: `low`, `medium`, `high`, `xhigh` o `max`. Más alto = mejor en tareas difíciles, pero más lento y caro. |
| `max_tokens` | número | no | `1024` | Tope de tokens que puede generar, **incluido el razonamiento interno**. Tope del servidor: `4096`; si pides más, se recorta a 4096. |
| `timeout` | número (segundos) | no | `60` | Cuánto espera el servicio a Claude antes de rendirse con `504`. |

Encabezado opcional: `X-Caller: nombre-de-tu-app`. Solo sirve para que los
logs del servicio digan quién hizo cada pedido.

#### Respuesta `200`

| Campo | Qué es |
|---|---|
| `text` | La respuesta de Claude, en texto plano. Puede venir vacía. |
| `stop_reason` | Por qué terminó: `end_turn` (normal), `max_tokens` (se quedó sin tokens; el texto puede estar cortado o vacío), `refusal` (Claude se negó a responder), `stop_sequence`. |
| `request_id` | ID del pedido en Anthropic, útil para depurar. |
| `usage.input_tokens` / `usage.output_tokens` | Tokens consumidos (lo que se cobra). |

**Revisa siempre `stop_reason`**: un `200` con `max_tokens` o `refusal` no es
una respuesta usable.

#### Errores

Todos vienen como JSON con un campo `error` (en español):

| Código | Cuándo | Ejemplo de `error` |
|---|---|---|
| `400` | Cuerpo inválido: JSON roto, falta `prompt`, `effort` desconocido, cuerpo vacío o > 200 KB | `'prompt' es obligatorio y debe ser texto` |
| `401` | Token ausente o incorrecto | `token inválido` |
| `404` | Ruta que no existe | `no encontrado` |
| `502` | Anthropic respondió con error (trae además `detail` con el mensaje original), o no se pudo llegar a Anthropic | `la API respondió 529` / `no se pudo conectar con la API (¿warp caído?)` |
| `504` | Claude no respondió dentro de `timeout` | `Claude no respondió a tiempo` |

El servicio **no reintenta** por su cuenta: si tu app quiere reintentar un
`502`/`504`, lo hace ella (con una pausa de unos segundos).

## Ejemplos

### Python (`requests`)

```python
import os
import requests

CLAUDE_API_URL = os.environ.get("CLAUDE_API_URL", "http://plexserver:8787")
CLAUDE_API_TOKEN = os.environ["CLAUDE_API_TOKEN"]


def ask_claude(prompt: str, system: str | None = None, effort: str = "low",
               max_tokens: int = 2048, timeout: float = 60) -> str | None:
    """Devuelve el texto de Claude, o None si no hubo respuesta usable."""
    try:
        resp = requests.post(
            f"{CLAUDE_API_URL}/ask",
            headers={"Authorization": f"Bearer {CLAUDE_API_TOKEN}", "X-Caller": "mi-app"},
            json={"prompt": prompt, "system": system, "effort": effort,
                  "max_tokens": max_tokens, "timeout": timeout},
            timeout=timeout + 5,  # un poco más que el del servicio, para recibir su 504
        )
    except requests.RequestException:
        return None  # servicio apagado o red caída
    if resp.status_code != 200:
        return None  # resp.json()["error"] dice por qué
    data = resp.json()
    if data["stop_reason"] in ("max_tokens", "refusal") or not data["text"]:
        return None
    return data["text"]
```

### JavaScript / TypeScript (Node 18+, desde un backend)

```js
const CLAUDE_API_URL = process.env.CLAUDE_API_URL ?? "http://plexserver:8787";

async function askClaude(prompt, { system, effort = "low", maxTokens = 2048, timeout = 60 } = {}) {
  const resp = await fetch(`${CLAUDE_API_URL}/ask`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${process.env.CLAUDE_API_TOKEN}`,
      "Content-Type": "application/json",
      "X-Caller": "mi-app",
    },
    body: JSON.stringify({ prompt, system, effort, max_tokens: maxTokens, timeout }),
    signal: AbortSignal.timeout((timeout + 5) * 1000),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(`claude-api ${resp.status}: ${data.error}`);
  if (data.stop_reason === "max_tokens" || data.stop_reason === "refusal" || !data.text) {
    throw new Error(`respuesta no usable (stop_reason=${data.stop_reason})`);
  }
  return data.text;
}
```

## Cosas a tener en cuenta al construir una app

- **Llámalo desde un backend, no desde el navegador.** El servicio no tiene
  CORS y el token quedaría expuesto en el código del frontend. Una app web
  debe tener su propio servidor que guarde el token y llame a `claude-api`.
- **No tiene memoria.** Cada `/ask` es independiente y solo acepta un mensaje.
  Para una conversación, la app guarda el historial y lo incluye en `prompt`
  (por ejemplo: "Conversación hasta ahora: ... Usuario: ..."), o resume lo
  anterior para que no crezca sin límite.
- **El razonamiento gasta `max_tokens`.** Opus 5.5 siempre razona un poco
  antes de responder, y eso cuenta dentro de `max_tokens`. Con valores bajos
  la respuesta puede salir vacía y con `stop_reason: "max_tokens"`. Para
  respuestas cortas usa `effort: "low"` y `max_tokens` de 1024 a 2048; para
  respuestas largas, 4096.
- **Respuestas estructuradas.** Si necesitas JSON, pídelo en `system` (ej.
  "Responde solo con un objeto JSON con las claves ... sin texto alrededor")
  y valida el resultado en tu app: el servicio devuelve texto, no garantiza
  el formato.
- **Latencia.** Por el salto a través de warp, cuenta con varios segundos por
  respuesta (más con `effort` alto). Usa timeouts generosos (30-60 s) y
  muestra un indicador de "pensando" si hay un usuario esperando.
- **Ten un plan B.** warp a veces se cae o tarda: si la función de la app es
  importante, que siga funcionando sin la respuesta de Claude (como hace
  wan-monitor, que manda el aviso estático).
- **Costo.** Todo se cobra a la cuenta de Anthropic de starr-server. Para
  tareas simples y de mucho volumen, considera un modelo más barato.

## Modelos

Se pasa en `model`. Si no se manda, se usa `claude-opus-5-5`.

| Modelo | `model` | Cuándo usarlo |
|---|---|---|
| Claude Opus 5.5 | `claude-opus-5-5` | Default. El mejor para casi todo. |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | Más barato y rápido; muy bueno para tareas del día a día. |
| Claude Haiku 5.5 | `claude-haiku-5-5` | El más barato; clasificar, extraer datos, respuestas simples en volumen. |

Un nombre de modelo inválido devuelve `502` con el mensaje de Anthropic en
`detail`.

## Operación (en el servidor)

Configuración (en el `.env` de starr-server / `docker-compose.yml`):

| Variable | Default | Para qué |
|---|---|---|
| `ANTHROPIC_API_KEY` | (obligatoria) | Key de Anthropic, la misma que usa el bot de Telegram. |
| `CLAUDE_API_TOKEN` | (obligatoria) | El secreto compartido que mandan las apps. |
| `CLAUDE_DEFAULT_MODEL` | `claude-opus-5-5` | Modelo cuando el pedido no trae `model`. |
| `CLAUDE_DEFAULT_MAX_TOKENS` | `1024` | `max_tokens` cuando el pedido no lo trae. |
| `CLAUDE_MAX_TOKENS_CAP` | `4096` | Tope de `max_tokens` por pedido. |
| `CLAUDE_DEFAULT_TIMEOUT` | `60` | `timeout` cuando el pedido no lo trae. |
| `CLAUDE_PROXY` | `socks5://warp:1080` | Proxy de salida hacia Anthropic. |

Comandos útiles (en `~/starr-server`):

```bash
docker compose up -d --build claude-api   # aplicar cambios de código
docker logs -f claude-api                 # ver pedidos: quién, modelo, tokens
docker restart warp                       # si los pedidos dan 502 "¿warp caído?"
```

Cada pedido deja una línea en el log con quién lo hizo (`X-Caller` o la IP),
el modelo, el `stop_reason`, los tokens y el `request_id`. Nunca se registra
el contenido de los mensajes ni el token.

Para cambiar el servicio (por ejemplo, agregarle memoria o streaming) el
código está en [`server.py`](server.py).
