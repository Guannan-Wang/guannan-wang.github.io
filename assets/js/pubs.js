/* Publications: client-side type filter + per-paper Cite (copy BibTeX).
   Vanilla JS, no dependencies. Safe to load on any page: each feature is
   guarded and does nothing if its markup is absent. */
(function () {
  "use strict";

  /* ---- Filter chips ------------------------------------------------------ */
  var chips = document.querySelectorAll(".pub-chip");
  if (chips.length) {
    var cards = document.querySelectorAll(".pub-card");
    var groups = document.querySelectorAll(".pubs__group");

    function applyFilter(type) {
      cards.forEach(function (card) {
        var show = type === "all" || card.getAttribute("data-type") === type;
        card.hidden = !show;
      });
      // Hide a group heading when it has no visible cards under the filter.
      groups.forEach(function (group) {
        var visible = group.querySelectorAll(".pub-card:not([hidden])").length;
        group.hidden = visible === 0;
      });
    }

    chips.forEach(function (chip) {
      chip.addEventListener("click", function () {
        chips.forEach(function (c) {
          c.classList.remove("is-active");
          c.setAttribute("aria-pressed", "false");
        });
        chip.classList.add("is-active");
        chip.setAttribute("aria-pressed", "true");
        applyFilter(chip.getAttribute("data-filter"));
      });
    });
  }

  /* ---- Cite: copy BibTeX to clipboard ------------------------------------ */
  var reduceMotion = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function flash(btn, text) {
    var original = btn.textContent;
    btn.textContent = text;
    btn.classList.add("is-copied");
    var restore = function () {
      btn.textContent = original;
      btn.classList.remove("is-copied");
    };
    if (reduceMotion) { setTimeout(restore, 1200); }
    else { setTimeout(restore, 1500); }
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    // Fallback for older/insecure contexts.
    return new Promise(function (resolve, reject) {
      try {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "absolute";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
        resolve();
      } catch (e) { reject(e); }
    });
  }

  document.querySelectorAll(".pub-cite").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var pre = btn.parentNode.querySelector(".pub-bibtex");
      if (!pre) { return; }
      copyText(pre.textContent.trim()).then(
        function () { flash(btn, "Copied!"); },
        function () { flash(btn, "Copy failed"); }
      );
    });
  });
})();
