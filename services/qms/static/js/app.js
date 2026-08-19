document.addEventListener("input", (event) => {
  if (!event.target.classList.contains("fact-input")) return;
  const row = event.target.closest("tr");
  const low = row.dataset.low ? Number(row.dataset.low.replace(",", ".")) : null;
  const high = row.dataset.high ? Number(row.dataset.high.replace(",", ".")) : null;
  const value = event.target.value ? Number(event.target.value.replace(",", ".")) : null;
  const cell = row.querySelector(".result-cell");
  row.classList.remove("row-danger", "row-ok");
  if (value === null || Number.isNaN(value)) {
    cell.textContent = "-";
    return;
  }
  const ok = (low === null || value >= low) && (high === null || value <= high);
  row.classList.add(ok ? "row-ok" : "row-danger");
  cell.textContent = ok ? "OK" : "Отклонение";
});

document.addEventListener("DOMContentLoaded", () => {
  const menuToggle = document.querySelector(".menu-toggle");
  const sidebarCollapseToggle = document.querySelector(".sidebar-collapse-toggle");
  const sidebarRailToggle = document.querySelector(".sidebar-rail-toggle");
  const closeMenuTargets = document.querySelectorAll("[data-close-menu], .sidebar .nav-item");
  const setSidebarCollapsed = (collapsed) => {
    document.body.classList.toggle("sidebar-collapsed", collapsed);
    if (sidebarCollapseToggle) sidebarCollapseToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    localStorage.setItem("sidebarCollapsed", collapsed ? "1" : "0");
  };
  if (localStorage.getItem("sidebarCollapsed") === "1") {
    setSidebarCollapsed(true);
  }
  if (sidebarCollapseToggle) {
    sidebarCollapseToggle.addEventListener("click", () => setSidebarCollapsed(true));
  }
  if (sidebarRailToggle) {
    sidebarRailToggle.addEventListener("click", () => setSidebarCollapsed(false));
  }
  if (menuToggle) {
    menuToggle.addEventListener("click", () => {
      const isOpen = document.body.classList.toggle("menu-open");
      menuToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
    });
    closeMenuTargets.forEach((target) => {
      target.addEventListener("click", () => {
        document.body.classList.remove("menu-open");
        menuToggle.setAttribute("aria-expanded", "false");
      });
    });
  }

  const monthly = document.getElementById("monthlyChart");
  if (monthly && window.Chart) {
    new Chart(monthly, {
      type: "line",
      data: { labels: ["Янв", "Фев", "Мар", "Апр", "Май", "Июн"], datasets: [{ label: window.qmsTranslate ? window.qmsTranslate("Дефекты") : "Дефекты", data: [1, 2, 3, 2, 4, 1], borderColor: "#2457d6", tension: .3 }] },
    });
  }
  const severity = document.getElementById("severityChart");
  if (severity && window.Chart) {
    const labels = severity.dataset.labels ? severity.dataset.labels.split(",").filter(Boolean) : ["low", "medium", "high", "critical"];
    const values = severity.dataset.values ? severity.dataset.values.split(",").filter(Boolean).map(Number) : [0, 0, 0, 0];
    new Chart(severity, { type: "doughnut", data: { labels, datasets: [{ data: values, backgroundColor: ["#12805c", "#2457d6", "#b54708", "#c1153b"] }] } });
  }
  const reportChart = document.getElementById("reportChart");
  const labelsScript = document.getElementById("reportChartLabels");
  const valuesScript = document.getElementById("reportChartValues");
  if (reportChart && labelsScript && valuesScript && window.Chart) {
    new Chart(reportChart, {
      type: "bar",
      data: {
        labels: JSON.parse(labelsScript.textContent),
        datasets: [{ label: "С первого раза", data: JSON.parse(valuesScript.textContent), backgroundColor: "#2457d6" }]
      },
      options: { responsive: true, plugins: { legend: { display: false } } }
    });
  }
});

