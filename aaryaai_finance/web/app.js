// aaryaai finance — front-end. Plain JS, no build step. Everything country- or person-specific
// comes from the server (/config, packs, rules, trackers); nothing is hard-coded here.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
// Session token: the server hands it only to this page; every API call must carry it.
const TOKEN = document.querySelector('meta[name="session-token"]')?.content || "";
const HDRS = () => ({ "Content-Type": "application/json", "X-Session-Token": TOKEN });
const withToken = (url) => url + (url.includes("?") ? "&" : "?") + "t=" + encodeURIComponent(TOKEN);
function sessionExpired(r) {
  if (r.status !== 401) return false;
  if (!sessionStorage.getItem("afReloaded")) { try { sessionStorage.setItem("afReloaded", "1"); } catch (e) { } location.reload(); }
  return true;
}
const api = async (url, opts = {}) => {
  const r = await fetch(url, { ...opts, headers: HDRS(), body: opts.body ? JSON.stringify(opts.body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (sessionExpired(r)) throw new Error("The app was restarted — reloading…");
  if (!r.ok) throw new Error(j.detail || r.statusText);
  try { sessionStorage.removeItem("afReloaded"); } catch (e) { }
  return j;
};
// ---------------- app-wide config ----------------
let CFG = { base_currency: "EUR", currencies: ["EUR"], packs: [], rates: {} };
const BASE = () => CFG.base_currency;
const LOCALES = { INR: "en-IN", EUR: "de-DE", USD: "en-US", GBP: "en-GB", CHF: "de-CH", JPY: "ja-JP" };
const SYM = { EUR: "€", INR: "₹", USD: "$", GBP: "£", JPY: "¥", CHF: "CHF ", SGD: "S$", AUD: "A$", CAD: "C$", AED: "AED ", SEK: "kr ", NOK: "kr ", DKK: "kr ", PLN: "zł ", CZK: "Kč " };
// ---------------- hide amounts (privacy mode) ----------------
// One switch masks every amount: cards, tables, charts, tooltips, and amounts written inside text (deadline
// titles, tracker facts, chat answers). Percentages, dates and exchange rates stay visible. Remembered per browser.
let HIDE = false;
try { HIDE = localStorage.getItem("afHideAmounts") === "1"; } catch (e) { }
const MASK = "••••";
const AMT_RE = /(?:[€₹$£]|\b(?:Rs\.?|EUR|INR|USD|GBP|CHF)\s?)\s?[-−]?\d[\d.,]*(?:\s?(?:k|M|L|Cr|lakh|crore)\b)?|\b\d[\d.,]*\s?(?:€|₹|EUR|INR|USD|lakh|crore|Cr\b)/g;
const hideAmt = (t) => HIDE ? String(t ?? "").replace(AMT_RE, (m) => { const c = m.match(/[€₹$£]|Rs\.?|EUR|INR|USD|GBP|CHF/)?.[0] || ""; return /^[A-Z]/.test(c) ? (m.startsWith(c) ? c + " " + MASK : MASK + " " + c) : c + MASK; }) : t;
function money(v, c = BASE(), d) {
  if (HIDE) return (SYM[c || BASE()] ?? (c || BASE()) + " ") + MASK;
  return moneyRaw(v, c, d);
}
function moneyRaw(v, c = BASE(), d) {
  v = Number(v || 0); c = c || BASE();
  const dec = d ?? (Math.abs(v) < 100 && v % 1 ? 2 : 0);
  const s = Math.abs(v).toLocaleString(LOCALES[c] || "en-GB", { maximumFractionDigits: dec, minimumFractionDigits: dec });
  return (v < 0 ? "−" : "") + (SYM[c] ?? c + " ") + s;
}
const eur = (v, d) => money(v, BASE(), d);           // "base currency" formatter (legacy name)
const inr = (v) => money(v, "INR", 0);
const compact = (v, c = BASE()) => HIDE ? (SYM[c] ?? c + " ") + "•••" : c === "INR" ? (Math.abs(v) >= 1e7 ? (SYM.INR + (v / 1e7).toFixed(2) + " Cr") : SYM.INR + (v / 1e5).toLocaleString("en-IN", { maximumFractionDigits: 1 }) + "L")
  : (SYM[c] ?? c + " ") + (Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(1) + "M" : Math.round(v / 1000) + "k");
const lakh = (v) => compact(v, "INR");
const conv = (v, from, to = BASE()) => { const r = CFG.rates || {}; if (from === to) return v; if (!r[from] || !r[to]) return null; return v / r[from] * r[to]; };
const packFor = (code) => CFG.packs.find((p) => p.code === code);
const flagFor = (code) => packFor(code)?.flag || "";
const countryName = (code) => packFor(code)?.name || code || "Other";
const ccyCountry = (c) => CFG.packs.find((p) => p.currency === c);
const pct = (v, d = 1) => (v * 100).toFixed(d) + "%";
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const toast = (m) => { const t = $("#toast"); t.textContent = m; t.classList.add("show"); clearTimeout(toast.tm); toast.tm = setTimeout(() => t.classList.remove("show"), Math.max(2600, String(m).length * 55)); };
const kpi = (l, v, s = "", extra = "") => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${s}</div>${extra}</div>`;
const meter = (f, color) => `<div class="meter"><i style="width:${Math.max(0, Math.min(1, f)) * 100}%;${color ? "background:" + color : ""}"></i></div>`;
const daysTo = (d) => Math.ceil((new Date(d) - new Date(new Date().toDateString())) / 864e5);
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
// colour per currency: base = sky, second = lilac, others from palette
const CCY_COL = ["#38bdf8", "#a99bff", "#34d399", "#fbbf24", "#f472b6"];
const ccyColor = (c) => CCY_COL[Math.max(0, CFG.currencies.indexOf(c)) % CCY_COL.length];

let MODEL = { entities: {} };
async function loadConfig() {
  [CFG, MODEL] = await Promise.all([api("/config"), api("/model")]);
  const others = CFG.currencies.filter((c) => c !== BASE());
  const r = CFG.rates || {};
  const pill = others.length && r[others[0]] ? [`1 ${SYM[BASE()] || BASE()} =`, moneyRaw(r[others[0]], others[0], 2)] : ["base", BASE()];
  $$(".fxlbl").forEach((e) => e.textContent = pill[0]); $$(".fxval").forEach((e) => e.textContent = pill[1]);
  $("#brandSub").textContent = CFG.packs.map((p) => p.flag).join(" ") + "  local · private";
}
async function loadFx() { try { await loadConfig(); } catch (e) { } }
// ---------------- theme & charts ----------------
window.toggleTheme = () => {
  const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = cur === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("fm-theme", next); } catch (e) { }
  const active = $(".tab.on")?.id; if (active) loaders[active]?.();
};
// category colours stay neutral so blue/red always mean EUR/INR
const palette = () => ["#5b4bd6", "#fbbf24", "#34d399", "#f472b6", "#fb923c", "#2dd4bf", "#c4b5fd", "#64748b"];
const charts = {};
function chart(id, cfg) {
  if (!window.Chart) return;
  Chart.defaults.font.family = css("--body"); Chart.defaults.color = css("--muted");
  Chart.defaults.borderColor = css("--line");
  Chart.defaults.plugins.tooltip.backgroundColor = "#16223a"; Chart.defaults.plugins.tooltip.borderColor = "rgba(169,155,255,.3)"; Chart.defaults.plugins.tooltip.borderWidth = 1;
  charts[id]?.destroy();
  cfg.options = { responsive: true, maintainAspectRatio: false, animation: { duration: 700 }, ...(cfg.options || {}) };
  charts[id] = new Chart($("#" + id), cfg);
}
const doughnut = (labels, data, center) => ({ type: "doughnut",
  data: { labels, datasets: [{ data, backgroundColor: palette(), borderColor: css("--paper"), borderWidth: 3, hoverOffset: 6 }] },
  options: { cutout: "68%", plugins: { legend: { position: innerWidth < 760 ? "bottom" : "right", labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, padding: 12 } },
    tooltip: { callbacks: { label: (c) => ` ${c.label}: ${eur(c.raw)}` } } } },
  plugins: center ? [{ id: "c", afterDraw(ch) { const { ctx, chartArea: a } = ch; const x = (a.left + a.right) / 2, y = (a.top + a.bottom) / 2;
    ctx.save(); ctx.textAlign = "center"; ctx.fillStyle = css("--ink"); ctx.font = `600 22px ${css("--display")}`; ctx.fillText(center[0], x, y + 2);
    ctx.fillStyle = css("--muted"); ctx.font = `500 11px ${css("--body")}`; ctx.fillText(center[1], x, y + 20); ctx.restore(); } }] : [] });
function areaGradient(ctx, color) {
  const g = ctx.chart.ctx.createLinearGradient(0, ctx.chart.chartArea?.top || 0, 0, ctx.chart.chartArea?.bottom || 300);
  g.addColorStop(0, color + "55"); g.addColorStop(1, color + "00"); return g;
}

// ---------------- tabs ----------------
const loaders = {};
window.go = (tab) => $(`#tabs button[data-tab="${tab}"]`)?.click();
function setHide(on, quiet) {
  HIDE = !!on;
  try { localStorage.setItem("afHideAmounts", HIDE ? "1" : "0"); } catch (e) { }
  document.body.classList.toggle("amounts-hidden", HIDE);
  $$(".hidebtn").forEach((b) => { b.setAttribute("aria-pressed", String(HIDE)); b.title = (HIDE ? "Show amounts" : "Hide amounts") + " (Alt+H)";
    b.querySelector("use").setAttribute("href", HIDE ? "#i-eyeoff" : "#i-eye");
    const l = b.querySelector(".lbl"); if (l) l.textContent = HIDE ? "Show amounts" : "Hide amounts"; });
  if (quiet) return;
  const cur = $("#tabs button.on")?.dataset.tab;
  if (cur === "chat" && typeof CHAT_ID !== "undefined" && CHAT_ID) openChat(CHAT_ID); else loaders[cur]?.();
  toast(HIDE ? "Amounts hidden — Alt+H to show" : "Amounts visible");
}
window.toggleHide = () => setHide(!HIDE);
$$(".hidebtn").forEach((b) => b.onclick = toggleHide);
document.addEventListener("keydown", (e) => { if (e.altKey && !e.ctrlKey && !e.metaKey && e.code === "KeyH") { e.preventDefault(); toggleHide(); } });
setHide(HIDE, true);
$$("#tabs button").forEach((b) => b.onclick = () => {
  $$("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
  $$(".tab").forEach((t) => t.classList.toggle("on", t.id === b.dataset.tab));
  history.replaceState(null, "", "#" + b.dataset.tab); scrollTo({ top: 0 });
  b.scrollIntoView({ block: "nearest", inline: "center" });
  loaders[b.dataset.tab]?.();
  loadFx();
});


// ---------------- generic edit dialog ----------------
function dialog(title, fields, row, onSave, onDelete) {
  const f = $("#dlgForm");
  f.innerHTML = `<h3>${title}</h3>` + fields.map(([k, label, type = "text", opts, extra = {}]) => {
    const v = row[k] ?? "";
    const lab = esc(label) + (extra.custom ? `<span class="custom-tag">${esc(extra.source || "custom")}</span>` : "");
    const hint = extra.help ? `<span class="fieldhint">${esc(extra.help)}</span>` : "";
    if (type === "select") return `<label>${lab}<select name="${k}">${opts.map((o) => { const [val, txt] = Array.isArray(o) ? o : [o, o]; return `<option value="${esc(val)}" ${String(val) === String(v) ? "selected" : ""}>${esc(txt)}</option>`; }).join("")}</select>${hint}</label>`;
    if (type === "checkbox") return `<label><input type="checkbox" name="${k}" ${v ? "checked" : ""}> ${lab}${hint}</label>`;
    if (type === "textarea") return `<label>${lab}<textarea name="${k}" rows="3">${esc(v)}</textarea>${hint}</label>`;
    return `<label>${lab}<input name="${k}" type="${type}" step="any" value="${esc(v)}">${hint}</label>`;
  }).join("") + `<div style="display:flex;gap:8px;justify-content:space-between;margin-top:8px">
    ${onDelete && row.id ? '<button type="button" class="ghost" id="dlgDel">Delete</button>' : "<span></span>"}
    <span style="display:flex;gap:6px"><button type="button" class="ghost" id="dlgCancel">Cancel</button><button>Save</button></span></div>`;
  const d = $("#dlg"); d.showModal();
  $("#dlgCancel").onclick = () => d.close();
  if ($("#dlgDel")) $("#dlgDel").onclick = async () => { await onDelete(row.id); d.close(); toast("Deleted"); };
  f.onsubmit = async (e) => {
    e.preventDefault();
    const out = { ...row };
    fields.forEach(([k, , type]) => {
      const el = f.elements[k];
      out[k] = type === "checkbox" ? (el.checked ? 1 : 0) : type === "number" ? (el.value === "" ? null : +el.value) : el.value;
    });
    try { await onSave(out); d.close(); toast("Saved"); } catch (err) { toast(err.message); }
  };
}


// ---------------- model-driven form fields ----------------
// Turns a field from the JSON model into a dialog field. Extra fields added by a country pack or by you
// (Settings → Custom fields) appear in the matching dialogs automatically.
function modelField(name, f, refs = {}) {
  const label = f.label || name.replace(/_/g, " ");
  const x = { custom: f.custom, source: f.source, help: f.help };
  switch (f.type) {
    case "enum": return [name, label, "select", [["", "—"], ...f.values.map((v) => [v, v])], x];
    case "bool": return [name, label, "checkbox", null, x];
    case "money": case "number": case "int": return [name, label, "number", null, x];
    case "date": return [name, label, "date", null, x];
    case "currency": return [name, label, "select", CFG.currencies, x];
    case "country": return [name, label, "select", ["", ...(CFG.countries || [])], x];
    case "ref": return [name, label, "select", [["", "—"], ...(refs[f.to] || []).map((r) => [r.id, r.name || r.title || `#${r.id}`])], x];
    default: return [name, label, (f.type === "text" && /note|detail|description/.test(name)) ? "textarea" : "text", null, x];
  }
}
// A country pack's extra fields only show on records of that country (e.g. NRE/NRO only on Indian accounts).
function fieldForCountry(x, code) {
  const p = (CFG.all_packs || CFG.packs || []).find((pk) => x.source === `${pk.name} pack`);
  return !p || !code || p.code === code;
}
const customFields = (entity) => Object.entries(MODEL.entities[entity]?.fields || {}).filter(([, f]) => f.custom).map(([k, f]) => modelField(k, f));

// ---------------- your own record types (from model.json) ----------------
window.openRecords = async (entity) => {
  const ent = MODEL.entities[entity]; if (!ent) return;
  const refs = {};
  for (const f of Object.values(ent.fields)) if (f.type === "ref" && !refs[f.to]) refs[f.to] = await api("/api/" + f.to).catch(() => []);
  const rows = await api("/api/" + entity);
  const cols = Object.entries(ent.fields).slice(0, 5);
  const show = (f, v) => f.type === "ref" ? esc((refs[f.to] || []).find((r) => r.id === v)?.name || (v ? `#${v}` : "")) : f.type === "money" && v != null ? money(v, rows.currency) : f.type === "bool" ? (v ? "✓" : "") : esc(v ?? "");
  $("#recordsCard").hidden = false;
  $("#recTitle").innerHTML = `${esc(ent.label)} <span class="hint" style="font-size:13px">${rows.length} · defined in ${esc(ent.source)}</span>`;
  $("#setRecords").innerHTML = `<div class="tablewrap"><table><thead><tr>${cols.map(([k, f]) => `<th>${esc(f.label || k)}</th>`).join("")}</tr></thead><tbody>
    ${rows.map((r) => `<tr class="click" onclick="editRecord('${entity}', ${r.id})">${cols.map(([k, f]) => `<td>${show(f, r[k])}</td>`).join("")}</tr>`).join("") || `<tr><td colspan="${cols.length}" class="hint">Nothing yet.</td></tr>`}</tbody></table></div>
    <div style="display:flex;gap:8px;margin-top:10px"><button class="sm" onclick="editRecord('${entity}')">＋ Add ${esc(ent.label.toLowerCase())}</button><button class="sm ghost" onclick="$('#recordsCard').hidden=true">Close</button></div>`;
  window._recs = { entity, rows, refs };
  $("#recordsCard").scrollIntoView({ behavior: "smooth", block: "start" });
};
window.editRecord = (entity, id) => {
  const ent = MODEL.entities[entity], st = window._recs;
  const row = st.rows.find((r) => r.id === id) || Object.fromEntries(Object.entries(ent.fields).filter(([, f]) => "default" in f).map(([k, f]) => [k, f.default]));
  dialog(`${id ? "Edit" : "Add"} ${esc(ent.label.toLowerCase())}`, Object.entries(ent.fields).map(([k, f]) => modelField(k, f, st.refs)), row,
    async (r) => { await api("/api/" + entity, { method: "POST", body: r }); openRecords(entity); },
    async (i) => { await api(`/api/${entity}/${i}`, { method: "DELETE" }); openRecords(entity); });
};

// ---------------- "Ask the assistant" shortcut ----------------
window.askClaude = (q) => {
  go("chat");
  setTimeout(() => { CHAT_ID = null; drawEmpty(); const t = $("#prompt"); t.value = q; autosize(); t.focus(); }, 350);
};
function urgencyRing(days) {
  const r = 26, c = 2 * Math.PI * r, f = days == null ? 1 : Math.max(0, Math.min(1, days / 45));
  const col = days == null ? css("--lilac") : days <= 31 ? css("--bad") : days <= 62 ? css("--gold") : css("--good");
  return `<svg viewBox="0 0 64 64"><circle cx="32" cy="32" r="${r}" stroke="rgba(148,163,184,.18)"/>
    <circle cx="32" cy="32" r="${r}" stroke="${col}" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - f)}" style="filter:drop-shadow(0 0 4px ${col})"/></svg>`;
}

// ---------------- deadline timeline (shared) ----------------
function countdown(due) {
  if (!due) return `<span class="count">ongoing</span>`;
  const d = daysTo(due);
  const cls = d <= 31 ? "hot" : d <= 62 ? "warm" : "";
  return `<span class="count ${cls}">${d < 0 ? Math.abs(d) + " days late" : d === 0 ? "today" : d + " days"}</span>`;
}
const countryTag = (code) => code ? `<span class="tag" style="background:rgba(148,163,184,.12);color:var(--ink2)">${flagFor(code)} ${esc(countryName(code))}</span>` : "";
function timeline(items, { actions = false, compact = false } = {}) {
  let month = "";
  return items.map((c) => {
    const dt = c.due ? new Date(c.due) : null;
    const m = dt ? `${MON[dt.getMonth()]} ${dt.getFullYear()}` : "Every time";
    const head = !compact && m !== month ? `<div class="tl-month">${m}</div>` : ""; month = m;
    const sev = c.status === "done" ? "done" : c.severity;
    const q = JSON.stringify("Explain in simple words what I need to do for: " + c.title + " — and how, step by step.").replace(/'/g, "&#39;");
    return head + `<div class="tl-item ${c.status === "done" ? "done" : ""}" style="--tc:${ccyColor(packFor(c.country)?.currency)}">
      <div class="tl-date" style="border-top:3px solid var(--tc)">${dt ? `<b>${dt.getDate()}</b><span>${MON[dt.getMonth()]}</span>` : `<b>∞</b><span>always</span>`}</div>
      <div><div class="tl-title">${esc(hideAmt(c.title))}</div>
        <div class="tl-meta">${countryTag(c.country)}${c.origin === "yours" ? `<span class="srcbadge yours">yours</span>` : ""}
        ${sev !== "normal" ? `<span class="tag ${sev}">${sev === "critical" ? "Critical" : sev === "high" ? "Important" : "Done"}</span>` : ""}
        ${compact ? countdown(c.due) : ""}</div></div>
      ${actions ? `<div class="tl-actions">${countdown(c.due)}<button class="sm ${c.status === "done" ? "ghost" : ""}" onclick='toggleCal(${JSON.stringify(c.key)}, "${c.status}")'>${c.status === "done" ? "Reopen" : "Mark done"}</button>
        ${c.status !== "done" ? `<button class="sm ghost ask" onclick='askClaude(${q})'>Ask</button>` : ""}
        ${c.origin === "yours" && c.id ? `<button class="sm ghost" onclick="delDeadline(${c.id})">Delete</button>` : ""}</div>` : ""}
      ${actions && c.detail ? `<details><summary>What to do &amp; why</summary><p>${esc(hideAmt(c.detail))}</p><p class="hint">Source: ${esc(c.source || "")}</p></details>` : ""}
    </div>`;
  }).join("");
}

// ---------------- first-run setup wizard ----------------
const WIZ = { step: 0, opts: null, data: { countries: [], base_currency: "", extra_currencies: [], answers: {}, ai: { provider: "none" }, secrets: {} } };
window.openWizard = async () => {
  WIZ.opts = await api("/setup/options");
  try { const c = await api("/config"); if (c.configured) Object.assign(WIZ.data, { data_dir: c.data_dir, name: c.profile.name, about: c.profile.about, countries: c.countries,
    base_currency: c.base_currency, extra_currencies: c.extra_currencies, answers: c.profile.answers || {}, documents_root: c.documents_root, ai: { ...c.ai } }); } catch (e) { }
  WIZ.data.data_dir ||= WIZ.opts.default_data_dir;
  WIZ.step = 0; $("#wizard").hidden = false; drawWizard();
};
function drawWizard() {
  const o = WIZ.opts, d = WIZ.data, steps = ["Where", "Countries", "Documents", "AI"];
  $("#wizSteps").innerHTML = steps.map((_, i) => `<i class="${i <= WIZ.step ? "on" : ""}"></i>`).join("");
  $("#wizBack").style.visibility = WIZ.step ? "visible" : "hidden";
  $("#wizNext").textContent = WIZ.step === 3 ? "Finish setup" : "Next";
  $("#wizErr").textContent = "";
  const b = $("#wizBody");
  if (WIZ.step === 0) b.innerHTML = `<h2>Welcome</h2><p class="lead">Your finances stay on this computer, in one folder you choose. Nothing is uploaded anywhere unless you connect an AI assistant later.</p>
    <div class="form"><label>Your first name (used for greetings) <input id="wName" value="${esc(d.name || "")}" placeholder="e.g. Alex"></label>
    <label>Data folder — settings, database and your own rules live here <input id="wDir" value="${esc(d.data_dir)}"></label>
    <p class="hint" style="margin:0">Tip: a folder inside Documents or a synced drive (OneDrive, iCloud) makes backups automatic.</p></div>`;
  if (WIZ.step === 1) {
    const packs = o.packs;
    b.innerHTML = `<h2>Your countries</h2><p class="lead">Each country is a <b>pack</b> of readable rules: currency, tax calculators, deadlines and document types. Pick every country you have money or tax in.</p>
      <div class="packpick">${packs.map((p) => `<label><input type="checkbox" value="${p.code}" ${d.countries.includes(p.code) ? "checked" : ""}><span class="fl">${p.flag}</span><b>${esc(p.name)}</b><small>${p.currency} · ${p.source}</small></label>`).join("")}</div>
      <div class="form row2"><label>Base currency — totals are shown in this <select id="wBase">${[...new Set([...packs.map((p) => p.currency), ...o.currencies])].map((c) => `<option ${c === (d.base_currency || packs.find((p) => d.countries.includes(p.code))?.currency) ? "selected" : ""}>${c}</option>`).join("")}</select></label>
      <label>Other currencies you hold (comma-separated) <input id="wExtra" value="${esc((d.extra_currencies || []).join(", "))}" placeholder="e.g. USD, CHF"></label></div>
      <div id="wQs"></div><p class="hint">Missing your country? Copy <code>packs/_template</code> — see CONTRIBUTING.md. You can switch countries later in Settings.</p>`;
    const drawQs = () => {
      const sel = $$(".packpick input:checked").map((x) => x.value);
      const qs = packs.filter((p) => sel.includes(p.code)).flatMap((p) => (p.questions || []).map((q) => ({ ...q, flag: p.flag })));
      $("#wQs").innerHTML = qs.length ? `<p class="lead" style="margin:10px 0 4px">A few yes/no questions decide which deadlines apply to you:</p><div class="qlist">${qs.map((q) =>
        `<label><input type="checkbox" data-q="${q.id}" ${d.answers[q.id] ? "checked" : ""}><span class="fl">${q.flag}</span><span>${esc(q.label)}</span></label>`).join("")}</div>` : "";
      if (!d.base_currency) { const first = packs.find((p) => sel.includes(p.code)); if (first) $("#wBase").value = first.currency; }
    };
    $$(".packpick input").forEach((x) => x.onchange = drawQs); drawQs();
  }
  if (WIZ.step === 2) b.innerHTML = `<h2>Your documents</h2><p class="lead">Where should filed documents go? Point to an existing folder to keep your current structure — the app adds files into it and never deletes anything.</p>
    <div class="form"><label>Documents folder <input id="wDocs" value="${esc(d.documents_root || "documents")}"></label>
    <p class="hint" style="margin:0">A relative path is inside your data folder. An absolute path (like <code>C:\\Users\\you\\Documents\\Finance</code>) uses that folder directly. Folder names per country can be changed in Settings.</p></div>`;
  if (WIZ.step === 3) {
    const pv = o.providers;
    b.innerHTML = `<h2>AI assistant <span class="hint" style="font-size:15px">optional</span></h2><p class="lead">Everything works without AI — sorting and deadlines use rules. Connect one to chat about your finances in plain English. Only your question and the numbers it needs are sent.</p>
      <div class="provpick">${Object.entries(pv).map(([k, v]) => `<label><input type="radio" name="prov" value="${k}" ${d.ai.provider === k ? "checked" : ""}>${esc(v.label)}</label>`).join("")}</div>
      <div id="wAI" class="form"></div>
      ${(o.mcp_clients || []).length ? `<div class="form" style="margin-top:14px"><p class="lead" style="margin:0">Also use your numbers in an AI app you already have? It adds aaryaai-finance to its MCP settings (a backup is kept); the app can then read your numbers and suggest changes for you to approve.</p>
        ${o.mcp_clients.map((c) => `<label class="chk"><input type="checkbox" data-mcp="${c.id}" ${(d.mcp_clients || []).includes(c.id) ? "checked" : ""}> Connect ${esc(c.label)}</label>`).join("")}</div>` : ""}`;
    const drawAI = () => {
      const k = $("input[name=prov]:checked")?.value || "none", v = pv[k];
      d.ai.provider = k;
      $("#wAI").innerHTML = k === "none" ? `<p class="hint">You can connect one later in Settings → AI.</p>` : `<p class="hint">${esc(v.help || "")}</p>` +
        (k === "anthropic" ? `<label>Anthropic API key <input type="password" id="wKey" placeholder="sk-ant-…"></label>` : "") +
        (k === "azure_openai" ? `<label>Endpoint <input id="wEp" value="${esc(d.ai.endpoint || "")}" placeholder="https://my-resource.openai.azure.com"></label><label>Deployment name <input id="wDep" value="${esc(d.ai.deployment || "")}" placeholder="gpt-4.1"></label><label>API key <input type="password" id="wKey"></label>` : "") +
        (k === "github_models" ? `<label>GitHub token (Models: read) <input type="password" id="wKey" placeholder="github_pat_…"></label>` : "") +
        (k === "ollama" ? `<label>Ollama address <input id="wEp" value="${esc(d.ai.endpoint || "http://localhost:11434")}"></label>` : "") +
        (v.models ? `<label>Model <select id="wModel">${v.models.map((m) => `<option ${m === (d.ai.model || v.default_model) ? "selected" : ""}>${m}</option>`).join("")}</select></label>` : "");
    };
    $$("input[name=prov]").forEach((x) => x.onchange = drawAI); drawAI();
  }
}
function collectWizard() {
  const d = WIZ.data;
  if (WIZ.step === 0) { d.name = $("#wName").value.trim(); d.data_dir = $("#wDir").value.trim(); if (!d.data_dir) throw new Error("Choose a data folder"); }
  if (WIZ.step === 1) {
    d.countries = $$(".packpick input:checked").map((x) => x.value);
    if (!d.countries.length) throw new Error("Pick at least one country");
    d.base_currency = $("#wBase").value;
    d.extra_currencies = $("#wExtra").value.split(/[,\s]+/).map((x) => x.trim().toUpperCase()).filter((x) => /^[A-Z]{3}$/.test(x));
    $$("[data-q]").forEach((x) => d.answers[x.dataset.q] = x.checked);
  }
  if (WIZ.step === 2) d.documents_root = $("#wDocs").value.trim() || "documents";
  if (WIZ.step === 3) {
    const k = d.ai.provider;
    if ($("#wEp")) d.ai.endpoint = $("#wEp").value.trim();
    if ($("#wDep")) d.ai.deployment = $("#wDep").value.trim();
    if ($("#wModel")) d.ai.model = $("#wModel").value;
    d.mcp_clients = $$("[data-mcp]:checked").map((x) => x.dataset.mcp);
    const key = $("#wKey")?.value.trim();
    if (key) d.secrets[{ anthropic: "anthropic_api_key", azure_openai: "azure_openai_api_key", github_models: "github_token" }[k]] = key;
  }
}
$("#wizNext").onclick = async () => {
  try { collectWizard(); } catch (e) { $("#wizErr").textContent = e.message; return; }
  if (WIZ.step < 3) { WIZ.step++; drawWizard(); return; }
  $("#wizNext").disabled = true; $("#wizErr").textContent = "";
  try {
    const res = await api("/setup/apply", { method: "POST", body: WIZ.data });
    const ok = (res.mcp || []).filter((m) => m.ok), bad = (res.mcp || []).filter((m) => !m.ok);
    $("#wizard").hidden = true;
    toast(ok.length ? `You're all set. ${ok.map((m) => m.label).join(" and ")} connected: restart ${ok.length > 1 ? "them" : "it"} to see aaryaai-finance.` : bad.length ? `You're all set. MCP: ${bad[0].error}` : "You're all set");
    await loadConfig();
    go(location.hash.slice(1) || "home");
  } catch (e) { $("#wizErr").textContent = e.message; }
  $("#wizNext").disabled = false;
};
$("#wizBack").onclick = () => { try { collectWizard(); } catch (e) { } WIZ.step = Math.max(0, WIZ.step - 1); drawWizard(); };

// ---------------- POSITION ----------------
let ITEMS = [];
loaders.position = async () => {
  const [p, items, acc] = await Promise.all([api("/calc/position"), api("/api/items"), api("/money/accounts").catch(() => ({ accounts: [] }))]);
  ITEMS = items;
  const n = p.net_worth, base = p.base;
  $("#posDate").textContent = "Position · " + new Date().toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
  // one column per currency (base first), max 3
  const ccys = [...new Set([base, ...p.currencies, ...Object.keys(n.by_currency)])].slice(0, 3);
  const lines = {}; ccys.forEach((c) => lines[c] = []);
  acc.accounts.filter((a) => a.in_networth && a.balance > 0 && lines[a.currency]).sort((a, b) => b.balance - a.balance).forEach((a) => lines[a.currency].push([a.name, a.balance]));
  items.filter((i) => i.kind === "asset" && lines[i.currency]).forEach((i) => lines[i.currency].push([i.name, i.amount]));
  const hist = p.history, prev = hist.length > 1 ? hist[hist.length - 2].net_worth : null;
  const col = (c, i) => {
    const inBase = n.by_currency[c] || 0, share = n.assets ? inBase / n.assets : 0, pk = ccyCountry(c);
    const native = conv(inBase, base, c);
    return `<div class="lcol" style="background:linear-gradient(180deg,${ccyColor(c)}1f,transparent);${i ? "text-align:right" : ""}">
      <div class="where" style="color:${ccyColor(c)}">${esc(c)}${pk ? " · " + esc(pk.name) : ""}</div>
      <div class="amt">${money(native ?? inBase, native == null ? base : c)}</div>
      <div class="conv">${c !== base ? `= ${money(inBase, base)} · ` : ""}${pct(share, 0)} of what you own</div>
      <ul>${lines[c].slice(0, 4).map(([nm, a]) => `<li style="${i ? "flex-direction:row-reverse" : ""}"><span>${esc(nm.split(" — ")[0])}</span><span>${money(a, c)}</span></li>`).join("") || `<li><span class="muted">Nothing entered yet</span><span></span></li>`}</ul></div>`;
  };
  const r = p.rates || {};
  const pivot = (c) => `<div class="pivot"><div class="rate"><small>today</small>1 ${SYM[base] || base} = ${r[c] ? moneyRaw(r[c], c, 2) : "?"}</div></div>`;
  const colsHtml = ccys.map((c, i) => (i ? pivot(c) : "") + col(c, i)).join("");
  $("#ledger").innerHTML = `
    <div class="ledger-top"><div><div class="eyebrow">Net worth · ${esc(base)}</div><div class="nw">${money(n.net_worth, base)}</div></div>
      <div class="delta">${prev !== null ? `${n.net_worth >= prev ? "▲" : "▼"} ${money(Math.abs(n.net_worth - prev), base)} since last visit` : "Your first snapshot — check back next month"}
      ${n.liabilities ? `<br>after ${money(n.liabilities, base)} of debts` : ""}${n.warning ? `<br><span class="neg">${esc(n.warning)}</span>` : ""}</div></div>
    <div class="ledger-cols n${ccys.length}">${colsHtml}</div>
    <div class="splitbar">${ccys.map((c) => `<i style="width:0;background:${ccyColor(c)}" data-w="${n.assets ? (n.by_currency[c] || 0) / n.assets * 100 : 0}"></i>`).join("")}</div>
    <div class="split-legend">${ccys.map((c) => `<span><span class="dot" style="background:${ccyColor(c)}"></span> ${c}</span>`).join("")}</div>`;
  requestAnimationFrame(() => requestAnimationFrame(() => $$(".splitbar i").forEach((i) => i.style.width = i.dataset.w + "%")));
  countUp($("#ledger .nw"), n.net_worth, base);
  const cf = await api("/calc/cashflow").catch(() => null);
  const t0 = p.trackers[0];
  $("#kpis").innerHTML =
    kpi(`<span class="dot good"></span>Cash cushion`, money(n.liquid, base), cf && cf.spend ? `${cf.emergency_months} months of spending` : "accounts marked “liquid”", meter((cf?.emergency_months || 0) / 6)) +
    kpi(`<span class="dot gold"></span>You owe`, money(n.liabilities, base), n.liabilities ? "loans & cards" : "no debts entered") +
    kpi(`<span class="dot eur"></span>Savings rate`, cf && cf.income ? pct(cf.savings_rate, 0) : "—", cf && cf.income ? money(cf.savings, base) + " a month" : "log income in Money", meter((cf?.savings_rate || 0) / .3, css("--eur"))) +
    (t0 ? kpi(`<span class="dot inr"></span>${esc(t0.name)}`, compact(t0.remaining_with_tax, t0.currency), `still to pay · ${pct(t0.paid_pct, 0)} paid`, meter(t0.paid_pct, css("--inr")))
        : kpi(`<span class="dot inr"></span>Deadlines`, p.open_deadlines.length, "open with a date", ""));
  drawAttention(p.open_deadlines);
  drawTrackers(p.trackers);
  $("#nextDeadlines").innerHTML = timeline(p.open_deadlines.slice(0, 5), { compact: true }) || `<div class="empty">Nothing due — or switch on your countries in Settings.</div>`;
  const hasCat = Object.keys(n.by_category).length;
  $("#chCat").hidden = !hasCat; $("#chCatEmpty")?.remove();
  if (hasCat) chart("chCat", doughnut(Object.keys(n.by_category), Object.values(n.by_category), [compact(n.assets, base), "you own"]));
  else { charts.chCat?.destroy(); delete charts.chCat; $("#chCat").insertAdjacentHTML("afterend", `<div class="empty" id="chCatEmpty">Add an account, asset or holding and this shows how your money is split.</div>`); }
  drawOutlook(hist, n.net_worth, cf?.savings || 0);
  $("#itemsTbl").innerHTML = `<thead><tr><th>Name</th><th>Type</th><th class="n">Amount</th><th>Liquid</th><th>Updated</th></tr></thead><tbody>` +
    (items.map((i) => `<tr class="click" onclick="editItem(${i.id})"><td>${esc(i.name)}${i.note ? `<div class="hint" style="font-weight:400">${esc(i.note)}</div>` : ""}</td>
      <td data-l="Type">${i.kind === "liability" ? "▼ " : ""}${esc(i.category)}</td><td class="n" data-l="Amount">${money(i.amount, i.currency)}<span class="cur" style="background:${ccyColor(i.currency)}22;color:${ccyColor(i.currency)}">${i.currency}</span></td>
      <td data-l="Liquid">${i.liquid ? "✓" : "—"}</td><td class="muted" data-l="Updated">${i.updated || ""}</td></tr>`).join("") ||
      `<tr><td colspan="5"><div class="empty">Property, pensions, cars, loans… anything that isn't a bank account.<br><button class="sm" onclick="editItem()">＋ Add an asset or debt</button></div></td></tr>`) + "</tbody>";
};
function drawAttention(items) {
  const open = items.filter((c) => c.due);
  const top = open.slice().sort((a, b) => (a.severity === "critical" ? -1 : 0) - (b.severity === "critical" ? -1 : 0) || a.due.localeCompare(b.due))[0];
  if (!top || daysTo(top.due) > 60) { $("#attention").innerHTML = ""; return; }
  const d = daysTo(top.due), more = open.filter((c) => daysTo(c.due) <= 45).length - 1;
  $("#attention").innerHTML = `<div class="attn">
    <div class="urg">${urgencyRing(d)}<div class="c"><div><b>${d}</b><span>days</span></div></div></div>
    <div class="what"><div class="eyebrow">Needs your attention${top.country ? " · " + esc(countryName(top.country)) : ""}</div><div class="t">${esc(hideAmt(top.title))}</div>
      <p class="hint">Due ${new Date(top.due).toLocaleDateString("en-GB", { day: "numeric", month: "long" })}${more > 0 ? ` · ${more} more item${more > 1 ? "s" : ""} due within 45 days` : ""}</p></div>
    <div class="acts"><button class="sm ask" id="attnAsk">Ask how</button><button class="sm ghost" onclick="go('tax')">Open tax desk</button></div></div>`;
  $("#attnAsk").onclick = () => askClaude("Explain in simple words what I need to do for: " + top.title + " — and how, step by step.");
}
function drawTrackers(ts) {
  $("#topGrid").style.gridTemplateColumns = ts.length ? "" : "1fr";
  $("#trackerMain").style.display = ts.length ? "" : "none";
  if (!ts.length) { $("#trackerJourneys").innerHTML = ""; return; }
  const t = ts[0];
  $("#trackerMain").innerHTML = `<div class="card" style="height:100%"><h3>${esc(t.name)} <span class="sub">${esc(t.subtitle || "")}</span></h3>${towerHtml(t)}</div>`;
  requestAnimationFrame(() => {});
  $("#trackerJourneys").innerHTML = ts.map((x, i) => `<div class="card"><h3>${esc(x.name)} — payment journey <span class="sub">paid so far vs price</span>
      <span class="right legend-inline"><span><i class="sw solid"></i>Paid</span><span><i class="sw dash"></i>Still to come (estimate)</span></span></h3>
    <div class="chartbox tall"><canvas id="chTr${i}"></canvas></div><p class="hint" style="margin-bottom:0">${pct(x.paid_pct, 0)} of the price paid over ${x.payments.length} payments. The dashed line spreads the remaining stages evenly up to the possession date — an estimate.</p></div>`).join("")
    + ts.slice(1).map((x) => `<div class="card"><h3>${esc(x.name)}</h3>${towerHtml(x)}</div>`).join("");
  ts.forEach((x, i) => journeyChart("chTr" + i, x));
}
function towerHtml(g) {
  const paid = g.stages.filter((s) => s.paid).length;
  const floors = g.stages.map((s, i) => `<div class="floor ${s.paid ? "paid" : i === paid ? "now" : ""}" style="animation-delay:${i * 45}ms" title="${esc(s.no)} · ${esc(s.name)}${s.paid ? " · paid " + s.paid : ""}"><span>${esc(s.no)}</span>${i === paid && !s.paid ? "" : `<span>${s.paid ? esc(s.name) : ""}</span>`}</div>`).join("");
  const c = g.currency;
  return `<div class="tower-wrap"><div class="tower">${floors}<div class="roof">${g.possession_date ? "Possession" : "Done"}</div></div>
    <div class="tower-facts"><div class="eyebrow">Paid so far</div><div class="big">${pct(g.paid_pct, 0)}</div>
      <div class="hint">${money(g.paid, c)} of ${money(g.price, c)}</div>
      <div class="kv"><span class="k">Stages paid</span><span class="v num">${paid} of ${g.stages.length}</span>
        ${g.next_stage ? `<span class="k">Next stage (incl. tax)</span><span class="v num">≈ ${compact(g.next_stage, c)}</span>` : ""}
        <span class="k">Still to pay (incl. tax)</span><span class="v num">${money(g.remaining_with_tax, c)}</span>
        ${(g.facts || []).map((f) => `<span class="k">${esc(f.label)}</span><span class="v num">${esc(hideAmt(f.value))}</span>`).join("")}
        ${g.possession_date ? `<span class="k">Possession</span><span class="v num">${new Date(g.possession_date).toLocaleDateString("en-GB", { month: "short", year: "numeric" })}</span>` : ""}</div>
      ${g.warning ? `<div class="warnline">⚠ ${esc(hideAmt(g.warning))}</div>` : ""}</div></div>`;
}
function journeyChart(id, g) {
  if (!g.payments.length) return;
  const c = g.currency, pts = g.payments.map((p) => ({ x: +new Date(p.date), y: p.cumulative, l: p.label }));
  const last = pts[pts.length - 1], proj = [last, ...g.projection.map((p) => ({ x: +new Date(p.date), y: p.cumulative, l: p.label }))];
  const end = +new Date(g.possession_date || proj[proj.length - 1].x), col = css("--lilac"), today = +new Date(new Date().toDateString());
  chart(id, { type: "line", data: { datasets: [
      { label: "Paid", data: pts, stepped: "before", borderColor: col, borderWidth: 2.5, pointRadius: 3.5, pointBackgroundColor: col, fill: true, backgroundColor: (x) => areaGradient(x, "#a99bff") },
      { label: "Still to come (estimate)", data: proj, stepped: "before", borderColor: col, borderDash: [6, 5], borderWidth: 2, pointRadius: 3, pointBackgroundColor: css("--paper"), pointBorderColor: col },
      { label: "Total price", data: [{ x: pts[0].x, y: g.price }, { x: end, y: g.price }], borderColor: "rgba(148,163,184,.45)", borderDash: [2, 4], borderWidth: 1, pointRadius: 0 }] },
    options: { parsing: false, interaction: { mode: "nearest", intersect: false },
      plugins: { legend: { display: false }, tooltip: { callbacks: { title: (i) => new Date(i[0].raw.x).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }),
        label: (x) => x.dataset.label === "Total price" ? ` Total price ${money(x.raw.y, c)}` : ` ${x.raw.l || ""}: ${money(x.raw.y, c)} paid` } } },
      scales: { x: { type: "linear", min: pts[0].x, max: end + 30 * 864e5, grid: { display: false }, ticks: { stepSize: 182.6 * 864e5, callback: (v) => { const d = new Date(v); return MON[d.getMonth()] + " " + String(d.getFullYear()).slice(2); } } },
        y: { min: 0, ticks: { maxTicksLimit: 5, callback: (v) => compact(v, c) } } } },
    plugins: [{ id: "today", afterDraw(ch) { const x = ch.scales.x.getPixelForValue(today), { top, bottom } = ch.chartArea; const k = ch.ctx;
      k.save(); k.strokeStyle = "rgba(52,211,153,.6)"; k.setLineDash([3, 3]); k.beginPath(); k.moveTo(x, top); k.lineTo(x, bottom); k.stroke();
      k.fillStyle = css("--good"); k.font = `500 10px ${css("--num")}`; k.fillText("TODAY", x + 5, top + 10); k.restore(); } }] });
}
function drawOutlook(hist, nw, savings) {
  const now = new Date(), labels = [], proj = [], past = [];
  hist.slice(-6).forEach((x) => { labels.push(x.day.slice(5)); past.push(x.net_worth); proj.push(null); });
  proj[proj.length - 1] = nw;
  for (let m = 1; m <= 12; m++) { const d = new Date(now.getFullYear(), now.getMonth() + m, 1); labels.push(MON[d.getMonth()] + " " + String(d.getFullYear()).slice(2)); past.push(null); proj.push(nw + savings * m); }
  const col = css("--eur");
  chart("chHist", { type: "line", data: { labels, datasets: [
      { label: "So far", data: past, borderColor: col, borderWidth: 2.5, pointRadius: 4, pointBackgroundColor: col, tension: .3 },
      { label: "Outlook", data: proj, borderColor: col, borderDash: [6, 5], borderWidth: 2, pointRadius: 0, fill: true, backgroundColor: (c) => areaGradient(c, "#38bdf8"), tension: .3 }] },
    options: { plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${money(c.raw)}` } } },
      scales: { y: { ticks: { maxTicksLimit: 5, callback: (v) => compact(v) } }, x: { grid: { display: false }, ticks: { maxTicksLimit: 7 } } } } });
  $("#outlookNote").textContent = savings > 0 ? `Saving ${money(savings)} a month adds about ${money(savings * 12)} in a year — reaching ≈ ${money(nw + savings * 12)} by ${labels[labels.length - 1]}, before investment growth or currency moves.`
    : "Log your income and spending in Money to see where your net worth is heading.";
}
function countUp(el, target, c) {
  if (!el || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const t0 = performance.now(), dur = 900;
  const step = (t) => { const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3); el.textContent = money(target * e, c, 0); if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
const ITEM_CATS = ["Property", "Property (under construction)", "Retirement / pension", "Provident fund", "Vehicle", "Gold / valuables", "Other asset", "Home loan", "Personal loan", "Credit card", "Other debt"];
window.editItem = (id) => {
  const row = ITEMS.find((i) => i.id === id) || { kind: "asset", currency: BASE(), liquid: 0, country: CFG.countries?.[0] || "" };
  dialog(id ? "Edit asset or debt" : "Add an asset or debt", [["name", "Name"], ["kind", "Own or owe?", "select", ["asset", "liability"]],
    ["category", "Type", "select", ITEM_CATS], ["amount", "Current value / balance", "number"],
    ["currency", "Currency", "select", CFG.currencies], ["country", "Country", "select", ["", ...(CFG.countries || [])]],
    ["liquid", "Liquid (reachable within a week)", "checkbox"], ["note", "Note", "textarea"], ...customFields("items")], row,
    async (r) => { await api("/api/items", { method: "POST", body: r }); loaders.position(); },
    async (i) => { await api("/api/items/" + i, { method: "DELETE" }); loaders.position(); });
};
// ---------------- GOALS ----------------
let GOALS = [];
function ring(frac, color) {
  const r = 46, c = 2 * Math.PI * r, f = Math.max(0, Math.min(1, frac));
  return `<div class="ring"><svg viewBox="0 0 108 108"><circle class="bg" cx="54" cy="54" r="${r}"/>
    <circle class="fg" cx="54" cy="54" r="${r}" stroke="${color}" stroke-dasharray="${c}" stroke-dashoffset="${c}" data-off="${c * (1 - f)}"/></svg>
    <div class="c"><div><b>${Math.round(frac * 100)}%</b><span>funded</span></div></div></div>`;
}
loaders.goals = async () => {
  const [calc, raw] = await Promise.all([api("/calc/goals"), api("/api/goals")]);
  GOALS = raw;
  const on = calc.goals.filter((g) => g.status === "on_track").length;
  const nearest = calc.goals.slice().sort((a, b) => a.months - b.months)[0];
  $("#goalKpis").innerHTML = kpi("Goals", calc.goals.length, `${on} on track at steady growth`, meter(calc.goals.length ? on / calc.goals.length : 0)) +
    kpi("Needed each month", money(calc.total_required_monthly), `all goals, in ${BASE()}`) +
    kpi("Nearest goal", nearest ? `<span class="txt">${esc(nearest.name.split(" (")[0])}</span>` : "—", nearest ? nearest.months + " months away" : "");
  $("#goalCards").innerHTML = calc.goals.map((g) => {
    const color = g.status === "on_track" ? css("--good") : g.status === "close" ? css("--gold") : ccyColor(g.currency);
    const f = (v) => money(v, g.currency);
    const by = new Date(); by.setMonth(by.getMonth() + g.months);
    return `<div class="card"><h3>${esc(g.name)} <span class="right"><span class="pill ${g.status}" title="If growth were the same every year">${g.verdict} at steady growth</span><button class="sm ghost" onclick="editGoal(${g.id})">Edit</button></span></h3>
      <div class="goal">${ring(g.progress_pct, color)}
        <div><div class="eyebrow">Save each month</div><div class="need">${f(g.required_monthly)}<small> / month</small></div>
          <div class="hint">Target ${f(g.target_future)} by ${MON[by.getMonth()]} ${by.getFullYear()} · ${g.months} months</div></div>
        <div class="goal-foot">${esc(g.explanation)}${g.note ? `<div class="hint" style="margin-top:6px">${esc(g.note)}</div>` : ""}</div></div>
      <div class="chartbox short" style="margin-top:10px"><canvas id="gch${g.id}"></canvas></div></div>`;
  }).join("") || `<div class="empty">No goals yet. <button class="sm" onclick="editGoal()">＋ Add a goal</button></div>`;
  requestAnimationFrame(() => requestAnimationFrame(() => $$(".ring .fg").forEach((c) => c.style.strokeDashoffset = c.dataset.off)));
  calc.goals.forEach((g) => {
    const col = ccyColor(g.currency);
    chart("gch" + g.id, { type: "line", data: { labels: g.path.map((p) => "m" + p.month),
      datasets: [{ label: "Projected", data: g.path.map((p) => p.balance), borderColor: col, borderWidth: 2.5, fill: true, backgroundColor: (c) => areaGradient(c, col), tension: .3, pointRadius: 0 },
                 { label: "Target", data: g.path.map((p) => p.target), borderColor: css("--gold"), borderDash: [5, 5], borderWidth: 2, pointRadius: 0 }] },
      options: { plugins: { legend: { position: "bottom", labels: { boxWidth: 10, usePointStyle: true } }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${money(c.raw, g.currency)}` } } },
        scales: { x: { ticks: { maxTicksLimit: 6 }, grid: { display: false } }, y: { ticks: { maxTicksLimit: 4, callback: (v) => compact(v, g.currency) } } } } });
  });
};
window.editGoal = (id) => {
  const row = GOALS.find((g) => g.id === id) || { currency: BASE(), annual_return: 0.05, inflation: 0.02, priority: 2, saved: 0, monthly: 0 };
  dialog(id ? "Edit goal" : "New goal", [["name", "Goal"], ["target_today", "Cost in today's money", "number"],
    ["currency", "Currency", "select", CFG.currencies], ["target_date", "Needed by", "date"],
    ["saved", "Already set aside", "number"], ["monthly", "Saving per month", "number"],
    ["annual_return", "Expected growth per year (0.05 = 5%)", "number"], ["inflation", "Inflation per year (0.02 = 2%)", "number"],
    ["risk", "How the money is invested", "select", [["", "Guess from the growth rate"], ["cash", "Cash / savings account"], ["balanced", "Balanced mix"], ["growth", "Mostly shares"], ["glide", "Shares now, safer as the date nears"]]],
    ["priority", "Priority (1 = must, 3 = nice)", "select", [1, 2, 3]], ["note", "Note", "textarea"], ...customFields("goals")], row,
    async (r) => { await api("/api/goals", { method: "POST", body: r }); loaders.goals(); },
    async (i) => { await api("/api/goals/" + i, { method: "DELETE" }); loaders.goals(); });
};

