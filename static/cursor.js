/**
 * cursor.js — کرسر نرم طلایی/فیروزه‌ای (فقط دسکتاپ)
 * الهام از افکت fluid سایت‌های portfolio، با تم خوشبخت و نور کمتر.
 * منطق app / API / ربات را لمس نمی‌کند.
 */
(function () {
  if (typeof window === "undefined") return;

  // فقط دستگاه‌های با نشانگر دقیق (ماوس)
  const fine = window.matchMedia && window.matchMedia("(pointer: fine)").matches;
  const reduced =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const touch = "ontouchstart" in window || navigator.maxTouchPoints > 0;

  if (!fine || reduced || (touch && window.innerWidth < 900)) return;

  const root = document.createElement("div");
  root.className = "kh-cursor";
  root.setAttribute("aria-hidden", "true");
  root.innerHTML =
    '<div class="kh-cursor-blob"></div>' +
    '<div class="kh-cursor-ring"></div>' +
    '<div class="kh-cursor-core"></div>';
  document.documentElement.appendChild(root);

  const blob = root.querySelector(".kh-cursor-blob");
  const ring = root.querySelector(".kh-cursor-ring");
  const core = root.querySelector(".kh-cursor-core");

  document.documentElement.classList.add("has-kh-cursor");

  let mx = window.innerWidth / 2;
  let my = window.innerHeight / 2;
  let bx = mx, by = my;
  let rx = mx, ry = my;
  let cx = mx, cy = my;
  let visible = false;
  let hover = false;
  let raf = 0;

  function show() {
    if (visible) return;
    visible = true;
    root.classList.add("is-visible");
  }
  function hide() {
    visible = false;
    root.classList.remove("is-visible");
  }

  function onMove(e) {
    mx = e.clientX;
    my = e.clientY;
    show();
  }

  function onOver(e) {
    const t = e.target;
    if (!t || !t.closest) return;
    const hit = t.closest(
      "a, button, [role='button'], .btn, .btn-sm, .btn-outline, .nav-item, .list-item, .cfg-check, input[type='checkbox'], label, .back-link"
    );
    hover = !!hit;
    root.classList.toggle("is-hover", hover);
  }

  function tick() {
    // lag بیشتر برای blob = حس سیال ملایم
    bx += (mx - bx) * 0.08;
    by += (my - by) * 0.08;
    rx += (mx - rx) * 0.18;
    ry += (my - ry) * 0.18;
    cx += (mx - cx) * 0.38;
    cy += (my - cy) * 0.38;

    blob.style.transform = `translate3d(${bx}px, ${by}px, 0) translate(-50%, -50%)`;
    ring.style.transform = `translate3d(${rx}px, ${ry}px, 0) translate(-50%, -50%)${hover ? " scale(1.55)" : ""}`;
    core.style.transform = `translate3d(${cx}px, ${cy}px, 0) translate(-50%, -50%)${hover ? " scale(0.55)" : ""}`;

    raf = requestAnimationFrame(tick);
  }

  window.addEventListener("mousemove", onMove, { passive: true });
  window.addEventListener("mouseover", onOver, { passive: true });
  document.addEventListener("mouseleave", hide);
  document.addEventListener("mouseenter", show);
  window.addEventListener("blur", hide);

  raf = requestAnimationFrame(tick);
})();
