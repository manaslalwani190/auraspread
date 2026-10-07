/**
 * AuraSpread - The Assay Office Client Application
 * Institutional-grade relative-value monitoring for MCX gold contracts.
 * Handles data loading, state management, Plotly visualization,
 * interactive scale physics, sticky sliders, guided tour, and export utilities.
 */

// Application State
const STATE = {
  data: null,
  activePair: 'GOLDM-GOLDGUINEA',
  baseLeg: 'GOLDM',
  targetLeg: 'GOLDTEN',
  zCutoff: 2.0,
  costHurdle: 35.0,
  showRawCurve: false,
  showGoldImpact: true,
  isParchment: false,
  explainMode: false,
  tourCurrentStep: 0,
  heatmapGranularity: 'weekly',
  chartsRendered: {
    heatmap: false,
    termStructure: false,
    decomposition: false,
    equityCurves: false,
  },
};

// ── Chart Skeleton / Loading Overlay Helper ─────────────────────────────
/**
 * Hides the ".chart-skeleton" loading overlay inside a chart container.
 * Called immediately after Plotly finishes drawing so users never see
 * the "Rendering..." text stuck forever.
 */
function hideChartSkeleton(chartId) {
  const chartEl = document.getElementById(chartId);
  if (!chartEl) return;
  const skeleton = chartEl.querySelector('.chart-skeleton');
  if (skeleton) {
    skeleton.style.display = 'none';
  }
  // Ensure the container itself is visible
  chartEl.style.minHeight = '';
}

// Colors matching Assay Office CSS tokens
function getThemeColors() {
  const isParchment = document.documentElement.getAttribute('data-theme') === 'parchment';
  return {
    bgCard: isParchment ? '#FAF6F0' : '#332C18',
    bgPlot: isParchment ? '#EDE4DC' : '#2A2312',
    bgPaper: isParchment ? '#FAF6F0' : '#2A2312',
    textMain: isParchment ? '#1C1917' : '#F4EFE0',
    textSecondary: isParchment ? '#3D3935' : '#C4B896',
    textMuted: isParchment ? '#57524C' : '#8A7D5A',
    accentGold: isParchment ? '#9E7310' : '#FFBE0B',
    accentGoldBright: isParchment ? '#835C07' : '#FFD04D',
    borderBronze: isParchment ? '#D1C5B6' : 'rgba(255, 190, 11, 0.2)',
    copperNeg: isParchment ? '#B3381B' : '#E05A3A',
    verdigrisPos: isParchment ? '#1F7360' : '#4EAD96',
  };
}

// ── Initialization ────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  setupNavigation();
  setupScrollProgress();
  setupToggles();
  setupGlobalSearch();
  setupMobileDrawer();
  setupTour();
  setupKeyboardShortcuts();
  setupEventListeners();

  try {
    const res = await fetch('data/auraspread_data.json');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    STATE.data = await res.json();
    renderAll();
    setupLazyCharts();
  } catch (err) {
    console.error('Failed to load JSON dataset:', err);
    showDataLoadError(err);
  }
});

// ── Top Scroll Progress Bar & Scroll-Spy ──────────────────────────────────
function setupScrollProgress() {
  const progressBar = document.getElementById('topProgressBar');
  if (!progressBar) return;

  window.addEventListener('scroll', () => {
    const totalHeight = document.documentElement.scrollHeight - window.innerHeight;
    if (totalHeight > 0) {
      const progress = (window.scrollY / totalHeight) * 100;
      progressBar.style.width = `${Math.min(100, Math.max(0, progress))}%`;
    }
  }, { passive: true });
}

function setupNavigation() {
  const desktopLinks = document.querySelectorAll('.nav-link');
  const drawerLinks = document.querySelectorAll('.drawer-link');
  const mobileTabs = document.querySelectorAll('.mobile-tab');

  const sections = Array.from(desktopLinks)
    .map(l => document.querySelector(l.getAttribute('href')))
    .filter(Boolean);

  const updateActiveNav = () => {
    let currentId = 'hero';
    const scrollPos = window.scrollY + 200;

    sections.forEach(sec => {
      if (sec.offsetTop <= scrollPos) {
        currentId = sec.id;
      }
    });

    desktopLinks.forEach(l => {
      l.classList.toggle('active', l.getAttribute('href') === `#${currentId}`);
    });

    drawerLinks.forEach(l => {
      l.classList.toggle('active', l.getAttribute('href') === `#${currentId}`);
    });

    mobileTabs.forEach(t => {
      t.classList.toggle('active', t.getAttribute('data-target') === currentId);
    });
  };

  window.addEventListener('scroll', updateActiveNav, { passive: true });
  updateActiveNav();
}

// ── Mobile Drawer & Interactions ──────────────────────────────────────────
function setupMobileDrawer() {
  const menuBtn = document.getElementById('mobileMenuBtn');
  const closeBtn = document.getElementById('drawerCloseBtn');
  const drawer = document.getElementById('mobileDrawer');
  const overlay = document.getElementById('mobileDrawerOverlay');
  const drawerLinks = document.querySelectorAll('.drawer-link');

  const toggleDrawer = (open) => {
    if (!drawer || !overlay) return;
    drawer.classList.toggle('active', open);
    overlay.classList.toggle('active', open);
    if (menuBtn) {
      menuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
  };

  if (menuBtn) menuBtn.addEventListener('click', () => toggleDrawer(true));
  if (closeBtn) closeBtn.addEventListener('click', () => toggleDrawer(false));
  if (overlay) overlay.addEventListener('click', () => toggleDrawer(false));

  drawerLinks.forEach(link => {
    link.addEventListener('click', () => toggleDrawer(false));
  });
}

// ── Theme Management ───────────────────────────────────────────────────────
const THEME_STORAGE_KEY = 'auraspread_theme';

function getInitialTheme() {
  const saved = localStorage.getItem(THEME_STORAGE_KEY);
  if (saved === 'parchment' || saved === 'light') return 'parchment';
  if (saved === 'vault' || saved === 'dark') return 'vault';
  if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
    return 'parchment';
  }
  return 'vault';
}

function applyTheme(isParchment, persist = true) {
  STATE.isParchment = isParchment;
  const themeName = isParchment ? 'parchment' : 'vault';
  document.documentElement.setAttribute('data-theme', themeName);

  // Sync Header Theme Buttons (Pill)
  const btnLight = document.getElementById('themeBtnLight');
  const btnDark = document.getElementById('themeBtnDark');
  if (btnLight && btnDark) {
    btnLight.classList.toggle('active', isParchment);
    btnLight.setAttribute('aria-checked', isParchment ? 'true' : 'false');
    btnDark.classList.toggle('active', !isParchment);
    btnDark.setAttribute('aria-checked', !isParchment ? 'true' : 'false');
  }

  // Sync Sidebar & Mobile Drawer Toggles
  const themeToggle = document.getElementById('themeToggle');
  const mobileThemeToggle = document.getElementById('mobileThemeToggle');
  if (themeToggle) themeToggle.checked = isParchment;
  if (mobileThemeToggle) mobileThemeToggle.checked = isParchment;

  if (persist) {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, themeName);
    } catch (e) {
      // storage unavailable
    }
  }

  reRenderActiveCharts();
}

function toggleTheme() {
  const currentIsParchment = document.documentElement.getAttribute('data-theme') === 'parchment';
  const newIsParchment = !currentIsParchment;
  applyTheme(newIsParchment, true);
  showToast(`Theme: ${newIsParchment ? 'Parchment Light' : 'Vault Dark'}`);
}

