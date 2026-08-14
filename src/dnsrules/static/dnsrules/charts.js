/* The queries over time chart.

   The colours come from the stylesheet, so one file decides what a blocked
   query looks like and the dark scheme needs nothing here. */

let chart = null;

function draw(root) {
  const canvas = root.querySelector("#timeline");
  if (!canvas) return;
  if (typeof Chart === "undefined") {
    canvas.replaceWith("The chart library did not load.");
    return;
  }
  const data = JSON.parse(root.querySelector("#timeline-data").textContent);
  const style = getComputedStyle(document.documentElement);
  const colour = (name) => style.getPropertyValue(name).trim();

  /* A swap replaces the canvas, and Chart.js holds the one it drew into until
     it is told otherwise. */
  if (chart) chart.destroy();
  chart = new Chart(canvas, {
    type: "bar",
    data: {
      labels: data.labels,
      datasets: [
        {
          label: "Allowed",
          data: data.allowed,
          backgroundColor: colour("--bar"),
        },
        {
          label: "Blocked",
          data: data.blocked,
          backgroundColor: colour("--bad-line"),
        },
      ],
    },
    options: {
      animation: false,
      maintainAspectRatio: false,
      /* The whole column answers the pointer. Hitting one bar of a stack that
         is two pixels tall is not a thing anybody can do. */
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          stacked: true,
          grid: { display: false },
          ticks: {
            color: colour("--muted"),
            maxRotation: 0,
            autoSkipPadding: 16,
          },
        },
        y: {
          stacked: true,
          beginAtZero: true,
          grid: { color: colour("--line") },
          ticks: { color: colour("--muted"), precision: 0 },
        },
      },
      plugins: {
        legend: { labels: { color: colour("--fg"), boxHeight: 10 } },
        /* A tick says the time. The tooltip has room to say which day. */
        tooltip: {
          callbacks: { title: (items) => data.stamps[items[0].dataIndex] },
        },
      },
    },
  });
}

/* Redraw whatever htmx swapped in. */
htmx.onLoad(draw);

/* htmx processes the document as soon as it runs, which is before this file
   does, so the first chart is drawn here and not by the callback above. */
draw(document);
