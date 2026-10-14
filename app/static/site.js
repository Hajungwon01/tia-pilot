/* 공통 동작: 테마 토글, 스크롤 등장, 숫자 카운터, 안내 페이지 목차·준비물 체크 */
(function () {
  "use strict";
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_) { /* 저장 불가 환경은 무시 */ } },
  };
  window.TIA_STORE = store;

  // ── 테마 ──
  const root = document.documentElement;
  const saved = store.get("tia-theme");
  if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);
  const isDark = () => (root.getAttribute("data-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
  function paintToggle() {
    const b = document.getElementById("themeBtn");
    if (b) { b.textContent = isDark() ? "☀" : "☾"; b.setAttribute("aria-label", isDark() ? "라이트 모드로 전환" : "다크 모드로 전환"); }
  }
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#themeBtn")) return;
    const next = isDark() ? "light" : "dark";
    root.setAttribute("data-theme", next); store.set("tia-theme", next); paintToggle();
  });
  paintToggle();

  // ── 스크롤 등장 ──
  const rv = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && rv.length) {
    const io = new IntersectionObserver((es) => es.forEach((en) => { if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); } }), { threshold: 0.12 });
    rv.forEach((el) => io.observe(el));
  } else rv.forEach((el) => el.classList.add("in"));

  // ── 숫자 카운터 ──
  const counters = document.querySelectorAll("[data-count]");
  function run(el) {
    const to = Number(el.dataset.count), t0 = performance.now(), dur = 1200;
    const tick = (t) => { const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3); el.textContent = Math.round(to * e).toLocaleString("ko-KR"); if (p < 1) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  }
  if ("IntersectionObserver" in window && counters.length) {
    const io2 = new IntersectionObserver((es) => es.forEach((en) => { if (en.isIntersecting) { run(en.target); io2.unobserve(en.target); } }), { threshold: 0.6 });
    counters.forEach((c) => io2.observe(c));
  } else counters.forEach((c) => { c.textContent = Number(c.dataset.count).toLocaleString("ko-KR"); });

  // ── 안내 페이지: 목차 스크롤스파이 ──
  const toc = document.querySelectorAll(".toc a[href^='#']");
  if (toc.length && "IntersectionObserver" in window) {
    const map = new Map([...toc].map((a) => [a.getAttribute("href").slice(1), a]));
    const spy = new IntersectionObserver((es) => es.forEach((en) => {
      if (en.isIntersecting) { toc.forEach((a) => a.classList.remove("active")); const a = map.get(en.target.id); if (a) a.classList.add("active"); }
    }), { rootMargin: "-20% 0px -70% 0px" });
    map.forEach((_, id) => { const s = document.getElementById(id); if (s) spy.observe(s); });
  }

  // ── 안내 페이지: 준비물 체크(브라우저에 저장) ──
  const prep = document.querySelectorAll(".prep li[data-key]");
  if (prep.length) {
    const key = "tia-prep"; let done = {};
    try { done = JSON.parse(store.get(key) || "{}"); } catch (_) { done = {}; }
    const bar = document.getElementById("prepBar"), txt = document.getElementById("prepTxt");
    const paint = () => {
      let n = 0;
      prep.forEach((li) => { const on = !!done[li.dataset.key]; li.classList.toggle("done", on); li.querySelector("input").checked = on; if (on) n++; });
      if (bar) bar.style.width = (n / prep.length * 100) + "%";
      if (txt) txt.textContent = n === prep.length ? "준비 완료! 이제 시작해 보세요." : `${n} / ${prep.length} 준비됨`;
    };
    prep.forEach((li) => li.addEventListener("click", (e) => {
      if (e.target.tagName !== "INPUT") { const cb = li.querySelector("input"); cb.checked = !cb.checked; }
      done[li.dataset.key] = li.querySelector("input").checked; store.set(key, JSON.stringify(done)); paint();
    }));
    paint();
  }
})();