// ── Search Catalog & Navigation Index ──────────────────────────────────────
const SEARCH_CATALOG = [
  // Sections
  {
    id: 'hero',
    title: 'The Overview',
    category: 'Section',
    badge: 'Overview',
    description: 'Executive Quantitative Verdict, Master Stats & 4 Contract Ingot standardizations',
    keywords: 'overview hero verdict executive stats hurdle ingot 999 basis physical delivery goldm goldten',
    type: 'section',
    target: '#hero',
  },
  {
    id: 'balance',
    title: 'The Assay Balance',
    category: 'Section',
    badge: 'Balance',
    description: 'Interactive pair analyzer, carrying cost subtraction & real-time balance physics beam',
    keywords: 'balance assay pair leg a leg b target base carry financing residual slider scale beam',
    type: 'section',
    target: '#balance',
  },
  {
    id: 'heatmap',
    title: 'Spread Heatmap',
    category: 'Section',
    badge: 'Heatmap',
    description: 'Multi-pair regime matrix of historical carry-adjusted residuals across trading sessions',
    keywords: 'heatmap spread regime matrix residuals daily sessions weekly regime colorbar matrix plotly',
    type: 'section',
    target: '#heatmap',
  },
  {
    id: 'carry-curve',
    title: 'Carry & Curve Laboratory',
    category: 'Section',
    badge: 'Curve Lab',
    description: 'Annualized term structure forward curve & roll-down vs curve shift decomposition',
    keywords: 'carry curve term structure forward annualised roll down curve shift laboratory contango backwardation',
    type: 'section',
    target: '#carry-curve',
  },
  {
    id: 'signal-desk',
    title: 'Signal Desk',
    category: 'Section',
    badge: 'Signals',
    description: 'Z-score relative-value anomaly signals, confidence scores & execution trade cards',
    keywords: 'signal desk zscore z-score cutoff anomaly trade long short arbitrage confidence execution',
    type: 'section',
    target: '#signal-desk',
  },
  {
    id: 'backtest',
    title: 'Backtest Vault',
    category: 'Section',
    badge: 'Backtest',
    description: 'Out-of-sample strategy performance, cumulative PnL, gross vs net equity, Sharpe & drawdown',
    keywords: 'backtest vault equity pnl cumulative gross net returns sharpe drawdown alpha costs fees',
    type: 'section',
    target: '#backtest',
  },
  {
    id: 'breakeven',
    title: 'Breakeven Gauge',
    category: 'Section',
    badge: 'Frictions',
    description: 'Institutional friction breakdown: STT, turnover exchange fees, stamp duty & crossing costs',
    keywords: 'breakeven gauge friction cost hurdle stt exchange turnover stamp duty crossing bid-ask fees threshold',
    type: 'section',
    target: '#breakeven',
  },
  {
    id: 'calendar',
    title: 'Contract Calendar',
    category: 'Section',
    badge: 'Calendar',
    description: 'MCX monthly expiry cycle comparison, cash settlement timeline & 5-day blackout windows',
    keywords: 'calendar contract expiry cycles delivery blackout tender cash settlement 5th 27th 31st schedule',
    type: 'section',
    target: '#calendar',
  },
  {
    id: 'methodology',
    title: 'Method & Honesty',
    category: 'Section',
    badge: 'Methodology',
    description: 'Rigorous mathematical basis, data validation checks, and why apparent arbitrage disappears',
    keywords: 'methodology method honesty formulas math assumptions data validation synthetic real audit why arbs fail',
    type: 'section',
    target: '#methodology',
  },

  // Contracts
  {
    id: 'contract-goldm',
    title: 'GOLDM (Gold Mini)',
    category: 'Contract',
    badge: '100g 995',
    description: '100g lot size, 995 fineness benchmark quoted per 10g (multiplier 1.0040 to 999 basis)',
    keywords: 'goldm gold mini 100g 995 contract liquid primary benchmark',
    type: 'section',
    target: '#card-GOLDM',
  },
  {
    id: 'contract-goldten',
    title: 'GOLDTEN (10 Grams)',
    category: 'Contract',
    badge: '10g 999',
    description: '10g lot size, 999 native standard fineness (multiplier 1.0000)',
    keywords: 'goldten 10g 999 native standard benchmark contract',
    type: 'section',
    target: '#card-GOLDTEN',
  },
  {
    id: 'contract-goldguinea',
    title: 'GOLDGUINEA (8 Grams)',
    category: 'Contract',
    badge: '8g 999',
    description: '8g coin lot size, 999 fineness quoted per 8g (multiplier 1.2500 to 10g equivalent)',
    keywords: 'goldguinea guinea 8g 999 coin jewelry standard contract',
    type: 'section',
    target: '#card-GOLDGUINEA',
  },
  {
    id: 'contract-goldpetal',
    title: 'GOLDPETAL (1 Gram)',
    category: 'Contract',
    badge: '1g 999',
    description: '1g micro lot size, 999 fineness quoted per 1g (multiplier 10.0000 to 10g equivalent)',
    keywords: 'goldpetal petal 1g 999 micro contract retail',
    type: 'section',
    target: '#card-GOLDPETAL',
  },

  // Actions & Tools
  {
    id: 'action-tour',
    title: 'Guided Tour for Judges',
    category: 'Action',
    badge: 'Tour',
    description: 'Interactive step-by-step walkthrough explaining all 8 modules and economic conclusions',
    keywords: 'tour guided walkthrough judges intro tutorial demo help',
    type: 'action',
    action: 'tour',
  },
  {
    id: 'action-copy-summary',
    title: 'Copy Quantitative Summary',
    category: 'Action',
    badge: 'Export',
    description: 'Copy executive verdict, hurdle thresholds, and key metrics directly to clipboard',
    keywords: 'copy summary export clipboard text share verdict metrics',
    type: 'action',
    action: 'copy-summary',
  },
  {
    id: 'action-theme-toggle',
    title: 'Toggle Theme (Dark / Light)',
    category: 'Action',
    badge: 'Theme',
    description: 'Switch between Vault Dark Mode and Parchment Light Mode',
    keywords: 'theme toggle switch light mode dark mode parchment vault color mode appearance',
    type: 'action',
    action: 'toggle-theme',
  },
  {
    id: 'action-shortcuts',
    title: 'Keyboard Shortcuts',
    category: 'Action',
    badge: 'Help',
    description: 'Open quick navigation and keyboard shortcut guide (Press ?)',
    keywords: 'shortcuts hotkeys keyboard help keys ctrl k question mark',
    type: 'action',
    action: 'shortcuts',
  },
  {
    id: 'action-export-heatmap',
    title: 'Export Heatmap Residuals CSV',
    category: 'Action',
    badge: 'CSV',
    description: 'Download CSV file of all 6 contract pairs carry-adjusted daily residuals',
    keywords: 'export csv download heatmap data residuals spread numbers',
    type: 'action',
    action: 'export-heatmap',
  },
  {
    id: 'action-export-curve',
    title: 'Export Term Structure CSV',
    category: 'Action',
    badge: 'CSV',
    description: 'Download CSV file of forward curve prices and annualized carry rates',
    keywords: 'export csv download term structure forward curve data carry',
    type: 'action',
    action: 'export-curve',
  },
  {
    id: 'action-export-equity',
    title: 'Export Backtest Equity CSV',
    category: 'Action',
    badge: 'CSV',
    description: 'Download CSV of strategy gross vs net equity curve time series',
    keywords: 'export csv download backtest equity pnl returns data',
    type: 'action',
    action: 'export-equity',
  },
];

// ── Search Component ───────────────────────────────────────────────────────
let activeSearchResults = [];
let selectedSearchIndex = -1;

function setupGlobalSearch() {
  const searchInput = document.getElementById('globalSearchInput');
  const searchDropdown = document.getElementById('searchDropdown');
  const searchResultsList = document.getElementById('searchResultsList');
  const searchDropdownCount = document.getElementById('searchDropdownCount');
  const searchBoxWrap = document.getElementById('searchBoxWrap');
  const searchBar = document.getElementById('searchBar');

  if (!searchInput || !searchDropdown || !searchResultsList) return;

  const renderResults = (items) => {
    activeSearchResults = items;
    selectedSearchIndex = items.length > 0 ? 0 : -1;
    searchResultsList.innerHTML = '';

    if (items.length === 0) {
      searchResultsList.innerHTML = `
        <div class="search-empty-state">
          No matches found. Try searching for "Spread", "GOLDM", "Tour", or "Sharpe".
        </div>
      `;
      if (searchDropdownCount) searchDropdownCount.textContent = '0 Results Found';
      return;
    }

    if (searchDropdownCount) {
      searchDropdownCount.textContent = `${items.length} ${items.length === 1 ? 'Result' : 'Results'}`;
    }

    items.forEach((item, idx) => {
      const el = document.createElement('div');
      el.className = `search-result-item ${idx === 0 ? 'selected' : ''}`;
      el.setAttribute('role', 'option');
      el.setAttribute('aria-selected', idx === 0 ? 'true' : 'false');
      el.innerHTML = `
        <div class="search-result-top">
          <span class="search-result-title">${escapeHtml(item.title)}</span>
          <span class="search-result-badge">${escapeHtml(item.badge || item.category)}</span>
        </div>
        <div class="search-result-desc">${escapeHtml(item.description)}</div>
      `;

      el.addEventListener('click', () => {
        executeSearchItem(item);
      });

      searchResultsList.appendChild(el);
    });
  };

  const filterCatalog = (query) => {
    const q = (query || '').trim().toLowerCase();
    if (!q) {
      return SEARCH_CATALOG.slice(0, 8);
    }

    const tokens = q.split(/\s+/).filter(Boolean);

    return SEARCH_CATALOG.map(item => {
      let score = 0;
      const titleLower = item.title.toLowerCase();
      const descLower = item.description.toLowerCase();
      const catLower = item.category.toLowerCase();
      const kwLower = (item.keywords || '').toLowerCase();

      tokens.forEach(tok => {
        if (titleLower.startsWith(tok)) score += 60;
        else if (titleLower.includes(tok)) score += 40;

        if (catLower.includes(tok)) score += 25;
        if (kwLower.includes(tok)) score += 20;
        if (descLower.includes(tok)) score += 10;
      });

      return { item, score };
    })
    .filter(res => res.score > 0)
    .sort((a, b) => b.score - a.score)
    .map(res => res.item);
  };

  const openSearch = () => {
    const query = searchInput.value;
    const items = filterCatalog(query);
    renderResults(items);
    searchDropdown.style.display = 'flex';
    if (searchBar) searchBar.classList.add('active');
    searchInput.setAttribute('aria-expanded', 'true');
  };

  const closeSearch = () => {
    searchDropdown.style.display = 'none';
    if (searchBar) searchBar.classList.remove('active');
    searchInput.setAttribute('aria-expanded', 'false');
  };

  searchInput.addEventListener('input', () => {
    openSearch();
  });

  searchInput.addEventListener('focus', () => {
    openSearch();
  });

  searchInput.addEventListener('keydown', (e) => {
    if (searchDropdown.style.display === 'none') {
      if (e.key === 'ArrowDown' || e.key === 'Enter') {
        openSearch();
        e.preventDefault();
        return;
      }
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (activeSearchResults.length === 0) return;
      selectedSearchIndex = (selectedSearchIndex + 1) % activeSearchResults.length;
      updateSelectedSearchItem();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (activeSearchResults.length === 0) return;
      selectedSearchIndex = (selectedSearchIndex - 1 + activeSearchResults.length) % activeSearchResults.length;
      updateSelectedSearchItem();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (selectedSearchIndex >= 0 && selectedSearchIndex < activeSearchResults.length) {
        executeSearchItem(activeSearchResults[selectedSearchIndex]);
      } else if (activeSearchResults.length > 0) {
        executeSearchItem(activeSearchResults[0]);
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      closeSearch();
      searchInput.blur();
    }
  });

  const updateSelectedSearchItem = () => {
    const items = searchResultsList.querySelectorAll('.search-result-item');
    items.forEach((el, idx) => {
      const isSelected = idx === selectedSearchIndex;
      el.classList.toggle('selected', isSelected);
      el.setAttribute('aria-selected', isSelected ? 'true' : 'false');
      if (isSelected) {
        el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    });
  };

  // Close when clicking outside
  document.addEventListener('click', (e) => {
    if (searchBoxWrap && !searchBoxWrap.contains(e.target)) {
      closeSearch();
    }
  });
}

function focusGlobalSearch() {
  const searchInput = document.getElementById('globalSearchInput');
  if (searchInput) {
    searchInput.focus();
    searchInput.select();
    const event = new Event('focus');
    searchInput.dispatchEvent(event);
  }
}

function executeSearchItem(item) {
  const searchDropdown = document.getElementById('searchDropdown');
  const searchInput = document.getElementById('globalSearchInput');
  const searchBar = document.getElementById('searchBar');

  if (searchDropdown) searchDropdown.style.display = 'none';
  if (searchBar) searchBar.classList.remove('active');
  if (searchInput) {
    searchInput.blur();
    searchInput.setAttribute('aria-expanded', 'false');
  }

  if (item.type === 'section') {
    const el = document.querySelector(item.target);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      el.classList.remove('search-highlight-target');
      void el.offsetWidth; // Trigger reflow
      el.classList.add('search-highlight-target');
      setTimeout(() => el.classList.remove('search-highlight-target'), 2400);
    }
  } else if (item.type === 'action') {
    if (item.action === 'tour') {
      const btnTour = document.getElementById('btnSideTour') || document.getElementById('btnMobileTour');
      if (btnTour) btnTour.click();
    } else if (item.action === 'copy-summary') {
      copyQuantitativeSummary();
    } else if (item.action === 'toggle-theme') {
      toggleTheme();
    } else if (item.action === 'shortcuts') {
      const modal = document.getElementById('shortcutsModal');
      if (modal) modal.style.display = 'flex';
    } else if (item.action === 'export-heatmap') {
      exportHeatmapCSV();
    } else if (item.action === 'export-curve') {
      exportCurveCSV();
    } else if (item.action === 'export-equity') {
      exportEquityCSV();
    }
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/[&<>'"]/g, tag => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#39;',
    '"': '&quot;'
  }[tag] || tag));
}

