/* CineFlow web GUI: module manager and flow editor (sources -> filters -> actions).
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

// shown in the field of a stored secret; leaving it as it is keeps the stored value
const SECRET_MASK = '••••••••';
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
      spec.ordered ? h('span', { class: 'word-rank', 'aria-label': `priority ${index + 1}` }, index + 1) : null,
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
/** Fields in order: one-line inputs and dropdowns, then the switches two to a row, then lists. */
function arrangeFields(fields) {
  const items = fields.filter(Boolean);
  const switches = items.filter((el) => el.classList.contains('switch-field'));
  const rest = items.filter((el) => !switches.includes(el));
  // a wide text slider or a card list keeps its place among the one-line fields
  const inline = rest.filter((el) => el.classList.contains('inline') || el.classList.contains('in-order'));
  const other = rest.filter((el) => !inline.includes(el));
  return [...inline, switches.length ? h('div', { class: 'switch-grid' }, switches) : null, ...other].filter(Boolean);
}

/**
 * A list of mappings with declared item fields (e.g. filter conditions): one
 * card per item with its fields, a remove button, and a button to add one.
 * `opts.itemIssues(index, key)` returns the issues of one item field.
 */
function objectListField(spec, value, onChange, opts = {}) {
  let items = Array.isArray(value) ? value.map((item) => (isObject(item) ? { ...item } : {})) : [];
  // a required list starts with one item to fill in, an optional one with the add button
  if (!items.length && spec.required) items = [{}];
  const fields = visible(spec.item_fields);
  const name = spec.item_label || 'Item';
  const list = h('div', { class: 'object-list' });
  const write = () => {
    const kept = items.filter((item) => !isEmpty(item));
    onChange(kept.length ? kept.map((item) => ({ ...item })) : undefined);
  };
  const draw = () => {
    list.replaceChildren(...items.map((item, index) => h('div', { class: 'object-item' },
      h('div', { class: 'object-item-head' }, h('span', {}, `${name} ${index + 1}`),
        items.length > 1 || !spec.required ? h('button', {
          type: 'button', class: 'word-remove', title: `Remove ${name.toLowerCase()} ${index + 1}`,
          'aria-label': `Remove ${name.toLowerCase()} ${index + 1}`,
          onclick: () => { items.splice(index, 1); write(); draw(); },
        }, strokeIcon(['M6 6l12 12', 'M18 6L6 18'])) : null),
      arrangeFields(fields.map((sub) => fieldInput(sub, item[sub.key], (next) => {
        if (next === undefined) delete item[sub.key]; else item[sub.key] = next;
        write();
      }, { placeholder: '', issues: opts.itemIssues ? opts.itemIssues(index, sub.key) : [] }))))),
    h('button', {
      type: 'button', class: 'btn small object-add',
      onclick: () => { items.push({}); draw(); },
    }, `+ Add ${name.toLowerCase()}`));
  };
  draw();
  const issues = opts.issues || [];
  return h('div', { class: `field wide in-order${issues.some((i) => i.level === 'error') ? ' has-error' : ''}` },
    h('label', {}, spec.label || spec.key, spec.required ? h('span', { class: 'req' }, ' *') : null),
    spec.description ? h('div', { class: 'hint' }, spec.description) : null,
    list, fieldIssues(issues));
}

/** Choices of a select field shown as a text slider when they fit on one row. */
const SLIDER_MAX_OPTIONS = 4;
const SLIDER_MAX_TEXT = 36;  // characters of all choices together

/** Text slider input; `options` are [value, label]; '' stands for "not set". */
function sliderInput(id, options, current, onChange) {
  const wrap = h('div', { class: 'segmented field-slider', id, role: 'radiogroup' });
  options.forEach(([value, label]) => {
    const active = value === current;
    wrap.append(h('button', {
      type: 'button', role: 'radio', 'aria-checked': String(active), class: active ? 'active' : '',
      onclick: () => {
        if (active) return;
        onChange(value);
        wrap.querySelectorAll('button').forEach((button) => {
          const on = button === wrap.children[options.findIndex(([item]) => item === value)];
          button.classList.toggle('active', on);
          button.setAttribute('aria-checked', String(on));
        });
      },
    }, label));
  });
  return wrap;
}

// dropdown values read from the services: "<instance>/<list>" -> Promise of names
const choiceCache = new Map();

function loadChoices(instanceId, source) {
  const key = `${instanceId}/${source}`;
  if (!choiceCache.has(key)) {
    const promise = api('GET', `instances/${encodeURIComponent(instanceId)}/choices/${source}`).then((data) => data.choices);
    promise.catch(() => choiceCache.delete(key));
    choiceCache.set(key, promise);
  }
  return choiceCache.get(key);
}

// value of the "All" entry of a dropdown with an `all_key`
const ALL_CHOICE = '\u0000all';

/**
 * Dropdown filled from the service; a text input when the list cannot be read.
 * With `allLabel` the list starts with an "All" entry (value ALL_CHOICE).
 */
function choiceInput(spec, value, onChange, id, instanceId, emptyText, allLabel) {
  const select = h('select', { id, onchange: (e) => onChange(e.target.value === '' ? undefined : e.target.value) });
  const fill = (names, loading, failed) => {
    const values = names.slice();
    if (value && value !== ALL_CHOICE && !values.includes(value)) values.unshift(value);
    const note = (name) => (loading || failed || names.includes(name) ? name : `${name} (not found)`);
    select.replaceChildren(h('option', { value: '' }, loading ? 'Loading…' : emptyText),
      allLabel ? h('option', { value: ALL_CHOICE }, allLabel) : null,
      ...values.map((name) => h('option', { value: name }, note(name))));
    select.value = value ?? '';
  };
  fill([], true);
  loadChoices(instanceId, spec.choices).then((names) => fill(names, false)).catch((err) => {
    if (allLabel) {
      // keep the "All" entry; other names cannot be offered without the list
      fill([], false, true);
      select.title = err.message;
      return;
    }
    const input = h('input', {
      id, type: 'text', value: value ?? '', placeholder: 'type a name', title: err.message,
      oninput: (e) => onChange(e.target.value === '' ? undefined : e.target.value),
    });
    select.replaceWith(input);
  });
  return select;
}

