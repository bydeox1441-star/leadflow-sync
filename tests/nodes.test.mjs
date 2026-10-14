// Unit tests for the n8n Code nodes. Each node's JavaScript runs unchanged
// inside a small harness that provides the n8n globals it uses
// ($json, $(...), $prevNode, $execution, $env).
// Run: node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const root = new URL('..', import.meta.url);
const read = (rel) => readFileSync(fileURLToPath(new URL(rel, root)), 'utf8');

function runNode(file, { json = {}, nodes = {}, prevNode = '', env = {} } = {}) {
  const $ = (name) => {
    if (!(name in nodes)) throw new Error(`node "${name}" has not run`);
    return { item: { json: nodes[name] } };
  };
  const fn = new Function('$json', '$', '$prevNode', '$execution', '$env', read(`workflow/code/${file}`));
  return fn(json, $, { name: prevNode }, { id: 'test-exec' }, env).json;
}

const form = (body) => ({ body });
const lead = runNode('validate.js', {
  json: form({ name: '  Priya   Raman ', email: 'Priya.Raman@Northgate.example', company: 'Northgate', message: 'Demo please' }),
});

test('validate: normalises a good lead', () => {
  assert.equal(lead.decision, 'accept');
  assert.equal(lead.email, 'priya.raman@northgate.example');
  assert.equal(lead.firstname, 'Priya');
  assert.equal(lead.lastname, 'Raman');
  assert.equal(lead.source, 'website-contact');
  assert.equal(lead.log_row, null);
});

for (const [label, body, reason] of [
  ['invalid email', { name: 'A', email: 'a@', message: 'hi' }, /invalid email/],
  ['missing message', { name: 'A', email: 'a@b.example', message: '' }, /missing message/],
  ['honeypot', { name: 'A', email: 'a@b.example', message: 'hi', website_url: 'http://x.example' }, /honeypot/],
  ['link spam', { name: 'A', email: 'a@b.example', message: 'http://a.example http://b.example' }, /2 links/],
]) {
  test(`validate: rejects ${label}`, () => {
    const out = runNode('validate.js', { json: form(body) });
    assert.equal(out.decision, 'rejected');
    assert.equal(out.log_row.status, 'rejected');
    assert.match(out.log_row.summary, reason);
  });
}

const searchResult = (lastSync) => ({
  total: 1,
  results: [{ id: '1001', properties: { email: lead.email, ...(lastSync ? { leadflow_last_sync: lastSync } : {}) } }],
});

test('recent sync: new email is processed', () => {
  const out = runNode('recent_sync.js', { json: { total: 0, results: [] }, nodes: { 'Validate input': lead } });
  assert.equal(out.recently_synced, false);
  assert.equal(out.existing_id, '');
});

test('recent sync: re-send within 10 minutes is a duplicate', () => {
  const twoMinAgo = new Date(Date.now() - 2 * 60 * 1000).toISOString();
  const out = runNode('recent_sync.js', { json: searchResult(twoMinAgo), nodes: { 'Validate input': lead } });
  assert.equal(out.recently_synced, true);
  assert.equal(out.log_row.status, 'duplicate');
  assert.equal(out.log_row.crm_id, '1001');
});

test('recent sync: older contact or one never synced is updated, not skipped', () => {
  const old = new Date(Date.now() - 20 * 60 * 1000).toISOString();
  for (const json of [searchResult(old), searchResult(null)]) {
    const out = runNode('recent_sync.js', { json, nodes: { 'Validate input': lead } });
    assert.equal(out.recently_synced, false);
    assert.equal(out.existing_id, '1001');
  }
});

test('rules: classify every synthetic lead as expected', () => {
  const { leads } = JSON.parse(read('data/leads.json'));
  for (const l of leads.filter((x) => x.expected.lead_type)) {
    const validated = runNode('validate.js', { json: form(l.form) });
    const out = runNode('rules.js', { nodes: { 'Validate input': validated }, prevNode: 'AI step enabled?' });
    assert.equal(out.lead_type, l.expected.lead_type, `lead ${l.id}`);
    assert.equal(out.urgency, l.expected.urgency, `lead ${l.id}`);
    assert.equal(out.classifier, 'rules');
  }
});

