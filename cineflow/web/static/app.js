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
  stepIndex: null,      // selected step
  instanceId: null,     // selected instance in the modules view
  instanceDraft: null,
  instanceIssues: [],
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

/** Fields the GUI shows; hidden ones are only kept when written in YAML. */
const visible = (specs) => (specs || []).filter((spec) => !spec.hidden);

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

function switchControl(id, checked, onChange) {
  return h('span', { class: 'switch' },
    h('input', { id, type: 'checkbox', role: 'switch', checked, onchange: (e) => onChange(e.target.checked) }),
    h('span', { class: 'slider', 'aria-hidden': 'true' }));
}

function switchField(id, label, checked, onChange, hint, extra) {
  return h('div', { class: 'field switch-field' },
    h('div', { class: 'switch-row' }, h('label', { for: id }, label), switchControl(id, checked, onChange)),
    hint ? h('div', { class: 'hint' }, hint) : null, extra || null);
}

const SVG_NS = 'http://www.w3.org/2000/svg';

/** Eye icon for showing a masked value; crossed out while the value is shown. */
function eyeIcon(crossed) {
  const paths = ['M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z', 'M12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6z'];
  return strokeIcon(crossed ? [...paths, 'M4 4l16 16'] : paths);
}

/** Small stroke icon; ``paths`` are SVG path definitions on a 24x24 grid. */
function strokeIcon(paths) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  paths.forEach((d) => {
    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('d', d);
    svg.append(path);
  });
  return svg;
}

/**
 * Word list editor: type a word on the left and press Enter (or the arrow) to add it
 * to the labels on the right. Labels can be dragged into another order and removed with ×.
 */
function wordListInput(spec, value, onChange, id, inheritText) {
  let items = Array.isArray(value) ? value.slice() : [];
  const numeric = spec.key.endsWith('_ids');
  const label = spec.label || spec.key;
  const emptyText = inheritText
    || (Array.isArray(spec.default) && spec.default.length ? `default: ${spec.default.join(', ')}` : 'No values yet');
  const chips = h('ul', { class: 'word-chips', 'aria-label': label });
  let dragFrom = null;

  const commit = () => {
    onChange(items.length ? items.slice() : undefined);
    draw();
  };
  const move = (from, to) => {
    if (to < 0 || to >= items.length || from === to) return;
    const [item] = items.splice(from, 1);
    items.splice(to, 0, item);
    commit();
  };
  const clearMarks = () => chips.querySelectorAll('.drop-before, .drop-after')
    .forEach((el) => el.classList.remove('drop-before', 'drop-after'));

  function draw(focusIndex) {
    chips.replaceChildren(...(items.length ? items.map((item, index) => {
      const chip = h('li', {
        class: 'word-chip', draggable: 'true', tabindex: '0',
        title: 'Drag to reorder. Alt+arrow keys move, Delete removes.',
        ondragstart: (e) => {
          dragFrom = index;
          chip.classList.add('dragging');
          e.dataTransfer.effectAllowed = 'move';
          e.dataTransfer.setData('text/plain', String(item));
        },
        ondragend: () => { dragFrom = null; chip.classList.remove('dragging'); clearMarks(); },
        ondragover: (e) => {
          if (dragFrom === null) return;
          e.preventDefault();
          const box = chip.getBoundingClientRect();
          const after = e.clientX > box.left + box.width / 2;
          clearMarks();
          chip.classList.add(after ? 'drop-after' : 'drop-before');
        },
        ondrop: (e) => {
          if (dragFrom === null) return;
          e.preventDefault();
          const box = chip.getBoundingClientRect();
          let to = index + (e.clientX > box.left + box.width / 2 ? 1 : 0);
          if (dragFrom < to) to -= 1;
          const from = dragFrom;
          dragFrom = null;
          move(from, to);
        },
        onkeydown: (e) => {
          if (e.key === 'Delete' || e.key === 'Backspace') {
            e.preventDefault();
            items.splice(index, 1);
            commit();
            focusChip(Math.min(index, items.length - 1));
          } else if (e.altKey && (e.key === 'ArrowLeft' || e.key === 'ArrowUp')) {
            e.preventDefault();
            move(index, index - 1);
            focusChip(Math.max(index - 1, 0));
          } else if (e.altKey && (e.key === 'ArrowRight' || e.key === 'ArrowDown')) {
            e.preventDefault();
            move(index, index + 1);
            focusChip(Math.min(index + 1, items.length - 1));
          }
        },
      },
      h('span', { class: 'word-text' }, String(item)),
      h('button', {
        type: 'button', class: 'word-remove', title: `Remove ${item}`, 'aria-label': `Remove ${item}`,
        onclick: () => { items.splice(index, 1); commit(); },
      }, strokeIcon(['M6 6l12 12', 'M18 6L6 18'])));
      return chip;
    }) : [h('li', { class: 'word-empty' }, emptyText)]));
    if (focusIndex !== undefined) focusChip(focusIndex);
  }
  function focusChip(index) {
    const chip = chips.children[index];
    if (chip && chip.classList.contains('word-chip')) chip.focus();
  }

  const input = h('input', {
    id, type: 'text', autocomplete: 'off', placeholder: numeric ? 'Type an ID and press Enter' : 'Type a word and press Enter',
    onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } },
    oninput: () => input.setCustomValidity(''),
  });
  function add() {
    const raw = input.value.trim();
    if (!raw) return;
    const word = numeric && /^-?\d+$/.test(raw) ? Number(raw) : raw;
    if (items.some((item) => String(item).toLowerCase() === String(word).toLowerCase())) {
      input.setCustomValidity('Already in the list');
      input.reportValidity();
      return;
    }
    items.push(word);
    input.value = '';
    commit();
    input.focus();
  }
  draw();
  return h('div', { class: 'word-list' },
    h('div', { class: 'word-entry' }, input,
      h('button', { type: 'button', class: 'word-add', title: 'Add', 'aria-label': `Add to ${label}`, onclick: add },
        strokeIcon(['M5 12h14', 'M13 6l6 6-6 6']))),
    chips);
}