function fieldInput(spec, value, onChange, opts = {}) {
  // [value, text] of the choices of a select field
  const choices = () => (spec.options || []).map((option, i) => [String(option), String((spec.option_labels || [])[i] ?? option)]);
  const slider = spec.type === 'select' && spec.options.length <= SLIDER_MAX_OPTIONS
    && choices().reduce((sum, [, text]) => sum + text.length, 0) <= SLIDER_MAX_TEXT;
  const id = `f-${Math.random().toString(36).slice(2)}`;
  const inherit = opts.inherit;
  const inheritText = inherit ? `inherit (${inherit})` : 'inherit';
  const placeholder = opts.placeholder !== undefined ? opts.placeholder
    : (spec.default !== null && spec.default !== undefined && !Array.isArray(spec.default) ? `default: ${spec.default}` : '');
  let control;
  const type = spec.type;
  if (type === 'list' && (spec.item_fields || []).length) return objectListField(spec, value, onChange, opts);
  if (type === 'boolean' && opts.switch) {
    // a yes/no switch; the default value is stored as "not set"
    const fallback = spec.default === true;
    const issues = opts.issues || [];
    return h('div', {
      class: `field switch-field${issues.some((i) => i.level === 'error') ? ' has-error' : ''}`,
      title: spec.description || undefined,
    },
    h('div', { class: 'switch-row' },
      switchControl(id, typeof value === 'boolean' ? value : fallback,
        (checked) => onChange(checked === fallback ? undefined : checked)),
      h('label', { for: id }, spec.label || spec.key)),
    opts.extra || null,
      fieldIssues(issues));
  }
  if (spec.choices && opts.choicesFrom && (type === 'string' || type === 'select')) {
    control = choiceInput(spec, value, onChange, id, opts.choicesFrom,
      opts.emptyText || (inherit !== undefined ? inheritText : '— not set —'), opts.allLabel);
  } else if (type === 'boolean') {
    const current = value === true ? 'true' : value === false ? 'false' : '';
    const defaultText = inherit !== undefined ? 'Inherit'
      : spec.default !== null && spec.default !== undefined ? `Default (${spec.default ? 'yes' : 'no'})` : 'Not set';
    control = sliderInput(id, [['', defaultText], ['true', 'Yes'], ['false', 'No']], current,
      (picked) => onChange(picked === '' ? undefined : picked === 'true'));
  } else if (slider && inherit === undefined
    && spec.default !== null && spec.default !== undefined && spec.default !== '') {
    // a choice with a default is never empty: the default option stands for the unset value
    const current = value === undefined || value === null || value === '' ? String(spec.default) : String(value);
    control = sliderInput(id, choices(), current,
      (picked) => onChange(picked));
  } else if (slider) {
    const defaultText = inherit !== undefined ? 'Inherit' : spec.default ? `Default (${spec.default})` : 'Not set';
    control = sliderInput(id, [['', defaultText], ...choices()],
      value === undefined || value === null ? '' : String(value), (picked) => onChange(picked === '' ? undefined : picked));
  } else if (type === 'select') {
    const defaultText = inherit !== undefined ? inheritText
      : spec.default ? `default (${spec.default})` : '— not set —';
    control = h('select', { id, onchange: (e) => onChange(e.target.value === '' ? undefined : e.target.value) },
      h('option', { value: '' }, defaultText),
      choices().map(([option, text]) => h('option', { value: option }, text)));
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
      placeholder: type === 'secret' && secretSet ? 'empty: the stored value is deleted on save'
        : inherit !== undefined ? inheritText : placeholder,
      oninput: (e) => onChange(e.target.value === '' ? undefined : e.target.value),
      // typing over a stored secret replaces the whole value
      onfocus: (e) => { if (secretSet && e.target.value === SECRET_MASK) e.target.select(); },
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
  // one-line inputs have their label in front; lists, text boxes and ``opts.stacked`` keep it above
  // a text slider with long choices needs the full row
  const longSlider = control.classList && control.classList.contains('field-slider')
    && [...control.children].reduce((sum, button) => sum + button.textContent.length, 0) > 24;
  const stacked = opts.stacked || type === 'list' || type === 'object' || longSlider;
  const label = h('label', { for: id }, spec.label || spec.key, spec.required ? h('span', { class: 'req' }, ' *') : null);
  const hint = spec.description ? h('div', { class: 'hint' }, spec.description) : null;
  return h('div', { class: `field${stacked ? '' : ' inline'}${longSlider ? ' in-order' : ''}${issues.some((i) => i.level === 'error') ? ' has-error' : ''}${width}` },
    // inline fields: label and control side by side, the hint below both in the full width
    stacked ? [label, control, hint]
      : [h('div', { class: 'field-row' }, h('div', { class: 'field-label' }, label), control), hint],
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
  state.defaultExportDir = catalog.default_export_directory || '';
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

const MEDIA_KINDS = [['movie', 'Movies'], ['tv', 'TV series'], ['both', 'Both']];
// schedule choices: run interval in minutes, or null for a disabled flow
const SCHEDULES = [[null, 'Disabled'], [10, '10m'], [30, '30m'], [60, '1h'], [240, '4h'], [720, '12h'], [1440, '1d'], [10080, '1w']];
// priority choices with the number written to the flow; lower numbers run first in sequential mode
const PRIORITIES = [['low', 'Low', 100], ['medium', 'Medium', 10], ['high', 'High', 1]];

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
  const error = h('div', { class: 'field-issue error', role: 'alert' });
  const create = async () => {
    if (!name.value.trim()) { error.textContent = 'A name is required.'; name.focus(); return; }
    const flow = {
      name: name.value.trim(), enabled: false, delay: 60, priority: 10, kind: kind.value, steps: [],
    };
    if (desc.value.trim()) flow.description = desc.value.trim();
    try {
      const result = await api('POST', 'flows', { flow });
      document.getElementById('dialog').close();
      state.dirty = false;
      await refreshFlows();
      await selectFlow(result.id);
      toast('Flow created. Start by adding a source.', 'ok');
    } catch (err) { error.textContent = err.message; }
  };
  const body = h('div', {
    class: 'form-grid',
    onkeydown: (e) => { if (e.key === 'Enter' && e.target.tagName === 'INPUT') { e.preventDefault(); create(); } },
  },
  h('div', { class: 'field wide' }, h('label', { for: 'new-flow-name' }, 'Name', h('span', { class: 'req' }, ' *')), name),
  h('div', { class: 'field wide' }, h('label', { for: 'new-flow-desc' }, 'Description'), desc),
  h('div', { class: 'field wide' }, h('label', { for: 'new-flow-kind' }, 'Media kind'), kind),
  h('div', { class: 'wide hint muted small' }, 'The flow starts disabled. Choose a schedule once its steps are ready.'),
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
  const selected = state.stepIndex !== null && (state.flow.steps || [])[state.stepIndex];
  return h('div', {},
    renderFlowHeader(),
    h('div', { class: `layout-simple${selected ? '' : ' no-side'}` },
      h('section', { class: 'board-col' }, renderBoard(), renderTestPanel()),
      selected ? h('aside', { class: 'side-panel' }, renderStepEditor(state.stepIndex)) : null));
}

function updateFlow(key, value) {
  if (value === undefined) delete state.flow[key]; else state.flow[key] = value;
  markDirty();
}

/** Labelled segmented control; `options` are [value, label, title?]. */
function segmented(label, options, current, onPick, title) {
  const wrap = h('div', { class: 'segmented', role: 'radiogroup', 'aria-label': label });
  options.forEach(([value, text, hint]) => {
    const active = value === current;
    wrap.append(h('button', {
      type: 'button', role: 'radio', 'aria-checked': String(active), class: active ? 'active' : '', title: hint,
      onclick: () => { if (!active) onPick(value); },
    }, text));
  });
  return h('div', { class: 'option-group', title }, h('span', { class: 'option-label' }, label), wrap);
}

/** Short interval text, e.g. 90 -> "90m", 120 -> "2h". */
function delayText(minutes) {
  for (const [unit, size] of [['w', 10080], ['d', 1440], ['h', 60]]) {
    if (minutes % size === 0) return `${minutes / size}${unit}`;
  }
  return `${minutes}m`;
}

function priorityOf(value) {
  const number = Number.isInteger(value) ? value : 99;
  if (number <= 5) return 'high';
  return number <= 50 ? 'medium' : 'low';
}

/** Media kind, schedule and priority of the flow. */
function renderFlowOptions() {
  const flow = state.flow;
  const delay = Number.isInteger(flow.delay) && flow.delay > 0 ? flow.delay : 60;
  const schedules = SCHEDULES.slice();
  if (!schedules.some(([value]) => value === delay)) {
    // keep an interval written by hand selectable
    schedules.push([delay, delayText(delay)]);
    schedules.sort((a, b) => (a[0] ?? -1) - (b[0] ?? -1));
  }
  return h('div', { class: 'flow-options', id: 'flow-options' },
    segmented('Media', MEDIA_KINDS.map(([value, label]) => [value, label,
      value === 'both' ? 'Runs the flow twice: for movies, then for TV series.' : undefined]),
    flow.kind || 'movie', (value) => { updateFlow('kind', value); render(); }),
    segmented('Schedule', schedules, flow.enabled === false ? null : delay, (value) => {
      if (value === null) updateFlow('enabled', false);
      else { flow.delay = value; updateFlow('enabled', true); }
      render();
    }, 'How often the flow runs. Only flows without errors can run on a schedule.'),
    segmented('Priority', PRIORITIES.map(([value, label]) => [value, label]), priorityOf(flow.priority), (value) => {
      updateFlow('priority', PRIORITIES.find((item) => item[0] === value)[2]);
      render();
    }, 'Which flow runs first when several are due (sequential mode).'),
    h('div', { class: 'option-issues' },
      ['kind', 'enabled', 'delay', 'priority'].map((key) => h('div', { dataset: { issuePath: key } }))));
}

const ICONS = {
  save: ['M5 4h11l3 3v13H5z', 'M8 4v5h7V4', 'M8 20v-6h8v6'],
  run: ['M8 5l11 7-11 7z'],
  test: ['M9 3h6', 'M10 3v6l-5 10a1 1 0 0 0 1 2h12a1 1 0 0 0 1-2l-5-10V3', 'M7 15h10'],
  delete: ['M4 7h16', 'M9 7V4h6v3', 'M6 7l1 13h10l1-13', 'M10 11v6', 'M14 11v6'],
};

function iconButton(icon, text, attrs) {
  return h('button', { type: 'button', ...attrs, class: `btn icon-label ${attrs.class || ''}` },
    strokeIcon(ICONS[icon]), h('span', { class: 'btn-text' }, text));
}

function renderFlowActions() {
  const flow = state.flow;
  const running = Boolean(state.runtime && state.runtime.running);
  return h('div', { class: 'flow-actions', id: 'flow-actions' },
    iconButton('save', 'Save', { class: 'primary', id: 'save-flow', onclick: saveFlow }),
    iconButton('run', running ? 'Running…' : 'Run', {
      id: 'run-flow', disabled: !state.flowId || state.dirty || running || !(state.health && state.health.runtime),
      title: state.dirty ? 'Save the flow first' : 'Run the flow once now', onclick: runFlow,
    }),
    iconButton('test', state.testing ? 'Testing…' : 'Test', {
      disabled: state.testing || !(flow.steps || []).length,
      title: 'Run every step with real data but without side effects', onclick: () => runTest(undefined),
    }),
    iconButton('delete', 'Delete', { class: 'danger', disabled: !state.flowId, onclick: deleteFlow }));
}

function renderFlowHeader() {
  const flow = state.flow;
  return h('div', { class: 'panel flow-head' },
    h('div', { class: 'flow-top' },
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
      h('div', { class: 'flow-status', id: 'flow-status' }, renderFlowStatus())),
    h('div', { class: 'flow-bottom' }, renderFlowOptions(), renderFlowActions()),
    renderFlowSettings(),
    h('div', { id: 'flow-issues' }, renderFlowIssues()));
}

/**
 * Flow settings the flow hands to its modules (library folder, release
 * preference), in the header; each is shown while a step uses it or it has a value.
 */
function renderFlowSettings() {
  const flow = state.flow;
  const used = (setting) => (flow.steps || []).some((step) => isObject(step) && setting.modules.includes(step.module))
    || !isEmpty(flow[setting.key]);
  const fields = flowSettingFields((state.flowSettings || []).filter(used));
  return fields.length ? h('div', { class: 'flow-settings', id: 'flow-settings' }, h('div', { class: 'form-grid' }, fields))
    : h('div', { id: 'flow-settings', hidden: true });
}

/** Form fields of flow settings. */
function flowSettingFields(settings) {
  const flow = state.flow;
  return settings.map((setting) => {
    const spec = setting.field;
    const issueSlot = h('div', { dataset: { issuePath: setting.key } });
    if (spec.type === 'path') {
      // the full export path stands in front of the folder name
      const sep = state.exportDir.includes('\\') && !state.exportDir.includes('/') ? '\\' : '/';
      const root = state.exportDir ? `${state.exportDir.replace(/[\\/]+$/, '')}${sep}` : '';
      const both = flow.kind === 'both';
      const kinds = both ? ['movie', 'tv'] : [flow.kind || 'movie'];
      // only a flow of both kinds needs telling where each kind goes
      const where = h('div', { class: 'hint' });
      const showWhere = () => {
        where.hidden = !both;
        where.textContent = flow[setting.key] ? 'Movies and TV series go to this folder.'
          : 'Movies go to the movie folder, TV series to the tv folder.';
      };
      const input = h('input', {
        id: `flow-${setting.key}`, type: 'text', autocomplete: 'off', value: flow[setting.key] || '',
        placeholder: setting.kind_default ? kinds.join(' / ') : '',
        oninput: (e) => { updateFlow(setting.key, e.target.value.trim() || undefined); showWhere(); },
      });
      showWhere();
      return h('div', { class: 'field' },
        h('label', { for: input.id }, spec.label),
        h('div', { class: 'prefix-input', title: 'Export directory: set in the Library module settings' },
          root ? h('span', { class: 'prefix' }, root) : null, input),
        where, issueSlot);
    }
    const field = fieldInput(spec, flow[setting.key], (value) => updateFlow(setting.key, value), { stacked: true });
    field.classList.remove('wide');
    field.append(issueSlot);
    return field;
  });
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
  const status = document.getElementById('flow-status');
  if (status) status.replaceChildren(...renderFlowStatus());
  const summary = document.getElementById('flow-issues');
  if (summary) summary.replaceChildren(renderFlowIssues());
  const board = document.getElementById('board');
  if (board) board.replaceWith(renderBoard());
  const stepIssues = document.getElementById('step-issues');
  if (stepIssues && state.stepIndex !== null) {
    stepIssues.replaceChildren(issueList(issuesAt(state.issues, ['steps', state.stepIndex])) || '');
  }
  document.querySelectorAll('[data-step-issues]').forEach((el) => {
    el.replaceChildren(issueList(stepOwnIssues(Number(el.dataset.stepIssues), moduleDef(el.dataset.module))) || '');
  });
  document.querySelectorAll('[data-issue-path]').forEach((el) => {
    const path = el.dataset.issuePath.split('.');
    el.replaceChildren(...fieldIssues(state.issues.filter((issue) => issue.path.join('.') === path.join('.'))));
  });
  const run = document.getElementById('run-flow');
  if (run && state.dirty) { run.disabled = true; run.title = 'Save the flow first'; }
}

/** State pills shown in the top right corner of the flow header. */
function renderFlowStatus() {
  const errors = state.issues.filter((i) => i.level === 'error').length;
  const warnings = state.issues.filter((i) => i.level === 'warning').length;
  return [
    state.runtime && state.runtime.running ? h('span', { class: 'pill info' }, 'running') : null,
    state.dirty ? h('span', { class: 'pill info' }, 'unsaved') : null,
    warnings ? h('span', { class: 'pill warn' }, `${warnings} warning${warnings === 1 ? '' : 's'}`) : null,
    errors ? h('span', { class: 'pill err' }, `${errors} error${errors === 1 ? '' : 's'}`) : h('span', { class: 'pill ok' }, 'valid'),
  ].filter(Boolean);
}

/** Flow-level issues that have no field of their own. */
function renderFlowIssues() {
  const flowLevel = state.issues.filter((i) => (i.path[0] !== 'steps' || i.path.length === 1)
    && !['name', 'kind', 'enabled', 'delay', 'priority', ...(state.flowSettings || []).map((item) => item.key)]
      .includes(String(i.path[0])));
  return flowLevel.length ? h('div', { class: 'small section-gap' }, issueList(flowLevel)) : '';
}

/** Test results of a step: one per media kind for a flow of both kinds. */
function testResultsFor(index) {
  return state.test ? state.test.steps.filter((item) => item.index === index) : [];
}

const KIND_LABELS = Object.fromEntries(MEDIA_KINDS);

/** Card pill of the test results of a step; counts per kind, e.g. "12 / 5 items". */
function resultsPill(results) {
  if (results.length < 2) return resultPill(results[0]);
  const failed = results.find((item) => item.status !== 'ok' && item.status !== 'skipped');
  if (failed) return resultPill(failed);
  if (results.every((item) => item.status === 'skipped')) return resultPill(results[0]);
  const stale = state.testStale ? ' stale' : '';
  const title = results.map((item) => `${KIND_LABELS[item.kind] || item.kind}: ${item.count ?? 0}`).join(', ');
  return h('span', { class: `pill ok${stale}`, title }, `${results.map((item) => item.count ?? 0).join(' / ')} items`);
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
    h('div', { class: 'form-grid' }, arrangeFields(specs.filter((spec) => !spec.advanced).map(render))),
    moreOptions(arrangeFields(advanced.map(render)), advanced.some(inUse)),
  ];
}

async function refreshRuntime() {
  if (!state.flowId) return;
  try {
    const data = await api('GET', `flows/${encodeURIComponent(state.flowId)}`);
    state.runtime = data.runtime;
    await refreshFlows();
    renderSubnav();
    const actions = document.getElementById('flow-actions');
    if (actions && !state.dirty) actions.replaceWith(renderFlowActions());
    const status = document.getElementById('flow-status');
    if (status) status.replaceChildren(...renderFlowStatus());
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
  const stepIssues = issuesAt(state.issues, ['steps', index]);
  const at = (...path) => stepIssues.filter((issue) => issue.path.slice(2).join('.') === path.join('.'));
  const panel = h('div', { class: 'panel' });
  const rerender = () => { const side = panel.parentElement; if (side) side.replaceChildren(renderStepEditor(index)); };

  panel.append(h('div', { class: 'panel-head' },
    h('h2', {}, action ? action.label : step.action), h('span', { class: 'spacer' }), moduleIndicator(step, mod),
    h('button', { class: 'btn ghost small', title: 'Close', 'aria-label': 'Close', onclick: () => selectStep(index) }, '✕')));
  if (action) panel.append(h('p', { class: 'muted small' }, action.description));
  panel.append(h('div', { id: 'step-issues' }, issueList(stepIssues) || ''));

  const before = panel.children.length;
  if (action && action.stage === 'source') panel.append(...renderEnrichEditor(step));
  const query = renderQueryEditor(step, action, at);
  // module settings shown on this step go before the "More options" of the query
  const own = renderModuleOverrides(step, mod, action, at);
  if (own.length) query.insertBefore(h('div', { class: 'form-grid-flat' }, own), query.querySelector(':scope > details'));
  if ([...query.children].some((child) => child.tagName !== 'DETAILS')) {
    panel.append(h('div', { class: 'section-title' }, action && action.stage === 'source' ? 'What to collect' : 'Options'));
  }
  if (query.children.length) panel.append(query);
  appendArguments(panel, step, action, at);
  if (mod) panel.append(...renderStepSettings(step, mod, action, stepIssues, at, rerender));
  if (panel.children.length === before) panel.append(h('p', { class: 'muted small' }, 'This step needs no settings.'));

  return panel;
}

/**
 * Module settings an action shows on its step (`overrides`): empty means the
 * module value, shown as "inherit (…)"; a value is a step override (`config`).
 */
function renderModuleOverrides(step, mod, action, at) {
  if (!mod || !action || !(action.overrides || []).length) return [];
  const instance = instanceById(step.instance || step.module);
  return action.overrides.map((key) => mod.fields.find((spec) => spec.key === key)).filter(Boolean).map((spec) => {
    const value = getPath(step.config || {}, spec.key);
    const inherited = instance ? getPath(instance.config || {}, spec.key) ?? spec.default : spec.default;
    const none = inherited === undefined || inherited === null || inherited === '' || inherited === 0;
    return fieldInput(spec, value, (next) => {
      const config = clone(step.config) || {};
      setPath(config, spec.key, next);
      if (isEmpty(config)) delete step.config; else step.config = config;
      markDirty();
    }, {
      issues: at('config', spec.key),
      inherit: none ? (spec.type === 'select' ? 'any' : 'no limit') : String(inherited),
      switch: true,
    });
  });
}

/** Action arguments given next to the items, such as a file name. */
function appendArguments(panel, step, action, at) {
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
      (value) => setConfig(spec.key, value), {
        issues: at('config', spec.key), switch: true,
        itemIssues: (position, key) => at('config', spec.key, String(position), key),
      }),
    (spec) => getPath(config, spec.key) !== undefined || at('config', spec.key).length > 0).filter(Boolean));
  }
  // module settings live in the module; show only those this step sets or must set
  // (credentials and other module-only fields are fixed in the module settings)
  const shownOnStep = new Set(action ? action.overrides : []);
  const overrides = visible(mod.fields).filter((spec) => !shownOnStep.has(spec.key)
    && (getPath(config, spec.key) !== undefined || (spec.step && spec.type !== 'secret' && at('config', spec.key).length)));
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

