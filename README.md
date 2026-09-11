# Market Risk Analysis Dashboard: Argentine Trading Portfolio

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/streamlit-1.55+-red.svg)](https://streamlit.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An institutional-grade market risk management system and interactive dashboard for a multi-asset trading portfolio focused on the Argentine financial market. The book is structured with 15 realistic positions spanning **BYMA Equities**, **Argentine Sovereign Restructured Debt**, and **Derivatives (Exchange-Traded & OTC)**.

The platform provides regulatory-grade risk analytics featuring a **Base VaR Scenario** and a **Stressed VaR (sVaR) Scenario** (calibrated to Argentine crisis regimes), Parametric, Historical Simulation, and Monte Carlo VaR models, Expected Shortfall (CVaR), bond duration/convexity analytics, option Greeks, and macroeconomic stress testing.

---

## Portfolio Structure (\$10,000,000 USD NAV)

| Asset Class | Ticker | Name | Market Value (USD) | Weight (%) | Risk Factors & Characteristics |
|---|---|---|---|---|---|
| **Equities** (BYMA) | `YPFD.BA` | YPF S.A. Cl D | \$800,000 | 8.0% | Vaca Muerta oil & gas leader; high liquidity |
| | `GGAL.BA` | Grupo Financiero Galicia | \$800,000 | 8.0% | Benchmark Argentine banking stock; high beta |
| | `PAMP.BA` | Pampa Energía S.A. | \$500,000 | 5.0% | Integrated energy & utility |
| | `BMA.BA` | Banco Macro S.A. | \$500,000 | 5.0% | Commercial banking; monetary sensitivity |
| | `TXAR.BA` | Ternium Argentina S.A. | \$400,000 | 4.0% | Industrial exporter & steel producer |
| **Sovereign Debt** | `GD30` | Global USD 2030 (NY Law) | \$1,200,000 | 12.0% | Liquid benchmark restructuring bond; Mod Dur: 2.63 |
| | `AL30` | Bonar USD 2030 (Local Law) | \$1,200,000 | 12.0% | Benchmark local law bond; Mod Dur: 2.56 |
| | `GD35` | Global USD 2035 (NY Law) | \$1,000,000 | 10.0% | Intermediate sovereign tenor; Mod Dur: 4.98 |
| | `AL35` | Bonar USD 2035 (Local Law) | \$800,000 | 8.0% | Local law intermediate tenor; Mod Dur: 4.82 |
| | `GD38` | Global USD 2038 (NY Law) | \$800,000 | 8.0% | Long-end bond with high convexity (44.8) |
| **Derivatives** | `ROFEX_DLR_3M` | Rofex USD/ARS 3M Futures | \$450,000 | 4.5% | \$1.5M Notional FX hedge; 1.0 Delta to USD/ARS |
| | `GGAL_C_ATM` | GGAL 45D ATM Call Option | \$420,000 | 4.2% | Delta: 0.54, Vega: \$980/pt, Gamma: 0.082 |
| | `GGAL_P_OTM` | GGAL 45D OTM Protective Put | \$280,000 | 2.8% | Delta: -0.28, Downside crash protection |
| | `USD_ARS_NDF_6M` | OTC USD/ARS 6M NDF | \$450,000 | 4.5% | \$1.2M Notional OTC currency forward |
| | `BADLAR_IRS_1Y` | OTC BADLAR 1Y Interest Rate Swap| \$400,000 | 4.0% | Pay Fixed / Rec Float; DV01: \$185/bp |

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
  - **Live Excel Uploader**: You can upload a new `input.xlsx` file directly in the browser during a meeting without restarting the application.
  - **Currency Toggle**: Switch instantaneously between **USD ($)** and **ARS ($)** using the live CCL exchange rate.
  - **Regulatory Confidence & Horizon**: Switch between **95% 1-Day** (internal risk limit) and **99% 10-Day** (Basel regulatory capital standard).
- **Tab-by-Tab Presentation Flow**:
  1. **📊 Overview**: Show total portfolio NAV (\$10.0M USD), asset class allocation pie chart, and individual position weights.
  2. **⚡ VaR Analysis (Base vs. Stressed)**: Highlight the **Base VaR** vs. **Stressed VaR (sVaR)** cards, the **Stress Multiplier**, the regulatory capital buffer, and the loss distribution histograms with tail cutoff lines.
  3. **📑 VaR Supporting Schedules**: Inspect the historical market value evolution ($) per asset in dual currencies (USD & ARS), visualize asset trajectories, review the parametric Covariance/Correlation matrices, and click **"📥 Download Supporting Schedules"** to export `var_supporting_schedules.xlsx`.
  4. **🏛️ Fixed Income**: Review the sovereign yield curve, portfolio modified duration, and test yield shifts ($\pm 200$ bps) using the parallel shift slider.
  5. **📈 Derivatives**: Review total USD Delta, options Vega, Theta decay, and the combined collar/put protection payoff curve.
  6. **🌪️ Stress Testing**: Replay historical Argentine shocks (2019 PASO Black Monday, 2020 Restructuring, 2023 Devaluation) to demonstrate book drawdown resilience.

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
- Alternatively, upload any `.xlsx` file directly into the **Sidebar File Uploader** during monthly presentations without restarting the application.
- Click **"📥 Download Template (input.xlsx)"** in the sidebar to export the working format.

---

## Installation & Running

### Prerequisites
- Python 3.10+ (tested on Python 3.13)
- Git

### Setup
```bash
# Clone the repository (Private)
git clone https://github.com/JoaquinFernandez96/market-risk-analysis.git
cd market-risk-analysis

# Install dependencies
pip install -r requirements.txt
```

### Launch the Dashboard
```bash
streamlit run app.py
```

The interactive dashboard will open at `http://localhost:8501`.

### Running Unit Tests
```bash
pytest -v tests/
```

---

## Project Structure
```
market-risk-analysis/
├── app.py                      # Interactive Streamlit dashboard
├── input.xlsx                  # Master Excel workbook for monthly updates
├── create_template_excel.py    # Generator script for master input workbook
├── requirements.txt            # Python dependencies
├── README.md                   # System documentation & math formulation
├── .gitignore                  # Git exclusions
├── src/
│   ├── portfolio/
│   │   ├── models.py           # Portfolio & Position data models
│   │   ├── excel_loader.py     # Parser for input.xlsx workbooks & buffers
│   │   └── __init__.py
│   ├── pricing/
│   │   ├── bonds.py            # Argentine sovereign debt pricer & duration
│   │   ├── derivatives.py      # Black-Scholes, Greeks & OTC derivatives
│   │   └── __init__.py
│   ├── data/
│   │   ├── loader.py           # Base & Stressed market return generators
│   │   └── __init__.py
│   └── risk/
│       ├── var_engine.py       # Base vs Stressed VaR, CVaR, Component VaR
│       ├── stress_testing.py   # Historical crisis scenarios & factor shocks
│       └── __init__.py
└── tests/
    ├── test_excel_loader.py    # Unit tests for Excel workbook loading & dynamic assets
    ├── test_pricing.py         # Unit tests for bonds, options, and Greeks
    └── test_risk.py            # Unit tests for VaR, CVaR, and stress engine
```

---

## License
MIT License. Developed for quantitative market risk analysis.
