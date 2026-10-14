/**
 * LeadFlow Sync run log in a Google Sheet.
 *
 * 1. Create a sheet, open Extensions > Apps Script and paste this file.
 * 2. Deploy > New deployment > Web app: execute as "Me", access "Anyone with the link".
 * 3. Put the web app URL in LOG_URL (.env) and rerun scripts/setup.py.
 *
 * Accepts the same JSON body the workflow sends to the sandbox (POST /log/rows).
 * Keep the URL private: anyone who has it can append rows.
 */
const COLUMNS = ['timestamp', 'execution_id', 'email', 'name', 'company', 'status', 'lead_type', 'urgency',
                 'classifier', 'crm_id', 'failed_step', 'error', 'summary'];

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);  // concurrent executions append one at a time
  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
    if (sheet.getLastRow() === 0) sheet.appendRow(COLUMNS);
    const row = JSON.parse(e.postData.contents);
    row.timestamp = row.timestamp || new Date().toISOString();
    sheet.appendRow(COLUMNS.map((c) => row[c] ?? ''));
    return ContentService.createTextOutput(JSON.stringify({ ok: true, row: sheet.getLastRow() - 1 }))
      .setMimeType(ContentService.MimeType.JSON);
  } finally {
    lock.releaseLock();
  }
}