/**
 * Libraries choice: All / Only / All except, with one or more libraries. It
 * writes the field (one name, or a list) and its `inverse_key` (true for
 * "All except") into the query, so the flow states exactly what it compares.
 */
function scopeField(spec, query, setKeys, instanceId, issues) {
  const id = `f-${Math.random().toString(36).slice(2)}`;
  const raw = query[spec.key];
  let names = isEmpty(raw) ? [] : (Array.isArray(raw) ? raw : [raw]).map(String);
  let mode = !names.length ? 'all' : query[spec.inverse_key] === true ? 'except' : 'only';
  let offered = null;   // names read from the service, null while loading or when it failed
  const chips = h('ul', { class: 'word-chips scope-chips', 'aria-label': spec.label });
  const write = () => {
    const updates = { [spec.key]: undefined, [spec.inverse_key]: undefined };
    if (mode !== 'all' && names.length) {
      updates[spec.key] = names.length === 1 ? names[0] : names.slice();
      if (mode === 'except') updates[spec.inverse_key] = true;
    }
    setKeys(updates);
    draw();
  };
  const add = (name) => {
    if (name && !names.includes(name)) { names.push(name); write(); }
  };
  const adder = () => {
    if (offered === null) {
      const input = h('input', {
        type: 'text', class: 'scope-add', placeholder: 'library name, Enter to add',
        onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); add(e.target.value.trim()); } },
      });
      return h('li', { class: 'scope-adder' }, input);
    }
    const left = offered.filter((name) => !names.includes(name));
    if (!left.length) return null;
    const select = h('select', { class: 'scope-add', onchange: (e) => add(e.target.value) },
      h('option', { value: '' }, '+ Add library…'), left.map((name) => h('option', { value: name }, name)));
    return h('li', { class: 'scope-adder' }, select);
  };
  const draw = () => {
    chips.hidden = mode === 'all';
    chips.replaceChildren(...names.map((name) => h('li', { class: 'word-chip' },
      h('span', { class: 'word-text' }, offered && !offered.includes(name) ? `${name} (not found)` : name),
      h('button', {
        type: 'button', class: 'word-remove', title: `Remove ${name}`, 'aria-label': `Remove ${name}`,
        onclick: () => { names = names.filter((item) => item !== name); write(); },
      }, strokeIcon(['M6 6l12 12', 'M18 6L6 18'])))),
    adder());
  };
  draw();
  if (instanceId) {
    loadChoices(instanceId, spec.choices).then((list) => { offered = list; draw(); }).catch(() => draw());
  }
  const slider = sliderInput(id, [['all', 'All'], ['only', 'Only'], ['except', 'All except']], mode,
    (value) => { mode = value; write(); });
  return h('div', { class: `field inline${issues.some((i) => i.level === 'error') ? ' has-error' : ''}` },
    h('div', { class: 'field-row' },
      h('div', { class: 'field-label' }, h('label', { for: id }, spec.label)),
      h('div', { class: 'scope-control' }, slider, chips)),
    spec.description ? h('div', { class: 'hint' }, spec.description) : null,
    fieldIssues(issues));
}

