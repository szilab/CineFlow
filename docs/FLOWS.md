# Flow Configuration and Execution Logic

CineFlow behavior is defined through workflows (“flows”). A flow is an ordered set of module/action steps executed periodically by the background runtime.

Flows are YAML files. The web GUI's visual editor ([GUI.md](GUI.md)) reads and writes the same files, so hand-written and GUI-made flows are fully compatible.

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

All `.yaml` and `.yml` files in `CFG_DIRECTORY`, except `config.yaml`, are treated as workflows.

Example:

```text
/config/
├── config.yaml
├── discovery.yaml
├── favorites-download.yaml
└── custom-flow.yaml
```

Docker images include example workflows that are copied into an empty configuration directory on first start.

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
steps:
  - name: Collect Jellyfin series favorites
    module: jellyfin
    action: get
    config:
      kind: tv
    input:
      query:
        isFavorite: true
        allUsers: true
  - name: Normalize titles with TMDb
    module: tmdb
    action: enrich
    input: previous
    config:
      kind: tv
      must_match: true
  - name: Find season pack
    module: jackett
    action: enrich
    input: previous
    config:
      kind: tv
      must_match: true
  - name: Download
    module: transmission
    action: put
    input: previous
```

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
earlier steps, and the input shapes each action accepts. The runtime logs the
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

## 12. Workflow Runtime View

The GUI shows, per flow: enabled state, running/idle, last start and end,
last result, the failing step and error, the next due time in sequential
mode, recent log messages of the flow, and a manual *Run now* trigger.

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
