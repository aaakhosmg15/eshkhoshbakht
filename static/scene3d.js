/**
 * scene3d.js — منظومه شمسی سه‌بعدی (فقط بصری)
 * perspective + صفحه مداری کج + parallax + فاز تصادفی
 * صحنه داخل body می‌ماند تا روی پنل نیفتد
 */
(function () {
  const scene = document.getElementById("scene3d");
  const inner = document.getElementById("scene3dInner");
  if (!scene || !inner) return;

  // فقط مینی‌اپ تلگرام — سایت وب دست نخورده می‌ماند
  try {
    if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData) {
      document.documentElement.classList.add("tg-miniapp");
      if (document.body) document.body.classList.add("tg-miniapp");
      scene.remove();
      return;
    }
  } catch (e) {}

  const reduced =
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (reduced) {
    scene.classList.add("reduced");
  }

  // لایه‌های ستاره با عمق متفاوت
  function spawnStars(host, count, layerClass) {
    if (!host || host.children.length > 0) return;
    const frag = document.createDocumentFragment();
    for (let i = 0; i < count; i++) {
      const s = document.createElement("span");
      s.className = "star " + (layerClass || "");
      const size =
        layerClass === "star-near"
          ? 1.4 + Math.random() * 1.8
          : layerClass === "star-mid"
          ? 1 + Math.random() * 1.3
          : 0.7 + Math.random() * 1;
      s.style.width = size + "px";
      s.style.height = size + "px";
      s.style.left = Math.random() * 100 + "%";
      s.style.top = Math.random() * 100 + "%";
      s.style.opacity = String(0.2 + Math.random() * 0.7);
      s.style.animationDelay = Math.random() * 7 + "s";
      s.style.animationDuration = 2.5 + Math.random() * 5 + "s";
      frag.appendChild(s);
    }
    host.appendChild(frag);
  }

  spawnStars(scene.querySelector(".space-stars.far"), 70, "star-far");
  spawnStars(scene.querySelector(".space-stars.mid"), 50, "star-mid");
  spawnStars(scene.querySelector(".space-stars.near"), 30, "star-near");
  // fallback تک‌لایه قدیمی
  const legacy = scene.querySelector(".space-stars:not(.far):not(.mid):not(.near)");
  if (legacy) spawnStars(legacy, 90, "star-mid");

  // کمربند سیارکی
  const belt = inner.querySelector(".asteroid-belt");
  if (belt && belt.children.length === 0) {
    const frag = document.createDocumentFragment();
    for (let i = 0; i < 48; i++) {
      const a = document.createElement("span");
      a.className = "asteroid";
      const ang = (i / 48) * 360 + (Math.random() * 6 - 3);
      const rad = 48 + Math.random() * 6; // درصد شعاع نسبی داخل کمربند
      a.style.setProperty("--a", ang + "deg");
      a.style.setProperty("--r", rad + "%");
      a.style.width = 1 + Math.random() * 2 + "px";
      a.style.height = a.style.width;
      a.style.opacity = String(0.25 + Math.random() * 0.45);
      frag.appendChild(a);
    }
    belt.appendChild(frag);
  }

  // فاز تصادفی مدارها
  scene.querySelectorAll(".orbit").forEach((orbit) => {
    const durStr =
      orbit.style.getPropertyValue("--orbit-dur") ||
      getComputedStyle(orbit).getPropertyValue("--orbit-dur") ||
      "30s";
    const dur = parseFloat(durStr) || 30;
    const delay = -(Math.random() * dur);
    orbit.style.animationDelay = delay + "s";
    const wrap = orbit.querySelector(".planet-wrap");
    if (wrap) wrap.style.animationDelay = delay + "s";
  });
  if (belt) {
    const d = 100;
    belt.style.animationDelay = -(Math.random() * d) + "s";
  }

  if (reduced) {
    // tilt ثابت بدون انیمیشن parallax
    inner.style.setProperty("--solar-tilt", "58deg");
    inner.style.setProperty("--solar-yaw", "-12deg");
    inner.style.transform =
      "translate3d(-50%, -50%, 0) rotateX(58deg) rotateZ(-12deg)";
    return;
  }

  const BASE_TILT = 58;
  const BASE_YAW = -14;
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
    curX += (targetX - curX) * 0.045;
    curY += (targetY - curY) * 0.045;
    const tilt = BASE_TILT + curY * -10;
    const yaw = BASE_YAW + curX * 16;
    const roll = curX * 4;
    const parallaxY = Math.min(scrollY * 0.015, 18);
    const zScale = 1 + Math.abs(curX) * 0.03;

    // متغیرها برای billboard کره‌ها (خورشید/سیاره رو به دوربین)
    inner.style.setProperty("--solar-tilt", tilt.toFixed(2) + "deg");
    inner.style.setProperty("--solar-yaw", yaw.toFixed(2) + "deg");

    inner.style.transform =
      `translate3d(-50%, calc(-50% + ${parallaxY}px), 0) ` +
      `rotateX(${tilt}deg) rotateZ(${yaw}deg) rotateY(${roll}deg) scale(${zScale})`;

    // parallax لایه‌های ستاره
    const far = scene.querySelector(".space-stars.far");
    const mid = scene.querySelector(".space-stars.mid");
    const near = scene.querySelector(".space-stars.near");
    if (far)
      far.style.transform = `translate3d(${curX * -8}px, ${curY * -6}px, 0)`;
    if (mid)
      mid.style.transform = `translate3d(${curX * -18}px, ${curY * -12}px, 0)`;
    if (near)
      near.style.transform = `translate3d(${curX * -32}px, ${curY * -22}px, 0)`;

    requestAnimationFrame(tick);
  }

  window.addEventListener("mousemove", onMove, { passive: true });
  window.addEventListener("scroll", onScroll, { passive: true });
  requestAnimationFrame(tick);
})();
