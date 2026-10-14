// A CRM or Slack call still failed after its retries: log it with the
// failing step and prepare an alert for #leadflow-alerts.
const step = $prevNode.name;
// The CRM lookup runs before classification, so later fields may not exist yet.
const classified = ['Update contact', 'Create contact', 'Notify sales on Slack'].includes(step);
const rec = classified ? $('Prepare CRM record').item.json : $('Validate input').item.json;
const err = $json.error || {};
// HTTP errors arrive as '503 - "{...json...}"': keep the status and the API's own message.
let message = String(err.message || err.description || 'unknown error');
const http = message.match(/^(\d{3})\s*-\s*([\s\S]*)$/);
if (http) {
  let body = http[2];
  try { body = JSON.parse(body); if (typeof body === 'string') body = JSON.parse(body); } catch (e) { /* keep raw text */ }
  message = `HTTP ${http[1]}: ${typeof body === 'object' && body ? body.message || JSON.stringify(body) : body}`;
}
message = message.slice(0, 300);
const notifyFailed = step === 'Notify sales on Slack';
const crm_id = notifyFailed ? $('Build notification').item.json.crm_id : '';

const log_row = {
  timestamp: new Date().toISOString(),
  execution_id: $execution.id,
  email: rec.email,
  name: rec.name,
  company: rec.company,
  status: notifyFailed ? 'notify_failed' : 'failed',
  lead_type: rec.lead_type || '',
  urgency: rec.urgency || '',
  classifier: rec.classifier || '',
  crm_id,
  failed_step: step,
  error: message,
  summary: rec.summary || '',
};
const alert_text = notifyFailed
  ? `LeadFlow: ${rec.name} <${rec.email}> was saved in the CRM (ID ${crm_id}), but the Slack notification failed after 3 attempts: ${message}`
  : `LeadFlow: ${rec.name} <${rec.email}> was NOT saved. "${step}" failed after 3 attempts: ${message}. The submission is kept in n8n execution ${$execution.id} for replay.`;
return { json: { log_row, alert_text } };