// ---------------- PLAN ----------------
let EXP = [];
const EXP_CATS = ["Rent / Warmmiete", "Utilities & internet", "Groceries", "Transport", "Insurance", "Childcare & school",
  "Eating out", "Shopping", "Travel", "Subscriptions", "Support to family", "Loan / EMI", "Other"];
loaders.plan = async () => {
  const [cf, exp] = await Promise.all([api("/calc/cashflow"), api("/api/expenses")]);
  EXP = exp;
  $("#cfKpis").innerHTML = kpi("Take-home", eur(cf.income), "per month") + kpi("Spending", eur(cf.spend), exp.length + " categories") +
    kpi("Saved", `<span class="${cf.savings >= 0 ? "pos" : "neg"}">${eur(cf.savings)}</span>`, `savings rate ${pct(cf.savings_rate, 0)} · aim 20%+`, meter(cf.savings_rate / .3)) +
    kpi("Emergency cover", cf.emergency_months + " mo", "cash ÷ monthly spending · aim 3–6", meter(cf.emergency_months / 6, css("--eur")));
  const pal = palette(), sorted = exp.slice().sort((a, b) => b.amount - a.amount);
  const segs = sorted.map((e, i) => [e.category, e.amount, pal[i % pal.length]]);
  if (cf.savings > 0) segs.push(["Saved", cf.savings, css("--good")]);
  const tot = Math.max(cf.income, cf.spend) || 1;
  $("#flow").innerHTML = cf.income || exp.length ? `<div class="flowbar">${segs.map(([n, a, c]) => `<div style="flex-grow:${a};background:${c}" title="${esc(n)}: ${eur(a)}">${a / tot > .09 ? esc(n.split(" ")[0]) + " " + pct(a / tot, 0) : ""}</div>`).join("")}</div>
    <div class="flowlegend">${segs.map(([n, a, c]) => `<span><i style="background:${c}"></i>${esc(n)} <b class="num">${eur(a)}</b></span>`).join("")}</div>`
    : `<div class="empty">Add your take-home pay in Settings and your spending here to see where the money goes.</div>`;
  $("#expTbl").innerHTML = `<thead><tr><th>Category</th><th class="n">€ / month</th><th class="n">Share</th></tr></thead><tbody>` +
    (sorted.map((e) => `<tr class="click" onclick="editExpense(${e.id})"><td>${esc(e.category)}${e.note ? ` <span class="hint">${esc(e.note)}</span>` : ""}</td>
      <td class="n" data-l="€ / month">${eur(e.amount)}</td><td class="n" data-l="Share">${cf.income ? pct(e.amount / cf.income, 0) : "—"}</td></tr>`).join("") ||
      `<tr><td colspan="3"><div class="empty">No spending yet.<br><button class="sm" onclick="editExpense()">＋ Add a category</button></div></td></tr>`) + "</tbody>";
  drawRule(cf, exp);
  $("#cfTips").innerHTML = (cf.tips.length ? cf.tips : ["Add income and spending to get suggestions."]).map((t) => `<li>${esc(t)}</li>`).join("");
  const act = cf.actuals || {};
  $("#cfSrc").innerHTML = "Take-home pay from: " + esc(cf.income_source) + (act.count ? ` · <b>Actual (Money tab, last ${act.months} months):</b> in ${eur(act.income)}/month, out ${eur(act.expense)}/month` : " · Log real income and spending in <b>Money</b>, or set a take-home figure in Settings → You.");
};
const WANTS = ["Eating out", "Shopping", "Travel", "Subscriptions", "Other"];
function drawRule(cf, exp) {
  if (!cf.income) { $("#rule").innerHTML = `<div class="empty">Set your take-home pay in Settings to see the check.</div>`; return; }
  const wants = exp.filter((e) => WANTS.includes(e.category)).reduce((a, e) => a + e.amount, 0);
  const needs = cf.spend - wants, save = Math.max(cf.savings, 0);
  const rows = [["Needs", "rent, food, childcare, insurance, family support", needs, .5, "#5b4bd6", "under"],
                ["Wants", "eating out, shopping, travel, subscriptions", wants, .3, "#f472b6", "under"],
                ["Savings", "what's left each month", save, .2, css("--good"), "over"]];
  $("#rule").innerHTML = `<div class="rule">${rows.map(([n, sub, v, t, c, dir]) => {
    const f = v / cf.income, ok = dir === "under" ? f <= t : f >= t;
    return `<div class="rule-row"><div class="name">${n}<small>${sub}</small></div>
      <div class="rule-track"><i style="width:0;background:${c};box-shadow:0 0 12px ${c}66" data-w="${Math.min(f, 1) * 100}%"></i><b style="left:${t * 100}%" data-t="${t * 100}% target"></b></div>
      <div class="val">${eur(v)} · ${pct(f, 0)}<em class="${ok ? "pos" : "neg"}">${ok ? "✓ on target" : dir === "under" ? "above target" : "below target"}</em></div></div>`;
  }).join("")}</div>
  <div class="rule-verdict">${save / cf.income >= .2 ? `You save ${pct(save / cf.income, 0)} of your pay — above the 20% rule of thumb. The next question is where that money goes: goals first, then investing.` :
    `You save ${pct(save / cf.income, 0)} of your pay. Reaching 20% means finding about ${eur(cf.income * .2 - save)} a month — start with the biggest "wants" line.`}</div>`;
  requestAnimationFrame(() => requestAnimationFrame(() => $$("#rule .rule-track i").forEach((i) => i.style.width = i.dataset.w)));
}
window.editExpense = (id) => {
  const row = EXP.find((e) => e.id === id) || {};
  dialog(id ? "Edit budget line" : "Add a budget line", [["category", "Category", "select", EXP_CATS], ["amount", `${BASE()} per month`, "number"], ["note", "Note"]], row,
    async (r) => { await api("/api/expenses", { method: "POST", body: r }); loaders.plan(); },
    async (i) => { await api("/api/expenses/" + i, { method: "DELETE" }); loaders.plan(); });
};

