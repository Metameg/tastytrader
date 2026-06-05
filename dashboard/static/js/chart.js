// dashboard/static/js/chart.js
// Exposes renderChart(mode, data) — mode is 'line' or 'candle'.
// Also exposes updateLastCandle(data, mode) for in-place live updates.
// Back-compat: window.updateChart(labels, close, emaShort, emaLong) still works.
// Destroy + re-init on each renderChart call to avoid canvas reuse errors.
// Colors come from CSS design tokens (no inline styles).

(function () {
  let _chart = null;

  function _token(name) {
    return getComputedStyle(document.documentElement)
      .getPropertyValue(name).trim();
  }

  /**
   * Render or re-render the chart in 'line' or 'candle' mode.
   *
   * @param {string} mode  - 'line' or 'candle'
   * @param {Object} data  - { labels, open, high, low, close, ema_short, ema_long }
   */
  function renderChart(mode, data) {
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
    const colorWick  = _token('--border');
    const colorGreen = _token('--green');
    const colorRed   = _token('--red');

    const labels   = data.labels   || [];
    const close    = data.close    || [];
    const emaShort = data.ema_short || [];
    const emaLong  = data.ema_long  || [];
    const open     = data.open     || [];
    const high     = data.high     || [];
    const low      = data.low      || [];

    const sharedYAxis = {
      grid: { color: colorGrid },
      ticks: {
        color: _token('--text-muted'),
        font: { size: 10 },
        maxTicksLimit: 4,
      },
    };

    const sharedOptions = {
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
        x: { display: false },
        y: sharedYAxis,
      },
    };

    if (mode === 'candle') {
      // Per-candle background: green when close >= open, red otherwise
      const bodyColors = open.map((o, i) =>
        close[i] >= o ? colorGreen : colorRed
      );

      _chart = new Chart(canvas, {
        type: 'bar',
        data: {
          labels,
          datasets: [
            {
              // Wick: [low, high] floating bar behind the body
              label: 'wick',
              type: 'bar',
              data: open.map((_, i) => [low[i], high[i]]),
              backgroundColor: colorWick,
              barThickness: 1,
              order: 2,
            },
            {
              // Body: [open, close] floating bar (colored per direction)
              label: 'body',
              type: 'bar',
              data: open.map((o, i) => [o, close[i]]),
              backgroundColor: bodyColors,
              barPercentage: 0.6,
              categoryPercentage: 0.8,
              order: 1,
            },
            {
              label: 'ema 10',
              type: 'line',
              data: emaShort,
              borderColor: colorShort,
              borderWidth: 1.5,
              pointRadius: 0,
              tension: 0.1,
              spanGaps: true,
              order: 0,
            },
            {
              label: 'ema 20',
              type: 'line',
              data: emaLong,
              borderColor: colorLong,
              borderWidth: 1.5,
              pointRadius: 0,
              tension: 0.1,
              spanGaps: true,
              order: 0,
            },
          ],
        },
        options: sharedOptions,
      });
    } else {
      // Line mode: close + EMA overlays
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
        options: sharedOptions,
      });
    }

    // Reveal the chart area
    area.classList.remove('detail-chart-hidden');
  }

  /**
   * Update the live chart in-place without a full re-render.
   * Called by the 'candle' SSE listener in dashboard.js after it updates currentChartData.
   *
   * @param {Object} data  - the same currentChartData reference (already mutated)
   * @param {string} mode  - 'line' or 'candle'
   */
  function updateLastCandle(data, mode) {
    if (!_chart) return;

    const labels   = data.labels   || [];
    const close    = data.close    || [];
    const open     = data.open     || [];
    const high     = data.high     || [];
    const low      = data.low      || [];

    _chart.data.labels = labels;

    if (mode === 'candle') {
      const colorGreen = _token('--green');
      const colorRed   = _token('--red');
      const bodyColors = open.map((o, i) =>
        close[i] >= o ? colorGreen : colorRed
      );
      const wickDs = _chart.data.datasets.find(d => d.label === 'wick');
      const bodyDs = _chart.data.datasets.find(d => d.label === 'body');
      if (wickDs) wickDs.data = open.map((_, i) => [low[i], high[i]]);
      if (bodyDs) {
        bodyDs.data = open.map((o, i) => [o, close[i]]);
        bodyDs.backgroundColor = bodyColors;
      }
    } else {
      // Line mode: dataset labeled 'close'
      const closeDs = _chart.data.datasets.find(d => d.label === 'close');
      if (closeDs) closeDs.data = close;
    }

    _chart.update('none');
  }

  /**
   * Back-compat shim — existing callers that use window.updateChart still work.
   */
  function updateChart(labels, close, emaShort, emaLong) {
    renderChart('line', {
      labels,
      close,
      ema_short: emaShort,
      ema_long: emaLong,
      open: [],
      high: [],
      low: [],
    });
  }

  // Export to global scope
  window.renderChart      = renderChart;
  window.updateLastCandle = updateLastCandle;
  window.updateChart      = updateChart;
})();
