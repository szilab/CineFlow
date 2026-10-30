# Configuration Guide

CineFlow is configuration-driven. Core code provides reusable capabilities, while runtime behavior is assembled from module configuration and workflows.

The configuration format is YAML, and it remains the source of truth: the optional web GUI ([GUI.md](GUI.md)) reads and writes the same files.

## Configuration Layers

CineFlow currently uses two configuration layers:

1. **Global Configuration** (`config.yaml`)
   - system-wide module defaults and integration credentials;
   - runtime-level settings such as execution mode.

2. **Workflow Configuration** (`*.yaml`, except `config.yaml`)
   - workflow scheduling;
   - ordered module/action steps;
   - per-step configuration overrides;
   - data passed between steps.

Module settings use this precedence, from lowest to highest:

```text
module default < named instance < workflow step config < environment override
```

Named instances are optional; see [Module Instances](#module-instances).

Nested dictionaries from global and step configuration are merged recursively, so a step can override one nested setting without replacing unrelated global values.

## Configuration Directory

The configuration directory is defined with:

```bash
CFG_DIRECTORY=/path/to/config
```

Typical structure:

```text
config/
├── config.yaml
├── from_tmdb.yaml
├── from_lib.yaml
└── custom_flow.yaml
```

When either supported distribution starts with an empty configuration directory,
the bundled example configuration is copied into it automatically. Existing files
are never overwritten.

Runtime paths are controlled by the following variables:

- `CINEFLOW_HOME` sets the application root for default `config`, `library`, and `media` directories.
- `CFG_DIRECTORY` explicitly sets the configuration directory.
- `EXPORT_DIRECTORY` explicitly sets the exported-library directory.
- `MEDIA_DIRECTORY` optionally points to external `sample.<resolution>.mp4` files.

The three explicit directory variables take precedence over `CINEFLOW_HOME`.
Without overrides, the standalone Windows executable uses its own directory as
the application root. Docker defines its existing `/config`, `/library`, and
`/app/media` paths through environment variables.

## Global Configuration

Example:

```yaml
execution: parallel

tmdb:
  token:
  language: en-US

jackett:
  url:
  token:
  categories: "2000"
  search_preference: ["HUN", "HDR", "1080p", "2160p"]

jellyfin:
  url:
  token:
  ignore:
    users: []

plex:
  url:
  token:
  ignore:
    libraries: []

transmission:
  url:
  username:
  password:

qbittorrent:
  url:
  username:
  password:
  directory:
  category:
  tags:

library:
  directory: movies
  limit: 50
  age: 30
  search_preference: ["HUN", "HDR", "1080p", "2160p"]
```

Only configure modules that are actually used by your workflows. CineFlow does not require all integrations to be configured.

## Module Configuration

### TMDb

```yaml
tmdb:
  token: API_KEY
  language: en-US
```

Common settings:

- `token` — required API token;
- `language` — metadata language, default `en-US`;
- `quick_match` — optionally allow a single search result to match without strict year comparison.

`get` collects the weekly trending list. The trending endpoint has no region
filter, so the former `region` setting had no effect and is no longer read.
IMDb IDs are looked up only for collected or matched items, and those lookups
are cached for 30 days. `search` uses the TMDb ID when present, otherwise the
IMDb ID, and falls back to a title search.

### Jackett

```yaml
jackett:
  url: http://jackett:9117
  token: API_KEY
  include: HUN
  size_limit_gb: 26
  search_preference: ["HUN", "HDR", "1080p", "2160p"]
```

Jackett can be used directly with download clients or omitted from workflows that
use future higher-level integrations such as Radarr/Sonarr. Earlier
`search_preference` entries receive higher scores and sort the Jackett results.
Results that only carry a magnet URI use it as their `link`.

A `get` step query supports `include` (all words must be present), `exclude`,
`seeders`, `resolution`, and `size` (GB). `exclude` is either a word list or a
string of words that must not be present, or `true` to invert `include`:

```yaml
input:
  query:
    include: HUN
    exclude: [CAM, TS]
    seeders: 40
```

### Jellyfin

```yaml
jellyfin:
  url: http://jellyfin:8096
  token: API_KEY
  ignore:
    users:
      - username
```

Jellyfin can act as a media/library state source inside workflows, including favorite-based automation.

### Plex

```yaml
plex:
  url: http://plex:32400
  token: PLEX_TOKEN
  ignore:
    libraries:
      - Library Name
```

Plex is an optional alternative media-server module.

### Transmission

```yaml
transmission:
  url: http://transmission:9091
  username:
  password:
  directory:
```

Authentication is optional when the Transmission instance does not require it.

### qBittorrent

```yaml
qbittorrent:
  url: http://qbittorrent:8080
  username:
  password:
  directory:
  category:
  tags:
```

Authentication is optional when qBittorrent is configured to bypass WebAPI authentication for the CineFlow client. `directory` maps to qBittorrent `savepath`; `category` and `tags` are passed through when configured.

### Library

The internal library module creates and manages exported/dummy media entries under `EXPORT_DIRECTORY`.

```yaml
library:
  directory: movies
  limit: 50
  age: 30
```

- `directory` — subdirectory inside `EXPORT_DIRECTORY`;
- `limit` — maximum retained exported items (default 500, minimum 10);
- `age` — maximum age in days before cleanup (default 120, minimum 30);
- `search_preference` — release name preferences used to rank releases.

A background worker applies `limit` and `age` once an hour for every library
directory used by a flow. The first cleanup runs one hour after start, so
reading the library with `get` never deletes items.

Earlier `search_preference` entries receive higher scores. When CineFlow finds
a release for an item already exported to the library, it rewrites the item
only when the new release has a strictly higher score; tracker URL or
seeder-count changes alone do not refresh it. The library reads only its own
`search_preference`; copy the Jackett list here to keep the earlier ranking.

Each exported video file gets the publish time as its modification time.
Jellyfin derives "Date added" from these timestamps, so sorting the library by
date added shows new items and upgraded releases first, while unchanged items
keep their place.

Library identity is based on TMDb ID, with IMDb ID as a fallback. Once an item
is exported, a title punctuation or release-year change reuses its existing
directory rather than creating a duplicate.

## Poster Rules

The library module can modify exported poster images according to rules.

Example:

```yaml
library:
  rules:
    - expression: token
      property: torrent
      value: HUN
      case_sensitive: false
      color: red
      modification: border
```

Common fields:

| Field | Description |
|---|---|
| `expression` | comparison such as `missing`, `exists`, `contains`, or `token` |
| `modification` | visual operation such as `grayscale`, `border`, or `triangle` |
| `property` | media property to evaluate |
| `value` | optional comparison value |
| `case_sensitive` | optional case-sensitivity flag |

`token` matches a complete release-name token. It matches `HUN` in
`Some.Movie.2005.1080.HUN.DVDRip`, including when separated by `.`, `-`, `_`,
or spaces, but does not match it inside `Hungry`.

## Environment Overrides

Module values can be overridden through environment variables generated from the module and key name.

For example, a simple module setting may be overridden as:

```text
TMDB_TOKEN=...
JACKETT_SIZE_LIMIT_GB=26
```

Current conversion rules:

- booleans preserve boolean type;
- integers preserve integer type;
- floats preserve float type;
- values without an existing type hint remain strings.

Boolean values accept `true/false`, `1/0`, `yes/no`, and `on/off` case-insensitively.

### Current limitation

Environment overrides are most suitable for simple scalar values. Nested keys and list/dictionary configuration are not yet represented by a polished public environment-variable convention. Prefer YAML for complex configuration until the configuration model is formalized.

## Runtime Reload Behavior

`config.yaml` is read by the configuration layer when values are requested, but module instances can retain merged configuration for their lifetime. Therefore, changing global module configuration while CineFlow is running is not currently guaranteed to update already-created module instances.

For predictable operation, **restart CineFlow after editing `config.yaml` by hand**.
Settings saved in the web GUI apply without a restart: every flow rebuilds its
module objects at the next step. Changing the execution mode always needs a
restart.

If `config.yaml` becomes invalid while CineFlow is running (for example while it is
being saved), CineFlow logs an error and keeps using the last valid configuration.
An invalid file at startup stops CineFlow with a clear error instead of running
with an empty configuration.

Workflow files themselves are monitored by the flow manager and can be reloaded when their content changes.

## Module Instances

Each module section in `config.yaml` is the default configuration of that
module. To use several servers of the same kind, add named instances:

```yaml
instances:
  living-room:
    module: jellyfin
    name: Living room Jellyfin
    config:
      url: http://living-room:8096
      token: API_KEY
```

A flow step selects one with `instance: living-room`. The instance inherits
the module default, so only the differing values need to be set. Instance ids
use lower-case letters, digits, `-` and `_`, and must differ from module
names.

## TV Series

Every module accepts `kind: movie` (default) or `kind: tv`, globally or per
step. With `kind: tv`:

- TMDb collects and searches TV shows (`/trending/tv`, `/search/tv`, ...);
- Jackett searches the TV category (5000) by show title without the year and
  parses release names such as `Show.S01E02`, `Show.2019.S03` or
  `Show Season 2` into `title`, optional `year`, `season` and `episode`;
  `season_pack_only` (default `true`) drops single-episode releases;
- Jellyfin queries `Series` items, Plex queries shows;
- Transmission and qBittorrent parse series names of their torrents;
- the library exports `Show (Year) [tmdbid-N]/Season NN/Show SNNE01.mkv`, so a
  media server recognizes the placeholder as a series.

A series item may have no year when it comes from a release name; title
matching then ignores the unknown year. Use a separate library directory for
series, for example `config: {directory: shows, kind: tv}` on the library
steps. Mature episode tracking is better left to an optional Sonarr module
(see the roadmap).

## Validation

```bash
cineflow validate          # exit code 1 when anything has errors
cineflow validate --json
```

The command validates `config.yaml` and every flow without starting workers,
contacting services or creating files. Every module declares its fields and
actions, and the same validator serves the CLI, the runtime log and the GUI.
See [GUI.md](GUI.md#validation) for the checks.

## Web GUI

Set `CINEFLOW_WEB_PORT` (and optionally `CINEFLOW_WEB_HOST`) to serve the web
GUI. Optional sign-in with a local password, OIDC single sign-on or a trusted
reverse-proxy header is configured with `CINEFLOW_AUTH`; on a non-loopback
address the GUI does not start without it. Details in [GUI.md](GUI.md#authentication).
