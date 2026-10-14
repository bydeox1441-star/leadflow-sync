// One record with everything the CRM needs, whichever classifier ran.
const l = $json;
const existing_id = $('Check recent sync').item.json.existing_id;
const crm_properties = {
  email: l.email,
  firstname: l.firstname,
  lastname: l.lastname,
  company: l.company,
  phone: l.phone,
  message: l.message,
  leadflow_type: l.lead_type,
  leadflow_urgency: l.urgency,
  leadflow_summary: l.summary,
  leadflow_source: l.source,
  leadflow_classifier: l.classifier,
  leadflow_last_sync: new Date().toISOString(),
};
for (const key of Object.keys(crm_properties)) {
  if (crm_properties[key] === '' || crm_properties[key] == null) delete crm_properties[key];
}
const { email, ...update_properties } = crm_properties;
return { json: { ...l, existing_id, create_properties: crm_properties, update_properties } };
