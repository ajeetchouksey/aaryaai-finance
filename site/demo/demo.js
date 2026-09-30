// aaryaai finance — public demo. Replays answers recorded from the real app running on invented sample data.
// Nothing you do here is saved or sent anywhere. Loaded before app.js.
(() => {
  const NOT_SAVED = "This is the demo with sample data — changes aren't saved. Install the app to use your own data.";
  const COMPUTE = new Set(["/tax/run", "/calc/backtest", "/calc/sip", "/rules/test", "/docs/analyze", "/plan/odds/try"]);
  let REC = null;
  const loaded = (window.__DEMO_REC ? Promise.resolve(window.__DEMO_REC) : fetch("recordings.json").then((r) => r.json())).then((j) => (REC = j));
  const realFetch = window.fetch.bind(window);

  // must match request_key() in site/record_demo.py
  async function sha1(s) {
    const h = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(s));
    return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 12);
  }
  const canon = (v) => Array.isArray(v) ? "[" + v.map(canon).join(",") + "]"
    : v && typeof v === "object" ? "{" + Object.keys(v).sort().map((k) => JSON.stringify(k) + ":" + canon(v[k])).join(",") + "}"
    : JSON.stringify(v);
  async function keyOf(method, url, body) {
    const u = new URL(url, "http://x");
    const q = [...u.searchParams].filter(([k]) => k !== "t").sort((a, b) => a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : 1);
    let key = method.toUpperCase() + " " + u.pathname + (q.length ? "?" + new URLSearchParams(q).toString() : "");
    if (method.toUpperCase() !== "GET" && body) {
      let b = body; try { b = canon(JSON.parse(body)); } catch (e) { }
      key += "#" + await sha1(b);
    }
    return key;
  }
  const reply = (status, body, type = "application/json") => new Response(typeof body === "string" ? body : JSON.stringify(body), { status, headers: { "content-type": type } });
  const samePathAll = (method, path) => Object.keys(REC).filter((k) => k.startsWith(method + " " + path) && (k.length === (method + " " + path).length || "?#".includes(k[(method + " " + path).length])));

  window.fetch = async (input, init = {}) => {
    const url = typeof input === "string" ? input : input.url;
    if (!url.startsWith("/") || url.startsWith("//")) return realFetch(input, init);
    await loaded;
    const method = (init.method || "GET").toUpperCase(), path = url.split("?")[0];
    const key = await keyOf(method, url, init.body);
    if (REC[key]) return reply(REC[key].status, REC[key].body, REC[key].type);
    if (method === "GET") {
      // same screen on another day (e.g. money summary for a different date): reuse the closest recording
      const params = new URL(url, "http://x").searchParams;
      const cand = samePathAll("GET", path).map((k) => {
        const kp = new URL(k.slice(4), "http://x").searchParams; let score = 0;
        for (const [a, v] of params) if (a !== "anchor" && a !== "t" && kp.get(a) === v) score++;
        return [score, k];
      }).sort((a, b) => b[0] - a[0]);
      if (cand.length) { const r = REC[cand[0][1]]; return reply(r.status, r.body, r.type); }
      return reply(404, { detail: "Not part of the demo." });
    }
    if (COMPUTE.has(path)) {
      const k = samePathAll(method, path)[0];
      if (k) { toastSoon("Demo: showing the example result — install the app to calculate with your numbers"); return reply(REC[k].status, REC[k].body, REC[k].type); }
    }
    return reply(400, { detail: NOT_SAVED });
  };
  function toastSoon(m) { setTimeout(() => window.toast && window.toast(m), 60); }

  // links that would open files or downloads from the real app
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("a[href]");
    if (!a) return;
    const h = a.getAttribute("href") || "";
    if (h.startsWith("/docs/open") || h.startsWith("/data/export")) { e.preventDefault(); toastSoon("In the real app this opens the file or downloads your data."); }
  }, true);

  // demo banner
  addEventListener("DOMContentLoaded", () => {
    const b = document.createElement("div");
    b.className = "demo-banner";
    b.innerHTML = `<span><b>Demo</b> · invented sample data · nothing is saved</span><a href="../#download">Get the app</a>`;
    document.body.prepend(b);
  });
})();
