# Starr Server

Servidor de medios basado en Docker Compose que combina:

- `qBittorrent` como cliente de torrents
- `Prowlarr` como gestor de indexadores
- `Radarr` para gestión de películas
- `Sonarr` para gestión de series
- `Flaresolverr` para resolver captchas en búsquedas web
- `Warp` como proxy SOCKS5 para las solicitudes de red
- Un bot de Telegram con IA para buscar y agregar películas, series y episodios

## Qué hace este proyecto

Este proyecto monta un media server completo que permite buscar y descargar contenido multimedia mediante una interfaz de chat en Telegram.

El bot usa la API de Claude de Anthropic para interpretar mensajes naturales en español y luego interactúa con Radarr y Sonarr para: 

- buscar películas por nombre
- agregar películas a Radarr
- buscar series y agregarlas a Sonarr
- buscar episodios puntuales en series ya agregadas
- lanzar búsquedas de descarga de episodios específicos

## Características principales

- despliegue con `docker compose`
- gestión de descargas de películas y series
- interacción vía bot de Telegram
- uso de APIs de Radarr y Sonarr
- opciones de descarga automática a través de indexadores configurados en Prowlarr
- proxy WARP para tráfico de red saliente del bot

## Requisitos

- Docker
- Docker Compose
- Token de Telegram Bot
- API key de Anthropic
- API key de Radarr
- API key de Sonarr

## Estructura del proyecto

- `docker-compose.yml` - define los servicios del stack
- `telegram-bot/` - código fuente y Dockerfile del bot de Telegram
- `telegram-bot/bot.py` - lógica principal del bot y las integraciones con Radarr/Sonarr
- `telegram-bot/requirements.txt` - dependencias de Python del bot

## Configuración y uso

1. Clona o copia el repositorio en tu servidor.

2. Crea un archivo `.env` en la raíz del proyecto con las variables necesarias:

```env
TELEGRAM_BOT_TOKEN=tu_token_de_telegram
ANTHROPIC_API_KEY=tu_api_key_de_anthropic
RADARR_API_KEY=tu_api_key_de_radarr
SONARR_API_KEY=tu_api_key_de_sonarr
```

3. Ajusta los valores de zona horaria si es necesario en `docker-compose.yml` (`TZ=America/Bogota`).

4. Inicia el stack:

```bash
docker compose up -d
```

5. Verifica que los servicios estén corriendo:

- `http://localhost:8080` para qBittorrent
- `http://localhost:9696` para Prowlarr
- `http://localhost:7878` para Radarr
- `http://localhost:8989` para Sonarr
- `http://localhost:8191` para Flaresolverr

6. Inicia el bot de Telegram automáticamente con el servicio `telegram-bot`.

## Cómo usar el bot

Abre el chat del bot en Telegram y escribe comandos en lenguaje natural. Ejemplos:

- "Quiero ver Oppenheimer"
- "Descarga Breaking Bad"
- "Busca la última película de Nolan"
- "Necesito el episodio S02E05 de The Witcher"

El bot interpreta la intención, busca resultados y ejecuta las acciones necesarias en Radarr o Sonarr.

## Variables de entorno

- `TELEGRAM_BOT_TOKEN` - token del bot de Telegram
- `ANTHROPIC_API_KEY` - clave de API para Anthropic
- `RADARR_API_KEY` - clave de API para Radarr
- `SONARR_API_KEY` - clave de API para Sonarr
- `RADARR_URL` - URL interna de Radarr en el stack (por defecto `http://radarr:7878`)
- `SONARR_URL` - URL interna de Sonarr en el stack (por defecto `http://sonarr:8989`)

## Notas importantes

- El bot usa la API de Claude (`claude-haiku-4-5-20251001`) y ejecuta llamadas a `search_movie`, `add_movie`, `search_series`, `add_series`, `search_episode` y `download_episode`.
- Las descargas se gestionan a través de Radarr y Sonarr, por lo que es necesario tenerlos correctamente configurados con root folders y perfiles de calidad en su propia interfaz.
- La configuración de descargas y el comportamiento de indexadores se define en Prowlarr y en las propias aplicaciones de Radarr/Sonarr.

## Licencia

Este proyecto se publica bajo la licencia MIT, lo que permite a cualquiera descargarlo, usarlo, modificarlo y distribuirlo libremente.