/** Query fields of a step; the item input is wired by the funnel. */
function renderQueryEditor(step, action, at) {
  const model = parseInput(step.input);
  const wrap = h('div', { class: 'form-grid' });
  const commit = (next) => {
    const value = buildInput(next);
    if (value === undefined) delete step.input; else step.input = value;
    markDirty();
  };
  const takesQuery = Boolean(action) && model.mode === 'form' && (action.input === 'query' || action.input === 'data+query');

  if (takesQuery) {
    const queryFields = visible(action.query);
    const queryObj = isObject(model.query) ? model.query : {};
    if (typeof model.query === 'string' || !queryFields.length) {
      // an optional free text match; rarely needed
      wrap.append(moreOptions([h('div', { class: 'field wide' }, h('label', { for: 'query-text' }, 'Title contains'),
        h('input', {
          id: 'query-text', type: 'text', value: typeof model.query === 'string' ? model.query : '',
          placeholder: 'optional',
          oninput: (e) => { model.query = e.target.value || undefined; commit(model); },
        }),
        fieldIssues(at('input', 'query')))], !isEmpty(model.query) || at('input', 'query').length > 0, 'wide'));
    }
    if (queryFields.length && typeof model.query !== 'string') {
      const setKeys = (updates) => {
        const next = isObject(model.query) ? { ...model.query } : {};
        Object.entries(updates).forEach(([key, value]) => { if (value === undefined) delete next[key]; else next[key] = value; });
        model.query = isEmpty(next) ? undefined : next;
        commit(model);
      };
      const queryInput = (spec) => {
        if (spec.inverse_key) {
          return scopeField(spec, isObject(model.query) ? model.query : {}, setKeys, step.instance || step.module,
            at('input', 'query', spec.key).concat(at('input', 'query', spec.inverse_key)));
        }
        // a dropdown with an "All" entry writes `all_key: true` instead of a value
        const allSpec = spec.all_key && action.query.find((item) => item.key === spec.all_key);
        const current = allSpec && queryObj[spec.all_key] === true ? ALL_CHOICE : queryObj[spec.key];
        return fieldInput(spec, current, (value) => {
          const next = isObject(model.query) ? { ...model.query } : {};
          delete next[spec.key];
          if (allSpec) delete next[spec.all_key];
          if (allSpec && value === ALL_CHOICE) next[spec.all_key] = true;
          else if (value !== undefined) next[spec.key] = value;
          model.query = isEmpty(next) ? undefined : next;
          commit(model);
        }, {
          issues: at('input', 'query', spec.key).concat(allSpec ? at('input', 'query', spec.all_key) : []),
          itemIssues: (position, key) => at('input', 'query', spec.key, String(position), key),
          placeholder: '', switch: true, choicesFrom: step.instance || step.module,
          allLabel: allSpec ? allSpec.label : undefined,
          emptyText: allSpec ? 'Default' : undefined,
        });
      };
      const basic = queryFields.filter((spec) => !spec.advanced);
      wrap.append(...arrangeFields(basic.map(queryInput)));
      // hidden keys (e.g. allUsers, set by the User dropdown) are not other parameters
      const known = new Set(action.query.map((spec) => spec.key));
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
      wrap.append(moreOptions(arrangeFields(advanced.map(queryInput).concat(raw)),
        !isEmpty(extra) || advanced.some((spec) => queryObj[spec.key] !== undefined
          || at('input', 'query', spec.key).length), 'wide'));
    }
  }
  return wrap;
}

