# CineFlow

[![CI/CD Pipeline](https://github.com/szilab/CineFlow/actions/workflows/ci_cd.yaml/badge.svg)](https://github.com/szilab/CineFlow/actions/workflows/ci_cd.yaml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

CineFlow is an open-source media automation system for discovering, managing, and organizing your movie collection. Inspired by [Overseerr](https://overseerr.dev) and [Jellyseerr](https://docs.jellyseerr.dev), CineFlow provides a streamlined approach to media management with support for multiple third-party integrations.

---

## Features

### Core Capabilities
- Automated media discovery via TMDb
- Torrent search integration through Jackett
- Media server synchronization with Jellyfin
- Download automation using Transmission
- Export (dummy) libraries for preview and staging
- Rule-based poster modifications (status indicators)
- YAML-based configuration and workflows
- Long-running worker execution model

### Supported Integrations
- **TMDb** – metadata and discovery
- **Jackett** – torrent indexer aggregation
- **Jellyfin** – media server
- **Transmission** – download client

---

## Execution Model

CineFlow runs as a **long-lived worker process**, not a one-shot CLI tool.

- Each flow runs in its own loop
- Execution interval is defined inside the flow
- CineFlow continuously evaluates and executes workflows
- No external scheduler (cron/systemd) is required

This makes CineFlow suitable for always-on automation, especially in Docker environments.

---

## How It Works

1. **Discovery**  
   Flows periodically collect trending or popular movies from TMDb.

2. **Indexing**  
   Available downloads are searched via Jackett using configurable rules.

3. **Library Export**  
   Placeholder (export) libraries are created and synchronized with Jellyfin.

4. **Visual Indicators**  
   Poster modifications are applied via flow-defined rules, for example:
   - Grayscale for missing media
   - Borders or markers for specific qualities (HDR, resolution, etc.)

5. **Automation via Flows**  
   Default flows can:
   - Detect favorites in Jellyfin
   - Trigger downloads
   - Maintain library state

---

## Prerequisites

- Python >= 3.10 or Docker
- TMDb API key ([Request here](https://www.themoviedb.org/settings/api))
- Jackett instance with configured trackers
- Jellyfin media server
- Transmission download client

---

## Installation & Running

### Docker (Recommended)

#### Docker Run

```bash
docker run -d \
  --name cineflow \
  --restart unless-stopped \
  -v /path/to/library:/data \
  -v /path/to/config:/config \
  -e CFG_DIRECTORY=/config \
  -e EXPORT_DIRECTORY=/data \
  ghcr.io/szilab/cineflow:latest
```

#### Docker Compose

```yaml
services:
  cineflow:
    image: ghcr.io/szilab/cineflow:latest
    container_name: cineflow
    restart: unless-stopped
    volumes:
      - /path/to/library:/data
      - /path/to/config:/config
    environment:
      CFG_DIRECTORY: /config
      EXPORT_DIRECTORY: /data
      LOG_LEVEL: INFO
      TMDB_TOKEN: your_tmdb_token
```

When running via Docker:
* If the configuration directory is empty, **default example flows are copied automatically**
* These flows provide a ready-to-use automation setup

### Local / CLI Installation

Download the latest wheel from GitHub Releases and run:

```bash
pip install cineflow-*.whl
export CFG_DIRECTORY="/path/to/your/config"
export EXPORT_DIRECTORY="/path/to/your/library"
cineflow
```

## Configuration

CineFlow uses a dual configuration system:
1. **Global Configuration** (`config.yaml`) - System-wide settings for modules
2. **Flow Configuration** (`.yaml` files) - Workflow definitions and automation logic

For detailed flow syntax and examples, see:
**docs/CONFIGURATION.md**
**docs/FLOWS.md**

### Environment Variables

- `CFG_DIRECTORY`: Configuration directory path
- `EXPORT_DIRECTORY`: Library export path
- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)
- `LOG_COLORS`: Enable colored logs (true/false)

Any setting from `config.yaml` can be overridden via environment variables using:
```bash
MODULENAME_SETTING=xy
```

## Project Structure

```
cineflow/
├── bases
├── modules
├── system
└── main.py
```

## Roadmap

- [ ] TV Series support
- [ ] Web UI interface
- [ ] Additional downloader support (qBittorrent, etc.)
- [ ] Additional media server support (Plex)
- [ ] Advanced filtering and scheduling
- [ ] Notification system

## Contributing

Contributions are welcome.
Please see our [Contributing Guide](docs/CONTRIBUTING.md) for details on how to get started.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- 📚 [Documentation](https://github.com/szilab/CineFlow/wiki)
- 🐛 [Issue Tracker](https://github.com/szilab/CineFlow/issues)
- 💬 [Discussions](https://github.com/szilab/CineFlow/discussions)

## Acknowledgments

- Inspired by [Overseerr](https://overseerr.dev) and [Jellyseerr](https://docs.jellyseerr.dev)
- Self-hosted community