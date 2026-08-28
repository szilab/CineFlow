# Flow Configuration Guide

This document describes how CineFlow is configured and how its **flow-based automation system** works.

CineFlow is intentionally designed so that:
- Core code provides capabilities
- **All behavior is defined by configuration**
- No code changes are required to customize automation

---


## Configuration Overview

CineFlow uses **two configuration layers**:

1. **Global Configuration**  
   Defines system-wide settings and integration credentials.

2. **Flow Configuration**
   Defines automation logic, execution frequency, rules, and actions.

Both are written in **YAML**.

Module settings use this precedence, from lowest to highest:

```text
global module configuration < flow step config < environment override
```

Unchanged global keys remain available when a step overrides another key. Environment values inherit the type of the configured value or lookup default for booleans, integers, and floats. Boolean values accept `true/false`, `1/0`, `yes/no`, and `on/off` (case-insensitive). Values without a type hint remain strings; malformed typed values raise a configuration error.

---

## Configuration Directory

The configuration directory is defined via:

```bash
CFG_DIRECTORY=/path/to/config
```

Inside this directory:

```
config/
├── config.yaml        # Global configuration
├── from_tmdb.yaml     # Example flow
├── from_lib.yaml      # Example flow
└── custom_flow.yaml   # User-defined flow
```

### Global Configuration (config.yaml)

Create `config.yaml`

#### Required Settings
```yaml
tmdb:
  token:
  lang: en-US

jackett:
  url:
  token:
  include:
  categories: "2000"

jellyfin:
  url:
  token:
  ignore:
    users: []

transmission:
  url:
  user:
  password:

library:
  directory: movies
  limit: 50
  age: 30
  rules:
    - expression: missing
      modification: grayscale
      property: link
    - expression: exists
      modification: border
      property: link
    - expression: contains
      modification: triangle
      property: torrent
      value: HDR
```

### Flow File Location

Place flow files in your configuration directory:
```
/config/
├── config.yaml                    # Global configuration
├── tmdb_to_jellyfin.yaml          # Flow: Discover movies
├── jellyfin_to_transmission.yaml  # Flow: Download favorites
└── custom_flow.yaml               # Your custom flow
```
> **Note**: When running via Docker, if the directory is empty, example flows are copied automatically.

## Global Configuration (config.yaml)
Detailed in README.md

## Module Configuration Sections

### TMDb Module (`tmdb`)

```yaml
tmdb:
  token: API_KEY
  lang: en-US
```
* token – required
* lang – optional (default: en-US)

### Jackett Module (`jackett`)

```yaml
jackett:
  url: http://jackett:9117
  token: API_KEY
  include:
    - keyword
  categories: "2000"
```
* include filters results by keyword
* categories controls torrent categories

### Jellyfin Module (`jellyfin`)

```yaml
jellyfin:
  url: http://jellyfin:8096
  token: API_KEY
  ignore:
    users:
      - username
```
* Ignored users are excluded from favorite detection and sync

### Transmission Module (`transmission`)

```yaml
transmission:
  url: http://transmission:9091
  user:
  password:
```
* Authentication is optional

### Library Configuration

The library section controls export (dummy) library behavior.

```yaml
library:
  directory: movies
  limit: 50
  age: 30
```
* directory – subdirectory name inside EXPORT_DIRECTORY
* limit – maximum number of items kept
* age – maximum age in days before removal

Age and count cleanup runs synchronously when the Library is read with its normal
`get` action, before entries are returned. It uses no separate cleanup worker and
cannot overlap filesystem operations on the same Library handler.

#### Poster Rules

Poster rules define visual modifications applied during export.

**Rule Structure**:
```yaml
- expression: missing
  modification: grayscale
  property: link
```

**Fields**:
| Field | Description  |
|------------------|---------------------------------------------------|
| `expression`     | Match condition (missing, exists, contains, etc.) |
| `modification`   | Visual effect (grayscale, border, triangle)       |
| `property`       | Property to evaluate (link, torrent, etc.)        |
| `value`          | Optional comparison value                         |
| `case_sensitive` | Optional boolean                                  |

Example:
```yaml
- expression: contains
  modification: triangle
  property: torrent
  value: HDR
```
