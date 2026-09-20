/**
 * scene3d.js — منظومه شمسی سه‌بعدی (فقط دسکتاپ / پنل وب)
 * روی مینی‌اپ تلگرام و موبایل کاملاً غیرفعال می‌شود تا روان بماند.
 */
(function () {
  const scene = document.getElementById("scene3d");
  if (!scene) return;

  function isLightClient() {
    try {
      if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData) {
        return true;
      }
    } catch (e) {}
    try {
      if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        return true;
      }
    } catch (e) {}
    // موبایل / صفحه باریک
    try {
      if (window.matchMedia && window.matchMedia("(max-width: 900px)").matches) {
        return true;
      }
    } catch (e) {}
    if (navigator.maxTouchPoints > 0 && Math.min(screen.width, screen.height) < 900) {
      return true;
    }
    return false;
  }

  if (isLightClient()) {
    document.documentElement.classList.add("lite-ui");
    document.body && document.body.classList.add("lite-ui");
    scene.remove();
    return;
  }

  const inner = document.getElementById("scene3dInner");
  if (!inner) return;

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

  // تعداد ستاره کمتر از قبل
  spawnStars(scene.querySelector(".space-stars.far"), 40, "star-far");
  spawnStars(scene.querySelector(".space-stars.mid"), 28, "star-mid");
  spawnStars(scene.querySelector(".space-stars.near"), 16, "star-near");

  const belt = inner.querySelector(".asteroid-belt");
  if (belt && belt.children.length === 0) {
    const frag = document.createDocumentFragment();
    for (let i = 0; i < 24; i++) {
      const a = document.createElement("span");
      a.className = "asteroid";
      const ang = (i / 24) * 360 + (Math.random() * 6 - 3);
      const rad = 48 + Math.random() * 6;
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
  inner.querySelectorAll(".orbit").forEach(function (o) {
    o.style.setProperty("--phase", Math.random() * 360 + "deg");
  });

  // parallax خیلی سبک — فقط دسکتاپ
  let targetX = 0, targetY = 0, curX = 0, curY = 0, raf = 0;
  function tick() {
    curX += (targetX - curX) * 0.06;
    curY += (targetY - curY) * 0.06;
    inner.style.transform =
      "rotateX(62deg) rotateZ(0deg) translate3d(" +
      curX.toFixed(2) + "px," + curY.toFixed(2) + "px,0)";
    raf = requestAnimationFrame(tick);
  }
  window.addEventListener(
    "mousemove",
    function (e) {
      const cx = window.innerWidth / 2;
      const cy = window.innerHeight / 2;
      targetX = ((e.clientX - cx) / cx) * 12;
      targetY = ((e.clientY - cy) / cy) * 8;
    },
    { passive: true }
  );
  raf = requestAnimationFrame(tick);

  // اگر تب مخفی شد انیمیشن را متوقف کن
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
    } else if (!raf) {
      raf = requestAnimationFrame(tick);
    }
  });
})();
