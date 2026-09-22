const assert = require('node:assert/strict');
const test = require('node:test');
const { loadPureTs } = require('./helpers/load-pure-ts');
const library = loadPureTs('requirement-workspace.ts');
const { workspaceFocus, filterRequirements } = library;
const item = { id: 'r1', reference: 'REQ-001', title: 'Receipt', actor: 'Analyst', action: 'Track intake', benefit: 'Avoid delays', source_id: 's1', status: 'draft', quality_issues: [], story: null };
const detail = (items = [], sources = [{ id: 's1', title: 'SOP' }]) => ({ requirements: items, sources });
test('focus follows evidence and unresolved business questions before sign-off', () => {
  assert.equal(workspaceFocus(detail([], [])).action, 'source');
  assert.equal(workspaceFocus(detail()).action, 'gather');
  assert.equal(workspaceFocus(detail([item])).action, 'review');
  assert.equal(workspaceFocus(detail([item, { ...item, id: 'r2', quality_issues: ['Confirm outcome'] }])).action, 'questions');
});
test('agreement permits story preparation and revisions return to review', () => {
  const agreed = { ...item, status: 'validated' };
  assert.equal(workspaceFocus(detail([agreed])).action, 'story');
  assert.equal(workspaceFocus(detail([{ ...agreed, story: {} }])).action, 'export');
  assert.equal(workspaceFocus(detail([item])).action, 'review');
});
test('new evidence reopens exploration even when existing work has stories', () => {
  assert.equal(workspaceFocus(detail([{ ...item, status: 'validated', story: {} }], [{ id: 's1', title: 'SOP' }, { id: 's2', title: 'New policy' }])).sourceId, 's2');
});
test('search combines with readiness filters without treating agreement as a story', () => {
  const items = [item, { ...item, id: 'r2', quality_issues: ['Clarify'] }, { ...item, id: 'r3', status: 'validated' }, { ...item, id: 'r4', status: 'validated', story: {} }];
  assert.deepEqual(filterRequirements(items, ' ANALYST ', 'review').map(x => x.id), ['r1']);
  assert.deepEqual(filterRequirements(items, '', 'questions').map(x => x.id), ['r2']);
  assert.deepEqual(filterRequirements(items, '', 'delivery').map(x => x.id), ['r4']);
  assert.equal(filterRequirements(items, 'missing', 'all').length, 0);
});
test('business blockers take precedence and affect only their scope in filtered views', () => {
  const decisions = [{ requirement_id: 'r1', blocking: true, status: 'open', owner_role: 'Sponsor', question: 'Who owns the exception path?' }];
  assert.equal(workspaceFocus({ ...detail([item]), decisions }).action, 'decisions');
  assert.equal(filterRequirements([item], '', 'review', decisions).length, 0);
  assert.equal(filterRequirements([item], '', 'questions', decisions).length, 1);
  assert.equal(filterRequirements([{ ...item, id: 'r2' }], '', 'review', decisions).length, 1);
  assert.equal(workspaceFocus({ ...detail([item]), decisions: [{ ...decisions[0], status: 'resolved' }] }).action, 'review');
});
test('deferred requirements remain discoverable without demanding review or delivery', () => {
  const deferred = { ...item, priority: 'wont', quality_issues: ['Clarify the future outcome'] };
  assert.equal(workspaceFocus(detail([deferred])).action, 'deferred');
  assert.equal(filterRequirements([deferred], '', 'all').length, 1);
  assert.equal(filterRequirements([deferred], '', 'deferred').length, 1);
  for (const filter of ['questions', 'review', 'delivery']) assert.equal(filterRequirements([{ ...deferred, story: {} }], '', filter).length, 0);
  const current = { ...item, id: 'r2' };
  const decisions = [{ requirement_id: 'r1', blocking: true, status: 'open', owner_role: 'Sponsor', question: 'Future question' }];
  assert.equal(workspaceFocus({ ...detail([deferred, current]), decisions }).item.id, 'r2');
});

