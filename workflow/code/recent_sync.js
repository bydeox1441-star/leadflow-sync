// De-duplication uses the CRM as the source of truth: if this email was
// synced less than 10 minutes ago, the submission is a re-send and is skipped
// before any AI call or CRM write. Stateless, so it survives restarts and
// works with several n8n instances.
const DEDUPE_WINDOW_MS = 10 * 60 * 1000;
const lead = $('Validate input').item.json;
const match = ($json.results || [])[0];
const lastSync = match?.properties?.leadflow_last_sync;
const ago = lastSync ? Date.now() - Date.parse(lastSync) : Infinity;
const recently_synced = ago < DEDUPE_WINDOW_MS;

const log_row = recently_synced ? {
  timestamp: new Date().toISOString(),
  execution_id: $execution.id,
  email: lead.email,
  name: lead.name,
  company: lead.company,
  status: 'duplicate',
  crm_id: String(match.id),
  summary: `same email synced ${Math.round(ago / 1000)} s ago (CRM record ${match.id}); not processed again`,
} : null;
return { json: { ...lead, existing_id: match ? String(match.id) : '', recently_synced, log_row } };
