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

## Application folder

Everything CineFlow keeps lives in one application folder, `CINEFLOW_HOME`:

| Platform | `CINEFLOW_HOME` |
|---|---|
| Linux, macOS | `$XDG_CONFIG_HOME/cineflow`, default `~/.config/cineflow` |
| Windows | `%APPDATA%\cineflow` |
| Docker | `/data/cineflow` (the image sets `XDG_CONFIG_HOME=/data`) |

```text
<CINEFLOW_HOME>/
├── config/             config.yaml and the flow files (*.yaml)
│   ├── .backups/       previous versions of files the GUI changed
│   └── .cineflow/      GUI session secret
├── library/            default export directory, see below
├── debug/              files of the tools data_export / data_import actions
└── cachedb.sqlite3     cache of service responses
```

The folders cannot be moved one by one. The only exception is the export
directory (the library root the media server scans): the library module's
`export_directory` setting or the `EXPORT_DIRECTORY` environment variable
moves it, and the environment variable wins. A relative `export_directory`
is relative to `CINEFLOW_HOME`. When `EXPORT_DIRECTORY` is set, the GUI shows
the setting read-only.

CineFlow starts without flows; create them in the GUI or as YAML files in
`config/`.

Exported items get a small `.mkv` file that holds no pictures, only stream
headers built from the release name: resolution, video codec, bit depth,
HDR10, HLG or Dolby Vision, and the audio codec and channels. Media servers
show these properties; the file cannot be played.

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
  export_directory: /srv/media/cineflow   # optional
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
```

TMDb, Jackett, Jellyfin, Plex, Transmission and qBittorrent also accept
`limit`, a safety cap on the items one *Get* step collects (default 200,
about 10 pages of TMDb trending titles). It is not shown in the GUI and
normally needs no value; set it in the module section (or a step `config`)
to change it. It applies to collecting only: the *Not in*, *Also in* and
*Next season* steps always compare with every item on the server. (The
Library module's `limit` is the size of the library, see below.)

Common settings:

- `token` — required API token;
- `language` — metadata language, default `en-US`.

Matching is always strict: a search result matches when its TMDb or IMDb ID
is the same, or when its title (or alternative title) and year are the same.
Series without a known year match by title alone.

`get` collects the weekly trending list (the trending endpoint has no region
filter).
IMDb IDs are looked up only for collected or matched items, and those lookups
are cached for 30 days. `search` uses the TMDb ID when present, otherwise the
IMDb ID, and falls back to a title search.

### Jackett

```yaml
jackett:
  url: http://jackett:9117
  token: API_KEY
  min_seeders: 10        # skip releases with fewer seeders (0: no limit)
  resolution: 1080p      # keep only this resolution (empty: any)
  size_limit_gb: 26      # skip larger releases (0: no limit)
```

`min_seeders`, `resolution` and `size_limit_gb` filter every Jackett result,
both when collecting releases (`get`) and when looking them up for items
(`enrich`). A step may override them in its `config`; the GUI shows them on
every Jackett source step with the module value as the default.

Indexers return one page per search (about 50–100 releases each) and Jackett
does not page further, so a blank search only reaches the releases of the
last day or two. A *Get from Jackett* step therefore searches twice, once
more with the current year added, and merges the results (most seeded
first, duplicates removed) before `limit` applies. When its query has
`include` words, the step searches for those words instead of a blank
search, so older releases with these words are found too.

Jackett can be used directly with download clients or omitted from workflows that
use future higher-level integrations such as Radarr/Sonarr. The flow's
`search_preference` (see [Flow settings](#flow-settings)) sorts the Jackett
results by priority.
Results that only carry a magnet URI use it as their `link`.

A `get` step query supports `include` (all words must be present) and
`exclude`, either a word list or a string of words that must not be present,
or `true` to invert `include`:

```yaml
input:
  query:
    include: HUN
    exclude: [CAM, TS]
config:
  min_seeders: 40
```

To keep only some releases (for example Hungarian ones), add a *Filter by
field* step (see [Tools](#tools)) after the source.

### Tools

The tools module needs no settings. Besides *Remove duplicates* and the
debug export/import it has a *Filter by field* step (`filter_items`) that
works on the items alone. Each of its `conditions` compares a `field` of an
item with a `value`:

| `match` | the condition holds when the field |
|---|---|
| `equals` (default) | is the value; text without case, numbers by value (`2024` = `"2024"`) |
| `contains` | contains the value, without case |
| `has_word` | has the value as a whole word, without case: any character other than a letter or digit (`.`, `-`, `_`, space, brackets) separates words, so `HUN` is in `Film.HUN-GRP` but not in `Hungry` |
| `at_least` | is a number not smaller than the value |
| `at_most` | is a number not larger than the value |

`combine: all` (default) needs every condition (and), `combine: any` one of
them (or). `matching: keep` (default) passes the matching items on,
`matching: drop` removes them and passes the rest on. An item without the
field, or without a number for `at_least` and `at_most`, does not meet the
condition. A filter whose conditions are missing or incomplete keeps every
item. The fields offered are `title`, `alttitle`, `year`, `kind`, `tmdbid`,
`imdbid`, `torrent`, `resolution`, `seeders`, `size` (GB), `season`,
`episode` and `directory`.

```yaml
# Hungarian releases with at least 40 seeders
- name: Hungarian and seeded
  module: tools
  action: filter_items
  input:
    data: previous
    query:
      conditions:
        - {field: torrent, match: contains, value: HUN}
        - {field: seeders, match: at_least, value: 40}
# HDR or Dolby Vision releases
- name: HDR or Dolby
  module: tools
  action: filter_items
  input:
    data: previous
    query:
      combine: any
      conditions:
        - {field: torrent, match: contains, value: HDR}
        - {field: torrent, match: contains, value: dolby}
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