// ---------------- INVEST ----------------
let HOLD = [];
loaders.invest = async () => {
  const h = await api("/api/holdings");
  HOLD = h;
  let val = 0, cost = 0; const alloc = {};
  const rows = h.map((x) => {
    const px = x.last_price ?? x.avg_cost; const v = x.qty * px, c = x.qty * x.avg_cost;
    const vb = conv(v, x.currency) ?? v, cb = conv(c, x.currency) ?? c; val += vb; cost += cb;
    alloc[x.asset_type] = (alloc[x.asset_type] || 0) + vb;
    const g = v - c;
    return `<tr class="click" onclick="editHolding(${x.id})"><td>${esc(x.name)}<div class="hint" style="font-weight:400">${esc(x.ticker || "no ticker")}${x.account ? " · " + esc(x.account) : ""}</div></td>
      <td data-l="Type">${esc(x.asset_type)}</td><td class="n" data-l="Units">${x.qty}</td>
      <td class="n" data-l="Price">${money(px, x.currency)}<div class="hint">${x.price_date || "manual"}</div></td><td class="n" data-l="Value">${money(v, x.currency)}</td>
      <td class="n ${g >= 0 ? "pos" : "neg"}" data-l="Gain">${g >= 0 ? "+" : ""}${money(g, x.currency)}<div class="hint">${c ? pct(g / c) : ""}</div></td></tr>`;
  });
  $("#holdTbl").innerHTML = `<thead><tr><th>Holding</th><th>Type</th><th class="n">Units</th><th class="n">Price</th><th class="n">Value</th><th class="n">Gain</th></tr></thead><tbody>` +
    (rows.join("") || `<tr><td colspan="6"><div class="empty">No holdings yet — add your ETFs, funds, shares or pension accounts.<br><button class="sm" onclick="editHolding()">＋ Add a holding</button></div></td></tr>`) + "</tbody>";
  $("#invKpis").innerHTML = kpi("Invested value", eur(val)) + kpi("Paid in", eur(cost)) +
    kpi("Gain / loss", `<span class="${val - cost >= 0 ? "pos" : "neg"}">${val - cost >= 0 ? "+" : ""}${eur(val - cost)}</span>`, cost ? pct((val - cost) / cost) + " overall" : "");
  chart("chAlloc", doughnut(Object.keys(alloc), Object.values(alloc), [eur(val), "invested"]));
};
window.editHolding = (id) => {
  const row = HOLD.find((x) => x.id === id) || { asset_type: "ETF", currency: BASE(), country: CFG.countries?.[0] || "" };
  dialog(id ? "Edit holding" : "Add holding", [["name", "Name (e.g. Vanguard FTSE All-World)"], ["ticker", "Yahoo ticker (optional)"],
    ["asset_type", "Type", "select", ["ETF", "Mutual fund", "Stock", "Bond", "Gold", "Crypto", "Retirement"]],
    ["account", "Where (broker/bank)"], ["country", "Country", "select", ["", ...(CFG.countries || [])]],
    ["qty", "Units", "number"], ["avg_cost", "Average buy price per unit", "number"],
    ["currency", "Currency", "select", CFG.currencies], ["last_price", "Current price (blank = automatic)", "number"],
    ["bought", "First bought on (for holding periods)", "date"],
    ["asset_class", "Asset class", "select", [["shares", "Shares"], ["bonds", "Bonds"], ["cash", "Cash / money market"], ["gold", "Gold"], ["property", "Property (REIT)"], ["pension", "Pension"], ["other", "Other"]]],
    ["lookthrough", "Tracks (for Diversify)", "select", [["", "guess from the name"], ["ftse_all_world", "FTSE All-World"], ["msci_world", "MSCI World"], ["sp500", "S&P 500"], ["nasdaq100", "Nasdaq 100"], ["stoxx600", "STOXX Europe 600"], ["dax", "DAX"], ["msci_em", "MSCI Emerging Markets"], ["nifty50", "Nifty 50"], ["global_bonds", "Global bonds"], ["gold", "Gold"]]],
    ["payout", "Income", "select", [["accumulating", "Accumulating (reinvests)"], ["distributing", "Distributing (pays out)"]]],
    ["ter", "Yearly cost (TER, 0.0022 = 0.22%)", "number"], ...customFields("holdings")], row,
    async (r) => { await api("/api/holdings", { method: "POST", body: r }); loaders.invest(); },
    async (i) => { await api("/api/holdings/" + i, { method: "DELETE" }); loaders.invest(); });
};
window.refreshPrices = async () => {
  $("#refreshMsg").textContent = "Refreshing prices…";
  try { const r = await api("/calc/refresh-prices", { method: "POST", body: {} }); $("#refreshMsg").textContent = r.messages.join(" · "); toast("Prices refreshed"); }
  catch (e) { $("#refreshMsg").textContent = e.message; }
  loadFx(); loaders.invest();
};

