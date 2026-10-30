/* CineFlow web GUI: module manager and card-based flow editor.
 *
 * Plain JavaScript without a build step. Every form is generated from the
 * module definitions served by /api/catalog, and every validation result comes
 * from the backend, so new modules and actions need no frontend change.
 */
'use strict';

const state = {
  view: 'flows',
  catalog: [],          // module definitions
  instances: [],        // module defaults and named instances
  flows: [],            // flow summaries
  health: null,
  flowId: null,         // selected flow id, null for an unsaved new flow
  flow: null,           // flow being edited (YAML structure)
  revision: null,
  dirty: false,
  issues: [],
  runtime: null,
  logs: [],
  stepIndex: null,      // selected step
  instanceId: null,     // selected instance in the modules view
  instanceDraft: null,
  instanceIssues: [],
  settings: null,
  report: null,
};

/* ------------------------------------------------------------ utilities */

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else if (key === 'value') el.value = value;
    else if (key === 'checked') el.checked = Boolean(value);
    else el.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

const clone = (value) => (value === undefined ? undefined : JSON.parse(JSON.stringify(value)));
const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const isEmpty = (value) => value === undefined || value === null || value === '' ||
  (Array.isArray(value) && value.length === 0) || (isObject(value) && Object.keys(value).length === 0);

function getPath(obj, key) {
  return key.split('.').reduce((cur, part) => (isObject(cur) ? cur[part] : undefined), obj);
}

function setPath(obj, key, value) {
  const parts = key.split('.');
  let cur = obj;
  parts.slice(0, -1).forEach((part) => {
    if (!isObject(cur[part])) cur[part] = {};
    cur = cur[part];
  });
  const last = parts[parts.length - 1];
  if (isEmpty(value)) delete cur[last]; else cur[last] = value;
  // drop emptied parents
  if (parts.length > 1 && isEmpty(getPath(obj, parts.slice(0, -1).join('.')))) {
    setPath(obj, parts.slice(0, -1).join('.'), undefined);
  }
}

function toast(message, kind = '') {
  const el = h('div', { class: `toast ${kind}` }, message);
  document.getElementById('toasts').append(el);
  setTimeout(() => el.remove(), kind === 'err' ? 7000 : 3500);
}

function fmtTime(seconds) {
  if (!seconds) return '—';
  return new Date(seconds * 1000).toLocaleString();
}

function download(filename, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/yaml' }));
  const link = h('a', { href: url, download: filename });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

class ApiError extends Error {
  constructor(status, payload) {
    super((payload && payload.error && payload.error.message) || `HTTP ${status}`);
    this.status = status;
    this.issues = (payload && payload.error && payload.error.issues) || [];
  }
}

async function api(method, path, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  } else if (method !== 'GET') {
    options.headers['Content-Type'] = 'application/json';
  }
  const response = await fetch(`api/${path}`, options);
  let payload = null;
  try { payload = await response.json(); } catch (e) { payload = null; }
  if (response.status === 401 && !path.startsWith('auth/') && state.auth && state.auth.enabled) {
    state.auth.authenticated = false;
    state.dirty = false;
    renderLogin('Your session ended. Sign in again.');
  }
  if (!response.ok) throw new ApiError(response.status, payload);
  return payload;
}

function moduleDef(id) { return state.catalog.find((item) => item.id === id); }
function actionDef(moduleId, actionId) {
  const mod = moduleDef(moduleId);
  return mod ? mod.actions.find((item) => item.id === actionId) : undefined;
}
function instanceById(id) { return state.instances.find((item) => item.id === id); }

function statusPill(status) {
  const kinds = { valid: 'ok', incomplete: 'warn', invalid: 'err', success: 'ok', failed: 'err', stopped: 'warn' };
  return h('span', { class: `pill ${kinds[status] || ''}` }, status);
}

function issuesAt(issues, prefix) {
  return issues.filter((issue) => prefix.every((part, i) => String(issue.path[i]) === String(part)));
}

function issueList(issues) {
  if (!issues.length) return null;
  return h('ul', { class: 'issues' }, issues.map((issue) => h('li', { class: `issue ${issue.level}` },
    issue.message, issue.path.length ? [' ', h('code', {}, issue.path.join('.'))] : null)));
}

function fieldIssues(issues) {
  return issues.map((issue) => h('div', { class: `field-issue ${issue.level}` }, issue.message));
}

/* ------------------------------------------------------- generated forms */

/** Render an input for a field definition. ``onChange`` receives the parsed value or undefined. */
function fieldInput(spec, value, onChange, opts = {}) {
  const id = `f-${Math.random().toString(36).slice(2)}`;
  const inherit = opts.inherit;
  const inheritText = inherit ? `inherit (${inherit})` : 'inherit';
  const placeholder = opts.placeholder !== undefined ? opts.placeholder
    : (spec.default !== null && spec.default !== undefined && !Array.isArray(spec.default) ? `default: ${spec.default}` : '');
  let control;
  const type = spec.type;
  if (type === 'boolean') {
    const current = value === true ? 'true' : value === false ? 'false' : '';
    const defaultText = inherit !== undefined ? inheritText
      : spec.default !== null && spec.default !== undefined ? `default (${spec.default ? 'yes' : 'no'})` : 'not set';
    control = h('select', { id, onchange: (e) => onChange(e.target.value === '' ? undefined : e.target.value === 'true') },
      h('option', { value: '' }, defaultText),
      h('option', { value: 'true' }, 'yes'),
      h('option', { value: 'false' }, 'no'));
    control.value = current;
  } else if (type === 'select') {
    const defaultText = inherit !== undefined ? inheritText
      : spec.default ? `default (${spec.default})` : '— not set —';
    control = h('select', { id, onchange: (e) => onChange(e.target.value === '' ? undefined : e.target.value) },
      h('option', { value: '' }, defaultText),
      spec.options.map((option) => h('option', { value: option }, option)));
    control.value = value === undefined || value === null ? '' : String(value);
  } else if (type === 'integer' || type === 'number') {
    control = h('input', {
      id, type: 'number', value: value ?? '', placeholder: inherit !== undefined ? inheritText : placeholder,
      min: spec.minimum ?? undefined, max: spec.maximum ?? undefined, step: type === 'integer' ? 1 : 'any',
      oninput: (e) => {
        const raw = e.target.value.trim();
        if (raw === '') return onChange(undefined);
        const num = Number(raw);
        return onChange(Number.isNaN(num) ? raw : num);
      },
    });
  } else if (type === 'list' || type === 'object') {
    const structured = type === 'object' || (Array.isArray(value) && value.some((item) => typeof item === 'object'));
    const text = value === undefined || value === null ? ''
      : structured ? JSON.stringify(value, null, 2) : value.join('\n');
    control = h('textarea', {
      id, class: structured ? 'code' : '', value: text,
      placeholder: structured ? 'JSON' : (inherit ? `${inheritText}, one value per line` : 'one value per line'),
      oninput: (e) => {
        const raw = e.target.value.trim();
        if (raw === '') return onChange(undefined);
        if (structured || raw.startsWith('[') || raw.startsWith('{')) {
          try { onChange(JSON.parse(raw)); e.target.setCustomValidity(''); } catch (err) {
            e.target.setCustomValidity('Invalid JSON');
          }
          return undefined;
        }
        return onChange(raw.split('\n').map((line) => line.trim()).filter(Boolean)
          .map((line) => (/^-?\d+$/.test(line) && spec.key.endsWith('_ids') ? Number(line) : line)));
      },
    });
  } else {
    const secretSet = opts.secretSet;
    control = h('input', {
      id,
      type: type === 'secret' ? 'password' : type === 'url' ? 'url' : 'text',
      autocomplete: type === 'secret' ? 'new-password' : 'off',
      value: value ?? '',
      placeholder: type === 'secret' && secretSet ? '•••••••• (stored, type to replace)'
        : inherit !== undefined ? inheritText : placeholder,
      oninput: (e) => onChange(e.target.value === '' ? undefined : e.target.value),
    });
  }
  if (type === 'secret') {
    const input = control;
    const toggle = h('button', {
      class: 'btn', type: 'button', title: 'Show or hide', 'aria-label': 'Show or hide the value',
      onclick: () => { input.type = input.type === 'password' ? 'text' : 'password'; toggle.textContent = input.type === 'password' ? 'Show' : 'Hide'; },
    }, 'Show');
    control = h('div', { class: 'input-group' }, input, toggle);
  }
  const issues = opts.issues || [];
  const width = opts.wide || type === 'list' || type === 'object' ? ' wide' : (type === 'url' || type === 'secret' ? ' span2' : '');
  return h('div', { class: `field${issues.some((i) => i.level === 'error') ? ' has-error' : ''}${width}` },
    h('label', { for: id }, spec.label || spec.key, spec.required ? h('span', { class: 'req' }, ' *') : null),
    control,
    spec.description ? h('div', { class: 'hint' }, spec.description) : null,
    opts.extra || null,
    fieldIssues(issues));
}

/* ---------------------------------------------------------------- loading */

async function loadBasics() {
  const [catalog, instances, flows, health] = await Promise.all([
    api('GET', 'catalog'), api('GET', 'instances'), api('GET', 'flows'), api('GET', 'health'),
  ]);
  state.catalog = catalog.modules;
  state.instances = instances.instances;
  state.flows = flows.flows;
  state.health = health;
  renderRuntimeStatus();
}

async function refreshFlows() {
  state.flows = (await api('GET', 'flows')).flows;
}

async function refreshInstances() {
  state.instances = (await api('GET', 'instances')).instances;
}