test('blocker indexing distinguishes global, scoped, resolved and exploratory decisions', () => {
  const items = [item, { ...item, id: 'r2' }, { ...item, id: 'r3', priority: 'wont' }];
  const decisions = [
    { requirement_id: 'r1', status: 'open', blocking: true },
    { requirement_id: 'r1', status: 'open', blocking: true },
    { requirement_id: 'r3', status: 'open', blocking: true },
    { requirement_id: null, status: 'resolved', blocking: true },
    { requirement_id: 'r2', status: 'open', blocking: false },
  ];
  assert.deepEqual([...library.blockedRequirementIds(items, decisions)], ['r1', 'r3']);
  assert.deepEqual(filterRequirements(items, '', 'questions', decisions).map(row => row.id), ['r1']);
  assert.deepEqual(filterRequirements(items, '', 'review', decisions).map(row => row.id), ['r2']);
  decisions.push({ requirement_id: null, status: 'open', blocking: true });
  assert.deepEqual([...library.blockedRequirementIds(items, decisions)], ['r1', 'r2', 'r3']);
  assert.deepEqual(filterRequirements(items, '', 'questions', decisions).map(row => row.id), ['r1', 'r2']);
});


test('source coverage includes deferred evidence and counts multiple linked requirements', () => {
  const counts = library.sourceRequirementCounts([item, { ...item, id: 'r2', priority: 'wont' }, { ...item, id: 'r3', source_id: 's2' }]);
  assert.equal(counts.get('s1'), 2);
  assert.equal(counts.get('s2'), 1);
  assert.equal(counts.has('unlinked'), false);
  assert.equal(library.sourceRequirementCounts([]).size, 0);
});


test('decision views separate blockers, exploration and recorded answers while retaining an active draft', () => {
  const decisions = [
    { id: 'a', status: 'open', blocking: true, question: 'Who owns failures?', owner_role: 'Operations', resolution: null },
    { id: 'b', status: 'open', blocking: false, question: 'Additional channels?', owner_role: 'Sponsor', resolution: null },
    { id: 'c', status: 'resolved', blocking: true, question: 'Which deadline?', owner_role: 'Sponsor', resolution: 'Five minutes' },
  ];
  const ids = (view, search = '', editing = '') => library.filterDecisions(decisions, view, search, editing).map(item => item.id);
  assert.deepEqual(ids('open'), ['a', 'b']);
  assert.deepEqual(ids('blocking'), ['a']);
  assert.deepEqual(ids('exploratory'), ['b']);
  assert.deepEqual(ids('recorded', '  FIVE  '), ['c']);
  assert.deepEqual(ids('all', 'sponsor'), ['b', 'c']);
  assert.deepEqual(ids('recorded', 'missing', 'a'), ['a']);
  assert.deepEqual(ids('open', 'missing'), []);
});


test('requirements can be found by evidence, acceptance criteria and story references across wrapped text', () => {
  const row = { ...item, evidence_quote: 'Supplier receipt\nwithin thirty seconds.', acceptance_criteria: ['Given an outage, queue the acknowledgement.'], story: { reference: 'US-017', title: 'Confirm supplier intake', statement: 'As an analyst, I want a durable receipt.' } };
  for (const query of [' receipt within ', 'OUTAGE', 'us-017', 'durable receipt', 'Confirm supplier intake']) {
    assert.equal(filterRequirements([row], query, 'all').length, 1, query);
  }
  assert.equal(filterRequirements([row], 'supplier missing', 'all').length, 0);
  assert.equal(filterRequirements([{ ...row, priority: 'wont' }], 'outage', 'delivery').length, 0);
  assert.equal(filterRequirements([{ ...row, priority: 'wont' }], 'outage', 'deferred').length, 1);
});


test('review availability rejects stale snapshots and changed business gates', () => {
  const reviewed = { ...item, revision: 2, priority: 'must' };
  const check = (current, blocked = false) => library.reviewUnavailableReason(reviewed, current, blocked);
  assert.equal(check(reviewed), null);
  assert.match(check({ ...reviewed, revision: 3 }), /changed to revision 3/);
  assert.match(check(undefined), /no longer available/);
  assert.match(check({ ...reviewed, priority: 'wont' }), /outside/);
  assert.match(check({ ...reviewed, status: 'validated' }), /already been signed off/);
  assert.match(check(reviewed, true), /blocking business questions/);
  assert.match(check({ ...reviewed, quality_issues: ['Missing outcome'] }), /quality issues/);
});


test('business-priority ordering keeps equal priorities stable and does not mutate saved order', () => {
  const items = ['could', 'must', 'wont', 'should', 'must'].map((priority, index) => ({ ...item, id: `r${index}`, priority }));
  const result = library.orderRequirements(items, 'priority');
  assert.deepEqual(result.map(row => row.id), ['r1', 'r4', 'r3', 'r0', 'r2']);
  assert.deepEqual(items.map(row => row.id), ['r0', 'r1', 'r2', 'r3', 'r4']);
  assert.equal(library.orderRequirements(items, 'recorded'), items);
  const active = filterRequirements(items, '', 'review');
  assert.deepEqual(library.orderRequirements(active, 'priority').map(row => row.id), ['r1', 'r4', 'r3', 'r0']);
});


