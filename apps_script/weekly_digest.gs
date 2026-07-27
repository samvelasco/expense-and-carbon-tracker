/Weekly Expense Digest
 * Reports on rows added to the receipt tracker sheet since the last successful run, and emails a summary to whoever needs to see it.

 * SETUP:
 * 1. Open the spreadsheet -> Extensions -> Apps Script.
 * 2. Paste this whole file in, replacing any starter code.
 * 3. Project Settings (gear icon) -> Script Properties -> add:
 *      key:   DIGEST_RECIPIENT
 *      value: comma-separated email address(es)
 * 4. Run `createWeeklyTrigger` once manually (Run menu -> select it -> Run).

 * 5. Now, sendWeeklyDigest() now runs automatically every Monday morning. To change the schedule, edit createWeeklyTrigger().
 *
 */
// Must match the header row in the sheet exactly, in order.
const EXPECTED_HEADERS = [
  "Date", "Merchant", "Category", "Total ($)", "Est. Carbon (kg CO2)",
  "Submitted By", "Payment Method", "Notes", "Raw Extract"
];

function sendWeeklyDigest() {
  const props = PropertiesService.getScriptProperties();
  const recipientProp = props.getProperty("DIGEST_RECIPIENT");
  if (!recipientProp) {
    throw new Error(
      "No DIGEST_RECIPIENT set. Go to Project Settings > Script Properties and add one."
    );
  }
  const recipients = recipientProp.split(",").map(s => s.trim()).join(",");

  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  const data = sheet.getDataRange().getValues();

  if (data.length === 0) {
    MailApp.sendEmail(recipients, "Weekly Expense Digest", "Sheet is empty — nothing to report.");
    return;
  }

  const headers = data[0];
  if (JSON.stringify(headers) !== JSON.stringify(EXPECTED_HEADERS)) {
    MailApp.sendEmail(
      recipients,
      "Weekly Expense Digest — SETUP ISSUE",
      "The digest script didn't run because the sheet's header row doesn't " +
      "match what it expects.\n\nExpected: " + EXPECTED_HEADERS.join(", ") +
      "\n\nFound: " + headers.join(", ") +
      "\n\nFix the header row, then this will resolve itself next week " +
      "(or re-run sendWeeklyDigest manually once it's fixed)."
    );
    return;
  }

  const lastRow = sheet.getLastRow();
  const lastProcessedRow = parseInt(props.getProperty("LAST_PROCESSED_ROW") || "1", 10);

  if (lastRow <= lastProcessedRow) {
    Logger.log("No new rows since last digest — skipping email.");
    return;
  }

  const numNewRows = lastRow - lastProcessedRow;
  const weekRows = sheet.getRange(lastProcessedRow + 1, 1, numNewRows, headers.length).getValues();
  const timeZone = SpreadsheetApp.getActiveSpreadsheet().getSpreadsheetTimeZone();

  const stats = summarize(weekRows);
  const subject = `Weekly Expense Digest — ${weekRows.length} receipt(s), $${stats.totalSpend.toFixed(2)}`;
  const htmlBody = buildHtmlBody(stats, weekRows, timeZone);

  MailApp.sendEmail({
    to: recipients,
    subject: subject,
    htmlBody: htmlBody,
  });

  props.setProperty("LAST_PROCESSED_ROW", String(lastRow));
}

function parseRowDate(value) {
  if (value instanceof Date) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = new Date(value);
    if (!isNaN(parsed.getTime())) return parsed;
  }
  return null;
}

function summarize(weekRows) {
  let totalSpend = 0;
  let totalCarbon = 0;
  let missingCarbonCount = 0;
  let needsReviewCount = 0;
  const byCategory = {};
  const bySubmitter = {};

  weekRows.forEach(row => {
    const [ , , category, total, carbon, submittedBy, , , rawExtract] = row;

    const totalNum = Number(total) || 0;
    totalSpend += totalNum;

    byCategory[category] = (byCategory[category] || 0) + totalNum;

    const submitter = (submittedBy && submittedBy.toString().trim()) || "Unknown";
    bySubmitter[submitter] = (bySubmitter[submitter] || 0) + totalNum;

    if (carbon === "" || carbon === null || carbon === undefined) {
      missingCarbonCount++;
    } else {
      totalCarbon += Number(carbon) || 0;
    }

    try {
      const parsed = JSON.parse(rawExtract);
      if (parsed.category_confidence === "low") {
        needsReviewCount++;
      }
    } catch (e) {
    }
  });

  return { totalSpend, totalCarbon, missingCarbonCount, needsReviewCount, byCategory, bySubmitter };
}