A Jellyfin or Plex step query selects libraries with `parentLibrary`: one
name or a list. With `isInverse: true` it selects every library except those,
for example to compare with everything already on the server except the
libraries that show the CineFlow export:

```yaml
- name: Not in Jellyfin
  module: jellyfin
  action: unique
  input:
    data: previous
    query:
      parentLibrary: [Trending Filmek, Trending Sorozatok]
      isInverse: true
```

The GUI shows this as *Libraries: All / Only / All except* with the chosen
libraries, and writes these two keys.

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

The internal library module creates and manages exported/dummy media entries in
the export directory: `export_directory`, overridden by `EXPORT_DIRECTORY`,
default `<CINEFLOW_HOME>/library`.

```yaml
library:
  export_directory: /srv/media/cineflow   # optional
  limit: 50
  age: 30
```

- `limit` — maximum retained exported items (default 500, minimum 10);
- `age` — maximum age in days before cleanup (default 120, minimum 30).

The library folder and the release preference are flow settings (see
[Flow settings](#flow-settings)).

A background worker applies `limit` and `age` once an hour for every library
directory used by a flow. The first cleanup runs one hour after start, so
reading the library with `get` never deletes items.

The flow's `search_preference` ranks releases (see
[Flow settings](#flow-settings)). When CineFlow finds a release for an item already exported to the library, it
rewrites the item only when the new release has a strictly higher score;
tracker URL or seeder-count changes alone do not refresh it.

Every exported item keeps its data in a `data.json` file of its folder. The
`enrich` action of the library adds that data (e.g. the release, the resolution
and the TMDb/IMDb IDs) to the items of an other source, such as the Jellyfin
favorites of the exported library: in the flow editor it is offered under
*Add data from* of a source step. Items match by TMDb or IMDb ID, else by title
and year; the item's own values win, and `must_match: true` drops the items
not in the library.

Each exported video file gets the publish time as its modification time.
Jellyfin derives "Date added" from these timestamps, so sorting the library by
date added shows new items and upgraded releases first, while unchanged items
keep their place.

Library identity is based on TMDb ID, with IMDb ID as a fallback. Once an item
is exported, a title punctuation or release-year change reuses its existing
directory rather than creating a duplicate.

## Poster Rules

An *Export to library* step (`library.put`) can change the posters of the
items it exports. Its `poster_rules` setting is a list of rules; every rule
whose condition holds applies, in order. In the GUI each rule is a card on
the step.

```yaml
- name: Export
  module: library
  action: put
  input: previous
  config:
    poster_rules:
      - property: torrent
        expression: token
        value: HUN
        case_sensitive: false
        modification: border
        color: green
      - property: imdbid
        expression: missing
        modification: grayscale
```

| Field | Description |
|---|---|
| `property` | item field to check, e.g. `torrent`, `resolution`, `seeders` |
| `expression` | `token` (has word), `contains`, `eq`, `ne`, `gt`, `lt`, `exists` (default) or `missing` |
| `value` | comparison value; not needed for `exists` and `missing` |
| `case_sensitive` | text comparison with case (default `true`); YAML only |
| `modification` | `border`, `triangle` (a corner) or `grayscale` (black and white) |
| `color` | `yellow`, `blue`, `red` (default), `green`, `white`, `black` or `orange` |
| `position` | corner of the `triangle`: `top-left`, `top-right` (default), `bottom-left`, `bottom-right` |

`token` (has word) matches a complete release-name word: any character other
than a letter A-Z or a digit separates words. It matches `HUN` in
`Some.Movie.2005.1080.HUN.DVDRip` or `Movie-HUN_GRP`, but not inside
`Hungry`. Numbers such as `seeders`
or `size` compare as numbers with `eq`, `ne`, `gt` and `lt`.

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

The media kind is a flow setting: `kind: movie` (default) or `kind: tv` at the
top of the flow file. The flow passes it to every module it calls, so all steps
of a flow handle the same kind; use separate flows for movies and series. A
`kind` in a module section of `config.yaml` or on a step is not a setting and
has no effect. With `kind: tv`:

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
matching then ignores the unknown year. A `kind: tv` flow writes to the `tv`
library folder by default, so series stay apart from movies. Mature episode tracking is better left to an optional Sonarr module
(see the roadmap).

## Flow settings

Two settings belong to the flow rather than to a module, because the steps of
one flow must agree on them:

```yaml
name: Import media to library
kind: movie
library_directory: film          # optional; default: the media kind (movie or tv)
search_preference: ["HUN", "HDR", "1080p", "2160p"]
steps: ...
```

- `library_directory` — the library folder inside the export directory
  (with the default `<CINEFLOW_HOME>/library`, `film` means
  `<CINEFLOW_HOME>/library/film`). Without a value the
  folder is named after the flow's media kind: `movie` or `tv`. Every library
  step of the flow uses it. A torrent client's own `directory` (download
  folder) is unrelated.
- `search_preference` — release name words by priority. The first word
  decides: a release containing it beats every release without it, whatever
  else they contain; the second word only decides between releases equal on
  the first, and so on. With `[HUN, HDR, 1080p, 2160p]` a
  `Dune.2021.720p.HUN` release beats `Dune.2021.1080p.HDR.ENG`, and among HUN
  releases an HDR one wins. Jackett sorts its results by it, and the library
  replaces an exported item only with a better-ranked release. Jackett and the
  library steps of the flow use it.

These come only from the flow: the same keys in the `library` or `jackett`
section of `config.yaml`, in an instance or in a step `config` have no
effect, and `cineflow validate` warns about them like about any unknown
setting. In the GUI both are in the flow header.

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