/* ---------------------------------------------------------- simple editor */

/*
 * The simple editor shows a flow as sources (each with the services that add
 * data to its items), an automatic merge, filters and actions. It edits the
 * step list of the flow YAML through the funnel model in funnel.js; a flow that
 * does not fit that shape is shown with the reason and is edited by hand.
 */

function stageOf(step) {
  const action = isObject(step) ? actionDef(step.module, step.action) : undefined;
  return action ? action.stage : null;
}

function readFunnel() {
  return CineFunnel.toFunnel(state.flow.steps, stageOf);
}

function combineAction() {
  for (const mod of state.catalog) {
    const action = mod.actions.find((item) => item.stage === 'combine');
    if (action) return { module: mod.id, action: action.id };
  }
  return null;
}

function newStep(moduleId, actionId) {
  const action = actionDef(moduleId, actionId);
  return { name: uniqueStepName(action ? action.label : actionId), module: moduleId, action: actionId };
}

function newCombineStep() {
  const found = combineAction();
  return { name: uniqueStepName('Merge sources'), module: found.module, action: found.action };
}

/**
 * Change the funnel and write it back as steps. `change(funnel)` may return a
 * step to select; otherwise the selected step stays selected when it still exists.
 */
function editFunnel(change) {
  const { funnel } = readFunnel();
  if (!funnel) return;
  const before = state.flow.steps.slice();
  const kept = state.stepIndex !== null ? before[state.stepIndex] : null;
  const selected = change(funnel) || kept;
  state.flow.steps = CineFunnel.fromFunnel(funnel, newCombineStep);
  const index = selected ? state.flow.steps.indexOf(selected) : -1;
  state.stepIndex = index >= 0 ? index : null;
  // until the next validation and test run, issues and results follow their steps
  const moved = (at) => state.flow.steps.indexOf(before[at]);
  state.issues = state.issues.flatMap((issue) => {
    if (issue.path[0] !== 'steps' || issue.path.length < 2) return [issue];
    const to = moved(Number(issue.path[1]));
    return to < 0 ? [] : [{ ...issue, path: ['steps', to, ...issue.path.slice(2)] }];
  });
  if (state.test) {
    state.test.steps = state.test.steps.flatMap((item) => {
      const to = moved(item.index);
      return to < 0 ? [] : [{ ...item, index: to }];
    });
  }
  markDirty();
  render();
}

/** Position of a module in the catalog; data is added to items in this order. */
function moduleOrder(moduleId) {
  return state.catalog.findIndex((mod) => mod.id === moduleId);
}

/** Add (checked) or remove the step that adds a module's data to the items of a source. */
const MUST_MATCH = 'must_match';

function toggleEnrich(source, moduleId, actionId, checked, config) {
  editFunnel((funnel) => {
    const lane = funnel.lanes.find((item) => item.source === source);
    if (!lane) return source;
    if (checked) {
      const step = newStep(moduleId, actionId);
      if (config) step.config = config;
      lane.enrich.push(step);
      lane.enrich.sort((a, b) => moduleOrder(a.module) - moduleOrder(b.module));
    } else {
      lane.enrich = lane.enrich.filter((step) => step.module !== moduleId);
    }
    return source;
  });
}

/** Picker callback that adds a new step with `place(funnel, step)`; its card shows any missing setup. */
function addStep(place) {
  return (moduleId, actionId) => editFunnel((funnel) => {
    const step = newStep(moduleId, actionId);
    place(funnel, step);
    return step;
  });
}

function removeFunnelStep(step) {
  const { funnel } = readFunnel();
  const lane = funnel && funnel.lanes.find((item) => item.source === step);
  const extra = lane && lane.enrich.length ? ' and the data added to its items' : '';
  if (!window.confirm(`Remove "${step.name}"${extra}?`)) return;
  editFunnel((current) => {
    const own = current.lanes.find((item) => item.source === step);
    if (own) {
      current.lanes.splice(current.lanes.indexOf(own), 1);
      return null;
    }
    [...current.lanes.map((item) => item.enrich), current.filters, current.outputs].forEach((list) => {
      const at = list.indexOf(step);
      if (at >= 0) list.splice(at, 1);
    });
    return null;
  });
}

const STAGE_PICKERS = {
  source: ['Add a source', 'Where should the items come from?'],
  filter: ['Add a filter or data', 'Keep only the items you want, or look up more data for the items left, '
    + 'e.g. the release of the chosen season from Jackett.'],
  output: ['Add an action', 'What should happen with the items? Actions are skipped in test runs.'],
};

