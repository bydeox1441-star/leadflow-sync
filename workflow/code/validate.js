// Normalise the form submission and reject invalid input and spam.
const form = $json.body || {};
const clean = (v) => String(v ?? '').trim();

const name = clean(form.name).replace(/\s+/g, ' ');
const email = clean(form.email).toLowerCase();
const message = clean(form.message);
const company = clean(form.company);
const phone = clean(form.phone);
const source = clean(form.source) || 'website-contact';
const [firstname = '', ...rest] = name.split(' ');
const lastname = rest.join(' ');

const reasons = [];
if (!name) reasons.push('missing name');
if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) reasons.push(`invalid email "${email}"`);
if (!message) reasons.push('missing message');
if (clean(form.website_url)) reasons.push('spam: hidden honeypot field was filled');
const links = (message.match(/https?:\/\//gi) || []).length;
if (links >= 2) reasons.push(`spam: ${links} links in the message`);

const decision = reasons.length ? 'rejected' : 'accept';
const lead = { email, name, firstname, lastname, company, phone, source, message, received_at: new Date().toISOString() };
const log_row = decision === 'accept' ? null : {
  timestamp: lead.received_at,
  execution_id: $execution.id,
  email,
  name,
  company,
  status: 'rejected',
  summary: reasons.join('; '),
};
return { json: { ...lead, decision, reasons, log_row } };
