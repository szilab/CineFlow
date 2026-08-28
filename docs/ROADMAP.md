# CineFlow Roadmap

CineFlow is a configuration-driven media automation engine. Its direction is intentionally different from request-management applications such as Seerr: CineFlow focuses on modular workflows that can use Jellyfin, Plex, discovery services, download tools, and optional automation services as interchangeable workflow steps.

## Product Direction

The main product goal is to make CineFlow easy to configure and operate without losing its workflow-driven architecture.

Key principles:

- Keep YAML as the portable source-of-truth format for configuration and workflows.
- Add a first-party GUI that reads, validates, and writes the same configuration model.
- Keep integrations optional and composable as workflow modules.
- Avoid making Radarr, Sonarr, Trakt, Simkl, or any other external service mandatory.
- Prefer external online state providers for watched/history state when they fit the use case; do not introduce a large persistent internal database unless a concrete feature requires it.
- Preserve the current headless/Docker-friendly runtime.

## Phase 1 — Configuration Model and Validation

Goal: make configuration safe, discoverable, and machine-validatable before building the GUI on top of it.

### Planned work

- Define a formal schema/metadata contract for module configuration.
- Each module should expose:
  - configuration keys;
  - value types;
  - required/optional status;
  - defaults;
  - descriptions/help text;
  - secret/sensitive fields;
  - supported actions;
  - action input/output expectations where practical.
- Add application-level configuration validation.
- Add workflow validation beyond basic YAML shape checking.
- Validate module names and actions before a workflow becomes runnable.
- Validate step references and duplicate/invalid step names.
- Validate delay, priority, enabled, execution mode, and supported input shapes.
- Produce actionable validation messages that can be consumed both by CLI and GUI.
- Clearly define configuration reload semantics.

### CLI support

Add a non-destructive validation command, for example:

```text
cineflow validate
```

The command should validate global configuration and all workflow files without starting workers.

## Phase 2 — First-Party Configuration GUI

Goal: remove YAML editing as a requirement for normal users.

The GUI is a frontend for the existing configuration model, not a separate configuration system.

### Global and module configuration

- List available modules and integrations.
- Generate forms from module configuration metadata/schema.
- Show required fields, defaults, descriptions, and validation errors.
- Mark secret values appropriately.
- Test integration connectivity where the module supports a safe health check.
- Edit global settings such as execution mode and runtime options.
- Save valid configuration back to YAML.
- Allow advanced users to inspect/edit the generated YAML when useful.

### Workflow editor

Provide a visual drag-and-drop workflow builder.

Core UX:

1. Create or select a workflow.
2. Drag a module/action node into the workflow.
3. Configure the step through generated forms.
4. Connect step inputs to previous outputs.
5. Reorder steps visually.
6. Validate the complete workflow continuously.
7. Save/export the workflow as standard CineFlow YAML.

The visual editor must use the same validation and runtime model as manually authored YAML.

### Workflow observability

The GUI should gradually expose:

- enabled/disabled state;
- last run time;
- next scheduled run;
- last result/failure;
- current running state;
- manual run trigger;
- recent step-level execution messages.

## Phase 3 — Optional Automation Integrations

Goal: expand workflow capability without changing CineFlow into a fixed media stack.

### Radarr module

Optional workflow integration for movie acquisition and management.

Possible actions:

- search/add movie;
- query monitored/available state;
- select root folder and quality profile through module configuration;
- trigger search where supported;
- expose status back to later workflow steps.

Radarr must remain optional. Existing direct Jackett → Transmission workflows remain supported.

### Sonarr module

Optional workflow integration for TV/series acquisition and management.

Possible actions mirror the Radarr integration where appropriate.

Sonarr support is the preferred foundation for mature TV-series automation rather than reimplementing Sonarr behavior inside CineFlow.

## Phase 4 — Online Watch-State Integrations

Goal: support portable watched/history state without making CineFlow itself the primary long-term user-state database.

### Trakt module

Potential workflow capabilities:

- watched history;
- watchlist;
- ratings/favorites where useful;
- lists;
- history synchronization;
- watched-state filtering in workflows.

### Simkl module

Potential workflow capabilities similar to Trakt where supported:

- watched/history state;
- lists/watchlists;
- media-state synchronization;
- workflow filtering and enrichment.

These integrations should be optional providers. A workflow may use Jellyfin/Plex state, Trakt, Simkl, or none of them depending on the user's setup.

## Phase 5 — Runtime and Workflow Improvements

Goal: improve reliability and workflow expressiveness without turning the flow engine into a general-purpose programming language.

Candidates:

- explicit step contracts and typed validation;
- reusable workflow templates;
- optional conditional/branching steps if a concrete use case requires them;
- safer dry-run support for workflows that can perform destructive actions;
- improved scheduling controls while retaining simple delay-based execution;
- path-level synchronization for workflows operating on the same exported library;
- clearer runtime status and diagnostics.

Avoid adding complexity without a demonstrated workflow need.

## Phase 6 — Optional Persistent Application State

CineFlow currently uses SQLite primarily as a cache. A persistent application-state database may become useful later for features that cannot be represented reliably by external systems or configuration alone.

Possible future uses:

- workflow execution history;
- UI audit/history data;
- durable job state;
- locally managed media state not available from external providers;
- synchronization metadata between multiple state providers.

This is intentionally deferred. External providers such as Jellyfin, Plex, Trakt, and Simkl should remain usable state sources through normal modules.

## Integration Philosophy

CineFlow should support multiple valid deployment styles rather than enforce one stack.

Examples:

```text
TMDb → Jackett → Transmission
```

```text
TMDb → Radarr
```

```text
Jellyfin Favorites → Jackett → Transmission
```

```text
Plex Watchlist → Radarr
```

```text
Trakt Watchlist → Radarr
```

```text
Simkl state → workflow filters → Jellyfin/Plex/library actions
```

The flow engine and shared module contract are the product core; individual integrations remain replaceable workflow components.

## Not a Current Goal

The following are not primary roadmap goals unless future requirements justify them:

- reproducing Seerr's full request-management/user-management model;
- making Radarr/Sonarr mandatory dependencies;
- replacing YAML with a GUI-only proprietary format;
- building a large internal watched-state database when online/media-server state providers already solve the need;
- reimplementing mature Radarr/Sonarr release-management functionality inside CineFlow.