/** Render an input for a field definition. ``onChange`` receives the parsed value or undefined. */
function fieldInput(spec, value, onChange, opts = {}) {
  const id = `f-${Math.random().toString(36).slice(2)}`;
  const inherit = opts.inherit;
  const inheritText = inherit ? `inherit (${inherit})` : 'inherit';
  const placeholder = opts.placeholder !== undefined ? opts.placeholder
    : (spec.default !== null && spec.default !== undefined && !Array.isArray(spec.default) ? `default: ${spec.default}` : '');
  let control;
  const type = spec.type;
  if (type === 'boolean' && opts.switch) {
    // a yes/no switch; the default value is stored as "not set"
    const fallback = spec.default === true;
    const issues = opts.issues || [];
    return h('div', { class: `field switch-field${issues.some((i) => i.level === 'error') ? ' has-error' : ''}${opts.wide ? ' wide' : ''}` },
      h('div', { class: 'switch-row' }, h('label', { for: id }, spec.label || spec.key),
        switchControl(id, typeof value === 'boolean' ? value : fallback,
          (checked) => onChange(checked === fallback ? undefined : checked))),
      spec.description ? h('div', { class: 'hint' }, spec.description) : null,
      opts.extra || null,
      fieldIssues(issues));
  }
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
  } else if (type === 'list' && spec.item_type !== 'object'
      && !(Array.isArray(value) && value.some((item) => item !== null && typeof item === 'object'))) {
    control = wordListInput(spec, value, onChange, id, inherit !== undefined ? inheritText : '');
  } else if (type === 'list' || type === 'object') {
    const structured = type === 'object' || spec.item_type === 'object'
      || (Array.isArray(value) && value.some((item) => typeof item === 'object'));
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
    // eye icon inside the field shows or hides the value
    const input = control;
    const toggle = h('button', {
      class: 'reveal', type: 'button', title: 'Show value', 'aria-label': 'Show value', 'aria-pressed': 'false',
      onclick: () => {
        const shown = input.type === 'password';
        input.type = shown ? 'text' : 'password';
        toggle.title = shown ? 'Hide value' : 'Show value';
        toggle.setAttribute('aria-label', toggle.title);
        toggle.setAttribute('aria-pressed', String(shown));
        toggle.replaceChildren(eyeIcon(shown));
      },
    }, eyeIcon(false));
    control = h('div', { class: 'secret-input' }, input, toggle);
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
  state.flowSettings = catalog.flow_settings || [];
  state.exportDir = catalog.export_directory || '';
  state.instances = instances.instances;
  state.flows = flows.flows;
  state.health = health;
  renderRuntimeStatus();
}

async function refreshFlows() {
  state.flows = (await api('GET', 'flows')).flows;
}

async function refreshInstances() {
  // keep the last connection test results; the list itself does not carry them
  const tests = Object.fromEntries(state.instances.map((item) => [item.id, item.test]));
  state.instances = (await api('GET', 'instances')).instances;
  state.instances.forEach((item) => { if (tests[item.id] && !item.test) item.test = tests[item.id]; });
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
  if (view === 'modules') checkModules();
}

