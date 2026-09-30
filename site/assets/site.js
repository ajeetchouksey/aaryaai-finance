// Hero figure: the same "hide amounts" gesture as the app — digits turn into dots in place, and back.
(() => {
  const eye = document.getElementById("eye"), fig = document.getElementById("fig");
  if (!eye || !fig) return;
  const targets = [...fig.querySelectorAll("[data-amt]")];
  targets.forEach((el) => { el.dataset.real = el.textContent; });
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let hidden = false, timer = null;
  const mask = (s, k) => { let n = 0; return s.replace(/\d/g, (d) => (n++ < k ? "•" : d)); };
  function run(toHidden) {
    clearInterval(timer);
    const steps = still ? 1 : 14; let i = 0;
    timer = setInterval(() => {
      i++;
      targets.forEach((el) => {
        const real = el.dataset.real, digits = (real.match(/\d/g) || []).length;
        const k = Math.round(digits * (toHidden ? i / steps : 1 - i / steps));
        el.textContent = mask(real, k);
      });
      if (i >= steps) clearInterval(timer);
    }, 28);
    eye.setAttribute("aria-pressed", String(toHidden));
    eye.querySelector("span").textContent = toHidden ? "Show amounts" : "Hide amounts";
    fig.classList.toggle("masked", toHidden);
  }
  eye.addEventListener("click", () => { hidden = !hidden; run(hidden); });
  document.addEventListener("keydown", (e) => { if (e.altKey && e.code === "KeyH") { e.preventDefault(); eye.click(); } });
})();
