/**
 * scene3d.js — منظومه شمسی در پس‌زمینه (فقط بصری)
 * - موقعیت شروع هر سیاره تصادفی
 * - parallax ملایم
 * - صحنه داخل body می‌ماند تا روی پنل نیفتد
 */
(function () {
  const scene = document.getElementById("scene3d");
  const inner = document.getElementById("scene3dInner");
  if (!scene || !inner) return;

  // مهم: صحنه را از body خارج نکن — باعث می‌شود روی کل UI کشیده شود
  // (قبلاً برای perspective تونل به html منتقل می‌شد)

  const reduced =
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (reduced) {
    scene.classList.add("reduced");
  }

  // ستاره‌ها
  const starsHost = scene.querySelector(".space-stars");
  if (starsHost && starsHost.children.length === 0) {
    const frag = document.createDocumentFragment();
    const count = Math.min(
      120,
      Math.floor((window.innerWidth * window.innerHeight) / 14000) + 40
    );
    for (let i = 0; i < count; i++) {
      const s = document.createElement("span");
      s.className = "star";
      const size = Math.random() < 0.85 ? 1 + Math.random() * 1.2 : 2 + Math.random() * 1.5;
      s.style.width = size + "px";
      s.style.height = size + "px";
      s.style.left = Math.random() * 100 + "%";
      s.style.top = Math.random() * 100 + "%";
      s.style.opacity = String(0.25 + Math.random() * 0.65);
      s.style.animationDelay = Math.random() * 6 + "s";
      s.style.animationDuration = 3 + Math.random() * 5 + "s";
      frag.appendChild(s);
    }
    starsHost.appendChild(frag);
  }

  // موقعیت شروع تصادفی هر سیاره (فاز مدار)
  scene.querySelectorAll(".orbit").forEach((orbit) => {
    const durStr =
      orbit.style.getPropertyValue("--orbit-dur") ||
      getComputedStyle(orbit).getPropertyValue("--orbit-dur") ||
      "30s";
    const dur = parseFloat(durStr) || 30;
    // delay منفی = شروع از نقطه تصادفی روی مدار
    const delay = -(Math.random() * dur);
    orbit.style.animationDelay = delay + "s";
    const wrap = orbit.querySelector(".planet-wrap");
    if (wrap) wrap.style.animationDelay = delay + "s";
  });

  if (reduced) return;

  let targetX = 0;
  let targetY = 0;
  let curX = 0;
  let curY = 0;
  let scrollY = 0;

  function onMove(e) {
    const x = e.clientX ?? (e.touches && e.touches[0]?.clientX) ?? 0;
    const y = e.clientY ?? (e.touches && e.touches[0]?.clientY) ?? 0;
    const cx = window.innerWidth / 2;
    const cy = window.innerHeight / 2;
    targetX = (x - cx) / cx;
    targetY = (y - cy) / cy;
  }

  function onScroll() {
    scrollY = window.scrollY || 0;
  }

  function tick() {
    curX += (targetX - curX) * 0.05;
    curY += (targetY - curY) * 0.05;
    const parallaxY = Math.min(scrollY * 0.02, 24);
    inner.style.transform =
      `translate(-50%, -50%) translateY(${parallaxY}px) ` +
      `rotateY(${curX * 6}deg) rotateX(${-curY * 4}deg)`;
    requestAnimationFrame(tick);
  }

  window.addEventListener("mousemove", onMove, { passive: true });
  window.addEventListener("scroll", onScroll, { passive: true });
  requestAnimationFrame(tick);
})();