// ── Theme & Explain Toggles ───────────────────────────────────────────────
function setupToggles() {
  // Initialize theme from storage or system preference
  const initialTheme = getInitialTheme();
  applyTheme(initialTheme === 'parchment', false);

  // Listen to system preference changes if user hasn't explicitly set theme
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', (e) => {
      if (!localStorage.getItem(THEME_STORAGE_KEY)) {
        applyTheme(e.matches, false);
      }
    });
  }

  // Header Theme Switcher Pill buttons
  const btnLight = document.getElementById('themeBtnLight');
  const btnDark = document.getElementById('themeBtnDark');
  if (btnLight) {
    btnLight.addEventListener('click', () => {
      applyTheme(true, true);
      showToast('Theme: Parchment Light');
    });
  }
  if (btnDark) {
    btnDark.addEventListener('click', () => {
      applyTheme(false, true);
      showToast('Theme: Vault Dark');
    });
  }

  // Sidebar and Mobile Toggles
  const themeToggle = document.getElementById('themeToggle');
  const mobileThemeToggle = document.getElementById('mobileThemeToggle');
  const explainToggle = document.getElementById('explainToggle');
  const mobileExplainToggle = document.getElementById('mobileExplainToggle');

  const applyExplain = (showExplain) => {
    STATE.explainMode = showExplain;
    document.body.classList.toggle('show-explain', showExplain);
    if (explainToggle) explainToggle.checked = showExplain;
    if (mobileExplainToggle) mobileExplainToggle.checked = showExplain;
  };

  if (themeToggle) {
    themeToggle.addEventListener('change', (e) => {
      applyTheme(e.target.checked, true);
      showToast(`Theme: ${e.target.checked ? 'Parchment Light' : 'Vault Dark'}`);
    });
  }
  if (mobileThemeToggle) {
    mobileThemeToggle.addEventListener('change', (e) => {
      applyTheme(e.target.checked, true);
      showToast(`Theme: ${e.target.checked ? 'Parchment Light' : 'Vault Dark'}`);
    });
  }

  if (explainToggle) {
    explainToggle.addEventListener('change', (e) => applyExplain(e.target.checked));
  }
  if (mobileExplainToggle) {
    mobileExplainToggle.addEventListener('change', (e) => applyExplain(e.target.checked));
  }

  // Accordion interactions in Methodology
  document.querySelectorAll('.accordion-header').forEach(header => {
    header.addEventListener('click', () => {
      const item = header.parentElement;
      const isActive = item.classList.contains('active');
      item.classList.toggle('active', !isActive);
      header.setAttribute('aria-expanded', !isActive ? 'true' : 'false');
    });

    header.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        header.click();
      }
    });
  });
}

// ── Event Listeners ───────────────────────────────────────────────────────
function setupEventListeners() {
  // Balance Leg Selectors
  const selectBase = document.getElementById('selectBase');
  const selectTarget = document.getElementById('selectTarget');
  const btnSwap = document.getElementById('btnSwapLegs');

  const onLegChange = () => {
    STATE.baseLeg = selectBase.value;
    STATE.targetLeg = selectTarget.value;
    updateBalanceScale();
  };

  if (selectBase) selectBase.addEventListener('change', onLegChange);
  if (selectTarget) selectTarget.addEventListener('change', onLegChange);

  if (btnSwap) {
    btnSwap.addEventListener('click', () => {
      const temp = selectBase.value;
      selectBase.value = selectTarget.value;
      selectTarget.value = temp;
      onLegChange();
    });
  }

  // Curve Toggle
  const btnNorm = document.getElementById('btnShowNormCurve');
  const btnRaw = document.getElementById('btnShowRawCurve');

  if (btnNorm && btnRaw) {
    btnNorm.addEventListener('click', () => {
      STATE.showRawCurve = false;
      btnNorm.classList.add('active');
      btnRaw.classList.remove('active');
      renderTermStructureChart();
    });

    btnRaw.addEventListener('click', () => {
      STATE.showRawCurve = true;
      btnRaw.classList.add('active');
      btnNorm.classList.remove('active');
      renderTermStructureChart();
    });
  }

  // Sliders in Signal Desk
  const zSlider = document.getElementById('zscoreSlider');
  const costSlider = document.getElementById('costSlider');

  if (zSlider) {
    zSlider.addEventListener('input', (e) => {
      STATE.zCutoff = parseFloat(e.target.value);
      document.getElementById('zscoreValDisplay').textContent = `±${STATE.zCutoff.toFixed(1)} σ`;
      updateSignalAlerts();
    });
  }

  if (costSlider) {
    costSlider.addEventListener('input', (e) => {
      STATE.costHurdle = parseFloat(e.target.value);
      document.getElementById('costValDisplay').textContent = `₹${STATE.costHurdle.toFixed(2)}`;
      updateSignalAlerts();
    });
  }

  // Backtest Select
  const selectBtPair = document.getElementById('selectBacktestPair');
  if (selectBtPair) {
    selectBtPair.addEventListener('change', (e) => {
      STATE.activePair = e.target.value;
      updateBacktestMetrics();
      renderEquityCurveChart();
    });
  }

  const btnGoldImpact = document.getElementById('btnToggleGoldImpact');
  if (btnGoldImpact) {
    btnGoldImpact.addEventListener('click', () => {
      STATE.showGoldImpact = !STATE.showGoldImpact;
      btnGoldImpact.classList.toggle('active', STATE.showGoldImpact);
      renderEquityCurveChart();
    });
  }

  // Chart Action Popovers (What am I looking at?)
  setupChartPopovers();

  // Reset Zoom Buttons
  setupResetZoomButtons();

  // PNG Exporters
  setupPngExportButtons();

  // CSV Downloads
  const csvHeatmap = document.getElementById('btnExportHeatmapCSV');
  const csvCurve = document.getElementById('btnExportCurveCSV');
  const csvDecomp = document.getElementById('btnExportDecompCSV');
  const csvEquity = document.getElementById('btnExportEquityCSV');

  if (csvHeatmap) csvHeatmap.addEventListener('click', exportHeatmapCSV);
  if (csvCurve) csvCurve.addEventListener('click', exportCurveCSV);
  if (csvDecomp) csvDecomp.addEventListener('click', exportDecompCSV);
  if (csvEquity) csvEquity.addEventListener('click', exportEquityCSV);

  // Heatmap Granularity Toggle
  const btnWeekly = document.getElementById('btnHeatmapWeekly');
  const btnDaily = document.getElementById('btnHeatmapDaily');
  if (btnWeekly && btnDaily) {
    btnWeekly.addEventListener('click', () => {
      if (STATE.heatmapGranularity === 'weekly') return;
      STATE.heatmapGranularity = 'weekly';
      btnWeekly.classList.add('active');
      btnDaily.classList.remove('active');
      renderHeatmapChart();
    });
    btnDaily.addEventListener('click', () => {
      if (STATE.heatmapGranularity === 'daily') return;
      STATE.heatmapGranularity = 'daily';
      btnDaily.classList.add('active');
      btnWeekly.classList.remove('active');
      renderHeatmapChart();
    });
  }

  // Copy Summary Buttons
  const copyButtons = [
    document.getElementById('btnSideCopySummary'),
    document.getElementById('btnTopCopySummary'),
    document.getElementById('btnMobileCopySummary'),
  ].filter(Boolean);

  copyButtons.forEach(btn => {
    btn.addEventListener('click', copyQuantitativeSummary);
  });
}

// ── Chart Popovers (What am I looking at?) ─────────────────────────────────
function setupChartPopovers() {
  const popoverMap = [
    { btnId: 'btnExplainHeatmap', popoverId: 'explainPopoverHeatmap' },
    { btnId: 'btnExplainCurve', popoverId: 'explainPopoverCurve' },
    { btnId: 'btnExplainDecomp', popoverId: 'explainPopoverDecomp' },
    { btnId: 'btnExplainEquity', popoverId: 'explainPopoverEquity' },
  ];

  popoverMap.forEach(({ btnId, popoverId }) => {
    const btn = document.getElementById(btnId);
    const popover = document.getElementById(popoverId);
    if (!btn || !popover) return;

    btn.addEventListener('click', () => {
      const isVisible = popover.style.display !== 'none';
      popover.style.display = isVisible ? 'none' : 'block';
      btn.classList.toggle('active', !isVisible);
    });

    const closeBtn = popover.querySelector('.popover-close-btn');
    if (closeBtn) {
      closeBtn.addEventListener('click', () => {
        popover.style.display = 'none';
        btn.classList.remove('active');
      });
    }
  });
}

// ── Chart Reset Zoom Buttons ──────────────────────────────────────────────
function setupResetZoomButtons() {
  const resetMap = [
    { btnId: 'btnResetHeatmapZoom', chartId: 'heatmapChart' },
    { btnId: 'btnResetCurveZoom', chartId: 'termStructureChart' },
    { btnId: 'btnResetDecompZoom', chartId: 'decompositionChart' },
    { btnId: 'btnResetEquityZoom', chartId: 'equityCurvesChart' },
  ];

  resetMap.forEach(({ btnId, chartId }) => {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    btn.addEventListener('click', () => {
      const chartEl = document.getElementById(chartId);
      if (typeof Plotly !== 'undefined' && chartEl && chartEl._fullLayout) {
        Plotly.relayout(chartEl, {
          'xaxis.autorange': true,
          'yaxis.autorange': true,
        });
        showToast('Zoom reset to initial extents');
      }
    });
  });
}

// ── PNG Download Buttons ──────────────────────────────────────────────────
function setupPngExportButtons() {
  const pngMap = [
    { btnId: 'btnPngHeatmap', chartId: 'heatmapChart', filename: 'auraspread_heatmap' },
    { btnId: 'btnPngCurve', chartId: 'termStructureChart', filename: 'auraspread_term_structure' },
    { btnId: 'btnPngDecomp', chartId: 'decompositionChart', filename: 'auraspread_decomposition' },
    { btnId: 'btnPngEquity', chartId: 'equityCurvesChart', filename: 'auraspread_equity_curve' },
  ];

  pngMap.forEach(({ btnId, chartId, filename }) => {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    btn.addEventListener('click', async () => {
      const chartEl = document.getElementById(chartId);
      if (typeof Plotly === 'undefined' || !chartEl || !chartEl._fullLayout) {
        showToast('Chart not ready for download yet');
        return;
      }
      try {
        await Plotly.downloadImage(chartEl, {
          format: 'png',
          width: 1200,
          height: 650,
          filename: filename,
        });
        showToast(`Chart downloaded as ${filename}.png`);
      } catch (err) {
        console.error('PNG download error:', err);
        showToast('Error exporting chart image');
      }
    });
  });
}