function buildHtmlBody(stats, weekRows, timeZone) {
  const money = n => `$${n.toFixed(2)}`;

  const categoryRows = Object.keys(stats.byCategory).sort()
    .map(cat => `<tr><td>${escapeHtml(cat)}</td><td style="text-align:right">${money(stats.byCategory[cat])}</td></tr>`)
    .join("");

  const submitterRows = Object.keys(stats.bySubmitter).sort()
    .map(name => `<tr><td>${escapeHtml(name)}</td><td style="text-align:right">${money(stats.bySubmitter[name])}</td></tr>`)
    .join("");

  const itemRows = weekRows.map(row => {
    const [date, merchant, category, total, carbon, submittedBy, paymentMethod, notes] = row;
    const displayDate = parseRowDate(date)
      ? Utilities.formatDate(parseRowDate(date), timeZone, "yyyy-MM-dd")
      : String(date);
    const carbonDisplay = (carbon === "" || carbon === null || carbon === undefined)
      ? "—"
      : `${carbon} kg`;
    return `<tr>
      <td>${escapeHtml(displayDate)}</td>
      <td>${escapeHtml(merchant)}</td>
      <td>${escapeHtml(category)}</td>
      <td style="text-align:right">${money(Number(total) || 0)}</td>
      <td style="text-align:right">${carbonDisplay}</td>
      <td>${escapeHtml(submittedBy || "")}</td>
      <td>${escapeHtml(notes || "")}</td>
    </tr>`;
  }).join("");

  const carbonNote = stats.missingCarbonCount > 0
    ? ` (${stats.missingCarbonCount} receipt${stats.missingCarbonCount === 1 ? "" : "s"} had no reliable carbon factor yet — not counted as zero, just left out of this total)`
    : "";

  const reviewNote = stats.needsReviewCount > 0
    ? `<p style="color:#a15c00;"><strong>⚠ ${stats.needsReviewCount} receipt${stats.needsReviewCount === 1 ? "" : "s"} had a low-confidence category</strong> — worth a quick check in the sheet.</p>`
    : "";

  return `
    <div style="font-family: Arial, sans-serif; color: #222;">
      <h2>Weekly Expense Digest</h2>
      <p><strong>${weekRows.length}</strong> receipt(s) logged since the last digest, totaling <strong>${money(stats.totalSpend)}</strong>.</p>
      <p>Estimated carbon: <strong>~${stats.totalCarbon.toFixed(2)} kg CO2e</strong>${carbonNote}</p>
      ${reviewNote}

      <h3>By category</h3>
      <table cellpadding="4" style="border-collapse: collapse;">${categoryRows}</table>

      <h3>By submitter</h3>
      <table cellpadding="4" style="border-collapse: collapse;">${submitterRows}</table>

      <h3>All receipts this period</h3>
      <table cellpadding="4" style="border-collapse: collapse; border: 1px solid #ddd;">
        <tr style="background:#f2f2f2;">
          <th>Date</th><th>Merchant</th><th>Category</th><th>Total</th>
          <th>Carbon</th><th>Submitted By</th><th>Notes</th>
        </tr>
        ${itemRows}
      </table>
    </div>
  `;
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

//Run this ONCE manually to set up the weekly schedule.
function createWeeklyTrigger() {
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === "sendWeeklyDigest") {
      ScriptApp.deleteTrigger(t);
    }
  });

  ScriptApp.newTrigger("sendWeeklyDigest")
    .timeBased()
    .onWeekDay(ScriptApp.WeekDay.MONDAY)
    .atHour(8)
    .create();
}

//Testing helper: clears the row pointer so the next sendWeeklyDigest() run treats every row as new again.
function resetDigestState() {
  PropertiesService.getScriptProperties().deleteProperty("LAST_PROCESSED_ROW");
  Logger.log("Row pointer cleared — next run will treat all rows as new.");
}
