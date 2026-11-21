import { initTheme, checkStatus } from "/static/common.js";

initTheme();
checkStatus(document.getElementById("status"), { online: "Qwen is ready", offline: "Model offline" });

// Segmented meters
document.querySelectorAll("[data-meter]").forEach((m) => {
  const ticks = +m.dataset.ticks || 24, pct = +m.dataset.meter;
  const on = Math.round((ticks * pct) / 100);
  m.innerHTML = Array.from({ length: ticks }, (_, i) =>
    `<i class="${i < on ? "on" : ""}${i === on - 1 ? " last" : ""}"></i>`).join("");
});

// Reveal on scroll
const io = new IntersectionObserver((entries) => {
  for (const e of entries) if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
}, { threshold: 0.12 });
document.querySelectorAll(".reveal").forEach((el, i) => {
  el.style.transitionDelay = `${(i % 4) * 60}ms`;
  io.observe(el);
});