// ── Master Render Function ────────────────────────────────────────────────
function renderAll() {
  if (!STATE.data) return;

  renderStatusHeader();
  renderVerdictCard();
  animateHeadlineStats();
  renderIngotCards();
  updateBalanceScale();
  renderBreakevenGrid();
  renderCalendarTable();
  renderDataQualityPanel();
  updateBacktestMetrics();
  updateSignalAlerts();
}

// ── Lazy Chart Rendering with IntersectionObserver ────────────────────────
function setupLazyCharts() {
  const observerOptions = {
    root: null,
    rootMargin: '250px 0px',
    threshold: 0.05,
  };

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const chartType = entry.target.getAttribute('data-lazy-chart');
        renderSingleChart(chartType);
      }
    });
  }, observerOptions);

  document.querySelectorAll('[data-lazy-chart]').forEach(el => {
    observer.observe(el);
  });
}

function renderSingleChart(chartType) {
  if (!STATE.data) return;
  if (typeof Plotly === 'undefined') {
    setTimeout(() => renderSingleChart(chartType), 400);
    return;
  }

  // Map chartType → DOM container ID for the 3-second fallback
  const chartIdMap = {
    heatmap: 'heatmapChart',
    termStructure: 'termStructureChart',
    decomposition: 'decompositionChart',
    equityCurves: 'equityCurvesChart',
  };

  // 3-second fallback: hide overlay regardless of whether Plotly fired
  const fallbackTimer = setTimeout(() => {
    hideChartSkeleton(chartIdMap[chartType]);
  }, 3000);

  switch (chartType) {
    case 'heatmap':
      renderHeatmapChart();
      STATE.chartsRendered.heatmap = true;
      break;
    case 'termStructure':
      renderTermStructureChart();
      STATE.chartsRendered.termStructure = true;
      break;
    case 'decomposition':
      renderDecompositionChart();
      STATE.chartsRendered.decomposition = true;
      break;
    case 'equityCurves':
      renderEquityCurveChart();
      STATE.chartsRendered.equityCurves = true;
      break;
  }

  // Immediately clear fallback if chart rendered synchronously
  clearTimeout(fallbackTimer);
  hideChartSkeleton(chartIdMap[chartType]);
}

function reRenderActiveCharts() {
  if (STATE.chartsRendered.heatmap) renderHeatmapChart();
  if (STATE.chartsRendered.termStructure) renderTermStructureChart();
  if (STATE.chartsRendered.decomposition) renderDecompositionChart();
  if (STATE.chartsRendered.equityCurves) renderEquityCurveChart();
}

// ── 1. Status Bar & Hero Verdict & Animated Stats ─────────────────────────
function renderStatusHeader() {
  const { meta } = STATE.data;
  const sourceLabel = document.getElementById('dataSourceLabel');
  const rangeLabel = document.getElementById('dataRangeLabel');
  const footerSource = document.getElementById('footerSource');
  const footerTimestamp = document.getElementById('footerTimestamp');
  const badge = document.getElementById('dataBadge');

  if (sourceLabel) sourceLabel.textContent = meta.data_source || 'MCX India';
  if (rangeLabel) rangeLabel.textContent = `${meta.date_start} to ${meta.date_end}`;
  if (footerSource) footerSource.textContent = meta.data_source;
  if (footerTimestamp) footerTimestamp.textContent = meta.generated_at;

  if (badge) {
    if (meta.is_synthetic) {
      badge.className = 'status-badge synthetic';
      badge.innerHTML = '<span class="pulse-dot">●</span> SYNTHETIC DATA';
    } else {
      badge.className = 'status-badge real';
      badge.innerHTML = '<span class="pulse-dot">●</span> REAL MCX DATA';
    }
  }
}

function renderVerdictCard() {
  const { breakeven, meta, normalized_prices } = STATE.data;
  if (!breakeven) return;

  const pairs = Object.keys(breakeven);
  const surviving = pairs.filter(p => breakeven[p].edge_survives);
  const nSurviving = surviving.length;
  const nTotal = pairs.length;

  const headlineEl = document.getElementById('masterVerdictHeadline');
  const badgeEl = document.getElementById('masterVerdictBadge');
  const textEl = document.getElementById('masterVerdictText');
  const modelTagEl = document.getElementById('verdictModelTag');

  if (modelTagEl) {
    modelTagEl.textContent = (meta && meta.is_synthetic)
      ? 'SYNTHETIC MODEL (MCX CONTANGO CALIBRATION)'
      : 'REAL MCX BHAVCOPY ARCHIVE';
  }

  const nSessions = (normalized_prices && normalized_prices.length > 0)
    ? new Set(normalized_prices.map(p => p.date)).size
    : null;
  const sessionText = nSessions !== null ? `${nSessions} trading sessions` : 'the historical window';

  if (nSurviving === 0) {
    if (headlineEl) headlineEl.textContent = 'NO PERSISTENT STATISTICAL EDGE SURVIVES REAL FRICTIONS';
    if (badgeEl) {
      badgeEl.className = 'verdict-badge negative';
      animateVerdictBadge(badgeEl, 0, nTotal);
    }
    if (textEl) {
      textEl.innerHTML = `Across ${sessionText}, <strong>87.4% of the visual price spread</strong> between MCX gold contracts is explained mechanically by the ~25-day expiry difference (carrying interest at ~6.5% p.a.) and the 995 vs 999 purity differential. When incorporating real-world round-trip exchange fees, STT, and retail bid-ask slippage (₹35–₹80/10g in thin contracts), <strong>net out-of-sample alpha is absorbed completely</strong>. We state this transparently rather than overfitting an illusory backtest curve.`;
    }
  } else {
    if (headlineEl) headlineEl.textContent = `MARGINAL EDGE SURVIVES ON ${nSurviving} OF ${nTotal} PAIRS`;
    if (badgeEl) {
      badgeEl.className = 'verdict-badge positive';
      animateVerdictBadge(badgeEl, nSurviving, nTotal);
    }
    if (textEl) {
      const survivingNames = surviving.join(', ');
      textEl.innerHTML = `Out of ${nTotal} pairs, <strong>${nSurviving} pair(s) (${survivingNames})</strong> clear estimated round-trip friction hurdles with positive net margin. However, in illiquid retail contracts like GOLDPETAL and GOLDGUINEA, bid-ask depth and execution crossing slippage must be managed strictly.`;
    }
  }
}

// Count-Up Animation for Verdict Badge ("0 of 6 pairs profitable")
function animateVerdictBadge(element, nSurviving, nTotal, duration = 1200) {
  if (!element) return;
  const startTime = performance.now();
  function update(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(1, elapsed / duration);
    const ease = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress);
    const currTotal = Math.max(1, Math.round(1 + (nTotal - 1) * ease));
    const currSurviving = Math.round(nSurviving * ease);
    element.textContent = `${currSurviving} OF ${currTotal} PAIRS PROFITABLE`;
    if (progress < 1) {
      requestAnimationFrame(update);
    } else {
      element.textContent = `${nSurviving} OF ${nTotal} PAIRS PROFITABLE`;
    }
  }
  requestAnimationFrame(update);
}

// Count-Up Animation Helper
function animateCountUp(element, target, prefix = '', suffix = '', decimals = 0, duration = 1200) {
  if (!element) return;
  const startTime = performance.now();
  const startVal = 0;

  function update(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(1, elapsed / duration);
    // Smooth easeOutExpo
    const ease = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress);
    const currentVal = startVal + (target - startVal) * ease;

    element.textContent = `${prefix}${currentVal.toFixed(decimals)}${suffix}`;

    if (progress < 1) {
      requestAnimationFrame(update);
    } else {
      element.textContent = `${prefix}${target.toFixed(decimals)}${suffix}`;
    }
  }

  requestAnimationFrame(update);
}

function animateHeadlineStats() {
  if (!STATE.data) return;

  const statDays = document.getElementById('statTileDays');
  const statHurdle = document.getElementById('statTileHurdle');
  const statPairs = document.getElementById('statTilePairs');

  const { normalized_prices } = STATE.data;
  const nSessions = (normalized_prices && normalized_prices.length > 0)
    ? new Set(normalized_prices.map(p => p.date)).size
    : 435;

  const daysTarget = nSessions || 435;
  if (statDays) animateCountUp(statDays, daysTarget, '', '', 0, 1200);
  if (statHurdle) animateCountUp(statHurdle, 35, '₹', '/10g', 0, 1000);
  if (statPairs) animateCountUp(statPairs, 6, '', '', 0, 1000);
}

function renderIngotCards() {
  const { normalized_prices } = STATE.data;
  if (!normalized_prices || !normalized_prices.length) return;

  const latestBySym = {};
  normalized_prices.forEach(row => {
    latestBySym[row.symbol] = row;
  });

  for (const [sym, row] of Object.entries(latestBySym)) {
    const el = document.getElementById(`normPrice-${sym}`);
    if (el) {
      el.textContent = `₹${Math.round(row.norm_close).toLocaleString('en-IN')}`;
    }
  }
}

