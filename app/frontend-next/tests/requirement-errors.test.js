const assert = require('node:assert/strict');
const test = require('node:test');
const { loadPureTs } = require('./helpers/load-pure-ts');
const library = loadPureTs('requirement-errors.ts');
const format = library.requirementErrorMessage;
const apiError = (message, status) => Object.assign(new Error(message), { status });

test('AI failures explain recovery and preserve the manual workflow', () => {
  for (const code of ['ai_unavailable', 'invalid_ai_output', 'ai_rate_limit_exceeded', 'ai_daily_budget_exceeded']) {
    const message = format(apiError(code, code.includes('exceeded') ? 429 : 503));
    assert.match(message, /manual/);
    assert.ok(!message.includes(code));
  }
});
test('business conflicts and file validation retain their actionable detail', () => {
  for (const [message, status] of [
    ['This requirement changed. Refresh before saving or validating.', 409],
    ['Resolve the blocking business questions before sign-off', 409],
    ['Evidence must be an exact excerpt from the selected source', 422],
    ['Choose a file smaller than 400 KB.', undefined],
  ]) assert.equal(format(apiError(message, status)), message);
});
test('generic responses and server failures do not expose endpoints or raw proxy pages', () => {
  for (const status of [400, 401, 403, 404, 409, 422, 429, 500, 502, 503]) {
    for (const message of [`API /requirements/private-id failed: ${status}`, '<html>Proxy failure</html>']) {
      assert.doesNotMatch(format(apiError(message, status)), /private-id|<html>|API /);
    }
  }
  assert.doesNotMatch(format(apiError('Internal database failure', 500)), /database/);
});
test('uncertain outcomes prompt checking saved work instead of claiming no mutation', () => {
  for (const error of [null, {}, new Error(''), new TypeError('Failed to fetch'), new TypeError('Load failed'), apiError('oops', 503)]) {
    assert.match(format(error), /latest saved work/);
    assert.doesNotMatch(format(error), /unchanged|not saved/);
  }
  assert.equal(format(new Error('toString')), 'toString');
});
