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
  -p 8080:8080 -v ./config:/config -v ./library:/library <image>
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
generated once into `CFG_DIRECTORY/.cineflow/secret` (mode 600). All settings
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
settings (for example `must_match`), and whether it is destructive.

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

### Secrets

Fields of type `secret` (and undeclared keys that look like credentials, such
as `token` or `password`) are never sent to the browser and never exported.
The GUI shows only whether a secret is stored. Saving without typing a new
value keeps the stored one; the "Clear stored value" box removes it. Logs
redact credentials as before.

### Flows

A flow stays a YAML file in `CFG_DIRECTORY` with the same keys and semantics.
The GUI adds two optional keys that the runtime ignores:

- `description` — free text;
- `version` — a revision counter increased on every GUI save.

Step names are the node identifiers: later steps refer to earlier ones by
name, and the GUI keeps them unique and updates references when a step is
renamed.

## Using the GUI

**Modules** lists every module with its default and named instances. Selecting
one opens a generated form. *Validate* checks the unsaved values, *Test
connection* performs one cheap authenticated request (TMDb, Jackett,
Jellyfin, Plex, Transmission, qBittorrent) with the unsaved values, *Save*
writes `config.yaml`. Saving settings rebuilds the module objects of every
flow, so the change applies from the next step without a restart.

**Flows** shows the flows with their schedule, validation and last result.
The editor is a vertical pipeline of action cards:

- drag an action from the *Actions* list on the left and drop it anywhere in
  the pipeline, or click it to append it; the *+* between two cards and
  *+ Add action* open the searchable action catalog;
- drag a card (or focus it and press Alt+↑/↓) to reorder, *⧉* duplicates
  it, *✕* or the Delete key removes it;
- a card whose module has no complete settings shows *set up*, which opens
  the module settings in a dialog; the step panel has the same *Configure*
  button and can create a new connection on the spot;
- click a card to edit its name, action, module instance, input source
  (previous step, a named earlier step, or several merged steps), query,
  arguments and step settings;
- cards and fields show errors and warnings from the backend validator while
  you type;
- *Test run* (or *▶* on a card for "up to this step") runs the flow with
  real data but **without side effects** — see below;
- *Save* writes the YAML file and reloads the flow at once;
- *Run now* starts one run in the background; the side panel shows the last
  result, the failing step and the recent log messages of the flow;
- *Export YAML* downloads the file without secrets, *Import* creates a flow
  from YAML.

A flow with validation errors can only be saved disabled, as a draft. If the
file changed on disk after it was opened, saving is refused until it is
reloaded, so concurrent hand edits are never overwritten silently.

**Modules** also has *Test all connections* and a quick *⚡* test next to
every complete connection.

### Test runs

A test run executes the steps (all, or up to the chosen one) of the flow as it
is in the editor, saved or not, with the normal input and failure rules. Read
actions really query your services, so the result shows what the flow would
work with. Actions that change something outside CineFlow — adding torrents,
writing or removing library items, exporting files — are not called; they pass
their input on and are marked *skipped in test*. The panel shows each step's
result, item count and duration, a table of the first 25 items (credentials in
values are masked) and the log messages of the test. A test is stopped after
three minutes; at most two run at the same time.

**Settings** edits the execution mode, runs a validation of everything and
exports `config.yaml` without secrets.

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

Every GUI write first copies the previous file to `CFG_DIRECTORY/.backups`
(the last 20 versions per file are kept) and then replaces the file
atomically. Deleting a flow also leaves a backup. Writing `config.yaml` from
the GUI drops YAML comments in it; the backup keeps the original.

## Migration

No migration is needed. Existing `config.yaml` and flow files are used as
they are, and the GUI opens them directly. Recommended steps:

1. Run `cineflow validate` and fix the reported errors.
2. Start CineFlow with `CINEFLOW_WEB_PORT` and check the module statuses.
3. Optionally move credentials of a second server into a named instance and
   select it in the steps that use it.

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
| `GET flows` | flows with validation and runtime state |
| `POST flows` | create `{flow}` |
| `GET/PUT/DELETE flows/<id>` | read (with `revision`), save `{flow, revision}`, delete |
| `POST flows/validate` | validate an unsaved `{flow}` |
| `POST flows/import` | create from `{yaml, as_draft?}` |
| `POST flows/test` | test run of `{flow, id?, until?}` without side effects |
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

## Known limitations

- One local password account; more users come from the SSO provider or the proxy.
- Sessions cannot be revoked one by one; changing `CINEFLOW_SECRET_KEY` (or
  deleting the generated key file) signs everyone out.
- Execution mode changes need a restart (shown in the GUI).
- Flows remain linear pipelines with name references; there are no branches.
- The log view keeps the last 2000 messages of the process in memory
  (`LOG_HISTORY`); it is empty after a restart.
- Connection tests check reachability and credentials, not library names or
  indexer results.
