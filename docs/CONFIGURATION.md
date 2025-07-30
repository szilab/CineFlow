# Flow Configuration Guide

CineFlow uses a powerful flow-based automation system that allows you to create custom workflows by chaining together different modules and actions. This guide explains how to create, customize, and optimize your flows.

## Table of Contents

- [Flow Basics](#flow-basics)
- [Flow Structure](#flow-structure)
- [Available Modules](#available-modules)
- [Input/Output Chaining](#inputoutput-chaining)
- [Configuration Overrides](#configuration-overrides)
- [Troubleshooting](#troubleshooting)

## Flow Basics

### What are Flows?

Flows are YAML configuration files that define automated workflows. Each flow consists of sequential steps that execute modules with specific actions, allowing you to create complex automation pipelines.

### How Flows Work

1. **Discovery**: CineFlow automatically finds all `.yaml` files in your config directory (except `config.yaml`)
2. **Parsing**: Each flow file is parsed and validated
3. **Execution**: Flows run continuously based on their defined delay interval
4. **Chaining**: Data flows between steps, allowing complex processing pipelines

### Flow File Location

Place flow files in your configuration directory:
```
/config/
├── config.yaml                    # Global configuration
├── tmdb_to_jellyfin.yaml          # Flow: Discover movies
├── jellyfin_to_transmission.yaml  # Flow: Download favorites
└── custom_flow.yaml               # Your custom flow
```

## Flow Structure

### Basic Flow Anatomy

```yaml
name: "Flow Name"           # Display name for the flow
delay: 30                   # Execution interval in minutes
steps:                      # List of sequential steps
  - name: "step_name"       # Unique step identifier
    module: "module_name"   # Module to use (tmdb, jackett, etc.)
    action: "action_name"   # Action to execute
    config:                 # Optional: Override global config
      setting: "value"
    input: {}               # Provide input data
```

### Required Fields

- **`name`**: Flow display name
- **`steps`**: Array of step definitions
- **`steps[].module`**: Module name to execute
- **`steps[].action`**: Action name within the module

### Optional Fields

- **`delay`**: Execution interval in seconds (default: 60)
- **`steps[].name`**: Step identifier for referencing output
- **`steps[].config`**: Step-specific configuration
- **`steps[].input`**: Input data specification

## Available Modules

### TMDb Module (`tmdb`)

Interacts with The Movie Database API.

**Actions:**
- `get(query)` - Get trending movies
- `search(title, year)` - Search for movies
- `enrich(data)` - Extend the received data with module properties

**Example:**
```yaml
- name: Get trending movies
  module: "tmdb"
  action: "trending"
```

### Jackett Module (`jackett`)

Searches torrent indexers through Jackett.

**Actions:**
- `get(query)` - Get latest entries
- `search(title, year)` - Search for torrents
- `enrich(data)` - Extend the received data with module properties

**Example:**
```yaml
- name: Add torrent data
  module: "jackett"
  action: "enrich"
  input: "previous"  # Movies from previous step
```

### Jellyfin Module (`jellyfin`)

Manages Jellyfin media server integration.

**Actions:**
- `get(query)` - Collect media from Jellyfin can use Jellyfin API /Items endpoint parameters
- `search(title, year)` - Search for media
- `enrich(data)` - Extend the received data with module properties

**Example:**
```yaml
  - name: Jellyfin favorites
    module: jellyfin
    action: get
    input:
      query:
        parentLibrary: Request
        isFavorite: true
        allUsers: true
```

### Transmission Module (`transmission`)

Manages downloads through Transmission.

**Actions:**
- `get(query)` - List of torrents
- `search(title, year)` - Search for torrent
- `put(data)` - Add list of media to download list must contain 'link' property

**Example:**
```yaml
  - name: Add to Transmission
    module: transmission
    action: put
    input: previous
```

## Input/Output Chaining

### Input Types

#### `none`
No input data provided to the action this is the default if not specified.
```yaml
input: none
```

#### `previous`
Use output from the immediately previous step.
```yaml
input: "previous"
```

#### `{{step_name}}`
Use output from a specific named step.
```yaml
input: "{{get_trending}}"  # Use output from step named "get_trending"
```

#### Custom Data
Provide custom input data structure.
```yaml
input:
  query: "Inception"
```

#### Complex Input with Previous Data
Combine custom data with previous step output. Just an example module action must support.
```yaml
input:
  data: "previous"      # Previous step output goes here
  quality: "1080p"      # Additional parameters
  category: "movies"
```

### Output Storage

Step outputs are automatically stored and can be referenced by:
- **Step name**: `{{step_name}}`
- **Previous step**: `previous`
- **Latest step**: `latest` (same as previous)

## Configuration Overrides

### Global vs Step Configuration

**Global configuration** (`config.yaml`) provides default settings for all modules:
```yaml
tmdb:
  token: "global_token"
  lang: "en-US"
```

**Step configuration** overrides global settings for that specific step:
```yaml
- name: "French movies"
  module: "tmdb"
  action: "get"
  config:
    lang: "fr-FR"    # Override global language setting
```

### Override Examples

```yaml
# Override Jackett search parameters for specific step
- name: "Search 4k torrents for media"
  module: "jackett"
  action: "enrich"
  config:
    include: "2160p"        # Override global "1080p" setting
  input: "previous"
```

## Troubleshooting

### Common Issues

#### Flow Not Running
**Symptoms**: Flow doesn't execute or shows no activity
**Solutions**:
- Check file is in correct config directory
- Verify YAML syntax is valid
- Ensure file has `.yaml` or `.yml` extension
- Steps defined
- Check logs for parsing errors

#### Invalid Step Definition
**Symptoms**: Flow stops with "Invalid step definition" error
**Solutions**:
- Ensure all steps have `module` and `action` fields
- Verify module names match available modules
- Check action names exist in the specified module

#### Module Not Found
**Symptoms**: "Module 'name' not found" error
**Solutions**:
- Check spelling of module name
- Verify module is available in `cineflow/modules/`
- Check module file has proper class definition

#### Action Not Found
**Symptoms**: "Action 'name' not found" error
**Solutions**:
- Verify action method exists in module class
- Check method is public (not starting with `_`)
- Ensure method is callable

#### Input Data Issues
**Symptoms**: "No input data" or parameter errors
**Solutions**:
- Check previous step produces expected output
- Verify step names for `{{step_name}}` references
- Ensure input structure matches action expectations

### Best Practices

1. **Start Simple**: Begin with basic flows and add complexity gradually
2. **Use Descriptive Names**: Name flows and steps clearly for easier debugging
3. **Test Incrementally**: Test each step individually before chaining
4. **Monitor Resources**: Be mindful of API rate limits and system resources
5. **Regular Cleanup**: Use cleanup flows to manage disk space and library size
6. **Error Handling**: Flows stop on errors, so validate inputs and test thoroughly
7. **Documentation**: Comment your flows with meaningful names and descriptions

### Performance Optimization

- **Adjust Delays**: Don't run flows more frequently than necessary
- **Limit Results**: Use configuration to limit API results and processing
- **Cache Effectively**: CineFlow caches module instances between runs
- **Monitor APIs**: Respect rate limits for external services
- **Resource Management**: Consider system resources when setting multiple flows
