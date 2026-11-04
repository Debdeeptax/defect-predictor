/* SDP front-end helpers: loading overlay, sortable tables, upload source toggle. No network calls. */
(function () {
  "use strict";

  // Loading overlay for long-running form submissions (forms with data-loading="...").
  document.querySelectorAll("form[data-loading]").forEach(function (form) {
    form.addEventListener("submit", function () {
      var overlay = document.getElementById("loading-overlay");
      var text = document.getElementById("loading-text");
      if (text) text.textContent = form.getAttribute("data-loading") || "Working…";
      if (overlay) overlay.hidden = false;
      form.querySelectorAll("button[type=submit]").forEach(function (b) { b.disabled = true; });
    });
  });
  // Back/forward cache restores the overlay state; reset it.
  window.addEventListener("pageshow", function () {
    var overlay = document.getElementById("loading-overlay");
    if (overlay) overlay.hidden = true;
    document.querySelectorAll("form[data-loading] button[type=submit]").forEach(function (b) { b.disabled = false; });
  });

  // Sortable tables: <table data-sortable> with <th class="sortable" data-key> and <td data-sort-value>.
  document.querySelectorAll("table[data-sortable]").forEach(function (table) {
    var headers = table.querySelectorAll("th.sortable");
    headers.forEach(function (th, idx) {
      var colIndex = Array.prototype.indexOf.call(th.parentNode.children, th);
      var trigger = th.querySelector("button") || th;
      trigger.addEventListener("click", function () {
        var current = th.getAttribute("aria-sort");
        var numeric = (th.getAttribute("data-type") || "text") === "number";
        var dir;
        if (current === "descending") dir = "ascending";
        else if (current === "ascending") dir = "descending";
        else dir = numeric ? "descending" : "ascending";  // first click: biggest numbers / A→Z
        headers.forEach(function (h) { h.setAttribute("aria-sort", "none"); });
        th.setAttribute("aria-sort", dir);
        var tbody = table.tBodies[0];
        var rows = Array.prototype.slice.call(tbody.querySelectorAll(":scope > tr[data-row]"));
        var type = th.getAttribute("data-type") || "text";
        rows.sort(function (a, b) {
          var va = a.children[colIndex].getAttribute("data-sort-value");
          var vb = b.children[colIndex].getAttribute("data-sort-value");
          var cmp;
          if (type === "number") { cmp = parseFloat(va) - parseFloat(vb); }
          else { cmp = String(va).localeCompare(String(vb)); }
          if (cmp === 0) { cmp = Number(a.getAttribute("data-index")) - Number(b.getAttribute("data-index")); }
          return dir === "ascending" ? cmp : -cmp;
        });
        rows.forEach(function (r) {
          tbody.appendChild(r);
          var detail = tbody.querySelector('tr[data-detail-for="' + r.id + '"]');
          if (detail) tbody.appendChild(detail);
        });
        table.setAttribute("data-sorted-by", th.getAttribute("data-key") + ":" + dir);
      });
    });
  });

  // Upload page: show the inputs for the selected source.
  var sourceRadios = document.querySelectorAll("input[name=source]");
  function syncSource() {
    var checked = document.querySelector("input[name=source]:checked");
    var value = checked ? checked.value : "file";
    document.querySelectorAll("[data-source-panel]").forEach(function (panel) {
      panel.hidden = panel.getAttribute("data-source-panel") !== value;
    });
  }
  sourceRadios.forEach(function (r) { r.addEventListener("change", syncSource); });
  if (sourceRadios.length) syncSource();
})();
