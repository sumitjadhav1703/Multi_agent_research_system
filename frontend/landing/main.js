(() => {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const video = document.querySelector(".bg-video");
  const burger = document.querySelector(".burger");
  const overlay = document.querySelector(".menu-overlay");
  const menu = document.querySelector("#mobile-menu");
  const mobileLinks = menu ? menu.querySelectorAll("a") : [];

  if (reduceMotion && video) {
    video.pause();
    video.removeAttribute("autoplay");
  }

  function setMenuOpen(open) {
    if (!burger || !overlay || !menu) return;
    burger.setAttribute("aria-expanded", open ? "true" : "false");
    burger.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    overlay.hidden = !open;
    menu.hidden = !open;
    overlay.setAttribute("aria-hidden", open ? "false" : "true");
    menu.setAttribute("aria-hidden", open ? "false" : "true");
    document.body.classList.toggle("menu-open", open);
    if (open) {
      menu.querySelector("a")?.focus();
    } else if (window.getComputedStyle(burger).display !== "none") {
      burger.focus();
    }
  }

  function closeMenu() {
    setMenuOpen(false);
  }

  if (burger) {
    burger.addEventListener("click", () => {
      const open = burger.getAttribute("aria-expanded") !== "true";
      setMenuOpen(open);
    });
  }

  if (overlay) {
    overlay.addEventListener("click", closeMenu);
  }

  mobileLinks.forEach((link) => {
    link.addEventListener("click", closeMenu);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenu();
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth > 720) closeMenu();
  });

  function easeOutCubic(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  function animateStat(el, index) {
    const target = Number(el.dataset.target);
    const decimals = Number(el.dataset.decimals || 0);
    const numEl = el.querySelector(".stat-num");
    if (!numEl || Number.isNaN(target)) return;

    if (reduceMotion) {
      numEl.textContent = target.toFixed(decimals);
      return;
    }

    const duration = 1500 + index * 80;
    const startOffset = 480 + index * 90;
    const start = performance.now() + startOffset;

    function frame(now) {
      if (now < start) {
        requestAnimationFrame(frame);
        return;
      }
      const t = Math.min(1, (now - start) / duration);
      const value = target * easeOutCubic(t);
      numEl.textContent = value.toFixed(decimals);
      if (t < 1) requestAnimationFrame(frame);
    }

    requestAnimationFrame(frame);
  }

  const stats = Array.from(document.querySelectorAll(".stat"));
  let started = false;

  function startCounts() {
    if (started) return;
    started = true;
    stats.forEach((stat, i) => animateStat(stat, i));
  }

  if (stats.length) {
    if (reduceMotion || !("IntersectionObserver" in window)) {
      startCounts();
    } else {
      const observer = new IntersectionObserver(
        (entries) => {
          if (entries.some((entry) => entry.isIntersecting)) {
            startCounts();
            observer.disconnect();
          }
        },
        { threshold: 0.25 },
      );
      const footer = document.querySelector(".stats");
      if (footer) observer.observe(footer);
    }
  }

  document.querySelector(".headline")?.classList.add("anim");
})();
