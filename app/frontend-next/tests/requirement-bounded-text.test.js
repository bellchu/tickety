const assert = require('node:assert/strict');
const test = require('node:test');
const { loadPureTs, loadComponentTs } = require('./helpers/load-pure-ts');
const { RequirementInput, RequirementTextarea } = loadComponentTs('requirements/BoundedText.tsx', {
  'react/jsx-runtime': require('react/jsx-runtime'),
  '@/lib/requirement-text': loadPureTs('requirement-text.ts'),
});
function control(Component, props) {
  const element = Component(props);
  let message;
  element.props.ref({ setCustomValidity: value => { message = value; } });
  assert.equal(element.props.value, props.value, 'the supplied text is retained');
  assert.equal(element.props.maxLength, undefined, 'native UTF-16 truncation must not apply');
  assert.equal(element.props.minLength, undefined);
  return { element, message };
}
test('business notes reject five emoji and allow ten by API character count', () => {
  const props = { required: true, minLength: 10, maxLength: 4000 };
  assert.match(control(RequirementTextarea, { ...props, value: '😀'.repeat(5) }).message, /10–4,000/);
  assert.equal(control(RequirementTextarea, { ...props, value: '😀'.repeat(10) }).message, '');
});
test('titles preserve supplementary characters up to the character boundary', () => {
  assert.equal(control(RequirementInput, { required: true, maxLength: 200, value: '  ' + '𠮷'.repeat(200) + '  ' }).message, '');
  const invalid = control(RequirementInput, { required: true, maxLength: 200, value: '𠮷'.repeat(201) });
  assert.match(invalid.message, /1–200/);
  assert.equal(invalid.element.props['aria-invalid'], true);
});
test('required whitespace, optional empty fields and control characters have distinct validity', () => {
  assert.match(control(RequirementInput, { required: true, maxLength: 200, value: '   ' }).message, /1–200/);
  assert.equal(control(RequirementInput, { maxLength: 200, value: '' }).message, '');
  assert.match(control(RequirementTextarea, { maxLength: 4000, value: 'Business\0 outcome' }).message, /control characters/);
});
