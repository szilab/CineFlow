# Configuration Guide

CineFlow is configuration-driven. Core code provides reusable capabilities, while runtime behavior is assembled from module configuration and workflows.

The current configuration format is YAML. YAML is intended to remain the portable source-of-truth format even after the first-party GUI is introduced.

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
global module configuration < workflow step config < environment override
```

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
  region: HU

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

library:
  directory: movies
  limit: 50
  age: 30
```

Only configure modules that are actually used by your workflows. CineFlow does not require all integrations to be configured.

## Module Configuration

### TMDb

```yaml
tmdb:
  token: API_KEY
  language: en-US
  region: HU
```

Common settings:

- `token` — required API token;
- `language` — metadata language, default `en-US`;
- `region` — discovery/watch region, default `US`;
- `quick_match` — optionally allow a single search result to match without strict year comparison.

### Jackett

```yaml
jackett:
  url: http://jackett:9117
  token: API_KEY
  include: HUN
  size_limit_gb: 26
  search_preference: ["HUN", "HDR", "1080p", "2160p"]
```

Jackett can be used directly with download clients or omitted from workflows that use future higher-level integrations such as Radarr/Sonarr.

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

### Library

The internal library module creates and manages exported/dummy media entries under `EXPORT_DIRECTORY`.

```yaml
library:
  directory: movies
  limit: 50
  age: 30
```

- `directory` — subdirectory inside `EXPORT_DIRECTORY`;
- `limit` — maximum retained exported items;
- `age` — maximum age in days before cleanup.

Cleanup runs synchronously when the library is read through its normal `get` action.

## Poster Rules

The library module can modify exported poster images according to rules.

Example:

```yaml
library:
  rules:
    - expression: contains
      property: torrent
      value: HUN
      case_sensitive: false
      color: red
      modification: border
```

Common fields:

| Field | Description |
|---|---|
| `expression` | comparison such as `missing`, `exists`, or `contains` |
| `modification` | visual operation such as `grayscale`, `border`, or `triangle` |
| `property` | media property to evaluate |
| `value` | optional comparison value |
| `case_sensitive` | optional case-sensitivity flag |

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

For predictable operation, **restart CineFlow after changing global configuration**.

Workflow files themselves are monitored by the flow manager and can be reloaded when their content changes.

## Validation Direction

The current runtime performs validation in several places, including required module configuration and basic workflow structure. The roadmap extends this into a formal shared validation model.

Planned validation metadata will allow each module to describe:

- available actions;
- configuration fields;
- required/optional fields;
- value types;
- defaults;
- user-facing descriptions;
- secret fields;
- action input/output expectations where practical.

The same validation contract should be consumed by:

- the runtime;
- a non-destructive CLI validation command;
- the first-party configuration GUI;
- the visual workflow editor.

This avoids maintaining separate validation rules for YAML and GUI-created configuration.

## Planned GUI

The GUI will be a frontend for the same YAML configuration model, not a separate configuration database.

Planned capabilities include:

- list available modules;
- generate configuration forms from module metadata;
- validate global and module settings before saving;
- identify required and secret fields;
- provide optional safe connectivity checks;
- edit runtime/global settings;
- save valid configuration back to YAML;
- expose advanced/raw YAML editing where useful.

For the workflow editor direction, see [FLOWS.md](FLOWS.md). For roadmap sequencing, see [ROADMAP.md](ROADMAP.md).
