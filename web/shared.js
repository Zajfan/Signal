export const $ = (selector, root = document) => root.querySelector(selector);
export const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
export function readStorage(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}
export function writeStorage(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Storage is optional. */ }
}
export function localIdentity() {
  const value = readStorage('signal.localIdentity', null);
  return value && typeof value.id === 'string' && value.id.trim() ? value : {id:'local-employer', email:'employer@example.test'};
}
export async function api(path, {method = 'GET', body, admin = false, employer = false, signal} = {}) {
  const headers = {'Accept':'application/json'};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (employer) {
    const identity = localIdentity();
    headers['X-Local-User-Id'] = identity.id;
    headers['X-Local-User-Email'] = identity.email;
  }
  if (admin) headers['X-Local-Admin'] = 'true';
  const response = await fetch(path, {method, headers, signal, body:body === undefined ? undefined : JSON.stringify(body)});
  const result = await response.json().catch(() => ({}));
  if (!response.ok) { const error = new Error(result.error || `Request failed (${response.status}). Please try again.`); error.status=response.status; throw error; }
  return result;
}
export const labels = {draft:'Draft', awaiting_payment:'Awaiting payment', pending_review:'In review', published:'Published', rejected:'Rejected', expired:'Expired', withdrawn:'Closed', needs_review:'Needs review', removed:'Removed', unverified:'Not submitted', pending:'Verification pending', verified:'Verified'};
export const badge = state => `<span class="badge ${esc(state)}">${esc(labels[state] || state)}</span>`;
export function countryName(code) {
  if (!code) return 'Not specified';
  try { return new Intl.DisplayNames(['en'], {type:'region'}).of(code); } catch { return code; }
}
export function salary(job) {
  if (job.salary_min == null && job.salary_max == null) return 'Salary not disclosed';
  const format = n => new Intl.NumberFormat('en', {maximumFractionDigits:0}).format(n);
  const amount = job.salary_min != null && job.salary_max != null ? `${format(job.salary_min)}–${format(job.salary_max)}` : job.salary_min != null ? `From ${format(job.salary_min)}` : `Up to ${format(job.salary_max)}`;
  return `${job.salary_currency || 'Currency not specified'} ${amount}`;
}
export function dateLabel(value) {
  const date = new Date(value?.includes('T') ? value : value?.replace(' ', 'T') + 'Z');
  return Number.isNaN(date.valueOf()) ? 'Not available' : new Intl.DateTimeFormat('en', {day:'numeric', month:'short', year:'numeric'}).format(date);
}
export function safeUrl(value) {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : ''; } catch { return ''; }
}
export function showError(error, target = $('#feedback')) {
  target.hidden = false;
  target.className = 'notice error';
  target.textContent = error.message || String(error);
  target.focus();
}
export function notify(message) {
  const box = $('#toast');
  box.textContent = message;
  box.hidden = false;
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => box.hidden = true, 4000);
}
export function field(label, name, value = '', {type = 'text', required = false, placeholder = '', hint = '', min, maxLength} = {}) {
  return `<label class="field">${esc(label)}<input aria-label="${esc(label)}" name="${esc(name)}" type="${type}" value="${esc(value)}" ${required?'required':''} ${min !== undefined?`min="${min}"`:''} ${maxLength?`maxlength="${maxLength}"`:''} placeholder="${esc(placeholder)}">${hint?`<small>${esc(hint)}</small>`:''}</label>`;
}
export function selectField(label, name, options, value = '', required = false) {
  return `<label class="field">${esc(label)}<select aria-label="${esc(label)}" name="${esc(name)}" ${required?'required':''}>${options.map(([key,text])=>`<option value="${esc(key)}" ${key===value?'selected':''}>${esc(text)}</option>`).join('')}</select></label>`;
}
export function countryOptions(includeBlank = true) {
  const codes = 'AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW'.split(' ');
  return [...(includeBlank?[['','Choose a country']]:[]), ...codes.map(c => [c,countryName(c)]).sort((a,b)=>a[1].localeCompare(b[1]))];
}
export function jobSummary(job) {
  return `<div class="eyebrow">${esc(job.company_name || 'Company')}</div><h2>${esc(job.title || 'Your job title')}</h2><div class="job-meta">${esc(job.location || 'Location')} · ${esc(job.work_mode || 'Work arrangement')} · ${esc(job.employment_type || 'Employment type')}</div><p class="salary">${esc(salary(job))}</p><div class="description">${esc(job.description || 'Your job description will appear here.')}</div>`;
}
export async function submitForm(form, work) {
  const buttons = [...form.querySelectorAll('button[type="submit"]')];
  buttons.forEach(button => button.disabled = true);
  try { await work(); } catch (error) { showError(error); }
  finally { buttons.forEach(button => button.disabled = false); }
}