// ---------------- LEARN ----------------
const formData = (f) => Object.fromEntries([...new FormData(f)].filter(([, v]) => !(v instanceof File)));
$("#btForm").onsubmit = async (e) => {
  e.preventDefault(); const f = e.target; const body = formData(f);
  body.cost_pct = +body.cost_pct / 100;
  if (f.file.files[0]) body.csv = await f.file.files[0].text();
  $("#btOut").className = ""; $("#btOut").textContent = "Running…";
  try {
    const r = await api("/calc/backtest", { method: "POST", body });
    const m = r.metrics, b = r.buy_hold;
    const row = (l, a, bb, cls = "") => `<tr><td>${l}</td><td class="n ${cls}" data-l="Rule">${a}</td><td class="n ${cls}" data-l="Buy & hold">${bb}</td></tr>`;
    $("#btOut").innerHTML = `<table class="rt"><thead><tr><th></th><th class="n">Rule</th><th class="n">Buy &amp; hold</th></tr></thead><tbody>
      ${row("Ended with", eur(m.final), eur(b.final))}${row("Growth per year", pct(m.cagr), pct(b.cagr))}
      ${row("Worst fall", pct(m.max_drawdown, 0), pct(b.max_drawdown, 0), "neg")}${row("Bumpiness", pct(m.volatility, 0), pct(b.volatility, 0))}
      ${row("Return per risk", m.sharpe, b.sharpe)}</tbody></table>
      <div class="result">${esc(r.verdict)}</div><p class="hint">Data: ${esc(r.source)} · ${m.years} years</p>`;
    chart("chBt", { type: "line", data: { labels: r.series.map((s) => s.d), datasets: [
      { label: "Rule", data: r.series.map((s) => s.s), borderColor: css("--eur"), borderWidth: 2, pointRadius: 0, fill: true, backgroundColor: (c) => areaGradient(c, css("--eur")) },
      { label: "Buy & hold", data: r.series.map((s) => s.b), borderColor: css("--muted"), borderWidth: 1.5, pointRadius: 0 }] },
      options: { interaction: { mode: "index", intersect: false }, plugins: { legend: { position: "bottom", labels: { boxWidth: 10, usePointStyle: true } } },
        scales: { x: { ticks: { maxTicksLimit: 6 }, grid: { display: false } } } } });
  } catch (err) { $("#btOut").innerHTML = `<p class="err">${esc(err.message)}</p>`; }
};
$("#sipForm").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const r = await api("/calc/sip", { method: "POST", body: formData(e.target) });
    $("#sipOut").innerHTML = `<div class="result"><div class="big">${eur(r.value)}</div>${esc(r.explanation)}<div class="hint">Data: ${esc(r.source)}</div></div>`;
    chart("chSip", { type: "line", data: { labels: r.series.map((s) => s.d.slice(0, 7)), datasets: [
      { label: "Worth", data: r.series.map((s) => s.value), borderColor: css("--good"), borderWidth: 2.5, pointRadius: 0, fill: true, backgroundColor: (c) => areaGradient(c, css("--good")) },
      { label: "Paid in", data: r.series.map((s) => s.invested), borderColor: css("--gold"), borderDash: [5, 5], borderWidth: 2, pointRadius: 0 }] },
      options: { interaction: { mode: "index", intersect: false }, plugins: { legend: { position: "bottom", labels: { boxWidth: 10, usePointStyle: true } } },
        scales: { x: { ticks: { maxTicksLimit: 6 }, grid: { display: false } } } } });
  } catch (err) { $("#sipOut").innerHTML = `<p class="err">${esc(err.message)}</p>`; }
};
loaders.learn = async () => {
  const p = await api("/calc/paper");
  $("#paperKpis").innerHTML = kpi("Account value", eur(p.total_value, 2), `started with ${eur(p.start)}`) +
    kpi("Return", `<span class="${p.total_return >= 0 ? "pos" : "neg"}">${p.total_return >= 0 ? "+" : ""}${pct(p.total_return)}</span>`) +
    kpi("Pretend cash", eur(p.cash, 2), "", meter(p.cash / p.start, css("--eur"))) + kpi("Realised profit", eur(p.realized_pnl, 2), "from sells");
  const pos = Object.entries(p.positions);
  $("#paperPos").innerHTML = `<thead><tr><th>Ticker</th><th class="n">Units</th><th class="n">Avg cost</th><th class="n">Price</th><th class="n">Value</th><th class="n">Unrealised</th></tr></thead><tbody>` +
    (pos.map(([t, x]) => `<tr><td>${esc(t)}</td><td class="n" data-l="Units">${x.qty}</td><td class="n" data-l="Avg cost">${x.avg_cost}</td><td class="n" data-l="Price">${x.price}</td><td class="n" data-l="Value">${eur(x.value, 2)}</td>
      <td class="n ${x.unrealized >= 0 ? "pos" : "neg"}" data-l="Unrealised">${eur(x.unrealized, 2)}</td></tr>`).join("") || `<tr><td colspan="6"><div class="empty">No positions. Try buying a few units of an ETF.</div></td></tr>`) + "</tbody>";
  $("#paperHist").innerHTML = `<thead><tr><th>When</th><th>Side</th><th>Ticker</th><th class="n">Units</th><th class="n">Price</th><th></th></tr></thead><tbody>` +
    p.trades.slice().reverse().map((t) => `<tr><td>${t.ts.replace("T", " ")}</td><td data-l="Side">${t.side}</td><td data-l="Ticker">${esc(t.ticker)}</td><td class="n" data-l="Units">${t.qty}</td><td class="n" data-l="Price">${t.price}</td>
      <td data-l=""><button class="link" onclick="delTrade(${t.id})">undo</button></td></tr>`).join("") + "</tbody>";
};
$("#paperForm").onsubmit = async (e) => {
  e.preventDefault(); $("#paperErr").textContent = "";
  const b = formData(e.target); ["qty", "price", "fee"].forEach((k) => b[k] = +b[k]); b.ticker = b.ticker.trim().toUpperCase();
  try { await api("/api/paper_trades", { method: "POST", body: b }); toast("Pretend order placed"); e.target.qty.value = ""; loaders.learn(); }
  catch (err) { $("#paperErr").textContent = err.message; }
};
window.getQuote = async (e) => {
  e.preventDefault(); const f = $("#paperForm");
  try { const q = await api("/calc/quote/" + encodeURIComponent(f.ticker.value.trim())); f.price.value = q.price; }
  catch (err) { $("#paperErr").textContent = err.message; }
};
window.delTrade = async (id) => { await api("/api/paper_trades/" + id, { method: "DELETE" }); loaders.learn(); };


