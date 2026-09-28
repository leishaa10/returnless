/**
 * ReturnLess - Main Application Controller (Product-Level AI Return Risk)
 */

const App = {
  state: {
    currentView: 'landing',
    user: null,
    products: [],
    currentProduct: null,
    analytics: null,
    profile: null,
    meta: { categories: [], countries: [] },
    billingCycle: 'monthly',
    paymentConfig: null,
    paying: false,
    filters: {
      risk: 'ALL',
      category: 'ALL',
      search: ''
    }
  },

  async init() {
    this.bindGlobalEvents();
    await this.loadMeta();

    const savedUser = localStorage.getItem('returnless_user');
    if (savedUser) {
      try {
        this.state.user = JSON.parse(savedUser);
      } catch (e) {
        this.state.user = null;
      }
    }

    // A genuinely fresh page load (new tab, browser refresh, reopened
    // bookmark) should always show the company picker first - even if the
    // address bar still has an old #dashboard hash and localStorage still
    // has a previously-picked company saved. Without this, reopening the
    // tab from an earlier demo session skips straight back into whichever
    // company was last used, which looks like the app only has one
    // company. sessionStorage is per-tab and cleared when the tab/browser
    // closes, so this only kicks in on a real fresh load, not on normal
    // in-app navigation/refresh right after picking a company.
    const hasActiveSession = sessionStorage.getItem('returnless_active_session') === '1';

    const hash = window.location.hash.replace('#', '').trim();
    const knownViews = ['landing', 'login', 'logout', 'register', 'dashboard', 'add-order', 'order-details', 'order-history', 'analytics', 'plans', 'settings', 'admin'];
    const protectedViews = ['dashboard', 'add-order', 'order-details', 'order-history', 'analytics', 'settings', 'admin'];
    const hashView = hash.split('/')[0];

    if (hashView && protectedViews.includes(hashView) && !hasActiveSession) {
      this.state.user = null;
      localStorage.removeItem('returnless_user');
      this.navigate('login');
      return;
    }

    if (hash && knownViews.includes(hashView)) {
      const parts = hash.split('/');
      this.navigate(parts[0], parts[1] || null);
    } else {
      this.navigate('landing');
    }

    await this.loadProfile();
  },

  async loadMeta() {
    try {
      const res = await fetch('/api/meta').then(r => r.json());
      if (res.success) {
        this.state.meta = { categories: res.categories, countries: res.countries };
        this.populateMetaSelects();
      }
    } catch (e) {
      console.error('Error loading model metadata:', e);
    }
  },

  populateMetaSelects() {
    const catSelect = document.getElementById('f_category');
    if (catSelect && catSelect.options.length === 0) {
      catSelect.innerHTML = this.state.meta.categories.map(c => `<option value="${c}">${c}</option>`).join('');
    }
    const marketSelect = document.getElementById('f_market');
    if (marketSelect && marketSelect.options.length === 0) {
      marketSelect.innerHTML = this.state.meta.countries.map(c => `<option value="${c}">${c}</option>`).join('');
    }
    const catFilter = document.getElementById('historyStatusFilter');
    if (catFilter && catFilter.options.length <= 1) {
      catFilter.innerHTML = '<option value="ALL">All Categories</option>' +
        this.state.meta.categories.map(c => `<option value="${c}">${c}</option>`).join('');
    }
  },

  bindGlobalEvents() {
    document.querySelectorAll('[data-view]').forEach(elem => {
      elem.addEventListener('click', (e) => {
        e.preventDefault();
        const targetView = elem.getAttribute('data-view');
        this.navigate(targetView);
      });
    });

    window.addEventListener('hashchange', () => {
      const hash = window.location.hash.replace('#', '').trim();
      const parts = hash.split('/');
      const known = ['landing', 'login', 'logout', 'register', 'dashboard', 'add-order', 'order-details', 'order-history', 'analytics', 'plans', 'settings', 'admin'];
      // Ignore in-page anchors (e.g. #how-it-works) - they are not views
      if (parts[0] && known.includes(parts[0]) && parts[0] !== this.state.currentView) {
        this.navigate(parts[0], parts[1] || null, false);
      }
    });

    const searchInput = document.getElementById('historySearchInput');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        this.state.filters.search = e.target.value;
        this.loadProductHistory();
      });
    }

    const riskSelect = document.getElementById('historyRiskFilter');
    if (riskSelect) {
      riskSelect.addEventListener('change', (e) => {
        this.state.filters.risk = e.target.value;
        this.loadProductHistory();
      });
    }

    const categorySelect = document.getElementById('historyStatusFilter');
    if (categorySelect) {
      categorySelect.addEventListener('change', (e) => {
        this.state.filters.category = e.target.value;
        this.loadProductHistory();
      });
    }
  },

  isAdmin() {
    return !!(this.state.user && this.state.user.role === 'admin');
  },

  async navigate(viewName, param = null, updateHash = true) {
    // Admin and company areas are separate: the admin dashboard needs an
    // admin session, and an admin session only ever sees the admin dashboard.
    if (viewName === 'admin' && !this.isAdmin()) {
      return this.navigate('login');
    }
    const companyViews = ['dashboard', 'add-order', 'order-details', 'order-history', 'analytics', 'plans', 'settings'];
    if (this.isAdmin() && companyViews.includes(viewName)) {
      return this.navigate('admin');
    }

    const protectedViews = ['dashboard', 'add-order', 'order-details', 'order-history', 'analytics', 'settings'];
    if (protectedViews.includes(viewName) && !this.state.user) {
      // Fallback only for a direct URL/refresh into a protected view with no
      // session at all - defaults to the Apex demo account (merchant_id: 1)
      // so it still resolves to a real, valid company rather than an
      // unscoped session.
      this.state.user = {
        merchant_id: 1,
        email: 'operations@apexretail.com',
        business_name: 'Apex Retailers Global',
        plan: 'Growth Tier'
      };
      localStorage.setItem('returnless_user', JSON.stringify(this.state.user));
      sessionStorage.setItem('returnless_active_session', '1');
    }

    this.state.currentView = viewName;
    if (updateHash) {
      window.location.hash = param ? `${viewName}/${param}` : viewName;
    }

    const landingNav = document.getElementById('public-nav');
    const appShell = document.getElementById('app-shell');
    const publicContainer = document.getElementById('public-container');

    const isPublic = ['landing', 'login', 'logout', 'register'].includes(viewName);

    if (isPublic) {
      if (landingNav) landingNav.style.display = 'flex';
      if (appShell) appShell.style.display = 'none';
      if (publicContainer) publicContainer.style.display = 'block';

      document.querySelectorAll('.public-view').forEach(v => v.classList.remove('active'));
      const activePublic = document.getElementById(`view-${viewName}`);
      if (activePublic) activePublic.classList.add('active');

      if (viewName === 'login') {
        this.setLoginMode(false);
        this.loadDemoAccounts();
      }
      if (viewName === 'logout') {
        this.renderLogoutPage();
      }
    } else {
      if (landingNav) landingNav.style.display = 'none';
      if (appShell) appShell.style.display = 'flex';
      if (publicContainer) publicContainer.style.display = 'none';

      document.querySelectorAll('.sidebar-nav-item').forEach(item => {
        item.classList.toggle('active', item.getAttribute('data-view') === viewName);
      });

      document.querySelectorAll('.app-view').forEach(v => v.classList.remove('active'));
      const activeApp = document.getElementById(`view-${viewName}`);
      if (activeApp) activeApp.classList.add('active');

      if (appShell) appShell.classList.toggle('is-admin', this.isAdmin());
      if (this.state.user) {
        const storeNameElem = document.getElementById('sidebarStoreName');
        if (storeNameElem) storeNameElem.textContent = this.state.user.business_name;
        const planElem = document.getElementById('sidebarPlanName');
        if (planElem && this.isAdmin()) planElem.textContent = 'Platform Administrator';
      }
    }

    window.scrollTo(0, 0);

    if (viewName === 'admin') {
      await this.loadAdminDashboard();
    } else if (viewName === 'dashboard') {
      await this.loadDashboard();
    } else if (viewName === 'order-history') {
      this.populateMetaSelects();
      await this.loadProductHistory();
    } else if (viewName === 'order-details') {
      if (param) {
        await this.loadProductDetails(param);
      } else if (this.state.currentProduct) {
        this.renderProductDetails(this.state.currentProduct);
      } else {
        this.navigate('dashboard');
      }
    } else if (viewName === 'analytics') {
      await this.loadAnalyticsPage();
    } else if (viewName === 'plans') {
      await this.loadPlansPage();
    } else if (viewName === 'settings') {
      await this.loadSettingsPage();
    } else if (viewName === 'add-order') {
      this.setupAnalyzeProductPage();
    }
  },

  async loadDashboard() {
    try {
      const [productsRes, analyticsRes] = await Promise.all([
        fetch('/api/products').then(r => r.json()),
        fetch('/api/analytics').then(r => r.json())
      ]);

      if (productsRes.success) {
        this.state.products = productsRes.products;
        this.renderRecentProducts(productsRes.products.slice(0, 6));
      }

      if (analyticsRes.success) {
        this.state.analytics = analyticsRes.analytics;
        this.renderDashboardKPIs(analyticsRes.analytics);
        ChartManager.initDashboardCharts(analyticsRes.analytics);
        this.renderHighRiskAlerts(this.state.products);
      }
    } catch (err) {
      console.error('Error loading dashboard data:', err);
    }
  },

  renderDashboardKPIs(data) {
    const totalElem = document.getElementById('kpiTotalOrders');
    const highRiskElem = document.getElementById('kpiHighRisk');
    const medRiskElem = document.getElementById('kpiMediumRisk');
    const lowRiskElem = document.getElementById('kpiLowRisk');
    const avgProbElem = document.getElementById('kpiAvgProbability');
    const savingsElem = document.getElementById('kpiPreventedSavings');

    if (totalElem) totalElem.textContent = data.total_products;
    if (highRiskElem) highRiskElem.textContent = data.high_risk_count;
    if (medRiskElem) medRiskElem.textContent = data.medium_risk_count;
    if (lowRiskElem) lowRiskElem.textContent = data.low_risk_count;
    if (avgProbElem) avgProbElem.textContent = `${data.avg_predicted_probability}%`;
    if (savingsElem) savingsElem.textContent = `$${data.estimated_cost_exposure.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
  },

  renderHighRiskAlerts(products) {
    const alertBox = document.getElementById('highRiskAlertContainer');
    if (!alertBox) return;

    const highRiskPending = products.filter(p => p.risk_level === 'HIGH' && p.status === 'Needs Review');
    if (highRiskPending.length === 0) {
      alertBox.innerHTML = `
        <div class="alert-banner alert-success">
          <div class="alert-icon">
            <svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
          </div>
          <div class="alert-content">
            <strong>All High-Risk Products Reviewed</strong>
            <p>No high-risk products are currently pending review. Your catalog is in good shape.</p>
          </div>
        </div>
      `;
      return;
    }

    const first = highRiskPending[0];
    alertBox.innerHTML = `
      <div class="alert-banner alert-danger">
        <div class="alert-icon">
          <svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
        </div>
        <div class="alert-content">
          <div class="alert-title-row">
            <strong>High-Risk Alert: ${highRiskPending.length} Products Need Review</strong>
            <span class="badge badge-danger">Action Suggested</span>
          </div>
          <p><strong>${first.product_name}</strong> (${first.category}) has an <strong>${Math.round(first.predicted_return_probability * 100)}% AI predicted return probability</strong> vs. a ${this.formatHistoricalRate(first.total_orders, first.historical_return_rate)} historical rate.</p>
        </div>
        <div class="alert-actions">
          <button class="btn btn-sm btn-danger" onclick="App.navigate('order-details', '${first.product_id}')">Inspect & Act</button>
        </div>
      </div>
    `;
  },

  renderRecentProducts(products) {
    const tbody = document.getElementById('recentOrdersTableBody');
    if (!tbody) return;

    if (products.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center py-4 text-muted">No products analyzed yet. Click "Analyze Product" to begin.</td></tr>`;
      return;
    }

    tbody.innerHTML = products.map(p => `
      <tr>
        <td>
          <div class="product-cell">
            <span class="product-name">${p.product_name}</span>
            <span class="text-muted" style="font-size:11px;">${p.product_id}</span>
          </div>
        </td>
        <td>${p.category}</td>
        <td class="font-semibold">£${p.price.toFixed(2)}</td>
        <td>${this.formatHistoricalRate(p.total_orders, p.historical_return_rate)}</td>
        <td>
          <div class="prob-pill-wrapper">
            <div class="prob-bar-track">
              <div class="prob-bar-fill ${this.getRiskColorClass(p.risk_level)}" style="width: ${Math.round(p.predicted_return_probability * 100)}%"></div>
            </div>
            <span class="prob-number font-bold">${Math.round(p.predicted_return_probability * 100)}%</span>
          </div>
        </td>
        <td>
          <span class="risk-badge badge-${p.risk_level.toLowerCase()}">${p.risk_level}</span>
        </td>
        <td>
          <span class="status-pill status-${p.status.toLowerCase().replace(/\s+/g, '-')}">${p.status}</span>
        </td>
        <td class="text-right">
          <button class="btn btn-xs btn-outline" onclick="App.navigate('order-details', '${p.product_id}')">Inspect</button>
        </td>
      </tr>
    `).join('');
  },

  async loadProductHistory() {
    const risk = this.state.filters.risk;
    const category = this.state.filters.category;
    const search = this.state.filters.search;

    const query = new URLSearchParams();
    if (risk && risk !== 'ALL') query.append('risk', risk);
    if (category && category !== 'ALL') query.append('category', category);
    if (search) query.append('search', search);

    try {
      const res = await fetch(`/api/products?${query.toString()}`).then(r => r.json());
      if (res.success) {
        this.renderHistoryTable(res.products);
      }
    } catch (e) {
      console.error('Error fetching product history:', e);
    }
  },

  renderHistoryTable(products) {
    const tbody = document.getElementById('historyTableBody');
    const countBadge = document.getElementById('historyOrderCount');
    if (countBadge) countBadge.textContent = `${products.length} products analyzed`;

    if (!tbody) return;
    if (products.length === 0) {
      tbody.innerHTML = `<tr><td colspan="10" class="text-center py-5 text-muted">No products match your filter criteria.</td></tr>`;
      return;
    }

    tbody.innerHTML = products.map(p => `
      <tr>
        <td>
          <div class="font-medium">${p.product_name}</div>
          <div class="text-xs text-muted">${p.product_id}</div>
        </td>
        <td>${p.category}</td>
        <td class="font-semibold">£${p.price.toFixed(2)}</td>
        <td>${p.total_orders}</td>
        <td>${p.total_returns}</td>
        <td>${this.formatHistoricalRate(p.total_orders, p.historical_return_rate)}</td>
        <td>
          <div class="font-bold ${this.getRiskTextClass(p.risk_level)}">${Math.round(p.predicted_return_probability * 100)}%</div>
        </td>
        <td>
          <span class="risk-badge badge-${p.risk_level.toLowerCase()}">${p.risk_level} RISK</span>
        </td>
        <td>
          <span class="status-pill status-${p.status.toLowerCase().replace(/\s+/g, '-')}">${p.status}</span>
        </td>
        <td class="text-right">
          <button class="btn btn-xs btn-primary" onclick="App.navigate('order-details', '${p.product_id}')">Inspect</button>
        </td>
      </tr>
    `).join('');
  },

  async loadProductDetails(productId) {
    try {
      const res = await fetch(`/api/products/${productId}`).then(r => r.json());
      if (res.success && res.product) {
        this.state.currentProduct = res.product;
        this.renderProductDetails(res.product);
      } else {
        this.showToast('Product not found', 'error');
        this.navigate('dashboard');
      }
    } catch (e) {
      console.error('Error fetching product details:', e);
    }
  },

  renderProductDetails(product) {
    this.state.currentProduct = product;
    const pct = Math.round(product.predicted_return_probability * 100);
    const histDisplay = this.formatHistoricalRate(product.total_orders, product.historical_return_rate);

    document.getElementById('detailsOrderId').textContent = product.product_name;
    document.getElementById('detailsOrderDate').textContent = `Last analyzed on ${product.last_analyzed_at}`;

    const statusContainer = document.getElementById('detailsStatusContainer');
    if (statusContainer) {
      statusContainer.innerHTML = `<span class="status-pill status-${product.status.toLowerCase().replace(/\s+/g, '-')}">${product.status}</span>`;
    }

    const probNumber = document.getElementById('detailsProbabilityNumber');
    if (probNumber) {
      probNumber.textContent = `${pct}%`;
      probNumber.className = `metric-giant ${this.getRiskTextClass(product.risk_level)}`;
    }
    const histNumber = document.getElementById('detailsHistoricalRateNumber');
    if (histNumber) histNumber.textContent = histDisplay;

    const badgeElem = document.getElementById('detailsRiskBadge');
    if (badgeElem) {
      badgeElem.textContent = `${product.risk_level} RETURN RISK`;
      badgeElem.className = `risk-badge-lg badge-${product.risk_level.toLowerCase()}`;
    }

    const gaugeFill = document.getElementById('detailsGaugeBar');
    if (gaugeFill) {
      gaugeFill.style.width = `${pct}%`;
      gaugeFill.className = `gauge-bar-fill ${this.getRiskColorClass(product.risk_level)}`;
    }

    const recText = document.getElementById('detailsRecommendationText');
    if (recText) recText.textContent = this.recommendationFor(product);

    const costElem = document.getElementById('detailsEstimatedCost');
    if (costElem) {
      const expectedReturns = product.total_orders * product.predicted_return_probability;
      const cost = (expectedReturns * (product.price * 0.28 + 1.5)).toFixed(2);
      costElem.textContent = `$${cost}`;
    }

    const factorsList = document.getElementById('detailsFactorsList');
    if (factorsList) {
      const factors = product.key_factors || [];
      if (factors.length === 0) {
        factorsList.innerHTML = `<p class="text-muted">No explicit risk factors available.</p>`;
      } else {
        factorsList.innerHTML = factors.map(f => `
          <div class="factor-item factor-negative">
            <div class="factor-header">
              <div class="factor-title"><strong>${f}</strong></div>
            </div>
          </div>
        `).join('');
      }
    }

    document.getElementById('detailsProductName').textContent = product.product_name;
    document.getElementById('detailsProductBrand').textContent = product.category;
    document.getElementById('detailsProductPrice').textContent = `£${product.price.toFixed(2)}`;
    document.getElementById('detailsProductSpecs').textContent = product.market;

    document.getElementById('detailsCustomerName').textContent = product.total_orders;
    document.getElementById('detailsCustomerType').textContent = product.total_returns;
    document.getElementById('detailsPrevReturns').textContent = histDisplay;
    document.getElementById('detailsOrderFreq').textContent = product.status;

    const notesBox = document.getElementById('detailsDecisionNotesBox');
    if (notesBox) {
      if (product.decision_notes) {
        notesBox.style.display = 'block';
        document.getElementById('detailsDecisionNotesText').textContent = product.decision_notes;
      } else {
        notesBox.style.display = 'none';
      }
    }
  },

  recommendationFor(product) {
    if (product.risk_level === 'HIGH') {
      return `High return risk detected for "${product.product_name}". Consider improving the product description, images, sizing/spec information, or packaging for this ${product.category} item.`;
    } else if (product.risk_level === 'MEDIUM') {
      return `Moderate return risk. Review the listing for "${product.product_name}" and monitor its return rate as order volume grows.`;
    }
    return `Low return risk. No action needed for "${product.product_name}" right now.`;
  },

  async handleOrderAction(newStatus) {
    if (!this.state.currentProduct) return;
    const productId = this.state.currentProduct.product_id;

    let defaultNotes = '';
    if (newStatus === 'Listing Improved') {
      defaultNotes = 'Seller updated the product description, images and/or sizing information to reduce future returns.';
    } else if (newStatus === 'Monitoring') {
      defaultNotes = 'Flagged for ongoing monitoring as more orders come in.';
    } else if (newStatus === 'Discontinued') {
      defaultNotes = 'High return risk confirmed. Product marked for discontinuation.';
    }

    try {
      const res = await fetch(`/api/products/${productId}/action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus, notes: defaultNotes })
      }).then(r => r.json());

      if (res.success) {
        this.showToast(`Product status updated to: ${newStatus}`, 'success');
        this.renderProductDetails(res.product);
        this.loadDashboard();
      } else {
        this.showToast('Failed to update status', 'error');
      }
    } catch (e) {
      console.error(e);
      this.showToast('Server error', 'error');
    }
  },

  setupAnalyzeProductPage() {
    this.populateMetaSelects();
    const form = document.getElementById('addOrderForm');
    if (!form) return;

    form.onsubmit = async (e) => {
      e.preventDefault();
      await this.submitNewProduct(form);
    };

    const inputs = form.querySelectorAll('input, select');
    inputs.forEach(input => {
      input.addEventListener('input', () => this.debouncedPreview(form));
      input.addEventListener('change', () => this.debouncedPreview(form));
    });

    this.updateLivePreview(form);
  },

  debouncedPreview(form) {
    clearTimeout(this._previewTimer);
    this._previewTimer = setTimeout(() => this.updateLivePreview(form), 400);
  },

  loadPresetScenario(presetKey) {
    const form = document.getElementById('addOrderForm');
    if (!form) return;

    if (presetKey === 'scenario_high') {
      form.product_id.value = '22299';
      form.product_name.value = 'Pig Keyring With Light & Sound';
      form.category.value = 'Lighting & Candles';
      form.price.value = '1.71';
      form.market.value = 'United Kingdom';
      form.total_orders.value = '83';
      form.total_returns.value = '3';
      this.showToast('Loaded a real high-risk product from the training dataset', 'info');
    } else if (presetKey === 'scenario_low') {
      form.product_id.value = '85187';
      form.product_name.value = 'S/12 Mini Rabbit Easter';
      form.category.value = 'Christmas & Seasonal';
      form.price.value = '1.88';
      form.market.value = 'United Kingdom';
      form.total_orders.value = '71';
      form.total_returns.value = '0';
      this.showToast('Loaded a real low-risk product from the training dataset', 'info');
    } else if (presetKey === 'scenario_new') {
      form.product_id.value = '';
      form.product_name.value = 'New Ceramic Table Lamp';
      form.category.value = 'Lighting & Candles';
      form.price.value = '18.00';
      form.market.value = 'United Kingdom';
      form.total_orders.value = '0';
      form.total_returns.value = '0';
      this.showToast('Loaded a brand-new / cold-start product (no order history yet)', 'info');
    }

    this.updateLivePreview(form);
  },

  async updateLivePreview(form) {
    const data = this.serializeForm(form);
    if (!data.price) return;

    try {
      const res = await fetch('/predict-return', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      }).then(r => r.json());

      if (!res.success) return;
      const pct = Math.round(res.predicted_return_probability * 100);
      const totalOrders = res.inputs_used ? res.inputs_used.total_orders : 0;
      const histDisplay = this.formatHistoricalRate(totalOrders, res.historical_return_rate);

      const probVal = document.getElementById('previewProbValue');
      const riskBadge = document.getElementById('previewRiskBadge');
      const histRateEl = document.getElementById('previewHistoricalRate');
      const gaugeFill = document.getElementById('previewGaugeFill');
      const factorsList = document.getElementById('previewFactorsList');

      if (probVal) {
        probVal.textContent = `${pct}%`;
        probVal.className = `preview-score ${this.getRiskTextClass(res.risk_level)}`;
      }
      if (riskBadge) {
        riskBadge.textContent = `${res.risk_level} RISK`;
        riskBadge.className = `risk-badge badge-${res.risk_level.toLowerCase()}`;
      }
      if (histRateEl) histRateEl.textContent = histDisplay;
      if (gaugeFill) {
        gaugeFill.style.width = `${pct}%`;
        gaugeFill.className = `preview-gauge-bar ${this.getRiskColorClass(res.risk_level)}`;
      }
      if (factorsList) {
        factorsList.innerHTML = (res.key_factors || []).map(f => `<li>${f}</li>`).join('');
      }
    } catch (e) {
      console.error('Live preview error:', e);
    }
  },

  async submitNewProduct(form) {
    const data = this.serializeForm(form);
    const submitBtn = document.getElementById('btnSubmitAnalyze');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML = `Running AI Prediction...`;
    }

    try {
      const res = await fetch('/api/products', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      }).then(r => r.json());

      if (res.success && res.product) {
        this.showToast(`${res.product.product_name} analyzed and saved!`, 'success');
        this.navigate('order-details', res.product.product_id);
      } else {
        this.showToast(res.error || 'Failed to analyze product', 'error');
      }
    } catch (e) {
      console.error(e);
      this.showToast('Network error while saving product', 'error');
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = `Analyze Return Risk & Save Product`;
      }
    }
  },

  serializeForm(form) {
    const formData = new FormData(form);
    const obj = {};
    formData.forEach((val, key) => {
      obj[key] = val;
    });
    return obj;
  },

  async loadAnalyticsPage() {
    try {
      const res = await fetch('/api/analytics').then(r => r.json());
      if (res.success) {
        this.renderAnalyticsSummary(res.analytics);
        ChartManager.initAnalyticsCharts(res.analytics);
      }
    } catch (e) {
      console.error(e);
    }
  },

  renderAnalyticsSummary(analytics) {
    const totalElem = document.getElementById('anTotalOrders');
    const avgProbElem = document.getElementById('anAvgProb');
    const avgHistElem = document.getElementById('anAvgHistorical');
    const highRiskPctElem = document.getElementById('anHighRiskPct');
    const preventedSavingsElem = document.getElementById('anPreventedSavings');

    if (totalElem) totalElem.textContent = analytics.total_products;
    if (avgProbElem) avgProbElem.textContent = `${analytics.avg_predicted_probability}%`;
    if (avgHistElem) avgHistElem.textContent = `vs. ${analytics.avg_historical_rate}% avg. historical rate`;

    if (highRiskPctElem) {
      const pct = analytics.total_products > 0
        ? Math.round((analytics.high_risk_count / analytics.total_products) * 100)
        : 0;
      highRiskPctElem.textContent = `${pct}% of total volume`;
    }

    if (preventedSavingsElem) {
      preventedSavingsElem.textContent = `$${analytics.estimated_cost_exposure.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
    }
  },

  async loadProfile() {
    if (this.isAdmin()) return;
    try {
      const res = await fetch('/api/profile').then(r => r.json());
      if (res.success && res.profile) {
        this.state.profile = res.profile;
        this.renderSidebarPlan();
      }
    } catch (e) {
      console.error(e);
    }
  },

  async loadSettingsPage() {
    await this.loadProfile();
    const p = this.state.profile || {};

    const nameInput = document.getElementById('settingBusinessName');
    const emailInput = document.getElementById('settingBusinessEmail');
    const catInput = document.getElementById('settingBusinessCategory');
    const thresholdInput = document.getElementById('settingHighRiskThreshold');
    const thresholdVal = document.getElementById('thresholdValueDisplay');
    const shopifyToggle = document.getElementById('settingShopifyConnected');
    const wooToggle = document.getElementById('settingWooConnected');
    const emailAlertsToggle = document.getElementById('settingEmailAlerts');

    if (nameInput) nameInput.value = p.business_name || '';
    if (emailInput) emailInput.value = p.business_email || '';
    if (catInput) catInput.value = p.business_category || 'Multi-Brand Fashion & Tech';
    if (thresholdInput) {
      thresholdInput.value = p.high_risk_threshold || 70;
      if (thresholdVal) thresholdVal.textContent = `${p.high_risk_threshold || 70}%`;
      thresholdInput.oninput = () => {
        if (thresholdVal) thresholdVal.textContent = `${thresholdInput.value}%`;
      };
    }
    if (shopifyToggle) shopifyToggle.checked = !!p.shopify_connected;
    if (wooToggle) wooToggle.checked = !!p.woocommerce_connected;
    if (emailAlertsToggle) emailAlertsToggle.checked = !!p.email_alerts;
  },

  async saveSettings() {
    const data = {
      business_name: document.getElementById('settingBusinessName')?.value || '',
      business_email: document.getElementById('settingBusinessEmail')?.value || '',
      business_category: document.getElementById('settingBusinessCategory')?.value || '',
      high_risk_threshold: parseInt(document.getElementById('settingHighRiskThreshold')?.value || 70, 10),
      shopify_connected: document.getElementById('settingShopifyConnected')?.checked ? 1 : 0,
      woocommerce_connected: document.getElementById('settingWooConnected')?.checked ? 1 : 0,
      email_alerts: document.getElementById('settingEmailAlerts')?.checked ? 1 : 0,
      plan: this.state.profile?.plan || 'Growth Tier'
    };

    try {
      const res = await fetch('/api/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      }).then(r => r.json());

      if (res.success) {
        this.state.profile = res.profile;
        if (this.state.user) {
          this.state.user.business_name = res.profile.business_name;
          localStorage.setItem('returnless_user', JSON.stringify(this.state.user));
        }
        const storeElem = document.getElementById('sidebarStoreName');
        if (storeElem) storeElem.textContent = res.profile.business_name;
        this.showToast('Settings successfully updated!', 'success');
      }
    } catch (e) {
      this.showToast('Failed to save settings', 'error');
    }
  },

  async resetDemoData() {
    if (!confirm('Reset demo database back to the original real, model-scored product catalog?')) return;

    try {
      const res = await fetch('/api/reset', { method: 'POST' }).then(r => r.json());
      if (res.success) {
        this.showToast('Database reset to presentation defaults!', 'success');
        await this.loadProfile();
        this.navigate('dashboard');
      }
    } catch (e) {
      this.showToast('Error resetting database', 'error');
    }
  },

  // Switches the single login form between company sign-in (Company
  // dropdown + email) and platform-admin sign-in (email + password only).
  setLoginMode(admin) {
    this.state.adminLogin = !!admin;
    const $ = id => document.getElementById(id);
    const company = $('loginCompany');
    $('loginCompanyGroup').style.display = admin ? 'none' : '';
    company.required = !admin;
    $('loginTitle').textContent = admin ? 'Admin Portal Login' : 'Merchant Portal Login';
    $('loginSubtitle').textContent = admin ? 'Combined analysis across all companies' : 'Access your return risk intelligence workspace';
    $('loginSubmitBtn').textContent = admin ? 'Sign In to Admin Dashboard' : 'Sign In to Dashboard';
    $('loginModeToggle').textContent = admin ? '← Back to company sign in' : 'ReturnLess admin? Sign in here';
    $('registerLine').style.display = admin ? 'none' : '';
    $('loginEmail').placeholder = admin ? 'admin email' : 'e.g. operations@apexretail.com';
    $('loginEmail').value = '';
    $('loginPassword').value = admin ? '' : '••••••••••••';
    if (!admin) this.onCompanyChange();
  },

  toggleAdminLogin(e) {
    if (e) e.preventDefault();
    this.setLoginMode(!this.state.adminLogin);
  },

  // Selecting a company hints which work email belongs to it.
  onCompanyChange() {
    const id = document.getElementById('loginCompany').value;
    const acc = (this.state.companies || []).find(c => String(c.id) === String(id));
    document.getElementById('loginEmail').placeholder = acc ? acc.business_email : 'e.g. operations@apexretail.com';
  },

  async handleLogin(e) {
    e.preventDefault();
    const email = document.getElementById('loginEmail').value;

    if (this.state.adminLogin) {
      try {
        const res = await fetch('/api/auth/admin-login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password: document.getElementById('loginPassword').value })
        }).then(r => r.json());
        if (res.success) {
          this.state.user = res.admin;
          localStorage.setItem('returnless_user', JSON.stringify(res.admin));
          sessionStorage.setItem('returnless_active_session', '1');
          this.showToast('Welcome, ReturnLess Admin', 'success');
          this.navigate('admin');
        } else {
          this.showToast(res.error || 'Admin login failed', 'error');
        }
      } catch (err) {
        this.showToast('Admin login failed', 'error');
      }
      return;
    }

    const companyId = document.getElementById('loginCompany').value;
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, company_id: companyId })
      }).then(r => r.json());

      if (res.success) {
        this.state.user = res.merchant;
        localStorage.setItem('returnless_user', JSON.stringify(res.merchant));
        sessionStorage.setItem('returnless_active_session', '1');
        this.showToast(`Welcome back, ${res.merchant.business_name}!`, 'success');
        this.navigate('dashboard');
      } else {
        this.showToast(res.error || 'Login failed', 'error');
      }
    } catch (err) {
      this.showToast('Login failed', 'error');
    }
  },

  // Fills the Company dropdown from the real companies in the database.
  async loadDemoAccounts() {
    const select = document.getElementById('loginCompany');
    if (!select) return;
    try {
      const res = await fetch('/api/auth/demo-accounts').then(r => r.json());
      if (!res.success || !res.accounts) return;
      this.state.companies = res.accounts;
      const current = select.value;
      select.innerHTML = '<option value="" disabled selected>Select Company</option>' +
        res.accounts.map(a => `<option value="${a.id}">${this.esc(a.business_name)}</option>`).join('');
      if (current) select.value = current;
    } catch (e) {
      console.error('Could not load companies:', e);
    }
  },

  esc(v) {
    return String(v ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  },

  // ---------------- Admin dashboard (combined, all companies) ----------------
  formatUsd(n) {
    return `$${Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  },

  async loadAdminDashboard() {
    try {
      const res = await fetch('/api/admin/overview').then(async r => ({ status: r.status, body: await r.json() }));
      if (res.status === 401) {
        this.showToast('Admin session expired - please sign in again', 'error');
        this.logout();
        return;
      }
      if (!res.body.success) throw new Error(res.body.error || 'Failed to load');
      this.state.admin = res.body;
      this.renderAdminDashboard(res.body);
    } catch (err) {
      console.error('Error loading admin dashboard:', err);
      this.showToast('Could not load admin dashboard', 'error');
    }
  },

  renderAdminDashboard({ overall, companies }) {
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    const share = overall.total_products ? Math.round(overall.high_risk_count / overall.total_products * 100) : 0;
    set('adTotalProducts', overall.total_products);
    set('adCompanyCount', `Across ${overall.total_companies} companies`);
    set('adHighRisk', overall.high_risk_count);
    set('adHighRiskShare', `${share}% of all products`);
    set('adAvgProb', `${overall.avg_predicted_probability}%`);
    set('adAvgHist', `vs. ${overall.avg_historical_rate}% avg. historical rate`);
    set('adExposure', this.formatUsd(overall.estimated_cost_exposure));

    ChartManager.renderRiskDistribution(overall.risk_distribution, 'adRiskChart', 'adRisk');
    ChartManager.renderCategoryComparison(
      companies.map(c => ({ category: c.business_name, avg_historical: c.analytics.avg_historical_rate, avg_predicted: c.analytics.avg_predicted_probability })),
      'adCompanyChart', 'adCompanies'
    );

    document.getElementById('adCompaniesBody').innerHTML = companies.map(c => {
      const a = c.analytics;
      return `<tr>
        <td><div class="product-cell"><span class="product-name">${this.esc(c.business_name)}</span>
          <span class="text-muted" style="font-size:11px;">${this.esc(c.business_category)}</span></div></td>
        <td>${this.esc(c.plan)}</td>
        <td class="font-semibold">${a.total_products}</td>
        <td><span class="risk-badge badge-high">${a.high_risk_count}</span></td>
        <td><span class="risk-badge badge-medium">${a.medium_risk_count}</span></td>
        <td><span class="risk-badge badge-low">${a.low_risk_count}</span></td>
        <td>${a.avg_historical_rate}%</td>
        <td class="font-bold">${a.avg_predicted_probability}%</td>
        <td>${this.formatUsd(a.estimated_cost_exposure)}</td>
      </tr>`;
    }).join('');

    document.getElementById('adCompanyTabs').innerHTML = companies.map(c =>
      `<button type="button" class="admin-tab" data-company="${c.id}" onclick="App.selectAdminCompany(${c.id})">${this.esc(c.business_name)}</button>`
    ).join('');
    const keep = this.state.adminCompanyId && companies.some(c => c.id === this.state.adminCompanyId);
    if (keep || companies.length) this.selectAdminCompany(keep ? this.state.adminCompanyId : companies[0].id);
  },

  selectAdminCompany(id) {
    const c = ((this.state.admin || {}).companies || []).find(x => x.id === id);
    if (!c) return;
    this.state.adminCompanyId = id;
    document.querySelectorAll('.admin-tab').forEach(t => t.classList.toggle('active', Number(t.dataset.company) === id));
    const a = c.analytics;
    const rows = a.top_risk_products.length ? a.top_risk_products.map(p => `<tr>
        <td><div class="product-cell"><span class="product-name">${this.esc(p.product_name)}</span>
          <span class="text-muted" style="font-size:11px;">${this.esc(p.product_id)}</span></div></td>
        <td>${this.esc(p.category)}</td>
        <td class="font-bold">${p.predicted_return_probability}%</td>
        <td><span class="risk-badge badge-${p.risk_level.toLowerCase()}">${p.risk_level}</span></td>
      </tr>`).join('') : '<tr><td colspan="4" class="text-center py-4 text-muted">No products yet.</td></tr>';

    document.getElementById('adCompanyDetail').innerHTML = `
      <div class="admin-detail-meta">${this.esc(c.business_category)} · ${this.esc(c.plan)} · ${a.total_products} products ·
        ${a.high_risk_count} high / ${a.medium_risk_count} medium / ${a.low_risk_count} low risk ·
        avg. AI predicted ${a.avg_predicted_probability}% (historical ${a.avg_historical_rate}%) ·
        est. cost exposure ${this.formatUsd(a.estimated_cost_exposure)}</div>
      <div class="charts-grid" style="margin-bottom:0;">
        <div><div class="chart-container"><canvas id="adCategoryChart"></canvas></div></div>
        <div class="table-responsive">
          <table class="data-table">
            <thead><tr><th>Highest-Risk Products</th><th>Category</th><th>AI Predicted</th><th>Tier</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>`;
    ChartManager.renderCategoryComparison(a.category_breakdown, 'adCategoryChart', 'adCategory');
  },

  async handleRegister(e) {
    e.preventDefault();
    const name = document.getElementById('regBusinessName').value;
    const email = document.getElementById('regBusinessEmail').value;
    const category = document.getElementById('regBusinessCategory').value;

    try {
      const res = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ business_name: name, business_email: email, business_category: category })
      }).then(r => r.json());

      if (res.success) {
        this.state.user = res.merchant;
        localStorage.setItem('returnless_user', JSON.stringify(res.merchant));
        sessionStorage.setItem('returnless_active_session', '1');
        this.showToast(`Merchant workspace initialized for ${res.merchant.business_name}!`, 'success');
        this.navigate('dashboard');
      } else {
        this.showToast(res.error || 'Registration failed', 'error');
      }
    } catch (e) {
      this.showToast('Registration failed', 'error');
    }
  },

  // Scrolls to a section on the landing page (How It Works / Value Proposition)
  async goToSection(sectionId) {
    if (this.state.currentView !== 'landing') {
      await this.navigate('landing');
    }
    const el = document.getElementById(sectionId);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  },

  logout() {
    // Remember who was signed in so the logout page can show it
    const lastName = this.state.user && this.state.user.business_name;
    localStorage.removeItem('returnless_user');
    sessionStorage.removeItem('returnless_active_session');
    this.state.user = null;
    this.state.lastBusinessName = lastName || null;
    this.navigate('logout');
  },

  renderLogoutPage() {
    const nameEl = document.getElementById('logoutBusinessName');
    const timeEl = document.getElementById('logoutTime');
    if (nameEl) nameEl.textContent = this.state.lastBusinessName || 'Merchant workspace';
    if (timeEl) timeEl.textContent = new Date().toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  },

  setBillingCycle(cycle) {
    this.state.billingCycle = cycle;
    document.getElementById('btnBillingMonthly')?.classList.toggle('active', cycle === 'monthly');
    document.getElementById('btnBillingAnnual')?.classList.toggle('active', cycle === 'annual');

    const starterPrice = document.getElementById('priceStarter');
    const growthPrice = document.getElementById('priceGrowth');
    const enterprisePrice = document.getElementById('priceEnterprise');

    if (cycle === 'annual') {
      if (starterPrice) starterPrice.innerHTML = '$79 <span>/mo (billed annually)</span>';
      if (growthPrice) growthPrice.innerHTML = '$239 <span>/mo (billed annually)</span>';
      if (enterprisePrice) enterprisePrice.innerHTML = '$699 <span>/mo (billed annually)</span>';
    } else {
      if (starterPrice) starterPrice.innerHTML = '$99 <span>/mo</span>';
      if (growthPrice) growthPrice.innerHTML = '$299 <span>/mo</span>';
      if (enterprisePrice) enterprisePrice.innerHTML = '$799 <span>/mo</span>';
    }
  },

  /* =============================================================
     PAYMENTS (Razorpay)
     Flow: create order (server) -> checkout -> verify signature (server)
     mode 'razorpay': real Razorpay Checkout (test or live keys)
     mode 'mock'    : simulated checkout, same server-side flow, no account needed
     ============================================================= */

  async loadPaymentConfig() {
    if (!this.state.paymentConfig) {
      this.state.paymentConfig = await fetch('/api/payment/config').then(r => r.json());
    }
    return this.state.paymentConfig;
  },

  normalizePlan(plan) {
    // Older saved data may say "Growth Tier Plan"; the canonical name has no suffix.
    return (plan || '').replace(/\s+Plan$/, '').trim();
  },

  formatMoney(minorUnits, currency) {
    const locale = currency === 'INR' ? 'en-IN' : 'en-US';
    return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(minorUnits / 100);
  },

  async loadPlansPage() {
    try {
      const [cfg] = await Promise.all([this.loadPaymentConfig(), this.loadProfile()]);
      const note = document.getElementById('paymentModeNote');
      if (note && cfg) {
        note.textContent = cfg.mode === 'mock'
          ? 'Payments run through a simulated Razorpay test checkout. No real money is charged.'
          : (cfg.test_keys ? 'Payments run in Razorpay test mode.' : 'Payments are processed by Razorpay.');
      }
      this.renderPlanButtons();
      await this.loadBillingHistory();
    } catch (e) {
      console.error(e);
    }
  },

  renderSidebarPlan() {
    if (this.isAdmin()) return;
    const el = document.getElementById('sidebarPlanName');
    const plan = this.normalizePlan(this.state.profile?.plan);
    if (el && plan) el.textContent = plan;
  },

  renderPlanButtons() {
    const current = this.normalizePlan(this.state.profile?.plan);
    const labels = { 'Starter SME': 'Select Starter Tier', 'Growth Tier': 'Select Growth Tier', 'Enterprise Tier': 'Upgrade to Enterprise' };
    document.querySelectorAll('[data-plan-btn]').forEach(btn => {
      const plan = btn.getAttribute('data-plan-btn');
      const isCurrent = plan === current;
      btn.disabled = isCurrent;
      btn.textContent = isCurrent ? 'Current plan' : labels[plan];
    });
  },

  async loadBillingHistory() {
    const body = document.getElementById('billingHistoryBody');
    if (!body) return;
    try {
      const res = await fetch('/api/payment/history').then(r => r.json());
      const rows = res.payments || [];
      if (!rows.length) {
        body.innerHTML = `<tr><td colspan="6" class="text-muted" style="text-align:center; padding:28px;">No payments yet. Choose a plan above to make your first payment.</td></tr>`;
        return;
      }
      const badge = {
        paid: ['badge-low', 'Paid'],
        failed: ['badge-high', 'Failed'],
        created: ['badge-medium', 'Not completed']
      };
      body.innerHTML = rows.map(p => {
        const [cls, label] = badge[p.status] || badge.created;
        return `
          <tr>
            <td>${p.created_at}</td>
            <td>${p.plan}</td>
            <td>${p.cycle === 'annual' ? 'Annual' : 'Monthly'}</td>
            <td>${this.formatMoney(p.amount, p.currency)}</td>
            <td><span class="risk-badge ${cls}">${label}</span></td>
            <td class="pay-ref">${p.rz_payment_id || p.rz_order_id}</td>
          </tr>`;
      }).join('');
    } catch (e) {
      console.error(e);
    }
  },

  async selectPlan(tierName) {
    if (this.state.paying) return;
    this.state.paying = true;
    try {
      const order = await fetch('/api/payment/create-order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan: tierName, cycle: this.state.billingCycle })
      }).then(r => r.json());

      if (!order.success) {
        this.state.paying = false;
        this.showToast(order.error || 'Could not start the payment', 'error');
        return;
      }
      if (order.mode === 'mock') {
        this.openMockCheckout(order);
      } else {
        await this.openRazorpayCheckout(order);
      }
    } catch (e) {
      console.error(e);
      this.state.paying = false;
      this.showToast('Could not start the payment. Is the server running?', 'error');
    }
  },

  // Sends what Checkout returned to the server. The plan is only activated
  // after the server has verified the Razorpay signature.
  async confirmPayment(rz, order) {
    try {
      const res = await fetch('/api/payment/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          razorpay_order_id: rz.razorpay_order_id,
          razorpay_payment_id: rz.razorpay_payment_id,
          razorpay_signature: rz.razorpay_signature
        })
      }).then(r => r.json());
      if (!res.success) throw new Error(res.error || 'Payment could not be verified');

      this.state.profile = res.profile;
      if (this.state.user) {
        this.state.user.plan = res.profile.plan;
        localStorage.setItem('returnless_user', JSON.stringify(this.state.user));
      }
      this.showToast(`Payment received. You are now on the ${order.plan} plan.`, 'success');
      this.renderSidebarPlan();
      this.renderPlanButtons();
      await this.loadBillingHistory();
      return true;
    } catch (e) {
      this.showToast(e.message || 'Payment could not be verified', 'error');
      await this.loadBillingHistory();
      return false;
    }
  },

  loadScript(src) {
    return new Promise((resolve, reject) => {
      if (window.Razorpay) return resolve();
      const tag = document.createElement('script');
      tag.src = src;
      tag.onload = resolve;
      tag.onerror = () => reject(new Error('Could not load Razorpay Checkout. Check your internet connection.'));
      document.head.appendChild(tag);
    });
  },

  async openRazorpayCheckout(order) {
    try {
      await this.loadScript('https://checkout.razorpay.com/v1/checkout.js');
    } catch (e) {
      this.state.paying = false;
      this.showToast(e.message, 'error');
      return;
    }
    const p = this.state.profile || {};
    const rzp = new Razorpay({
      key: order.key_id,
      amount: order.amount,
      currency: order.currency,
      order_id: order.order_id,
      name: 'ReturnLess',
      description: `${order.plan}, ${order.cycle === 'annual' ? 'annual' : 'monthly'} billing`,
      prefill: { name: p.business_name || '', email: p.business_email || '' },
      theme: { color: '#5A0F1B' },
      handler: async (rz) => {
        await this.confirmPayment(rz, order);
        this.state.paying = false;
      },
      modal: { ondismiss: () => { this.state.paying = false; } }
    });
    rzp.on('payment.failed', (resp) => {
      const reason = resp?.error?.description || 'Payment failed';
      this.showToast(reason, 'error');
      fetch('/api/payment/failed', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ razorpay_order_id: order.order_id, reason })
      }).then(() => this.loadBillingHistory()).catch(() => {});
    });
    rzp.open();
  },

  /* ---------- Simulated Razorpay checkout (mock mode) ---------- */

  openMockCheckout(order) {
    this.closeMockCheckout();
    const cycle = order.cycle === 'annual' ? 'billed annually' : 'billed monthly';
    const overlay = document.createElement('div');
    overlay.id = 'payOverlay';
    overlay.className = 'pay-overlay';
    overlay.innerHTML = `
      <div class="pay-modal" role="dialog" aria-modal="true" aria-labelledby="payTitle">
        <div class="pay-head">
          <div>
            <div class="pay-merchant" id="payTitle">ReturnLess</div>
            <div class="pay-sub">${order.plan} plan, ${cycle}</div>
          </div>
          <button class="pay-close" type="button" aria-label="Close checkout" data-pay-close>&times;</button>
        </div>
        <div class="pay-simnote">Simulated Razorpay test checkout. No real money is charged.</div>
        <div class="pay-body" id="payBody"></div>
      </div>`;
    document.body.appendChild(overlay);

    overlay.addEventListener('click', (e) => {
      if (e.target === overlay || e.target.closest('[data-pay-close]')) {
        if (!this.state.payBusy) this.closeMockCheckout();
      }
    });
    this._payKeydown = (e) => {
      if (e.key === 'Escape' && !this.state.payBusy) this.closeMockCheckout();
    };
    document.addEventListener('keydown', this._payKeydown);

    this.renderMockForm(order);
  },

  closeMockCheckout() {
    const overlay = document.getElementById('payOverlay');
    if (overlay) overlay.remove();
    if (this._payKeydown) {
      document.removeEventListener('keydown', this._payKeydown);
      this._payKeydown = null;
    }
    this.state.payBusy = false;
    this.state.paying = false;
  },

  renderMockForm(order) {
    const body = document.getElementById('payBody');
    if (!body) return;
    const amount = this.formatMoney(order.amount, order.currency);
    const businessName = this.state.profile?.business_name || '';
    body.innerHTML = `
      <div class="pay-amount-label">Amount payable</div>
      <div class="pay-amount">${amount}</div>
      <div class="pay-order">Order ${order.order_id}</div>

      <div class="pay-tabs" role="tablist" aria-label="Payment method">
        <button class="pay-tab" role="tab" type="button" aria-selected="true" data-pay-tab="upi">UPI</button>
        <button class="pay-tab" role="tab" type="button" aria-selected="false" data-pay-tab="card">Card</button>
        <button class="pay-tab" role="tab" type="button" aria-selected="false" data-pay-tab="netbanking">Netbanking</button>
      </div>

      <div class="pay-panel" data-pay-panel="upi">
        <div class="form-group">
          <label for="payUpi">UPI ID</label>
          <input id="payUpi" class="form-control" type="text" value="success@razorpay" autocomplete="off">
        </div>
      </div>
      <div class="pay-panel" data-pay-panel="card" hidden>
        <div class="form-group">
          <label for="payCardNumber">Card number</label>
          <input id="payCardNumber" class="form-control" type="text" value="4111 1111 1111 1111" autocomplete="off">
        </div>
        <div class="form-group">
          <label for="payCardName">Name on card</label>
          <input id="payCardName" class="form-control" type="text" autocomplete="off">
        </div>
        <div class="pay-row-2">
          <div class="form-group">
            <label for="payCardExpiry">Expiry</label>
            <input id="payCardExpiry" class="form-control" type="text" value="12 / 30" autocomplete="off">
          </div>
          <div class="form-group">
            <label for="payCardCvv">CVV</label>
            <input id="payCardCvv" class="form-control" type="password" value="123" autocomplete="off">
          </div>
        </div>
      </div>
      <div class="pay-panel" data-pay-panel="netbanking" hidden>
        <div class="form-group">
          <label for="payBank">Choose your bank</label>
          <select id="payBank" class="form-control">
            <option>HDFC Bank</option>
            <option>State Bank of India</option>
            <option>ICICI Bank</option>
            <option>Axis Bank</option>
          </select>
        </div>
      </div>

      <div class="pay-actions">
        <button class="btn btn-primary btn-lg" type="button" id="payNowBtn">Pay ${amount}</button>
        <button class="pay-link-btn" type="button" id="payFailBtn">Simulate a failed payment</button>
      </div>`;

    const nameInput = body.querySelector('#payCardName');
    if (nameInput) nameInput.value = businessName;

    body.querySelectorAll('[data-pay-tab]').forEach(tab => {
      tab.addEventListener('click', () => {
        const target = tab.getAttribute('data-pay-tab');
        body.querySelectorAll('[data-pay-tab]').forEach(t => t.setAttribute('aria-selected', String(t === tab)));
        body.querySelectorAll('[data-pay-panel]').forEach(panel => {
          panel.hidden = panel.getAttribute('data-pay-panel') !== target;
        });
      });
    });

    body.querySelector('#payNowBtn').addEventListener('click', () => this.mockPay(order, 'success'));
    body.querySelector('#payFailBtn').addEventListener('click', () => this.mockPay(order, 'failure'));
    body.querySelector('#payNowBtn').focus();
  },

  renderMockState(kind, title, text, actionsHtml = '') {
    const body = document.getElementById('payBody');
    if (!body) return;
    const icon = kind === 'processing'
      ? '<div class="pay-spinner" aria-hidden="true"></div>'
      : `<div class="pay-icon ${kind === 'success' ? 'pay-icon-ok' : 'pay-icon-bad'}" aria-hidden="true">${kind === 'success' ? '&#10003;' : '&times;'}</div>`;
    body.innerHTML = `
      <div class="pay-state" role="status" aria-live="polite">
        ${icon}
        <div class="pay-state-title">${title}</div>
        <div class="pay-state-text">${text}</div>
        ${actionsHtml}
      </div>`;
  },

  async mockPay(order, outcome) {
    if (this.state.payBusy) return;
    this.state.payBusy = true;
    this.renderMockState('processing', 'Processing payment', 'Waiting for the bank to confirm...');
    await new Promise(resolve => setTimeout(resolve, 1200));

    try {
      // Stands in for the customer paying inside Razorpay Checkout.
      const auth = await fetch('/api/payment/mock-authorize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ razorpay_order_id: order.order_id, outcome })
      }).then(r => r.json());

      if (!auth.success) {
        await this.loadBillingHistory();
        this.showMockFailure(order, auth.error || 'The payment did not go through.');
        return;
      }

      // From here on it is identical to the real Razorpay handler.
      const ok = await this.confirmPayment(auth, order);
      if (ok) {
        this.renderMockState('success', 'Payment successful', `Reference ${auth.razorpay_payment_id}`);
        this.state.payBusy = false;
        setTimeout(() => this.closeMockCheckout(), 1800);
      } else {
        this.showMockFailure(order, 'The payment could not be verified. Please try again.');
      }
    } catch (e) {
      console.error(e);
      this.showMockFailure(order, 'Could not reach the server.');
    }
  },

  showMockFailure(order, message) {
    this.state.payBusy = false;
    this.renderMockState('failed', 'Payment failed', message, `
      <div class="pay-actions">
        <button class="btn btn-primary" type="button" id="payRetryBtn">Try again</button>
        <button class="pay-link-btn" type="button" data-pay-close>Close</button>
      </div>`);
    const retry = document.getElementById('payRetryBtn');
    if (retry) {
      retry.addEventListener('click', () => this.renderMockForm(order));
      retry.focus();
    }
  },

  getRiskColorClass(risk) {
    if (risk === 'HIGH') return 'color-high';
    if (risk === 'MEDIUM') return 'color-medium';
    return 'color-low';
  },

  getRiskTextClass(risk) {
    if (risk === 'HIGH') return 'text-danger';
    if (risk === 'MEDIUM') return 'text-warning';
    return 'text-success';
  },

  // A product with zero orders has no real historical rate to show - "0%"
  // reads as "measured and returns nothing," which the AI prediction can
  // then look like it's contradicting. Show the actual state instead.
  formatHistoricalRate(totalOrders, historicalRate) {
    if (!totalOrders || totalOrders <= 0) return 'No orders yet';
    return `${Math.round(historicalRate * 100)}%`;
  },

  showToast(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
      <div class="toast-content">${message}</div>
      <button class="toast-close" onclick="this.parentElement.remove()">×</button>
    `;

    container.appendChild(toast);
    setTimeout(() => {
      if (toast.parentElement) toast.remove();
    }, 4500);
  }
};

// Every API/prediction call is tagged with the logged-in company's
// merchant_id (X-Merchant-Id header), so each company only ever sees its
// own products, analytics, profile and payments. Wrapping fetch once here
// covers every existing call site above without editing each one.
(function attachMerchantHeader() {
  const originalFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (url.startsWith('/api/') || url.startsWith('/predict-return')) {
      const merchantId = (App.state.user && App.state.user.merchant_id) || 1;
      const extra = { 'X-Merchant-Id': String(merchantId) };
      if (App.state.user && App.state.user.admin_token) extra['X-Admin-Token'] = App.state.user.admin_token;
      init = Object.assign({}, init, {
        headers: Object.assign({}, init.headers || {}, extra)
      });
    }
    return originalFetch(input, init);
  };
})();

document.addEventListener('DOMContentLoaded', () => {
  App.init();
});