function renderRuntimeStatus() {
  const el = document.getElementById('runtime-status');
  const auth = state.auth || {};
  el.replaceChildren(
    state.health ? h('span', { class: 'muted' }, `v${state.health.version} · ${state.health.runtime ? 'runtime active' : 'runtime not attached'}`) : '',
    auth.enabled && auth.user ? h('span', { class: 'user' }, h('span', { class: 'avatar', 'aria-hidden': 'true' }, auth.user.name.slice(0, 1).toUpperCase()), auth.user.name) : '',
    auth.enabled && auth.user && auth.user.method !== 'header' ? h('button', { class: 'btn small', onclick: signOut }, 'Sign out') : '');
}

async function signOut() {
  if (state.dirty && !window.confirm('Discard unsaved flow changes?')) return;
  state.dirty = false;
  try { await api('POST', 'auth/logout'); } catch (err) { /* the cookie is gone either way */ }
  window.location.reload();
}

function renderLogin(message = '') {
  document.body.classList.add('signed-out');
  document.getElementById('runtime-status').replaceChildren();
  const auth = state.auth || { methods: [] };
  const error = h('div', { class: 'field-issue error', role: 'alert' }, message);
  const parts = [];
  if (auth.methods.includes('oidc')) {
    parts.push(h('a', { class: 'btn primary sso', href: 'auth/oidc/login' }, `Sign in with ${auth.oidc_label || 'SSO'}`));
  }
  if (auth.methods.includes('password')) {
    const user = h('input', { type: 'text', id: 'login-user', autocomplete: 'username', required: true });
    const pass = h('input', { type: 'password', id: 'login-pass', autocomplete: 'current-password', required: true });
    const submit = h('button', { class: 'btn primary', type: 'submit' }, 'Sign in');
    parts.push(h('form', {
      class: 'login-form',
      onsubmit: async (e) => {
        e.preventDefault();
        submit.disabled = true;
        try {
          await api('POST', 'auth/login', { username: user.value, password: pass.value });
          window.location.reload();
        } catch (err) {
          error.textContent = err.message;
          submit.disabled = false;
          pass.select();
        }
      },
    },
    parts.length ? h('div', { class: 'divider' }, h('span', {}, 'or with password')) : null,
    h('div', { class: 'field' }, h('label', { for: 'login-user' }, 'User name'), user),
    h('div', { class: 'field' }, h('label', { for: 'login-pass' }, 'Password'), pass),
    submit));
  }
  if (!parts.length) {
    parts.push(h('p', {}, 'Sign in through your single sign-on portal, then reload this page.'),
      h('button', { class: 'btn primary', onclick: () => window.location.reload() }, 'Reload'));
  }
  document.getElementById('app').replaceChildren(h('div', { class: 'login-wrap' },
    h('div', { class: 'panel login' },
      h('div', { class: 'brand big' }, h('span', { class: 'logo', 'aria-hidden': 'true' }), 'CineFlow'),
      h('p', { class: 'muted' }, 'Sign in to manage your media flows.'),
      parts, error)));
  const first = document.getElementById('login-user');
  if (first) first.focus();
}

/* ------------------------------------------------------------ navigation */

function setView(view) {
  if (state.view === 'flows' && view !== 'flows' && state.dirty
      && !window.confirm('Discard unsaved flow changes?')) return;
  if (view !== 'flows') state.dirty = false;
  state.view = view;
  try { localStorage.setItem('cineflow.view', view); } catch (e) { /* storage unavailable */ }
  document.querySelectorAll('.tab').forEach((tab) => tab.classList.toggle('active', tab.dataset.view === view));
  render();
  if (view === 'settings') loadSettings();
}

function render() {
  const app = document.getElementById('app');
  app.replaceChildren();
  if (state.view === 'flows') app.append(renderFlowsView());
  else if (state.view === 'modules') app.append(renderModulesView());
  else app.append(renderSettingsView());
}

/* ================================================================= FLOWS */

const categoryClass = (mod) => `cat-${((mod && mod.category) || 'other').replace(/[^a-z]+/g, '-')}`;

function moduleBadge(mod) {
  return h('span', { class: `module-badge ${categoryClass(mod)}`, 'aria-hidden': 'true' },
    (mod ? mod.label : '?').slice(0, 2));
}

/** True when no valid instance of a configurable module exists. */
function moduleNeedsSetup(mod) {
  return mod && mod.fields.length > 0 && !state.instances.some((item) => item.module === mod.id && item.status === 'valid');
}

let drag = null; // {type: 'step', index} or {type: 'action', module, action}

function startDrag(e, payload) {
  drag = payload;
  e.dataTransfer.effectAllowed = payload.type === 'step' ? 'move' : 'copy';
  e.dataTransfer.setData('text/plain', payload.type === 'step' ? String(payload.index) : `${payload.module}.${payload.action}`);
  requestAnimationFrame(() => document.body.classList.add('is-dragging'));
}

function endDrag() {
  drag = null;
  document.body.classList.remove('is-dragging');
  if (state.pipelinePending) {
    state.pipelinePending = false;
    setTimeout(() => { const pipeline = document.getElementById('pipeline'); if (pipeline && !drag) pipeline.replaceWith(renderPipeline()); });
  }
  document.querySelectorAll('.over, .drop-before, .drop-after, .dragging').forEach((el) => el.classList.remove('over', 'drop-before', 'drop-after', 'dragging'));
}

function dropAt(index) {
  const payload = drag;
  endDrag();
  if (!payload || !state.flow) return;
  if (payload.type === 'step') {
    moveStep(payload.index, payload.index < index ? index - 1 : index);
  } else {
    insertStep(payload.module, payload.action, index);
  }
}

function renderFlowsView() {
  return h('div', { class: 'layout-flows' },
    h('div', { class: 'left-col' }, renderFlowList(), renderPalette()),
    h('section', {}, renderFlowEditor()),
    h('aside', { class: 'side-panel' }, renderSidePanel()));
}

function renderPalette() {
  const filter = h('input', {
    type: 'text', placeholder: 'Filter actions…', 'aria-label': 'Filter actions', value: state.paletteFilter || '',
  });
  const list = h('div', { class: 'palette-list' });
  const draw = () => {
    const term = filter.value.trim().toLowerCase();
    state.paletteFilter = filter.value;
    list.replaceChildren(...state.catalog.map((mod) => {
      const actions = mod.actions.filter((action) => !term
        || `${mod.label} ${action.label} ${action.description}`.toLowerCase().includes(term));
      if (!actions.length) return null;
      return h('div', { class: 'palette-group' },
        h('div', { class: 'palette-module' }, moduleBadge(mod), h('span', { class: 'grow' }, mod.label),
          moduleNeedsSetup(mod) ? h('button', {
            class: 'pill warn as-button', title: `Configure ${mod.label}`, onclick: () => openInstanceDialog(mod.id),
          }, 'set up') : null),
        actions.map((action) => h('div', {
          class: `chip ${categoryClass(mod)}`, draggable: 'true', tabindex: '0', role: 'button',
          title: `${action.description}\nDrag into the flow, or click to append.`,
          ondragstart: (e) => startDrag(e, { type: 'action', module: mod.id, action: action.id }),
          ondragend: endDrag,
          onclick: () => {
            if (!state.flow) { toast('Open or create a flow first.'); return; }
            insertStep(mod.id, action.id, state.flow.steps.length);
          },
          onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click(); } },
        }, h('span', { class: 'grow' }, action.label),
        action.side_effects ? h('span', { class: 'chip-flag', title: 'Changes external state; skipped in test runs' }, '⚡') : null)));
    }).filter(Boolean));
  };
  filter.addEventListener('input', draw);
  draw();
  return h('div', { class: 'panel palette' },
    h('div', { class: 'panel-head' }, h('h2', {}, 'Actions')),
    h('p', { class: 'muted small' }, 'Drag an action into the flow, or click it to append.'),
    h('div', { class: 'field' }, filter),
    list);
}

function renderFlowList() {
  return h('aside', { class: 'panel' },
    h('div', { class: 'panel-head' }, h('h2', {}, 'Flows'), h('span', { class: 'spacer' }),
      h('button', { class: 'btn small', title: 'Import a flow from YAML', onclick: openImportDialog }, 'Import'),
      h('button', { class: 'btn primary small', onclick: newFlow }, '+ New')),
    state.flows.length ? h('ul', { class: 'list' }, state.flows.map((flow) => h('li', {},
      h('button', {
        class: `list-item${flow.id === state.flowId ? ' active' : ''}`,
        onclick: () => selectFlow(flow.id),
      },
      h('span', { class: 'title' }, flow.name),
      h('span', { class: 'meta' },
        flow.enabled === false ? h('span', { class: 'pill' }, 'disabled') : h('span', { class: 'pill info' }, `every ${flow.delay} min`),
        flow.status === 'invalid' ? h('span', { class: 'pill err' }, `${flow.errors} error${flow.errors === 1 ? '' : 's'}`) : null,
        flow.runtime && flow.runtime.running ? h('span', { class: 'pill info' }, 'running') : null,
        flow.runtime && flow.runtime.last_status ? statusPill(flow.runtime.last_status) : null))))) :
      h('div', { class: 'empty' }, 'No flows yet.'));
}

function newFlow() {
  if (state.dirty && !window.confirm('Discard unsaved flow changes?')) return;
  state.flowId = null;
  state.flow = { name: 'New flow', enabled: false, delay: 60, priority: 10, steps: [] };
  state.revision = null;
  state.dirty = true;
  state.issues = [];
  state.runtime = null;
  state.logs = [];
  state.stepIndex = null;
  state.test = null;
  render();
  scheduleValidation();
}

