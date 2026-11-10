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
    if (event.key === "Escape" && !menu?.hidden) closeMenu();
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth > 720) closeMenu();
  });

  document.querySelector(".headline")?.classList.add("anim");
})();