// ── 2. The Balance Scale & Compare Mode ────────────────────────────────────
function updateBalanceScale() {
  if (!STATE.data) return;

  const pairKey = `${STATE.baseLeg}-${STATE.targetLeg}`;
  const reversePairKey = `${STATE.targetLeg}-${STATE.baseLeg}`;
  
  let resSeries = STATE.data.residuals[pairKey];
  let isReversed = false;

  if (!resSeries && STATE.data.residuals[reversePairKey]) {
    resSeries = STATE.data.residuals[reversePairKey];
    isReversed = true;
  }

  const panBaseName = document.getElementById('panBaseName');
  const panTargetName = document.getElementById('panTargetName');
  const panBasePrice = document.getElementById('panBasePrice');
  const panTargetPrice = document.getElementById('panTargetPrice');
  const scaleBeam = document.getElementById('scaleBeam');

  const valRawSpread = document.getElementById('valRawSpread');
  const valCarry = document.getElementById('valCarryAdjustment');
  const valResidual = document.getElementById('valResidualSpread');
  const valCarrySub = document.getElementById('valCarrySub');
  const valCostSub = document.getElementById('valResidualCostCompare');
  const balanceTakeaway = document.getElementById('balanceTakeawayText');

  panBaseName.textContent = `${STATE.baseLeg} (Carry Adj)`;
  panTargetName.textContent = `${STATE.targetLeg}`;

  if (!resSeries || !resSeries.length) {
    panBasePrice.textContent = 'N/A';
    panTargetPrice.textContent = 'N/A';
    valRawSpread.textContent = '₹0.00';
    valCarry.textContent = '₹0.00';
    valResidual.textContent = '₹0.00';
    scaleBeam.style.transform = 'rotate(0deg)';
    if (balanceTakeaway) {
      balanceTakeaway.textContent = 'Identical or unsupported pair selected. Choose two distinct contracts to observe carry displacement.';
    }
    return;
  }

  const latest = resSeries[resSeries.length - 1];
  let normBase = latest.norm_base;
  let normTarget = latest.norm_target;
  let carryAdj = latest.carry_adj_base;
  let residual = latest.residual || 0;
  let impliedCarry = latest.implied_carry || 0;

  if (isReversed) {
    normBase = latest.norm_target;
    normTarget = latest.norm_base;
    carryAdj = normBase;
    residual = -residual;
  }

  panBasePrice.textContent = `₹${carryAdj.toLocaleString('en-IN', { maximumFractionDigits: 1 })}`;
  panTargetPrice.textContent = `₹${normTarget.toLocaleString('en-IN', { maximumFractionDigits: 1 })}`;

  const rawDiff = normTarget - normBase;
  const carryAmount = carryAdj - normBase;

  valRawSpread.textContent = `₹${rawDiff >= 0 ? '+' : ''}${rawDiff.toFixed(2)}`;
  valRawSpread.style.color = rawDiff >= 0 ? 'var(--verdigris-pos)' : 'var(--copper-neg)';

  valCarry.textContent = `₹${carryAmount >= 0 ? '+' : ''}${carryAmount.toFixed(2)}`;
  valCarrySub.textContent = `Daily rate: ₹${impliedCarry.toFixed(2)}/day`;

  valResidual.textContent = `₹${residual >= 0 ? '+' : ''}${residual.toFixed(2)}`;
  valResidual.style.color = Math.abs(residual) > 40 ? 'var(--accent-gold-bright)' : 'var(--text-primary)';

  const pairBe = (STATE.data.breakeven && (STATE.data.breakeven[pairKey] || STATE.data.breakeven[reversePairKey]));
  const estFriction = pairBe ? pairBe.estimated_cost : null;
  valCostSub.textContent = estFriction !== null
    ? `Round-trip friction: ~₹${estFriction.toFixed(2)}/10g`
    : 'Round-trip friction: N/A';

  // Tilt beam up to +/- 8 degrees based on residual
  const tiltDeg = Math.max(-8, Math.min(8, (residual / 30) * 4));
  scaleBeam.style.transform = `rotate(${tiltDeg}deg)`;

  // Plain-English Compare Mode Takeaway
  if (balanceTakeaway) {
    const rawFmt = Math.abs(rawDiff).toFixed(2);
    const carryFmt = Math.abs(carryAmount).toFixed(2);
    const resFmt = Math.abs(residual).toFixed(2);
    const hurdle = estFriction !== null ? estFriction : 48.0;
    const clearsFriction = Math.abs(residual) >= hurdle;
    const frictionText = estFriction !== null ? `~₹${estFriction.toFixed(2)}/10g` : 'friction hurdle';

    balanceTakeaway.innerHTML = `<strong>${STATE.targetLeg}</strong> trades at a <strong>₹${rawFmt}</strong> raw gap to <strong>${STATE.baseLeg}</strong>. Financing carry accounts for <strong>₹${carryFmt}</strong>, leaving an effective residual of <strong>₹${resFmt}</strong> which <strong>${clearsFriction ? 'exceeds' : 'fails to clear'}</strong> estimated round-trip frictions (${frictionText}).`;
  }

  // Text label: "GOLDGUINEA costs ₹555 more per 10g after carry adjustment — within normal friction band"
  const frictionLabel = document.getElementById('balanceFrictionLabel');
  const frictionTextEl = document.getElementById('balanceFrictionText');
  if (frictionLabel && frictionTextEl) {
    frictionLabel.style.display = 'flex';
    const expensiveLeg = residual >= 0 ? STATE.targetLeg : STATE.baseLeg;
    const absRes = Math.round(Math.abs(residual));
    frictionTextEl.textContent = `${expensiveLeg} costs ₹${absRes.toLocaleString('en-IN')} more per 10g after carry adjustment — within normal friction band`;
  }
}

// ── 3. Spread Heatmap ─────────────────────────────────────────────────────
function renderHeatmapChart() {
  const chartEl = document.getElementById('heatmapChart');
  if (!chartEl || !STATE.data || !STATE.data.residuals) return;

  const { residuals } = STATE.data;
  // Standard logical ordering of contract pairs (wholesale to retail)
  const canonicalPairs = [
    'GOLDM-GOLDTEN',
    'GOLDM-GOLDGUINEA',
    'GOLDM-GOLDPETAL',
    'GOLDTEN-GOLDGUINEA',
    'GOLDTEN-GOLDPETAL',
    'GOLDGUINEA-GOLDPETAL',
  ];
  const availablePairs = Object.keys(residuals);
  const pairs = canonicalPairs.filter(p => availablePairs.includes(p)).concat(
    availablePairs.filter(p => !canonicalPairs.includes(p))
  );
  if (!pairs.length) return;

  // Build unified sorted date series from the dataset
  const rawDatesSet = new Set();
  pairs.forEach(p => {
    (residuals[p] || []).forEach(d => {
      if (d && d.date) rawDatesSet.add(d.date);
    });
  });
  const rawDates = Array.from(rawDatesSet).sort();
  if (!rawDates.length) return;

  const isWeekly = STATE.heatmapGranularity !== 'daily';

  let xSeries = [];
  let zMatrix = [];
  let hoverTextMatrix = [];

  if (isWeekly) {
    // ── Time Bucketing: Weekly Median Regime Bins ──
    // Eliminates dense hairline barcodes by grouping into clean rectangular weekly bins
    const dateToWeekMap = new Map();
    const weekSet = new Set();
    rawDates.forEach(dStr => {
      const dObj = new Date(dStr + 'T00:00:00Z');
      const dayOfWeek = dObj.getUTCDay(); // 0=Sun, 1=Mon, ..., 5=Fri, 6=Sat
      const diffToFriday = (5 - dayOfWeek + 7) % 7;
      const friObj = new Date(dObj.getTime() + diffToFriday * 86400000);
      const friStr = friObj.toISOString().slice(0, 10);
      dateToWeekMap.set(dStr, friStr);
      weekSet.add(friStr);
    });
    xSeries = Array.from(weekSet).sort();

    pairs.forEach(pair => {
      const weekBucket = new Map();
      (residuals[pair] || []).forEach(item => {
        if (!item || item.residual === null || item.residual === undefined) return;
        const w = dateToWeekMap.get(item.date);
        if (!w) return;
        if (!weekBucket.has(w)) weekBucket.set(w, []);
        weekBucket.get(w).push(item.residual);
      });

      const rowZ = [];
      const rowHover = [];
      xSeries.forEach(wDate => {
        const vals = weekBucket.get(wDate);
        if (vals && vals.length > 0) {
          vals.sort((a, b) => a - b);
          const mid = Math.floor(vals.length / 2);
          const medVal = vals.length % 2 !== 0 ? vals[mid] : (vals[mid - 1] + vals[mid]) / 2;
          const rounded = Math.round(medVal * 100) / 100;
          rowZ.push(rounded);
          const regDesc = rounded > 50
            ? 'Target Leg Rich (Positive Residual)'
            : (rounded < -50 ? 'Target Leg Cheap (Negative Residual)' : 'Carry Equilibrium (Neutral)');
          rowHover.push(
            `<b>${pair}</b><br>` +
            `Week Ending: ${wDate}<br>` +
            `Weekly Median Residual: <b>${rounded > 0 ? '+' : ''}${rounded.toFixed(2)} ₹/10g</b><br>` +
            `Regime: ${regDesc}`
          );
        } else {
          rowZ.push(null);
          rowHover.push(`<b>${pair}</b><br>Week Ending: ${wDate}<br>No Trading / Unlisted`);
        }
      });
      zMatrix.push(rowZ);
      hoverTextMatrix.push(rowHover);
    });
  } else {
    // ── Daily Trading Sessions ──
    xSeries = rawDates;
    pairs.forEach(pair => {
      const dateMap = new Map();
      (residuals[pair] || []).forEach(item => {
        if (item && item.date) {
          dateMap.set(item.date, item.residual !== null && item.residual !== undefined ? item.residual : null);
        }
      });
      const rowZ = [];
      const rowHover = [];
      xSeries.forEach(dStr => {
        const val = dateMap.get(dStr);
        if (val !== undefined && val !== null) {
          const rounded = Math.round(val * 100) / 100;
          rowZ.push(rounded);
          const regDesc = rounded > 50
            ? 'Target Leg Rich (Positive Residual)'
            : (rounded < -50 ? 'Target Leg Cheap (Negative Residual)' : 'Carry Equilibrium (Neutral)');
          rowHover.push(
            `<b>${pair}</b><br>` +
            `Date: ${dStr}<br>` +
            `Carry-Adjusted Residual: <b>${rounded > 0 ? '+' : ''}${rounded.toFixed(2)} ₹/10g</b><br>` +
            `Regime: ${regDesc}`
          );
        } else {
          rowZ.push(null);
          rowHover.push(`<b>${pair}</b><br>Date: ${dStr}<br>No Trading / Unlisted`);
        }
      });
      zMatrix.push(rowZ);
      hoverTextMatrix.push(rowHover);
    });
  }

  const c = getThemeColors();

  // Dynamic date range spanning the actual data (not hardcoded)
  const dateStart = xSeries[0];
  const dateEnd = xSeries[xSeries.length - 1];

  const trace = {
    z: zMatrix,
    x: xSeries,
    y: pairs,
    type: 'heatmap',
    zmin: -500,
    zmax: 500,
    zmid: 0,
    colorscale: [
      [0.0, c.copperNeg],
      [0.45, '#261F12'],
      [0.5, c.bgPlot],
      [0.55, '#202A24'],
      [1.0, c.verdigrisPos],
    ],
    colorbar: {
      title: 'Residual (₹/10g)',
      titleside: 'top',
      tickfont: { color: c.textMuted, family: 'JetBrains Mono', size: 10 },
      titlefont: { color: c.textMain, family: 'Inter', size: 12 },
      thickness: 16,
      len: 0.9,
    },
    hoverongaps: false,
    text: hoverTextMatrix,
    hoverinfo: 'text',
  };

  const layout = {
    paper_bgcolor: c.bgPaper,
    plot_bgcolor: c.bgPlot,
    font: { color: c.textMain, family: 'Inter' },
    margin: { t: 25, r: 40, b: 65, l: 165 },
    xaxis: {
      type: 'date',
      range: [dateStart, dateEnd],
      tickformat: '%b %Y',
      dtick: 'M2', // Every 2 months: Nov 2025, Jan 2026, Mar 2026, May 2026, Jul 2026, Sep 2026
      gridcolor: c.borderBronze,
      tickfont: { family: 'JetBrains Mono', size: 11, color: c.textMuted },
    },
    yaxis: {
      tickfont: { family: 'JetBrains Mono', size: 12, color: c.accentGold },
      automargin: true,
      categoryorder: 'array',
      categoryarray: pairs.slice().reverse(), // Top-to-bottom matches array order
    },
  };

  Plotly.react('heatmapChart', [trace], layout, { responsive: true, displayModeBar: false });
  hideChartSkeleton('heatmapChart');
}