// ---------------- TAX (from country packs) ----------------
let CAL = [];
loaders.tax = async () => {
  const [cal, t] = await Promise.all([api("/calendar"), api("/tax/calculators")]);
  CAL = cal;
  $("#taxEyebrow").textContent = "Tax · " + (CFG.packs.map((p) => p.flag + " " + p.name).join(" · ") || "no countries switched on");
  drawCal();
  $("#calcs").innerHTML = t.calculators.map((c, i) => `<div class="card calc"><h3>${c.flag} ${esc(c.title)} <span class="sub">${esc(c.country)} pack</span></h3>
    <form class="form" data-i="${i}">${c.inputs.map((f) => {
      const v = f.default ?? "";
      if (f.type === "bool") return `<label class="wide" style="display:flex;gap:8px;align-items:center;color:var(--ink)"><input type="checkbox" name="${f.id}" ${v ? "checked" : ""}> ${esc(f.label)}</label>`;
      if (f.type === "select") return `<label>${esc(f.label)}<select name="${f.id}">${f.options.map((o) => `<option ${String(o) === String(v) ? "selected" : ""}>${o}</option>`).join("")}</select></label>`;
      return `<label>${esc(f.label)}<input name="${f.id}" type="${f.type === "date" ? "date" : "number"}" step="any" value="${esc(v)}"></label>`;
    }).join("")}<button>Calculate</button></form>
    <div class="calcout"></div>${c.help ? `<details style="margin-top:8px"><summary class="hint">Tips</summary><p class="hint">${esc(c.help)}</p></details>` : ""}</div>`).join("")
    || `<div class="empty">No calculators — switch on a country pack in Settings.</div>`;
  $$("#calcs form").forEach((f) => f.onsubmit = async (e) => {
    e.preventDefault();
    const c = t.calculators[+f.dataset.i], inputs = {};
    c.inputs.forEach((x) => { const el = f.elements[x.id]; inputs[x.id] = x.type === "bool" ? el.checked : x.type === "number" ? +el.value || 0 : el.value; });
    const out = f.parentElement.querySelector(".calcout");
    try {
      const r = await api("/tax/run", { method: "POST", body: { pack: c.pack, calculator: c.id, inputs } });
      out.innerHTML = `<div class="result"><div class="eyebrow">${esc(r.headline_label)}</div><div class="big ${r.tone === "good" ? "pos" : r.tone === "bad" ? "neg" : ""}">${esc(r.headline)}</div>${esc(r.explanation)}
        ${r.rows?.length ? `<table>${r.rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="n">${esc(v)}</td></tr>`).join("")}</table>` : ""}
        ${r.table ? `<table><tr>${r.table.columns.map((x) => `<th class="n">${esc(x)}</th>`).join("")}</tr>${r.table.rows.map((row) => `<tr>${row.map((x, j) => `<td class="${j ? "n" : ""}">${esc(x)}</td>`).join("")}</tr>`).join("")}</table>` : ""}</div>`;
    } catch (err) { out.innerHTML = `<p class="err">${esc(err.message)}</p>`; }
  });
  $("#checklists").innerHTML = t.checklists.filter((c) => c.items.length).map((c) => `<div class="card"><h3>${c.flag} ${esc(c.name)} checklist</h3><ul class="ideas">${c.items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`).join("");
};
function drawCal() {
  const show = $("#showDone").checked, open = CAL.filter((c) => c.status !== "done");
  const soon = open.filter((c) => c.due && daysTo(c.due) <= 45).length, done = CAL.length - open.length, health = CAL.length ? done / CAL.length : 0;
  $("#taxKpis").innerHTML = `<div class="kpi gauge">${ring(health, health > .7 ? css("--good") : health > .35 ? css("--gold") : css("--lilac")).replace("funded", "done")}
      <div><div class="l">Compliance</div><div class="v">${done}/${CAL.length}</div><div class="s">${open.length} open</div></div></div>` +
    kpi(`<span class="dot" style="background:var(--bad)"></span>Due within 45 days`, `<span class="${soon ? "neg" : "pos"}">${soon}</span>`, soon ? "act on these first" : "nothing urgent") +
    CFG.packs.slice(0, 2).map((p) => kpi(`${p.flag} ${esc(p.name)}`, open.filter((c) => c.country === p.code).length, "open items")).join("");
  $("#calendar").innerHTML = timeline(CAL.filter((c) => show || c.status !== "done"), { actions: true }) || `<div class="empty">No deadlines. Answer the yes/no questions in Settings, or add your own.</div>`;
  requestAnimationFrame(() => requestAnimationFrame(() => $$("#taxKpis .ring .fg").forEach((c) => c.style.strokeDashoffset = c.dataset.off)));
}
$("#showDone").onchange = drawCal;
window.toggleCal = async (key, status) => {
  await api("/calendar/status", { method: "POST", body: { key, status: status === "done" ? "open" : "done" } });
  toast(status === "done" ? "Reopened" : "Marked done"); CAL = await api("/calendar"); drawCal();
};
window.addDeadline = () => dialog("Add your own deadline", [["title", "What needs doing"], ["due", "Due date", "date"],
  ["country", "Country", "select", ["", ...(CFG.countries || [])]], ["severity", "Importance", "select", ["normal", "high", "critical"]], ["detail", "Details / how", "textarea"]],
  { severity: "normal" }, async (r) => { await api("/api/calendar", { method: "POST", body: r }); loaders.tax(); });
window.delDeadline = async (id) => { await api("/api/calendar/" + id, { method: "DELETE" }); loaders.tax(); };

// ---------------- RULES ----------------
const RULE_EXAMPLE = `# Your own rules — checked before the country packs. Same id as a pack rule = replace it.
document_rules:
  - id: my_gym_invoice
    label: Gym membership invoice
    category: Receipts & bills
    confidence: 0.9
    match:
      text_any: [fitnessfirst, mcfit]      # words to look for (spaces/punctuation ignored)
      filename_any: [gym]
    extract:
      - {name: invoice_no, pattern: "Rechnungsnummer\\\\s*:?\\\\s*(\\\\w+)"}
    route:
      folder: "{folder:DE}/Receipts/{first_year}"
      filename: "{first_date}_gym_{invoice_no}{ext}"

deadlines:
  - id: my_car_insurance
    title: "Renew car insurance ({year})"
    due: "{year}-11-30"
    severity: normal
    detail: Compare quotes before the 30 Nov switching deadline.
`;
let RULES = null;
loaders.rules = async () => {
  RULES = await api("/rules");
  $("#rulesDir").textContent = RULES.rules_dir;
  const files = Object.entries(RULES.user_files);
  $("#userRules").value = files.length ? files[0][1] : "";
  $("#userRules").dataset.file = files.length ? files[0][0] : "my-rules.yaml";
  $("#rulesMsg").innerHTML = RULES.errors.length ? `<span class="err">${esc(RULES.errors.join("; "))}</span>` : files.length > 1 ? `Also loaded: ${files.slice(1).map((f) => esc(f[0])).join(", ")}` : "";
  const badge = (s) => `<span class="srcbadge ${s?.startsWith("yours") ? "yours" : s?.startsWith("tracker") ? "tracker" : ""}">${esc(s || "")}</span>`;
  $("#docRuleCount").textContent = `${RULES.document_rules.length} rules, checked in this order`;
  $("#docRules").innerHTML = `<thead><tr><th>Rule</th><th>Category</th><th>Looks for</th><th>Files to</th><th>Source</th></tr></thead><tbody>` + RULES.document_rules.map((r) => {
    const m = r.match || {};
    const looks = [...(m.text_all || []).map((w) => `<b>${esc(w)}</b>`), ...(m.text_any || []).map(esc)].slice(0, 5).join(", ") + (m.filename_any?.length ? ` <span class="hint">· name: ${esc(m.filename_any.slice(0, 3).join(", "))}</span>` : "");
    return `<tr><td>${esc(r.label || r.id)}<div class="hint" style="font-weight:400">${esc(r.id)} · ${Math.round((r.confidence || .8) * 100)}%</div></td><td data-l="Category">${esc(r.category || "")}</td>
      <td data-l="Looks for" style="font-size:13px">${looks}</td><td data-l="Files to" style="font:500 12px var(--num);color:var(--muted)">${esc(r.route?.folder || "")}<br>${esc(r.route?.filename || "")}</td><td data-l="Source">${badge(r._source)}</td></tr>`;
  }).join("") + "</tbody>";
  $("#dlRules").innerHTML = `<thead><tr><th>Deadline</th><th>Due</th><th>Only if</th><th>Source</th></tr></thead><tbody>` + RULES.deadline_rules.map((r) =>
    `<tr><td>${esc(hideAmt(r.title))}</td><td data-l="Due" style="font:500 12.5px var(--num)">${esc(r.due)}</td><td data-l="Only if" class="hint">${esc(r.if || "always")}</td><td data-l="Source">${badge(r._source)}</td></tr>`).join("") + "</tbody>";
};
$("#saveRules").onclick = async () => {
  try { RULES = await api("/rules/user", { method: "POST", body: { file: $("#userRules").dataset.file || "my-rules.yaml", text: $("#userRules").value } });
    toast("Rules saved and applied"); loaders.rules(); }
  catch (e) { $("#rulesMsg").innerHTML = `<span class="err">${esc(e.message)}</span>`; }
};
$("#exampleRules").onclick = () => { const t = $("#userRules"); t.value = (t.value.trim() ? t.value.trimEnd() + "\n\n" : "") + RULE_EXAMPLE; };
async function testRuleFile(file) {
  $("#ruleTestOut").innerHTML = `<p class="hint">Reading ${esc(file.name)}…</p>`;
  try {
    const a = await api("/rules/test", { method: "POST", body: { filename: file.name, data: await readAsDataURL(file) } });
    $("#ruleTestOut").innerHTML = `<div class="result"><div class="eyebrow">${esc(a.method)}</div><div class="big" style="font-size:22px">${esc(a.label)}</div>
      ${a.confidence ? `${Math.round(a.confidence * 100)}% sure · matched on ${esc(a.matched_on)} · rule <code>${esc(a.doc_type)}</code> (${esc(a.rule_source || "")})` : "No rule matched — it would go to your inbox folder."}
      <p style="margin:8px 0 0">Would file to <code>${esc(a.folder)}/${esc(a.filename)}</code></p>
      ${Object.keys(a.fields || {}).length ? `<div class="fchips">${Object.entries(a.fields).filter(([k]) => k !== "dates").map(([k, v]) => `<span class="fchip"><b>${esc(k)}</b>${esc(v)}</span>`).join("")}</div>` : ""}
      ${a.candidates?.length ? `<p class="hint" style="margin:10px 0 4px">All rules that matched:</p>${a.candidates.map((c) => `<div class="candrow"><span>${esc(c.label)} <span class="hint">· ${esc(c.on)}</span></span><b>${Math.round(c.score * 100)}%</b><div class="bar"><i style="width:${c.score * 100}%"></i></div></div>`).join("")}` : ""}</div>`;
  } catch (e) { $("#ruleTestOut").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}
$("#ruleFile").onchange = (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) testRuleFile(f); };
["dragenter", "dragover"].forEach((ev) => $("#ruleDrop").addEventListener(ev, (e) => { e.preventDefault(); $("#ruleDrop").classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => $("#ruleDrop").addEventListener(ev, (e) => { e.preventDefault(); $("#ruleDrop").classList.remove("over"); }));
$("#ruleDrop").addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) testRuleFile(f); });

// ---------------- SETTINGS ----------------
loaders.settings = async () => {
  await loadConfig();
  const c = CFG, app = await api("/api-settings");
  const qs = c.all_packs.filter((p) => c.countries.includes(p.code)).flatMap((p) => (p.questions || []).map((q) => ({ ...q, flag: p.flag })));
  $("#setGeneral").innerHTML = `<label>First name <input name="name" value="${esc(c.profile.name || "")}"></label>
    <label>About you — one or two lines the assistant should know <textarea name="about" rows="2" placeholder="e.g. Employee in Germany, married, one child; buying a flat in India">${esc(c.profile.about || "")}</textarea></label>
    <label>Take-home pay per month in ${esc(c.base_currency)} (blank = average from Money) <input name="monthly_income" type="number" value="${esc(app.monthly_income || "")}"></label>
    <div class="packpick">${c.all_packs.map((p) => `<label><input type="checkbox" name="country" value="${p.code}" ${c.countries.includes(p.code) ? "checked" : ""}><span class="fl">${p.flag}</span><b>${esc(p.name)}</b><small>${p.currency} · ${p.source}</small></label>`).join("")}</div>
    ${qs.length ? `<div class="qlist">${qs.map((q) => `<label><input type="checkbox" data-q="${q.id}" ${c.profile.answers?.[q.id] ? "checked" : ""}><span class="fl">${q.flag}</span><span>${esc(q.label)}</span></label>`).join("")}</div>` : ""}
    <button>Save</button>`;
  $("#setGeneral").onsubmit = async (e) => {
    e.preventDefault(); const f = e.target, answers = {};
    $$("[data-q]", f).forEach((x) => answers[x.dataset.q] = x.checked);
    await api("/config", { method: "POST", body: { countries: $$("input[name=country]:checked", f).map((x) => x.value), profile: { name: f.name.value, about: f.about.value, answers } } });
    await api("/api-settings", { method: "POST", body: { monthly_income: f.monthly_income.value } });
    toast("Saved"); loaders.settings();
  };
  const others = c.currencies.filter((x) => x !== c.base_currency);
  $("#setFx").innerHTML = `<div class="row2"><label>Base currency <select name="base">${[...new Set([...c.currencies, ...c.common_currencies])].map((x) => `<option ${x === c.base_currency ? "selected" : ""}>${x}</option>`).join("")}</select></label>
    <label>Extra currencies <input name="extra" value="${esc((c.extra_currencies || []).join(", "))}" placeholder="USD, CHF"></label></div>
    <label>Exchange rates <select name="source"><option value="ecb" ${c.fx.source !== "manual" ? "selected" : ""}>European Central Bank (daily, automatic)</option><option value="manual" ${c.fx.source === "manual" ? "selected" : ""}>My own rates</option></select></label>
    ${others.map((x) => `<label>1 ${esc(c.base_currency)} = ? ${esc(x)} <input name="rate_${x}" type="number" step="any" value="${esc(c.fx.manual_rates?.[x] || c.rates?.[x] || "")}"></label>`).join("")}
    <div style="display:flex;gap:8px"><button>Save</button><button type="button" class="ghost" id="fxRefresh">↻ Refresh from ECB</button></div>`;
  $("#setFx").onsubmit = async (e) => {
    e.preventDefault(); const f = e.target, manual = {};
    others.forEach((x) => { const v = f["rate_" + x].value; if (v) manual[x] = +v; });
    await api("/config", { method: "POST", body: { base_currency: f.base.value, extra_currencies: f.extra.value.split(/[,\s]+/).map((x) => x.trim().toUpperCase()).filter((x) => /^[A-Z]{3}$/.test(x)), fx: { source: f.source.value, manual_rates: manual } } });
    toast("Saved"); loaders.settings();
  };
  $("#fxRefresh").onclick = async () => { try { const r = await api("/fx/refresh", { method: "POST", body: {} }); $("#fxMsg").textContent = r.message; loaders.settings(); } catch (e) { $("#fxMsg").textContent = e.message; } };
  $("#setDocs").innerHTML = `<label>Documents folder <input name="root" value="${esc(c.documents_root)}"></label><p class="hint" style="margin:0">Now: <code>${esc(c.documents_root_resolved)}</code></p>
    ${[...c.countries, "inbox"].map((k) => `<label>Folder for ${k === "inbox" ? "unrecognised files" : flagFor(k) + " " + esc(countryName(k))} <input name="f_${k}" value="${esc(c.folders?.[k] || "")}" placeholder="${esc(k === "inbox" ? "_Inbox" : (c.all_packs.find((p) => p.code === k)?.default_folder || k))}"></label>`).join("")}
    <button>Save</button>`;
  $("#setDocs").onsubmit = async (e) => {
    e.preventDefault(); const f = e.target, folders = {};
    [...c.countries, "inbox"].forEach((k) => { const v = f["f_" + k].value.trim(); if (v) folders[k] = v; });
    await api("/config", { method: "POST", body: { documents_root: f.root.value.trim(), folders } }); toast("Saved"); loaders.settings();
  };
  const pv = c.providers, ai = c.ai;
  const drawAI = (k) => {
    const v = pv[k], secretKey = { anthropic: "anthropic_api_key", azure_openai: "azure_openai_api_key", github_models: "github_token" }[k];
    $("#setAI").innerHTML = `<label>Provider <select name="provider">${Object.entries(pv).map(([kk, vv]) => `<option value="${kk}" ${kk === k ? "selected" : ""}>${esc(vv.label)}</option>`).join("")}</select></label>
      ${k !== "none" ? `<p class="hint" style="margin:0">${esc(v.help || "")}</p>` : `<p class="hint" style="margin:0">Everything works without AI. Connect one to chat about your finances.</p>`}
      ${k === "azure_openai" || k === "ollama" ? `<label>Endpoint <input name="endpoint" value="${esc(ai.endpoint || (k === "ollama" ? "http://localhost:11434" : ""))}"></label>` : ""}
      ${k === "azure_openai" ? `<div class="row2"><label>Deployment <input name="deployment" value="${esc(ai.deployment || "")}"></label><label>API version <input name="api_version" value="${esc(ai.api_version || "2024-10-21")}"></label></div>` : ""}
      ${k !== "none" ? `<label>Model ${v.models ? `<select name="model">${v.models.map((m) => `<option ${m === (ai.model || v.default_model) ? "selected" : ""}>${m}</option>`).join("")}</select>` : `<input name="model" value="${esc(ai.model || "")}">`}</label>` : ""}
      ${secretKey ? `<label>${k === "github_models" ? "GitHub token" : "API key"} <input name="secret" type="password" placeholder="${c.secrets_set[secretKey] ? "saved — leave blank to keep" : "paste here"}"><span class="fieldhint">${c.secrets_storage === "keychain" ? "🔒 Stored in your system keychain (Windows Credential Manager / macOS Keychain), not in a file." : "Stored in secrets.json in your data folder (no system keychain found)."}</span></label>` : ""}
      ${k === "anthropic" ? `<label style="display:flex;gap:8px;align-items:center;color:var(--ink)"><input type="checkbox" name="web" ${ai.web_search !== false ? "checked" : ""}> Allow web search for current tax rules</label>` : ""}
      <div style="display:flex;gap:8px"><button>Save</button>${k !== "none" ? `<button type="button" class="ghost" id="aiTest">Test connection</button>` : ""}</div>`;
    $("#setAI").provider.onchange = (e) => drawAI(e.target.value);
    $("#setAI").onsubmit = async (e) => {
      e.preventDefault(); const f = e.target, body = { ai: { provider: f.provider.value } };
      ["endpoint", "deployment", "api_version", "model"].forEach((x) => { if (f[x]) body.ai[x] = f[x].value.trim(); });
      if (f.web) body.ai.web_search = f.web.checked;
      if (f.secret?.value) body.secrets = { [secretKey]: f.secret.value.trim() };
      await api("/config", { method: "POST", body }); toast("AI settings saved"); CFG = await api("/config"); drawAI(f.provider.value);
    };
    if ($("#aiTest")) $("#aiTest").onclick = async () => { $("#aiMsg").textContent = "Testing…"; try { const r = await api("/ai/test", { method: "POST", body: {} }); $("#aiMsg").innerHTML = `<span class="pos">✓ Connected:</span> ${esc(r.reply)}`; } catch (e) { $("#aiMsg").innerHTML = `<span class="err">${esc(e.message)}</span>`; } };
  };
  drawAI(ai.provider || "none");
  const m = await api("/model");
  MODEL = m;
  const problems = [...m.errors.map((e) => "Model: " + e), ...m.rule_errors.map((e) => "Rules: " + e),
    ...(c.all_packs || []).flatMap((p) => (p.errors || []).map((e) => `${p.flag || ""} ${p.name} pack: ${e}`))];
  const sy = m.last_sync || {};
  const userEnts = Object.entries(m.entities).filter(([, e]) => e.user_defined);
  $("#setData").innerHTML = `<p style="margin-top:0">Data folder:<br><code>${esc(c.data_dir)}</code></p>
    <p class="hint">Back up this folder to keep everything. Automatic backups before any database change go to <code>backups/</code>.
      API keys: ${c.secrets_storage === "keychain" ? "in your system keychain" : "in <code>secrets.json</code> — don't share that file"}.</p>
    <p class="hint" style="margin:6px 0">Database schema v${esc(m.version)} · ${Object.keys(m.entities).length} record types, links between them checked.
      ${sy.rebuilt?.length ? `<br>Updated at start-up (${sy.rebuilt.length} tables) — backup: <code>${esc(sy.backup || "")}</code>` : ""}
      ${(sy.repaired || []).map((r) => `<br>Repaired: ${esc(r)}`).join("")}
      ${(m.secrets_moved_to_keychain || []).length ? `<br>🔒 Moved ${m.secrets_moved_to_keychain.length} API key(s) from the file into your keychain.` : ""}</p>
    <div class="updrow" id="updRow"><span class="hint">Version ${esc(m.app_version || "")}</span>
      <label style="display:flex;gap:8px;align-items:center;margin:0"><input type="checkbox" id="updChk" ${c.updates?.check !== false ? "checked" : ""}> Check for updates once a day</label>
      <button class="sm ghost" type="button" id="updNow">Check now</button><span class="hint" id="updMsg"></span></div>
    ${problems.length ? `<ul class="probs">${problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>` : `<p class="okline">✓ All packs, rules and the model check out.</p>`}
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">
      <a class="btn sm" href="${withToken("/data/export")}" download>Export everything (JSON)</a>
      <label class="btn sm ghost" style="cursor:pointer">Import from JSON…<input type="file" id="importFile" accept=".json,application/json" hidden></label>
      <button class="sm ghost" onclick="openWizard()">Use a different data folder</button></div>
    ${userEnts.length ? `<p style="margin:12px 0 4px"><b>Your record types</b></p><div style="display:flex;gap:6px;flex-wrap:wrap">${userEnts.map(([k, e]) => `<button class="sm ghost" onclick="openRecords('${k}')">${esc(e.label)}</button>`).join("")}</div>` : ""}`;
  $("#updChk").onchange = async (e) => { await api("/config", { method: "POST", body: { updates: { check: e.target.checked } } }); toast(e.target.checked ? "Update checks on" : "Update checks off"); };
  $("#updNow").onclick = async () => { $("#updMsg").textContent = "Checking…"; const u = await checkUpdate(true);
    $("#updMsg").textContent = !u ? "Couldn't check right now" : !u.enabled ? "Update checks are off" : u.error && !u.latest?.version ? "Couldn't reach the website" : u.newer ? `Version ${u.latest.version} is available` : "You have the latest version"; };
  $("#importFile").onchange = async (e) => {
    const file = e.target.files[0]; e.target.value = ""; if (!file) return;
    let data; try { data = JSON.parse(await file.text()); } catch (err) { toast("That file isn't valid JSON"); return; }
    const n = Object.values(data.tables || {}).reduce((a, r) => a + (r.length || 0), 0);
    dialog("Replace all data?", [["confirm", `This replaces everything in the app with ${n} records from ${file.name} (exported ${data.exported || "?"}). A backup of your current data is made first. Type REPLACE to continue.`]], {},
      async (r) => { const res = await api("/data/import", { method: "POST", body: { data, confirm: r.confirm.trim() } }); toast("Imported — backup saved"); await loadConfig(); loaders.settings(); return res; });
  };
  const EXAMPLE_MODEL = `{
  "extends": {
    "accounts": { "fields": { "iban_last4": { "type": "text", "label": "IBAN (last 4 digits)" } } },
    "goals": { "fields": { "for_whom": { "type": "enum", "values": ["Family", "Me", "Child"], "label": "For whom" } } }
  },
  "entities": {
    "policies": {
      "label": "Insurance policy",
      "fields": {
        "name": { "type": "text", "required": true, "label": "Policy" },
        "insurer": { "type": "text", "label": "Insurer" },
        "premium": { "type": "money", "label": "Premium per year" },
        "renews_on": { "type": "date", "label": "Renews on" },
        "paid_from": { "type": "ref", "to": "accounts", "on_delete": "set_null", "label": "Paid from account" }
      }
    }
  }
}`;
  $("#setModel").innerHTML = `<p class="hint" style="margin-top:0">Add your own fields to accounts, goals, assets… or whole new record types (insurance policies, loans, subscriptions). Types: text, number, money, int, bool, date, enum, ref, currency, country. Links (<code>ref</code>) are checked like the built-in ones.</p>
    <textarea id="modelText" class="code" rows="12" spellcheck="false" placeholder="{ }">${esc(m.user_model_text)}</textarea>
    <p id="modelMsg" class="hint"></p>
    <div style="display:flex;gap:8px"><button class="sm" id="modelSave">Save &amp; apply</button><button class="sm ghost" id="modelEx">Insert an example</button></div>`;
  $("#modelEx").onclick = () => { if (!$("#modelText").value.trim()) $("#modelText").value = EXAMPLE_MODEL; else toast("Clear the box first, or edit it by hand"); };
  $("#modelSave").onclick = async () => {
    try { const r = await api("/model/user", { method: "POST", body: { text: $("#modelText").value } });
      toast(`Saved${r.sync.created.length ? " — new record type: " + r.sync.created.join(", ") : ""}${r.sync.backup ? " (backup made first)" : ""}`);
      await loadConfig(); loaders.settings();
    } catch (e) { $("#modelMsg").innerHTML = `<span class="err">${esc(e.message)}</span>`; }
  };
  const t = await api("/tax/calculators");
  const gl = { "Net worth": "What you own minus what you owe.", "Liquid": "Money you can get within days without a big loss.", "Inflation": "Prices rising over time.",
    "CAGR": "Average yearly growth rate.", "Drawdown": "A fall from a previous high.", "ETF": "A cheap fund traded on an exchange that tracks an index.", ...t.glossary };
  $("#gloss").innerHTML = Object.entries(gl).map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("");
};
// ---------------- ASK CLAUDE ----------------
let CHAT_ID = null, STREAMING = false, META = null;
const md = (t) => { t = hideAmt(t || ""); return window.marked && window.DOMPurify ? DOMPurify.sanitize(marked.parse(t, { breaks: false, gfm: true })) : esc(t).replace(/\n/g, "<br>"); };
function greeting() { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"; }
loaders.chat = async () => {
  loadFx();
  META = await api("/chat/meta");
  const models = META.models.length ? META.models : [META.model].filter(Boolean);
  $("#modelPick").innerHTML = models.map((m) => `<option ${m === META.model ? "selected" : ""}>${esc(m)}</option>`).join("");
  $("#modelPick").style.display = models.length > 1 ? "" : "none";
  await drawChatList();
  if (CHAT_ID) openChat(CHAT_ID); else drawEmpty();
};
async function drawChatList() {
  const list = await api("/chat/list");
  const today = new Date().toISOString().slice(0, 10);
  let last = "";
  $("#chatList").innerHTML = list.map((c) => {
    const d = (c.updated || "").slice(0, 10), label = d === today ? "Today" : d;
    const head = label !== last ? `<div class="day">${label}</div>` : ""; last = label;
    return head + `<div class="ci ${c.id === CHAT_ID ? "on" : ""}" onclick="openChat(${c.id})"><span title="${esc(hideAmt(c.title))}">${esc(hideAmt(c.title))}</span>
      <button onclick="event.stopPropagation();delChat(${c.id})" title="Delete chat" aria-label="Delete chat">✕</button></div>`;
  }).join("") || `<p class="hint" style="padding:4px 8px">Your conversations will appear here.</p>`;
}
function drawEmpty() {
  if (!META?.ready) {
    $("#msgs").innerHTML = `<div class="keycard"><div class="hello" style="margin:0"><div class="mark">✦</div></div><h3 style="text-align:center">Connect an AI assistant — optional</h3>
      <p>Everything else in the app works without AI. To chat about your finances in plain English, connect one of:</p>
      <ul class="ideas"><li><b>Claude</b> (Anthropic API key)</li><li><b>Azure OpenAI / AI Foundry</b> (Microsoft — endpoint, deployment, key)</li>
        <li><b>GitHub Models</b> (Microsoft — free tier with a GitHub token)</li><li><b>Ollama</b> (runs on your own computer — nothing leaves it)</li></ul>
      <button onclick="go('settings')">Open Settings → AI</button></div>`;
    return;
  }
  $("#msgs").innerHTML = `<div class="hello"><div class="mark">✦</div><h2>${greeting()}${META.name ? ", " + esc(META.name) : ""}</h2>
    <p class="muted">Ask about your money, goals, or German and Indian taxes. Answers use your own numbers, in plain English.</p>
    <p class="hint">Connected: ${esc(META.provider_label)} · ${esc(META.model)}</p>
    <div class="sugg">${META.suggestions.map(([i, q, s]) => `<button onclick="askSuggest(this)" data-q="${esc(q)}"><span class="si">${i}</span><span>${esc(q)}<small>${esc(s)}</small></span></button>`).join("")}</div></div>`;
}
window.askSuggest = (b) => { $("#prompt").value = b.dataset.q; send(); };
window.newChat = () => { CHAT_ID = null; drawEmpty(); drawChatList(); $("#chatSide").classList.remove("open"); $("#prompt").focus(); };
window.delChat = async (id) => { await api("/chat/" + id, { method: "DELETE" }); if (CHAT_ID === id) CHAT_ID = null; loaders.chat(); };
window.openChat = async (id) => {
  CHAT_ID = id; $("#chatSide").classList.remove("open");
  const c = await api("/chat/" + id);
  $("#msgs").innerHTML = c.messages.map((m) => m.role === "user" ? userMsg(m.text) : aiMsg(m.text, m.tools)).join("");
  scrollDown(true); drawChatList();
};
const userMsg = (t) => `<div class="msg user"><div class="bub">${esc(t)}</div></div>`;
const aiMsg = (t, tools = []) => `<div class="msg ai"><div class="ai-ico">✦</div><div class="ai-body">
  ${tools.length ? `<div class="chips">${[...new Set(tools)].map((x) => `<span class="chip done">${esc(x)}</span>`).join("")}</div>` : ""}${md(t)}</div></div>`;
function scrollDown(force) { const m = $("#msgs"); if (force || m.scrollHeight - m.scrollTop - m.clientHeight < 160) m.scrollTop = m.scrollHeight; }
async function send() {
  const ta = $("#prompt"), text = ta.value.trim();
  if (!text || STREAMING) return;
  if (!META?.ready) { drawEmpty(); return; }
  if (!CHAT_ID) $("#msgs").innerHTML = "";
  ta.value = ""; autosize();
  $("#msgs").insertAdjacentHTML("beforeend", userMsg(text) +
    `<div class="msg ai" id="live"><div class="ai-ico">✦</div><div class="ai-body"><div class="chips"></div><div class="txt cursor"></div></div></div>`);
  scrollDown(true);
  STREAMING = true; $("#sendBtn").disabled = true; $("#chatStatus").textContent = "Thinking…";
  const live = $("#live"), chipsEl = $(".chips", live), txtEl = $(".txt", live);
  let buf = "", changed = false, pending = false;
  const render = () => { if (pending) return; pending = true; requestAnimationFrame(() => { txtEl.innerHTML = md(buf); pending = false; scrollDown(); }); };
  try {
    const r = await fetch("/chat/send", { method: "POST", headers: HDRS(), body: JSON.stringify({ chat_id: CHAT_ID, text }) });
    if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.detail || r.statusText); }
    const reader = r.body.getReader(), dec = new TextDecoder();
    let pend = "";
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      pend += dec.decode(value, { stream: true });
      let i;
      while ((i = pend.indexOf("\n\n")) >= 0) {
        const block = pend.slice(0, i); pend = pend.slice(i + 2);
        const ev = (block.match(/^event: (.*)$/m) || [])[1], data = JSON.parse((block.match(/^data: (.*)$/m) || [, "{}"])[1]);
        if (ev === "chat") { CHAT_ID = data.id; drawChatList(); }
        else if (ev === "text") { buf += data.t; $("#chatStatus").textContent = "Writing…"; render(); }
        else if (ev === "tool") { chipsEl.insertAdjacentHTML("beforeend", `<span class="chip run" data-n="${data.name}">${esc(data.label)}</span>`); $("#chatStatus").textContent = data.label + "…"; scrollDown(); }
        else if (ev === "tool_done") { const c = chipsEl.querySelector(`.chip.run[data-n="${data.name}"]`); if (c) c.className = "chip done"; if (data.changed) changed = true; }
        else if (ev === "error") { txtEl.insertAdjacentHTML("beforeend", `<p class="err-inline">⚠ ${esc(data.message)}</p>`); }
        else if (ev === "done") { $$(".chip.run", chipsEl).forEach((c) => c.className = "chip done"); }
      }
    }
  } catch (e) {
    txtEl.insertAdjacentHTML("beforeend", `<p class="err-inline">⚠ ${esc(e.message)}</p>`);
  } finally {
    txtEl.classList.remove("cursor"); if (buf) txtEl.innerHTML = md(buf);
    live.removeAttribute("id"); STREAMING = false; $("#sendBtn").disabled = false; $("#chatStatus").textContent = "";
    if (changed) toast("Claude updated your data");
    drawChatList(); scrollDown();
  }
}
function autosize() { const t = $("#prompt"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 220) + "px"; }
$("#prompt").addEventListener("input", autosize);
$("#prompt").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
$("#composer").onsubmit = (e) => { e.preventDefault(); send(); };
$("#modelPick").onchange = async (e) => { META = await api("/chat/model", { method: "POST", body: { model: e.target.value } }); toast("Model: " + e.target.value); };


// ---------------- MONEY ----------------
const CAT_ICON = { "Salary": "💼", "Bonus": "🎯", "Interest": "🏦", "Dividends": "📈", "Rent received": "🏠", "Tax refund": "🧾", "Gift": "🎁", "Sale of asset": "🔁", "Other income": "➕",
  "Rent / Warmmiete": "🏠", "Utilities & internet": "💡", "Groceries": "🛒", "Transport": "🚆", "Insurance": "🛡️", "Childcare & school": "🎒", "Eating out": "🍽️", "Shopping": "🛍️",
  "Travel": "✈️", "Subscriptions": "🔁", "Health": "🩺", "Support to family": "🤝", "Loan / EMI": "🏦", "Property payment": "🏗️", "Taxes & fees": "🧾", "Investments / SIP": "🌱", "Other": "•" };
const MONEY = { ccy: "", period: "month", anchor: new Date().toISOString().slice(0, 10), account: "", kind: "expense", meta: null, accts: [] };
try { MONEY.ccy = localStorage.getItem("fm-ccy") || ""; } catch (e) { }
const fmtC = (v, c) => money(v, c);
const shiftAnchor = (dir) => {
  const d = new Date(MONEY.anchor);
  if (MONEY.period === "day") d.setDate(d.getDate() + dir);
  else if (MONEY.period === "week") d.setDate(d.getDate() + 7 * dir);
  else if (MONEY.period === "month") d.setMonth(d.getMonth() + dir, 1);
  else d.setFullYear(d.getFullYear() + dir);
  MONEY.anchor = d.toISOString().slice(0, 10);
};
function periodLabel(s) {
  const a = new Date(s.start), b = new Date(s.end);
  if (s.period === "day") return a.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
  if (s.period === "week") return `${a.getDate()} ${MON[a.getMonth()]} – ${b.getDate()} ${MON[b.getMonth()]}`;
  if (s.period === "month") return `${["January","February","March","April","May","June","July","August","September","October","November","December"][a.getMonth()]} ${a.getFullYear()}`;
  return String(a.getFullYear());
}
loaders.money = async () => {
  if (!MONEY.meta) MONEY.meta = await api("/money/meta");
  const q = new URLSearchParams({ period: MONEY.period, anchor: MONEY.anchor, display: MONEY.ccy }); if (MONEY.account) q.set("account", MONEY.account);
  if (!CFG.currencies.includes(MONEY.ccy)) { MONEY.ccy = BASE(); q.set("display", MONEY.ccy); }
  const [acc, sum] = await Promise.all([api("/money/accounts"), api("/money/summary?" + q)]);
  $("#ccySeg").innerHTML = CFG.currencies.map((c) => `<button data-c="${c}">${SYM[c] ? SYM[c].trim() + " " : ""}${c}</button>`).join("");
  $$("#ccySeg button").forEach((b) => b.onclick = () => { MONEY.ccy = b.dataset.c; try { localStorage.setItem("fm-ccy", MONEY.ccy); } catch (e) { } loaders.money(); });
  MONEY.accts = acc.accounts;
  $$("#ccySeg button").forEach((b) => b.classList.toggle("on", b.dataset.c === MONEY.ccy));
  $$("#perSeg button").forEach((b) => b.classList.toggle("on", b.dataset.p === MONEY.period));
  // account groups
  const grp = (code, label, flag, list) => {
    const byC = {}; list.forEach((a) => byC[a.currency] = (byC[a.currency] || 0) + a.balance);
    return `<div class="acct-group"><h4 style="color:${ccyColor(packFor(code)?.currency || list[0]?.currency)}">${flag} ${esc(label)}<span class="tot">${Object.entries(byC).map(([c, v]) => fmtC(v, c)).join(" · ") || ""}</span></h4><div class="acct-row">
      ${list.map((a) => `<div class="acct ${String(a.id) === MONEY.account ? "sel" : ""}" style="--ac:${ccyColor(a.currency)}" onclick="pickAccount(${a.id})" tabindex="0">
        <button class="edit" onclick="event.stopPropagation();editAccount(${a.id})" aria-label="Edit account">✎</button>
        <div class="ty">${esc(a.type)}${a.institution ? " · " + esc(a.institution) : ""}</div><div class="nm">${esc(a.name)}</div>
        <div class="bal ${a.balance < 0 ? "neg" : ""}">${fmtC(a.balance, a.currency)}</div>
        <div class="io">+${fmtC(a.income, a.currency)} · −${fmtC(a.expense, a.currency)}</div></div>`).join("")}
      ${code !== "_" ? `<div class="acct add" onclick="editAccount(null,'${code}')" tabindex="0">＋ Add ${esc(label)} account</div>` : ""}</div></div>`;
  };
  const known = CFG.packs.map((p) => p.code), hasOther = acc.accounts.some((a) => !known.includes(a.country));
  $("#acctGroups").innerHTML = CFG.packs.map((p) => grp(p.code, p.name, p.flag, acc.accounts.filter((a) => a.country === p.code))).join("")
    + (hasOther ? grp("_", "Other", "🌍", acc.accounts.filter((a) => !known.includes(a.country))) : "");
  $("#acctGroups").style.gridTemplateColumns = innerWidth < 760 ? "1fr" : `repeat(${Math.min(CFG.packs.length + (hasOther ? 1 : 0), 2) || 1}, 1fr)`;
  // selects
  const opts = acc.accounts.map((a) => `<option value="${a.id}">${esc(a.name)} (${a.currency})</option>`).join("");
  $("#acctFilter").innerHTML = `<option value="">All accounts</option>` + opts; $("#acctFilter").value = MONEY.account;
  const f = $("#txForm");
  const keepA = f.account_id.value, keepT = f.to_account_id.value;
  f.account_id.innerHTML = opts || `<option value="">Add an account first</option>`; f.to_account_id.innerHTML = opts;
  if (keepA) f.account_id.value = keepA; if (keepT) f.to_account_id.value = keepT;
  if (!f.date.value) f.date.value = new Date().toISOString().slice(0, 10);
  setKind(MONEY.kind, true);
  // kpis
  $("#perLabel").textContent = periodLabel(sum);
  const c = MONEY.ccy, bc = sum.by_currency;
  const split = (k) => Object.entries(bc).filter(([, v]) => v[k]).map(([cc, v]) => fmtC(v[k], cc)).join(" · ");
  $("#perKpis").innerHTML = kpi(`<span class="dot good"></span>Money in`, `<span class="pos">${fmtC(sum.income, c)}</span>`, split("income")) +
    kpi(`<span class="dot" style="background:var(--bad)"></span>Money out`, fmtC(sum.expense, c), split("expense")) +
    kpi(`<span class="dot eur"></span>Left over`, `<span class="${sum.net >= 0 ? "pos" : "neg"}">${fmtC(sum.net, c)}</span>`, sum.income ? `${pct(Math.max(sum.net, 0) / sum.income, 0)} of income saved` : "") +
    kpi(`<span class="dot inr"></span>All accounts`, conv(acc.total_base, acc.base, c) != null ? fmtC(conv(acc.total_base, acc.base, c), c) : fmtC(acc.total_base, acc.base), `converted at today's rates`);
  // charts
  $("#trendSub").textContent = `last 6 ${MONEY.period}s · ${c}`;
  chart("chTrend", { type: "bar", data: { labels: sum.trend.map((t) => t.label), datasets: [
      { label: "In", data: sum.trend.map((t) => t.income), backgroundColor: "#34d399", borderRadius: 6, maxBarThickness: 26 },
      { label: "Out", data: sum.trend.map((t) => t.expense), backgroundColor: "#fb7185", borderRadius: 6, maxBarThickness: 26 }] },
    options: { plugins: { legend: { position: "bottom", labels: { boxWidth: 10, usePointStyle: true } }, tooltip: { callbacks: { label: (x) => ` ${x.dataset.label}: ${fmtC(x.raw, c)}` } } },
      scales: { x: { grid: { display: false } }, y: { ticks: { maxTicksLimit: 5, callback: (v) => compact(v, c) } } } } });
  const cats = Object.entries(sum.by_category);
  if (cats.length) chart("chCats", doughnut(cats.map((x) => x[0]), cats.map((x) => x[1]), [fmtC(sum.expense, c), "spent"]));
  else { charts.chCats?.destroy(); delete charts.chCats; }
  // transactions
  $("#txCount").textContent = sum.transactions.length ? `${sum.transactions.length} in this ${MONEY.period}` : "";
  let day = "";
  $("#txList").innerHTML = sum.transactions.map((t) => {
    const d = new Date(t.date), head = t.date !== day ? `<div class="txday"><span>${d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}</span></div>` : ""; day = t.date;
    const sign = t.kind === "income" ? "+" : t.kind === "expense" ? "−" : "⇄ ";
    const title = t.kind === "transfer" ? `${esc(t.account)} → ${esc(t.to_account)}` : esc(t.note || t.category || (t.kind === "income" ? "Income" : "Expense"));
    const sub = t.kind === "transfer" ? `<span>Transfer</span>${t.note ? `<span>· ${esc(t.note)}</span>` : ""}` : `<span>${esc(t.category || "")}</span><span class="acctchip ${t.currency}">${esc(t.account)}</span>`;
    const cv = t.currency !== c && t.kind !== "transfer" && conv(t.amount, t.currency, c) != null ? `<small>≈ ${fmtC(conv(t.amount, t.currency, c), c)}</small>` : t.kind === "transfer" ? `<small>→ ${fmtC(t.to_amount ?? t.amount, t.to_currency)}</small>` : "";
    return head + `<div class="tx ${t.kind}"><div class="ic">${t.kind === "transfer" ? "⇄" : CAT_ICON[t.category] || "•"}</div>
      <div><div class="t1">${title}</div><div class="t2">${sub}${t.recurring_id ? `<span class="rep">↻ repeating</span>` : ""}${t.doc_id ? `<span class="rep">📎</span>` : ""}</div></div>
      <div class="amt">${sign}${fmtC(t.amount, t.currency)}${cv}</div>
      ${t.recurring_id ? `<span></span>` : `<button class="del" onclick="delTx(${t.id})" aria-label="Delete" title="Delete">✕</button>`}</div>`;
  }).join("") || `<div class="empty">${acc.accounts.length ? `Nothing logged for this ${MONEY.period} yet — add an entry on the right.` : "Start by adding your accounts above, then log income and spending."}</div>`;
  drawRecurring(acc.recurring || []);
};
function drawRecurring(list) {
  const accts = Object.fromEntries(MONEY.accts.map((a) => [a.id, a]));
  $("#recList").innerHTML = list.map((r) => {
    const a = accts[r.account_id] || {}, fq = r.frequency[0].toUpperCase() + r.frequency.slice(1);
    return `<div class="recitem ${r.active ? "" : "paused"}"><div><div class="t1">${CAT_ICON[r.category] || (r.kind === "transfer" ? "⇄" : "•")} ${esc(r.note || r.category || r.kind)}</div>
      <div class="t2">${fq} · ${esc(a.name || "?")}${r.next ? ` · next ${new Date(r.next).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}` : ""}${r.end_date ? ` · until ${r.end_date}` : ""}</div></div>
      <div class="amt ${r.kind === "income" ? "pos" : ""}">${r.kind === "income" ? "+" : r.kind === "expense" ? "−" : "⇄"}${fmtC(r.amount, a.currency)}</div>
      <div class="acts"><button class="sm ghost" onclick="toggleRec(${r.id})">${r.active ? "Pause" : "Resume"}</button><button class="sm ghost" onclick="delRec(${r.id})">Stop &amp; remove</button></div></div>`;
  }).join("") || `<p class="hint" style="margin:0">Salary, rent, SIPs, insurance… set "Repeats" when adding an entry and it's logged for you each time.</p>`;
}
window.pickAccount = (id) => { MONEY.account = String(MONEY.account) === String(id) ? "" : String(id); loaders.money(); };
window.delTx = async (id) => { await api("/api/transactions/" + id, { method: "DELETE" }); toast("Entry deleted"); loaders.money(); };
window.toggleRec = async (id) => { const r = (await api("/api/recurring")).find((x) => x.id === id); r.active = r.active ? 0 : 1; await api("/api/recurring", { method: "POST", body: r }); toast(r.active ? "Resumed" : "Paused"); loaders.money(); };
window.delRec = async (id) => { await api("/api/recurring/" + id, { method: "DELETE" }); toast("Repeating entry removed — past entries are kept"); loaders.money(); };
window.editAccount = (id, country) => {
  const pk = packFor(country) || CFG.packs[0] || {};
  const row = MONEY.accts.find((a) => a.id === id) || { country: pk.code || "", currency: pk.currency || BASE(), type: MONEY.meta.account_types[0], opening_balance: 0, opening_date: new Date().toISOString().slice(0, 10), liquid: 1, in_networth: 1 };
  dialog(id ? "Edit account" : `Add ${pk.flag || ""} ${esc(pk.name || "")} account`, [["name", "Account name (e.g. Main current account)"], ["institution", "Bank / broker"],
    ["country", "Country", "select", ["", ...(CFG.countries || [])]], ["currency", "Currency", "select", CFG.currencies], ["type", "Type", "select", MONEY.meta.account_types],
    ["opening_balance", "Balance on the start date", "number"], ["opening_date", "Start date", "date"],
    ["liquid", "Cash I can reach within a week", "checkbox"], ["in_networth", "Count in net worth", "checkbox"], ["archived", "Hide (closed account)", "checkbox"], ["note", "Note", "textarea"],
    ...customFields("accounts").filter(([, , , , x]) => fieldForCountry(x, row.country || country))], row,
    async (r) => { if (!r.name) throw new Error("Give the account a name"); await api("/api/accounts", { method: "POST", body: r }); loaders.money(); },
    async (i) => { await api("/api/accounts/" + i, { method: "DELETE" }); loaders.money(); });
};
function setKind(k, silent) {
  MONEY.kind = k;
  $$("#kindSeg button").forEach((b) => b.classList.toggle("on", b.dataset.k === k));
  const f = $("#txForm"), q = $(".quick");
  q.classList.toggle("transfer", k === "transfer");
  $("#acctLbl").textContent = k === "income" ? "Into account" : "From account";
  const cats = k === "income" ? MONEY.meta.income_categories : MONEY.meta.expense_categories;
  const keep = f.category.value;
  f.category.innerHTML = cats.map((x) => `<option>${x}</option>`).join("");
  if (cats.includes(keep)) f.category.value = keep;
  $("#txSubmit").textContent = { expense: "Add expense", income: "Add income", transfer: "Add transfer" }[k] + (f.frequency.value ? " (repeating)" : "");
  syncCcy();
}
function syncCcy() {
  const f = $("#txForm"), a = MONEY.accts.find((x) => String(x.id) === f.account_id.value);
  $("#amtCcy").textContent = a ? a.currency : "";
}
$$("#kindSeg button").forEach((b) => b.onclick = () => setKind(b.dataset.k));
$("#txForm").account_id.onchange = syncCcy;
$("#txForm").frequency.onchange = (e) => { $(".quick").classList.toggle("repeat", !!e.target.value); setKind(MONEY.kind); };
$$("#perSeg button").forEach((b) => b.onclick = () => { MONEY.period = b.dataset.p; loaders.money(); });
$("#perPrev").onclick = () => { shiftAnchor(-1); loaders.money(); };
$("#perNext").onclick = () => { shiftAnchor(1); loaders.money(); };
$("#acctFilter").onchange = (e) => { MONEY.account = e.target.value; loaders.money(); };
$("#txForm").onsubmit = async (e) => {
  e.preventDefault(); $("#txErr").textContent = "";
  const f = e.target, b = formData(f);
  const row = { kind: MONEY.kind, account_id: +b.account_id, amount: +b.amount, category: MONEY.kind === "transfer" ? null : b.category, note: b.note || null,
    to_account_id: MONEY.kind === "transfer" ? +b.to_account_id : null, to_amount: MONEY.kind === "transfer" && b.to_amount ? +b.to_amount : null };
  try {
    if (b.frequency) await api("/api/recurring", { method: "POST", body: { ...row, frequency: b.frequency, start_date: b.date, end_date: b.end_date || null, active: 1 } });
    else await api("/api/transactions", { method: "POST", body: { ...row, date: b.date, doc_id: f.dataset.doc ? +f.dataset.doc : null } });
    toast(b.frequency ? `Repeating ${MONEY.kind} set up` : `${MONEY.kind[0].toUpperCase() + MONEY.kind.slice(1)} added`);
    f.amount.value = ""; f.note.value = ""; f.to_amount.value = ""; f.frequency.value = ""; f.end_date.value = ""; delete f.dataset.doc;
    $(".quick").classList.remove("repeat"); setKind(MONEY.kind); loaders.money();
  } catch (err) { $("#txErr").textContent = err.message; }
};
window.prefillTx = async ({ amount, date, note, category, currency, doc }) => {
  go("money");
  await new Promise((r) => setTimeout(r, 450));
  setKind("expense");
  const f = $("#txForm");
  const acct = MONEY.accts.find((a) => a.currency === currency);
  if (acct) { f.account_id.value = acct.id; syncCcy(); }
  if (amount) f.amount.value = amount; if (date) f.date.value = date; if (note) f.note.value = note;
  if (category) f.category.value = category;
  if (doc) f.dataset.doc = doc;
  f.amount.focus(); toast("Check the details and press Add");
};

// ---------------- DOCUMENTS ----------------
const DOCS = { meta: null, lib: [], cat: "", q: "" };
const CAT_COLOR = { "Salary & payslips": "#34d399", "Tax": "#38bdf8", "Tax — Germany": "#38bdf8", "Tax — India": "#a99bff", "Property": "#5b4bd6", "Bank statements": "#fbbf24",
  "Investments": "#2dd4bf", "Insurance": "#f472b6", "Receipts & bills": "#fb923c", "Social security & pension": "#94a3b8", "Employment": "#c4b5fd", "Career": "#e879f9", "Other": "#64748b" };
loaders.documents = async () => {
  DOCS.meta = await api("/docs/meta");
  $("#rootChip").textContent = "📁 " + DOCS.meta.root; $("#rootChip").title = DOCS.meta.root;
  DOCS.lib = await api("/docs/library");
  drawLibrary();
};
function drawLibrary() {
  const counts = {}; DOCS.lib.forEach((d) => counts[d.category] = (counts[d.category] || 0) + 1);
  $("#libCats").innerHTML = [["", `All (${DOCS.lib.length})`], ...Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, n]) => [k, `${k} (${n})`])]
    .map(([k, l]) => `<button class="${DOCS.cat === k ? "on" : ""}" data-k="${esc(k)}">${k ? `<span class="catdot" style="background:${CAT_COLOR[k] || "#64748b"}"></span>` : ""}${esc(l)}</button>`).join("");
  $$("#libCats button").forEach((b) => b.onclick = () => { DOCS.cat = b.dataset.k; drawLibrary(); });
  const q = DOCS.q.toLowerCase();
  const rows = DOCS.lib.filter((d) => (!DOCS.cat || d.category === DOCS.cat) && (!q || d.path.toLowerCase().includes(q)));
  $("#libCount").textContent = `${rows.length} file${rows.length === 1 ? "" : "s"}`;
  $("#libTbl").innerHTML = `<thead><tr><th>File</th><th>Category</th><th>Folder</th><th class="n">Size</th></tr></thead><tbody>` + rows.slice(0, 300).map((d) => `<tr>
    <td><a href="${withToken("/docs/open?path=" + encodeURIComponent(d.path))}" target="_blank" rel="noopener" style="color:var(--ink)">${esc(d.name)}</a>${d.logged ? ` <span class="rep">filed here</span>` : ""}</td>
    <td data-l="Category"><span class="catdot" style="background:${CAT_COLOR[d.category] || "#64748b"}"></span>${esc(d.category)}</td>
    <td data-l="Folder" class="muted" style="font-size:12.5px">${esc(d.folder)}</td><td class="n" data-l="Size">${(d.size / 1024).toFixed(0)} KB</td></tr>`).join("") + "</tbody>";
}
$("#libSearch").oninput = (e) => { DOCS.q = e.target.value; drawLibrary(); };
const drop = $("#drop");
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => handleFiles([...e.dataTransfer.files]));
$("#fileIn").onchange = (e) => { const list = [...e.target.files]; e.target.value = ""; handleFiles(list); };
function readAsDataURL(file) { return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(file); }); }
async function handleFiles(files) {
  if (!DOCS.meta) DOCS.meta = await api("/docs/meta");
  for (const file of files) {
    const id = "q" + Math.random().toString(36).slice(2, 8);
    $("#queue").insertAdjacentHTML("afterbegin", `<div class="qcard" id="${id}"><div class="fileic">${esc((file.name.split(".").pop() || "").toUpperCase())}</div>
      <div><div class="qhead"><span class="nm">Reading ${esc(file.name)}…</span></div><div class="hint">Extracting text and working out what it is.</div></div></div>`);
    try {
      const a = await api("/docs/analyze", { method: "POST", body: { filename: file.name, data: await readAsDataURL(file) } });
      drawQueueCard(id, a);
    } catch (err) { $("#" + id).innerHTML = `<div class="fileic">!</div><div><div class="qhead"><span class="nm">${esc(file.name)}</span></div><p class="err">${esc(err.message)}</p></div>`; }
  }
}
function drawQueueCard(id, a) {
  const el = $("#" + id), c = a.confidence, col = c >= .85 ? "var(--good)" : c >= .6 ? "var(--gold)" : "var(--bad)";
  const F = a.fields || {}, chips = [];
  if (F.dates?.length) chips.push(["date", F.dates[0]]);
  if (F.amount) chips.push(["amount", money(F.amount, F.currency || BASE(), 2)]);
  ["invoice_no", "ack_no", "cin", "bank_ref", "period", "tax_year", "assessment_year", "certificate_no"].forEach((k) => F[k] && chips.push([k.replace("_", " "), F[k]]));
  const folders = DOCS.meta.folders.includes(a.folder) ? DOCS.meta.folders : [a.folder, ...DOCS.meta.folders];
  el.innerHTML = `<div class="fileic">${esc((a.filename.split(".").pop() || "").toUpperCase())}</div><div>
    <div class="qhead"><span class="nm">${esc(a.label)}</span>${a.country ? countryTag(a.country) : ""}${a.rule_source ? `<span class="srcbadge">${esc(a.rule_source)}</span>` : ""}
      <span class="conf"><i><b style="width:${c * 100}%;background:${col}"></b></i>${Math.round(c * 100)}% sure · ${esc(a.matched_on)}</span></div>
    <div class="qhead"><span class="orig">${esc(a.method)} · ${(a.size / 1024).toFixed(0)} KB</span></div>
    ${chips.length ? `<div class="fchips">${chips.map(([k, v]) => `<span class="fchip"><b>${esc(k)}</b>${esc(v)}</span>`).join("")}</div>` : ""}
    ${a.duplicate_of ? `<div class="warnline dup">This exact file is already filed at <b>${esc(a.duplicate_of)}</b>.</div>` : ""}
    ${!a.has_text ? `<div class="warnline">No readable text (scan or photo) — I went by the file name${a.confidence ? "" : " and couldn't tell"}. Check the category and folder.</div>` : ""}
    <div class="qform">
      <label>Category <select data-f="category">${DOCS.meta.categories.map((x) => `<option ${x === a.category ? "selected" : ""}>${x}</option>`).join("")}</select></label>
      <label>Folder <input data-f="folder" list="fl-${id}" value="${esc(a.folder)}"><datalist id="fl-${id}">${folders.map((x) => `<option value="${esc(x)}">`).join("")}</datalist></label>
      <label>File name <input data-f="filename" value="${esc(a.filename)}"></label></div>
    ${a.excerpt ? `<details><summary class="hint">What I read</summary><div class="excerpt">${esc(a.excerpt)}</div></details>` : ""}
    <div class="qacts"><button class="sm" data-act="file">File it</button>
      ${F.amount ? `<button class="sm ghost" data-act="filetx">File + log as expense</button>` : ""}
      <button class="sm ghost" data-act="skip">Discard</button><span class="okline"></span></div></div>`;
  const get = (k) => $(`[data-f="${k}"]`, el).value.trim();
  const doFile = async () => {
    const r = await api("/docs/file", { method: "POST", body: { ...a, original_name: a.filename, category: get("category"), folder: get("folder"), filename: get("filename") } });
    el.classList.add("done"); $(".okline", el).textContent = `✓ Saved to ${r.path}`;
    toast("Filed"); DOCS.lib = await api("/docs/library"); drawLibrary(); return r;
  };
  $$("[data-act]", el).forEach((b) => b.onclick = async () => {
    try {
      if (b.dataset.act === "skip") { el.remove(); return; }
      const r = await doFile();
      if (b.dataset.act === "filetx") prefillTx({ amount: F.amount, date: F.dates?.[0], currency: F.currency || packFor(a.country)?.currency || BASE(),
        note: a.label + " — " + get("filename"), category: a.category.startsWith("Property") ? "Property payment" : a.category.startsWith("Tax") ? "Taxes & fees" : "Other", doc: r.id });
    } catch (err) { $(".okline", el).innerHTML = `<span class="err">${esc(err.message)}</span>`; }
  });
}
$("#reviewBtn").onclick = async () => {
  $("#reviewOut").innerHTML = `<p class="hint">Reading every document… this can take a few seconds.</p>`;
  try {
    const r = await api("/docs/review");
    $("#reviewOut").innerHTML = `<p class="hint">Checked ${r.checked} files.</p>` + (r.suggestions.map((s, i) => `<div class="revitem"><b>${esc(s.label)}</b>
      <span class="from">now: ${esc(s.path)}</span><span class="to">suggested: ${esc(s.suggested_folder)}/${esc(s.suggested_name)}</span><span class="hint">rule: ${esc(s.rule_source || "")}</span>
      <div><button class="sm" data-i="${i}">Move it</button></div></div>`).join("") || `<div class="okline">✓ Everything looks like it's in the right place.</div>`);
    $$("#reviewOut button[data-i]").forEach((b) => b.onclick = async () => {
      const s = r.suggestions[+b.dataset.i];
      try { const m = await api("/docs/move", { method: "POST", body: { path: s.path, folder: s.suggested_folder, filename: s.suggested_name } });
        b.parentElement.innerHTML = `<span class="okline">✓ Moved to ${esc(m.path)}</span>`; DOCS.lib = await api("/docs/library"); drawLibrary(); }
      catch (err) { toast(err.message); }
    });
  } catch (err) { $("#reviewOut").innerHTML = `<p class="err">${esc(err.message)}</p>`; }
};