test('suggested focus respects business priority without bypassing blocking questions or deferred scope', () => {
  const optional = { ...item, id: 'optional', priority: 'could' };
  const essential = { ...item, id: 'essential', priority: 'must' };
  const deferred = { ...item, id: 'deferred', priority: 'wont' };
  const workspace = detail([optional, essential, deferred]);
  assert.equal(workspaceFocus(workspace).item.id, 'essential');
  assert.deepEqual(workspace.requirements.map(row => row.id), ['optional', 'essential', 'deferred']);
  const agreed = { ...workspace, requirements: workspace.requirements.map(row => ({ ...row, status: 'validated' })) };
  assert.equal(workspaceFocus(agreed).item.id, 'essential');
  assert.equal(workspaceFocus({ ...workspace, decisions: [{ requirement_id: 'optional', status: 'open', blocking: true, owner_role: 'Sponsor', question: 'Confirm ownership' }] }).action, 'decisions');
  assert.equal(workspaceFocus(detail([{ ...essential, quality_issues: ['Confirm outcome'] }, optional])).action, 'questions');
});

test('AI snapshots expire on revision changes or removal, but not unrelated updates', () => {
  const { requirementSnapshotsCurrent: current } = library;
  const snapshots = [{ id: 'r1', revision: 2 }, { id: 'r2', revision: 4 }];
  assert.equal(current(snapshots, [...snapshots, { id: 'other', revision: 8 }]), true);
  assert.equal(current(snapshots, [{ id: 'r1', revision: 3 }, snapshots[1]]), false);
  assert.equal(current(snapshots, [snapshots[0]]), false);
  assert.equal(current([{ id: 'r1', revision: 2 }], [{ id: 'r1', revision: 3 }]), false);
  assert.equal(current([{ id: 'r1', revision: 3 }], [{ id: 'r1', revision: 3 }]), true);
});

test('focus routes blocking questions by business impact, preserving order within equal priorities', () => {
  const requirements = ['could', 'must', 'must', 'wont'].map((priority, index) => ({ ...item, id: `r${index}`, priority }));
  const decisions = requirements.map(row => ({ requirement_id: row.id, status: 'open', blocking: true, owner_role: row.id, question: `Question for ${row.id}` }));
  const workspace = { ...detail(requirements), decisions };
  assert.match(workspaceFocus(workspace).reason, /Start with r1:/);
  assert.deepEqual(decisions.map(row => row.requirement_id), ['r0', 'r1', 'r2', 'r3']);
  decisions[1] = { ...decisions[1], status: 'resolved' };
  assert.match(workspaceFocus(workspace).reason, /Start with r2:/);
  decisions.push({ requirement_id: null, status: 'open', blocking: true, owner_role: 'Sponsor', question: 'Whole initiative decision' });
  assert.match(workspaceFocus(workspace).reason, /Start with Sponsor:/);
});

test('source traceability composes with search and readiness without changing saved work', () => {
  const rows = [{ ...item, source_id: 's1', priority: 'should' },
    { ...item, id: 'r2', source_id: 's2', priority: 'should' },
    { ...item, id: 'r3', source_id: 's1', priority: 'wont' }];
  assert.deepEqual(filterRequirements(rows, '', 'all', [], 's1').map(x => x.id), ['r1', 'r3']);
  assert.deepEqual(filterRequirements(rows, 'receipt', 'review', [], 's1').map(x => x.id), ['r1']);
  assert.equal(filterRequirements(rows, 'missing', 'all', [], 's1').length, 0);
  assert.equal(filterRequirements(rows, '', 'all', [], 'unknown').length, 0);
  assert.equal(filterRequirements(rows, '', 'all', [], '').length, 3);
  assert.equal(rows.length, 3);
});