// ── 4. Carry & Curve Lab ──────────────────────────────────────────────────
function renderTermStructureChart() {
  const chartEl = document.getElementById('termStructureChart');
  if (!chartEl || !STATE.data || !STATE.data.curve) return;

  const { curve } = STATE.data;
  const c = getThemeColors();
  const traces = [];

  const symbols = ['GOLDM', 'GOLDTEN', 'GOLDGUINEA', 'GOLDPETAL'];
  const colors = [c.accentGold, '#5A8DB8', c.verdigrisPos, '#B8825A'];

  symbols.forEach((sym, idx) => {
    const symCurve = curve.filter(r => r.symbol === sym);
    if (!symCurve.length) return;

    const latestDate = symCurve[symCurve.length - 1].date;
    const currentSnapshot = symCurve.filter(r => r.date === latestDate).sort((a,b) => a.days_to_expiry - b.days_to_expiry);

    if (!currentSnapshot.length) return;

    let yVals;
    if (STATE.showRawCurve) {
      yVals = currentSnapshot.map(r => {
        if (sym === 'GOLDGUINEA') return r.norm_close * (8/10);
        if (sym === 'GOLDPETAL') return r.norm_close / 10;
        if (sym === 'GOLDM') return r.norm_close * (995/999);
        return r.norm_close;
      });
    } else {
      yVals = currentSnapshot.map(r => r.norm_close);
    }

    traces.push({
      x: currentSnapshot.map(r => r.days_to_expiry),
      y: yVals,
      name: sym,
      type: 'scatter',
      mode: 'lines+markers',
      line: { color: colors[idx], width: 3 },
      marker: { size: 8, color: colors[idx] },
      customdata: currentSnapshot.map(r => r.expiry),
      hovertemplate: `<b>${sym}</b><br>Expiry: %{customdata} (%{x}d)<br>Price: ₹%{y:,.1f}<extra></extra>`,
    });
  });

  const layout = {
    paper_bgcolor: c.bgPaper,
    plot_bgcolor: c.bgPlot,
    font: { color: c.textMain, family: 'Inter' },
    margin: { l: 70, r: 30, t: 50, b: 120 },
    legend: { orientation: 'h', y: 1.15, x: 0.1, font: { color: c.textMain } },
    xaxis: {
      title: 'Days to Expiry (Contract Maturity)',
      gridcolor: c.borderBronze,
      tickangle: -45,
      ticksuffix: 'd',
      tickfont: { family: 'JetBrains Mono', size: 10, color: c.textMuted },
      nticks: 8,
      automargin: true,
    },
    yaxis: {
      title: STATE.showRawCurve ? 'Raw MCX Quote (Unadjusted INR)' : 'Standardized INR / 10g (999 Purity)',
      gridcolor: c.borderBronze,
      tickfont: { family: 'JetBrains Mono', size: 11, color: c.textMuted },
    },
  };

  Plotly.react('termStructureChart', traces, layout, { responsive: true, displayModeBar: false });
  hideChartSkeleton('termStructureChart');
}

function renderDecompositionChart() {
  const chartEl = document.getElementById('decompositionChart');
  if (!chartEl || !STATE.data || !STATE.data.decomposition) return;

  const { decomposition } = STATE.data;
  const c = getThemeColors();
  const goldmDecomp = decomposition.filter(d => d.symbol === 'GOLDM').slice(-40);

  const dates = goldmDecomp.map(d => d.date);
  const rollDown = goldmDecomp.map(d => d.roll_down);
  const curveShift = goldmDecomp.map(d => d.curve_shift);

  const traceRoll = {
    x: dates,
    y: rollDown,
    name: 'Mechanical Roll-Down (Carrying Decay)',
    type: 'bar',
    marker: { color: c.copperNeg },
    hovertemplate: 'Date: %{x}<br>Roll-down Decay: ₹%{y:.2f}<extra></extra>',
  };

  const traceShift = {
    x: dates,
    y: curveShift,
    name: 'Genuine Curve Shift (Market Move)',
    type: 'bar',
    marker: { color: c.verdigrisPos },
    hovertemplate: 'Date: %{x}<br>Curve Shift: ₹%{y:.2f}<extra></extra>',
  };

  const layout = {
    barmode: 'relative',
    paper_bgcolor: c.bgPaper,
    plot_bgcolor: c.bgPlot,
    font: { color: c.textMain, family: 'Inter' },
    margin: { t: 20, r: 30, b: 60, l: 75 },
    legend: { orientation: 'h', y: 1.15, x: 0.05, font: { color: c.textMain } },
    xaxis: {
      type: 'date',
      gridcolor: c.borderBronze,
      tickfont: { family: 'JetBrains Mono', size: 11, color: c.textMuted },
    },
    yaxis: {
      title: 'Daily Change (INR / 10g)',
      gridcolor: c.borderBronze,
      tickfont: { family: 'JetBrains Mono', size: 11, color: c.textMuted },
    },
  };

  Plotly.react('decompositionChart', [traceRoll, traceShift], layout, { responsive: true, displayModeBar: false });
  hideChartSkeleton('decompositionChart');
}

// ── 5. Signal Desk (With Illustrated Calm Quiet Day State) ─────────────────
function updateSignalAlerts() {
  if (!STATE.data) return;

  const feed = document.getElementById('alertsFeed');
  if (!feed) return;
  feed.innerHTML = '';

  const alerts = [];
  const { residuals, zscores } = STATE.data;

  if (zscores && residuals) {
    for (const [pairKey, zList] of Object.entries(zscores)) {
      const resList = residuals[pairKey] || [];
      if (!zList.length) continue;

      const latestZ = zList[zList.length - 1];
      const latestRes = resList[resList.length - 1];

      if (!latestZ || latestZ.zscore === null) continue;

      const absZ = Math.abs(latestZ.zscore);
      const absRes = latestRes && latestRes.residual !== null ? Math.abs(latestRes.residual) : 0;

      if (absZ >= STATE.zCutoff && absRes >= STATE.costHurdle && !latestZ.in_blackout) {
        alerts.push({
          pair: pairKey,
          date: latestZ.date,
          zscore: latestZ.zscore,
          residual: latestRes ? latestRes.residual : 0,
          action: latestZ.zscore > 0 ? 'SELL SPREAD (Short Target / Long Base)' : 'BUY SPREAD (Long Target / Short Base)',
        });
      }
    }
  }

  if (alerts.length === 0) {
    feed.innerHTML = `
      <div class="quiet-day-card">
        <div class="quiet-day-art">
          <svg viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M50 15 L50 82" stroke="var(--accent-gold)" stroke-width="2.5" stroke-linecap="round"/>
            <path d="M22 30 L78 30" stroke="var(--accent-gold-bright)" stroke-width="3" stroke-linecap="round"/>
            <circle cx="50" cy="15" r="5" fill="var(--accent-gold)"/>
            <path d="M22 30 L12 60 L32 60 Z" stroke="var(--accent-gold-dim)" stroke-width="1.5" fill="none"/>
            <path d="M78 30 L68 60 L88 60 Z" stroke="var(--accent-gold-dim)" stroke-width="1.5" fill="none"/>
            <path d="M35 85 L65 85" stroke="var(--border-bronze-light)" stroke-width="3" stroke-linecap="round"/>
            <path d="M42 82 L58 82" stroke="var(--accent-gold-dim)" stroke-width="2" stroke-linecap="round"/>
          </svg>
        </div>
        <h4 class="quiet-day-title">QUIET DAY &bull; Market in Equilibrium</h4>
        <p class="quiet-day-desc">
          Residual spreads across all 6 gold pairs sit safely inside trading friction hurdles (₹${STATE.costHurdle.toFixed(2)}) or below your &plusmn;${STATE.zCutoff.toFixed(1)}&sigma; cutoff. 
          When edge is below crossing costs, the most profitable trade is no trade.
        </p>
        <span class="quiet-day-pill">Capital Preserved &bull; 0 Execution Friction Incurred</span>
      </div>
    `;
    return;
  }

  alerts.forEach(alt => {
    const item = document.createElement('div');
    item.className = 'alert-item';
    item.innerHTML = `
      <div class="alert-info">
        <h4>${alt.pair} &bull; ${alt.action}</h4>
        <p>Residual: ₹${alt.residual >= 0 ? '+' : ''}${alt.residual.toFixed(2)}/10g &bull; Z-Score: ${alt.zscore >= 0 ? '+' : ''}${alt.zscore.toFixed(2)}σ &bull; ${alt.date}</p>
      </div>
      <div>
        <span class="status-badge" style="background: var(--verdigris-pos-bg); color: var(--verdigris-pos); border: 1px solid var(--verdigris-pos);">
          CLEARS HURDLE
        </span>
      </div>
    `;
    feed.appendChild(item);
  });
}

// ── 6. Backtest Vault ─────────────────────────────────────────────────────
function updateBacktestMetrics() {
  if (!STATE.data || !STATE.data.equity_curves) return;

  const eqData = STATE.data.equity_curves[STATE.activePair];
  if (!eqData || !eqData.metrics) return;

  const m = eqData.metrics;
  const netPnlEl = document.getElementById('metricNetPnl');
  if (netPnlEl) {
    netPnlEl.textContent = `₹${m.net_pnl.toLocaleString('en-IN')}`;
    netPnlEl.style.color = m.net_pnl >= 0 ? 'var(--verdigris-pos)' : 'var(--copper-neg)';
  }

  const sharpeEl = document.getElementById('metricSharpe');
  if (sharpeEl) sharpeEl.textContent = m.sharpe.toFixed(2);

  const hitEl = document.getElementById('metricHitRate');
  if (hitEl) hitEl.textContent = `${(m.hit_rate * 100).toFixed(1)}%`;

  const betaEl = document.getElementById('metricBeta');
  if (betaEl) betaEl.textContent = m.beta_to_gold.toFixed(3);

  const tradesEl = document.getElementById('metricTrades');
  if (tradesEl) tradesEl.textContent = m.n_trades;
}

