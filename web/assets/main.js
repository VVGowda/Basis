/* ============================================================
   Basis - shared script

   Injects the header, nav overlay and footer on every page, and
   wires the scroll reveals and count-ups. The chrome-injection
   pattern is adapted from the fabrica studio template; the data,
   copy and navigation are Basis's own.

   The eligibility tool itself lives in assets/tool.js and only
   loads on the page that has the form.
   ============================================================ */

(function () {
  "use strict";

  var SITE = {
    brand: "Basis",
    tagline: "Every figure has a source",
  };

  var NAV = [
    { href: "index.html", label: "Check" },
    { href: "method.html", label: "Method" },
    { href: "sources.html", label: "Sources" },
    { href: "privacy.html", label: "Privacy" },
  ];

  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function currentPage() {
    var path = location.pathname.split("/").pop();
    return path === "" ? "index.html" : path;
  }

  /* ---------- chrome ---------- */
  function injectChrome() {
    var here = currentPage();

    var header = document.createElement("header");
    header.className = "site-head";
    header.innerHTML =
      '<a class="logo" href="index.html">' + esc(SITE.brand) + "</a>" +
      '<nav class="head-nav">' +
        NAV.map(function (item) {
          var on = item.href === here ? " aria-current=\"page\"" : "";
          return '<a href="' + esc(item.href) + '"' + on + ">" + esc(item.label) + "</a>";
        }).join("") +
      "</nav>" +
      '<button class="burger" type="button" aria-label="Open menu" ' +
      'aria-expanded="false" aria-controls="nav-overlay">' +
      "<span></span><span></span><span></span></button>";

    var overlay = document.createElement("div");
    overlay.className = "nav-overlay";
    overlay.id = "nav-overlay";
    overlay.innerHTML =
      "<ul>" +
        NAV.map(function (item) {
          return '<li><a href="' + esc(item.href) + '">' + esc(item.label) + "</a></li>";
        }).join("") +
      "</ul>" +
      '<div class="nav-meta"><span>' + esc(SITE.tagline) + "</span>" +
      "<span>Federal data, checked live</span></div>";

    var footer = document.createElement("footer");
    footer.className = "site-foot card card--dark";
    footer.innerHTML =
      '<div class="foot-grid">' +
        "<ul><b>" + esc(SITE.brand) + "</b>" +
          "<li>Loan eligibility, traced to the source.</li>" +
          "<li>Federal program rules, live bank data.</li>" +
          "<li>Free, keyless, no account.</li></ul>" +
        "<ul><b>Pages</b>" +
          NAV.map(function (item) {
            return '<li><a href="' + esc(item.href) + '">' + esc(item.label) + "</a></li>";
          }).join("") +
        "</ul>" +
        "<ul><b>Sourced from</b>" +
          "<li>Federal Deposit Insurance Corporation</li>" +
          "<li>Consumer Financial Protection Bureau</li>" +
          "<li>United States Treasury</li>" +
          "<li>HUD, VA, USDA, Fannie Mae, SBA</li>" +
        "</ul>" +
      "</div>" +
      '<div class="foot-base">' +
        "<span>Estimates only. Not a credit decision or an offer of credit. " +
        "Confirm terms with the lender.</span>" +
        '<a href="#top">Back to top</a>' +
      "</div>";

    var shell = document.querySelector(".shell");
    if (!shell) return;
    shell.insertBefore(header, shell.firstChild);
    shell.appendChild(footer);
    document.body.appendChild(overlay);

    // The overlay slides rather than appearing, the way the source design
    // does it. It stays in the DOM and is moved off-screen by transform, so
    // visibility is what actually removes it from the tab order.
    var toggle = header.querySelector(".burger");

    function setMenu(open) {
      overlay.classList.toggle("open", open);
      document.body.classList.toggle("nav-open", open);
      toggle.setAttribute("aria-expanded", String(open));
      toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    }

    toggle.addEventListener("click", function () {
      setMenu(!overlay.classList.contains("open"));
    });

    overlay.addEventListener("click", function (ev) {
      if (ev.target.tagName === "A") setMenu(false);
    });

    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && overlay.classList.contains("open")) setMenu(false);
    });
  }

  /* ---------- scroll reveals ---------- */
  function wireReveals() {
    var targets = document.querySelectorAll(".reveal");
    if (!targets.length) return;

    function revealAll() {
      Array.prototype.forEach.call(targets, function (el) { el.classList.add("in"); });
    }

    // Anyone who has asked for less motion gets the finished state immediately.
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || !window.IntersectionObserver) {
      revealAll();
      return;
    }

    // Only now does hiding become safe, because this same function is
    // guaranteed to unhide again.
    document.documentElement.classList.add("reveal-ready");

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("in");
          io.unobserve(entry.target);
        }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });

    Array.prototype.forEach.call(targets, function (el) { io.observe(el); });

    // Backstop. In a background tab, a non-compositing viewport, or any
    // situation where the observer never reports, the page must not stay
    // blank. Two seconds is long after a normal reveal has finished.
    setTimeout(revealAll, 2000);
  }

  /* ---------- count-ups ---------- */
  function wireCounts() {
    var targets = document.querySelectorAll("[data-count]");
    if (!targets.length) return;

    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function run(el) {
      var end = Number(el.getAttribute("data-count"));
      if (!isFinite(end)) return;
      if (reduce || !window.requestAnimationFrame) {
        el.textContent = end.toLocaleString("en-US");
        return;
      }
      var start = null;
      var span = 900;
      var done = false;

      function settle() {
        if (done) return;
        done = true;
        el.textContent = end.toLocaleString("en-US");
      }

      function step(ts) {
        if (done) return;
        if (start === null) start = ts;
        var p = Math.min((ts - start) / span, 1);
        // Ease out, so the number settles rather than stopping dead.
        var eased = 1 - Math.pow(1 - p, 3);
        el.textContent = Math.round(end * eased).toLocaleString("en-US");
        if (p < 1) requestAnimationFrame(step);
        else settle();
      }

      requestAnimationFrame(step);

      // An animation that starts at zero must have a guaranteed end. If frames
      // are dropped or throttled the count can stall part-way and display "0",
      // which for a figure like "4,238 institutions" is not a missing
      // animation, it is a wrong number on the page.
      setTimeout(settle, span + 300);
    }

    if (!window.IntersectionObserver) {
      Array.prototype.forEach.call(targets, run);
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) { run(entry.target); io.unobserve(entry.target); }
      });
    }, { threshold: 0.4 });
    Array.prototype.forEach.call(targets, function (el) { io.observe(el); });
  }

  /* ---------- accordions ---------- */
  function wireAccordions() {
    Array.prototype.forEach.call(document.querySelectorAll(".faq-q"), function (btn) {
      btn.addEventListener("click", function () {
        var item = btn.closest(".faq-item");
        var open = item.classList.toggle("open");
        btn.setAttribute("aria-expanded", String(open));
      });
    });
  }

  /* ---------- live headline figures ---------- */
  function wireStats() {
    var slots = document.querySelectorAll("[data-stat]");
    if (!slots.length) return;

    fetch("/api/stats")
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var map = {
          banks: d.active_fdic_institutions,
          programs: d.loan_programs,
          apis: d.public_apis,
        };
        Array.prototype.forEach.call(slots, function (el) {
          var value = map[el.getAttribute("data-stat")];
          if (!value) return;
          // Re-point the count-up at the live figure before it animates.
          el.setAttribute("data-count", value);
          el.textContent = Number(value).toLocaleString("en-US");
        });
      })
      .catch(function () {
        // The verified fallback numbers already in the markup stand.
      });
  }

  function init() {
    injectChrome();
    wireStats();
    wireCounts();
    wireReveals();
    wireAccordions();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.LM = { esc: esc, SITE: SITE };
})();