async function selectFlow(id) {
  if (state.dirty && id !== state.flowId && !window.confirm('Discard unsaved flow changes?')) return;
  try {
    const data = await api('GET', `flows/${encodeURIComponent(id)}`);
    state.flowId = id;
    state.flow = data.flow;
    state.revision = data.revision;
    state.issues = data.issues;
    state.runtime = data.runtime;
    state.dirty = false;
    state.stepIndex = null;
    state.logs = [];
    if (id !== state.testFlowId) state.test = null;
    state.testFlowId = id;
    render();
    loadLogs();
  } catch (err) {
    toast(err.message, 'err');
  }
}

function markDirty() {
  state.dirty = true;
  if (state.test) state.testStale = true;
  scheduleValidation();
}

let validationTimer = null;
function scheduleValidation() {
  clearTimeout(validationTimer);
  validationTimer = setTimeout(async () => {
    if (!state.flow) return;
    try {
      state.issues = (await api('POST', 'flows/validate', { flow: state.flow })).issues;
      updateIssueViews();
    } catch (err) { /* validation is best effort while typing */ }
  }, 350);
}

/** Refresh issue displays without rebuilding the inputs being edited. */
function updateIssueViews() {
  const summary = document.getElementById('flow-issues');
  if (summary) summary.replaceChildren(renderFlowIssueSummary());
  const pipeline = document.getElementById('pipeline');
  // replacing the cards during a drag would drop the dragged element
  if (pipeline && drag) state.pipelinePending = true;
  else if (pipeline) pipeline.replaceWith(renderPipeline());
  const stepIssues = document.getElementById('step-issues');
  if (stepIssues && state.stepIndex !== null) {
    stepIssues.replaceChildren(issueList(issuesAt(state.issues, ['steps', state.stepIndex])) || '');
  }
  document.querySelectorAll('[data-issue-path]').forEach((el) => {
    const path = el.dataset.issuePath.split('.');
    el.replaceChildren(...fieldIssues(state.issues.filter((issue) => issue.path.join('.') === path.join('.'))));
  });
  const save = document.getElementById('save-flow');
  if (save) save.textContent = state.dirty ? 'Save *' : 'Save';
}

function renderFlowIssueSummary() {
  const errors = state.issues.filter((i) => i.level === 'error').length;
  const warnings = state.issues.filter((i) => i.level === 'warning').length;
  const flowLevel = state.issues.filter((i) => i.path[0] !== 'steps' || i.path.length === 1);
  return h('div', {},
    h('div', { class: 'btn-row' },
      errors ? h('span', { class: 'pill err' }, `${errors} error${errors === 1 ? '' : 's'}`) : h('span', { class: 'pill ok' }, 'valid'),
      warnings ? h('span', { class: 'pill warn' }, `${warnings} warning${warnings === 1 ? '' : 's'}`) : null,
      state.dirty ? h('span', { class: 'pill info' }, 'unsaved') : null),
    flowLevel.length ? h('div', { class: 'small' }, issueList(flowLevel)) : null);
}

function renderFlowEditor() {
  if (!state.flow) {
    return h('div', { class: 'panel empty' }, 'Select a flow or create a new one.');
  }
  const flow = state.flow;
  const update = (key, value) => { if (isEmpty(value) && key === 'description') delete flow[key]; else flow[key] = value; markDirty(); };
  const runtime = state.runtime || {};
  return h('div', {},
    h('div', { class: 'panel' },
      h('div', { class: 'panel-head' },
        h('h2', {}, state.flowId ? flow.name || state.flowId : 'New flow'),
        h('span', { class: 'spacer' }),
        h('div', { class: 'btn-row' },
          h('button', { class: 'btn primary', id: 'save-flow', onclick: saveFlow }, state.dirty ? 'Save *' : 'Save'),
          h('button', {
            class: 'btn', disabled: state.testing || !(flow.steps || []).length,
            title: 'Run every step with real data but without side effects', onclick: () => runTest(undefined),
          }, state.testing ? 'Testing…' : 'Test run'),
          h('button', {
            class: 'btn', disabled: !state.flowId || state.dirty || !(state.health && state.health.runtime),
            title: state.dirty ? 'Save the flow first' : 'Run the flow once now', onclick: runFlow,
          }, runtime.running ? 'Running…' : 'Run now'),
          h('button', { class: 'btn', disabled: !state.flowId, onclick: exportFlow }, 'Export YAML'),
          h('button', { class: 'btn danger', disabled: !state.flowId, onclick: deleteFlow }, 'Delete'))),
      h('div', { class: 'form-grid' },
        h('div', { class: 'field wide' }, h('label', { for: 'flow-name' }, 'Name'),
          h('input', { id: 'flow-name', type: 'text', value: flow.name || '', oninput: (e) => update('name', e.target.value) }),
          h('div', { dataset: { issuePath: 'name' } })),
        h('div', { class: 'field wide' }, h('label', { for: 'flow-desc' }, 'Description'),
          h('input', { id: 'flow-desc', type: 'text', value: flow.description || '', oninput: (e) => update('description', e.target.value) })),
        h('div', { class: 'field' }, h('label', { for: 'flow-delay' }, 'Run every (minutes)'),
          h('input', { id: 'flow-delay', type: 'number', min: 1, step: 1, value: flow.delay ?? 60,
            oninput: (e) => update('delay', e.target.value === '' ? undefined : Number(e.target.value)) }),
          h('div', { dataset: { issuePath: 'delay' } })),
        h('div', { class: 'field' }, h('label', { for: 'flow-priority' }, 'Priority'),
          h('input', { id: 'flow-priority', type: 'number', step: 1, value: flow.priority ?? 99,
            oninput: (e) => update('priority', e.target.value === '' ? undefined : Number(e.target.value)) }),
          h('div', { class: 'hint' }, 'Lower runs first in sequential mode.'),
          h('div', { dataset: { issuePath: 'priority' } })),
        h('div', { class: 'field' }, h('span', { class: 'label' }, 'State'),
          h('label', { class: 'check' }, h('input', {
            type: 'checkbox', checked: flow.enabled !== false, onchange: (e) => update('enabled', e.target.checked),
          }), 'Enabled'),
          h('div', { class: 'hint' }, 'Only flows without errors can be enabled.'))),
      h('div', { id: 'flow-issues', class: 'section-gap' }, renderFlowIssueSummary())),
    h('div', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('h2', {}, 'Steps'), h('span', { class: 'spacer' }),
        h('span', { class: 'muted small' }, 'Drag to reorder · drop actions between steps · click to configure')),
      renderPipeline(),
      h('button', { class: 'add-step', onclick: () => openCatalogDialog() }, '+ Add action')),
    renderTestPanel());
}

function stepSummary(step, index) {
  const parsed = parseInput(step.input);
  const parts = [];
  if (parsed.mode === 'custom') parts.push('custom input');
  else if (parsed.source === 'previous') parts.push('input: previous step');
  else if (parsed.source === 'step') parts.push(`input: ${parsed.step}`);
  else if (parsed.source === 'merge') parts.push(`input: ${parsed.steps.join(' + ')}`);
  else if (index > 0) parts.push('no item input');
  if (parsed.query !== undefined && !isEmpty(parsed.query)) parts.push('with query');
  return parts.join(' · ');
}

function dropZone(index, kind) {
  const zone = h('div', {
    class: `drop-zone ${kind}`,
    ondragover: (e) => { if (!drag) return; e.preventDefault(); zone.classList.add('over'); },
    ondragleave: () => zone.classList.remove('over'),
    ondrop: (e) => { e.preventDefault(); dropAt(index); },
  },
  h('span', { class: 'drop-line', 'aria-hidden': 'true' }),
  kind === 'between' ? h('button', {
    class: 'insert-btn', title: 'Insert an action here', 'aria-label': `Insert an action before step ${index + 1}`,
    onclick: () => openCatalogDialog(index),
  }, '+') : null,
  h('span', { class: 'drop-hint' }, 'Drop here'));
  return zone;
}

function testResultFor(index) {
  return state.test ? state.test.steps.find((item) => item.index === index) : undefined;
}

function resultPill(result) {
  if (!result) return null;
  const stale = state.testStale ? ' stale' : '';
  if (result.status === 'ok') {
    return h('span', { class: `pill ok${stale}`, title: 'Test run result' }, `${result.count ?? 0} item${result.count === 1 ? '' : 's'}`);
  }
  if (result.status === 'skipped') return h('span', { class: `pill info${stale}`, title: result.message }, 'skipped in test');
  return h('span', { class: `pill err${stale}`, title: result.message || '' }, 'test failed');
}

function renderPipeline() {
  const steps = state.flow.steps || [];
  const container = h('div', { class: 'pipeline', id: 'pipeline' });
  if (!steps.length) {
    const empty = h('div', {
      class: 'drop-empty',
      ondragover: (e) => { if (!drag) return; e.preventDefault(); empty.classList.add('over'); },
      ondragleave: () => empty.classList.remove('over'),
      ondrop: (e) => { e.preventDefault(); dropAt(0); },
    }, h('strong', {}, 'Drag the first action here'), h('span', { class: 'muted small' }, 'from the Actions list, or use “+ Add action” below.'));
    container.append(empty);
    return container;
  }
  container.append(dropZone(0, 'edge'));
  steps.forEach((step, index) => {
    if (index > 0) container.append(dropZone(index, 'between'));
    container.append(renderCard(step, index, steps.length));
  });
  container.append(dropZone(steps.length, 'edge'));
  return container;
}

/** Whether a drag event is over the lower half of an element. */
function inLowerHalf(e, el) {
  const box = el.getBoundingClientRect();
  return e.clientY > box.top + box.height / 2;
}