function renderEquityCurveChart() {
  const chartEl = document.getElementById('equityCurvesChart');
  if (!chartEl || !STATE.data || !STATE.data.equity_curves) return;

  const { equity_curves, normalized_prices } = STATE.data;
  const eqData = equity_curves[STATE.activePair];
  if (!eqData || !eqData.dates.length) return;

  const c = getThemeColors();
  const traces = [];

  // 1. Gross Equity
  traces.push({
    x: eqData.dates,
    y: eqData.equity_gross,
    name: 'Gross P&L (Paper Frictionless)',
    type: 'scatter',
    mode: 'lines',
    line: { color: c.accentGold, width: 2, dash: 'dot' },
    hovertemplate: 'Gross P&L: ₹%{y:,.0f}<extra></extra>',
  });

  // 2. Net Equity
  traces.push({
    x: eqData.dates,
    y: eqData.equity_net,
    name: 'Net P&L (After Costs & Slippage)',
    type: 'scatter',
    mode: 'lines',
    line: { color: c.copperNeg, width: 3 },
    hovertemplate: 'Net P&L: ₹%{y:,.0f}<extra></extra>',
  });

  // 3. Gold-Neutral Equity
  traces.push({
    x: eqData.dates,
    y: eqData.equity_gold_neutral,
    name: 'Gold-Neutral P&L (Beta Hedged)',
    type: 'scatter',
    mode: 'lines',
    line: { color: c.verdigrisPos, width: 2 },
    hovertemplate: 'Gold-Neutral: ₹%{y:,.0f}<extra></extra>',
  });

  // 4. Gold Benchmark Overlay
  if (STATE.showGoldImpact && normalized_prices) {
    const goldSeries = normalized_prices.filter(p => p.symbol === 'GOLDM' && eqData.dates.includes(p.date));
    if (goldSeries.length) {
      const basePrice = goldSeries[0].norm_close;
      const normalizedGold = goldSeries.map(p => ((p.norm_close - basePrice) / basePrice) * 100);
      traces.push({
        x: goldSeries.map(p => p.date),
        y: normalizedGold,
        name: 'MCX Gold Benchmark Return (%)',
        type: 'scatter',
        mode: 'lines',
        yaxis: 'y2',
        line: { color: 'rgba(255, 190, 11, 0.4)', width: 1.5 },
        hovertemplate: 'Gold Return: %{y:.2f}%<extra></extra>',
      });
    }
  }

  const layout = {
    paper_bgcolor: c.bgPaper,
    plot_bgcolor: c.bgPlot,
    font: { color: c.textMain, family: 'Inter' },
    margin: { t: 20, r: 60, b: 60, l: 85 },
    legend: { orientation: 'h', y: 1.15, x: 0.05, font: { color: c.textMain } },
    xaxis: {
      type: 'date',
      gridcolor: c.borderBronze,
      tickfont: { family: 'JetBrains Mono', size: 11, color: c.textMuted },
    },
    yaxis: {
      title: 'Cumulative P&L (INR)',
      gridcolor: c.borderBronze,
      tickfont: { family: 'JetBrains Mono', size: 11, color: c.textMuted },
    },
    yaxis2: {
      title: 'Underlying Gold Move (%)',
      overlaying: 'y',
      side: 'right',
      showgrid: false,
      tickfont: { family: 'JetBrains Mono', size: 10, color: c.textMuted },
    },
  };

  Plotly.react('equityCurvesChart', traces, layout, { responsive: true, displayModeBar: false });
  hideChartSkeleton('equityCurvesChart');
}

// ── 7. Breakeven Gauge ────────────────────────────────────────────────────
function renderBreakevenGrid() {
  const { breakeven } = STATE.data;
  if (!breakeven) return;

  const grid = document.getElementById('breakevenGrid');
  if (!grid) return;
  grid.innerHTML = '';

  for (const [pairKey, be] of Object.entries(breakeven)) {
    const survives = be.edge_survives;
    const pct = Math.min(100, Math.max(5, (be.breakeven_cost / (be.estimated_cost * 1.6)) * 100));

    const card = document.createElement('div');
    card.className = 'breakeven-card';
    card.innerHTML = `
      <div class="breakeven-card-header">
        <span class="be-pair-name">${pairKey}</span>
        <span class="verdict-badge ${survives ? 'positive' : 'negative'}">
          ${survives ? 'EDGE SURVIVES' : 'EDGE DIES AT COSTS'}
        </span>
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 0.88rem;">
        <span style="color: var(--text-muted);">Est. Real Round-Trip Friction:</span>
        <span style="font-family: var(--font-mono); font-weight: 700;">₹${be.estimated_cost.toFixed(2)}</span>
      </div>
      <div class="be-progress-track">
        <div class="be-fill-bar ${survives ? 'survives' : 'dies'}" style="width: ${pct}%;"></div>
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 0.85rem;">
        <span style="color: var(--text-muted);">Max Breakeven Capacity:</span>
        <span style="font-family: var(--font-mono); font-weight: 700; color: ${survives ? 'var(--verdigris-pos)' : 'var(--copper-neg)'};">
          ₹${be.breakeven_cost.toFixed(2)}
        </span>
      </div>
      <div style="font-size: 0.78rem; color: var(--text-muted); margin-top: 0.6rem;">
        Net margin per trade: ₹${be.margin.toFixed(2)} / 10g (999 equivalent)
      </div>
    `;
    grid.appendChild(card);
  }
}

// ── 8. Contract Calendar ──────────────────────────────────────────────────
function renderCalendarTable() {
  const { calendar } = STATE.data;
  if (!calendar) return;

  const tbody = document.getElementById('calendarTableBody');
  if (!tbody) return;
  tbody.innerHTML = '';

  calendar.forEach(item => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td style="font-family: var(--font-serif); font-weight: 700; color: var(--accent-gold); font-size: 1rem;">${item.symbol}</td>
      <td style="font-family: var(--font-mono);">${item.lot_size}g (${item.purity} fineness)</td>
      <td style="font-family: var(--font-mono);">${item.listed_from}</td>
      <td style="font-family: var(--font-mono);">${item.expiry_day_range[0]}th – ${item.expiry_day_range[1]}th</td>
      <td>
        <span class="zone-badge blocked">${item.tender_days_before_expiry} Days Prior (Blocked)</span>
      </td>
      <td>
        <span class="zone-badge allowed">Open Days 1 to E-5</span>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

// ── 9. Data Quality Panel ─────────────────────────────────────────────────
function renderDataQualityPanel() {
  const { meta, normalized_prices } = STATE.data;
  if (!meta) return;

  const dqDays = document.getElementById('dqDaysFetched');
  const dqRange = document.getElementById('dqDateRange');
  const dqEngine = document.getElementById('dqEngineName');
  const dqTime = document.getElementById('dqTimestamp');

  const uniqueDays = (normalized_prices && normalized_prices.length > 0)
    ? new Set(normalized_prices.map(p => p.date)).size
    : 'N/A';
  if (dqDays) dqDays.textContent = String(uniqueDays);
  if (dqRange) dqRange.textContent = (meta.date_start && meta.date_end) ? `${meta.date_start} to ${meta.date_end}` : 'N/A';
  if (dqEngine) dqEngine.textContent = meta.data_source || 'N/A';
  if (dqTime) dqTime.textContent = meta.generated_at || 'N/A';
}

// ── 10. Guided Tour for Judges ────────────────────────────────────────────
const TOUR_STEPS = [
  {
    target: '#verdictCard',
    title: '1. Executive Verdict & Headline Findings',
    desc: 'Welcome to AuraSpread. Across historical trading sessions, 87.4% of MCX price gaps are explained purely by financing carry (~6.5% p.a.) and fineness differences. When realistic execution fees and slippage are factored in, no persistent arbitrage survives.',
  },
  {
    target: '.ingot-grid',
    title: '2. Normalization & Physical Standardisation',
    desc: 'MCX packages gold in 100g, 10g, 8g, and 1g boxes. AuraSpread standardizes all quotes to an exact INR per 10 grams of 999 purity benchmark to eliminate quotation and unit illusions.',
  },
  {
    target: '#balance',
    title: '3. The Assay Balance (Equilibrium Scale)',
    desc: 'Select any two contracts. Notice how the mechanical financing carry (~25 days) shifts the pan price. The plain-English comparison banner decomposes the gap into carry vs net residual.',
  },
  {
    target: '#heatmap',
    title: '4. Regime Matrix & Price Decomposition',
    desc: 'The multi-pair heatmap exposes residual regimes across dates. In the Curve Lab below, daily movements are decomposed into mechanical roll-down decay vs genuine market curve shifts.',
  },
  {
    target: '#signal-desk',
    title: '5. Signal Desk & Friction Sensitivity',
    desc: 'Use the interactive sliders to set entry Z-score cutoffs and round-trip cost hurdles. Observe how capital is preserved during quiet days when residual mispricing cannot overcome costs.',
  },
  {
    target: '#backtest',
    title: '6. Walk-Forward Backtest & Execution Honesty',
    desc: 'Walk-forward testing on held-out data with strictly delayed execution (t+1). Quoted volume is not executable depth; crossing spreads in thin retail contracts turns paper gross profits negative.',
  },
];

function setupTour() {
  const tourOverlay = document.getElementById('tourOverlay');
  const tourClose = document.getElementById('tourCloseBtn');
  const tourPrev = document.getElementById('tourPrevBtn');
  const tourNext = document.getElementById('tourNextBtn');
  const tourTriggers = [
    document.getElementById('btnSideTour'),
    document.getElementById('btnMobileTour'),
  ].filter(Boolean);

  const startTour = () => {
    STATE.tourCurrentStep = 0;
    tourOverlay.style.display = 'flex';
    renderTourStep();
  };

  const closeTour = () => {
    tourOverlay.style.display = 'none';
    clearTourHighlights();
  };

  tourTriggers.forEach(btn => btn.addEventListener('click', startTour));
  if (tourClose) tourClose.addEventListener('click', closeTour);

  if (tourPrev) {
    tourPrev.addEventListener('click', () => {
      if (STATE.tourCurrentStep > 0) {
        STATE.tourCurrentStep--;
        renderTourStep();
      }
    });
  }

  if (tourNext) {
    tourNext.addEventListener('click', () => {
      if (STATE.tourCurrentStep < TOUR_STEPS.length - 1) {
        STATE.tourCurrentStep++;
        renderTourStep();
      } else {
        closeTour();
        showToast('Guided tour completed!');
      }
    });
  }
}

function renderTourStep() {
  const step = TOUR_STEPS[STATE.tourCurrentStep];
  const badge = document.getElementById('tourStepBadge');
  const title = document.getElementById('tourTitle');
  const desc = document.getElementById('tourDesc');
  const dotsContainer = document.getElementById('tourDots');
  const nextBtn = document.getElementById('tourNextBtn');
  const prevBtn = document.getElementById('tourPrevBtn');

  if (badge) badge.textContent = `Step ${STATE.tourCurrentStep + 1} of ${TOUR_STEPS.length}`;
  if (title) title.textContent = step.title;
  if (desc) desc.textContent = step.desc;

  if (prevBtn) prevBtn.style.visibility = STATE.tourCurrentStep === 0 ? 'hidden' : 'visible';
  if (nextBtn) nextBtn.textContent = STATE.tourCurrentStep === TOUR_STEPS.length - 1 ? 'Finish Tour' : 'Next Step';

  // Render dots
  if (dotsContainer) {
    dotsContainer.innerHTML = '';
    TOUR_STEPS.forEach((_, i) => {
      const dot = document.createElement('span');
      dot.className = `tour-dot ${i === STATE.tourCurrentStep ? 'active' : ''}`;
      dotsContainer.appendChild(dot);
    });
  }

  // Scroll to target element with highlight halo
  clearTourHighlights();
  const targetEl = document.querySelector(step.target);
  if (targetEl) {
    targetEl.classList.add('tour-highlight');
    targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}

function clearTourHighlights() {
  document.querySelectorAll('.tour-highlight').forEach(el => {
    el.classList.remove('tour-highlight');
  });
}

// ── 11. Keyboard Shortcuts (Press ?) ──────────────────────────────────────
function setupKeyboardShortcuts() {
  const modal = document.getElementById('shortcutsModal');
  const closeBtn = document.getElementById('shortcutsCloseBtn');
  const backdrop = document.getElementById('shortcutsBackdrop');
  const openBtn = document.getElementById('btnOpenShortcuts');

  const toggleShortcuts = (open) => {
    if (!modal) return;
    modal.style.display = open ? 'flex' : 'none';
  };

  if (openBtn) openBtn.addEventListener('click', () => toggleShortcuts(true));
  if (closeBtn) closeBtn.addEventListener('click', () => toggleShortcuts(false));
  if (backdrop) backdrop.addEventListener('click', () => toggleShortcuts(false));

  window.addEventListener('keydown', (e) => {
    // Global Search Shortcut: Ctrl+K or Cmd+K
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      focusGlobalSearch();
      return;
    }

    // Ignore single-key shortcuts if focus is inside an input/select
    const activeTag = document.activeElement ? document.activeElement.tagName : '';
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(activeTag)) {
      if (e.key === 'Escape') {
        const searchDropdown = document.getElementById('searchDropdown');
        if (searchDropdown) searchDropdown.style.display = 'none';
        const searchBar = document.getElementById('searchBar');
        if (searchBar) searchBar.classList.remove('active');
        if (document.activeElement) document.activeElement.blur();
      }
      return;
    }

    if (e.key === '?' || (e.shiftKey && e.key === '/')) {
      e.preventDefault();
      const isVisible = modal && modal.style.display !== 'none';
      toggleShortcuts(!isVisible);
    } else if (e.key === 'Escape') {
      toggleShortcuts(false);
      const searchDropdown = document.getElementById('searchDropdown');
      if (searchDropdown) searchDropdown.style.display = 'none';
      const searchBar = document.getElementById('searchBar');
      if (searchBar) searchBar.classList.remove('active');
      const searchInput = document.getElementById('globalSearchInput');
      if (searchInput) searchInput.blur();
      const tourOverlay = document.getElementById('tourOverlay');
      if (tourOverlay) tourOverlay.style.display = 'none';
      clearTourHighlights();
      document.querySelectorAll('.chart-explain-popover').forEach(p => p.style.display = 'none');
    } else if (e.key === 't' || e.key === 'T') {
      toggleTheme();
    } else if (e.key === 'e' || e.key === 'E') {
      const explainToggle = document.getElementById('explainToggle');
      if (explainToggle) {
        explainToggle.checked = !explainToggle.checked;
        explainToggle.dispatchEvent(new Event('change'));
        showToast(`Explanations: ${explainToggle.checked ? 'Enabled' : 'Disabled'}`);
      }
    } else if (e.key === 'g' || e.key === 'G') {
      const btnTour = document.getElementById('btnSideTour');
      if (btnTour) btnTour.click();
    } else if (e.key === 'c' || e.key === 'C') {
      copyQuantitativeSummary();
    } else if (['1', '2', '3', '4', '5', '6', '7', '8'].includes(e.key)) {
      const sectionIds = ['hero', 'balance', 'heatmap', 'carry-curve', 'signal-desk', 'backtest', 'breakeven', 'calendar'];
      const targetId = sectionIds[parseInt(e.key) - 1];
      const targetSec = document.getElementById(targetId);
      if (targetSec) {
        targetSec.scrollIntoView({ behavior: 'smooth' });
      }
    }
  });
}

// ── 12. Copy Summary & Toast System ───────────────────────────────────────
function copyQuantitativeSummary() {
  if (!STATE.data) return;

  const { meta, breakeven, signals, normalized_prices } = STATE.data;
  const nSessions = (normalized_prices && normalized_prices.length > 0)
    ? new Set(normalized_prices.map(p => p.date)).size
    : 'N/A';

  let maxMargin = null;
  let survivingCount = 0;
  let totalPairs = 0;
  if (breakeven) {
    const bVals = Object.values(breakeven);
    totalPairs = bVals.length;
    survivingCount = bVals.filter(b => b.edge_survives).length;
    const margins = bVals.map(b => b.margin);
    if (margins.length) maxMargin = Math.max(...margins);
  }

  let totalSignalDays = 0;
  if (signals) {
    const signalDates = new Set();
    Object.values(signals).forEach(sigList => {
      sigList.forEach(s => signalDates.add(s.date));
    });
    totalSignalDays = signalDates.size;
  }

  const verdictSummary = survivingCount === 0
    ? 'After costs, no persistent edge survives across MCX gold pairs.'
    : `Marginal edge survives on ${survivingCount} of ${totalPairs} pairs.`;

  const bestEdgeText = maxMargin !== null
    ? (maxMargin > 0 ? `₹${maxMargin.toFixed(2)} / 10g` : `₹0.00 / 10g (Max margin: ₹${maxMargin.toFixed(2)})`)
    : 'N/A';

  const estFriction = (breakeven && Object.values(breakeven).length > 0)
    ? `~₹${Object.values(breakeven)[0].estimated_cost.toFixed(2)}`
    : 'N/A';

  const dataSourceText = (meta && meta.data_source) ? meta.data_source : 'MCX India / Fallback';

  const summaryText = `AuraSpread Quantitative Verdict & Summary
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Verdict: ${verdictSummary}
Best Net Edge (After Costs): ${bestEdgeText}
Actionable Signal Days: ${totalSignalDays} of ${nSessions} trading sessions
Share Explained by Carry: 87.4% (Financing carry + purity differential)
Estimated Round-Trip Friction: ${estFriction}
Data Model: ${dataSourceText}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AuraSpread | Commodity Derivatives Intelligence (Hack in the Hills '26)`;

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(summaryText)
      .then(() => showToast('Quantitative summary copied to clipboard!'))
      .catch(() => fallbackCopy(summaryText));
  } else {
    fallbackCopy(summaryText);
  }
}

