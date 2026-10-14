// The contact is in the CRM: prepare the Slack message and the log row.
const rec = $('Prepare CRM record').item.json;
const crm_id = String($json.id || rec.existing_id);
const status = rec.existing_id ? 'updated' : 'created';

const link = ($env.CRM_RECORD_URL || '').replace('{id}', crm_id);
const slack_text = [
  `${rec.urgency.toUpperCase()} · ${rec.lead_type.replace('_', ' ')} · ${status === 'updated' ? 'existing contact updated' : 'new contact'}`,
  `*${rec.name}*${rec.company ? ` (${rec.company})` : ''} · ${rec.email}`,
  `> ${rec.summary}`,
  link ? `CRM record: ${link}` : '',
].filter(Boolean).join('\n');

const log_row = {
  timestamp: new Date().toISOString(),
  execution_id: $execution.id,
  email: rec.email,
  name: rec.name,
  company: rec.company,
  status,
  lead_type: rec.lead_type,
  urgency: rec.urgency,
  classifier: rec.classifier,
  crm_id,
  summary: rec.summary,
};
return { json: { crm_id, slack_text, log_row } };