function openStagePicker(stage, onPick) {
  const [title, intro] = STAGE_PICKERS[stage];
  const choice = (mod, action) => h('button', {
    class: 'catalog-action',
    onclick: () => { document.getElementById('dialog').close(); onPick(mod.id, action.id); },
  }, h('div', { class: 'name' }, action.label, action.destructive ? ' ⚠' : ''), h('div', { class: 'desc' }, action.description));
  // actions that never contact the service, such as "Exclude by ID", are the
  // same in every module: list each once in its own group
  const local = new Map();
  const groups = state.catalog.map((mod) => {
    // the filter column also takes steps that add data to the filtered items
    const actions = mod.actions.filter((action) => action.stage === stage || (stage === 'filter' && action.stage === 'enrich'));
    // prefer a module that is set up: the step still needs valid module settings
    actions.filter((action) => action.local).forEach((action) => {
      const known = local.get(action.id);
      if (!known || (moduleNeedsSetup(known[0]) && !moduleNeedsSetup(mod))) local.set(action.id, [mod, action]);
    });
    const own = actions.filter((action) => !action.local);
    if (!own.length) return null;
    const head = h('div', { class: 'picker-head' }, moduleBadge(mod),
      h('div', { class: 'grow' }, h('h3', {}, mod.label), h('div', { class: 'muted small' }, mod.description)),
      moduleNeedsSetup(mod) ? h('span', { class: 'pill warn', title: `${mod.label} has no settings yet` }, 'needs setup') : null);
    // a source is chosen by its module: the module has one way to collect items
    if (stage === 'source' && own.length === 1) {
      return h('button', {
        type: 'button', class: `catalog-module module-choice ${categoryClass(mod)}`, title: own[0].description,
        dataset: { category: mod.category || 'other' },
        onclick: () => { document.getElementById('dialog').close(); onPick(mod.id, own[0].id); },
      }, head);
    }
    return h('div', { class: `catalog-module ${categoryClass(mod)}`, dataset: { category: mod.category || 'other' } },
      head, own.map((action) => choice(mod, action)));
  }).filter(Boolean);
  if (stage === 'source') {
    // one heading per module category, in catalog order
    const sections = new Map();
    groups.forEach((group) => {
      const { category } = group.dataset;
      if (!sections.has(category)) sections.set(category, []);
      sections.get(category).push(group);
    });
    openDialog(title, h('div', {}, h('p', { class: 'muted' }, intro),
      [...sections.entries()].map(([category, items]) => h('section', { class: 'picker-section' },
        h('h3', { class: 'picker-category' }, category.charAt(0).toUpperCase() + category.slice(1)),
        h('div', { class: 'catalog' }, items)))));
    return;
  }
  if (local.size) {
    groups.push(h('div', { class: 'catalog-module cat-internal' },
      h('div', { class: 'picker-head' }, h('div', { class: 'grow' }, h('h3', {}, 'Any items'),
        h('div', { class: 'muted small' }, 'Works on the items alone; no service is contacted.'))),
      [...local.values()].map(([mod, action]) => choice(mod, action))));
  }
  openDialog(title, h('div', {}, h('p', { class: 'muted' }, intro), h('div', { class: 'catalog' }, groups)));
}

/** Short text of the values a step sets, e.g. "Library: Movies · Favorites". */
function stepDetails(step, action) {
  if (!action) return '';
  const parts = [];
  const add = (specs, values, skip = []) => {
    const labels = new Map(specs.map((spec) => [spec.key, spec.label || spec.key]));
    const skipped = skip.slice();
    specs.filter((spec) => spec.inverse_key && !isEmpty(values[spec.key])).forEach((spec) => {
      const names = (Array.isArray(values[spec.key]) ? values[spec.key] : [values[spec.key]]).join(', ');
      parts.push(values[spec.inverse_key] === true ? `All except ${names}` : `Only ${names}`);
      skipped.push(spec.key, spec.inverse_key);
    });
    Object.entries(values).forEach(([key, value]) => {
      if (skipped.includes(key) || isEmpty(value)) return;
      const name = labels.get(key) || key;
      const spec = specs.find((item) => item.key === key);
      const at = spec && spec.option_labels && spec.option_labels.length ? (spec.options || []).indexOf(value) : -1;
      // items of a card list read as text, e.g. "torrent contains HUN"
      const itemText = (item) => (spec.item_fields || []).filter((sub) => !isEmpty(item[sub.key])).map((sub) => {
        const position = (sub.options || []).indexOf(item[sub.key]);
        return position >= 0 && (sub.option_labels || [])[position] ? sub.option_labels[position] : settingText(item[sub.key]);
      }).join(' ');
      // a `combine` choice of all/any joins the items with and/or
      const joiner = !specs.some((item) => item.key === 'combine') ? ', ' : values.combine === 'any' ? ' or ' : ' and ';
      if (key === 'combine' && specs.some((item) => (item.item_fields || []).length)) return;
      if (spec && (spec.item_fields || []).length && Array.isArray(value)) parts.push(value.filter(isObject).map(itemText).join(joiner));
      else if (value === true) parts.push(name);
      else if (value === false) parts.push(`not ${name.toLowerCase()}`);
      else parts.push(`${name}: ${at >= 0 ? spec.option_labels[at] : settingText(value)}`);
    });
  };
  const input = step.input;
  const query = isObject(input) ? input.query
    : typeof input === 'string' && !['previous', 'none', ''].includes(input) && refName(input) === null ? input : undefined;
  if (typeof query === 'string') parts.push(`“${query}”`);
  else if (isObject(query)) add(action.query, query);
  if (isObject(input)) add(action.arguments, input, ['data', 'query']);
  if (isObject(step.config)) add([...action.fields, ...((moduleDef(step.module) || {}).fields || [])], step.config);
  return parts.join(' · ');
}

/** Pills of a module that still needs settings. */
function setupPill(step) {
  const mod = moduleDef(step.module);
  const instance = step.instance ? instanceById(step.instance) : instanceById(step.module);
  if (!(mod && mod.fields.length > 0 && instance && instance.status !== 'valid')) return null;
  return h('button', {
    class: 'pill err as-button', title: `Configure ${mod.label}`,
    onclick: (e) => { e.stopPropagation(); openInstanceDialog(instance.id); },
  }, `set up ${instance.default ? mod.label : instance.name}`);
}

/** Card of a step; a source card also stands for the steps that add data to its items. */
function simpleCard(step, lane = null) {
  const index = state.flow.steps.indexOf(step);
  const steps = lane ? [lane.source, ...lane.enrich] : [step];
  const mod = moduleDef(step.module);
  const action = actionDef(step.module, step.action);
  const issues = steps.flatMap((item) => issuesAt(state.issues, ['steps', state.flow.steps.indexOf(item)]));
  const errors = issues.filter((i) => i.level === 'error').length;
  const warnings = issues.length - errors;
  const instance = step.instance ? instanceById(step.instance) : instanceById(step.module);
  const details = stepDetails(step, action);
  const added = lane ? lane.enrich.map((item) => (moduleDef(item.module) || { label: item.module }).label) : [];
  const end = steps[steps.length - 1];
  const title = lane ? (mod ? mod.label : step.module) : action ? action.label : `${step.module}.${step.action}`;
  const card = h('div', {
    class: `scard ${categoryClass(mod)}${index === state.stepIndex ? ' selected' : ''}${errors ? ' err' : warnings ? ' warn' : ''}`,
    tabindex: '0', role: 'button', 'aria-label': `${title}, click to configure`,
    onclick: () => selectStep(index),
    onkeydown: (e) => {
      if (e.target !== card) return;
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectStep(index); }
      if (e.key === 'Delete') { e.preventDefault(); removeFunnelStep(step); }
    },
  },
  moduleBadge(mod),
  h('div', { class: 'scard-body' },
    h('div', { class: 'scard-title' }, title, instance && !instance.default ? h('span', { class: 'muted' }, ` · ${instance.name}`) : null),
    details ? h('div', { class: 'scard-sub', title: details }, details) : null,
    added.length ? h('div', { class: 'scard-sub scard-added' }, `+ data from ${added.join(', ')}`) : null,
    h('div', { class: 'step-meta' },
      action && action.destructive ? h('span', { class: 'pill warn' }, 'deletes') : null,
      steps.map(setupPill),
      errors ? h('span', { class: 'pill err' }, `${errors} error${errors === 1 ? '' : 's'}`) : null,
      warnings ? h('span', { class: 'pill warn' }, `${warnings} warning${warnings === 1 ? '' : 's'}`) : null,
      resultsPill(testResultsFor(state.flow.steps.indexOf(end))))),
  h('button', {
    class: 'icon-btn danger', title: 'Remove', 'aria-label': `Remove ${title}`,
    onclick: (e) => { e.stopPropagation(); removeFunnelStep(step); },
  }, '✕'));
  return card;
}

