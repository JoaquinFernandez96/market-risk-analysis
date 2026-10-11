# Market Risk Analysis Dashboard: Argentine Trading Portfolio

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/streamlit-1.55+-red.svg)](https://streamlit.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An institutional-grade market risk management system and interactive dashboard for multi-asset trading portfolios focused on the Argentine financial market. The platform supports **BYMA Equities & CEDEARs**, **Argentine Sovereign Restructured Debt**, **Money Market / Liquidity**, and **Derivatives (Exchange-Traded & OTC)**.

The platform provides regulatory-grade risk analytics featuring a **Base VaR Scenario** and a **Stressed VaR (sVaR) Scenario** (calibrated to Argentine crisis regimes), Parametric, Historical Simulation, and Monte Carlo VaR models, Expected Shortfall (CVaR), bond duration/convexity analytics, option Greeks, and macroeconomic stress testing.

---

## Portfolio Structure & Asset Classes

The platform is designed to model multi-asset books across the primary instruments traded in the Argentine market (BYMA / MAE):

- **BYMA Equities & CEDEARs**: Liquid domestic blue chips (Energy, Banking, Utilities, Materials) and US-listed depositary receipts traded in ARS/USD.
- **Sovereign Debt (Bonares & Globales)**: Restructured sovereign bonds (e.g. `AL30`, `GD30`, `AL35`, `GD35`) characterized by semi-annual amortizations and step-up coupon profiles.
- **Money Market & Liquidity**: T+0 Money Market mutual funds (FCIs), cauciones bursátiles, and cash balances acting as risk-dampeners.
- **Derivatives (Listed & OTC)**: Matba Rofex currency futures, options on liquid stocks, currency forwards (NDFs), and BADLAR interest rate swaps.

All holdings, quantities, prices, and risk factors are dynamically loaded from an editable Excel file ([`input.xlsx`](input.xlsx)) or direct broker statement imports.

---

## Core Risk Engines

### 1. Base VaR vs. Stressed VaR (sVaR)
- **Base VaR Scenario**: Calibrated to standard trailing 252-day market dynamics (recent annualized volatilities: Equities 35–46%, Sovereign Debt 25–32%).
- **Stressed VaR (sVaR) Scenario**: Basel 2.5 / III compliant stressed calibration reflecting the 2019 PASO / 2020 default restructuring crisis. Volatilities expand by $1.8\times - 2.5\times$, correlation matrices spike toward 1.0 (breakdown of diversification), and returns exhibit heavy Student-$t$ fat tails ($\nu=4$).
- **Capital Add-On Buffer**: Computes the regulatory multiplier:
  $$\text{Capital} = 3 \times \max(\text{Base VaR}, \text{sVaR})$$

### 2. Multi-Methodology VaR & Expected Shortfall (CVaR)
- **Parametric (Variance-Covariance)**: Analytical normal distribution with full portfolio covariance matrix:
  $$\text{VaR}_\alpha(h) = z_\alpha \cdot \sqrt{w^T \Sigma w} \cdot \sqrt{h} \cdot V$$
- **Historical Simulation**: Empirical percentile distribution of historical multi-asset return vectors with non-parametric CVaR ($E[L \mid L > \text{VaR}]$).
- **Monte Carlo Simulation**: 10,000 correlated pseudo-random trajectories generated via Cholesky decomposition ($L = \text{chol}(\Sigma)$).
- **Component VaR (Euler Decomposition)**: Identifies the exact percentage contribution of each individual asset to total portfolio risk:
  $$\text{Component VaR}_i = w_i \cdot \frac{(\Sigma w)_i}{\sigma_p} \cdot z_\alpha \cdot V$$

### 3. Sovereign Bond Analytics
- Amortization cash flows and semi-annual step-up coupon structures for Argentine restructuring debt (`GD30`, `AL30`, `GD35`, `AL35`, `GD38`).
- Analytical Macaulay Duration, Modified Duration, Convexity, and DV01 sensitivity.
- Second-order Taylor series approximation for non-linear yield curve shifts:
  $$\frac{\Delta P}{P} \approx -D_{\text{mod}} \cdot \Delta y + \frac{1}{2} C \cdot (\Delta y)^2$$

### 4. Derivatives Pricing & Greeks
- Analytical Black-Scholes-Merton model for European options (`GGAL` Call & Put) computing Delta ($\Delta$), Gamma ($\Gamma$), Vega ($\mathcal{V}$), Theta ($\Theta$), and Rho ($\rho$).
- Linear Delta modeling for Matba Rofex FX Futures and OTC NDF forwards.
- Floating-rate sensitivity and DV01 for BADLAR Interest Rate Swaps.

### 5. Macro Scenario Stress Testing
Pre-configured historical crisis replays and interactive factor sliders:
- **2019 PASO Primary Election Shock**: Black Monday replay (-48% equities, +1,500 bps bond spread, +30% FX devaluation).
- **2020 Global COVID & Debt Restructuring**: Severe liquidity freeze and sovereign debt markdown.
- **2023 Post-Primary Devaluation**: Sudden currency jump with equity inflation hedge.
- **Global Emerging Market Stagflation**: Contraction in EM flows and US rate hike.

### 6. Modern Portfolio Theory (MPT) & Markowitz Efficient Frontier
- **Multi-Asset Return & Volatility Modeling**: Models annualized expected returns ($\mu_i$), volatilities ($\sigma_i$), and positive-definite covariance matrices ($\boldsymbol{\Sigma}$) across **Core CEDEARs**, **High-Beta CEDEARs**, **Fixed Income / Carry** (Boncaps, Lecaps, Sovereign Bonds), and **Money Market FCIs**, backed by the persistent local `yfinance` disk cache.
- **Markowitz Optimization (`scipy.optimize.minimize`)**: Computes the **Maximum Sharpe Ratio (Tangency) Portfolio** and **Global Minimum Volatility Portfolio** subject to long-only allocation constraints ($\sum w_i = 1, w_i \ge 0$).
- **Interactive Frontier & Capital Allocation Line (CAL)**: Plots weight-scaled instrument bubbles against the Efficient Frontier boundary and the tangent CAL originating from the configurable Risk-Free Rate ($R_f$).

### 7. Persistent Local Market Data Cache (`yfinance` + Granular Fallback)
- **Daily TTL & Zero-Redundancy Sync (`data/cache/market_returns_cache.csv`)**: Stores 504 trading days of split- and dividend-adjusted daily returns locally on disk (git-ignored). Subsequent launches on the same day make **0 API calls**, and adding a new stock triggers a **delta-only fetch** for that single ticker.
- **Revision-Safe Full-Window Overwrite (`period="2y", auto_adjust=True`)**: Overwrites the full 2-year column per refreshed ticker in a single batched request so retroactive stock splits, dividends, and exchange price revisions never introduce boundary crash seams.
- **Granular Per-Ticker Priors**: Non-Yahoo local instruments (Boncaps, Lecaps, Sovereign Debt, Money Market FCIs, OTC Derivatives) and offline runs use calibrated per-ticker volatilities and category-aware correlations.

---

## User Guide: Monthly Risk Presentation Walkthrough

This guide explains how to operate the system, update monthly holdings, and run presentations step by step.

### 1. Updating Your Monthly Portfolio (`input.xlsx`)
Whenever your trading book changes at month-end:
1. Open [`input.xlsx`](input.xlsx) in Microsoft Excel.
2. Update the tabs as needed:
   - **`Equities`**: Update share quantities or prices in USD/ARS. If you swap or add a stock (e.g. adding `ALUA.BA` or `CEPU.BA`), just insert a row.
   - **`Bonds`**: Update clean prices or nominal amounts for your Argentine sovereign bonds.
   - **`Derivatives`**: Adjust contract quantities, option strikes, FX futures notionals, or swap terms.
   - **`Settings`**: Update the **USD/ARS CCL Rate**, **Reporting Month** label (e.g. `October 2026`), and default VaR parameters.
3. Save the file. The dashboard will automatically reflect the changes upon reload.

### 2. Launching & Presenting the Dashboard
Open your terminal in the project directory and execute:
```bash
streamlit run app.py
```
Your browser will open `http://localhost:8501`.

### 3. How to Present to Stakeholders
- **Sidebar Controls**:
  - **Live Excel / CSV Uploader**: You can upload a new `input.xlsx` or broker `portfolio_report.csv` file directly in the browser during a meeting without restarting the application.
  - **Currency Toggle**: Switch instantaneously between **USD ($)** and **ARS ($)** using the live CCL/MEP exchange rate.
  - **MPT & VaR Controls**: Adjust the Risk-Free Rate ($R_f$), filter asset universes (`All Assets`, `CEDEARs Only`, `Optimal Allocations`), and switch between **95% 1-Day** and **99% 10-Day** VaR horizons.
- **Tab-by-Tab Presentation Flow**:
  1. **📊 Portfolio Overview**: Show total portfolio NAV, asset class allocation pie chart, and individual position weights.
  2. **🎯 MPT Risk-Return Frontier**: Inspect the portfolio's position relative to the Markowitz Efficient Frontier and Capital Allocation Line (CAL), compare Current Sharpe vs. Target Max Sharpe, and review optimal weight rebalancing.
  3. **⚡ VaR Analysis (Base vs. Stressed)**: Highlight the **Base VaR** vs. **Stressed VaR (sVaR)** cards, the **Stress Multiplier**, the regulatory capital buffer, and the loss distribution histograms with tail cutoff lines.
  4. **📑 VaR Supporting Schedules**: Inspect the historical market value evolution ($) per asset in dual currencies (USD & ARS), visualize asset trajectories, review the parametric Covariance/Correlation matrices, and click **"📥 Download Supporting Schedules"** to export `var_supporting_schedules.xlsx`.
  5. **🏛️ Fixed Income**: Review the sovereign yield curve, portfolio modified duration, and test yield shifts ($\pm 200$ bps) using the parallel shift slider.
  6. **📈 Derivatives**: Review total USD Delta, options Vega, Theta decay, and the combined collar/put protection payoff curve.
  7. **🌪️ Stress Testing**: Replay historical Argentine shocks (2019 PASO Black Monday, 2020 Restructuring, 2023 Devaluation) to demonstrate book drawdown resilience.

---

## VaR Supporting Schedules & Excel Audit Export

The platform features an audit-ready schedule generator producing a downloadable 6-tab Excel workbook (`var_supporting_schedules.xlsx`):

- **`Base_Market_Values`**: Daily historical market value series per asset and Total Portfolio NAV in parallel **USD ($)** and **ARS ($)** columns.
- **`Base_Returns_PnL`**: Daily returns (%) and daily dollar PnL ($ USD and $ ARS) for every individual position.
- **`Stressed_Market_Values`**: Dual-currency daily market value evolution under the stressed crisis regime.
- **`Stressed_Returns_PnL`**: Stressed daily percentage returns and dollar PnL series.
- **`Parametric_Risk_Matrix`**: Annualized Covariance Matrix, Correlation Matrix, and Euler Component VaR risk attribution.
- **`VaR_CVaR_Tail_Audit`**: Ranked empirical tail losses exceeding the VaR threshold, showing the Expected Shortfall (CVaR) calculation step-by-step.

---

## Monthly Portfolio Updates via `input.xlsx`

The system is fully modular and allows risk managers to update holdings, prices, notionals, and risk parameters every month through an Excel spreadsheet:

### Workbook Tabs
1. **`Equities`**: BYMA stock tickers, quantities, unit prices, market values, sectors, and betas.
2. **`Bonds`**: Argentine sovereign debt issues, nominal quantities, clean prices, maturities, coupons, YTMs, duration, and convexity.
3. **`Derivatives`**: Listed & OTC contracts (Rofex Futures, Options, NDFs, Interest Rate Swaps) with notionals, MTM values, and Greeks.
4. **`Settings`**: Monthly reporting cycle, USD/ARS CCL rate, default confidence levels, holding horizon, and stress multipliers.

### Updating Workflow
- Edit `input.xlsx` in Excel and save. The dashboard will automatically read the updated holdings upon reload.
- Alternatively, upload any `.xlsx` or broker `.csv` file directly into the **Sidebar File Uploader** during monthly presentations without restarting the application.
- Click **"📥 Download Template (input.xlsx)"** in the sidebar to export the working format.

---

## Installation & Running

### Prerequisites
- Python 3.10+ (tested on Python 3.13)
- Git

### Setup
```bash
# Clone the repository
git clone https://github.com/JoaquinFernandez96/market-risk-analysis.git
cd market-risk-analysis

# Install dependencies
pip install -r requirements.txt

# (Optional) Install development dependencies for testing
pip install -r requirements-dev.txt
```

### Launch the Dashboard
```bash
streamlit run app.py
```

The interactive dashboard will open at `http://localhost:8501`.

### Running Unit Tests
```bash
pytest -v
```

---

## Project Structure
```
market-risk-analysis/
├── app.py                      # Interactive Streamlit dashboard
├── input.xlsx                  # Master Excel workbook for monthly updates
├── input_institutional.xlsx    # Institutional $10M trading book preset
├── create_template_excel.py    # Generator script for master input workbook
├── requirements.txt            # Runtime Python dependencies
├── requirements-dev.txt        # Developer & test suite dependencies
├── README.md                   # System documentation & math formulation
├── .gitignore                  # Git exclusions & financial data privacy rules
├── src/
│   ├── portfolio/
│   │   ├── models.py           # Portfolio & Position data models
│   │   ├── excel_loader.py     # Parser for input.xlsx workbooks & broker CSVs
│   │   └── __init__.py
│   ├── pricing/
│   │   ├── bonds.py            # Argentine sovereign debt pricer & duration
│   │   ├── derivatives.py      # Black-Scholes, Greeks & OTC derivatives
│   │   └── __init__.py
│   ├── data/
│   │   ├── loader.py           # Base & Stressed market return generators
│   │   └── __init__.py
│   └── risk/
│       ├── mpt_optimizer.py    # Modern Portfolio Theory & Markowitz optimizer
│       ├── var_engine.py       # Base vs Stressed VaR, CVaR, Component VaR
│       ├── schedules.py        # Audit-ready time-series & Excel schedule builder
│       ├── stress_testing.py   # Historical crisis scenarios & factor shocks
│       └── __init__.py
└── tests/
    ├── test_excel_loader.py    # Unit tests for Excel/CSV loading & dynamic assets
    ├── test_mpt_optimizer.py   # Unit tests for MPT engine & Markowitz frontier
    ├── test_pricing.py         # Unit tests for bonds, options, and Greeks
    ├── test_risk.py            # Unit tests for VaR, CVaR, and stress engine
    └── test_schedules.py       # Unit tests for VaR supporting schedules
```

---

## License
MIT License. Developed for quantitative market risk analysis.

