// Validate the model's answer before trusting it. Anything unexpected sends
// the lead to the rule-based classifier instead.
const lead = $('Validate input').item.json;
const res = $json;
const TYPES = ['sales_demo', 'pricing', 'support', 'partnership', 'job_application', 'other'];
const URGENCY = ['high', 'medium', 'low'];

let parsed = null;
let problem = '';
if (res.stop_reason === 'refusal') problem = 'model declined the request';
else if (res.stop_reason === 'max_tokens') problem = 'answer was cut off';
else {
  const text = (res.content || []).find((b) => b.type === 'text')?.text;
  try { parsed = JSON.parse(text); } catch (e) { problem = 'answer was not valid JSON'; }
}

const ok = Boolean(parsed) && TYPES.includes(parsed.lead_type) && URGENCY.includes(parsed.urgency)
  && typeof parsed.summary === 'string' && parsed.summary.trim().length > 0;
if (!ok) return { json: { ...lead, ai_ok: false, ai_problem: problem || 'answer failed validation' } };

return {
  json: {
    ...lead,
    ai_ok: true,
    lead_type: parsed.lead_type,
    urgency: parsed.urgency,
    summary: parsed.summary.trim().slice(0, 200),
    classifier: `claude (${res.model || 'unknown model'})`,
  },
};
