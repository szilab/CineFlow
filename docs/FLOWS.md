# Flow Configuration and Execution Logic

This document describes how CineFlow processes workflows (“flows”), how they are configured, and how execution is handled internally.

## 1. Overview

A **flow** is a YAML-defined workflow executed periodically by the background worker.
Each flow:
* Has a name and schedule configuration
* Defines an ordered list of steps
* Passes data between steps
* Can be enabled/disabled independently
Flows are discovered by the FlowManager. In `parallel` mode, each enabled and valid flow has its own worker. In `sequential` mode, the manager executes due flows one at a time. Both modes respect each flow's individual delay.

## 2. Flow Configuration

Automation logic is defined by flow YAML files.
* All .yaml files (except config.yaml) are treated as flows
* Flows define:
  * execution interval
  * conditions
  * actions
  * rules

Default example flows are shipped with the Docker image and copied automatically on first run.

## 3.Flow Execution Model
### 3.1 Worker Architecture

* WorkerBase
  * Implements threaded execution
  * Provides periodic scheduling
* FlowManager
  * Loads configured flows
  * Executes enabled flows
  * Tracks each flow's next due time in sequential mode

Execution pattern:

```text
parallel: one worker per enabled flow
sequential: manager refresh → select due flows → priority order → execute one at a time
```

Each flow has its own delay configuration, allowing different polling intervals for different automation tasks. Sequential mode does not create flow worker threads.

## 4. Flow YAML Structure

A flow is defined in YAML format.

### 4.1 Basic Structure

```yaml
name: trending-to-transmission
enabled: true
delay: 60   # minutes

steps:
  - name: Collect trending movies
    module: tmdb
    action: get
    config:
      media_type: movie
      time_window: week

  - name: Find torrents
    module: jackett
    action: enrich
    input: previous
    config:
      min_seeders: 5

```

## 5. Flow Properties

| Property   | Type    | Description                            |
|------------|---------|----------------------------------------|
| `name`	 | string  | Unique flow identifier                 |
| `enabled`	 | boolean | Whether flow runs                      |
| `delay`	 | integer | Delay in minutes between executions    |
| `steps`	 | list	   | Ordered list of step definitions       |

## 6. Module Definition

Each step contains:

```yaml
- name: Descriptive step name
  module: module_name
  action: get
  input: previous
  config:
    key: value
```

## 7. Data Passing Between Modules

Modules operate on a shared context object.

Conceptually:
```
Context
 ├── items
 ├── metadata
 ├── matched_results
 ├── favorites
 └── torrent_links
```

Each module may:
* Read from context
* Add new properties
* Modify existing structures

Example:
1. tmdb_trending → populates items
2. jackett_search → enriches items with torrents
3. jellyfin_export → writes items to library

## 8. Typical Flow Examples

### 8.1 Trending → Library → Transmission

Purpose:
* Fetch trending media
* Extend with torrent data
* Export to Jellyfin
* Add favorites to Transmission

```yaml
name: trending-automation
enabled: true
delay: 120  # minutes

steps:
  - name: Collect trending
    module: tmdb
    action: get
  - name: Extend with torrents
    module: jackett
    action: enrich
    input: previous
```

### 8.2 Favorites Sync Flow

Purpose:
* Read Jellyfin favorites
* Find matching torrents
* Send to Transmission

```yaml
name: favorites-download
enabled: true
delay: 30  # minutes

steps:
  - name: Collect favorites
    module: jellyfin
    action: get
  - name: Find torrents
    module: jackett
    action: enrich
    input: previous
  - name: Download
    module: transmission
    action: put
    input: previous
```

## 9. Duplicate Handling

CineFlow includes internal deduplication logic:
* Prevents duplicate TMDB entries
* Detects already existing Jellyfin items
* Avoids re-adding torrents to Transmission
* Maintains mapping between TMDB ID and library items
This ensures idempotent flow execution.

## 10. Error Handling

Module-level errors are logged
* Flow execution stops on module failure
* Next iteration retries automatically
* Flow isolation prevents one failing flow from stopping others

## 11. Enabling and Disabling Flows

Flows can be controlled via YAML:
```yaml
enabled: false
```
Disabled flows:
* Are loaded
* Are not executed
* Can be re-enabled without restarting

## 12. Execution Timing Strategy

In parallel mode each flow worker manages its own interval. In sequential mode the manager stores a monotonic next-due timestamp for every enabled, valid flow. Newly discovered or reloaded flows are eligible during that manager refresh; after execution, next due is completion time plus `delay * 60` seconds.

Conceptually:
```
execute()
sleep(delay * 60)
repeat()
```

This enables:
* Fast polling for favorites (e.g., 10 min)
* Slower polling for trending (e.g., 2–6 hours)

## 13. Design Principles

CineFlow flow system is designed to be:
* Modular
* Extensible
* Idempotent
* Configuration-driven
* Service-agnostic (TMDB, Jackett, Jellyfin, Transmission are modules, not hard dependencies)

## 14. Best Practices

* Keep flows small and focused
* Separate trending and download flows
* Use meaningful names
* Avoid very small delays (< 5 minutes)
* Ensure modules are stateless where possible
* Validate configuration before deployment

## 15. Flow Lifecycle Summary

* FlowManager loads YAML
* Enabled flows are registered
* Worker thread starts
* Flow executes steps sequentially
* Delay is applied
* Loop continues
