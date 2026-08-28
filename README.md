# CineFlow

[![CI/CD Pipeline](https://github.com/szilab/CineFlow/actions/workflows/ci_cd.yaml/badge.svg)](https://github.com/szilab/CineFlow/actions/workflows/ci_cd.yaml)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

CineFlow is an open-source, configuration-driven media automation system for discovering, managing, and organizing media collections.

CineFlow is inspired by media request and automation tools such as Overseerr/Jellyseerr/Seerr, but it intentionally follows a different model: **the workflow engine and replaceable integration modules are the product core**. Jellyfin, Plex, TMDb, Jackett, Transmission, and future integrations such as Radarr, Sonarr, Trakt, or Simkl can participate as optional workflow steps rather than forming a mandatory stack.

The current runtime is headless and YAML-driven. A first-party GUI is planned to make global/module configuration and workflow creation significantly easier while preserving YAML as the portable source-of-truth format.

---

## Features

### Core Capabilities
- Automated media discovery via TMDb
- Torrent search integration through Jackett
- Media server synchronization with Jellyfin and Plex
- Download automation using Transmission
- Export (dummy) libraries for preview and staging
- Rule-based poster modifications (status indicators)
- YAML-based configuration and workflows
- Long-running worker execution model
- Parallel or sequential workflow execution

### Supported Integrations
- **TMDb** – metadata and discovery
- **Jackett** – torrent indexer aggregation
- **Jellyfin** – media server and user/library state
- **Plex** – media server and library state
- **Transmission** – download client

### Planned Optional Integrations
- **Radarr** – movie acquisition/management workflow module
- **Sonarr** – TV/series acquisition/management workflow module
- **Trakt** – portable watchlist/history/state workflow module
- **Simkl** – portable watched/history/list state workflow module

No planned integration is intended to become a mandatory dependency. Existing direct workflows such as `Jackett → Transmission` remain valid alongside higher-level alternatives such as `TMDb → Radarr`.

---

## Product Direction

CineFlow is not intended to reproduce a full Seerr-style request-management application.

The main direction is:

1. Keep integrations modular and replaceable.
2. Make configuration safe and machine-validatable.
3. Add a first-party GUI for global/module configuration.
4. Add a drag-and-drop workflow editor that reads and writes standard CineFlow YAML.
5. Add optional Radarr/Sonarr integration without removing direct downloader workflows.
6. Add optional online watched-state providers such as Trakt and Simkl.
7. Introduce persistent application state only when a concrete feature requires data that cannot be represented reliably by configuration or external state providers.

See **[docs/ROADMAP.md](docs/ROADMAP.md)** for the detailed roadmap.

---

## Execution Model

CineFlow runs as a **long-lived worker process**, not a one-shot CLI tool.

- Each flow runs in its own loop in parallel mode
- Sequential mode executes due flows one at a time
- Execution interval is defined inside each flow
- CineFlow continuously evaluates and executes workflows
- No external scheduler (cron/systemd) is required

This makes CineFlow suitable for always-on automation, especially in Docker environments.

---

## How It Works

CineFlow behavior is assembled from workflows rather than hard-coded into a single fixed media stack.

A typical direct workflow can look like:

```text
Jellyfin Favorites → Jackett → Transmission
```

Another deployment may eventually use:

```text
Trakt Watchlist → Radarr
```

or:

```text
TMDb → Radarr
```

The same workflow engine is responsible for passing media data between modules.

Current default examples include:

1. **Discovery**  
   Flows periodically collect trending or popular movies from TMDb or recent releases from Jackett.

2. **Indexing**  
   Available downloads are searched via Jackett using configurable rules.

3. **Library Export**  
   Placeholder (export) libraries are created and synchronized with Jellyfin/Plex.

4. **Visual Indicators**  
   Poster modifications are applied via flow-defined rules, for example:
   - Grayscale for missing media
   - Borders or markers for specific qualities (HDR, resolution, etc.)

5. **Automation via Flows**  
   Flows can detect media-server state such as favorites, enrich items, filter existing media, and trigger later actions.

---

## Prerequisites

The exact prerequisites depend on the workflows you enable.

For the supplied example workflows:

- Python >= 3.13 or Docker
- TMDb API key ([Request here](https://www.themoviedb.org/settings/api))
- Jackett instance with configured trackers
- Jellyfin media server
- Transmission download client

Plex can be used by workflows where appropriate. Future Radarr, Sonarr, Trakt, and Simkl modules will likewise remain optional.

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

CineFlow currently uses a dual YAML configuration system:

1. **Global Configuration** (`config.yaml`) - System-wide settings for modules
2. **Flow Configuration** (`.yaml` files) - Workflow definitions and automation logic

YAML will remain the portable source-of-truth configuration format. The planned GUI will operate on the same configuration and validation model rather than introduce a separate proprietary representation.

For detailed syntax and examples, see:

- **[docs/CONFIGURATION.md](docs/CONFIGURATION.md)**
- **[docs/FLOWS.md](docs/FLOWS.md)**
- **[docs/ROADMAP.md](docs/ROADMAP.md)**

### Environment Variables

- `CFG_DIRECTORY`: Configuration directory path
- `EXPORT_DIRECTORY`: Library export path
- `DB_DIRECTORY`: SQLite cache database directory
- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)
- `LOG_COLORS`: Enable colored logs (true/false)

Module settings may be overridden through environment variables. See `docs/CONFIGURATION.md` for current behavior and known limitations.

Module configuration precedence is global configuration, then flow-step `config`, then environment override. Environment overrides preserve an existing boolean, integer, or float type; values without a type hint remain strings.

## Project Structure

```text
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
│   ├── plex.py             # Plex media server
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

Major roadmap themes:

- [ ] Formal module/configuration metadata and validation
- [ ] First-party configuration GUI
- [ ] Drag-and-drop workflow editor
- [ ] Workflow runtime/status observability
- [ ] Optional Radarr integration
- [ ] Optional Sonarr integration and mature TV workflow support
- [ ] Optional Trakt integration
- [ ] Optional Simkl integration
- [ ] Notification/webhook modules
- [ ] Persistent application state only where justified by concrete features

See **[docs/ROADMAP.md](docs/ROADMAP.md)** for sequencing and design principles.

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

- Inspired by Overseerr/Jellyseerr/Seerr and the wider self-hosted media automation ecosystem
- Self-hosted community
