// Keyword classifier. Used when the AI step is off, when the API call fails
// after its retries, or when the model's answer fails validation.
const lead = $('Validate input').item.json;
const text = ` ${lead.message} `.toLowerCase();
const has = (re) => re.test(text);

let lead_type = 'other';
if (has(/can'?t log|cannot log|log ?in|locked|error|bug|broken|not working|refund|charged twice|empty file/)) lead_type = 'support';
else if (has(/\bcv\b|resume|hiring|internship|\bjob\b|position|\bapply\b/)) lead_type = 'job_application';
else if (has(/partner|reseller|affiliate|referral/)) lead_type = 'partnership';
else if (has(/demo|trial|quote|get(ting)? started|onboarding|book a call|interested in/)) lead_type = 'sales_demo';
else if (has(/price|pricing|cost|\bplan\b|discount|billing/)) lead_type = 'pricing';

const urgent = has(/urgent|asap|immediately|this week|today|by (monday|tuesday|wednesday|thursday|friday)|go live|budget is approved/);
const urgency = ['job_application', 'other'].includes(lead_type) ? 'low' : urgent ? 'high' : 'medium';

// Summary: first sentence after any greeting ("Hi!", "Hello,"), capitalised.
const body = lead.message.replace(/^(hi|hello|hey|good (morning|afternoon))\b[^a-z0-9]*/i, '');
let first = body.split(/(?<=[.!?])\s/)[0] || lead.message;
first = first.charAt(0).toUpperCase() + first.slice(1);
const summary = first.length > 140 ? `${first.slice(0, 137)}...` : first;

const via = $prevNode.name;
const classifier = via === 'AI step enabled?' ? 'rules'
  : via === 'Classify with Claude' ? 'rules (AI call failed)' : 'rules (AI answer invalid)';
return { json: { ...lead, lead_type, urgency, summary, classifier } };
