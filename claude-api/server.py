"""Puente HTTP hacia Claude para otros servicios de la casa.

Desde esta red Claude solo responde saliendo por el proxy `warp` (EE.UU.), así
que en vez de que cada servicio tenga su propia API key y su propio proxy, le
piden el mensaje a este servicio:

    POST /ask
    Authorization: Bearer <CLAUDE_API_TOKEN>
    {"prompt": "...", "system": "...", "model": "...", "effort": "low",
     "max_tokens": 1024, "timeout": 10}

    200 -> {"text": "...", "stop_reason": "end_turn", "request_id": "...",
            "usage": {"input_tokens": N, "output_tokens": N}}
    400 cuerpo inválido · 401 token incorrecto · 502 error de la API · 504 timeout

Solo `prompt` es obligatorio. Cada pedido es independiente (sin memoria).
"""

import hmac
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import anthropic
import httpx2
from anthropic import Anthropic, DefaultHttpxClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("claude-api")

API_TOKEN = os.environ["CLAUDE_API_TOKEN"]
PORT = int(os.environ.get("PORT", "8787"))
PROXY = os.environ.get("CLAUDE_PROXY", "socks5://warp:1080")
DEFAULT_MODEL = os.environ.get("CLAUDE_DEFAULT_MODEL", "claude-opus-5-5")
DEFAULT_MAX_TOKENS = int(os.environ.get("CLAUDE_DEFAULT_MAX_TOKENS", "1024"))
# Tope para que un servicio no pueda disparar respuestas enormes (y caras).
MAX_TOKENS_CAP = int(os.environ.get("CLAUDE_MAX_TOKENS_CAP", "4096"))
DEFAULT_TIMEOUT = float(os.environ.get("CLAUDE_DEFAULT_TIMEOUT", "60"))
MAX_BODY_BYTES = 200_000
EFFORTS = {"low", "medium", "high", "xhigh", "max"}

# max_retries=0: quien llama decide si reintenta; acá un reintento silencioso
# solo haría que su timeout venza sin recibir respuesta.
# El proxy va en un transport propio y con trust_env=False: si no,
# DefaultHttpxClient monta igual los proxies de HTTPS_PROXY/HTTP_PROXY del
# entorno (ej. inyectados por Docker Desktop) y esos le ganan a `proxy=`,
# sacando el tráfico sin pasar por warp.
client = Anthropic(
    http_client=DefaultHttpxClient(
        transport=httpx2.HTTPTransport(proxy=PROXY or None),
        trust_env=False,
    ),
    max_retries=0,
)


class BadRequest(Exception):
    pass


def parse_request(body: dict) -> tuple[dict, float]:
    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise BadRequest("'prompt' es obligatorio y debe ser texto")
    system = body.get("system")
    if system is not None and not isinstance(system, str):
        raise BadRequest("'system' debe ser texto")
    model = body.get("model") or DEFAULT_MODEL
    if not isinstance(model, str):
        raise BadRequest("'model' debe ser texto")
    try:
        max_tokens = min(int(body.get("max_tokens") or DEFAULT_MAX_TOKENS), MAX_TOKENS_CAP)
        timeout = float(body.get("timeout") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        raise BadRequest("'max_tokens' y 'timeout' deben ser números")
    if max_tokens < 1 or timeout <= 0:
        raise BadRequest("'max_tokens' y 'timeout' deben ser positivos")

    params = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        params["system"] = system
    effort = body.get("effort")
    if effort is not None:
        if effort not in EFFORTS:
            raise BadRequest(f"'effort' debe ser uno de {sorted(EFFORTS)}")
        params["output_config"] = {"effort": effort}
    return params, timeout


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._reply(200, {"ok": True})
        else:
            self._reply(404, {"error": "no encontrado"})

    def do_POST(self) -> None:
        if self.path != "/ask":
            self._reply(404, {"error": "no encontrado"})
            return
        auth = self.headers.get("Authorization", "")
        if not hmac.compare_digest(auth.encode(), f"Bearer {API_TOKEN}".encode()):
            self._reply(401, {"error": "token inválido"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY_BYTES:
                raise BadRequest("cuerpo vacío o demasiado grande")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise BadRequest("el cuerpo debe ser un objeto JSON")
            params, timeout = parse_request(body)
        except (BadRequest, ValueError) as exc:
            self._reply(400, {"error": str(exc)})
            return

        caller = self.headers.get("X-Caller", self.client_address[0])
        try:
            response = client.with_options(timeout=timeout).messages.create(**params)
        except anthropic.APITimeoutError:
            log.warning("[%s] timeout tras %ss (model=%s)", caller, timeout, params["model"])
            self._reply(504, {"error": "Claude no respondió a tiempo"})
            return
        except anthropic.APIStatusError as exc:
            log.warning("[%s] la API respondió %s: %s", caller, exc.status_code, exc.message)
            self._reply(502, {"error": f"la API respondió {exc.status_code}", "detail": exc.message})
            return
        except anthropic.APIConnectionError as exc:
            log.warning("[%s] sin conexión con la API: %s", caller, exc)
            self._reply(502, {"error": "no se pudo conectar con la API (¿warp caído?)"})
            return

        # Solo texto: los bloques de thinking vienen vacíos por defecto.
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        log.info(
            "[%s] model=%s stop=%s in=%s out=%s request_id=%s",
            caller, params["model"], response.stop_reason,
            response.usage.input_tokens, response.usage.output_tokens, response._request_id,
        )
        self._reply(200, {
            "text": text,
            "stop_reason": response.stop_reason,
            "request_id": response._request_id,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        })

    def log_message(self, format: str, *args) -> None:
        pass  # el log útil ya lo hace do_POST


def main() -> None:
    log.info("claude-api escuchando en :%s (proxy=%s, modelo por defecto=%s)", PORT, PROXY, DEFAULT_MODEL)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