function render() {
  renderSubnav();
  const app = document.getElementById('app');
  app.replaceChildren();
  if (state.view === 'flows') app.append(renderFlowsView());
  else app.append(renderModulesView());
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

const MEDIA_KINDS = [['movie', 'Movies'], ['tv', 'TV series']];

/* ------------------------------------------------------------- sub menu */

function flowDot(flow) {
  let kind = 'ok';
  let title = 'Enabled';
  if (flow.runtime && flow.runtime.running) { kind = 'info'; title = 'Running'; }
  else if (flow.status === 'invalid') { kind = 'err'; title = `${flow.errors} error${flow.errors === 1 ? '' : 's'}`; }
  else if (flow.enabled === false) { kind = 'off'; title = 'Disabled'; }
  return h('span', { class: `dot ${kind}`, title, 'aria-hidden': 'true' });
}

function renderSubnav() {
  const nav = document.getElementById('subnav');
  const show = state.view === 'flows' && !document.body.classList.contains('signed-out');
  nav.hidden = !show;
  document.body.classList.toggle('has-subnav', show);
  if (!show) { nav.replaceChildren(); return; }
  nav.replaceChildren(
    ...state.flows.map((flow) => {
      const active = flow.id === state.flowId;
      const name = (active && state.flow && state.flow.name) || flow.name;
      return h('button', {
        type: 'button', class: `subtab${active ? ' active' : ''}`, title: name,
        'aria-current': active ? 'page' : undefined, onclick: () => selectFlow(flow.id),
      }, flowDot(flow), h('span', { class: 'subtab-name' }, name),
      active && state.dirty ? h('span', { class: 'dirty-mark', title: 'Unsaved changes' }, '•') : null);
    }),
    h('button', {
      type: 'button', class: 'subtab add', title: 'New flow', 'aria-label': 'New flow', onclick: openNewFlowDialog,
    }, '+'));
}

function openNewFlowDialog() {
  if (state.dirty && !window.confirm('Discard unsaved flow changes?')) return;
  const name = h('input', { id: 'new-flow-name', type: 'text', placeholder: 'e.g. Trending movies', autocomplete: 'off' });
  const desc = h('input', { id: 'new-flow-desc', type: 'text', placeholder: 'optional', autocomplete: 'off' });
  const kind = h('select', { id: 'new-flow-kind' }, MEDIA_KINDS.map(([value, label]) => h('option', { value }, label)));
  const delay = h('input', { id: 'new-flow-delay', type: 'number', min: 1, step: 1, value: 60 });
  const error = h('div', { class: 'field-issue error', role: 'alert' });
  const create = async () => {
    if (!name.value.trim()) { error.textContent = 'A name is required.'; name.focus(); return; }
    const flow = {
      name: name.value.trim(), enabled: false, delay: Number(delay.value) || 60, priority: 10, kind: kind.value, steps: [],
    };
    if (desc.value.trim()) flow.description = desc.value.trim();
    try {
      const result = await api('POST', 'flows', { flow });
      document.getElementById('dialog').close();
      state.dirty = false;
      await refreshFlows();
      await selectFlow(result.id);
      toast('Flow created. Add steps from the Actions list.', 'ok');
    } catch (err) { error.textContent = err.message; }
  };
  const body = h('div', {
    class: 'form-grid',
    onkeydown: (e) => { if (e.key === 'Enter' && e.target.tagName === 'INPUT') { e.preventDefault(); create(); } },
  },
  h('div', { class: 'field wide' }, h('label', { for: 'new-flow-name' }, 'Name', h('span', { class: 'req' }, ' *')), name),
  h('div', { class: 'field wide' }, h('label', { for: 'new-flow-desc' }, 'Description'), desc),
  h('div', { class: 'field' }, h('label', { for: 'new-flow-kind' }, 'Media kind'), kind),
  h('div', { class: 'field' }, h('label', { for: 'new-flow-delay' }, 'Run every (minutes)'), delay),
  h('div', { class: 'wide hint muted small' }, 'The flow starts disabled. Enable it once its steps are ready.'),
  h('div', { class: 'wide' }, error));
  openDialog('New flow', body, [
    h('button', { class: 'btn ghost', onclick: openImportDialog }, 'Import YAML…'),
    h('span', { class: 'spacer' }),
    h('button', { class: 'btn', onclick: () => document.getElementById('dialog').close() }, 'Cancel'),
    h('button', { class: 'btn primary', onclick: create }, 'Create'),
  ], { narrow: true });
  name.focus();
}

/* ------------------------------------------------------------ flow page */

function renderFlowsView() {
  if (!state.flow) {
    return h('div', { class: 'panel empty' }, state.flows.length ? 'Select a flow in the menu above.'
      : h('div', {}, h('p', {}, 'No flows yet.'), h('button', { class: 'btn primary', onclick: openNewFlowDialog }, '+ New flow')));
  }
  return h('div', {},
    renderFlowHeader(),
    h('div', { class: 'layout-flows' },
      h('div', { class: 'left-col' }, renderSchedule(), renderFlowSettings(), renderPalette()),
      h('section', { class: 'steps-col' }, renderSteps(), renderTestPanel()),
      h('aside', { class: 'side-panel' }, renderSidePanel())));
}

function updateFlow(key, value) {
  if (value === undefined) delete state.flow[key]; else state.flow[key] = value;
  markDirty();
}

function renderKindSwitch() {
  const current = state.flow.kind || 'movie';
  const wrap = h('div', {
    class: 'segmented', role: 'radiogroup', 'aria-label': 'Media kind', title: 'Media kind of every step in this flow',
  });
  MEDIA_KINDS.forEach(([value, label]) => wrap.append(h('button', {
    type: 'button', role: 'radio', 'aria-checked': String(current === value), class: current === value ? 'active' : '',
    onclick: () => {
      if (state.flow.kind === value) return;
      updateFlow('kind', value);
      wrap.replaceWith(renderKindSwitch());
      // the default library folder follows the media kind
      const card = document.getElementById('flow-settings');
      if (card) card.replaceWith(renderFlowSettings());
    },
  }, label)));
  return wrap;
}

function renderFlowHeader() {
  const flow = state.flow;
  const runtime = state.runtime || {};
  return h('div', { class: 'panel flow-head' },
    h('div', { class: 'flow-title-row' },
      h('div', { class: 'flow-titles' },
        h('input', {
          class: 'title-input', id: 'flow-name', type: 'text', value: flow.name || '', placeholder: 'Flow name',
          'aria-label': 'Flow name', autocomplete: 'off', spellcheck: 'false',
          oninput: (e) => { updateFlow('name', e.target.value); renderSubnav(); },
        }),
        h('div', { dataset: { issuePath: 'name' } }),
        h('input', {
          class: 'desc-input', id: 'flow-desc', type: 'text', value: flow.description || '',
          placeholder: 'Add a description…', 'aria-label': 'Description', autocomplete: 'off',
          oninput: (e) => updateFlow('description', e.target.value.trim() ? e.target.value : undefined),
        })),
      h('div', { class: 'flow-tools' },
        renderKindSwitch(),
        h('div', { class: 'btn-row' },
          h('button', { class: 'btn primary', id: 'save-flow', onclick: saveFlow }, state.dirty ? 'Save *' : 'Save'),
          h('button', {
            class: 'btn', disabled: state.testing || !(flow.steps || []).length,
            title: 'Run every step with real data but without side effects', onclick: () => runTest(undefined),
          }, state.testing ? 'Testing…' : 'Test run'),
          h('button', {
            class: 'btn', id: 'run-flow', disabled: !state.flowId || state.dirty || !(state.health && state.health.runtime),
            title: state.dirty ? 'Save the flow first' : 'Run the flow once now', onclick: runFlow,
          }, runtime.running ? 'Running…' : 'Run now'),
          h('button', { class: 'btn', disabled: !state.flowId, onclick: exportFlow }, 'Export YAML'),
          h('button', { class: 'btn danger', disabled: !state.flowId, onclick: deleteFlow }, 'Delete')))),
    h('div', { id: 'flow-issues' }, renderFlowIssueSummary()));
}

function renderSchedule() {
  const flow = state.flow;
  return h('div', { class: 'panel' },
    h('div', { class: 'panel-head' }, h('h2', {}, 'Schedule')),
    h('div', { class: 'stack' },
      switchField('flow-enabled', 'Enabled', flow.enabled !== false, (checked) => { updateFlow('enabled', checked); renderSubnav(); },
        'Only flows without errors can be enabled.'),
      h('div', { class: 'field' }, h('label', { for: 'flow-delay' }, 'Run every (minutes)'),
        h('input', {
          id: 'flow-delay', type: 'number', min: 1, step: 1, value: flow.delay ?? 60,
          oninput: (e) => updateFlow('delay', e.target.value === '' ? undefined : Number(e.target.value)),
        }),
        h('div', { dataset: { issuePath: 'delay' } })),
      h('div', { class: 'field' }, h('label', { for: 'flow-priority' }, 'Priority'),
        h('input', {
          id: 'flow-priority', type: 'number', step: 1, value: flow.priority ?? 99,
          oninput: (e) => updateFlow('priority', e.target.value === '' ? undefined : Number(e.target.value)),
        }),
        h('div', { class: 'hint' }, 'Lower runs first in sequential mode.'),
        h('div', { dataset: { issuePath: 'priority' } }))));
}

/** Flow settings handed to the modules that use them; shown only when a step needs them. */
function renderFlowSettings() {
  const flow = state.flow;
  const used = (setting) => (flow.steps || []).some((step) => isObject(step) && setting.modules.includes(step.module))
    || !isEmpty(flow[setting.key]);
  const settings = (state.flowSettings || []).filter(used);
  if (!settings.length) return h('div', { id: 'flow-settings', hidden: true });
  const fields = settings.map((setting) => {
    const spec = setting.field;
    const issueSlot = h('div', { dataset: { issuePath: setting.key } });
    if (spec.type === 'path') {
      const root = state.exportDir ? `${state.exportDir.replace(/\/+$/, '')}/` : '';
      // a long export path shows only its last folder in front of the input
      const shortRoot = root.length > 20 ? `…/${root.split('/').filter(Boolean).pop()}/` : root;
      const where = h('div', { class: 'hint' });
      const showWhere = () => {
        const folder = flow[setting.key] || (setting.kind_default ? (flow.kind || 'movie') : '');
        where.textContent = `Items are created in ${root}${folder}.`;
      };
      const input = h('input', {
        id: `flow-${setting.key}`, type: 'text', autocomplete: 'off', value: flow[setting.key] || '',
        placeholder: setting.kind_default ? (flow.kind || 'movie') : '',
        oninput: (e) => { updateFlow(setting.key, e.target.value.trim() || undefined); showWhere(); },
      });
      showWhere();
      return h('div', { class: 'field' },
        h('label', { for: input.id }, spec.label),
        h('div', { class: 'prefix-input', title: `Export directory: ${root || 'not known'} (EXPORT_DIRECTORY, set at installation)` },
          shortRoot ? h('span', { class: 'prefix' }, shortRoot) : null, input),
        where, issueSlot);
    }
    const field = fieldInput(spec, flow[setting.key], (value) => updateFlow(setting.key, value), {});
    field.classList.remove('wide');
    field.append(issueSlot);
    return field;
  });
  return h('div', { class: 'panel', id: 'flow-settings' },
    h('div', { class: 'panel-head' }, h('h2', {}, 'Library & releases')),
    h('div', { class: 'stack' }, fields));
}

function renderPalette() {
  const panel = h('div', { class: 'panel palette' },
    h('div', { class: 'panel-head' }, h('h2', {}, 'Actions')),
    h('p', { class: 'muted small' }, 'Open a module, then drag an action into the flow or click it to append.'));
  const list = h('div', { class: 'palette-list' });
  state.catalog.forEach((mod) => {
    const open = state.openModule === mod.id;
    list.append(h('div', { class: `palette-group ${categoryClass(mod)}${open ? ' open' : ''}` },
      h('div', { class: 'palette-row' },
        h('button', {
          type: 'button', class: 'palette-module', 'aria-expanded': String(open),
          onclick: () => { state.openModule = open ? null : mod.id; panel.replaceWith(renderPalette()); },
        }, moduleBadge(mod), h('span', { class: 'grow' }, mod.label), h('span', { class: 'chev', 'aria-hidden': 'true' }, '›')),
        moduleNeedsSetup(mod) ? h('button', {
          class: 'pill warn as-button', title: `Configure ${mod.label}`, onclick: () => openInstanceDialog(mod.id),
        }, 'set up') : null),
      open ? h('div', { class: 'palette-actions' }, mod.actions.map((action) => h('div', {
        class: `chip ${categoryClass(mod)}`, draggable: 'true', tabindex: '0', role: 'button',
        title: `${action.description}\nDrag into the flow, or click to append.`,
        ondragstart: (e) => startDrag(e, { type: 'action', module: mod.id, action: action.id }),
        ondragend: endDrag,
        onclick: () => insertStep(mod.id, action.id, state.flow.steps.length),
        onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click(); } },
      }, h('span', { class: 'grow' }, action.label),
      action.side_effects ? h('span', { class: 'chip-flag', title: 'Changes external state; skipped in test runs' }, '⚡') : null))) : null));
  });
  panel.append(list);
  return panel;
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
    if (id !== state.testFlowId) state.test = null;
    state.testFlowId = id;
    try { localStorage.setItem('cineflow.flow', id); } catch (e) { /* storage unavailable */ }
    render();
  } catch (err) {
    toast(err.message, 'err');
  }
}

