/* CineFlow simple flow editor model ("funnel").
 *
 * A funnel is a view of an ordinary step list: one or more source lanes
 * (a source step and the steps that add data to its items), an automatic
 * merge when there are several lanes, then filters (and steps adding data to
 * the filtered items, in their order) and output actions on the merged items:
 *
 *   {lanes: [{source, enrich: [...]}], combine, filters: [...], outputs: [...]}
 *
 * Every entry is the step object itself, so editing a step's settings needs no
 * conversion. `toFunnel` reads a step list (or explains why it does not fit),
 * `fromFunnel` writes it back in a fixed order and wires every step input.
 * The YAML format does not change; a flow that does not fit is shown with
 * the reason and edited by hand.
 *
 * Works as a browser script (global `CineFunnel`) and as a Node module (tests).
 */
'use strict';

(function factory(root, build) {
  const api = build();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.CineFunnel = api;
}(typeof self !== 'undefined' ? self : this, () => {
  const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
  const isRef = (value) => typeof value === 'string' && value.startsWith('{{') && value.endsWith('}}');
  const refName = (value) => value.slice(2, -2).trim();
  const isDataWord = (value) => value === 'previous' || value === 'none' || value === '' || isRef(value);

  /**
   * Item input of a step: null (none), 'previous', {ref: name} or {list: [names]};
   * undefined when the input has a shape this view cannot represent.
   */
  function dataOf(input) {
    if (input === undefined || input === null || input === '' || input === 'none') return null;
    if (input === 'previous') return 'previous';
    if (isRef(input)) return { ref: refName(input) };
    if (typeof input === 'string') return null; // a plain search text
    if (Array.isArray(input)) {
      if (!input.every((item) => typeof item === 'string')) return undefined;
      return { list: input.map((item) => (isRef(item) ? refName(item) : item)) };
    }
    if (isObject(input)) return 'data' in input ? dataOf(input.data) : null;
    return undefined;
  }

  /** The input with its item data replaced; query and arguments are kept. */
  function withData(input, data) {
    if (isObject(input)) {
      const rest = { ...input };
      delete rest.data;
      return Object.keys(rest).length ? { data, ...rest } : data;
    }
    if (typeof input === 'string' && !isDataWord(input)) return { data, query: input };
    return data;
  }

  /** The input without item data (sources start a lane). */
  function withoutData(input) {
    if (isObject(input)) {
      const rest = { ...input };
      delete rest.data;
      return Object.keys(rest).length ? rest : undefined;
    }
    if (typeof input === 'string' && !isDataWord(input)) return input;
    return undefined;
  }

  const fail = (reason) => ({ funnel: null, reason });
  const label = (step) => `"${step.name}"`;

  /**
   * Read a step list as a funnel. `stageOf(step)` returns the stage of the
   * step's action ('source', 'enrich', 'combine', 'filter', 'output') or null.
   * Returns {funnel} or {funnel: null, reason}.
   */
  function toFunnel(steps, stageOf) {
    const funnel = { lanes: [], combine: null, filters: [], outputs: [] };
    if (steps === undefined || steps === null) return { funnel };
    if (!Array.isArray(steps)) return fail('The flow has no step list.');
    const names = new Set();
    let previous = null; // the step before the current one
    let end = null;      // the step whose items the next trunk step works on
    for (const [index, step] of steps.entries()) {
      if (!isObject(step) || typeof step.name !== 'string' || !step.name.trim()) {
        return fail(`Step ${index + 1} has no name.`);
      }
      if (names.has(step.name)) return fail(`The step name ${label(step)} is used twice.`);
      names.add(step.name);
      const data = dataOf(step.input);
      if (data === undefined) return fail(`${label(step)} has a custom input.`);
      const fromPrevious = (data === 'previous' && (previous === null || previous === end))
        || (isObject(data) && data.ref !== undefined && end !== null && data.ref === end.name);
      const trunkStarted = funnel.combine || funnel.filters.length || funnel.outputs.length;
      const merged = funnel.lanes.length < 2 || funnel.combine;
      switch (stageOf(step)) {
        case 'source':
          if (data !== null) return fail(`${label(step)} collects items but also takes the items of another step.`);
          if (trunkStarted) return fail(`${label(step)} starts a second pipeline after the filters or actions.`);
          funnel.lanes.push({ source: step, enrich: [] });
          end = step;
          break;
        case 'enrich': {
          const lane = funnel.lanes[funnel.lanes.length - 1];
          if (lane && !trunkStarted) {
            if (!(data === 'previous' || (isObject(data) && data.ref === previous.name))) {
              return fail(`${label(step)} does not work on the items of the step before it.`);
            }
            lane.enrich.push(step);
            end = step;
            break;
          }
          // after the merge or a filter, adding data is a step of the filtered items
          if (!merged) return fail(`${label(step)} adds data to only one of several sources.`);
          if (funnel.outputs.length) return fail(`${label(step)} adds data after an action.`);
          if (!fromPrevious) return fail(`${label(step)} does not work on the items of the step before it.`);
          funnel.filters.push(step);
          end = step;
          break;
        }
        case 'combine': {
          if (funnel.lanes.length < 2 || trunkStarted) return fail(`${label(step)} merges items outside the source merge.`);
          const ends = funnel.lanes.map((lane) => (lane.enrich[lane.enrich.length - 1] || lane.source).name);
          const list = isObject(data) && data.list ? data.list : [];
          if (list.length !== ends.length || !ends.every((name) => list.includes(name))) {
            return fail(`${label(step)} does not merge exactly the sources.`);
          }
          funnel.combine = step;
          end = step;
          break;
        }
        case 'filter':
          if (!merged) return fail(`${label(step)} filters only one of several sources.`);
          if (funnel.outputs.length) return fail(`${label(step)} filters after an action.`);
          if (!fromPrevious) return fail(`${label(step)} does not work on the items of the step before it.`);
          funnel.filters.push(step);
          end = step;
          break;
        case 'output':
          if (!merged) return fail(`${label(step)} works on only one of several sources.`);
          if (!fromPrevious && !(data === 'previous' && end === null)) {
            return fail(`${label(step)} does not work on the result of the filters.`);
          }
          funnel.outputs.push(step);
          break;
        default:
          return fail(`${label(step)} uses an action the simple editor does not know.`);
      }
      previous = step;
    }
    return { funnel };
  }

  /**
   * Write a funnel back as a step list, wiring every input. The step objects
   * are updated in place. `newCombine()` returns a new merge step and is
   * called when several sources have none yet.
   */
  function fromFunnel(funnel, newCombine) {
    const steps = [];
    const ends = [];
    funnel.lanes.forEach((lane) => {
      lane.source.input = withoutData(lane.source.input);
      if (lane.source.input === undefined) delete lane.source.input;
      steps.push(lane.source);
      lane.enrich.forEach((step) => {
        step.input = withData(step.input, 'previous');
        steps.push(step);
      });
      ends.push(steps[steps.length - 1].name);
    });
    if (ends.length > 1) {
      funnel.combine = funnel.combine || newCombine();
      // keep the written order when the merged sources did not change
      const current = dataOf(funnel.combine.input);
      const same = isObject(current) && current.list && current.list.length === ends.length
        && ends.every((name) => current.list.includes(name));
      if (!same) funnel.combine.input = withData(funnel.combine.input, ends.slice());
      steps.push(funnel.combine);
    } else {
      funnel.combine = null;
    }
    funnel.filters.forEach((step) => {
      step.input = withData(step.input, 'previous');
      steps.push(step);
    });
    const result = steps.length ? steps[steps.length - 1].name : null;
    funnel.outputs.forEach((step, index) => {
      step.input = withData(step.input, index === 0 || result === null ? 'previous' : `{{${result}}}`);
      steps.push(step);
    });
    return steps;
  }

  return { toFunnel, fromFunnel, dataOf, withData, withoutData };
}));