test('requirement decision view includes global decisions and preserves an active answer', () => {
  const rows = [
    { id: 'global', requirement_id: null, status: 'open', blocking: true, question: 'Global?', owner_role: 'Sponsor' },
    { id: 'local', requirement_id: 'r1', status: 'resolved', blocking: true, question: 'Local?', owner_role: 'Owner', resolution: 'Agreed' },
    { id: 'other', requirement_id: 'r2', status: 'open', blocking: false, question: 'Other?', owner_role: 'Owner' },
  ];
  const filter = library.filterDecisions;
  assert.deepEqual(filter(rows, 'all', '', '', 'r1').map(x => x.id), ['global', 'local']);
  assert.deepEqual(filter(rows, 'blocking', '', '', 'r1').map(x => x.id), ['global']);
  assert.deepEqual(filter(rows, 'recorded', 'agreed', '', 'r1').map(x => x.id), ['local']);
  assert.deepEqual(filter(rows, 'all', '', 'other', 'r1').map(x => x.id), ['global', 'local', 'other']);
  assert.equal(filter(rows, 'all', '', '', '').length, 3);
});

test('decision window bounds long registers while keeping a distant active answer visible', () => {
  const rows = Array.from({ length: 200 }, (_, i) => ({ id: `d${i}`, question: `Question ${i}`, owner_role: 'Owner', status: 'open', blocking: true }));
  const window = library.decisionWindow;
  assert.equal(window(rows, 20).length, 20);
  assert.deepEqual(window(rows, 20, 'd199').map(x => x.id), [...rows.slice(0, 20).map(x => x.id), 'd199']);
  assert.equal(window(rows, 40, 'd199').length, 41);
  assert.equal(window(rows, 200, 'd199').length, 200);
  assert.equal(window(rows, 20, 'd5').length, 20);
  const matches = library.filterDecisions(rows, 'all', 'Question 199');
  assert.deepEqual(window(matches, 20).map(x => x.id), ['d199']);
  assert.equal(rows.length, 200);
});

test('agreed view isolates signed-off requirements still awaiting story preparation', () => {
  const signed = { ...item, status: 'validated', priority: 'must' };
  const rows = [signed, { ...signed, id: 'story', story: { reference: 'US-002' } },
    { ...signed, id: 'deferred', priority: 'wont' }, { ...signed, id: 'draft', status: 'draft' },
    { ...signed, id: 'blocked' }, { ...signed, id: 'other-source', source_id: 's2' }];
  const decisions = [{ requirement_id: 'blocked', status: 'open', blocking: true }];
  assert.deepEqual(filterRequirements(rows, '', 'agreed', decisions).map(x => x.id), ['r1', 'other-source']);
  assert.deepEqual(filterRequirements(rows, 'receipt', 'agreed', decisions, 's1').map(x => x.id), ['r1']);
  assert.equal(filterRequirements(rows, '', 'agreed', [{ requirement_id: null, status: 'open', blocking: true }]).length, 0);
  assert.equal(filterRequirements([{ ...signed, status: 'draft' }], '', 'agreed').length, 0);
});

test('open decision triage prioritizes blockers without reordering history or saved records', () => {
  const base = { status: 'open', question: 'Confirm the business rule', owner_role: 'Sponsor' };
  const rows = [{ ...base, id: 'explore-1', blocking: false }, { ...base, id: 'block-1', blocking: true },
    { ...base, id: 'explore-2', blocking: false }, { ...base, id: 'block-2', blocking: true }];
  const original = rows.map(x => x.id);
  assert.deepEqual(library.filterDecisions(rows, 'open', '').map(x => x.id), ['block-1', 'block-2', 'explore-1', 'explore-2']);
  assert.deepEqual(library.filterDecisions(rows, 'all', '').map(x => x.id), original);
  assert.deepEqual(rows.map(x => x.id), original);
  assert.deepEqual(library.filterDecisions(rows, 'open', 'missing', 'explore-2').map(x => x.id), ['explore-2']);
});


test('unlinked background material does not delay agreed story preparation, but remains discoverable afterwards', () => {
  const agreed = { ...item, priority: 'must', status: 'validated' };
  const sources = [{ id: 's1', title: 'SOP' }, { id: 's2', title: 'Background interview' }];
  const workspace = detail([agreed], sources);
  assert.equal(workspaceFocus(workspace).action, 'story');
  assert.equal(workspaceFocus(workspace).item.id, agreed.id);
  assert.equal(workspaceFocus(detail([{ ...agreed, story: {} }], sources)).sourceId, 's2');
  assert.equal(workspaceFocus({ ...workspace, decisions: [{ requirement_id: agreed.id, status: 'open', blocking: true, owner_role: 'Sponsor', question: 'Confirm scope' }] }).action, 'decisions');
  assert.equal(workspaceFocus(detail([{ ...agreed, priority: 'wont' }], sources)).action, 'gather');
  assert.equal(workspace.requirements[0].story, null);
  assert.equal(workspace.sources.length, 2);
});
