const assert = require('node:assert/strict');
const test = require('node:test');
const React = require('react');
const { loadComponentTs, loadPureTs } = require('./helpers/load-pure-ts');
const parse = loadPureTs('requirement-criteria.ts', { './requirement-text': loadPureTs('requirement-text.ts') }).parseRequirementCriteria;
const { AcceptanceCriteriaEditor: Editor } = loadComponentTs('requirements/AcceptanceCriteriaEditor.tsx', {
  react: { memo: component => component }, 'react/jsx-runtime': require('react/jsx-runtime'),
  '@/components/ui': { Button: 'button' }, './fields': { Field: 'label', inputStyle: '' },
});
function descendants(node, type) {
  if (!node || typeof node !== 'object') return [];
  return [...(node.type === type ? [node] : []), ...React.Children.toArray(node.props?.children).flatMap(child => descendants(child, type))];
}
function editor(initial) {
  let criteria = initial;
  return {
    get criteria() { return criteria; },
    render() {
      const validation = parse(criteria);
      return Editor({ criteria, issue: validation.issue, invalidIndex: validation.invalidIndex, count: validation.criteria.length, onChange: next => { criteria = next; } });
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
