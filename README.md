# mmWave Visualizer (Docker)

> **Obsolete.** Use [nickduvall921/mmwave_vis](https://github.com/nickduvall921/mmwave_vis)
> instead. It now runs in Docker as well as as a Home Assistant add-on, and upstream has
> deprecated the standalone Docker repo this was forked from.

A web UI for Inovelli mmWave smart switches in Zigbee2MQTT: live 2D tracking of up to
three targets, and visual setup of detection, interference and stay zones.

This is a fork of [nickduvall921/mmWave_vis_docker](https://github.com/nickduvall921/mmWave_vis_docker)
by Nick Duvall, who wrote the visualizer. In February 2026 the Docker version lagged behind
the add-on, so this fork brought `app.py` and the web page up to the newer version. That gap
no longer exists upstream.

## Running it

Set your MQTT broker in `docker-compose.yml`, then:

```bash
docker compose up -d --build
```

Open `http://<host>:5000`.
