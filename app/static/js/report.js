/* Report charts (Chart.js, vendored). Animations off so screenshots/tests see the final state. */
(function () {
  "use strict";
  var el = document.getElementById("report-data");
  if (!el || typeof Chart === "undefined") return;
  var data = JSON.parse(el.textContent);
  var COLORS = { High: "#dc3545", Medium: "#fd7e14", Low: "#198754" };
  Chart.defaults.animation = false;
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;

  var riskCanvas = document.getElementById("risk-chart");
  if (riskCanvas) {
    var levels = ["High", "Medium", "Low"];
    new Chart(riskCanvas, {
      type: "doughnut",
      data: {
        labels: levels,
        datasets: [{ data: levels.map(function (k) { return data.risk_counts[k]; }),
                     backgroundColor: levels.map(function (k) { return COLORS[k]; }), borderWidth: 2 }]
      },
      options: { maintainAspectRatio: false, cutout: "60%",
                 plugins: { legend: { position: "bottom" } } }
    });
    riskCanvas.setAttribute("data-rendered", "true");
  }

  var topCanvas = document.getElementById("top-files-chart");
  if (topCanvas) {
    var short = data.top.map(function (p) { return p.length > 38 ? "…" + p.slice(-37) : p; });
    new Chart(topCanvas, {
      type: "bar",
      data: {
        labels: short,
        datasets: [{ label: "Defect probability", data: data.top_probs,
                     backgroundColor: data.top_risks.map(function (r) { return COLORS[r]; }) }]
      },
      options: {
        indexAxis: "y", maintainAspectRatio: false,
        scales: { x: { min: 0, max: 1, title: { display: true, text: "Defect probability" } },
                  y: { ticks: { font: { size: 11 } } } },
        plugins: { legend: { display: false },
                   tooltip: { callbacks: { title: function (items) { return data.top[items[0].dataIndex]; } } } }
      }
    });
    topCanvas.setAttribute("data-rendered", "true");
  }
})();
