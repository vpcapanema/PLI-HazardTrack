/**
 * Paginas /docs/* — indice lateral e rolagem do conteudo.
 */
(function () {
  "use strict";

  function slugify(text) {
    return (
      text
        .trim()
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "") || "secao"
    );
  }

  function ensureUniqueId(base, used) {
    let id = base;
    let n = 2;
    while (used.has(id)) {
      id = `${base}-${n}`;
      n += 1;
    }
    used.add(id);
    return id;
  }

  function collectSections(root) {
    const glossary = root.querySelector(".modal-glossary");
    if (glossary) {
      return [...glossary.querySelectorAll("dt")].map((el) => ({
        el,
        label: el.textContent.trim(),
      }));
    }
    return [...root.querySelectorAll("h3")].map((el) => ({
      el,
      label: el.textContent.trim(),
    }));
  }

  function buildToc() {
    const root = document.getElementById("docs-body");
    const list = document.getElementById("docs-toc");
    if (!root || !list) return [];

    const used = new Set();
    const links = [];

    collectSections(root).forEach(({ el, label }) => {
      const id = el.id || ensureUniqueId(slugify(label), used);
      if (!el.id) el.id = id;

      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = `#${id}`;
      a.textContent = label;
      a.dataset.sectionId = id;
      li.appendChild(a);
      list.appendChild(li);
      links.push({ el, a });
    });

    return links;
  }

  function initTocToggle() {
    const btn = document.querySelector("[data-docs-toc-toggle]");
    const panel = document.getElementById("docs-toc-panel");
    const body = document.getElementById("docs-toc-body");
    if (!btn || !panel || !body) return;

    btn.addEventListener("click", () => {
      const open = panel.classList.toggle("is-open");
      body.hidden = !open;
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  function scrollToSection(content, target) {
    const top =
      target.getBoundingClientRect().top -
      content.getBoundingClientRect().top +
      content.scrollTop -
      12;
    content.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
  }

  function initSectionNav(links) {
    const content = document.getElementById("docs-content");
    const list = document.getElementById("docs-toc");
    if (!content || !list || !links.length) return;

    list.addEventListener("click", (e) => {
      const a = e.target.closest('a[href^="#"]');
      if (!a) return;
      e.preventDefault();
      const id = a.getAttribute("href").slice(1);
      const target = document.getElementById(id);
      if (target) scrollToSection(content, target);
    });

    const sectionTop = (el) =>
      el.getBoundingClientRect().top -
      content.getBoundingClientRect().top +
      content.scrollTop;

    let ticking = false;
    const setActive = () => {
      ticking = false;
      const marker = content.scrollTop + 80;
      let current = links[0];
      links.forEach((item) => {
        if (sectionTop(item.el) <= marker) current = item;
      });
      links.forEach((item) => {
        item.a.classList.toggle("is-active", item === current);
      });
    };

    content.addEventListener("scroll", () => {
      if (!ticking) {
        ticking = true;
        requestAnimationFrame(setActive);
      }
    }, { passive: true });

    setActive();
  }

  document.addEventListener("DOMContentLoaded", () => {
    const links = buildToc();
    initTocToggle();
    initSectionNav(links);
  });
})();
