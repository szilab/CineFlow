# Web GUI and Configuration Model

CineFlow ships an optional web GUI for configuring modules and building flows
without editing YAML. It is served by the CineFlow process itself and works on
the same files the runtime reads, so hand-written YAML and GUI-made flows are
interchangeable.

## Enabling the GUI

The GUI is off by default. Set a port to enable it:

```bash
CINEFLOW_WEB_PORT=8080 cineflow        # or: cineflow --web-port 8080
```

| Variable | Default | Meaning |
|---|---|---|
| `CINEFLOW_WEB_PORT` | unset (disabled) | port of the GUI and its JSON API |
| `CINEFLOW_WEB_HOST` | `127.0.0.1` (`0.0.0.0` in Docker) | listen address |
| `CINEFLOW_AUTH` | unset | sign-in methods, see [Authentication](#authentication) |

Docker:

```bash
docker run -e CINEFLOW_WEB_PORT=8080 -e CINEFLOW_AUTH=password \
  -e CINEFLOW_AUTH_PASSWORD_HASH='pbkdf2_sha256$600000$...' \
  -p 8080:8080 -v ./cineflow-data:/data <image>
```

Without authentication the GUI only starts on a loopback address. On any
other address CineFlow refuses to start until `CINEFLOW_AUTH` is set (use
`CINEFLOW_AUTH=none` only when an authenticating reverse proxy protects it).
All URLs are relative, so the GUI also works below a sub-path such as
`https://example.org/cineflow/` when the proxy strips the prefix
(Caddy `handle_path /cineflow/*`).

Modifying API requests must use `Content-Type: application/json` and, when the
browser sends an `Origin` header, come from the same host. The pages are
served with a strict Content Security Policy.

## Authentication

Authentication is optional. Choose one or more methods with `CINEFLOW_AUTH`
(comma-separated):

| Method | What it does |
|---|---|
| `password` | one local account with a sign-in form |
| `oidc` | single sign-on with an OpenID Connect provider (VoidAuth, Authelia, Authentik, Keycloak, …) |
| `header` | trusts the user header of an authenticating reverse proxy (forward auth) |
| `none` | no authentication, explicitly |

Sessions are signed, `HttpOnly`, `SameSite=Lax` cookies (`Secure` when the
public URL is https). The signing key comes from `CINEFLOW_SECRET_KEY` or is
generated once into `<CINEFLOW_HOME>/config/.cineflow/secret` (mode 600). All settings
are environment variables, so nothing in the GUI can weaken or lock out its
own sign-in.

Common settings:

| Variable | Default | Meaning |
|---|---|---|
| `CINEFLOW_AUTH` | unset | methods, e.g. `oidc,password` |
| `CINEFLOW_PUBLIC_URL` | unset | external URL of the GUI, e.g. `https://web.example.org/cineflow` (required for `oidc`) |
| `CINEFLOW_AUTH_SESSION_HOURS` | `12` | session lifetime |
| `CINEFLOW_AUTH_ALLOWED_USERS` | any | comma-separated user names allowed in |
| `CINEFLOW_AUTH_ALLOWED_GROUPS` | any | comma-separated groups allowed in |
| `CINEFLOW_SECRET_KEY` | generated | session signing key |

### Password

```bash
CINEFLOW_AUTH=password
CINEFLOW_AUTH_USERNAME=admin              # default: admin
CINEFLOW_AUTH_PASSWORD_HASH='pbkdf2_sha256$600000$...'   # from: cineflow hash-password
# or, less safe: CINEFLOW_AUTH_PASSWORD=plain-text
```

`cineflow hash-password` asks for a password and prints the hash. In
`docker-compose.yml` write every `$` of the hash as `$$`. Five failed sign-ins
from one address within five minutes block further attempts for a while.

### Single sign-on (OIDC)

Register CineFlow as a confidential client at the provider with the redirect
URL `<CINEFLOW_PUBLIC_URL>/auth/oidc/callback`, then:

```bash
CINEFLOW_AUTH=oidc                       # or oidc,password for a local fallback
CINEFLOW_PUBLIC_URL=https://web.example.org/cineflow
CINEFLOW_OIDC_ISSUER=https://auth.example.org
CINEFLOW_OIDC_CLIENT_ID=cineflow
CINEFLOW_OIDC_CLIENT_SECRET=...
CINEFLOW_OIDC_LABEL=VoidAuth             # text of the sign-in button
CINEFLOW_AUTH_ALLOWED_GROUPS=media       # optional
```

| Variable | Default |
|---|---|
| `CINEFLOW_OIDC_SCOPES` | `openid profile email groups` |
| `CINEFLOW_OIDC_USER_CLAIM` | `preferred_username` |
| `CINEFLOW_OIDC_GROUPS_CLAIM` | `groups` |
| `CINEFLOW_OIDC_TOKEN_AUTH` | `basic` (`client_secret_basic`), or `post` |

The sign-in uses the authorization code flow with PKCE, `state` and `nonce`.
The ID token is taken straight from the token endpoint over TLS (OpenID Connect
Core 3.1.3.7), and its issuer, audience, expiry and nonce are checked; missing
user or group claims are read from the userinfo endpoint.

### Reverse proxy header (forward auth)

When the proxy already authenticates every request (for example Caddy
`forward_auth` with VoidAuth or Authelia), CineFlow can trust its headers:

```bash
CINEFLOW_AUTH=header
CINEFLOW_AUTH_TRUSTED_PROXIES=127.0.0.1,172.16.0.0/12   # addresses of the proxy
CINEFLOW_AUTH_HEADER=Remote-User                        # default
CINEFLOW_AUTH_GROUPS_HEADER=Remote-Groups               # default
```

Headers from any other address are ignored, so make sure only the proxy can
reach the GUI port.

## Concepts

### Module definition

Every module class declares a `DEFINITION`
(`cineflow/core/schema.py`): id, label, description, category, configuration
fields and the actions it publishes. A field has a type (`string`, `integer`,
`number`, `boolean`, `select`, `url`, `path`, `secret`, `list`, `object`),
required flag, default, range or options, description, and whether a flow step
may override it (`step`). An action declares its input kind (`none`, `data`,
`query`, `data+query`), its known query keys, extra arguments, its own step
settings (for example `must_match`), whether it is destructive, and its
*stage* in the flow editor:

| Stage | Meaning | Derived when not declared |
|---|---|---|
| `source` | collects items | takes no items (`none` or `query` input) |
| `enrich` | adds data to every item | takes items only (`data`) |
| `combine` | merges several sources | declared (`tools.remove_duplicates`) |
| `filter` | drops items | takes items and a query (`data+query`) |
| `output` | changes something outside CineFlow | `side_effects` or `destructive` |

An action marked `local` works on the items alone without contacting its
service (for example *Exclude by ID* or *Filter by field*); the flow editor lists
it once, in the *Any items* group.

The GUI renders every form from these definitions. Adding a module or an
action only needs a Python definition; no frontend change.

### Module instances

`config.yaml` keeps its existing per-module sections. Each section is the
**module default** that every step of that module uses, exactly as before.

Named instances let a flow talk to several servers of the same kind:

```yaml
jellyfin:                # module default
  url: http://jellyfin:8096
  token: API_KEY

instances:
  living-room:           # instance id
    module: jellyfin
    name: Living room Jellyfin
    config:
      url: http://living-room:8096
      token: OTHER_KEY
```

A step selects one with `instance: living-room`. Settings are merged as:

```text
module default < instance settings < step config < environment override
```

Instance status is shown as **valid**, **incomplete** (only required values
are missing) or **invalid** (wrong values). Only valid instances can be used in
a flow, and an instance used by a flow cannot be deleted.

### Settings set by environment variables

A module setting that an environment variable overrides (`<MODULE>_<KEY>`, or
the field's own `env`, such as `EXPORT_DIRECTORY` for the library
`export_directory`) is shown read-only with the variable's value and name;
secrets show only that they are set. The YAML value stays in the file but has
no effect while the variable is set. Paths are always shown in full.

### Dropdowns read from the services

A field may name a list of valid values that its module reads from the
service (`Field.choices`, answered by `ModuleBase.field_choices`). The GUI
shows such a field as a dropdown filled from the step's module instance:
the library of Jellyfin and Plex steps and the Jellyfin user. The list comes
from `GET instances/<id>/choices/<list>`, which needs valid module settings,
is kept for five minutes and is read again after the module settings are
saved. A value that is no longer offered is shown as *(not found)*; when the
list cannot be read, the field falls back to a text input. A field with an
`all_key` gets an *All* entry that writes that boolean key instead: the
Jellyfin *User* dropdown offers *Default* (the first user), *All users*
(`allUsers: true`) or one user (`userName`).

### Secrets

Fields of type `secret` (and undeclared keys that look like credentials, such
as `token` or `password`) are never sent to the browser and never exported.
The GUI shows a stored secret as a mask. Saving with the mask unchanged
keeps the stored value, a typed value replaces it, and an emptied field
deletes it: the field warns about it and saving asks for confirmation. Logs
redact credentials as before.

### Flows

A flow stays a YAML file in `<CINEFLOW_HOME>/config` with the same keys and semantics.
The GUI adds two optional keys that the runtime ignores:

- `description` — free text;
- `version` — a revision counter increased on every GUI save.

Step names are the node identifiers: later steps refer to earlier ones by
name, and the GUI keeps them unique and updates references when a step is
renamed.

## Using the GUI

**Modules** lists every module with its connection (and any named instances
from `config.yaml`; named instances are not created in the GUI). Selecting
one opens a generated form. *Test* checks the unsaved values and, when
they are valid, performs one cheap authenticated request (TMDb, Jackett,
Jellyfin, Plex, Transmission, qBittorrent) with them; *Save* writes
`config.yaml`. Saving settings rebuilds the module objects of every
flow, so the change applies from the next step without a restart.
Fields are listed in one column; word lists (e.g. *Search preference*) come
at the end of their section.

Every form uses the same layout: one-line inputs and dropdowns come first,
with their label in front and the hint under the label; then the on/off
switches, two to a row when they fit, each switch in front of its label (its
hint is shown on hover); lists come last. Yes/no and short choice
lists are text sliders like the flow header switches, longer lists are
dropdowns. Word lists (here and on steps) are edited as labels: type a word and press
Enter or the arrow inside the field to add it; drag labels to change their
order (or focus one and use Alt+arrow keys), and remove one with its ×
(or Delete). Lists of mappings whose fields are declared (`item_fields`),
such as the filter conditions and the poster rules, are edited as cards,
one per item, with *+ Add …* and a remove button; other lists of mappings
stay a JSON text box.

**Flows** has a second menu row with one entry per flow (long names are
shortened; a dot shows enabled, disabled, invalid or running) and a *+* at
the end. *+* opens a small dialog that creates a disabled flow without steps
from a name, description and media kind, or imports one from YAML.

#### Flow header

The top box of the flow page holds everything that belongs to the whole flow:

- the name and the description, edited in place;
- top right, the state of the flow: *valid* or the number of errors, warnings,
  *unsaved* and *running*;
- below the description, three switches:
  - **Media**: *Movies*, *TV series* or *Both*. The kind is passed to every
    step (it is not a module setting). *Both* runs the flow twice, first for
    movies, then for TV series;
  - **Schedule**: *Disabled*, *10m*, *30m*, *1h*, *4h*, *12h*, *1d* or *1w*.
    *Disabled* writes `enabled: false` and keeps the interval; any other value
    enables the flow with that `delay`. An interval written by hand (for
    example 15 minutes) is shown as an extra choice;
  - **Priority**: *Low*, *Medium* or *High*, written as `priority` 100, 10
    or 1 (lower runs first in sequential mode). Hand-written numbers are shown
    as *High* up to 5, *Medium* up to 50 and *Low* above;
- below them, while a Library or Jackett step uses them, the flow settings
  those modules share, side by side with their labels above them: the
  *Library folder* inside the export directory (default the media kind; the
  field shows the full export path in front of the folder name, and a flow of
  both kinds says which folder each kind goes to) and the *Release preference*
  as numbered word labels (see [CONFIGURATION.md](CONFIGURATION.md#flow-settings));
- bottom right, the *Save*, *Run*, *Test* and *Delete* buttons. *Save* writes
  the YAML file and reloads the flow at once; *Run* starts one run in the
  background (save first); *Test* runs the flow with real data but **without
  side effects** (see below).

#### Flow editor

Below the header the flow is shown as three columns:

1. **Sources**: where the items come from. *+ Add a source* only asks for
   the module (grouped by module category), because every module has one way
   to collect items. At the top of the settings of a source, *Add data from*
   has a three-way switch per service that looks up every item of the source
   (for example release links from Jackett or the title in your language from
   TMDb): *Off*, *On* (add the data when the item is found) or *Must* (also
   drop the items that are not found; `must_match: true`). Only set-up modules of another category than the source
   are offered, so a Jellyfin source gets no Plex switch; a service the flow
   already uses stays listed so it can be switched off. The data is added in
   the order of the module list (TMDb before Jackett); the source card lists
   the services. With several sources the items are merged into one list and
   duplicates are removed automatically.
2. **Filters** (optional): keep only the items you want, for example
   *Not in Jellyfin*, *Exclude by ID*, *Filter by field* (one or more
   conditions such as "the release name contains HUN" or "at least 40
   seeders", combined with and/or) or *Next season to
   download* (TV), or
   add data to the items left, e.g. the release of the chosen season from
   Jackett. These steps run in their order, after the merge.
3. **Actions**: what happens with the items, for example *Add torrents* or
   *Export to library*. Every action gets the filtered items.

The *+* buttons only offer actions that fit the column. Click a card to open
its few options on the right; click it again or *✕* to close them. Options
a regular user rarely needs (marked `advanced` in the module definition,
e.g. item limits, search term, inverse queries, extra JSON parameters) are in
a collapsed *More options* section, which opens by itself when one is in use.
Library fields of Jellyfin and Plex steps are a *Libraries* choice: *All*,
*Only* or *All except*, with one or more libraries picked from the server.
It writes `parentLibrary` (one name or a list) and `isInverse` into the step,
so excluding what is already on the media server except the CineFlow
libraries is *Not in Jellyfin* with *All except* and those libraries. An action may list module settings to show on its step (`overrides`): empty
means the module value, shown as *inherit (…)*, and a value is stored as the
step's override in `config`. The Jackett source step shows *Minimum seeders*,
*Resolution* and *Maximum size* this way; its include and exclude words are
under *More options*. The module is shown at the top right of the step panel, green
when it is ready and red when it still needs settings; click it to open the
module settings. A step keeps showing a module setting only when its YAML
already overrides it, or when a required step-level value is missing, with
*Use module value* to drop the override. Cards and fields show errors and
warnings from the backend validator while you type, and a card whose module
has no complete settings shows *set up*.

Step names, inputs and the merge step are written automatically and step
names are not shown (they appear in test runs and logs), so there is nothing
to wire: the sources and their data steps first, then the merge
(`tools.remove_duplicates` with the list of sources), the filters with
`input: previous`, the first action with `input: previous` and further
actions with a `{{name}}` reference to the last filter. A test run shows the
item count on each card (for *Both*, the movie and TV counts).

A flow that does not have this shape, for example one with a second source
after the actions or a filter on only one of several sources, is shown with
the reason instead of the columns. It keeps running as before; edit its YAML
file by hand or split it into several flows. Its header switches still work.

A flow with validation errors can only be saved disabled, as a draft. If the
file changed on disk after it was opened, saving is refused until it is
reloaded, so concurrent hand edits are never overwritten silently.

The **Modules** page lists the modules that have settings (Tools has none, so
it is not shown). Every card shows the state of its module in the top
right corner (*ready*, *incomplete*, *invalid* or *unreachable*); clicking the
card opens its settings on the right. While the page is open it re-checks the
module states and tests every complete connection once a minute.

### Test runs

A test run executes the steps (all, or up to the chosen one) of the flow as it
is in the editor, saved or not, with the normal input and failure rules. Read
actions really query your services, so the result shows what the flow would
work with. Actions that change something outside CineFlow — adding torrents,
writing or removing library items, exporting files — are not called; they pass
their input on and are marked *skipped in test*. The panel shows each step's
result, item count and duration, a table of its items 25 to a page
(credentials in values are masked) and the log messages of the test. The
pager browses up to 2000 items per step; the pages are read from the server,
which keeps the last five test results, so after a restart the test must be
run again to page. A test is stopped after
three minutes; at most two run at the same time.

The execution mode is set with `execution` in `config.yaml`. A validation
report of everything and a `config.yaml` export without secrets are still
available through the API (`GET validate`, `GET config/export`).

## Validation

`cineflow/core/validation.py` is the single validator used by the GUI, the API
and the CLI:

```bash
cineflow validate          # human-readable, exit code 1 on errors
cineflow validate --json   # structured issues
```

It never contacts services, starts workers or creates files. It checks:

- fields: required values (including `<MODULE>_<KEY>` environment
  overrides), types, URL/path format, ranges and options;
- configuration: execution mode, module sections, instance ids, modules and
  inherited settings;
- flows: root keys, `enabled`/`delay`/`priority`, step structure, duplicate
  step names, modules, actions, instance references and status, effective
  required settings, step settings, `{{name}}` references to earlier steps and
  input shapes per action.

Each issue has a level, a path such as `steps.2.config.limit`, a message and a
code. When the runtime loads a flow file it logs these findings as warnings;
it does not refuse to run flows that worked before.

## Backups and storage

Every GUI write first copies the previous file to `<CINEFLOW_HOME>/config/.backups`
(the last 20 versions per file are kept) and then replaces the file
atomically. Deleting a flow also leaves a backup. Writing `config.yaml` from
the GUI drops YAML comments in it; the backup keeps the original.

## Getting started

1. Run `cineflow validate` and fix the reported errors.
2. Start CineFlow with `CINEFLOW_WEB_PORT` and check the module statuses.

Flows that use an input shape the form cannot represent are still editable as
JSON in the step panel.

## API

All endpoints are below `api/` and exchange JSON. Errors have the form
`{"error": {"message": ..., "issues": [...]}}`.

| Method and path | Purpose |
|---|---|
| `GET health` | version and whether the runtime is attached |
| `GET catalog` | module definitions |
| `GET instances` | defaults and named instances with status (secrets masked) |
| `POST instances` | create a named instance `{module, name, id?, config?}` |
| `GET/PUT/DELETE instances/<id>` | read, save `{config, name?}`, delete |
| `POST instances/<id>/validate` | validate saved or unsaved `{config}` |
| `POST instances/<id>/test` | connection test with saved or unsaved `{config}` |
| `POST instances/test-all` | connection test of every complete instance |
| `GET instances/<id>/choices/<list>` | values of a dropdown field read from the service, e.g. `libraries` |
| `GET flows` | flows with validation and runtime state |
| `POST flows` | create `{flow}` |
| `GET/PUT/DELETE flows/<id>` | read (with `revision`), save `{flow, revision}`, delete |
| `POST flows/validate` | validate an unsaved `{flow}` |
| `POST flows/import` | create from `{yaml, as_draft?}` |
| `POST flows/test` | test run of `{flow, id?, until?}` without side effects |
| `GET flows/test/<test>/<step>/<page>` | one page of the items of a step result of a recent test run |
| `GET flows/<id>/yaml` | export without secrets |
| `POST flows/<id>/run` | start one manual run |
| `GET flows/<id>/logs` | recent log messages of the flow |
| `GET/PUT settings` | execution mode |
| `GET validate` | validate configuration and all flows |
| `GET config/export` | `config.yaml` without secrets |
| `GET auth/status`, `POST auth/login`, `POST auth/logout` | sign-in (public) |
| `GET /auth/oidc/login`, `GET /auth/oidc/callback` | SSO redirect endpoints (outside `api/`) |

With authentication enabled every other endpoint answers 401 without a valid
session.

## Architecture

```text
browser ── static/app.js (no build step) ──► cineflow/web/server.py (http.server)
                                               │
                                               ▼
                                       cineflow/web/api.py ──► core/validation.py ─► core/schema.py
                                               │                       ▲                 ▲
                                               ├──► core/store.py ─────┘   module DEFINITIONs
                                               │      (YAML files, backups, secret masking)
                                               └──► core/runner.FlowManager (refresh, run, state)
```

Decisions:

- **No new dependency.** The server uses the standard library; the frontend is
  plain JavaScript and CSS shipped inside the wheel, so Docker, the wheel and
  the Windows executable need no Node.js build.
- **YAML stays the storage.** A database would duplicate the source of truth,
  break hand editing and need a migration; the files already give
  versioning through backups and git.
- **The backend owns all rules.** The frontend only renders definitions and
  issues returned by the API.
- **The flow states what runs.** GUI conveniences are written into the flow
  YAML as explicit values (the merge step, step inputs, `allUsers`,
  `parentLibrary` with `isInverse`, `must_match`, step overrides) instead of
  defaults the runtime would apply silently, so a flow file reads the same as
  it runs.
- **The flow editor is a view.** `static/funnel.js` reads the step list as
  sources → merge → filters → actions and writes it back; the YAML format and
  the runtime do not change. Action stages come from the module definitions,
  so a new module appears in the right column without frontend changes.

## Known limitations

- One local password account; more users come from the SSO provider or the proxy.
- Sessions cannot be revoked one by one; changing `CINEFLOW_SECRET_KEY` (or
  deleting the generated key file) signs everyone out.
- Execution mode changes need a restart (shown in the GUI).
- Flows remain linear pipelines with name references; there are no branches.
  The GUI edits flows of the form sources → merge → filters → actions;
  others are edited by hand.
- The log view keeps the last 2000 messages of the process in memory
  (`LOG_HISTORY`); it is empty after a restart.
- Connection tests check reachability and credentials, not library names or
  indexer results.
