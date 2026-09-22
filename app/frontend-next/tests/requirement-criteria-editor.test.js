const { descendants } = require('./helpers/react-tree');
const assert = require('node:assert/strict');
const test = require('node:test');
const { loadComponentTs, loadPureTs } = require('./helpers/load-pure-ts');
const parse = loadPureTs('requirement-criteria.ts', { './requirement-text': loadPureTs('requirement-text.ts') }).parseRequirementCriteria;
let hooks;
const { AcceptanceCriteriaEditor: Editor } = loadComponentTs('requirements/AcceptanceCriteriaEditor.tsx', {
  react: {
    memo: component => component,
    useRef: initial => hooks.refs[hooks.cursor++] ||= { current: initial },
    useEffect: effect => { hooks.effects.push(effect); },
  }, 'react/jsx-runtime': require('react/jsx-runtime'),
  '@/components/ui': { Button: 'button' }, './fields': { Field: 'label', inputStyle: '' },
});
function editor(initial) {
  let criteria = initial;
  const state = { refs: [], cursor: 0, effects: [] };
  let focused = null;
  let focusCalls = 0;
  return {
    get focused() { return focused; },
    get focusCalls() { return focusCalls; },
    get criteria() { return criteria; },
    render() {
      const validation = parse(criteria);
      hooks = state; state.cursor = 0; state.effects = [];
      const tree = Editor({ criteria, issue: validation.issue, invalidIndex: validation.invalidIndex, count: validation.criteria.length, onChange: next => { criteria = next; } });
      state.refs[0].current = {
        querySelectorAll: () => criteria.map((_, index) => ({ focus: () => { focused = index; focusCalls++; } })),
        querySelector: () => ({ focus: () => { focused = 'add'; focusCalls++; } }),
      };
      state.effects.forEach(effect => effect());
      return tree;
    },
  };
}

test('editing and removing a middle criterion keeps neighboring multiline commitments intact', () => {
  const original = ['Given valid input,\nreturn a receipt.', 'Queue the request for retry.', 'When the retry succeeds,\nrecord its completion.'];
  const form = editor(original);
  descendants(form.render(), 'textarea')[1].props.onChange({ target: { value: 'On failure,\nqueue the request for retry.' } });
  assert.equal(form.criteria.length, 3);
  assert.equal(form.criteria[0], original[0]);
  assert.equal(form.criteria[2], original[2]);
  descendants(form.render(), 'button')[1].props.onClick();
  assert.deepEqual(form.criteria, [original[0], original[2]]);
  assert.equal(original[1], 'Queue the request for retry.');
});

test('adding the twentieth criterion stops further additions until one is removed', () => {
  const form = editor(Array(19).fill('Return a receipt.'));
  let buttons = descendants(form.render(), 'button');
  assert.equal(buttons.at(-1).props.disabled, false);
  buttons.at(-1).props.onClick();
  assert.equal(form.criteria.length, 20);
  buttons = descendants(form.render(), 'button');
  assert.equal(buttons.at(-1).props.disabled, true);
  buttons[19].props.onClick();
  assert.equal(descendants(form.render(), 'button').at(-1).props.disabled, false);
});

test('validation marks the original input position and clears after correction', () => {
  const form = editor(['Return a receipt.', '', 'short']);
  let fields = descendants(form.render(), 'textarea');
  assert.deepEqual(fields.map(field => field.props['aria-invalid']), [false, false, true]);
  fields[2].props.onChange({ target: { value: 'Record the receipt timestamp.' } });
  fields = descendants(form.render(), 'textarea');
  assert.deepEqual(fields.map(field => field.props['aria-invalid']), [false, false, false]);
});


test('add and remove move focus to a useful entry without stealing focus during typing', () => {
  const form = editor(['Return a receipt.', 'Record the timestamp.']);
  let tree = form.render();
  assert.equal(form.focused, null);
  descendants(tree, 'button').at(-1).props.onClick();
  tree = form.render();
  assert.equal(form.focused, 2);
  descendants(tree, 'button')[2].props.onClick();
  tree = form.render();
  assert.equal(form.focused, 1);
  descendants(tree, 'button')[0].props.onClick();
  tree = form.render();
  assert.equal(form.focused, 0);
  descendants(tree, 'button')[0].props.onClick();
  tree = form.render();
  assert.equal(form.focused, 'add');
  descendants(tree, 'button').at(-1).props.onClick();
  tree = form.render();
  assert.equal(form.focused, 0);
  const callsBeforeTyping = form.focusCalls;
  descendants(tree, 'textarea')[0].props.onChange({ target: { value: 'Return the receipt.' } });
  form.render();
  assert.equal(form.focused, 0);
  assert.equal(form.focusCalls, callsBeforeTyping);
});
