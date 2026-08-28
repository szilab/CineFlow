# CineFlow

[![CI/CD Pipeline](https://github.com/szilab/CineFlow/actions/workflows/ci_cd.yaml/badge.svg)](https://github.com/szilab/CineFlow/actions/workflows/ci_cd.yaml)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
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

- Python >= 3.13 or Docker
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

### Local development (Windows)

Install [uv](https://docs.astral.sh/uv/) once:

```powershell
winget install --id=astral-sh.uv -e
```

Clone the project and create the managed development environment. No virtual
environment activation is needed:

```powershell
git clone https://github.com/szilab/CineFlow.git
cd CineFlow
uv sync
```

Run CineFlow:

```powershell
uv run cineflow
# Or: uv run python -m cineflow.main
```

For development, use the tools through uv:

```powershell
uv run pytest
uv run pytest --cov=cineflow --cov-report=term-missing
uv run flake8 .
uv run pylint cineflow
uv build
```

CI enforces a minimum line coverage of 75%. For a local HTML report, run
`uv run pytest --cov=cineflow --cov-report=html`.

To install a release wheel outside a development checkout, use `uv tool install`
or `uv pip install` in the environment where CineFlow will run.

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

Module configuration precedence is global configuration, then flow-step `config`, then environment override. Environment overrides preserve an existing boolean, integer, or float type; values without a type hint remain strings.

## Project Structure

```
cineflow/
├── main.py                 # Application entry point
├── core/                   # Framework internals
│   ├── bases/              # Abstract base classes
│   │   ├── module.py       # ModuleBase, ConsumerBase, LibraryBase
│   │   ├── worker.py       # WorkerBase (threaded execution)
│   │   └── singleton.py    # SingletonMeta metaclass
│   ├── config.py           # Configuration management (YAML + ENV)
│   ├── database.py         # SQLite cache database
│   ├── logger.py           # Structured logging
│   └── runner.py           # Workflow orchestration engine
├── integrations/           # External service integrations
│   ├── tmdb.py             # TMDb metadata API
│   ├── jackett.py          # Jackett torrent indexer
│   ├── jellyfin.py         # Jellyfin media server
│   └── transmission.py     # Transmission download client
├── internal/               # Internal modules (not external APIs)
│   ├── library.py          # File system library management
│   └── tools.py            # Utility tools (export/import/dedup)
└── utils/                  # Pure utility functions
    ├── directory.py        # Directory operations
    ├── image.py            # Image processing (posters)
    ├── misc.py             # Helpers (sanitize, evaluate, load_module)
    └── request.py          # HTTP request handler with caching/rate-limit
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