test('rules: records why the AI step was skipped', () => {
  const viaApi = runNode('rules.js', { nodes: { 'Validate input': lead }, prevNode: 'Classify with Claude' });
  const viaCheck = runNode('rules.js', { nodes: { 'Validate input': lead }, prevNode: 'AI answer valid?' });
  assert.equal(viaApi.classifier, 'rules (AI call failed)');
  assert.equal(viaCheck.classifier, 'rules (AI answer invalid)');
});

test('AI request: strict schema, fallback and model from env', () => {
  const out = runNode('ai_request.js', { json: lead, env: { LEADFLOW_MODEL: 'claude-haiku-5-5' } });
  const req = out.ai_request;
  assert.equal(req.model, 'claude-haiku-5-5');
  assert.equal(req.fallbacks, 'default');
  assert.equal(req.output_config.format.schema.additionalProperties, false);
  assert.match(req.messages[0].content, /<form>[\s\S]*Demo please[\s\S]*<\/form>/);
  assert.equal(runNode('ai_request.js', { json: lead }).ai_request.model, 'claude-opus-5-5');
});

const answer = (obj, extra = {}) => ({
  stop_reason: 'end_turn', model: 'claude-opus-5-5',
  content: [{ type: 'text', text: typeof obj === 'string' ? obj : JSON.stringify(obj) }], ...extra,
});

test('AI check: accepts a valid answer', () => {
  const out = runNode('ai_check.js', {
    json: answer({ lead_type: 'sales_demo', urgency: 'high', summary: 'Wants a demo this week.' }),
    nodes: { 'Validate input': lead },
  });
  assert.equal(out.ai_ok, true);
  assert.equal(out.classifier, 'claude (claude-opus-5-5)');
});

for (const [label, res] of [
  ['refusal', answer('', { stop_reason: 'refusal' })],
  ['truncated answer', answer('{"lead_type"', { stop_reason: 'max_tokens' })],
  ['invalid JSON', answer('not json')],
  ['unknown category', answer({ lead_type: 'vip', urgency: 'high', summary: 'x' })],
  ['empty summary', answer({ lead_type: 'pricing', urgency: 'low', summary: ' ' })],
]) {
  test(`AI check: rejects ${label}`, () => {
    const out = runNode('ai_check.js', { json: res, nodes: { 'Validate input': lead } });
    assert.equal(out.ai_ok, false);
  });
}

test('prepare: drops empty fields and never patches the email', () => {
  const classified = { ...lead, phone: '', lead_type: 'sales_demo', urgency: 'high', summary: 's', classifier: 'rules' };
  const out = runNode('prepare.js', { json: classified, nodes: { 'Check recent sync': { existing_id: '1001' } } });
  assert.equal(out.existing_id, '1001');
  assert.ok(!('phone' in out.create_properties));
  assert.ok(!('email' in out.update_properties));
  assert.ok(out.create_properties.leadflow_last_sync);
});

test('failure: CRM lookup failure is logged with a clean message', () => {
  const out = runNode('failure.js', {
    json: { error: { message: '503 - "{\\"status\\": \\"error\\", \\"message\\": \\"Service unavailable\\"}"' } },
    nodes: { 'Validate input': lead },
    prevNode: 'Find contact in CRM',
  });
  assert.equal(out.log_row.status, 'failed');
  assert.equal(out.log_row.error, 'HTTP 503: Service unavailable');
  assert.match(out.alert_text, /NOT saved/);
});

test('failure: Slack failure keeps the CRM id and says the lead was saved', () => {
  const prepared = { ...lead, lead_type: 'pricing', urgency: 'medium', summary: 's', classifier: 'rules' };
  const out = runNode('failure.js', {
    json: { error: { message: 'connect ECONNREFUSED' } },
    nodes: { 'Prepare CRM record': prepared, 'Build notification': { crm_id: '1007' } },
    prevNode: 'Notify sales on Slack',
  });
  assert.equal(out.log_row.status, 'notify_failed');
  assert.equal(out.log_row.crm_id, '1007');
  assert.match(out.alert_text, /saved in the CRM \(ID 1007\)/);
});