function renderCard(step, index, total) {
  const action = actionDef(step.module, step.action);
  const mod = moduleDef(step.module);
  const issues = issuesAt(state.issues, ['steps', index]);
  const errors = issues.filter((i) => i.level === 'error').length;
  const warnings = issues.length - errors;
  const instance = step.instance ? instanceById(step.instance) : instanceById(step.module);
  const needsSetup = mod && mod.fields.length > 0 && instance && instance.status !== 'valid';
  const card = h('div', {
    class: `card ${categoryClass(mod)}${index === state.stepIndex ? ' selected' : ''}${errors ? ' err' : warnings ? ' warn' : ''}`,
    draggable: 'true', tabindex: '0', role: 'button',
    'aria-label': `Step ${index + 1}: ${step.name || step.action}`,
    onclick: () => selectStep(index),
    onkeydown: (e) => {
      if (e.target !== card) return;
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectStep(index); }
      if (e.altKey && e.key === 'ArrowUp' && index > 0) { e.preventDefault(); moveStep(index, index - 1); }
      if (e.altKey && e.key === 'ArrowDown' && index < total - 1) { e.preventDefault(); moveStep(index, index + 1); }
      if (e.key === 'Delete') { e.preventDefault(); removeStep(index); }
    },
    ondragstart: (e) => { startDrag(e, { type: 'step', index }); card.classList.add('dragging'); },
    ondragend: endDrag,
    ondragover: (e) => {
      if (!drag) return;
      e.preventDefault();
      const after = inLowerHalf(e, card);
      card.classList.toggle('drop-after', after);
      card.classList.toggle('drop-before', !after);
    },
    ondragleave: () => card.classList.remove('drop-after', 'drop-before'),
    ondrop: (e) => {
      e.preventDefault();
      dropAt(index + (inLowerHalf(e, card) ? 1 : 0));
    },
  },
  h('span', { class: 'handle', title: 'Drag to reorder (or Alt+↑/↓)' }, '⋮⋮'),
  moduleBadge(mod),
  h('div', { class: 'card-body' },
    h('div', {}, h('span', { class: 'step-index' }, index + 1),
      h('span', { class: 'step-title' }, step.name || '(unnamed step)')),
    h('div', { class: 'step-sub' },
      `${mod ? mod.label : step.module || '?'} → ${action ? action.label : step.action || '?'}`,
      instance && !instance.default ? ` · ${instance.name}` : ''),
    h('div', { class: 'step-meta' },
      h('span', { class: 'pill' }, stepSummary(step, index) || 'no input'),
      action && action.destructive ? h('span', { class: 'pill warn' }, 'destructive') : null,
      step.config && step.config.kind === 'tv' ? h('span', { class: 'pill info' }, 'TV') : null,
      needsSetup ? h('button', {
        class: 'pill err as-button', title: `Configure ${mod.label}`,
        onclick: (e) => { e.stopPropagation(); openInstanceDialog(instance.id); },
      }, `set up ${instance.default ? mod.label : instance.name}`) : null,
      errors ? h('span', { class: 'pill err' }, `${errors} error${errors === 1 ? '' : 's'}`) : null,
      warnings ? h('span', { class: 'pill warn' }, `${warnings} warning${warnings === 1 ? '' : 's'}`) : null,
      resultPill(testResultFor(index)))),
  h('div', { class: 'card-actions' },
    h('button', { class: 'icon-btn', title: 'Test run up to this step', 'aria-label': 'Test run up to this step',
      disabled: state.testing, onclick: (e) => { e.stopPropagation(); runTest(index); } }, '▶'),
    h('button', { class: 'icon-btn', title: 'Duplicate step', 'aria-label': 'Duplicate step',
      onclick: (e) => { e.stopPropagation(); duplicateStep(index); } }, '⧉'),
    h('button', { class: 'icon-btn danger', title: 'Remove step', 'aria-label': 'Remove step',
      onclick: (e) => { e.stopPropagation(); removeStep(index); } }, '✕')));
  return card;
}

function moveStep(from, to) {
  const steps = state.flow.steps;
  if (from === to || to < 0 || to >= steps.length) return;
  const [step] = steps.splice(from, 1);
  steps.splice(to, 0, step);
  if (state.stepIndex === from) state.stepIndex = to;
  else if (state.stepIndex !== null) {
    if (from < state.stepIndex && to >= state.stepIndex) state.stepIndex -= 1;
    else if (from > state.stepIndex && to <= state.stepIndex) state.stepIndex += 1;
  }
  markDirty();
  render();
}

function removeStep(index) {
  const step = state.flow.steps[index];
  if (!window.confirm(`Remove step "${step.name || step.action}"?`)) return;
  state.flow.steps.splice(index, 1);
  if (state.stepIndex === index) state.stepIndex = null;
  else if (state.stepIndex > index) state.stepIndex -= 1;
  markDirty();
  render();
}

function selectStep(index) {
  state.stepIndex = index;
  render();
}

function uniqueStepName(base) {
  const names = new Set((state.flow.steps || []).map((step) => step.name));
  let name = base;
  let n = 2;
  while (names.has(name)) { name = `${base} ${n}`; n += 1; }
  return name;
}

function insertStep(moduleId, actionId, index) {
  const action = actionDef(moduleId, actionId);
  const steps = state.flow.steps || (state.flow.steps = []);
  const at = Math.max(0, Math.min(index ?? steps.length, steps.length));
  const step = { name: uniqueStepName(action.label), module: moduleId, action: actionId };
  if ((action.input === 'data' || action.input === 'data+query') && at > 0) step.input = 'previous';
  steps.splice(at, 0, step);
  state.stepIndex = at;
  markDirty();
  render();
  const mod = moduleDef(moduleId);
  if (moduleNeedsSetup(mod)) toast(`${mod.label} is not configured yet. Use “set up” on the card.`);
}

function duplicateStep(index) {
  const steps = state.flow.steps;
  const copy = clone(steps[index]);
  copy.name = uniqueStepName(`${steps[index].name || steps[index].action} copy`);
  steps.splice(index + 1, 0, copy);
  state.stepIndex = index + 1;
  markDirty();
  render();
}

function renameStepReferences(oldName, newName) {
  if (!oldName || oldName === newName) return;
  const fix = (value) => {
    if (value === `{{${oldName}}}`) return `{{${newName}}}`;
    if (value === oldName) return newName;
    return value;
  };
  for (const step of state.flow.steps) {
    if (typeof step.input === 'string') step.input = fix(step.input);
    else if (Array.isArray(step.input)) step.input = step.input.map(fix);
    else if (isObject(step.input)) {
      if (typeof step.input.data === 'string') step.input.data = fix(step.input.data);
      else if (Array.isArray(step.input.data)) step.input.data = step.input.data.map(fix);
    }
  }
}

/* ------------------------------------------------------------ step input */

const refName = (value) => (typeof value === 'string' && value.startsWith('{{') && value.endsWith('}}')
  ? value.slice(2, -2).trim() : null);

function parseSource(value) {
  if (value === undefined || value === null || value === '' || value === 'none') return { source: 'none' };
  if (value === 'previous') return { source: 'previous' };
  if (refName(value) !== null) return { source: 'step', step: refName(value) };
  if (Array.isArray(value) && value.every((item) => typeof item === 'string')) {
    return { source: 'merge', steps: value.map((item) => refName(item) ?? item) };
  }
  return null;
}

/** Split a step input into source, query and extra arguments for the form. */
function parseInput(input) {
  const plain = parseSource(input);
  if (plain) return { mode: 'form', ...plain, steps: plain.steps || [], query: undefined, args: {} };
  if (typeof input === 'string') return { mode: 'form', source: 'none', steps: [], query: input, args: {} };
  if (isObject(input)) {
    const source = 'data' in input ? parseSource(input.data) : { source: 'none' };
    if (source) {
      const args = {};
      for (const [key, value] of Object.entries(input)) if (key !== 'data' && key !== 'query') args[key] = value;
      return { mode: 'form', ...source, steps: source.steps || [], query: input.query, args };
    }
  }
  return { mode: 'custom' };
}

function buildInput(model) {
  let data;
  if (model.source === 'previous') data = 'previous';
  else if (model.source === 'step' && model.step) data = `{{${model.step}}}`;
  else if (model.source === 'merge' && model.steps.length) data = model.steps.slice();
  const hasQuery = !isEmpty(model.query);
  const hasArgs = !isEmpty(model.args);
  if (!hasQuery && !hasArgs) return data;
  if (typeof model.query === 'string' && data === undefined && !hasArgs) return model.query;
  const result = {};
  if (data !== undefined) result.data = data;
  if (hasQuery) result.query = model.query;
  Object.assign(result, model.args);
  return result;
}

/* ------------------------------------------------------------ side panel */

function renderSidePanel() {
  if (!state.flow) return h('div', { class: 'panel muted' }, 'Flow details appear here.');
  if (state.stepIndex !== null && state.flow.steps[state.stepIndex]) return renderStepEditor(state.stepIndex);
  return renderRuntimePanel();
}

function renderRuntimePanel() {
  const runtime = state.runtime;
  return h('div', {},
    h('div', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('h2', {}, 'Runtime'), h('span', { class: 'spacer' }),
        h('button', { class: 'btn small', disabled: !state.flowId, onclick: refreshRuntime }, 'Refresh')),
      !state.flowId ? h('div', { class: 'muted' }, 'Save the flow to run it.') :
        !runtime ? h('div', { class: 'muted' }, 'The web GUI runs without the flow runtime.') :
          !runtime.loaded ? h('div', { class: 'muted' }, 'Not loaded by the runtime yet.') :
            h('dl', { class: 'kv' },
              h('dt', {}, 'State'), h('dd', {}, runtime.running ? h('span', { class: 'pill info' }, 'running') : 'idle'),
              h('dt', {}, 'Last result'), h('dd', {}, runtime.last_status ? statusPill(runtime.last_status) : '—'),
              h('dt', {}, 'Last start'), h('dd', {}, fmtTime(runtime.last_start)),
              h('dt', {}, 'Last end'), h('dd', {}, fmtTime(runtime.last_end)),
              runtime.last_step ? [h('dt', {}, 'Last step'), h('dd', {}, runtime.last_step)] : null,
              runtime.last_error ? [h('dt', {}, 'Error'), h('dd', { class: 'field-issue error' }, runtime.last_error)] : null,
              h('dt', {}, 'Mode'), h('dd', {}, runtime.mode),
              runtime.next_due ? [h('dt', {}, 'Next run'), h('dd', {}, fmtTime(runtime.next_due))] : null)),
    h('div', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('h2', {}, 'Recent messages'), h('span', { class: 'spacer' }),
        h('button', { class: 'btn small', disabled: !state.flowId, onclick: loadLogs }, 'Reload')),
      h('div', { class: 'logs', id: 'logs' }, renderLogs())));
}