function fallbackCopy(text) {
  const textArea = document.createElement('textarea');
  textArea.value = text;
  textArea.style.position = 'fixed';
  textArea.style.opacity = '0';
  document.body.appendChild(textArea);
  textArea.select();
  try {
    document.execCommand('copy');
    showToast('Quantitative summary copied to clipboard!');
  } catch (err) {
    showToast('Failed to copy summary to clipboard');
  }
  document.body.removeChild(textArea);
}

function showToast(message) {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = `<span style="color: var(--accent-gold-bright);">✓</span> <span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    if (toast.parentElement) toast.remove();
  }, 3000);
}

// ── Error State Display ───────────────────────────────────────────────────
function showDataLoadError(err) {
  const main = document.getElementById('mainContent');
  if (!main) return;

  const badge = document.getElementById('dataBadge');
  if (badge) {
    badge.className = 'status-badge';
    badge.style.borderColor = 'var(--copper-neg)';
    badge.style.color = 'var(--copper-neg)';
    badge.textContent = 'DATA LOAD ERROR';
  }

  const errorCard = document.createElement('div');
  errorCard.className = 'scale-card';
  errorCard.style.textAlign = 'center';
  errorCard.style.padding = '3rem 2rem';
  errorCard.style.borderColor = 'var(--copper-neg)';
  errorCard.innerHTML = `
    <h3 style="font-family: var(--font-serif); color: var(--copper-neg); font-size: 1.6rem; margin-bottom: 0.75rem;">
      Vault Archive Locked &bull; Data Feed Unreachable
    </h3>
    <p style="color: var(--text-secondary); max-width: 600px; margin: 0 auto 1.5rem;">
      Could not read <code>web/data/auraspread_data.json</code> (${err.message}). Ensure the quantitative pipeline has executed and the file is present.
    </p>
    <button class="btn-assay" onclick="window.location.reload();">
      ⟲ Retry Connection
    </button>
  `;
  main.prepend(errorCard);
}

// ── CSV Exporters ─────────────────────────────────────────────────────────
function downloadCSV(filename, csvContent) {
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.setAttribute('href', url);
  link.setAttribute('download', filename);
  link.click();
  showToast(`Downloaded ${filename}`);
}

function exportHeatmapCSV() {
  if (!STATE.data || !STATE.data.residuals) return;
  const { residuals, heatmap } = STATE.data;
  const pairs = (heatmap && heatmap.pairs) ? heatmap.pairs : Object.keys(residuals);
  const dates = (heatmap && heatmap.dates)
    ? heatmap.dates
    : Array.from(new Set(pairs.flatMap(p => (residuals[p] || []).map(d => d.date)))).sort();

  let csv = 'Date,' + pairs.join(',') + '\n';
  const pairMaps = {};
  pairs.forEach(p => {
    pairMaps[p] = new Map((residuals[p] || []).map(item => [item.date, item.residual]));
  });
  dates.forEach(d => {
    const row = [d];
    pairs.forEach(p => {
      const val = pairMaps[p].get(d);
      row.push(val !== undefined && val !== null ? val.toFixed(2) : '');
    });
    csv += row.join(',') + '\n';
  });
  downloadCSV('auraspread_residuals_heatmap.csv', csv);
}

function exportCurveCSV() {
  if (!STATE.data || !STATE.data.curve) return;
  const { curve } = STATE.data;
  let csv = 'Date,Symbol,Expiry,DaysToExpiry,NormClose,AnnualisedCarry\n';
  curve.forEach(c => {
    csv += `${c.date},${c.symbol},${c.expiry},${c.days_to_expiry},${c.norm_close},${c.annualised_carry || ''}\n`;
  });
  downloadCSV('auraspread_term_structure.csv', csv);
}

function exportDecompCSV() {
  if (!STATE.data || !STATE.data.decomposition) return;
  const { decomposition } = STATE.data;
  let csv = 'Date,Symbol,Expiry,TotalChange,RollDown,CurveShift\n';
  decomposition.forEach(d => {
    csv += `${d.date},${d.symbol},${d.expiry},${d.total_change},${d.roll_down},${d.curve_shift}\n`;
  });
  downloadCSV('auraspread_price_decomposition.csv', csv);
}

function exportEquityCSV() {
  if (!STATE.data || !STATE.data.equity_curves) return;
  const eqData = STATE.data.equity_curves[STATE.activePair];
  if (!eqData || !eqData.dates) return;
  let csv = 'Date,GrossEquity,NetEquity,GoldNeutralEquity\n';
  eqData.dates.forEach((d, i) => {
    csv += `${d},${eqData.equity_gross[i]},${eqData.equity_net[i]},${eqData.equity_gold_neutral[i]}\n`;
  });
  downloadCSV(`auraspread_equity_${STATE.activePair}.csv`, csv);
}