function markDirty() {
  const wasDirty = state.dirty;
  state.dirty = true;
  if (state.test) state.testStale = true;
  if (!wasDirty) renderSubnav();
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
  const run = document.getElementById('run-flow');
  if (run && state.dirty) { run.disabled = true; run.title = 'Save the flow first'; }
}

function renderFlowIssueSummary() {
  const errors = state.issues.filter((i) => i.level === 'error').length;
  const warnings = state.issues.filter((i) => i.level === 'warning').length;
  const flowLevel = state.issues.filter((i) => (i.path[0] !== 'steps' || i.path.length === 1)
    && !['name', 'delay', 'priority'].includes(String(i.path[0])));
  return h('div', {},
    h('div', { class: 'btn-row' },
      errors ? h('span', { class: 'pill err' }, `${errors} error${errors === 1 ? '' : 's'}`) : h('span', { class: 'pill ok' }, 'valid'),
      warnings ? h('span', { class: 'pill warn' }, `${warnings} warning${warnings === 1 ? '' : 's'}`) : null,
      state.dirty ? h('span', { class: 'pill info' }, 'unsaved') : null),
    flowLevel.length ? h('div', { class: 'small section-gap' }, issueList(flowLevel)) : null);
}

function renderSteps() {
  return h('div', { class: 'panel' },
    h('div', { class: 'panel-head' }, h('h2', {}, 'Steps'), h('span', { class: 'spacer' }),
      h('span', { class: 'muted small' }, 'Drag to reorder · click to configure')),
    renderPipeline(),
    h('button', { class: 'add-step', onclick: () => openCatalogDialog() }, '+ Add action'));
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
  state.stepIndex = state.stepIndex === index ? null : index;
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

/** Collapsed section for options a regular user rarely needs; open when one is in use. */
function moreOptions(children, open, extraClass = '') {
  if (!children.length) return null;
  return h('details', { class: `section more-options ${extraClass}`, open },
    h('summary', {}, 'More options'), h('div', { class: 'form-grid' }, children));
}

/** Basic fields in a grid, advanced ones in a collapsed "More options" section. */
function fieldGroup(allSpecs, render, inUse) {
  const specs = visible(allSpecs);
  const advanced = specs.filter((spec) => spec.advanced);
  return [
    h('div', { class: 'form-grid' }, specs.filter((spec) => !spec.advanced).map(render)),
    moreOptions(advanced.map(render), advanced.some(inUse)),
  ];
}

function renderSidePanel() {
  if (state.stepIndex !== null && state.flow.steps[state.stepIndex]) return renderStepEditor(state.stepIndex);
  return h('div', { class: 'panel muted small' }, 'Select a step to edit its settings.');
}

async function refreshRuntime() {
  if (!state.flowId) return;
  try {
    const data = await api('GET', `flows/${encodeURIComponent(state.flowId)}`);
    state.runtime = data.runtime;
    await refreshFlows();
    renderSubnav();
    const run = document.getElementById('run-flow');
    if (run && !state.dirty) run.textContent = state.runtime && state.runtime.running ? 'Running…' : 'Run now';
  } catch (err) { /* ignore */ }
}

/** Coloured module label: green when the step's module can be used. */
function moduleIndicator(step, mod) {
  const instance = step.instance ? instanceById(step.instance) : instanceById(step.module);
  const configurable = Boolean(mod && mod.fields.length);
  const ready = Boolean(mod) && (!configurable || Boolean(instance && instance.status === 'valid'));
  const label = mod ? mod.label : step.module || '?';
  let title = `${label} is ready. Click to open its settings.`;
  if (!mod) title = 'Unknown module';
  else if (!configurable) title = `${label} needs no settings.`;
  else if (!ready) title = `${label} needs settings before this step can run. Click to configure.`;
  const content = [h('span', { class: 'dot', 'aria-hidden': 'true' }), label,
    instance && !instance.default ? ` · ${instance.name}` : ''];
  const cls = `module-indicator ${ready ? 'ok' : 'err'}`;
  if (configurable && instance) {
    return h('button', { type: 'button', class: cls, title, onclick: () => openInstanceDialog(instance.id) }, content);
  }
  return h('span', { class: cls, title }, content);
}

function settingText(value) {
  if (Array.isArray(value)) return value.join(', ');
  if (isObject(value)) return JSON.stringify(value);
  return String(value);
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

  // header: the module indicator replaces the old test and close buttons
  panel.append(h('div', { class: 'panel-head' },
    h('h2', {}, `Step ${index + 1}`), h('span', { class: 'spacer' }), moduleIndicator(step, mod)));
  panel.append(h('div', { id: 'step-issues' }, issueList(stepIssues) || ''));

  // name, action
  let nameBefore = step.name;
  panel.append(h('div', { class: 'form-grid' },
    h('div', { class: 'field wide' }, h('label', { for: 'step-name' }, 'Name'),
      h('input', {
        id: 'step-name', type: 'text', value: step.name || '',
        oninput: (e) => { step.name = e.target.value; markDirty(); },
        onchange: (e) => { renameStepReferences(nameBefore, e.target.value); nameBefore = e.target.value; render(); },
      }),
      h('div', { class: 'hint' }, 'Later steps refer to this step by its name.'),
      fieldIssues(at('name'))),
    h('div', { class: 'field wide' }, h('label', { for: 'step-action' }, 'Action'),
      (() => {
        const select = h('select', {
          id: 'step-action',
          onchange: (e) => { step.action = e.target.value; markDirty(); rerender(); },
        }, (mod ? mod.actions : []).map((item) => h('option', { value: item.id }, item.label)),
        action ? null : h('option', { value: step.action }, `${step.action} (undocumented)`));
        select.value = step.action;
        return select;
      })(),
      action ? h('div', { class: 'hint' }, action.description) : null,
      fieldIssues(at('action')))));

  // input
  panel.append(h('div', { class: 'section-title' }, 'Input'));
  panel.append(renderInputEditor(step, index, action, earlier, at, rerender));

  // action arguments
  const parsed = parseInput(step.input);
  if (action && action.arguments.length && parsed.mode === 'form') {
    panel.append(h('div', { class: 'section-title' }, 'Arguments'));
    panel.append(...fieldGroup(action.arguments, (spec) => fieldInput(spec, parsed.args[spec.key], (value) => {
      const model = parseInput(step.input);
      if (value === undefined) delete model.args[spec.key]; else model.args[spec.key] = value;
      step.input = buildInput(model);
      if (step.input === undefined) delete step.input;
      markDirty();
    }, { issues: at('input', spec.key), switch: true }),
    (spec) => parsed.args[spec.key] !== undefined || at('input', spec.key).length > 0).filter(Boolean));
  }

  if (mod) panel.append(...renderStepSettings(step, mod, action, stepIssues, at, rerender));
  return panel;
}

/** Action settings, plus module settings the step still overrides (set, or needed). */
function renderStepSettings(step, mod, action, stepIssues, at, rerender) {
  const parts = [];
  const config = step.config || {};
  const setConfig = (key, value) => {
    const next = clone(step.config) || {};
    setPath(next, key, value);
    if (isEmpty(next)) delete step.config; else step.config = next;
    markDirty();
  };
  const actionFields = action ? action.fields : [];
  if (actionFields.length) {
    parts.push(h('div', { class: 'section-title' }, 'Settings'));
    parts.push(...fieldGroup(actionFields, (spec) => fieldInput(spec, getPath(config, spec.key),
      (value) => setConfig(spec.key, value), { issues: at('config', spec.key), switch: true }),
    (spec) => getPath(config, spec.key) !== undefined || at('config', spec.key).length > 0).filter(Boolean));
  }
  // module settings live in the module; show only those this step sets or must set
  // (credentials and other module-only fields are fixed in the module settings)
  const overrides = visible(mod.fields).filter((spec) => getPath(config, spec.key) !== undefined
    || (spec.step && spec.type !== 'secret' && at('config', spec.key).length));
  if (overrides.length || step.instance) {
    parts.push(h('div', { class: 'section-title' }, 'Module settings on this step'));
    parts.push(h('p', { class: 'muted small' }, 'Module settings belong to the module. Remove a value here to use the module.'));
    if (step.instance) {
      const instance = instanceById(step.instance);
      parts.push(h('div', { class: 'override-row' },
        h('span', { class: 'grow' }, h('strong', {}, 'Connection: '), instance ? instance.name : `${step.instance} (missing)`),
        h('button', { class: 'btn small', onclick: () => { delete step.instance; markDirty(); rerender(); } }, 'Use module')));
    }
    parts.push(h('div', { class: 'form-grid' }, overrides.map((spec) => {
      const set = getPath(config, spec.key) !== undefined;
      return fieldInput(spec, getPath(config, spec.key), (value) => setConfig(spec.key, value), {
        issues: at('config', spec.key),
        switch: true,
        wide: true,
        extra: set ? h('button', {
          class: 'btn small ghost remove-override', title: `Use the module value instead of ${settingText(getPath(config, spec.key))}`,
          onclick: () => { setConfig(spec.key, undefined); rerender(); },
        }, 'Use module value') : null,
      });
    })));
  }
  const known = new Set([...mod.fields, ...actionFields].map((spec) => spec.key.split('.')[0]));
  const other = Object.keys(config).filter((key) => !known.has(key));
  // module field issues are listed at the top and fixed in the module settings
  const shown = new Set([...actionFields, ...mod.fields].map((spec) => spec.key));
  const otherIssues = stepIssues.filter((issue) => issue.path[2] === 'config' && !shown.has(issue.path.slice(3).join('.')));
  if (other.length || otherIssues.length) {
    parts.push(h('details', { class: 'section', open: otherIssues.length > 0 },
      h('summary', {}, 'Other settings'),
      h('p', { class: 'muted small' }, 'Settings without a form field, as JSON.'),
      fieldIssues(otherIssues),
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
  return parts;
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
    const queryFields = action ? visible(action.query) : [];
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
      const queryInput = (spec) => fieldInput(spec, queryObj[spec.key], (value) => {
        const next = isObject(model.query) ? { ...model.query } : {};
        if (value === undefined) delete next[spec.key]; else next[spec.key] = value;
        model.query = isEmpty(next) ? undefined : next;
        commit(model);
      }, { issues: at('input', 'query', spec.key), placeholder: '', switch: true });
      const basic = queryFields.filter((spec) => !spec.advanced);
      if (basic.length) wrap.append(h('div', { class: 'field wide' }, h('span', { class: 'label' }, 'Filters')));
      basic.forEach((spec) => wrap.append(queryInput(spec)));
      const known = new Set(queryFields.map((spec) => spec.key));
      const extra = Object.fromEntries(Object.entries(queryObj).filter(([key]) => !known.has(key)));
      const advanced = queryFields.filter((spec) => spec.advanced);
      const raw = h('div', { class: 'field wide' }, h('label', {}, 'Other parameters (JSON)'),
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
        }));
      wrap.append(moreOptions(advanced.map(queryInput).concat(raw),
        !isEmpty(extra) || advanced.some((spec) => queryObj[spec.key] !== undefined
          || at('input', 'query', spec.key).length), 'wide'));
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
    if (state.flows.length) await selectFlow(state.flows[0].id); else render();
  } catch (err) { toast(err.message, 'err'); }
}

/* ----------------------------------------------------------------- dialogs */

function openDialog(title, body, footer, opts = {}) {
  const dialog = document.getElementById('dialog');
  dialog.classList.toggle('narrow', Boolean(opts.narrow));
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

const MODULE_CHECK_INTERVAL = 60000;

/** State badge of a module: ready, incomplete, invalid or unreachable. */
function moduleState(mod, instance) {
  if (!mod.fields.length) return { kind: 'ok', label: 'ready', title: 'No settings needed.' };
  if (!instance || instance.status === 'incomplete') {
    return { kind: 'warn', label: 'incomplete', title: 'Some required settings are missing.' };
  }
  if (instance.status !== 'valid') return { kind: 'err', label: 'invalid', title: 'Some settings have wrong values.' };
  if (instance.test && !instance.test.ok) return { kind: 'err', label: 'unreachable', title: instance.test.message };
  return { kind: 'ok', label: 'ready', title: instance.test ? instance.test.message : 'Settings are complete.' };
}

function renderModuleGrid() {
  // modules without settings (such as Tools) have nothing to show here
  const modules = state.catalog.filter((mod) => mod.fields.length);
  return h('div', { class: 'module-grid', id: 'module-grid' }, modules.map((mod) => {
    const instances = state.instances.filter((item) => item.module === mod.id);
    const main = instances.find((item) => item.default) || instances[0];
    const extra = instances.filter((item) => item !== main);
    const selected = instances.some((item) => item.id === state.instanceId);
    const badge = moduleState(mod, main);
    const clickable = Boolean(mod.fields.length && main);
    return h('div', {
      class: `panel module-card ${categoryClass(mod)}${selected ? ' selected' : ''}${clickable ? ' clickable' : ''}`,
      role: clickable ? 'button' : undefined, tabindex: clickable ? '0' : undefined,
      'aria-label': clickable ? `${mod.label} settings` : undefined,
      onclick: clickable ? () => selectInstance(main.id) : undefined,
      onkeydown: clickable ? (e) => {
        if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); selectInstance(main.id); }
      } : undefined,
    },
    h('div', { class: 'module-head' }, moduleBadge(mod),
      h('div', { class: 'grow' }, h('div', { class: 'category' }, mod.category), h('h3', {}, mod.label)),
      h('span', { class: `pill ${badge.kind}`, title: badge.title }, badge.label)),
    h('div', { class: 'muted small module-desc' }, mod.description),
    // extra named connections (instances: in config.yaml)
    extra.length ? h('div', { class: 'list' }, extra.map((item) => {
      const itemState = moduleState(mod, item);
      return h('button', {
        class: `instance-row${item.id === state.instanceId ? ' active' : ''}`,
        onclick: (e) => { e.stopPropagation(); selectInstance(item.id); },
      }, h('span', { class: 'name' }, item.name), h('span', { class: `pill ${itemState.kind}`, title: itemState.title }, itemState.label));
    })) : null);
  }));
}