function renderLogs() {
  if (!state.logs.length) return h('div', { class: 'muted small' }, 'No messages since start.');
  return state.logs.slice().reverse().map((line) => h('div', { class: `log-line ${line.level}` },
    `${line.time.slice(11)} ${line.level.padEnd(7)} ${line.message}`));
}

async function loadLogs() {
  if (!state.flowId) return;
  try {
    state.logs = (await api('GET', `flows/${encodeURIComponent(state.flowId)}/logs`)).logs;
    const el = document.getElementById('logs');
    if (el) el.replaceChildren(...[renderLogs()].flat());
  } catch (err) { /* ignore */ }
}

async function refreshRuntime() {
  if (!state.flowId) return;
  try {
    const data = await api('GET', `flows/${encodeURIComponent(state.flowId)}`);
    state.runtime = data.runtime;
    await refreshFlows();
    await loadLogs();
    if (state.stepIndex === null) render();
  } catch (err) { /* ignore */ }
}

function renderStepEditor(index) {
  const step = state.flow.steps[index];
  const mod = moduleDef(step.module);
  const action = actionDef(step.module, step.action);
  const earlier = state.flow.steps.slice(0, index).map((item) => item.name).filter(Boolean);
  const stepIssues = issuesAt(state.issues, ['steps', index]);
  const at = (...path) => stepIssues.filter((issue) => issue.path.slice(2).join('.') === path.join('.'));
  const panel = h('div', { class: 'panel' });
  const rerender = () => { const side = panel.parentElement; if (side) side.replaceChildren(renderStepEditor(index)); };

  // header
  panel.append(h('div', { class: 'panel-head' },
    moduleBadge(mod), h('h2', {}, `Step ${index + 1}`), h('span', { class: 'spacer' }),
    h('button', { class: 'btn small', disabled: state.testing, title: 'Run the flow up to this step with real data, without side effects',
      onclick: () => runTest(index) }, '▶ Test to here'),
    h('button', { class: 'btn small ghost', onclick: () => { state.stepIndex = null; render(); } }, 'Close')));
  panel.append(h('div', { id: 'step-issues' }, issueList(stepIssues) || ''));

  // name, module, action, instance
  let nameBefore = step.name;
  panel.append(h('div', { class: 'form-grid' },
    h('div', { class: 'field wide' }, h('label', { for: 'step-name' }, 'Step name'),
      h('input', {
        id: 'step-name', type: 'text', value: step.name || '',
        oninput: (e) => { step.name = e.target.value; markDirty(); },
        onchange: (e) => { renameStepReferences(nameBefore, e.target.value); nameBefore = e.target.value; render(); },
      }),
      h('div', { class: 'hint' }, 'Later steps refer to this step by its name.'),
      fieldIssues(at('name'))),
    h('div', { class: 'field' }, h('span', { class: 'label' }, 'Module'), h('div', {}, mod ? mod.label : step.module)),
    h('div', { class: 'field' }, h('label', { for: 'step-action' }, 'Action'),
      (() => {
        const select = h('select', {
          id: 'step-action',
          onchange: (e) => { step.action = e.target.value; markDirty(); rerender(); },
        }, (mod ? mod.actions : []).map((item) => h('option', { value: item.id }, item.label)),
        action ? null : h('option', { value: step.action }, `${step.action} (undocumented)`));
        select.value = step.action;
        return select;
      })(),
      fieldIssues(at('action'))),
    renderInstanceSelect(step, mod, at('instance'), rerender)));
  if (action) panel.append(h('p', { class: 'muted small' }, action.description));

  // input
  panel.append(h('div', { class: 'section-title' }, 'Input'));
  panel.append(renderInputEditor(step, index, action, earlier, at, rerender));

  // action arguments
  const parsed = parseInput(step.input);
  if (action && action.arguments.length && parsed.mode === 'form') {
    panel.append(h('div', { class: 'section-title' }, 'Arguments'));
    panel.append(h('div', { class: 'form-grid' }, action.arguments.map((spec) => fieldInput(spec, parsed.args[spec.key], (value) => {
      const model = parseInput(step.input);
      if (value === undefined) delete model.args[spec.key]; else model.args[spec.key] = value;
      step.input = buildInput(model);
      if (step.input === undefined) delete step.input;
      markDirty();
    }, { issues: at('input', spec.key) }))));
  }

  // settings: action fields + overridable module fields
  if (mod) {
    const config = step.config || {};
    const base = step.instance ? (instanceById(step.instance) || {}).config || {} : (instanceById(step.module) || {}).config || {};
    const setConfig = (key, value) => {
      const next = clone(step.config) || {};
      setPath(next, key, value);
      if (isEmpty(next)) delete step.config; else step.config = next;
      markDirty();
    };
    const actionFields = action ? action.fields : [];
    const stepFields = mod.fields.filter((spec) => spec.step);
    if (actionFields.length || stepFields.length) {
      panel.append(h('div', { class: 'section-title' }, 'Step settings'));
      panel.append(h('div', { class: 'form-grid' },
        actionFields.map((spec) => fieldInput(spec, getPath(config, spec.key), (value) => setConfig(spec.key, value),
          { issues: at('config', spec.key) })),
        stepFields.map((spec) => {
          const inherited = getPath(base, spec.key);
          return fieldInput(spec, getPath(config, spec.key), (value) => setConfig(spec.key, value), {
            issues: at('config', spec.key),
            inherit: inherited !== undefined ? (Array.isArray(inherited) ? inherited.join(', ') : String(inherited))
              : spec.default !== null && spec.default !== undefined ? String(spec.default) : '',
          });
        })));
    }
    const known = new Set([...mod.fields, ...actionFields].map((spec) => spec.key.split('.')[0]));
    const other = Object.keys(config).filter((key) => !known.has(key));
    const moduleIssues = stepIssues.filter((issue) => issue.path[2] === 'config'
      && !actionFields.concat(stepFields).some((spec) => spec.key === issue.path.slice(3).join('.')));
    if (other.length || moduleIssues.length) {
      panel.append(h('details', { class: 'section', open: moduleIssues.length > 0 },
        h('summary', {}, 'Other settings'),
        h('p', { class: 'muted small' }, 'Settings without a form field, as JSON. Connection settings belong to the module instance.'),
        fieldIssues(moduleIssues),
        h('textarea', {
          class: 'code', value: JSON.stringify(Object.fromEntries(other.map((key) => [key, config[key]])), null, 2),
          onchange: (e) => {
            try {
              const extra = e.target.value.trim() ? JSON.parse(e.target.value) : {};
              const next = clone(step.config) || {};
              other.forEach((key) => delete next[key]);
              Object.assign(next, extra);
              if (isEmpty(next)) delete step.config; else step.config = next;
              markDirty();
            } catch (err) { toast('Invalid JSON in other settings.', 'err'); }
          },
        })));
    }
  }
  return panel;
}

function renderInstanceSelect(step, mod, issues, rerender) {
  if (!mod || !mod.fields.length) return null;
  const options = state.instances.filter((item) => item.module === step.module);
  const current = step.instance ? instanceById(step.instance) : instanceById(step.module);
  const select = h('select', {
    id: 'step-instance',
    onchange: (e) => {
      if (e.target.value === '__new__') {
        e.target.value = step.instance || '';
        createInstance(mod, (id) => { step.instance = id; markDirty(); render(); });
        return;
      }
      if (e.target.value === '' || e.target.value === step.module) delete step.instance;
      else step.instance = e.target.value;
      markDirty();
      rerender();
    },
  }, options.map((item) => h('option', {
    value: item.default ? '' : item.id,
    disabled: !item.default && item.status !== 'valid',
  }, `${item.name}${item.status !== 'valid' ? ` (${item.status})` : ''}`)),
  h('option', { value: '__new__' }, '+ New instance…'));
  select.value = step.instance || '';
  const ready = current && current.status === 'valid';
  return h('div', { class: 'field wide' }, h('label', { for: 'step-instance' }, 'Connection'),
    h('div', { class: 'input-group' }, select,
      current ? h('button', { class: 'btn', type: 'button', onclick: () => openInstanceDialog(current.id) }, 'Configure') : null),
    current ? h('div', { class: `connection-state ${ready ? 'ok' : 'err'}` },
      statusPill(current.status),
      current.test ? h('span', { class: `pill ${current.test.ok ? 'ok' : 'err'}` }, current.test.ok ? 'connected' : 'test failed') : null,
      h('span', { class: 'small' }, ready ? `Uses ${current.name}.` : `${current.name} needs settings before this step can run.`)) : null,
    fieldIssues(issues));
}

