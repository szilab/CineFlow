# Flow Configuration and Execution Logic

CineFlow behavior is defined through workflows (“flows”). A flow is an ordered set of module/action steps executed periodically by the background runtime.

Flows are YAML files. The web GUI's visual editor ([GUI.md](GUI.md)) reads and writes the same files, so hand-written and GUI-made flows are fully compatible.

Most flows follow one shape: collect items from one or more sources, add data from other services, merge the sources, filter, then act on the result (download, export, delete). The GUI's flow editor builds exactly this shape (see [GUI.md](GUI.md#flow-editor)); anything else is edited by hand.

## 1. Overview

Each flow:

- has a name;
- can be enabled or disabled;
- has its own execution delay;
- has an optional priority;
- defines an ordered list of module/action steps;
- passes data between steps.

Flows are discovered by the `FlowManager`.

Execution modes:

```text
parallel   -> one worker per enabled flow
sequential -> one manager executes due flows one at a time
```

Both modes preserve each flow's own delay.

## 2. Flow Files

All `.yaml` and `.yml` files in `<CINEFLOW_HOME>/config` (see
[Application folder](CONFIGURATION.md#application-folder)), except `config.yaml`, are treated as workflows.

Example:

```text
config/
├── config.yaml
├── discovery.yaml
├── favorites-download.yaml
└── custom-flow.yaml
```

CineFlow starts without flows; create them in the GUI or as YAML files here.

## 3. Basic Flow Structure

```yaml
name: trending-to-transmission
enabled: true
delay: 60
priority: 10

steps:
  - name: Collect trending movies
    module: tmdb
    action: get

  - name: Find torrents
    module: jackett
    action: enrich
    input: previous
    config:
      must_match: true
```

### Flow properties

| Property | Type | Description |
|---|---|---|
| `name` | string | human-readable flow name |
| `description` | string | optional free text (ignored by the runtime) |
| `version` | integer | optional revision counter maintained by the GUI |
| `enabled` | boolean | whether the flow is runnable |
| `delay` | integer | delay in minutes between executions |
| `priority` | integer | execution ordering in sequential mode |
| `kind` | `movie`, `tv` or `both` | media kind of the flow (default `movie`); the flow passes it to every module it calls. `both` runs the steps twice, first for movies, then for TV series |
| `library_directory` | path | library folder inside the export directory for the library steps (default: the media kind) |
| `search_preference` | list | release name words by priority (the first word decides, the next one only on a tie), used by Jackett and the library |
| `steps` | list | ordered step definitions |

## 4. Steps

A normal step contains:

```yaml
- name: Descriptive step name
  module: module_name
  instance: instance_id   # optional named module instance
  action: action_name
  input: previous
  config:
    key: value
```

The module determines which actions are available and what configuration they accept.
`instance` selects a named module instance from `config.yaml`; without it the
module default is used (see [CONFIGURATION.md](CONFIGURATION.md#module-instances)).
Step names must be unique because later steps refer to them.

Current examples include actions such as:

```text
get
search
enrich
unique
common
exclude
put
remove
rename
wait
```

The exact set depends on the selected module.

## 5. Data Passing

A step may use output produced earlier in the same flow.

### No input

```yaml
input: none
```

or omit `input` entirely.

### Previous step output

```yaml
input: previous
```

### Named step output

```yaml
input: "{{Collect trending movies}}"
```

### Merge multiple previous outputs

```yaml
input:
  - "First source"
  - "Second source"
```

### Structured input

```yaml
input:
  data: previous
  query:
    parentLibrary: "Trending Filmek"
```

In a structured input `data` may also be a named reference or a list of step
names to merge:

```yaml
input:
  data: "{{Collect trending movies}}"
  query:
    parentLibrary: "Trending Filmek"
```

The runner resolves these references before calling the selected module action.

## 6. Execution and Failure Semantics

CineFlow distinguishes a failed retrieval from a successful empty result.

```text
get() -> None   = retrieval/API failure
get() -> []     = successful query with no matching items
```

A `get` step returning `None` stops the current flow to prevent later steps from treating failed upstream state as an empty successful state.

Module/action exceptions also stop the current flow. Other flows remain isolated and continue running.

This fail-closed behavior is particularly important for workflows containing destructive filtering or cleanup steps.

## 7. Scheduling

### Parallel mode

Each enabled flow has its own worker thread and delay.

### Sequential mode

The manager tracks when each flow is next due and executes due flows in priority order.

Conceptually:

```text
manager refresh
  -> find due flows
  -> sort by priority
  -> execute
  -> next due = completion + delay
```

Delays are expressed in **minutes**.

## 8. Hot Reload

Workflow file content is monitored by the flow manager.

When a workflow changes, CineFlow stops the old flow instance before loading the modified definition. If the running flow cannot terminate safely within the stop timeout, reload is deferred rather than starting overlapping old/new instances.

Global `config.yaml` changes have different semantics: existing module instances may retain previously merged global configuration. Restart CineFlow after changing global configuration for predictable behavior.

## 9. Typical Workflows

### Jellyfin Favorites → Jackett → Transmission

```yaml
name: favorites-download
enabled: true
delay: 15
steps:
  - name: Collect Jellyfin favorites
    module: jellyfin
    action: get
    input:
      query:
        parentLibrary: "Trending Filmek"
        isFavorite: true
        allUsers: true

  # Jellyfin may return a localized display title. Resolve the configured
  # TMDb-language title by provider ID before querying Jackett.
  - name: Normalize titles with TMDb
    module: tmdb
    action: enrich
    input: previous
    config:
      must_match: true

  - name: Find release
    module: jackett
    action: enrich
    input: previous
    config:
      must_match: true

  - name: Download
    module: transmission
    action: put
    input: previous
```

### TV series example

```yaml
name: series-favorites-download
enabled: true
delay: 30
kind: tv
steps:
  - name: Collect Jellyfin series favorites
    module: jellyfin
    action: get
    input:
      query:
        isFavorite: true
        allUsers: true
  - name: Normalize titles with TMDb
    module: tmdb
    action: enrich
    input: previous
    config:
      must_match: true
  - name: Find season pack
    module: jackett
    action: enrich
    input: previous
    config:
      must_match: true
  - name: Download
    module: transmission
    action: put
    input: previous
```

### Jellyfin folder names for downloads

Two steps after `put` give every added torrent a download folder Jellyfin
identifies: `Title (year) [tmdbid-N]`, from the TMDb title, year and ID of the
item. `tools.wait` lets a magnet link fetch its metadata (the file list) first;
`rename` of the same download client then renames the root folder of the
torrent on the disk.

```yaml
  - name: Download
    module: transmission
    action: put
    input: previous
  - name: Wait for metadata
    module: tools
    action: wait
    input:
      data: previous
      seconds: 20          # 1-300, default 10; no wait when nothing was added
  - name: Jellyfin folders
    module: transmission
    action: rename
    input: previous
    config:
      suffix: " - {resolution}"   # optional: 'Film (2020) [tmdbid-1] - 1080p'
```

`suffix` is added after the generated name; `{field}` inserts a field of the
item (e.g. `resolution`, `season`), an unknown field inserts nothing.
Characters not allowed in folder names are removed.

- A torrent without a root folder (a single file) moves into a new folder of
  that name; the file keeps its name, so episode markers such as `S01E02` stay.
- When another download already uses the folder name (e.g. an other episode
  release of the series), the torrent moves into that folder instead of
  replacing it.
- Transmission renames the torrent together with its root folder; qBittorrent
  keeps the torrent name and only renames the folder. The `get` action of both
  clients reads such a name back (title, year and `tmdbid`), so a renamed
  torrent is still found, e.g. by `unique`; the season of a renamed series
  torrent is unknown. qBittorrent finds the
  torrent by the info hash of its magnet link, or of the `.torrent` file the
  link serves.
- Nothing changes when the torrent, its metadata or the torrent list is not
  available: `transmission_folder` / `qbittorrent_folder` records `pending`
  (no metadata yet, wait longer) or `error`, and the download goes on.
- The title follows the TMDb `language` setting: use `en-US` for English
  folder names.

### Removing and moving torrents

`transmission` and `qbittorrent` have two more actions that work on the
torrents of the incoming items. The `get` action of both clients returns
`torrent_hash` and `added` (add time, Unix timestamp) and takes a `min_age`
query: only torrents added at least that many hours ago are collected.

```yaml
  - name: Torrents older than two days
    module: transmission
    action: get
    input:
      query:
        min_age: 48            # hours since the torrent was added
  - name: Finished only
    module: tools
    action: filter_items
    input:
      data: previous
      query:
        conditions:
          - {field: percent_done, match: at_least, value: 1}
  - name: Archive
    module: transmission
    action: move
    input: previous
    config:
      location: /downloads/archive   # folder on the client's machine
  - name: Clean up
    module: transmission
    action: delete
    input: previous
    config:
      delete_files: false            # default: the data stays on the disk
```

- `min_age` also works in `unique` and `common`. A torrent whose add time is
  unknown is never collected by a `min_age` query.
- `delete` is destructive and is skipped in test runs; `delete_files: true`
  also deletes the downloaded data.
- Outcomes are recorded in `<module>_deleted` (`deleted`, `missing`, `error`)
  and `<module>_moved` (`moved`, `done`, `missing`, `error`). An item whose
  torrent cannot be identified or found is never touched.

### TMDb discovery → exported library

```text
TMDb -> optional enrichment/filtering -> Library
```

### Future optional workflows

The module architecture is intended to allow alternative stacks without changing the flow engine, for example:

```text
TMDb -> Radarr
Trakt Watchlist -> Radarr
Plex state -> Sonarr
Simkl state -> workflow filter -> Jellyfin/Plex action
```

Radarr, Sonarr, Trakt, and Simkl are planned optional modules, not mandatory architecture components.

## 10. Validation

```text
cineflow validate
```

validates `config.yaml` and every flow without starting workers or performing
actions. It checks the flow root keys and value ranges, module and action
existence, module instances, required module settings (including environment
overrides), step settings, duplicate step names, `{{name}}` references to
earlier steps, and the input shapes each action accepts. A setting no module
or action defines, in `config.yaml`, an instance or a step `config`, gets the
warning *Unknown setting '…': it has no effect*; old or misspelled keys are not
mapped to their replacements. The runtime logs the
same findings as warnings when it loads a flow file. Details: [GUI.md](GUI.md#validation).

## 11. Visual Workflow Editor

The web GUI contains a card-based editor that manipulates the same YAML
structure: add actions from a catalog generated from module definitions,
drag cards to reorder, configure each step in a side panel, see validation
errors on cards and fields, save, export/import YAML and run a flow manually.
Flows with errors can only be saved disabled. See [GUI.md](GUI.md).

```text
[TMDb: Get]
     |
     v
[Jackett: Enrich]
     |
     v
[Transmission: Add torrents]
```

### TV series: one season at a time

A TV download flow fetches at most one season of a series per run. The
*Next season to download* step of Jellyfin (`next_season`) decides which:

- a series that is not in the queried libraries yet gets season 1;
- aired episodes missing from the latest season in the libraries (an airing
  season) come next, watched or not: that season with the missing episodes
  in `wanted_episodes`;
- otherwise the season after the latest one in the libraries, once
  `watched_percent` (default 75) of that latest season's episodes were
  watched by anyone; until then the series is dropped;
- a season that has not aired yet is never chosen. The aired seasons come
  from TMDb (`seasons_aired`, added by a TMDb `enrich` of a TV flow); without
  them the next season is assumed to exist.

The step sets `season` on each item it keeps. A Jackett `enrich` after it
then looks for that season:

1. missing episodes (`wanted_episodes`): only releases of those episodes;
2. a whole season: a single-season pack first; without one, releases of its
   aired episodes (one per episode, or an episode range such as
   `S02E01-E03`); without those, the multi-season pack with the fewest extra
   seasons (`S01-S03`, `Season 1-3`, `S01.S02`), or a whole-series pack
   (`Complete`) as the last resort.

Several episode releases turn the item into one item per release, so the
download step adds each torrent. The Jackett *Season packs only* setting
applies to collecting releases and to series without a chosen season.

```yaml
kind: tv
steps:
- name: Favorites
  module: jellyfin
  action: get
  input:
    query: {parentLibrary: Trending Sorozatok, isFavorite: true, allUsers: true}
- name: Titles and seasons
  module: tmdb
  action: enrich
  input: previous
- name: Next season to download
  module: jellyfin
  action: next_season
  input:
    data: previous
    query: {parentLibrary: Trending Sorozatok, isInverse: true}   # skip the CineFlow library
  config:
    watched_percent: 75
- name: Release of the season
  module: jackett
  action: enrich
  input: previous
  config:
    must_match: true
- name: Download
  module: transmission
  action: put
  input: previous
```

In the GUI the steps that add data can also be placed among the filters;
they then run on the items left, in their order (here: Jackett after the
season choice).

### Movies and TV series in one flow

With `kind: both` one run of the flow executes every step twice: first as a
movie flow, then as a TV flow. Each pass has its own step outputs, and the
default library folder follows the kind of the pass (`movie`, then `tv`). The
passes are independent: a failed movie pass does not stop the TV pass, but
the run is reported as failed with the error of each failed pass. Test runs
report the steps of both passes.

## 12. Workflow Runtime View

The flow menu of the GUI marks each flow as enabled, disabled, invalid or
running, and the flow page has a manual *Run* trigger. Runtime details
and log messages are in the CineFlow log.

## 13. Design Constraints

The flow language should remain intentionally small.

Prefer:

- reusable modules;
- clear ordered data flow;
- simple configuration;
- deterministic validation.

Avoid turning CineFlow YAML into a general-purpose programming language. Add branching, complex conditions, persistence, or advanced orchestration only when concrete media workflows require them.

## 14. Best Practices

- Keep workflows small and purpose-specific.
- Prefer stable provider IDs (TMDb/IMDb/etc.) over title-only matching when available.
- Use `must_match` when later actions require enrichment to succeed.
- Avoid unnecessarily small polling delays.
- Treat API failure differently from empty results.
- Keep destructive cleanup dependent on complete upstream state.
- Use higher-level modules such as future Radarr/Sonarr where they provide mature behavior rather than duplicating that behavior inside CineFlow.

For configuration details see [CONFIGURATION.md](CONFIGURATION.md). For future sequencing and integration plans see [ROADMAP.md](ROADMAP.md).