function renderModulesView() {
  return h('div', {},
    h('h1', { class: 'page-title' }, 'Modules'),
    h('div', { class: 'layout-modules' }, renderModuleGrid(),
      h('aside', { class: 'side-panel' }, renderInstanceEditor())));
}

let moduleCheckRunning = false;
/** Refresh the module states and test every complete connection, without touching the open editor. */
async function checkModules() {
  if (moduleCheckRunning) return;
  moduleCheckRunning = true;
  try {
    await refreshInstances();
    const { results } = await api('POST', 'instances/test-all');
    Object.entries(results).forEach(([id, result]) => { const item = instanceById(id); if (item) item.test = result; });
  } catch (err) { /* the next check tries again */ }
  moduleCheckRunning = false;
  const grid = document.getElementById('module-grid');
  if (grid && state.view === 'modules') grid.replaceWith(renderModuleGrid());
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

function instancePayload() {
  const draft = state.instanceDraft;
  const config = clone(draft.config) || {};
  draft.clear.forEach((key) => { config[key] = ''; });
  return { name: draft.name, config };
}

function renderInstanceEditor(inDialog = false) {
  const item = instanceById(state.instanceId);
  if (!item || !state.instanceDraft) {
    return h('div', { class: 'panel muted' }, 'Select a connection to edit its settings.');
  }
  const mod = moduleDef(item.module);
  const draft = state.instanceDraft;
  const issues = state.instanceIssues || [];
  const prefix = item.default ? [item.id] : ['instances', item.id, 'config'];
  const at = (key) => issues.filter((issue) => issue.path.slice(prefix.length).join('.') === key
    && prefix.every((part, i) => issue.path[i] === part));
  const panel = h('div', { class: inDialog ? 'instance-editor' : 'panel instance-editor' });
  const set = (key, value) => { setPath(draft.config, key, value); };
  // connection first, then other short fields and switches; word lists take a full row and come last
  const isConnection = (spec) => ['url', 'secret'].includes(spec.type) || ['username', 'password'].includes(spec.key);
  const rank = (spec) => {
    if (['list', 'object'].includes(spec.type)) return 3;  // full-row lists always last
    if (spec.type === 'url') return 0;            // address first,
    if (spec.key === 'username') return 1;        // then the user name
    if (spec.key === 'password') return 1.5;      // with its password right after it
    return 2;                                     // then keys and other short fields
  };
  const ordered = (specs) => specs.map((spec, i) => [spec, i])
    .sort(([a, i], [b, j]) => rank(a) - rank(b) || i - j).map(([spec]) => spec);
  const basic = visible(mod.fields).filter((spec) => !spec.advanced);
  const advanced = ordered(visible(mod.fields).filter((spec) => spec.advanced));
  // short fields and switches sit side by side in two equal columns
  const main = [...ordered(basic.filter(isConnection)), ...ordered(basic.filter((spec) => !isConnection(spec)))]
    .sort((a, b) => (rank(a) >= 3) - (rank(b) >= 3));
  // keep the user name and password in one row: if the user name would start in the
  // right column, the next short field moves up beside the URL (or the URL takes the row)
  const wide = new Set();
  const userAt = main.findIndex((spec) => spec.key === 'username');
  if (userAt > 0 && userAt % 2 === 1 && main[userAt + 1]?.key === 'password') {
    const next = main.findIndex((spec, i) => i > userAt + 1 && rank(spec) < 3);
    if (next >= 0) main.splice(userAt, 0, ...main.splice(next, 1));
    else wide.add(main[userAt - 1].key);
  }
  const gridOf = (specs) => h('div', { class: 'form-grid settings-grid' }, specs.map((spec) => renderSpec(spec)));
  const renderSpec = (spec) => {
    const secretSet = spec.type === 'secret' && item.secrets.includes(spec.key) && !draft.clear.includes(spec.key);
    return fieldInput(spec, getPath(draft.config, spec.key), (value) => set(spec.key, value), {
      issues: at(spec.key),
      wide: wide.has(spec.key),
      // the main connection has no other values to inherit, so yes/no is a switch
      switch: item.default,
      secretSet,
      extra: spec.type === 'secret' && item.secrets.includes(spec.key) ? h('label', { class: 'check small' },
        h('input', { type: 'checkbox', checked: draft.clear.includes(spec.key), onchange: (e) => {
          draft.clear = e.target.checked ? [...draft.clear, spec.key] : draft.clear.filter((key) => key !== spec.key);
        } }), 'Clear stored value') : null,
    });
  };
  panel.append(...[
    h('div', { class: 'panel-head' }, moduleBadge(mod), h('h2', {}, item.default ? mod.label : item.name), h('span', { class: 'spacer' }), statusPill(item.status)),
    h('p', { class: 'muted small' }, item.default
      ? `Used by every ${mod.label} step.`
      : `Extra ${mod.label} connection. Empty fields use the main ${mod.label} settings.`),
    item.default ? null : h('div', { class: 'field' }, h('label', { for: 'inst-name' }, 'Name'),
      h('input', { id: 'inst-name', type: 'text', value: draft.name, oninput: (e) => { draft.name = e.target.value; } })),
    gridOf(main),
    advanced.length ? h('details', { class: 'section', open: advanced.some((spec) => at(spec.key).length > 0) },
      h('summary', {}, 'More options'),
      gridOf(advanced)) : null,
    h('div', { class: 'section-gap' }),
    issueList(issues.filter((issue) => !visible(mod.fields).some((spec) => at(spec.key).includes(issue)))) || '',
    item.test ? h('div', { class: `issue ${item.test.ok ? '' : 'error'}` },
      h('span', { class: `pill ${item.test.ok ? 'ok' : 'err'}` }, item.test.ok ? 'connected' : 'failed'), ' ', item.test.message) : null,
    h('div', { class: 'btn-row section-gap' },
      h('button', { class: 'btn primary', onclick: saveInstance }, 'Save'),
      h('button', { class: 'btn', 'data-test-button': '', onclick: () => testInstance(mod) }, 'Test'),
      item.default ? null : h('button', { class: 'btn danger', onclick: deleteInstance }, 'Delete'),
      inDialog ? h('button', { class: 'btn ghost', onclick: () => document.getElementById('dialog').close() }, 'Close') : null),
  ].filter((child) => child !== null && child !== undefined && child !== ''));
  return panel;
}

// Check the settings first, then try the connection when the module has a test.
async function testInstance(mod) {
  const busy = () => document.querySelectorAll('[data-test-button]').forEach((button) => {
    button.disabled = true;
    button.textContent = 'Testing…';
  });
  busy();
  try {
    const id = encodeURIComponent(state.instanceId);
    const payload = instancePayload();
    const check = await api('POST', `instances/${id}/validate`, payload);
    state.instanceIssues = check.issues;
    const item = instanceById(state.instanceId);
    if (item) item.test = null;
    if (check.status !== 'valid') {
      toast(`Settings are ${check.status}. Fix them before testing.`, 'err');
    } else if (!mod.connection_test) {
      toast('Settings are valid.', 'ok');
    } else {
      refreshInstanceView();  // show the cleared issues while the connection test runs
      busy();
      const result = await api('POST', `instances/${id}/test`, payload);
      if (item) item.test = result;
      toast(result.message, result.ok ? 'ok' : 'err');
    }
  } catch (err) { toast(err.message, 'err'); }
  refreshInstanceView();
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
  setView(['flows', 'modules'].includes(view) ? view : 'flows');
  let lastFlow = null;
  try { lastFlow = localStorage.getItem('cineflow.flow'); } catch (e) { /* storage unavailable */ }
  const first = state.flows.find((flow) => flow.id === lastFlow) || state.flows[0];
  if (first) selectFlow(first.id);
  setInterval(() => {
    if (state.view === 'flows' && state.flowId) refreshRuntime();
  }, 15000);
  setInterval(() => {
    if (state.view === 'modules' && !document.hidden) checkModules();
  }, MODULE_CHECK_INTERVAL);
}

start();