function renderInputEditor(step, index, action, earlier, at, rerender) {
  const model = parseInput(step.input);
  const wrap = h('div', { class: 'form-grid' });
  const commit = (next) => {
    const value = buildInput(next);
    if (value === undefined) delete step.input; else step.input = value;
    markDirty();
  };
  if (model.mode === 'custom') {
    wrap.append(h('div', { class: 'field wide' }, h('label', {}, 'Custom input (JSON)'),
      h('textarea', {
        class: 'code', value: JSON.stringify(step.input, null, 2),
        onchange: (e) => {
          try { step.input = JSON.parse(e.target.value); markDirty(); rerender(); } catch (err) { toast('Invalid JSON input.', 'err'); }
        },
      }),
      h('div', { class: 'hint' }, 'This input shape has no form. Edit it as JSON.'),
      fieldIssues(at('input'))));
    return wrap;
  }
  const takesData = !action || action.input === 'data' || action.input === 'data+query';
  const takesQuery = !action || action.input === 'query' || action.input === 'data+query';

  if (takesData || model.source !== 'none') {
    const source = h('select', {
      id: 'input-source',
      onchange: (e) => {
        model.source = e.target.value;
        if (model.source === 'step' && !model.step) model.step = earlier[earlier.length - 1];
        if (model.source === 'merge' && !model.steps.length) model.steps = earlier.slice(-2);
        commit(model);
        rerender();
      },
    },
    h('option', { value: 'none' }, 'No items'),
    h('option', { value: 'previous', disabled: index === 0 }, 'Previous step'),
    h('option', { value: 'step', disabled: !earlier.length }, 'A specific earlier step'),
    h('option', { value: 'merge', disabled: earlier.length < 1 }, 'Merge several steps'));
    source.value = model.source;
    wrap.append(h('div', { class: 'field wide' }, h('label', { for: 'input-source' }, 'Items from'), source,
      fieldIssues(at('input').concat(at('input', 'data')))));
    if (model.source === 'step') {
      const select = h('select', { onchange: (e) => { model.step = e.target.value; commit(model); } },
        earlier.map((name) => h('option', { value: name }, name)),
        model.step && !earlier.includes(model.step) ? h('option', { value: model.step }, `${model.step} (missing)`) : null);
      select.value = model.step || '';
      wrap.append(h('div', { class: 'field wide' }, h('label', {}, 'Step'), select));
    }
    if (model.source === 'merge') {
      wrap.append(h('div', { class: 'field wide' }, h('span', { class: 'label' }, 'Steps to merge'),
        earlier.map((name) => h('label', { class: 'check' }, h('input', {
          type: 'checkbox', checked: model.steps.includes(name),
          onchange: (e) => {
            model.steps = earlier.filter((item) => (item === name ? e.target.checked : model.steps.includes(item)));
            commit(model);
          },
        }), name))));
    }
  }

  if (takesQuery) {
    const queryFields = action ? action.query : [];
    const queryObj = isObject(model.query) ? model.query : {};
    if (typeof model.query === 'string' || !queryFields.length) {
      wrap.append(h('div', { class: 'field wide' }, h('label', { for: 'query-text' }, 'Search text'),
        h('input', {
          id: 'query-text', type: 'text', value: typeof model.query === 'string' ? model.query : '',
          placeholder: 'optional',
          oninput: (e) => { model.query = e.target.value || undefined; commit(model); },
        }),
        fieldIssues(at('input', 'query'))));
    }
    if (queryFields.length && typeof model.query !== 'string') {
      wrap.append(h('div', { class: 'field wide' }, h('span', { class: 'label' }, 'Query')));
      queryFields.forEach((spec) => {
        wrap.append(fieldInput(spec, queryObj[spec.key], (value) => {
          const next = isObject(model.query) ? { ...model.query } : {};
          if (value === undefined) delete next[spec.key]; else next[spec.key] = value;
          model.query = isEmpty(next) ? undefined : next;
          commit(model);
        }, { issues: at('input', 'query', spec.key), placeholder: '' }));
      });
      const known = new Set(queryFields.map((spec) => spec.key));
      const extra = Object.fromEntries(Object.entries(queryObj).filter(([key]) => !known.has(key)));
      wrap.append(h('details', { class: 'section wide', open: !isEmpty(extra) },
        h('summary', {}, 'Additional query parameters'),
        h('textarea', {
          class: 'code', value: isEmpty(extra) ? '' : JSON.stringify(extra, null, 2), placeholder: '{"key": "value"}',
          onchange: (e) => {
            try {
              const parsed = e.target.value.trim() ? JSON.parse(e.target.value) : {};
              const next = Object.fromEntries(Object.entries(queryObj).filter(([key]) => known.has(key)));
              Object.assign(next, parsed);
              model.query = isEmpty(next) ? undefined : next;
              commit(model);
            } catch (err) { toast('Invalid JSON in query parameters.', 'err'); }
          },
        })));
    }
  }
  if (!wrap.children.length) wrap.append(h('div', { class: 'muted small wide' }, 'This action takes no input.'));
  return wrap;
}

/* -------------------------------------------------------------- test runs */

async function runTest(until) {
  if (!state.flow || !(state.flow.steps || []).length || state.testing) return;
  state.testing = true;
  state.testUntil = until;
  state.test = null;
  state.testStale = false;
  render();
  document.getElementById('test-panel')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  try {
    state.test = await api('POST', 'flows/test', { flow: state.flow, id: state.flowId || undefined, until });
    const last = state.test.steps[state.test.steps.length - 1];
    state.testStep = last ? last.index : null;
    toast(state.test.status === 'success' ? 'Test run finished.' : `Test run ${state.test.status}.`,
      state.test.status === 'success' ? 'ok' : 'err');
  } catch (err) {
    if (err.issues && err.issues.length) state.issues = err.issues;
    toast(err.message, 'err');
  } finally {
    state.testing = false;
    render();
  }
}

const PREVIEW_COLUMNS = ['poster', 'title', 'year', 'season', 'episode', 'kind', 'tmdbid', 'imdbid',
  'resolution', 'seeders', 'size', 'torrent', 'link'];

