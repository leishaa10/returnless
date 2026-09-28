/**
 * ReturnLess - Chart Visualizations using bundled Chart.js
 * All data plotted here comes straight from /api/analytics (which in turn
 * comes from the real product catalog + the trained model) - nothing is
 * fabricated for visual effect.
 */

const ChartManager = {
  charts: {},

  initDashboardCharts(analytics) {
    if (typeof Chart === 'undefined') {
      console.warn('Chart.js not loaded');
      return;
    }
    this.renderRiskDistribution(analytics.risk_distribution || {});
  },

  initAnalyticsCharts(analytics) {
    if (typeof Chart === 'undefined') {
      console.warn('Chart.js not loaded');
      return;
    }
    this.renderCategoryRisk(analytics.category_breakdown || []);
    this.renderCategoryComparison(analytics.category_breakdown || []);
    this.renderTopRiskProducts(analytics.top_risk_products || []);
  },

  destroyChart(id) {
    if (this.charts[id]) {
      this.charts[id].destroy();
      delete this.charts[id];
    }
  },

  renderRiskDistribution(dist, canvasId = 'riskDonutChart', key = 'riskDonut') {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    this.destroyChart(key);

    const high = dist['High Risk'] || 0;
    const med = dist['Medium Risk'] || 0;
    const low = dist['Low Risk'] || 0;

    this.charts[key] = new Chart(canvas, {
      type: 'doughnut',
      data: {
        labels: ['High Risk', 'Medium Risk', 'Low Risk'],
        datasets: [{
          data: [high, med, low],
          backgroundColor: ['#ef4444', '#f59e0b', '#10b981'],
          borderWidth: 2,
          borderColor: '#FFFFFF'
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '72%',
        plugins: {
          legend: {
            position: 'bottom',
            labels: { boxWidth: 12, padding: 14, font: { family: 'Inter, sans-serif', size: 12, weight: '500' }, color: '#5E4E53' }
          }
        }
      }
    });
  },

  renderCategoryRisk(categories) {
    const canvas = document.getElementById('categoryRiskChart');
    if (!canvas) return;
    this.destroyChart('categoryRisk');

    const labels = categories.map(c => c.category);
    const data = categories.map(c => Number(c.avg_historical) || 0);
    const backgroundColors = data.map(val => val >= 3 ? '#ef4444' : val >= 1 ? '#f59e0b' : '#10b981');

    this.charts.categoryRisk = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: 'Historical Return Rate (%)',
          data: data,
          backgroundColor: backgroundColors,
          borderRadius: 6,
          borderSkipped: false
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: { beginAtZero: true, ticks: { callback: value => value + '%', color: '#6E5E63' }, grid: { color: '#EDE0DD' } },
          x: { ticks: { color: '#5E4E53', font: { weight: '500' } }, grid: { display: false } }
        },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: context => 'Historical Return Rate: ' + context.parsed.y + '%' } }
        }
      }
    });
  },

  renderCategoryComparison(categories, canvasId = 'paymentRiskChart', key = 'categoryComparison') {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    this.destroyChart(key);

    const labels = categories.map(c => c.category);
    const historical = categories.map(c => Number(c.avg_historical) || 0);
    const predicted = categories.map(c => Number(c.avg_predicted) || 0);

    this.charts[key] = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [
          { label: 'Historical Return Rate (%)', data: historical, backgroundColor: '#A89A9E', borderRadius: 4 },
          { label: 'AI Predicted Probability (%)', data: predicted, backgroundColor: '#741F32', borderRadius: 4 }
        ]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { beginAtZero: true, ticks: { callback: value => value + '%' }, grid: { color: '#EDE0DD' } },
          y: { grid: { display: false } }
        },
        plugins: {
          legend: { position: 'top', labels: { boxWidth: 12, color: '#5E4E53', font: { weight: '500' } } },
          tooltip: { callbacks: { label: context => context.dataset.label + ': ' + context.parsed.x + '%' } }
        }
      }
    });
  },

  renderTopRiskProducts(products) {
    const canvas = document.getElementById('savingsTrendChart');
    if (!canvas) return;
    this.destroyChart('topRiskProducts');

    const labels = products.map(p => p.product_name.length > 22 ? p.product_name.slice(0, 22) + '…' : p.product_name);
    const data = products.map(p => Number(p.predicted_return_probability) || 0);
    const colors = products.map(p => p.risk_level === 'HIGH' ? '#ef4444' : p.risk_level === 'MEDIUM' ? '#f59e0b' : '#10b981');

    this.charts.topRiskProducts = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{ label: 'AI Predicted Return Probability (%)', data: data, backgroundColor: colors, borderRadius: 6 }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { beginAtZero: true, max: 100, ticks: { callback: value => value + '%' }, grid: { color: '#EDE0DD' } },
          y: { grid: { display: false } }
        },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: context => 'AI Predicted: ' + context.parsed.x + '%' } }
        }
      }
    });
  }
};