/** Issues of a step without the missing module settings; its "set up" pill covers those. */
function stepOwnIssues(index, mod) {
  const moduleKeys = new Set(((mod && mod.fields) || []).map((spec) => spec.key));
  return issuesAt(state.issues, ['steps', index])
    .filter((issue) => !(issue.path[2] === 'config' && moduleKeys.has(issue.path.slice(3).join('.'))));
}

/**
 * Switches of the services whose data is added to the items of a source. Only
 * set-up modules of another category are offered (a Jellyfin source gets no
 * Plex data); a service the flow already uses stays listed so it can be turned off.
 */
function renderEnrichEditor(source) {
  const { funnel } = readFunnel();
  const lane = funnel && funnel.lanes.find((item) => item.source === source);
  const sourceModule = moduleDef(source.module);
  if (!lane || !sourceModule) return [];
  const choices = state.catalog
    .map((mod) => [mod, mod.actions.find((action) => action.stage === 'enrich'), lane.enrich.find((item) => item.module === mod.id)])
    .filter(([mod, action, step]) => action && (step
      || (mod.id !== source.module && mod.category !== sourceModule.category && !moduleNeedsSetup(mod))));
  if (!choices.length) return [];
  const rows = choices.map(([mod, action, step]) => {
    const index = step ? state.flow.steps.indexOf(step) : -1;
    // off: no step; on: add the data when found; must: also drop items without a match
    const strict = action.fields.some((spec) => spec.key === MUST_MATCH);
    const current = !step ? 'off' : getPath(step.config || {}, MUST_MATCH) === true ? 'must' : 'on';
    const pick = (value) => {
      if (value === 'off') { toggleEnrich(source, mod.id, action.id, false); return; }
      if (!step) {
        toggleEnrich(source, mod.id, action.id, true, value === 'must' ? { [MUST_MATCH]: true } : undefined);
        return;
      }
      const next = clone(step.config) || {};
      setPath(next, MUST_MATCH, value === 'must' ? true : undefined);
      if (isEmpty(next)) delete step.config; else step.config = next;
      markDirty();
      render();
    };
    const options = [['off', 'Off', 'Do not add this data'], ['on', 'On', 'Add the data when the item is found']];
    if (strict) options.push(['must', 'Must', 'Add the data and drop the items that are not found']);
    const control = h('div', { class: 'segmented small', role: 'radiogroup', 'aria-label': mod.label });
    options.forEach(([value, text, hint]) => control.append(h('button', {
      type: 'button', role: 'radio', 'aria-checked': String(current === value), class: current === value ? 'active' : '', title: hint,
      onclick: () => { if (current !== value) pick(value); },
    }, text)));
    return h('div', { class: `enrich-option${step ? ' on' : ''} ${categoryClass(mod)}`, title: action.description },
      h('div', { class: 'enrich-row' }, h('span', { class: 'enrich-name' }, mod.label), step ? setupPill(step) : null, control),
      step ? h('div', { dataset: { stepIssues: String(index), module: mod.id } }, issueList(stepOwnIssues(index, mod)) || '') : null);
  });
  return [
    h('div', { class: 'section-title first' }, 'Add data from'),
    h('p', { class: 'muted small enrich-intro' }, 'Look up every item in these services. ',
      h('strong', {}, 'On'), ' adds the data when the item is found, ',
      h('strong', {}, 'Must'), ' also drops the items that are not found.'),
    h('div', { class: 'enrich-list' }, rows),
  ];
}

function stageColumn(number, title, hint, body, footer) {
  return h('div', { class: 'stage' },
    h('div', { class: 'stage-head' }, h('span', { class: 'stage-num' }, number), h('h2', {}, title)),
    h('p', { class: 'muted small stage-hint' }, hint),
    h('div', { class: 'stage-body' }, body),
    footer);
}

function stageAdd(text, onclick, disabled, title) {
  return h('button', { type: 'button', class: 'stage-add', onclick, disabled, title }, text);
}

function renderBoard() {
  const board = h('div', { class: 'board', id: 'board' });
  const { funnel, reason } = readFunnel();
  if (!funnel) {
    board.classList.add('board-blocked');
    board.append(h('div', { class: 'panel' },
      h('h2', {}, 'This flow cannot be shown in the editor'),
      h('p', {}, reason),
      h('p', { class: 'muted small' }, 'The editor shows flows of the form sources → filters → actions. '
        + 'This flow keeps running as before; edit its YAML file by hand, or split it into several flows. '
        + 'The schedule, media kind and priority above can still be changed.')));
    return board;
  }
  const hasSource = funnel.lanes.length > 0;
  const canMerge = Boolean(combineAction());
  const lanes = funnel.lanes.map((lane) => simpleCard(lane.source, lane));
  board.append(
    stageColumn(1, 'Sources', 'Where the items come from, and what to add to them.', [
      lanes,
      funnel.lanes.length > 1 ? h('div', { class: 'merge-note' }, h('span', { 'aria-hidden': 'true' }, '⤵'),
        'The sources are merged into one list; duplicates are removed.') : null,
    ], hasSource && !canMerge ? null : stageAdd(hasSource ? '+ Add another source' : '+ Add a source',
      () => openStagePicker('source', addStep((current, step) => current.lanes.push({ source: step, enrich: [] }))))),
    h('div', { class: 'board-link', 'aria-hidden': 'true' }),
    stageColumn(2, 'Filters', 'Optional. Keep only the items you want, or add data to the items left.',
      funnel.filters.length ? funnel.filters.map((step) => simpleCard(step))
        : h('p', { class: 'stage-empty' }, 'No filters: every item goes on.'),
      stageAdd('+ Add filter or data', () => openStagePicker('filter', addStep((current, step) => current.filters.push(step))),
        !hasSource, hasSource ? undefined : 'Add a source first')),
    h('div', { class: 'board-link', 'aria-hidden': 'true' }),
    stageColumn(3, 'Actions', 'What happens with the items.',
      funnel.outputs.length ? funnel.outputs.map((step) => simpleCard(step))
        : h('p', { class: 'stage-empty' }, 'No actions yet. Without one the flow changes nothing.'),
      stageAdd('+ Add an action', () => openStagePicker('output', addStep((current, step) => current.outputs.push(step))),
        !hasSource, hasSource ? undefined : 'Add a source first')));
  return board;
}

/* -------------------------------------------------------------- test runs */