function cellValue(key, value) {
  if (value === null || value === undefined) return '';
  if (key === 'poster' && typeof value === 'string' && value.startsWith('https://image.tmdb.org/')) {
    return h('img', { class: 'thumb', src: value.replace('/original/', '/w92/'), alt: '', loading: 'lazy' });
  }
  if (key === 'size' && typeof value === 'number') return `${value.toFixed(1)} GB`;
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function renderItemsTable(result) {
  if (!result.items.length) {
    return h('p', { class: 'muted small' }, result.count === null ? 'No output.' : 'No items.');
  }
  const keys = new Set();
  result.items.forEach((item) => Object.keys(item).forEach((key) => keys.add(key)));
  const columns = PREVIEW_COLUMNS.filter((key) => keys.has(key))
    .concat([...keys].filter((key) => !PREVIEW_COLUMNS.includes(key))).slice(0, 12);
  return h('div', {},
    h('p', { class: 'muted small' }, `Showing ${result.items.length} of ${result.count} item${result.count === 1 ? '' : 's'}.`),
    h('div', { class: 'table-wrap' }, h('table', { class: 'items' },
      h('thead', {}, h('tr', {}, columns.map((key) => h('th', {}, key === 'poster' ? '' : key)))),
      h('tbody', {}, result.items.map((item) => h('tr', {},
        columns.map((key) => h('td', { class: `col-${key}` }, cellValue(key, item[key])))))))));
}

function renderTestPanel() {
  if (!state.testing && !state.test) return null;
  const test = state.test;
  const selected = test ? test.steps.find((item) => item.index === state.testStep) : null;
  return h('div', { class: 'panel test-panel', id: 'test-panel' },
    h('div', { class: 'panel-head' }, h('h2', {}, 'Test run'),
      test ? statusPill(test.status) : h('span', { class: 'pill info' }, 'running…'),
      state.testStale ? h('span', { class: 'pill warn' }, 'flow changed since') : null,
      h('span', { class: 'spacer' }),
      h('button', { class: 'btn small', disabled: state.testing, onclick: () => runTest(state.testUntil) }, 'Run again'),
      h('button', { class: 'btn small ghost', disabled: state.testing, onclick: () => { state.test = null; render(); } }, 'Close')),
    h('p', { class: 'muted small' }, 'Reads real data from your services. Actions that change anything (downloads, library files) are skipped and pass their input on.'),
    state.testing ? h('div', { class: 'spinner-row' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), 'Running the steps…') : null,
    test && test.message ? h('p', { class: 'field-issue error' }, test.message) : null,
    test ? h('div', { class: 'test-steps' }, test.steps.map((item) => h('button', {
      class: `test-step${item.index === state.testStep ? ' active' : ''}`,
      onclick: () => { state.testStep = item.index; const panel = document.getElementById('test-panel'); if (panel) panel.replaceWith(renderTestPanel()); },
    },
    h('span', { class: 'step-index' }, item.index + 1),
    h('span', { class: 'grow' }, item.name || '(unnamed)'),
    resultPill(item),
    h('span', { class: 'muted small' }, `${item.duration}s`)))) : null,
    selected && selected.message ? h('p', { class: `field-issue ${selected.status === 'failed' ? 'error' : 'warning'}` }, selected.message) : null,
    selected ? renderItemsTable(selected) : null,
    test && test.logs.length ? h('details', { class: 'section' }, h('summary', {}, `Messages (${test.logs.length})`),
      h('div', { class: 'logs' }, test.logs.slice().reverse().map((line) => h('div', { class: `log-line ${line.level}` },
        `${line.time.slice(11)} ${line.level.padEnd(7)} ${line.message}`)))) : null);
}

/* --------------------------------------------------------- flow actions */

async function saveFlow(asDraft = false) {
  if (asDraft === true) state.flow.enabled = false;
  try {
    let result;
    if (state.flowId) {
      result = await api('PUT', `flows/${encodeURIComponent(state.flowId)}`, { flow: state.flow, revision: state.revision });
    } else {
      result = await api('POST', 'flows', { flow: state.flow });
    }
    state.dirty = false;
    toast('Flow saved.', 'ok');
    await refreshFlows();
    const keepStep = state.stepIndex;
    state.dirty = false;
    await selectFlow(result.id);
    state.stepIndex = keepStep;
    render();
  } catch (err) {
    if (err.issues && err.issues.length) {
      state.issues = err.issues;
      render();
    }
    if (err.status === 422 && state.flow.enabled !== false) {
      if (window.confirm(`${err.message}\n\nSave it disabled as a draft now?`)) saveFlow(true);
    } else {
      toast(err.message, 'err');
    }
  }
}

async function runFlow() {
  try {
    await api('POST', `flows/${encodeURIComponent(state.flowId)}/run`);
    toast('Flow started.', 'ok');
    setTimeout(refreshRuntime, 800);
  } catch (err) { toast(err.message, 'err'); }
}

async function exportFlow() {
  try {
    const data = await api('GET', `flows/${encodeURIComponent(state.flowId)}/yaml`);
    download(data.filename, data.yaml);
  } catch (err) { toast(err.message, 'err'); }
}

async function deleteFlow() {
  if (!window.confirm(`Delete flow "${state.flow.name}"? A backup copy is kept.`)) return;
  try {
    await api('DELETE', `flows/${encodeURIComponent(state.flowId)}`);
    state.flowId = null; state.flow = null; state.dirty = false; state.stepIndex = null;
    await refreshFlows();
    toast('Flow deleted.', 'ok');
    render();
  } catch (err) { toast(err.message, 'err'); }
}

/* ----------------------------------------------------------------- dialogs */

function openDialog(title, body, footer) {
  const dialog = document.getElementById('dialog');
  dialog.replaceChildren(
    h('div', { class: 'dialog-head' }, h('h2', {}, title),
      h('button', { class: 'btn ghost', 'aria-label': 'Close', onclick: () => dialog.close() }, '✕')),
    h('div', { class: 'dialog-body' }, body),
    ...(footer ? [h('div', { class: 'dialog-foot' }, footer)] : []));
  if (!dialog.open) dialog.showModal();
  return dialog;
}

function openCatalogDialog(index) {
  const filter = h('input', { type: 'text', placeholder: 'Search actions…', class: 'search' });
  const grid = h('div', { class: 'catalog' });
  const draw = () => {
    const term = filter.value.trim().toLowerCase();
    grid.replaceChildren(...state.catalog.map((mod) => {
      const actions = mod.actions.filter((action) => !term || `${mod.label} ${action.label} ${action.description}`.toLowerCase().includes(term));
      if (!actions.length) return null;
      return h('div', { class: 'catalog-module' },
        h('h3', {}, mod.label), h('div', { class: 'muted small' }, mod.description),
        actions.map((action) => h('button', {
          class: 'catalog-action',
          onclick: () => { document.getElementById('dialog').close(); insertStep(mod.id, action.id, index ?? state.flow.steps.length); },
        }, h('div', { class: 'name' }, action.label, action.destructive ? ' ⚠' : ''), h('div', { class: 'desc' }, action.description))));
    }).filter(Boolean));
  };
  filter.addEventListener('input', draw);
  draw();
  openDialog(index === undefined ? 'Add action' : `Insert action at position ${index + 1}`, h('div', {}, h('div', { class: 'field' }, filter), h('div', { class: 'section-gap' }), grid));
  filter.focus();
}

function openImportDialog() {
  const text = h('textarea', { class: 'code', rows: 16, placeholder: 'name: My flow\nsteps:\n  - name: ...' });
  const file = h('input', { type: 'file', accept: '.yaml,.yml,text/yaml', onchange: async (e) => {
    const [selected] = e.target.files;
    if (selected) text.value = await selected.text();
  } });
  const issues = h('div', {});
  const submit = async (asDraft) => {
    try {
      const result = await api('POST', 'flows/import', { yaml: text.value, as_draft: asDraft });
      document.getElementById('dialog').close();
      toast(result.enabled === false ? 'Imported as a disabled draft.' : 'Flow imported.', 'ok');
      await refreshFlows();
      selectFlow(result.id);
    } catch (err) {
      issues.replaceChildren(h('p', { class: 'field-issue error' }, err.message), issueList(err.issues) || '');
    }
  };
  openDialog('Import flow from YAML', h('div', {},
    h('div', { class: 'field' }, h('label', {}, 'YAML file'), file),
    h('div', { class: 'field' }, h('label', {}, 'or paste YAML'), text), issues),
  [h('button', { class: 'btn', onclick: () => submit(true) }, 'Import as draft'),
    h('button', { class: 'btn primary', onclick: () => submit(false) }, 'Import')]);
}

/* ================================================================ MODULES */

function renderModulesView() {
  const grid = h('div', { class: 'module-grid' }, state.catalog.map((mod) => {
    const instances = state.instances.filter((item) => item.module === mod.id);
    return h('div', { class: `panel module-card ${categoryClass(mod)}` },
      h('div', { class: 'module-head' }, moduleBadge(mod),
        h('div', { class: 'grow' }, h('div', { class: 'category' }, mod.category), h('h3', {}, mod.label))),
      h('div', { class: 'muted small' }, mod.description),
      mod.fields.length ? h('div', { class: 'list' }, instances.map((item) => h('div', { class: 'instance-line' },
        h('button', {
          class: `instance-row${item.id === state.instanceId ? ' active' : ''}`,
          onclick: () => selectInstance(item.id),
        }, h('span', { class: 'name' }, item.name), statusPill(item.status),
        item.test ? h('span', { class: `pill ${item.test.ok ? 'ok' : 'err'}`, title: item.test.message },
          item.test.ok ? 'connected' : 'test failed') : null),
        mod.connection_test ? h('button', {
          class: 'icon-btn', title: `Test ${item.name}`, 'aria-label': `Test ${item.name}`,
          disabled: item.status !== 'valid', onclick: () => quickTest(item.id),
        }, '⚡') : null)))
        : h('div', { class: 'muted small' }, 'No settings needed.'),
      mod.fields.length ? h('div', {}, h('button', { class: 'btn small', onclick: () => createInstance(mod) }, '+ New connection')) : null,
      h('details', { class: 'small' }, h('summary', { class: 'muted' }, `${mod.actions.length} action${mod.actions.length === 1 ? '' : 's'}`),
        h('ul', { class: 'action-list' }, mod.actions.map((action) => h('li', {}, h('strong', {}, action.label), ' — ', action.description)))));
  }));
  const configured = state.instances.filter((item) => item.status === 'valid').length;
  const head = h('div', { class: 'panel modules-head' },
    h('div', { class: 'grow' }, h('h2', {}, 'Modules'),
      h('p', { class: 'muted small' }, `${configured} ready connection${configured === 1 ? '' : 's'}. `,
        'A module default is used by every step that picks no other connection; add more connections to talk to several servers of the same kind.')),
    h('button', { class: 'btn primary', onclick: (e) => testAllInstances(e.currentTarget) }, 'Test all connections'));
  return h('div', {}, head, h('div', { class: 'layout-modules' }, h('section', {}, grid),
    h('aside', { class: 'side-panel' }, renderInstanceEditor())));
}

function loadInstanceDraft(id) {
  const item = instanceById(id);
  state.instanceId = id;
  state.instanceDraft = item ? { name: item.name, config: clone(item.config) || {}, clear: [] } : null;
  state.instanceIssues = item ? item.issues : [];
}

function selectInstance(id) {
  loadInstanceDraft(id);
  refreshInstanceView();
}

/** Re-render the instance editor wherever it is shown, and the page behind it. */
function refreshInstanceView() {
  const body = document.getElementById('instance-dialog-body');
  if (state.instanceDialog && body) body.replaceChildren(renderInstanceEditor(true));
  render();
}

function openInstanceDialog(id) {
  const item = instanceById(id);
  if (!item) return;
  loadInstanceDraft(id);
  state.instanceDialog = true;
  const dialog = openDialog(`${(moduleDef(item.module) || {}).label || item.module} settings`,
    h('div', { id: 'instance-dialog-body' }, renderInstanceEditor(true)));
  dialog.addEventListener('close', () => {
    state.instanceDialog = false;
    if (state.flow) scheduleValidation();
  }, { once: true });
}

async function createInstance(mod, onCreated) {
  const name = window.prompt(`Name of the new ${mod.label} connection`, `Home ${mod.label}`);
  if (!name) return;
  try {
    const created = await api('POST', 'instances', { module: mod.id, name });
    await refreshInstances();
    toast('Connection created. Fill in its settings.', 'ok');
    if (onCreated) onCreated(created.id);
    if (state.view === 'flows') openInstanceDialog(created.id);
    else selectInstance(created.id);
  } catch (err) { toast(err.message, 'err'); }
}

async function testAllInstances(button) {
  if (button) { button.disabled = true; button.textContent = 'Testing…'; }
  try {
    const { results } = await api('POST', 'instances/test-all');
    Object.entries(results).forEach(([id, result]) => { const item = instanceById(id); if (item) item.test = result; });
    const failed = Object.values(results).filter((result) => !result.ok).length;
    const total = Object.keys(results).length;
    toast(total ? `${total - failed} of ${total} complete connections work.` : 'No complete connections to test yet.', failed ? 'err' : 'ok');
  } catch (err) { toast(err.message, 'err'); }
  render();
}

async function quickTest(id) {
  try {
    const result = await api('POST', `instances/${encodeURIComponent(id)}/test`);
    instanceById(id).test = result;
    toast(result.message, result.ok ? 'ok' : 'err');
  } catch (err) { toast(err.message, 'err'); }
  render();
}

function instancePayload() {
  const draft = state.instanceDraft;
  const config = clone(draft.config) || {};
  draft.clear.forEach((key) => { config[key] = ''; });
  return { name: draft.name, config };
}

function renderInstanceEditor(inDialog = false) {
  const item = instanceById(state.instanceId);
  if (!item || !state.instanceDraft) {
    return h('div', { class: 'panel muted' }, 'Select a module instance to edit its settings. A module default applies to every step without an instance; named instances let you connect to several servers of the same kind.');
  }
  const mod = moduleDef(item.module);
  const draft = state.instanceDraft;
  const issues = state.instanceIssues || [];
  const prefix = item.default ? [item.id] : ['instances', item.id, 'config'];
  const at = (key) => issues.filter((issue) => issue.path.slice(prefix.length).join('.') === key
    && prefix.every((part, i) => issue.path[i] === part));
  const panel = h('div', { class: inDialog ? 'instance-editor' : 'panel instance-editor' });
  const set = (key, value) => { setPath(draft.config, key, value); };
  const basic = mod.fields.filter((spec) => !spec.advanced);
  const advanced = mod.fields.filter((spec) => spec.advanced);
  const renderSpec = (spec) => {
    const secretSet = spec.type === 'secret' && item.secrets.includes(spec.key) && !draft.clear.includes(spec.key);
    return fieldInput(spec, getPath(draft.config, spec.key), (value) => set(spec.key, value), {
      issues: at(spec.key),
      secretSet,
      extra: spec.type === 'secret' && item.secrets.includes(spec.key) ? h('label', { class: 'check small' },
        h('input', { type: 'checkbox', checked: draft.clear.includes(spec.key), onchange: (e) => {
          draft.clear = e.target.checked ? [...draft.clear, spec.key] : draft.clear.filter((key) => key !== spec.key);
        } }), 'Clear stored value') : null,
    });
  };
  panel.append(...[
    h('div', { class: 'panel-head' }, moduleBadge(mod), h('h2', {}, item.name), h('span', { class: 'spacer' }), statusPill(item.status)),
    h('p', { class: 'muted small' }, item.default
      ? `Default ${mod.label} settings (the "${item.id}" section of config.yaml). Named instances inherit them.`
      : `Named ${mod.label} instance "${item.id}". Empty fields inherit the module default.`),
    item.default ? null : h('div', { class: 'field' }, h('label', { for: 'inst-name' }, 'Name'),
      h('input', { id: 'inst-name', type: 'text', value: draft.name, oninput: (e) => { draft.name = e.target.value; } })),
    h('div', { class: 'form-grid' }, basic.map(renderSpec)),
    advanced.length ? h('details', { class: 'section' }, h('summary', {}, 'Advanced'),
      h('div', { class: 'form-grid' }, advanced.map(renderSpec))) : null,
    h('div', { class: 'section-gap' }),
    issueList(issues.filter((issue) => !mod.fields.some((spec) => at(spec.key).includes(issue)))) || '',
    item.test ? h('div', { class: `issue ${item.test.ok ? '' : 'error'}` },
      h('span', { class: `pill ${item.test.ok ? 'ok' : 'err'}` }, item.test.ok ? 'connected' : 'failed'), ' ', item.test.message) : null,
    h('div', { class: 'btn-row section-gap' },
      h('button', { class: 'btn primary', onclick: saveInstance }, 'Save'),
      h('button', { class: 'btn', onclick: validateInstance }, 'Validate'),
      mod.connection_test ? h('button', { class: 'btn', onclick: testInstance }, 'Test connection') : null,
      item.default ? null : h('button', { class: 'btn danger', onclick: deleteInstance }, 'Delete'),
      inDialog ? h('button', { class: 'btn ghost', onclick: () => document.getElementById('dialog').close() }, 'Close') : null),
  ].filter((child) => child !== null && child !== undefined && child !== ''));
  return panel;
}

async function validateInstance() {
  try {
    const result = await api('POST', `instances/${encodeURIComponent(state.instanceId)}/validate`, instancePayload());
    state.instanceIssues = result.issues;
    toast(`Settings are ${result.status}.`, result.status === 'valid' ? 'ok' : 'err');
    refreshInstanceView();
  } catch (err) { toast(err.message, 'err'); }
}

async function testInstance() {
  try {
    const result = await api('POST', `instances/${encodeURIComponent(state.instanceId)}/test`, instancePayload());
    const item = instanceById(state.instanceId);
    item.test = result;
    toast(result.message, result.ok ? 'ok' : 'err');
    refreshInstanceView();
  } catch (err) { toast(err.message, 'err'); }
}

async function saveInstance() {
  try {
    const result = await api('PUT', `instances/${encodeURIComponent(state.instanceId)}`, instancePayload());
    await refreshInstances();
    toast(`Saved. Settings are ${result.status}.`, result.status === 'valid' ? 'ok' : '');
    selectInstance(result.id);
    if (state.flow) scheduleValidation();
  } catch (err) {
    state.instanceIssues = err.issues;
    toast(err.message, 'err');
    refreshInstanceView();
  }
}

async function deleteInstance() {
  const item = instanceById(state.instanceId);
  if (!window.confirm(`Delete instance "${item.name}"?`)) return;
  try {
    await api('DELETE', `instances/${encodeURIComponent(state.instanceId)}`);
    state.instanceId = null; state.instanceDraft = null;
    if (state.instanceDialog) document.getElementById('dialog').close();
    await refreshInstances();
    toast('Instance deleted.', 'ok');
    refreshInstanceView();
  } catch (err) { toast(err.message, 'err'); }
}

/* =============================================================== SETTINGS */

async function loadSettings() {
  try {
    [state.settings, state.report] = await Promise.all([api('GET', 'settings'), api('GET', 'validate')]);
    if (state.view === 'settings') render();
  } catch (err) { toast(err.message, 'err'); }
}

function renderSettingsView() {
  const settings = state.settings;
  const report = state.report;
  if (!settings) return h('div', { class: 'panel muted' }, 'Loading…');
  const mode = h('select', { id: 'exec-mode' }, settings.modes.map((item) => h('option', { value: item }, item)));
  mode.value = settings.execution;
  const flowNames = Object.fromEntries(state.flows.map((flow) => [flow.id, flow.name]));
  return h('div', {},
    h('div', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('h2', {}, 'Runtime')),
      h('div', { class: 'form-grid' },
        h('div', { class: 'field' }, h('label', { for: 'exec-mode' }, 'Execution mode'), mode,
          h('div', { class: 'hint' }, 'parallel: one worker per flow · sequential: due flows run one at a time by priority.'))),
      settings.restart_required ? h('p', { class: 'field-issue warning' }, `Restart CineFlow to switch from ${settings.execution_effective} to ${settings.execution} mode.`) : null,
      h('div', { class: 'btn-row section-gap' },
        h('button', { class: 'btn primary', onclick: async () => {
          try { state.settings = await api('PUT', 'settings', { execution: mode.value }); toast('Saved.', 'ok'); render(); } catch (err) { toast(err.message, 'err'); }
        } }, 'Save'))),
    h('div', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('h2', {}, 'Validation'), h('span', { class: 'spacer' }),
        h('button', { class: 'btn small', onclick: loadSettings }, 'Re-run')),
      report ? h('div', {},
        h('h3', {}, 'config.yaml ', report.config.some((i) => i.level === 'error') ? h('span', { class: 'pill err' }, 'errors') : h('span', { class: 'pill ok' }, 'ok')),
        issueList(report.config) || '',
        Object.entries(report.flows).map(([id, issues]) => h('div', { class: 'section-gap' },
          h('h3', {}, `${flowNames[id] || id} `, issues.some((i) => i.level === 'error') ? h('span', { class: 'pill err' }, 'errors') : h('span', { class: 'pill ok' }, 'ok')),
          issueList(issues) || ''))) : null),
    h('div', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('h2', {}, 'Export')),
      h('p', { class: 'muted' }, 'Download config.yaml without secrets. Every save keeps the previous file version in the .backups folder of the configuration directory.'),
      h('button', { class: 'btn', onclick: async () => {
        try { const data = await api('GET', 'config/export'); download(data.filename, data.yaml); } catch (err) { toast(err.message, 'err'); }
      } }, 'Export config.yaml')));
}

