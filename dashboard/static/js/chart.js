// dashboard/static/js/chart.js
// Exposes updateChart(labels, close, emaShort, emaLong) globally.
// Destroy + re-init on each call so switching symbols always shows fresh data.
// Uses design tokens via getComputedStyle for colors.

(function () {
  let _chart = null;

  function _token(name) {
    return getComputedStyle(document.documentElement)
      .getPropertyValue(name).trim();
  }

  /**
   * Render or re-render the OHLC close + EMA chart.
   *
   * @param {Array}  labels    - x-axis labels (timestamps or indices)
   * @param {Array}  close     - close price array (may contain nulls during warm-up)
   * @param {Array}  emaShort  - EMA-10 array (may contain nulls)
   * @param {Array}  emaLong   - EMA-20 array (may contain nulls)
   */
  function updateChart(labels, close, emaShort, emaLong) {
    const canvas = document.getElementById('detail-chart-canvas');
    const area   = document.getElementById('detail-chart-area');
    if (!canvas || !area) return;

    // Destroy previous instance to avoid canvas reuse errors
    if (_chart) {
      _chart.destroy();
      _chart = null;
    }

    const colorClose = _token('--text-dim');
    const colorShort = _token('--green');
    const colorLong  = _token('--yellow');
    const colorGrid  = _token('--border');

    _chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'close',
            data: close,
            borderColor: colorClose,
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.1,
            spanGaps: true,
          },
          {
            label: 'ema 10',
            data: emaShort,
            borderColor: colorShort,
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.1,
            spanGaps: true,
          },
          {
            label: 'ema 20',
            data: emaLong,
            borderColor: colorLong,
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.1,
            spanGaps: true,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: {
            display: true,
            labels: {
              color: _token('--text-dim'),
              font: { size: 10 },
              boxWidth: 12,
              padding: 8,
            },
          },
          tooltip: { enabled: false },
        },
        scales: {
          x: {
            display: false,
          },
          y: {
            grid: { color: colorGrid },
            ticks: {
              color: _token('--text-muted'),
              font: { size: 10 },
              maxTicksLimit: 4,
            },
          },
        },
      },
    });

    // Reveal the chart area
    area.classList.remove('detail-chart-hidden');
  }

  // Export to global scope so dashboard.js can call it
  window.updateChart = updateChart;
})();