async function runTest(until) {
  if (!state.flow || !(state.flow.steps || []).length || state.testing) return;
  state.testing = true;
  state.testUntil = until;
  state.test = null;
  state.testPage = null;
  state.testStale = false;
  render();
  document.getElementById('test-panel')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  try {
    state.test = await api('POST', 'flows/test', { flow: state.flow, id: state.flowId || undefined, until });
    const last = state.test.steps[state.test.steps.length - 1];
    state.testStep = last ? state.test.steps.length - 1 : null;
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

function rerenderTestPanel() {
  const panel = document.getElementById('test-panel');
  if (panel) panel.replaceWith(renderTestPanel());
}

/** Show another page of a step result; pages after the first are read from the server. */
async function showTestPage(position, page) {
  const test = state.test;
  const result = test && test.steps[position];
  if (!result) return;
  if (page === 0) {
    state.testPage = null;
    rerenderTestPanel();
    return;
  }
  state.testPage = { position, page, loading: true, items: (state.testPage && state.testPage.items) || result.items };
  rerenderTestPanel();
  try {
    const data = await api('GET', `flows/test/${test.id}/${position}/${page}`);
    if (state.test === test) { state.testPage = { position, page, items: data.items }; rerenderTestPanel(); }
  } catch (err) {
    state.testPage = null;
    toast(err.message, 'err');
    rerenderTestPanel();
  }
}

function renderItemsTable(result, position) {
  if (!result.items.length) {
    return h('p', { class: 'muted small' }, result.count === null ? 'No output.' : 'No items.');
  }
  const size = (state.test && state.test.page_size) || result.items.length;
  const kept = result.kept ?? result.items.length;
  const pages = Math.max(1, Math.ceil(kept / size));
  const current = state.testPage && state.testPage.position === position ? state.testPage : null;
  const page = current ? current.page : 0;
  const items = current ? current.items : result.items;
  const keys = new Set();
  items.forEach((item) => Object.keys(item).forEach((key) => keys.add(key)));
  const columns = PREVIEW_COLUMNS.filter((key) => keys.has(key))
    .concat([...keys].filter((key) => !PREVIEW_COLUMNS.includes(key))).slice(0, 12);
  const first = page * size + 1;
  const pager = pages > 1 && state.test && state.test.id ? h('div', { class: 'pager' },
    h('button', { class: 'btn small', disabled: page === 0 || (current && current.loading), title: 'First page', onclick: () => showTestPage(position, 0) }, '«'),
    h('button', { class: 'btn small', disabled: page === 0 || (current && current.loading), title: 'Previous page', onclick: () => showTestPage(position, page - 1) }, '‹'),
    h('span', { class: 'pager-text' }, current && current.loading ? 'Loading…' : `Page ${page + 1} of ${pages}`),
    h('button', { class: 'btn small', disabled: page >= pages - 1 || (current && current.loading), title: 'Next page', onclick: () => showTestPage(position, page + 1) }, '›'),
    h('button', { class: 'btn small', disabled: page >= pages - 1 || (current && current.loading), title: 'Last page', onclick: () => showTestPage(position, pages - 1) }, '»')) : null;
  return h('div', {},
    h('div', { class: 'pager-row' },
      h('p', { class: 'muted small' }, `Items ${first}–${first + items.length - 1} of ${result.count}`,
        kept < result.count ? ` (the first ${kept} can be browsed)` : '', '.'),
      pager),
    h('div', { class: 'table-wrap' }, h('table', { class: 'items' },
      h('thead', {}, h('tr', {}, columns.map((key) => h('th', {}, key === 'poster' ? '' : key)))),
      h('tbody', {}, items.map((item) => h('tr', {},
        columns.map((key) => h('td', { class: `col-${key}` }, cellValue(key, item[key])))))))));
}

function renderTestPanel() {
  if (!state.testing && !state.test) return null;
  const test = state.test;
  const selected = test && state.testStep !== null ? test.steps[state.testStep] : null;
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
    test ? h('div', { class: 'test-steps' }, test.steps.map((item, position) => h('button', {
      class: `test-step${position === state.testStep ? ' active' : ''}`,
      onclick: () => { state.testStep = position; state.testPage = null; rerenderTestPanel(); },
    },
    h('span', { class: 'step-index' }, item.index + 1),
    h('span', { class: 'grow' }, item.name || '(unnamed)', item.kind ? h('span', { class: 'muted' }, ` · ${KIND_LABELS[item.kind] || item.kind}`) : null),
    resultPill(item),
    h('span', { class: 'muted small' }, `${item.duration}s`)))) : null,
    selected && selected.message ? h('p', { class: `field-issue ${selected.status === 'failed' ? 'error' : 'warning'}` }, selected.message) : null,
    selected ? renderItemsTable(selected, state.testStep) : null,
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
  const gridOf = (specs) => h('div', { class: 'form-grid settings-grid' }, arrangeFields(specs.map((spec) => renderSpec(spec))));
  const renderSpec = (spec) => {
    // an environment variable overrides the setting: shown, not editable
    const env = (item.environment || {})[spec.key];
    if (env) {
      const field = fieldInput({ ...spec, type: spec.type === 'secret' ? 'secret' : 'string' },
        env.value ?? undefined, () => {}, { placeholder: spec.type === 'secret' ? '•••••••• (set)' : '' });
      field.querySelectorAll('input, select, textarea, button').forEach((el) => { el.disabled = true; });
      field.append(h('div', { class: 'hint path-hint' }, env.value
        ? `Set by the ${env.name} environment variable: ${env.value}`
        : `Set by the ${env.name} environment variable.`));
      return field;
    }
    // a stored secret shows a mask: kept while unchanged, replaced by typing, deleted when emptied
    const secretSet = spec.type === 'secret' && item.secrets.includes(spec.key);
    const cleared = () => draft.clear.includes(spec.key);
    const warning = secretSet ? h('div', { class: 'issue warning', hidden: !cleared() },
      'The stored value is deleted when you save.') : null;
    const onSecret = (value) => {
      draft.clear = draft.clear.filter((key) => key !== spec.key);
      if (value === undefined) draft.clear.push(spec.key);
      set(spec.key, value === SECRET_MASK ? undefined : value);
      warning.hidden = !cleared();
    };
    // the default export directory is a full path of this installation, shown whole under the field
    const exportRoot = item.module === 'library' && spec.key === 'export_directory' && state.defaultExportDir;
    if (exportRoot) spec = { ...spec, description: `${spec.description.replace(/ Empty:.*$/, '')} Default: ${state.defaultExportDir}` };
    const value = getPath(draft.config, spec.key);
    return fieldInput(spec, secretSet && value === undefined ? (cleared() ? '' : SECRET_MASK) : value,
      secretSet ? onSecret : (next) => set(spec.key, next), {
        issues: at(spec.key),
        wide: wide.has(spec.key),
        placeholder: exportRoot ? 'default' : undefined,
        // the main connection has no other values to inherit, so yes/no is a switch
        switch: item.default,
        secretSet,
        // dropdowns read their values with the saved settings of this connection
        choicesFrom: item.id,
        extra: warning,
      });
  };
  panel.append(...[
    h('div', { class: 'panel-head' }, moduleBadge(mod), h('h2', {}, item.default ? mod.label : item.name), h('span', { class: 'spacer' }),
      // the connection test result sits beside the validation state; the details are its tooltip
      item.test ? h('span', { class: `pill ${item.test.ok ? 'ok' : 'err'}`, title: item.test.message }, item.test.ok ? 'connected' : 'failed') : null,
      statusPill(item.status)),
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
    // a failed test explains itself below the settings
    item.test && !item.test.ok ? h('div', { class: 'issue error' }, item.test.message) : null,
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
  const cleared = state.instanceDraft ? state.instanceDraft.clear : [];
  if (cleared.length) {
    const mod = moduleDef(instanceById(state.instanceId)?.module);
    const names = cleared.map((key) => (mod?.fields || []).find((spec) => spec.key === key)?.label || key);
    if (!window.confirm(`The stored ${names.join(', ')} will be deleted. Save anyway?`)) return;
  }
  try {
    const result = await api('PUT', `instances/${encodeURIComponent(state.instanceId)}`, instancePayload());
    choiceCache.clear();
    await refreshInstances();
    // the library settings move the export directory shown in the flow header
    if (instanceById(result.id)?.module === 'library') {
      state.exportDir = (await api('GET', 'catalog')).export_directory || state.exportDir;
    }
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