// re-draw when crossing a layout breakpoint so charts and legends re-flow
let lastBp = innerWidth < 760 ? "m" : innerWidth < 1024 ? "t" : "d";
addEventListener("resize", () => {
  const bp = innerWidth < 760 ? "m" : innerWidth < 1024 ? "t" : "d";
  if (bp !== lastBp) { lastBp = bp; const a = $(".tab.on")?.id; if (a && a !== "chat") loaders[a]?.(); }
});

// ---------------- boot ----------------
(async () => {
  const st = await api("/setup/status").catch(() => ({ configured: false }));
  if (!st.configured) { openWizard(); return; }
  await loadConfig();
  const start = location.hash.slice(1) || "home";
  ($(`#tabs button[data-tab="${start}"]`) || $("#tabs button")).click();
  setTimeout(checkUpdate, 1500);
})();

// ---------------- update notice ----------------
// The app checks the project's public latest.json at most once a day (Settings → Your data can switch it off).
// It never installs anything by itself.
async function checkUpdate(force) {
  let u; try { u = await api("/update/check" + (force ? "?force=true" : "")); } catch (e) { return null; }
  let dismissed = ""; try { dismissed = localStorage.getItem("afUpdateDismissed") || ""; } catch (e) { }
  const el = $("#updateNote");
  if (u.newer && (force || dismissed !== u.latest.version)) {
    el.innerHTML = `<span><b>Version ${esc(u.latest.version)} is available</b> — you have ${esc(u.current)}.</span>
      ${u.latest.notes_url ? `<a href="${esc(u.latest.notes_url)}" target="_blank" rel="noopener">What's new</a>` : ""}
      <button class="sm" type="button" id="updHow">How to update</button><button class="sm ghost" type="button" id="updLater">Later</button>`;
    el.hidden = false;
    $("#updLater").onclick = () => { try { localStorage.setItem("afUpdateDismissed", u.latest.version); } catch (e) { } el.hidden = true; };
    $("#updHow").onclick = () => {
      el.innerHTML = `<span><b>Update to ${esc(u.latest.version)}</b> — your data is backed up automatically when the new version first starts.</span>
        <span>Installed with pipx: <code>${esc(u.latest.install || "pipx upgrade aaryaai-finance")}</code></span>
        ${u.latest.download_url ? `<span>Using start.bat: <a href="${esc(u.latest.download_url)}" target="_blank" rel="noopener">download the new version</a> and unzip it over the old folder.</span>` : ""}
        <button class="sm ghost" type="button" id="updClose">Close</button>`;
      $("#updClose").onclick = () => { el.hidden = true; };
    };
  } else el.hidden = true;
  return u;
}
