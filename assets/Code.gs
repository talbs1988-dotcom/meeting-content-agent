/**
 * Pipeline bridge - content agent
 * Paste into the sheet: Extensions > Apps Script. Deploy as Web app, access: Anyone.
 * No Hebrew literals anywhere: nothing breaks on paste.
 *
 * Columns, by position:
 *   A=1 date | B=2 type | C=3 hook | D=4 link | E=5 notes | F=6 approved
 */

var NCOLS = 6;
var HOOK_COL = 3;
var APPROVED_COL = 6;

function doPost(e) {
  try {
    var b = JSON.parse(e.postData.contents);
    if (b.action === 'add')     return ok_(addRows_(b.rows, b.month));
    if (b.action === 'read')    return ok_(readRows_(b.month));
    if (b.action === 'tabs')    return ok_(listTabs_());
    if (b.action === 'ping')    return ok_({ alive: true, tabs: listTabs_().tabs.length });
    return err_('unknown action: ' + b.action);
  } catch (ex) { return err_(String(ex)); }
}

function doGet(e) {
  var m = (e && e.parameter && e.parameter.month) ? Number(e.parameter.month) : null;
  return ok_(readRows_(m));
}

function addRows_(rows, month) {
  if (!rows || !rows.length) return { added: 0 };
  var sh = sheet_(month);
  var start = firstEmptyRow_(sh);
  sh.getRange(start, 1, rows.length, NCOLS).setValues(rows);
  sh.getRange(start, 1, rows.length, NCOLS).setVerticalAlignment('top').setWrap(true);
  for (var i = 0; i < rows.length; i++) { sh.setRowHeight(start + i, 56); }
  return { added: rows.length, tab: sh.getName(), firstRow: start };
}

function readRows_(month) {
  var sh = sheet_(month);
  var last = sh.getLastRow();
  if (last < 2) return { tab: sh.getName(), rows: [] };
  var vals = sh.getRange(2, 1, last - 1, NCOLS).getValues();
  var out = [];
  for (var i = 0; i < vals.length; i++) {
    var r = vals[i];
    if (String(r[HOOK_COL - 1]).trim() === '') continue;
    out.push({
      row: i + 2,
      date: String(r[0]),
      type: String(r[1]),
      hook: String(r[2]),
      link: String(r[3]),
      notes: String(r[4]),
      approved: r[5] === true || String(r[5]).toUpperCase() === 'TRUE'
    });
  }
  return { tab: sh.getName(), rows: out };
}

function listTabs_() {
  return { tabs: book_().getSheets().map(function (s) { return s.getName(); }) };
}

/* ---------- helpers ---------- */

function book_() {
  var id = PropertiesService.getScriptProperties().getProperty('SHEET_ID');
  return id ? SpreadsheetApp.openById(id) : SpreadsheetApp.getActiveSpreadsheet();
}

function sheet_(month) {
  var all = book_().getSheets();
  var idx = (month === null || month === undefined) ? new Date().getMonth() : Number(month);
  if (idx < 0 || idx >= all.length) idx = 0;
  return all[idx];
}

function firstEmptyRow_(sh) {
  var last = sh.getLastRow();
  if (last < 2) return 2;
  var hooks = sh.getRange(2, HOOK_COL, last - 1, 1).getValues();
  for (var i = 0; i < hooks.length; i++) {
    if (String(hooks[i][0]).trim() === '') return i + 2;
  }
  return last + 1;
}

function ok_(d)  { return json_({ ok: true,  data: d }); }
function err_(m) { return json_({ ok: false, error: m }); }
function json_(o){ return ContentService.createTextOutput(JSON.stringify(o))
                     .setMimeType(ContentService.MimeType.JSON); }
