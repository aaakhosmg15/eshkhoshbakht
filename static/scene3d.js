/**
 * scene3d.js — منظومه شمسی سه‌بعدی (فقط بصری)
 * فقط در مینی‌اپ تلگرام غیرفعال می‌شود؛ پنل وب مثل قبل می‌ماند.
 */
(function () {
  const scene = document.getElementById("scene3d");
  const inner = document.getElementById("scene3dInner");
  if (!scene || !inner) return;

  // فقط مینی‌اپ تلگرام (نه سایت موبایل)
  try {
    if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData) {
      document.documentElement.classList.add("tg-miniapp", "lite-ui");
      if (document.body) document.body.classList.add("tg-miniapp", "lite-ui");
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
  const legacy = scene.querySelector(".space-stars:not(.far):not(.mid):not(.near)");
  if (legacy) spawnStars(legacy, 90, "star-mid");

  const belt = inner.querySelector(".asteroid-belt");
  if (belt && belt.children.length === 0) {
    const frag = document.createDocumentFragment();
    for (let i = 0; i < 48; i++) {
      const a = document.createElement("span");
      a.className = "asteroid";
      const ang = (i / 48) * 360 + (Math.random() * 6 - 3);
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

  inner.querySelectorAll(".orbit").forEach(function (o) {
    o.style.setProperty("--phase", Math.random() * 360 + "deg");
  });

  let targetX = 0, targetY = 0, curX = 0, curY = 0, raf = 0;
  function tick() {
    curX += (targetX - curX) * 0.08;
    curY += (targetY - curY) * 0.08;
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
      targetX = ((e.clientX - cx) / cx) * 18;
      targetY = ((e.clientY - cy) / cy) * 12;
    },
    { passive: true }
  );
  raf = requestAnimationFrame(tick);

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
    } else if (!raf) {
      raf = requestAnimationFrame(tick);
    }
  });
})();