/* ------------------------------------------------------------------ start */

async function start() {
  document.querySelectorAll('.tab').forEach((tab) => tab.addEventListener('click', () => setView(tab.dataset.view)));
  window.addEventListener('beforeunload', (e) => { if (state.dirty) { e.preventDefault(); e.returnValue = ''; } });
  window.addEventListener('dragend', endDrag);
  try {
    state.auth = await api('GET', 'auth/status');
  } catch (err) {
    document.getElementById('app').replaceChildren(h('div', { class: 'panel' }, `Cannot reach the CineFlow API: ${err.message}`));
    return;
  }
  if (state.auth.enabled && !state.auth.authenticated) {
    renderLogin();
    return;
  }
  document.body.classList.remove('signed-out');
  try {
    await loadBasics();
  } catch (err) {
    document.getElementById('app').replaceChildren(h('div', { class: 'panel' }, `Cannot reach the CineFlow API: ${err.message}`));
    return;
  }
  let view = 'flows';
  try { view = localStorage.getItem('cineflow.view') || 'flows'; } catch (e) { /* storage unavailable */ }
  setView(['flows', 'modules', 'settings'].includes(view) ? view : 'flows');
  if (state.flows.length) selectFlow(state.flows[0].id);
  setInterval(() => {
    if (state.view === 'flows' && state.flowId && !state.dirty && state.stepIndex === null) refreshRuntime();
  }, 10000);
}

start();
