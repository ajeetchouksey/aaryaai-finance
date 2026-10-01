/* aaryaai finance — planning screens: Home, Cash forecast, Goal odds, Diversify, Opportunities, Tax return, Routines.
   Loaded after app.js and uses its helpers (api, money, compact, esc, dialog, loaders, go, toast, CFG…). */
"use strict";

// ---------------------------------------------------------------- small building blocks
const TONE = { known: "good", planned: "lilac", estimated: "muted", learned: "eur", plan: "warn" };
const chip = (t, tone = "lilac") => `<span class="chip ${tone}">${t}</span>`;
const confChip = (c) => chip(esc(c === "plan" ? "funding plan" : c), TONE[c] || "muted");
const monthLabel = (m, long) => { const [y, mo] = m.split("-").map(Number); return MON[mo - 1] + (long ? " " + y : ""); };
const dayLabel = (d) => new Date(d + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" });
const probTone = (p) => p >= 0.8 ? "good" : p >= 0.6 ? "warn" : "bad";
const probColor = (p) => css(p >= 0.8 ? "--good" : p >= 0.6 ? "--gold" : "--bad");
const pctText = (p) => Math.round(p * 100) + "%";
const hdr = (title, sub = "", right = "") => `<h3>${title}${sub ? ` <span class="sub">${sub}</span>` : ""}${right ? `<span class="right">${right}</span>` : ""}</h3>`;
const emptyBox = (t, btn = "") => `<div class="empty">${t}${btn ? "<br>" + btn : ""}</div>`;
const rowItem = (main, sub, right = "", right2 = "") => `<div class="li"><div class="li-l"><div class="li-t">${main}</div>${sub ? `<div class="li-s">${sub}</div>` : ""}</div>
  <div class="li-r">${right ? `<div>${right}</div>` : ""}${right2 ? `<div>${right2}</div>` : ""}</div></div>`;
const bar = (pct, color, h = 8) => `<div class="pbar" style="height:${h}px"><i style="width:${Math.max(0, Math.min(100, pct))}%;background:${color}"></i></div>`;
function hstack(parts, h = 16) {
  return `<div class="hstack" style="height:${h}px">${parts.filter((p) => p.pct > 0.2).map((p) => `<i style="width:${p.pct}%;background:${p.color}" title="${esc(p.label)} ${p.pct.toFixed(0)}%"></i>`).join("")}</div>`;
}
const legendRow = (items) => `<div class="legend">${items.map(([t, c]) => `<span><i style="background:${c}"></i>${t}</span>`).join("")}</div>`;
const PALETTE = ["#5b4bd6", "#38bdf8", "#a99bff", "#34d399", "#fbbf24", "#f472b6", "#fb923c", "#2dd4bf", "#94a3b8"];

// Vertical bars that can go below zero, with an optional floor line. rows: [{label, v, color, note}]
function vbars(rows, { h = 170, floor = null, floorLabel = "", fmt = (v) => v } = {}) {
  const vals = rows.map((r) => r.v).concat(floor != null ? [floor] : []);
  let max = Math.max(0, ...vals), min = Math.min(0, ...vals);
  if (max === min) max = min + 1;
  const pad = (max - min) * 0.12, top = max + pad, bot = min < 0 ? min - pad : 0, span = top - bot;
  const y = (v) => (top - v) / span * h, zero = y(0);
  const cols = rows.map((r) => {
    const yy = y(r.v), t = Math.min(yy, zero), ht = Math.max(Math.abs(yy - zero), 2);
    const note = r.note ? `<div class="vb-note" style="top:${r.v >= 0 ? t - 18 : t + ht + 3}px;color:${r.color}">${r.note}</div>` : "";
    return `<div class="vb-col"><div class="vb-area" style="height:${h}px"><div class="vb-bar ${r.v < 0 ? "neg" : ""}" style="top:${t}px;height:${ht}px;background:${r.color}" title="${esc(r.label)}: ${esc(fmt(r.v))}"></div>${note}</div>
      <div class="vb-lab">${esc(r.label)}</div></div>`;
  }).join("");
  const fl = floor != null ? `<div class="vb-floor" style="top:${y(floor)}px"></div><div class="vb-floorlab" style="top:${y(floor) - 17}px">${floorLabel}</div>` : "";
  return `<div class="vbars"><div class="vb-zero" style="top:${zero}px"></div>${fl}${cols}</div>`;
}

async function decideProposal(id, decision, after) {
  try {
    const r = await api(`/proposals/${id}`, { method: "POST", body: { decision } });
    toast(decision === "approve" ? "Done — " + (r.result || "approved") : "Skipped");
  } catch (e) { toast(e.message); }
  refreshNavCount();
  after?.();
}
window.decideProposal = decideProposal;
async function refreshNavCount() {
  try {
    const r = await api("/routines");
    const n = r.proposals.filter((p) => p.status === "pending").length;
    const b = $("#navProposals"); if (b) { b.hidden = !n; b.textContent = n; }
  } catch (e) { }
}

function proposalRow(p, after) {
  const pending = p.status === "pending";
  return `<div class="prop ${pending ? "" : "decided"}"><div class="prop-t"><b>${esc(hideAmt(p.title))}</b>
      <div class="li-s">${esc(hideAmt(p.detail || ""))}</div>
      <div class="li-s">${chip(esc(p.source || ""), "muted")} ${p.effect ? chip(esc(hideAmt(p.effect)), "good") : ""} ${pending ? "" : chip(p.status, p.status === "approved" ? "good" : "muted")}</div></div>
    ${pending ? `<div class="prop-a"><button class="sm" onclick="decideProposal(${p.id},'approve',${after})">Approve</button><button class="sm ghost" onclick="decideProposal(${p.id},'skip',${after})">Skip</button></div>` : ""}</div>`;
}

// ---------------------------------------------------------------- HOME
loaders.home = async () => {
  const d = await api("/home");
  const base = d.base, n = d.net_worth;
  $("#homeDate").textContent = new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  $("#homeHello").textContent = `${greeting()}${d.name ? ", " + d.name : ""}`;
  const rateChips = CFG.currencies.filter((c) => c !== base && d.rates[c]).slice(0, 2).map((c) => chip(`1 ${esc(base)} = ${moneyRaw(d.rates[c], c, 2)}`, "eur")).join("");
  $("#homeChips").innerHTML = chip("Base " + esc(base), "muted") + rateChips;

  // attention banner
  const a = d.attention[0];
  if (a && !a.watch) {
    const b = a.because;
    $("#homeAttention").innerHTML = `<div class="banner warn"><svg><use href="#i-wave"/></svg><div>
      ${b ? `<b>${esc(b.label)}</b> on ${dayLabel(b.date)} needs ${money(b.amount, a.ccy, 0)}. ` : ""}Your ${esc(a.ccy)} accounts would drop to <b>${money(a.low, a.ccy, 0)}</b> in ${monthLabel(a.month, true)} (your floor is ${money(a.floor, a.ccy, 0)}).
      Plan a transfer of about <b>${money(a.send, a.from_ccy, 0)}</b> around ${dayLabel(a.date)}.</div>
      <button class="sm" onclick="go('forecast')">See the plan</button></div>`;
  } else if (a && a.watch) {
    $("#homeAttention").innerHTML = `<div class="banner bad"><svg><use href="#i-wave"/></svg><div>Your ${esc(a.ccy)} accounts dip to <b>${money(a.low, a.ccy, 0)}</b> in ${monthLabel(a.month, true)}, below your floor of ${money(a.floor, a.ccy, 0)}, and no other currency has room to cover it.</div>
      <button class="sm" onclick="go('forecast')">See options</button></div>`;
  } else $("#homeAttention").innerHTML = "";

  const cush = d.cushion_months;
  $("#homeKpis").innerHTML =
    kpi("Net worth", money(n.net_worth, base, 0), d.change_month == null ? "first month of history" : `<span class="${d.change_month >= 0 ? "pos" : "neg"}">${d.change_month >= 0 ? "+" : "−"}${money(Math.abs(d.change_month), base, 0)}</span> this month`) +
    kpi("Cash cushion", cush == null ? "—" : `<span class="txt">${cush} months</span>`, cush == null ? "log spending in Money or a budget" : `target ${d.cushion_target} months`, meter((cush || 0) / (d.cushion_target || 6), cush >= d.cushion_target ? css("--good") : css("--gold"))) +
    kpi("Next 90 days", money(d.next90.in, base, 0) + " in", `${money(d.next90.out, base, 0)} out · net <span class="${d.next90.net >= 0 ? "pos" : "neg"}">${money(d.next90.net, base, 0)}</span>`) +
    kpi("Deadlines", `<span class="txt">${d.deadlines30} in 30 days</span>`, d.next_deadline ? "Next: " + esc(hideAmt(d.next_deadline.title)).slice(0, 60) : "nothing with a date");

  // net worth by currency
  const byc = n.by_currency, tot = Object.values(byc).reduce((s, v) => s + v, 0) || 1;
  const ccys = Object.keys(byc).sort((x, y) => byc[y] - byc[x]);
  const hist = d.history.slice(-12);
  const hmax = Math.max(...hist.map((h) => h.net_worth), 1);
  $("#homeCcy").innerHTML = hdr("Net worth by currency", "assets, before debts") +
    hstack(ccys.map((c) => ({ pct: byc[c] / tot * 100, color: ccyColor(c), label: c }))) +
    `<div class="ccycols">${ccys.slice(0, 3).map((c) => { const nat = conv(byc[c], base, c); return `<div><div class="lbl" style="color:${ccyColor(c)}">${esc(c)}</div>
      <div class="big num">${money(nat ?? byc[c], nat == null ? base : c, 0)}</div><div class="li-s">${pctText(byc[c] / tot)}${c !== base ? " · ≈ " + money(byc[c], base, 0) : ""}</div></div>`; }).join("")}</div>` +
    (hist.length > 1 ? `<div class="lbl" style="margin-top:14px">Last ${hist.length} snapshots</div><div class="spark">${hist.map((h, i) => `<i style="height:${Math.max(4, h.net_worth / hmax * 100)}%;background:${i === hist.length - 1 ? css("--lilac") : "rgba(169,155,255,.45)"}" title="${esc(h.day)}: ${esc(money(h.net_worth, base, 0))}"></i>`).join("")}</div>` : "");

  $("#homeComing").innerHTML = hdr("Coming up", "next 45 days", `<button class="sm ghost" onclick="go('forecast')">Forecast</button>`) +
    (d.coming.slice(0, 7).map((c) => c.kind === "deadline"
      ? rowItem(esc(hideAmt(c.label)), dayLabel(c.date) + (c.country ? " · " + esc(countryName(c.country)) : ""), "", chip("Deadline", c.severity === "high" || c.severity === "critical" ? "warn" : "muted"))
      : rowItem(esc(c.label), dayLabel(c.date), `<span class="num ${c.amount < 0 ? "" : "pos"}">${c.amount < 0 ? "−" : "+"}${money(Math.abs(c.amount), c.ccy, 0)}</span>`, confChip(c.confidence))).join("") ||
      emptyBox("Nothing in the next 45 days. Add repeating entries in Money or planned items in the forecast."));

  $("#homeGoals").innerHTML = hdr("Goals", "chance of reaching each one", `<button class="sm ghost" onclick="go('goals')">Goals</button>`) +
    (d.goals.map((g) => `<div class="goalrow"><div class="gr-top"><span>${esc(g.name)}</span><span class="num" style="color:${probColor(g.probability)}">${pctText(g.probability)} likely</span></div>
      ${bar(g.probability * 100, probColor(g.probability))}<div class="li-s">${money(g.saved, g.currency, 0)} saved · ${money(g.monthly, g.currency, 0)}/month${g.monthly_for_85 ? ` · ${money(g.monthly_for_85, g.currency, 0)} would make it 85%` : ""}</div></div>`).join("") ||
      emptyBox("No goals yet.", `<button class="sm" onclick="go('goals');setTimeout(()=>editGoal(),300)">＋ Add a goal</button>`));

  const inbox = d.proposals.map((p) => proposalRow(p, "loaders.home")).join("");
  const opp = d.opportunities;
  $("#homeInbox").innerHTML = hdr("Routine inbox", d.proposals.length ? `${d.proposals.length} waiting for you` : "", `<button class="sm ghost" onclick="go('routines')">Routines</button>`) +
    inbox +
    (opp.count ? rowItem(`${opp.count} tax opportunit${opp.count > 1 ? "ies" : "y"}`, esc(opp.top.map((c) => c.title.replace(/^.*?·\s*/, "")).join(" · ")),
      opp.total_base ? `<span class="num pos">≈ ${money(opp.total_base, base, 0)}</span>` : "", `<button class="sm ghost" onclick="go('opportunities')">Open</button>`) : "") +
    d.routines.map((r) => rowItem(esc(r.label), esc(hideAmt(r.summary?.text || "")).slice(0, 140), "", chip(r.last_status === "ok" ? "ran " + dayLabel(r.last_run.slice(0, 10)) : "problem", r.last_status === "ok" ? "muted" : "bad"))).join("") ||
    emptyBox("Routines run on their own while the app is open.");

  const t = d.trackers[0];
  if (t && !t.error) {
    const cur = t.stages.findIndex((s) => !s.paid);
    $("#homeTracker").innerHTML = `<div class="card" style="margin-top:16px">${hdr(esc(t.name), `${t.stages.length} stages · ${esc(t.subtitle || "")}`, `<button class="sm ghost" onclick="go('position')">Details</button>`)}
      <div class="stagestrip" style="grid-template-columns:repeat(${t.stages.length},minmax(0,1fr))">${t.stages.map((s, i) => `<i class="${s.paid ? "paid" : i === cur ? "next" : ""}" title="${esc(s.name || "")}${s.paid ? " · paid " + esc(s.paid) : ""}">${i + 1}</i>`).join("")}</div>
      <div class="kvrow"><div><div class="lbl">Paid</div><div class="num big2">${compact(t.paid, t.currency)}</div></div><div><div class="lbl">Still to pay</div><div class="num big2">${compact(t.remaining_with_tax, t.currency)}</div></div>
      <div><div class="lbl">Next stage</div><div>${esc(t.stages[cur]?.name || "—")}${t.stages[cur]?.due ? " · due " + esc(String(t.stages[cur].due)) : ""}</div></div>${t.possession_date ? `<div><div class="lbl">Possession</div><div>${esc(t.possession_date)}</div></div>` : ""}</div></div>`;
  } else $("#homeTracker").innerHTML = "";
  refreshNavCount();
};

// ---------------------------------------------------------------- CASH FORECAST
const FC = { scenario: "base", data: null };
loaders.forecast = async () => {
  const f = await api("/forecast?scenario=" + FC.scenario);
  FC.data = f;
  $("#fcScenarios").innerHTML = Object.entries(f.scenarios).map(([k, v]) => `<button class="pillbtn ${k === f.scenario ? "on" : ""}" onclick="FC.scenario='${k}';loaders.forecast()">${esc(v)}</button>`).join("") +
    `<span class="li-s" style="margin-left:auto">12 months from today · rebuilt by the Forecast refresh routine every morning</span>`;
  const ccys = Object.keys(f.series).sort((a, b) => (a === f.base ? -1 : b === f.base ? 1 : a.localeCompare(b)));
  $("#fcCharts").innerHTML = ccys.map((c) => {
    const rows = f.series[c], fl = f.floors[c] || 0, lo = f.lowest[c];
    const scale = Math.max(...rows.map((r) => Math.abs(r.end)), fl) >= 1e5 && c === "INR" ? 1e5 : 1000;
    const unit = scale === 1e5 ? "lakh" : "thousand";
    const col = ccyColor(c);
    const data = rows.map((r) => ({ label: monthLabel(r.month), v: r.end, color: r.low < fl - 0.5 ? css("--bad") : col,
      note: r.month === lo.month ? (HIDE ? "•••" : (r.low / scale).toFixed(scale === 1e5 ? 2 : 1)) : "" }));
    const without = lo.without_plan < lo.low - 1 ? `<div class="li-s">Without the funding plan, the lowest point would be <b class="neg">${money(lo.without_plan, c, 0)}</b>.</div>` : "";
    return `<div class="card">${hdr(`${esc(c)} · month-end balance`, `in ${unit} ${esc(c)}`, chip(`Lowest ${money(lo.low, c, 0)} in ${monthLabel(lo.month)}`, lo.below_floor ? "bad" : "muted"))}
      ${vbars(data.map((x) => ({ ...x, v: x.v / scale })), { floor: fl / scale, floorLabel: `floor ${HIDE ? "•••" : money(fl, c, 0)}`, fmt: (v) => money(v * scale, c, 0) })}
      ${legendRow([["Above floor", col], ["Below floor", css("--bad")], ["Floor", css("--gold")]])}${without}</div>`;
  }).join("") || emptyBox("Add accounts in Money and mark them “available within a week” to see a forecast.");

  $("#fcPlan").innerHTML = hdr("Funding plan", "transfers that keep every currency above its floor") +
    (f.plan.map((s) => {
      const tds = s.because.filter((b) => b.tds);
      return `<div class="fstep"><div class="fstep-h"><b>${monthLabel(s.month, true)} · ${esc(s.because.map((b) => b.label).join(", ") || s.ccy + " dips below its floor")}</b>${s.partial ? chip("only partly covered", "bad") : ""}</div>
        <table class="mini"><tbody>
        ${s.because.map((b) => `<tr><td>${esc(b.label)} <span class="li-s">${dayLabel(b.date)} · ${esc(b.tax_note || "")}</span></td><td class="n">${money(b.amount, s.ccy, 0)}</td></tr>`).join("")}
        <tr><td>${esc(s.ccy)} balance at its lowest without a transfer</td><td class="n ${s.low_before < 0 ? "neg" : ""}">${money(s.low_before, s.ccy, 0)}</td></tr>
        <tr><td>Your floor</td><td class="n">${money(s.floor, s.ccy, 0)}</td></tr>
        <tr class="hl"><td>Transfer ${esc(s.from_ccy)} → ${esc(s.ccy)} around ${dayLabel(s.date)}</td><td class="n"><b>${money(s.send, s.from_ccy, 0)}</b><div class="li-s">→ ${money(s.receive, s.ccy, 0)} ${esc(s.rate_note)}</div></td></tr>
        ${tds.map((b) => `<tr><td>TDS to deposit within 30 days of the month-end after paying</td><td class="n">${money(b.tds, s.ccy, 0)}</td></tr>`).join("")}
        </tbody></table><div class="acts"><button class="sm" onclick="addPlanTransfer(${esc(JSON.stringify({ date: s.date, from: s.from_ccy, to: s.ccy, send: s.send, receive: s.receive, month: s.month }))})">Add as a planned transfer</button></div></div>`;
    }).join("") || emptyBox("No transfers needed: every currency stays above its floor for the next 12 months."));

  const w = f.watch;
  $("#fcWatch").innerHTML = hdr("Watch this", w.length ? "" : "nothing below a floor") +
    (w.length ? w.map((x) => `<p>${esc(x.ccy)} dips to <b class="neg">${money(x.low, x.ccy, 0)}</b> in ${monthLabel(x.month, true)}, below your floor of ${money(f.floors[x.ccy], x.ccy, 0)}.</p>`).join("") +
      `<div class="lbl" style="margin:10px 0 4px">Options the forecast tested</div>` +
      (f.options.map((o) => rowItem(esc(o.text), esc(o.detail), `<span class="num">${money(o.low_after, o.ccy, 0)}</span>`, chip(o.fixes ? "fixes it" : "helps", o.fixes ? "good" : "warn"))).join("") || `<p class="li-s">No flexible item to move that month. Lower the floor, add income, or move a planned expense.</p>`)
      : `<p>Every currency stays above its floor${f.plan.length ? " once the funding plan is followed" : ""}.</p>`) +
    `<div class="lbl" style="margin:14px 0 4px">Next 90 days, in ${esc(f.base)}</div>` +
    `<div class="kvrow"><div><div class="lbl">In</div><div class="num big2 pos">${money(f.next90.in, f.base, 0)}</div></div><div><div class="lbl">Out</div><div class="num big2">${money(f.next90.out, f.base, 0)}</div></div>
      <div><div class="lbl">Net</div><div class="num big2 ${f.next90.net >= 0 ? "pos" : "neg"}">${money(f.next90.net, f.base, 0)}</div></div></div>` +
    (Object.keys(f.learned).length ? `<p class="li-s">Other spending is learned from your last 6 months: ${Object.entries(f.learned).map(([c, v]) => money(v, c, 0) + " a month in " + esc(c)).join(", ")} (median, so one big month doesn't skew it).</p>` : "");

  $("#fcSources").innerHTML = hdr("Where the numbers come from", "every line and how sure it is") +
    `<div class="tablewrap"><table class="rt"><thead><tr><th>Item</th><th class="n">Next 12 months</th><th>How sure</th><th>Why</th></tr></thead><tbody>` +
    f.sources.map((r) => `<tr><td>${esc(r.label)}</td><td class="n" data-l="12 months">${r.total < 0 ? "−" : "+"}${money(Math.abs(r.total), r.ccy, 0)}${r.monthly ? `<div class="li-s">${money(Math.abs(r.monthly), r.ccy, 0)} a month</div>` : `<div class="li-s">${dayLabel(r.first)}</div>`}</td>
      <td data-l="How sure">${confChip(r.confidence)}</td><td class="li-s" data-l="Why">${esc(r.why)}</td></tr>`).join("") + `</tbody></table></div>` +
    `<p class="li-s">Known: fixed amounts and dates. Planned: things you plan. Estimated: guesses (a bonus, a stage without a demand letter). Learned: your usual spending.</p>`;

  $("#fcFloors").innerHTML = hdr("Floors", "the least you want to keep in each currency") +
    `<form class="form" id="floorForm">${ccys.map((c) => `<label>${esc(c)} <span class="li-s">${esc(f.floor_source[c] || "")}</span><input name="${esc(c)}" type="number" step="any" value="${f.floor_source[c] === "your setting" ? f.floors[c] : ""}" placeholder="${Math.round(f.floors[c] || 0)}"></label>`).join("")}
      <button class="sm">Save floors</button></form><p class="li-s">Leave empty to use the default (about one month of that currency's usual outgoings).</p>`;
  $("#floorForm").onsubmit = async (e) => { e.preventDefault(); const body = {}; ccys.forEach((c) => body[c] = e.target.elements[c].value); await api("/forecast/floors", { method: "POST", body }); toast("Floors saved"); loaders.forecast(); };

  const accName = (id) => f.accounts.find((a) => a.id === id)?.name || "#" + id;
  const accCcy = (id) => f.accounts.find((a) => a.id === id)?.currency || f.base;
  $("#fcPlanned").innerHTML = hdr("Planned items", "one-off things you know or expect", `<button class="sm" onclick="editPlanned()">＋ Add</button>`) +
    (f.planned.length ? `<div class="tablewrap"><table class="rt"><thead><tr><th>Date</th><th>What</th><th>Account</th><th class="n">Amount</th><th>How sure</th><th></th></tr></thead><tbody>` +
      f.planned.map((p) => `<tr class="${p.done ? "muted" : ""}"><td>${esc(p.date)}</td><td data-l="What">${esc(p.note || p.category || p.kind)}</td>
        <td data-l="Account">${esc(accName(p.account_id))}${p.to_account_id ? " → " + esc(accName(p.to_account_id)) : ""}</td>
        <td class="n" data-l="Amount">${p.kind === "income" ? "+" : "−"}${money(p.amount, accCcy(p.account_id), 0)}</td><td data-l="How sure">${p.done ? chip("done", "muted") : confChip(p.confidence)}</td>
        <td><button class="sm ghost" onclick="editPlanned(${p.id})">Edit</button></td></tr>`).join("") + `</tbody></table></div>`
      : emptyBox("A bonus, a holiday, a school fee, a transfer you're planning: add it and the forecast includes it."));
};
window.FC = FC;
window.addPlanTransfer = async (s) => {
  const acc = FC.data.accounts.filter((a) => a.liquid);
  const pick = (c) => acc.filter((a) => a.currency === c).sort((x, y) => y.balance - x.balance)[0];
  const frm = pick(s.from), to = pick(s.to);
  if (!frm || !to) return toast(`Add a liquid ${!frm ? s.from : s.to} account first`);
  await api("/api/planned", { method: "POST", body: { date: s.date, kind: "transfer", account_id: frm.id, to_account_id: to.id, amount: s.send, to_amount: s.receive,
    category: "Transfer", confidence: "planned", note: `Funding plan for ${s.month}` } });
  toast("Planned transfer added"); loaders.forecast();
};
window.editPlanned = async (id) => {
  const f = FC.data || await api("/forecast");
  const row = f.planned.find((p) => p.id === id) || { date: new Date(Date.now() + 30 * 864e5).toISOString().slice(0, 10), kind: "expense", confidence: "planned", done: 0 };
  const accs = f.accounts.map((a) => [a.id, `${a.name} (${a.currency})`]);
  if (!accs.length) return toast("Add an account in Money first");
  dialog(id ? "Edit planned item" : "Add a planned item", [["date", "Date", "date"], ["kind", "Kind", "select", [["expense", "Expense"], ["income", "Income"], ["transfer", "Transfer"]]],
    ["account_id", "Account (from)", "select", accs], ["amount", "Amount (in the account's currency)", "number"],
    ["to_account_id", "To account (transfers only)", "select", [["", "—"], ...accs]], ["to_amount", "Amount received (transfers, optional)", "number"],
    ["note", "What is it?"], ["category", "Category"],
    ["confidence", "How sure", "select", [["known", "Known — amount and date are fixed"], ["planned", "Planned — you intend to"], ["estimated", "Estimated — a guess"]]],
    ["done", "Done (it's now in Money)", "checkbox"]], row,
    async (r) => { r.account_id = +r.account_id; r.to_account_id = r.to_account_id ? +r.to_account_id : null; if (r.kind !== "transfer") { r.to_account_id = null; r.to_amount = null; }
      await api("/api/planned", { method: "POST", body: r }); loaders.forecast(); },
    async (i) => { await api("/api/planned/" + i, { method: "DELETE" }); loaders.forecast(); });
};

// ---------------------------------------------------------------- GOALS: odds on top of the existing goal cards
const _goalsBase = loaders.goals;
loaders.goals = async () => {
  if (!$("#goalOdds").innerHTML) $("#goalOdds").innerHTML = `<div class="card"><p class="li-s">Replaying your goals in 2,000 simulated markets…</p></div>`;
  await Promise.all([_goalsBase(), drawOdds()]);
};
let ODDS = null;
async function drawOdds() {
  const o = await api("/plan/odds");
  ODDS = o;
  if (!o.goals.length) { $("#goalOdds").innerHTML = ""; return; }
  const base = o.base;
  const goalsCard = `<div class="card">${hdr("Chance of reaching each goal", `range of outcomes from ${o.runs.toLocaleString()} simulated markets`)}
    ${o.goals.map((g) => {
      const scale = Math.max(g.p90, g.target_future) * 1.08 || 1, x = (v) => v / scale * 100;
      return `<div class="oddrow"><div class="od-top"><div><b>${esc(g.name)}</b><div class="li-s">${esc(g.risk)} · ${money(g.monthly, g.currency, 0)}/month · target ${money(g.target_future, g.currency, 0)} by ${esc(g.target_date.slice(0, 7))}</div></div>
        <div class="od-p" style="color:${probColor(g.probability)}">${pctText(g.probability)}</div></div>
        <div class="range"><i class="band" style="left:${x(g.p10)}%;width:${Math.max(x(g.p90) - x(g.p10), 1)}%;background:${probColor(g.probability)}40"></i><i class="mid" style="left:${x(g.p50)}%;background:${probColor(g.probability)}"></i><i class="tgt" style="left:${x(g.target_future)}%"></i></div>
        <div class="li-s">Bad case ${money(g.p10, g.currency, 0)} · middle ${money(g.p50, g.currency, 0)} · good case ${money(g.p90, g.currency, 0)}${g.monthly_for_85 ? ` · <b>${money(g.monthly_for_85, g.currency, 0)}/month → 85%</b>` : ""}</div></div>`;
    }).join("")}${legendRow([["Bad case to good case (10th–90th percentile)", "rgba(169,155,255,.4)"], ["Middle outcome", css("--lilac")], ["Target", css("--ink2")]])}</div>`;
  const lever = o.goals.find((g) => g.probability < 0.85 && g.monthly_for_85) || o.goals[0];
  const leverCard = `<div class="card">${hdr("Try a saving amount")}
    <label class="form"><span>Goal</span><select id="lvGoal">${o.goals.map((g) => `<option value="${g.id}" ${g.id === lever.id ? "selected" : ""}>${esc(g.name)}</option>`).join("")}</select></label>
    <div class="lever"><input type="range" id="lvRange" min="0" step="10"><div class="kvrow"><div><div class="lbl">Per month</div><div class="num big2" id="lvAmt"></div></div><div><div class="lbl">Chance</div><div class="num big2" id="lvProb"></div></div></div></div>
    <p class="li-s" id="lvNote"></p><button class="sm" id="lvSave">Use this amount</button></div>`;
  const alloc = o.allocation, surplus = Math.max(o.surplus, 0) || 1;
  const wf = `<div class="card">${hdr("Where the monthly surplus goes", `${money(o.income, base, 0)} in − ${money(o.spend, base, 0)} out = ${money(o.surplus, base, 0)}`)}
    ${hstack([...alloc.map((a, i) => ({ pct: a.amount / surplus * 100, color: PALETTE[i % PALETTE.length], label: a.label })), { pct: Math.max(o.unallocated, 0) / surplus * 100, color: "rgba(148,163,184,.35)", label: "Not assigned" }], 18)}
    ${alloc.map((a, i) => rowItem(`<i class="dot" style="background:${PALETTE[i % PALETTE.length]}"></i> ${esc(a.label)}`, "", `<span class="num">${money(a.amount, base, 0)}</span>`)).join("")}
    ${rowItem(`<i class="dot" style="background:rgba(148,163,184,.5)"></i> Not assigned to a goal`, o.unallocated < 0 ? "<span class='neg'>Goals need more than the surplus</span>" : "buffer, or room to raise a goal", `<span class="num ${o.unallocated < 0 ? "neg" : ""}">${money(o.unallocated, base, 0)}</span>`)}</div>`;
  const wi = `<div class="card">${hdr("What if", "same goals, different futures")}<div class="tablewrap"><table class="rt"><thead><tr><th>Scenario</th>${o.goals.map((g) => `<th class="n">${esc(g.name.split(" (")[0])}</th>`).join("")}</tr></thead><tbody>
    ${o.whatif.map((w) => `<tr><td>${esc(w.label)}</td>${w.probabilities.map((p, i) => `<td class="n" data-l="${esc(o.goals[i].name)}">${chip(pctText(p), probTone(p))}</td>`).join("")}</tr>`).join("")}</tbody></table></div></div>`;
  const glideG = o.goals.find((g) => g.glide);
  const glide = glideG ? `<div class="card">${hdr("Glide path", esc(glideG.name) + " · share in shares")}
    <div class="glide">${glideG.glide.map((p) => `<div><div class="gl-col"><i style="height:${p.shares * 100}%"></i></div><div class="li-s">${p.year}</div><div class="num li-s">${Math.round(p.shares * 100)}%</div></div>`).join("")}</div>
    <p class="li-s">Shares until 10 years before the date, then moving step by step to safer money. The odds above already assume this.</p></div>` : "";
  $("#goalOdds").innerHTML = `<div class="grid g-hero">${goalsCard}${leverCard}</div><div class="grid g2">${wf}${glide || wi}</div>${glide ? wi : ""}`;
  const setLever = async () => {
    const g = o.goals.find((x) => x.id === +$("#lvGoal").value);
    const r = $("#lvRange"); r.max = Math.max((g.monthly_for_85 || g.monthly || 100) * 2, 100);
    if (!r.dataset.goal || r.dataset.goal !== String(g.id)) { r.value = g.monthly || 0; r.dataset.goal = g.id; }
    const run = async () => {
      $("#lvAmt").textContent = money(+r.value, g.currency, 0);
      const t = await api("/plan/odds/try", { method: "POST", body: { goal_id: g.id, monthly: +r.value } });
      $("#lvProb").innerHTML = `<span style="color:${probColor(t.probability)}">${pctText(t.probability)}</span>`;
      $("#lvNote").textContent = `Now ${pctText(g.probability)} at ${money(g.monthly, g.currency, 0)} a month.` + (g.monthly_for_85 ? ` ${money(g.monthly_for_85, g.currency, 0)} a month gives about 85%.` : "");
    };
    let tm; r.oninput = () => { $("#lvAmt").textContent = money(+r.value, g.currency, 0); clearTimeout(tm); tm = setTimeout(run, 180); };
    $("#lvSave").onclick = async () => { await api("/api/goals", { method: "POST", body: { id: g.id, monthly: +r.value } }); toast("Saving updated"); loaders.goals(); };
    run();
  };
  $("#lvGoal").onchange = () => { $("#lvRange").dataset.goal = ""; setLever(); };
  setLever();
}

// ---------------------------------------------------------------- DIVERSIFY
const CLS_COLOR = { shares: "#5b4bd6", bonds: "#34d399", cash: "#38bdf8", property: "#fbbf24", gold: "#e5c07b", pension: "#a99bff", other: "#94a3b8" };
loaders.diversify = async () => {
  const d = await api("/diversify");
  const base = d.base;
  $("#dvTotal").textContent = `${money(d.total, base, 0)} across ${d.positions.length} items`;
  const xr = (title, rows, colorOf, labelOf = (r) => r.label || r.key) => `<div class="xr"><div class="lbl">${title}</div>
    ${hstack(rows.map((r, i) => ({ pct: r.share * 100, color: colorOf(r, i), label: labelOf(r) })), 18)}
    ${legendRow(rows.filter((r) => r.share >= 0.005).slice(0, 7).map((r, i) => [`${esc(labelOf(r))} ${Math.round(r.share * 100)}%`, colorOf(r, i)]))}</div>`;
  $("#dvXray").innerHTML = hdr("X-ray", "looks inside index funds") + (d.total ? (
    xr("Asset type", d.classes, (r) => CLS_COLOR[r.key] || "#94a3b8") +
    xr("Country", d.countries, (r, i) => PALETTE[i % PALETTE.length]) +
    xr("Currency", d.currencies, (r) => ccyColor(r.key) || "#94a3b8", (r) => r.key) +
    (d.sectors.length ? xr("Sector (shares only)", d.sectors, (r, i) => PALETTE[i % PALETTE.length], (r) => r.key) : "")) :
    emptyBox("Add accounts, investments or assets to see the mix."));
  $("#dvFlags").innerHTML = hdr("Concentration flags") + (d.flags.map((f) => rowItem(esc(f.title), esc(f.detail), "", chip(f.tone === "bad" ? "Over" : f.tone === "warn" ? "Watch" : "Note", f.tone === "bad" ? "bad" : f.tone === "warn" ? "warn" : "muted"))).join("") || `<p>No flags against your rules.</p>`);
  $("#dvCompanies").innerHTML = hdr("Biggest companies", "through all your funds") + (d.companies.slice(0, 6).map((c) => rowItem(esc(c.name), esc(c.via.join(" + ")), `<span class="num">${(c.share * 100).toFixed(1)}%</span>`, c.via.length > 1 ? chip("in " + c.via.length + " funds", "warn") : "")).join("") || `<p class="li-s">No look-through data yet.</p>`);
  const t = d.targets;
  $("#dvTargets").innerHTML = hdr("Target vs actual", "your target mix, in %") +
    `<form id="tgtForm"><div class="tablewrap"><table class="rt"><thead><tr><th>Asset</th><th class="n">Target %</th><th class="n">Actual</th><th class="n">Gap</th></tr></thead><tbody>` +
    ["shares", "bonds", "cash", "property", "gold", "pension", "other"].map((k) => { const r = t.find((x) => x.key === k) || { key: k, label: k[0].toUpperCase() + k.slice(1), actual: 0 };
      return `<tr><td><i class="dot" style="background:${CLS_COLOR[k]}"></i> ${esc(r.label)}</td><td class="n" data-l="Target %"><input class="tin" name="${k}" type="number" min="0" max="100" step="1" value="${r.target ?? ""}"></td>
        <td class="n" data-l="Actual">${Math.round((r.actual || 0) * 100)}%</td><td class="n ${r.gap > 0.005 ? "eurtxt" : r.gap < -0.005 ? "warntxt" : ""}" data-l="Gap">${r.gap == null ? "—" : (r.gap > 0 ? "+" : "") + Math.round(r.gap * 100) + "%"}</td></tr>`; }).join("") +
    `</tbody></table></div><div class="form inline" style="margin-top:10px"><label>Invested each month (${esc(base)}) <input name="monthly_investable" type="number" step="any" value="${d.monthly_investable || ""}"></label><button class="sm">Save targets</button></div></form>`;
  $("#tgtForm").onsubmit = async (e) => { e.preventDefault(); const el = e.target.elements; const targets = {}; ["shares", "bonds", "cash", "property", "gold", "pension", "other"].forEach((k) => targets[k] = el[k].value);
    const body = { targets }; if (el.monthly_investable.value !== "") body.monthly_investable = el.monthly_investable.value;
    try { await api("/diversify/settings", { method: "POST", body }); toast("Targets saved"); loaders.diversify(); } catch (err) { toast(err.message); } };
  const R = d.rules;
  $("#dvRules").innerHTML = hdr("Your rules", "checked every time") + d.checks.map((c) => `<div class="rulechk"><span class="${c.ok ? "pos" : "warntxt"}">${c.ok ? "✓" : "!"}</span><span>${esc(c.label)}</span><span class="num li-s">${esc(c.value)}</span></div>`).join("") +
    `<details style="margin-top:10px"><summary>Change the rules</summary><form class="form" id="ruleForm">
      <label>Largest single company, % of everything <input name="max_single_company" type="number" step="any" value="${R.max_single_company * 100}"></label>
      <label>Cash cushion, months of spending <input name="min_cash_months" type="number" step="any" value="${R.min_cash_months}"></label>
      <label>Property at most, % <input name="max_property" type="number" step="any" value="${R.max_property * 100}"></label>
      <label>One sector at most, % of shares <input name="max_sector" type="number" step="any" value="${R.max_sector * 100}"></label>
      <label>One country at most, % <input name="max_one_country" type="number" step="any" value="${R.max_one_country * 100}"></label>
      <label>Fund costs at most, % a year <input name="max_ter" type="number" step="any" value="${(R.max_ter * 100).toFixed(2)}"></label><button class="sm">Save rules</button></form></details>`;
  $("#ruleForm").onsubmit = async (e) => { e.preventDefault(); const el = e.target.elements;
    const rules = { max_single_company: el.max_single_company.value / 100, min_cash_months: el.min_cash_months.value, max_property: el.max_property.value / 100,
      max_sector: el.max_sector.value / 100, max_one_country: el.max_one_country.value / 100, max_ter: el.max_ter.value / 100 };
    await api("/diversify/settings", { method: "POST", body: { rules } }); toast("Rules saved"); loaders.diversify(); };
  $("#dvOptions").innerHTML = hdr("Cheapest way to move towards your targets") +
    (d.options.map((o, i) => rowItem(`${i + 1}. ${esc(o.title)}`, esc(o.detail), `<span class="num">${o.tax ? "≈ " + money(o.tax, base, 0) + " tax" : "no tax"}</span>`, o.best ? chip("Cheapest", "good") : o.tax ? chip("Costs tax", "warn") : chip("No tax", "muted"))).join("") ||
      `<p class="li-s">${t.some((r) => r.target != null) ? "You're within 0.5% of every target." : "Set a target mix above to see how to get there."}</p>`) +
    `<p class="li-s">The app shows the arithmetic. It doesn't pick funds or tell you to buy or sell.${d.library_error ? " " + esc(d.library_error) : ""}</p>`;
};

// ---------------------------------------------------------------- OPPORTUNITIES
loaders.opportunities = async () => {
  const o = await api("/opportunities");
  const base = o.base;
  $("#opKpis").innerHTML = kpi("Found", `<span class="txt">${o.cards.length}</span>`, "from your country packs' rules") +
    kpi("Worth about", money(o.total_base, base, 0), "this year, if you act on all of them") +
    kpi("Next deadline", o.cards[0]?.deadline ? `<span class="txt">${dayLabel(o.cards[0].deadline)}</span>` : "—", o.cards[0] ? esc(o.cards[0].title.replace(/^.*?·\s*/, "")) : "");
  $("#opCards").innerHTML = o.cards.map((c) => {
    const x = c.extra || {};
    let extra = "";
    if (x.kind === "progress") extra = `<div class="kvrow"><span class="li-s">Used ${money(x.used, x.ccy, 0)}</span><span class="li-s pos">Room ${money(x.room, x.ccy, 0)}</span></div>${hstack([{ pct: x.used / x.total * 100, color: css("--lilac"), label: "used" }, { pct: x.room / x.total * 100, color: "rgba(52,211,153,.45)", label: "room" }], 12)}`;
    if (x.kind === "countdown") extra = `<div class="countbig"><b>${x.days}</b> days to go</div>`;
    if (x.kind === "table") extra = `<table class="mini"><thead><tr>${x.head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${x.rows.map((r) => `<tr>${r.map((v, i) => `<td class="${i ? "n" : ""}">${esc(hideAmt(v))}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    return `<div class="card opcard">${hdr(`${flagFor(c.country)} ${esc(c.title)}`)}
      <p>${esc(hideAmt(c.why))}</p>${extra}${c.caveat ? `<p class="li-s">${esc(c.caveat)}</p>` : ""}
      <div class="kvrow"><div><div class="lbl">Deadline</div><div>${c.deadline ? dayLabel(c.deadline) + " " + c.deadline.slice(0, 4) : "—"}</div></div>
        <div><div class="lbl">Estimated effect</div><div class="num ${c.effect_value >= 0 ? "pos" : ""}">${esc(hideAmt(c.effect))}</div></div>
        <div><div class="lbl">Rule</div><div class="num li-s">${esc(c.rule)}</div></div></div>
      <div class="acts"><button class="sm" onclick="addOppReminder(${esc(JSON.stringify({ t: c.title, d: c.deadline, c: c.country, w: c.why.slice(0, 300), k: c.rule }))})">Add a reminder</button>
        <button class="sm ghost" onclick="askClaude(${esc(JSON.stringify("Explain this for my situation, step by step: " + c.title + ". " + c.why))})">Ask AI</button></div></div>`;
  }).join("") || emptyBox("Nothing found right now. Opportunities come from your holdings (with their buy dates) and, in Germany, your banks' allowance and income fields (Money → edit account).");
  $("#opInputs").innerHTML = hdr("Numbers only you know", "used by the checks above") +
    `<form class="form inline" id="opForm"><label>India: long-term gains already realised this financial year (₹) <input name="in_ltcg_used" type="number" step="any" value="${esc(o.inputs.in_ltcg_used)}"></label><button class="sm">Save</button></form>
     <p class="li-s">Germany: set each bank's Freistellungsauftrag, investment income and losses this year in Money → edit account.</p>`;
  $("#opForm").onsubmit = async (e) => { e.preventDefault(); await api("/opportunities/inputs", { method: "POST", body: { in_ltcg_used: e.target.elements.in_ltcg_used.value } }); toast("Saved"); loaders.opportunities(); };
};
window.addOppReminder = async (x) => {
  await api("/api/calendar", { method: "POST", body: { title: x.t, due: x.d, country: x.c, detail: x.w, key: "opp:" + x.k + ":" + x.d, source: "opportunity" } }).catch((e) => toast(e.message));
  toast("Reminder added to Deadlines");
};

// ---------------------------------------------------------------- TAX RETURN
const TW = { country: null, year: null, data: null };
loaders.taxreturn = async () => {
  let w;
  try { w = await api(`/taxws?${TW.country ? "country=" + TW.country : ""}${TW.year ? "&year=" + TW.year : ""}`); }
  catch (e) { $("#twTitle").textContent = "Tax return"; $("#twSteps").innerHTML = emptyBox(esc(e.message)); return; }
  TW.data = w; TW.country = w.country; TW.year = w.year;
  $("#twEyebrow").textContent = `Tax return · ${w.name} · ${w.year_label}`;
  $("#twTitle").textContent = w.title;
  $("#twPick").innerHTML = w.available.map((a) => `<button class="pillbtn ${a.code === w.country ? "on" : ""}" onclick="TW.country='${a.code}';TW.year=null;loaders.taxreturn()">${a.flag} ${esc(a.name)}</button>`).join("") +
    `<select id="twYear" aria-label="Year">${w.years.map((y) => `<option value="${y}" ${y === w.year ? "selected" : ""}>${esc(w.year_kind === "india_fy" ? "FY " + y + "-" + String(y + 1).slice(2) : y)}</option>`).join("")}</select>`;
  $("#twYear").onchange = (e) => { TW.year = +e.target.value; loaders.taxreturn(); };
  $("#twSteps").innerHTML = w.steps.map((s, i) => `<div class="step ${s.done ? "done" : ""}"><span class="n">${s.done ? "✓" : i + 1}</span><div><b>${esc(s.label)}</b><div class="li-s">${esc(s.detail)}</div></div></div>`).join("");
  const sections = [...new Set(w.questions.map((q) => q.section || "Questions"))];
  $("#twQuestions").innerHTML = hdr("Questions", `${w.questions.filter((q) => q.answered).length} of ${w.questions.length} answered`) +
    `<form id="twForm" class="form">${sections.map((sec) => `<fieldset><legend>${esc(sec)}</legend>${w.questions.filter((q) => (q.section || "Questions") === sec).map((q) => {
      const src = q.source && q.source !== "you" ? `<span class="li-s">${esc(q.source)}</span>` : "";
      const help = q.help ? `<span class="fieldhint">${esc(q.help)}</span>` : "";
      if (q.type === "bool") return `<label class="chk"><input type="checkbox" name="${q.id}" ${q.value ? "checked" : ""}> ${esc(q.label)} ${src}${help}</label>`;
      return `<label>${esc(q.label)} ${src}<input name="${q.id}" type="${q.type === "number" ? "number" : "text"}" step="any" value="${q.value ?? ""}" class="${q.answered ? "" : "unanswered"}">${help}</label>`;
    }).join("")}</fieldset>`).join("")}<button class="sm">Save answers</button></form>`;
  $("#twForm").onsubmit = async (e) => { e.preventDefault(); const el = e.target.elements; const answers = {};
    w.questions.forEach((q) => { const i = el[q.id]; if (!i) return; answers[q.id] = q.type === "bool" ? i.checked : i.value; });
    await api("/taxws/answers", { method: "POST", body: { country: w.country, year: w.year, answers } }); toast("Answers saved"); loaders.taxreturn(); };
  $("#twDocs").innerHTML = hdr("Documents", `${w.documents.filter((d) => d.status !== "missing").length} of ${w.documents.length} found`) +
    w.documents.map((d) => rowItem(esc(d.label) + (d.required ? "" : ` <span class="li-s">optional</span>`), d.found.length ? esc(d.found.map((f) => f.path).join(", ")) : esc(d.why),
      "", chip(d.status === "found" ? "Found" : d.status === "check" ? "Check year" : "Missing", d.status === "found" ? "good" : d.status === "check" ? "warn" : "bad"))).join("") +
    `<p class="li-s">Found by your document rules in your documents folder. Drop missing ones on the Documents tab.</p>`;
  $("#twAsk").innerHTML = hdr("A follow-up question", w.ai_ready ? "from your AI assistant" : "optional, needs AI") +
    (w.ai_ready ? `<p class="li-s">The assistant reads your answers and missing documents and asks the one question a careful adviser would ask next.</p><button class="sm" id="twAskBtn">Ask me one more question</button><div id="twAskOut"></div>`
      : `<p class="li-s">The standard questions work without AI. Connect a provider in Settings (Ollama keeps it on this computer) to get a tailored follow-up.</p>`);
  if ($("#twAskBtn")) $("#twAskBtn").onclick = async () => { $("#twAskOut").innerHTML = `<p class="li-s">Thinking…</p>`;
    try { const r = await api("/taxws/ask", { method: "POST", body: { country: w.country, year: w.year } }); $("#twAskOut").innerHTML = `<div class="aiq">${md(r.question)}<div class="li-s">asked by ${esc(r.provider)}</div></div>`; }
    catch (err) { $("#twAskOut").innerHTML = `<p class="err">${esc(err.message)}</p>`; } };
  const est = w.estimate;
  $("#twOptimise").innerHTML = hdr("Optimise", "what makes a difference") +
    (w.checks.map((c) => rowItem(esc(c.title), esc(hideAmt(c.detail)), c.effect_shown ? `<span class="num ${c.effect >= 0 ? "pos" : "neg"}">${esc(hideAmt(c.effect_shown))}</span>` : "", chip(c.tone === "bad" ? "Act" : c.tone === "muted" ? "Note" : "Worth it", c.tone === "bad" ? "bad" : c.tone === "muted" ? "muted" : "good"))).join("") || `<p class="li-s">Answer the questions to see what helps.</p>`) +
    (est ? `<div class="estbox"><div class="lbl">${esc(est.headline_label || "Estimate")}</div><div class="bigest ${est.tone === "bad" ? "neg" : "pos"}">${esc(hideAmt(est.headline))}</div><p class="li-s">${esc(hideAmt(est.explanation || ""))}</p></div>` :
      w.estimate_error ? `<p class="err">${esc(w.estimate_error)}</p>` : "") +
    w.derived.map((x) => rowItem(esc(x.label), "", `<span class="num">${esc(hideAmt(x.shown || "—"))}</span>`)).join("");
  $("#twSheet").innerHTML = hdr("Filing sheet", "copy into the official form yourself") +
    `<div class="tablewrap"><table class="rt"><thead><tr><th>Form</th><th>Field</th><th class="n">Value</th></tr></thead><tbody>${w.sheet.map((r) => `<tr><td>${esc(r.form)}</td><td data-l="Field">${esc(r.field)}</td><td class="n" data-l="Value">${esc(hideAmt(r.shown))}</td></tr>`).join("")}</tbody></table></div>
    <p class="li-s">${esc(w.filing_hint)}</p><div class="acts"><a class="btnlink" href="${withToken(`/taxws/export?country=${w.country}&year=${w.year}&fmt=csv`)}">Export for your adviser (CSV)</a>
    <a class="btnlink ghost" href="${withToken(`/taxws/export?country=${w.country}&year=${w.year}&fmt=json`)}">JSON</a></div>
    <p class="li-s">Nothing is sent to a tax office. Estimates only — confirm with a tax adviser.</p>`;
};
window.TW = TW;

// ---------------------------------------------------------------- ROUTINES
const EVERY = { daily: "every day", weekly: "every week", monthly: "every month" };
loaders.routines = async () => {
  const r = await api("/routines");
  drawRoutines(r);
};
function drawRoutines(r) {
  const pend = r.proposals.filter((p) => p.status === "pending"), done = r.proposals.filter((p) => p.status !== "pending").slice(0, 6);
  $("#rtProposals").innerHTML = hdr("Proposals", pend.length ? `${pend.length} need your OK · nothing changes until you click` : "nothing waiting") +
    (pend.map((p) => proposalRow(p, "loaders.routines")).join("") || `<p class="li-s">Routines put suggestions here: transfers from the funding plan, goal changes that fit your surplus, reminders for tax deadlines. AI assistants connected through MCP can suggest too.</p>`) +
    (done.length ? `<details><summary>Recently decided</summary>${done.map((p) => proposalRow(p, "loaders.routines")).join("")}</details>` : "");
  $("#rtList").innerHTML = hdr("Routines", "all run without AI") + r.routines.map((x) => `<div class="rt-item">
      <label class="switch"><input type="checkbox" ${x.enabled ? "checked" : ""} onchange="toggleRoutine('${x.id}', this.checked)"><span></span></label>
      <div class="li-l"><div class="li-t">${esc(x.label)} <span class="li-s">${EVERY[x.every] || x.every}</span></div><div class="li-s">${esc(x.about)}</div>
        ${x.summary?.text ? `<div class="li-s rt-sum">${esc(hideAmt(x.summary.text))}</div>` : ""}
        ${x.summary?.ai_summary ? `<div class="aiq"><div class="lbl">Summary by ${esc(x.summary.ai_provider || "AI")}</div>${md(x.summary.ai_summary)}</div>` : ""}</div>
      <div class="li-r"><button class="sm ghost" onclick="runRoutines('${x.id}')">Run</button><div class="li-s">${x.last_run ? "last " + esc(x.last_run.replace("T", " ").slice(0, 16)) : "not run yet"}</div></div></div>`).join("") +
    `<label class="chk" style="margin-top:10px"><input type="checkbox" ${r.ai_summary ? "checked" : ""} onchange="setAiSummary(this.checked)"> Add a short AI-written summary to the monthly review ${r.ai.ready ? `(${esc(r.ai.label || r.ai.provider)})` : "(connect a provider in Settings)"}</label>`;
  const snip = JSON.stringify(r.mcp.config, null, 2);
  $("#rtConnections").innerHTML = hdr("Connections") +
    rowItem("In-app assistant", r.ai.ready ? `${esc(r.ai.label || r.ai.provider)}${r.ai.model ? " · " + esc(r.ai.model) : ""}` : "not connected", "", chip(r.ai.ready ? (r.ai.provider === "ollama" ? "On this computer" : "Connected") : "Off", r.ai.ready ? "good" : "muted")) +
    rowItem("Claude Desktop, VS Code (Copilot) and other MCP apps", r.mcp.last ? `last used by ${esc(r.mcp.last.actor.replace("MCP · ", ""))} · ${esc(r.mcp.last.ts.replace("T", " ").slice(0, 16))}` : "local MCP server over stdio — no network port", "", chip(r.mcp.last ? "Used" : "Ready", r.mcp.last ? "good" : "muted")) +
    rowItem("No AI", "every routine, rule, calculator and screen works without it", "", chip("Always", "muted")) +
    `<div class="lbl" style="margin:14px 0 2px">Connect an MCP app on this computer</div>` +
    (r.mcp.clients || []).map((c) => {
      const st = { connected: ["Connected", "good"], outdated: ["Needs update", "warn"], not_connected: ["Not connected", "muted"], not_found: ["Not installed", "muted"], unreadable: ["Can't read its settings", "bad"] }[c.state];
      const btn = !c.installed ? "" : c.state === "connected"
        ? `<button class="sm ghost" onclick="mcpConnect('${c.id}', true)">Disconnect</button>`
        : c.state === "unreadable" ? "" : `<button class="sm" onclick="mcpConnect('${c.id}')">${c.state === "outdated" ? "Update" : "Connect"}</button>`;
      return rowItem(esc(c.label), c.problem ? esc(c.problem) : c.installed ? esc(c.paths.join(" · ")) : "install it and open it once to connect here", btn, chip(st[0], st[1]));
    }).join("") +
    `<p class="li-s">Connect adds one entry to the app's MCP settings and keeps a backup of the file. Other entries are left as they are.</p>` +
    `<details style="margin-top:10px"><summary>Set it up by hand instead</summary><p class="li-s">Add this to Claude Desktop's <code>claude_desktop_config.json</code> (or under <code>servers</code> in VS Code's <code>mcp.json</code>), then restart the app. It can read your numbers and <b>propose</b> changes; proposals wait here for your OK.</p>
      <pre class="code">${esc(snip)}</pre><button class="sm ghost" onclick="navigator.clipboard.writeText(${esc(JSON.stringify(snip))}).then(()=>toast('Copied'))">Copy</button></details>`;
  $("#rtAudit").innerHTML = hdr("Audit log", "who did what") + `<div class="tablewrap"><table class="rt"><thead><tr><th>When</th><th>Who</th><th>What</th></tr></thead><tbody>` +
    r.audit.slice(0, 25).map((a) => `<tr><td class="li-s">${esc(a.ts.replace("T", " ").slice(5, 16))}</td><td data-l="Who">${chip(esc(a.actor), a.actor.startsWith("MCP") || a.actor.startsWith("AI") ? "lilac" : a.actor === "Routine" ? "muted" : "eur")}</td>
      <td data-l="What">${esc(hideAmt(a.action))}${a.detail ? `<div class="li-s">${esc(hideAmt(a.detail)).slice(0, 160)}</div>` : ""}</td></tr>`).join("") + `</tbody></table></div>`;
  const b = $("#navProposals"); if (b) { b.hidden = !pend.length; b.textContent = pend.length; }
}
window.mcpConnect = async (client, remove) => {
  try {
    const r = await api("/mcp/connect", { method: "POST", body: { client, remove: !!remove } });
    toast(remove ? `${r.label}: disconnected` : `${r.label} connected. ${r.next}`);
    loaders.routines();
  } catch (e) { toast(e.message); }
};
window.runRoutines = async (id) => {
  toast("Running…");
  try { const r = await api("/routines/run", { method: "POST", body: { id } }); drawRoutines(r); toast(r.ran.length ? `Ran ${r.ran.length} routine${r.ran.length > 1 ? "s" : ""}` : "Nothing was due"); }
  catch (e) { toast(e.message); }
};
window.toggleRoutine = async (id, on) => { const r = await api("/routines/settings", { method: "POST", body: { enabled: { [id]: on } } }); drawRoutines(r); };
window.setAiSummary = async (on) => { const r = await api("/routines/settings", { method: "POST", body: { ai_summary: on } }); drawRoutines(r); };
setTimeout(refreshNavCount, 2500);
