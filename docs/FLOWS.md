# Flow Configuration and Execution Logic

This document describes how CineFlow processes workflows (“flows”), how they are configured, and how execution is handled internally.

## 1. Overview

A **flow** is a YAML-defined workflow executed periodically by the background worker.
Each flow:
* Has a name and schedule configuration
* Defines an ordered list of modules
* Passes data between modules
* Can be enabled/disabled independently
Flows are executed by the FlowManager, which extends WorkerBase and runs in its own thread. Each flow runs independently and respects its own delay configuration.

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
  * Handles delay logic per flow

Execution pattern:
```
Worker thread
    → Iterate enabled flows
        → Execute modules sequentially
        → Sleep according to flow delay
        → Repeat
```
Each flow has its own delay configuration, allowing different polling intervals for different automation tasks.

## 4. Flow YAML Structure

A flow is defined in YAML format.

### 4.1 Basic Structure

```yaml
name: trending-to-transmission
enabled: true
delay: 3600   # seconds

modules:
  - name: tmdb_trending
    config:
      media_type: movie
      time_window: week

  - name: jackett_search
    config:
      min_seeders: 5

  - name: jellyfin_export
    config:
      library: Trending
```

## 5. Flow Properties

| Property   | Type    | Description                            |
|------------|---------|----------------------------------------|
| `name`	 | string  | Unique flow identifier                 |
| `enabled`	 | boolean | Whether flow runs                      |
| `delay`	 | integer | Delay in seconds between executions    |
| `modules`	 | list	   | Ordered list of module definitions     |

## 6. Module Definition

Each module entry contains:

```yaml
- name: module_name
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
delay: 7200

modules:
  - name: tmdb_trending
  - name: extend_with_jackett
  - name: jellyfin_sync
  - name: transmission_add
```

### 8.2 Favorites Sync Flow

Purpose:
* Read Jellyfin favorites
* Find matching torrents
* Send to Transmission

```yaml
name: favorites-download
enabled: true
delay: 1800

modules:
  - name: jellyfin_favorites
  - name: jackett_search
  - name: transmission_add
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
* Can be re-enabled without restarting (if configuration reload is supported)

## 12. Execution Timing Strategy

Each flow manages its own interval:
```
execute()
sleep(delay)
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
* Avoid very small delays (< 300s)
* Ensure modules are stateless where possible
* Validate configuration before deployment

## 15. Flow Lifecycle Summary

* FlowManager loads YAML
* Enabled flows are registered
* Worker thread starts
* Flow executes modules sequentially
* Delay is applied
* Loop continues