import os
import streamlit as st
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.portfolio.models import create_default_portfolio, AssetClass
from src.portfolio.excel_loader import load_portfolio_from_excel, get_excel_template_bytes, DEFAULT_SETTINGS
from src.pricing.bonds import ArgentineBondPricer
from src.pricing.derivatives import DerivativesRiskEngine, BlackScholesOption
from src.risk.var_engine import VaREngine
from src.risk.stress_testing import StressTestEngine
from src.risk.mpt_optimizer import (
    MPTOptimizer,
    MPT_CATEGORY_CORE_CEDEAR,
    MPT_CATEGORY_HIGH_BETA,
    MPT_CATEGORY_FIXED_INCOME,
    MPT_CATEGORY_CASH_FCI,
)
from src.risk.schedules import (
    generate_market_value_evolution,
    generate_returns_pnl_schedule,
    generate_parametric_audit_schedules,
    generate_tail_loss_audit_schedule,
    build_var_supporting_excel
)


# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Market Risk Dashboard | Argentine Trading Book",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS styling for an institutional Bloomberg / Aladdin dark-modern aesthetic
st.markdown("""
<style>
    .metric-card {
        background-color: #1e222d;
        border-radius: 8px;
        padding: 16px;
        border-left: 4px solid #3b82f6;
        margin-bottom: 12px;
    }
    .metric-card-stress {
        background-color: #2b181b;
        border-radius: 8px;
        padding: 16px;
        border-left: 4px solid #ef4444;
        margin-bottom: 12px;
    }
    .metric-title {
        font-size: 0.85rem;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 4px;
    }
    .metric-value {
        font-size: 1.55rem;
        font-weight: 700;
        color: #f8fafc;
    }
    .metric-sub {
        font-size: 0.80rem;
        color: #64748b;
        margin-top: 4px;
    }
</style>
""", unsafe_allow_html=True)


# --- SIDEBAR: MONTHLY DATA SOURCE (EXCEL) ---
st.sidebar.image("https://img.icons8.com/fluency/96/bullish.png", width=64)
st.sidebar.title("Portfolio Settings")

st.sidebar.markdown("### 📁 Monthly Data Source")
source_options = []
if os.path.exists("input_cocos.xlsx") or os.path.exists("COCOS/input_cocos.xlsx"):
    source_options.append("input_cocos.xlsx (Cocos Capital Portfolio)")
if os.path.exists("portfolio_report.csv"):
    source_options.append("portfolio_report.csv (Raw Broker CSV)")
if os.path.exists("COCOS/portfolio_report.csv"):
    source_options.append("COCOS/portfolio_report.csv (Raw Broker CSV)")
if os.path.exists("COCOS/portfolio_report_20260910.csv"):
    source_options.append("COCOS/portfolio_report_20260910.csv (Raw Broker CSV)")
if os.path.exists("input.xlsx"):
    source_options.append("input.xlsx (Active Portfolio)")
if os.path.exists("input_institutional.xlsx"):
    source_options.append("input_institutional.xlsx (Institutional $10M Book)")
source_options.append("Upload File (Excel / CSV)")

active_source_sel = st.sidebar.selectbox("Select Active Portfolio", source_options, index=0)

if active_source_sel == "Upload File (Excel / CSV)":
    uploaded_file = st.sidebar.file_uploader("Upload Monthly File (`.xlsx` or `.csv`)", type=["xlsx", "xls", "csv"])
    if uploaded_file is not None:
        portfolio, settings = load_portfolio_from_excel(uploaded_file)
        source_label = f"Uploaded `{uploaded_file.name}`"
    else:
        portfolio, settings = load_portfolio_from_excel("input_cocos.xlsx" if os.path.exists("input_cocos.xlsx") else "input.xlsx")
        source_label = "Local Default File (waiting for upload)"
elif "input_cocos" in active_source_sel:
    target = "input_cocos.xlsx" if os.path.exists("input_cocos.xlsx") else "COCOS/input_cocos.xlsx"
    portfolio, settings = load_portfolio_from_excel(target)
    source_label = "Cocos Capital Excel (input_cocos.xlsx)"
elif "CSV" in active_source_sel:
    csv_target = active_source_sel.split(" (")[0].strip()
    portfolio, settings = load_portfolio_from_excel(csv_target)
    source_label = f"Broker CSV ({csv_target})"
elif "institutional" in active_source_sel:
    portfolio, settings = load_portfolio_from_excel("input_institutional.xlsx")
    source_label = "Institutional $10M Book"
else:
    portfolio, settings = load_portfolio_from_excel("input.xlsx")
    source_label = "Local `input.xlsx`"

st.sidebar.success(f"**Source**: {source_label}\n\n**Cycle**: {settings.get('Reporting_Month', 'Monthly')}")

# Download template buttons
if os.path.exists("input_cocos.xlsx"):
    with open("input_cocos.xlsx", "rb") as f:
        cocos_xlsx_bytes = f.read()
    st.sidebar.download_button(
        label="📥 Download Cocos Input (input_cocos.xlsx)",
        data=cocos_xlsx_bytes,
        file_name="input_cocos.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="Download your Cocos Capital portfolio formatted as a master input spreadsheet."
    )

template_bytes = get_excel_template_bytes()
st.sidebar.download_button(
    label="📥 Download Template (input.xlsx)",
    data=template_bytes,
    file_name="input.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    help="Download formatted Excel workbook template to update monthly holdings and parameters."
)

st.sidebar.markdown("---")
st.sidebar.markdown("### Currency & Valuation")
default_ccl = float(settings.get("USD_ARS_CCL_Rate", 1280.0))
fx_rate = st.sidebar.number_input("USD/ARS CCL / MEP Rate", min_value=500.0, max_value=5000.0, value=default_ccl, step=10.0)
if abs(fx_rate - default_ccl) > 1e-3:
    portfolio.revalue_with_ccl(fx_rate)

curr_view = st.sidebar.radio("Display Currency", ["USD ($)", "ARS ($)"], horizontal=True)
curr_mult = fx_rate if curr_view == "ARS ($)" else 1.0
curr_sym = "ARS $" if curr_view == "ARS ($)" else "USD $"

var_engine = VaREngine(portfolio)
stress_engine = StressTestEngine(portfolio)

st.sidebar.markdown("---")
st.sidebar.markdown("### Dashboard Mode & Sizing")
dashboard_mode = st.sidebar.radio(
    "Dashboard View Mode",
    ["👤 Private / Retail Investor", "🏦 Institutional / Quant Desk"],
    index=0,
    help="Switch between intuitive retail takeaways vs institutional Basel II.5 capital metrics and Greeks."
)
is_retail = "Retail" in dashboard_mode

scale_choice = st.sidebar.selectbox(
    "Portfolio Scale / Sizing Preset",
    ["From Input File (100%)", "Retail Scale ($50,000 USD)", "Private Wealth ($100,000 USD)", "Micro Retail ($10,000 USD)", "Institutional ($10,000,000 USD)"],
    index=0,
    help="Scales all holdings proportionally in memory to visualize risk at different portfolio net worths."
)
if scale_choice == "Retail Scale ($50,000 USD)":
    portfolio = portfolio.scale_to_nav(50_000.0)
    var_engine = VaREngine(portfolio)
elif scale_choice == "Private Wealth ($100,000 USD)":
    portfolio = portfolio.scale_to_nav(100_000.0)
    var_engine = VaREngine(portfolio)
elif scale_choice == "Micro Retail ($10,000 USD)":
    portfolio = portfolio.scale_to_nav(10_000.0)
    var_engine = VaREngine(portfolio)
elif scale_choice == "Institutional ($10,000,000 USD)":
    portfolio = portfolio.scale_to_nav(10_000_000.0)
    var_engine = VaREngine(portfolio)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🎯 MPT & Frontier Settings")
rf_rate_pct = st.sidebar.slider(
    "Risk-Free Rate (R_f %)",
    min_value=0.0,
    max_value=12.0,
    value=4.2,
    step=0.1,
    help="US 10Y Treasury / Risk-Free Rate benchmark used for Sharpe Ratio and Capital Allocation Line."
)
mpt_sidebar_filter = st.sidebar.selectbox(
    "MPT Asset Universe Filter",
    options=["All Assets", "CEDEARs Only", "Optimal Allocations"],
    index=0,
    help="Filter the MPT Risk-Return Frontier view across all holdings, Equity/CEDEARs only, or optimal Markowitz allocations."
)

st.sidebar.markdown("---")
st.sidebar.markdown("### VaR Configuration")
default_conf = float(settings.get("Default_Confidence_Level", 0.95))
conf_options = [0.90, 0.95, 0.975, 0.99, 0.999]
conf_index = conf_options.index(default_conf) if default_conf in conf_options else 1
conf_level = st.sidebar.select_slider(
    "Confidence Level (α)",
    options=conf_options,
    value=conf_options[conf_index],
    format_func=lambda x: f"{x * 100:.1f}%"
)

default_horizon = int(settings.get("Default_Holding_Period_Days", 1))
horizon_options = [1, 5, 10, 21]
h_index = horizon_options.index(default_horizon) if default_horizon in horizon_options else 0
horizon_days = st.sidebar.selectbox(
    "Holding Period Horizon",
    options=horizon_options,
    index=h_index,
    format_func=lambda d: f"{d} Day{'s' if d > 1 else ''} ({'Basel standard' if d == 10 else ('1 Month' if d == 21 else ('1 Week' if d == 5 else 'Daily'))})"
)

st.sidebar.markdown("---")
num_eq = len(portfolio.get_positions_by_class(AssetClass.EQUITY))
num_bd = len(portfolio.get_positions_by_class(AssetClass.BOND))
num_cash = len(portfolio.get_positions_by_class(AssetClass.CASH))
num_der = len(portfolio.get_positions_by_class(AssetClass.DERIVATIVE))
st.sidebar.info(
    f"💡 **Active Portfolio Book**: {len(portfolio.positions)} Positions\n\n"
    f"• **Equities & Cedears**: {num_eq} positions\n"
    f"• **Bonds & Debt**: {num_bd} positions\n"
    f"• **Cash & Liquidity**: {num_cash} positions\n"
    f"• **Derivatives**: {num_der} contracts"
)


# --- TOP BANNER METRICS ---
comparison = var_engine.run_scenario_comparison(confidence_level=conf_level, horizon_days=horizon_days)

# Component breakdown for top risk identification
comp_breakdown = var_engine.get_component_var_breakdown(conf_level, horizon_days, scenario="base")
top_risk_ticker = comp_breakdown.iloc[0]["Ticker"] if not comp_breakdown.empty else "N/A"
top_risk_pct = comp_breakdown.iloc[0]["% Risk Contribution"] if not comp_breakdown.empty else 0.0

div_benefit_val = comparison["comparison"]["diversification_benefit_dollar"] * curr_mult
div_benefit_pct = comparison["comparison"]["diversification_benefit_pct"]

st.title(f"{'👤' if is_retail else '🏛️'} Argentine {'Investor' if is_retail else 'Trading'} Portfolio - Market Risk Analysis")
st.markdown(
    f"**{'Private Investor Dashboard' if is_retail else 'Institutional Trading Desk'}** | Portfolio: **{portfolio.name}** | Base Regime vs. **Stressed VaR (sVaR)** | Horizon: **{horizon_days}d** | Confidence: **{conf_level*100:.1f}%**"
)

kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)

port_val = portfolio.total_value * curr_mult
base_var = comparison["base"]["historical"]["var_dollar"] * curr_mult
base_pct = comparison["base"]["historical"]["var_pct"]
stress_var = comparison["stress"]["historical"]["var_dollar"] * curr_mult
stress_pct = comparison["stress"]["historical"]["var_pct"]

if is_retail:
    with kpi1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Portfolio Net Worth</div>
            <div class="metric-value">{curr_sym} {port_val:,.0f}</div>
            <div class="metric-sub">{len(portfolio.positions)} Active Positions</div>
        </div>
        """, unsafe_allow_html=True)

    with kpi2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Bad Day Risk ({conf_level*100:.0f}%)</div>
            <div class="metric-value" style="color: #f87171;">-{curr_sym} {base_var:,.0f}</div>
            <div class="metric-sub">Max loss in 19 of 20 days ({base_pct:.2f}%)</div>
        </div>
        """, unsafe_allow_html=True)

    with kpi3:
        st.markdown(f"""
        <div class="metric-card-stress">
            <div class="metric-title">Crisis Stress (2019 PASO)</div>
            <div class="metric-value" style="color: #fbbf24;">-{curr_sym} {stress_var:,.0f}</div>
            <div class="metric-sub" style="color: #fde68a;">Severe crash loss ({stress_pct:.2f}%)</div>
        </div>
        """, unsafe_allow_html=True)

    with kpi4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Top Risk Driver</div>
            <div class="metric-value" style="color: #60a5fa;">{top_risk_ticker}</div>
            <div class="metric-sub">{top_risk_pct:.1f}% of total portfolio risk</div>
        </div>
        """, unsafe_allow_html=True)

    with kpi5:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Diversification Shield</div>
            <div class="metric-value" style="color: #34d399;">+{curr_sym} {div_benefit_val:,.0f}</div>
            <div class="metric-sub">{div_benefit_pct:.1f}% risk reduction vs standalone</div>
        </div>
        """, unsafe_allow_html=True)
else:
    with kpi1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Portfolio NAV</div>
            <div class="metric-value">{curr_sym} {port_val:,.0f}</div>
            <div class="metric-sub">{len(portfolio.positions)} Book Positions</div>
        </div>
        """, unsafe_allow_html=True)

    with kpi2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Base VaR (Hist {conf_level*100:.1f}%)</div>
            <div class="metric-value">{curr_sym} {base_var:,.0f}</div>
            <div class="metric-sub">{base_pct:.2f}% of NAV | {horizon_days}d horizon</div>
        </div>
        """, unsafe_allow_html=True)

    with kpi3:
        st.markdown(f"""
        <div class="metric-card-stress">
            <div class="metric-title">Stressed VaR (sVaR)</div>
            <div class="metric-value" style="color: #f87171;">{curr_sym} {stress_var:,.0f}</div>
            <div class="metric-sub" style="color: #fca5a5;">{stress_pct:.2f}% of NAV | Stressed Regime</div>
        </div>
        """, unsafe_allow_html=True)

    with kpi4:
        mult = comparison["comparison"]["stress_multiplier"]
        delta_var = comparison["comparison"]["var_dollar_delta"] * curr_mult
        st.markdown(f"""
        <div class="metric-card-stress">
            <div class="metric-title">Stress Multiplier</div>
            <div class="metric-value" style="color: #fbbf24;">{mult:.2f}x</div>
            <div class="metric-sub">+ {curr_sym} {delta_var:,.0f} Capital Add-on</div>
        </div>
        """, unsafe_allow_html=True)

    with kpi5:
        ann_vol_base = comparison["base"]["portfolio_annual_vol"]
        ann_vol_stress = comparison["stress"]["portfolio_annual_vol"]
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Annualized Volatility</div>
            <div class="metric-value">{ann_vol_base:.1f}% <span style="font-size:0.9rem; color:#f87171;">➔ {ann_vol_stress:.1f}%</span></div>
            <div class="metric-sub">Base vs. Stressed Volatility</div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# --- MAIN TABS ---
tab_overview, tab_mpt, tab_var, tab_schedules, tab_bonds, tab_derivatives, tab_stress, tab_docs = st.tabs([
    "📊 Portfolio Overview",
    "🎯 MPT Risk-Return Frontier",
    "⚡ VaR & Expected Shortfall (Base vs Stress)",
    "📑 VaR Supporting Schedules",
    "🏛️ Fixed Income & Debt Curve",
    "📈 Derivatives & Greeks Matrix",
    "🌪️ Macro Scenario Stress Testing",
    "📑 Methodology & Reference"
])


# ==============================================================================
# TAB 1: PORTFOLIO OVERVIEW
# ==============================================================================
with tab_overview:
    st.subheader("Trading Portfolio Asset Allocation & Holdings")

    c_left, c_right = st.columns([1, 1.2])

    with c_left:
        summary_df = portfolio.asset_class_summary()
        summary_df["Market Value Display"] = summary_df["Market Value ($)"] * curr_mult

        fig_pie = px.pie(
            summary_df,
            names="Asset Class",
            values="Market Value Display",
            hole=0.45,
            color="Asset Class",
            color_discrete_map={
                AssetClass.EQUITY.value: "#3b82f6",
                AssetClass.BOND.value: "#10b981",
                AssetClass.CASH.value: "#8b5cf6",
                AssetClass.DERIVATIVE.value: "#f59e0b"
            },
            title="Portfolio NAV by Asset Class"
        )
        fig_pie.update_traces(textposition="inside", textinfo="percent+label")
        fig_pie.update_layout(margin=dict(t=40, b=10, l=10, r=10), height=340)
        st.plotly_chart(fig_pie, use_container_width=True)

    with c_right:
        df_pos = portfolio.to_dataframe()
        df_pos["Market Value Display"] = df_pos["Market Value ($)"] * curr_mult
        df_pos_sorted = df_pos.sort_values(by="Weight (%)", ascending=False)

        fig_bar = px.bar(
            df_pos_sorted,
            x="Weight (%)",
            y="Ticker",
            orientation="h",
            color="Asset Class",
            color_discrete_map={
                AssetClass.EQUITY.value: "#3b82f6",
                AssetClass.BOND.value: "#10b981",
                AssetClass.CASH.value: "#8b5cf6",
                AssetClass.DERIVATIVE.value: "#f59e0b"
            },
            title="Exposure Weights by Individual Asset (%)"
        )
        fig_bar.update_layout(yaxis=dict(autorange="reversed"), margin=dict(t=40, b=10, l=10, r=10), height=340)
        st.plotly_chart(fig_bar, use_container_width=True)

    # Executive Briefing & Cash Flow Calendar
    st.markdown("### 📋 Monthly Risk Executive Briefing & Cash Flow Calendar")
    br_c1, br_c2 = st.columns([1.2, 1])
    with br_c1:
        st.markdown(f"""
        <div style="background: rgba(30, 41, 59, 0.7); border: 1px solid #334155; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
            <div style="font-weight: 600; font-size: 1.05rem; color: #f8fafc; margin-bottom: 8px;">
                🗣️ Plain-English Risk Takeaways (for Monthly Review)
            </div>
            <ul style="color: #cbd5e1; font-size: 0.92rem; line-height: 1.6; margin: 0; padding-left: 20px;">
                <li><strong>Normal Market Conditions (95% VaR)</strong>: Over a {horizon_days}-day horizon, your portfolio is expected to lose at most <span style="color:#f87171; font-weight:600;">{curr_sym} {base_var:,.0f} ({base_pct:.2f}%)</span> in 19 out of 20 trading days.</li>
                <li><strong>Severe Argentine Stress Scenario</strong>: In an abrupt macro crisis like the 2019 PASO or sovereign restructuring, your projected loss expands to <span style="color:#fbbf24; font-weight:600;">{curr_sym} {stress_var:,.0f} ({stress_pct:.2f}%)</span>.</li>
                <li><strong>Risk Concentration Alert</strong>: <strong>{top_risk_ticker}</strong> is your single largest risk driver, accounting for <strong>{top_risk_pct:.1f}%</strong> of total portfolio risk.</li>
                <li><strong>Diversification Benefit</strong>: Holding this diversified basket across stocks, bonds, and cash saves you <span style="color:#34d399; font-weight:600;">+{curr_sym} {div_benefit_val:,.0f} ({div_benefit_pct:.1f}%)</span> compared to holding each position separately.</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)

    with br_c2:
        # Cash Flow & Coupon Calendar
        bonds = portfolio.get_positions_by_class(AssetClass.BOND)
        cash_pos = portfolio.get_positions_by_class(AssetClass.CASH)
        tot_bond_annual_usd = sum(p.quantity * p.details.get("coupon", 0.01) for p in bonds)
        tot_cash_annual_usd = sum(p.market_value * (p.details.get("annual_yield", 0.0) / 100.0) for p in cash_pos)
        tot_annual_usd = tot_bond_annual_usd + tot_cash_annual_usd

        st.markdown(f"""
        <div style="background: rgba(30, 41, 59, 0.7); border: 1px solid #334155; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
            <div style="font-weight: 600; font-size: 1.05rem; color: #f8fafc; margin-bottom: 8px;">
                📅 Upcoming Bond Coupons & Interest Calendar
            </div>
            <div style="color: #cbd5e1; font-size: 0.92rem; line-height: 1.6;">
                • <strong>Next Sovereign Payment Date</strong>: <span style="color: #60a5fa; font-weight:600;">January 9, 2027</span> (GD30, AL30, GD35, AL35, GD38)<br>
                • <strong>Subsequent Payment Date</strong>: <span style="color: #60a5fa; font-weight:600;">July 9, 2027</span> (Semi-annual coupon & amort)<br>
                • <strong>Est. Annual Bond Coupons</strong>: <span style="color: #34d399; font-weight:600;">{curr_sym} {tot_bond_annual_usd * curr_mult:,.0f}</span><br>
                • <strong>Est. Annual Cash/Caución Yield</strong>: <span style="color: #34d399; font-weight:600;">{curr_sym} {tot_cash_annual_usd * curr_mult:,.0f}</span><br>
                • <strong>Total Passive Income Projected</strong>: <span style="color: #a7f3d0; font-weight:700;">{curr_sym} {tot_annual_usd * curr_mult:,.0f}</span> / year
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("### Detailed Holdings Registry")
    table_df = portfolio.to_dataframe()
    table_df["Unit Price"] = table_df["Unit Price ($)"].apply(lambda x: f"${x:,.2f}")
    table_df[f"Market Value ({curr_sym.strip()})"] = (table_df["Market Value ($)"] * curr_mult).apply(lambda x: f"{x:,.0f}")
    table_df[f"Notional ({curr_sym.strip()})"] = (table_df["Notional ($)"] * curr_mult).apply(lambda x: f"{x:,.0f}")
    table_df["Weight"] = table_df["Weight (%)"].apply(lambda x: f"{x:.2f}%")

    st.dataframe(
        table_df[["Ticker", "Name", "Asset Class", "Quantity", "Unit Price", f"Market Value ({curr_sym.strip()})", f"Notional ({curr_sym.strip()})", "Weight"]],
        use_container_width=True,
        hide_index=True
    )


# ==============================================================================
# TAB 2: MPT RISK & EXPECTED RETURN FRONTIER VISUALIZER
# ==============================================================================
with tab_mpt:
    st.subheader("🎯 Portfolio Risk & Expected Return Frontier Visualizer (Modern Portfolio Theory)")
    st.caption(
        "Markowitz mean-variance optimization, Efficient Frontier, Capital Allocation Line (CAL), "
        "and risk-return attribution across CEDEARs, Fixed Income / Carry, and Money Market FCIs."
    )

    # Inline Controls & Filters Bar
    ctrl_c1, ctrl_c2, ctrl_c3, ctrl_c4 = st.columns([1.3, 1.0, 1.0, 0.9])
    with ctrl_c1:
        view_options = ["All Assets", "CEDEARs Only", "Optimal Allocations"]
        default_view_idx = view_options.index(mpt_sidebar_filter) if mpt_sidebar_filter in view_options else 0
        mpt_view_toggle = st.radio(
            "Portfolio Universe & View Mode",
            options=view_options,
            index=default_view_idx,
            horizontal=True,
            help="Filter between all portfolio assets, the Equity/CEDEAR sleeve only, or highlight optimal Markowitz allocations."
        )
    with ctrl_c2:
        rf_inline_pct = st.number_input(
            "Risk-Free Rate R_f (% p.a.)",
            min_value=0.0,
            max_value=15.0,
            value=float(rf_rate_pct),
            step=0.1,
            format="%.2f",
            help="US 10Y Treasury / Risk-Free Rate benchmark (defaults to ~4.2%)."
        )
        rf_decimal = rf_inline_pct / 100.0
    with ctrl_c3:
        max_w_cap_pct = st.slider(
            "Max Single-Asset Weight Cap (%)",
            min_value=15,
            max_value=100,
            value=100,
            step=5,
            help="Set to 100% for unconstrained Markowitz optimization, or cap single-asset concentration (e.g. 25%-35%)."
        )
        max_w_cap = max_w_cap_pct / 100.0
    with ctrl_c4:
        use_live_yf = st.checkbox(
            "Live yfinance Blend",
            value=False,
            help="Fetch trailing 1Y daily adjusted closes from Yahoo Finance for US CEDEAR underlyings and blend with institutional priors."
        )

    # Build base optimizer and subportfolio if "CEDEARs Only" is selected
    base_mpt = MPTOptimizer(portfolio, risk_free_rate=rf_decimal, use_yfinance=use_live_yf)
    active_mpt_portfolio = base_mpt.filter_subportfolio(mpt_view_toggle)
    mpt_engine = (
        base_mpt
        if active_mpt_portfolio is portfolio
        else MPTOptimizer(active_mpt_portfolio, risk_free_rate=rf_decimal, use_yfinance=use_live_yf)
    )

    frontier_data = mpt_engine.generate_efficient_frontier(num_points=42, max_weight=max_w_cap)
    cur_metrics = frontier_data["current"]
    ms_metrics = frontier_data["max_sharpe"]
    mv_metrics = frontier_data["min_vol"]

    df_alloc = mpt_engine.get_asset_allocation_dataframe(
        max_sharpe_res=ms_metrics,
        min_vol_res=mv_metrics,
        currency_multiplier=curr_mult,
    )

    # --- METRICS BAR (st.columns) ---
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    with m_col1:
        est_ann_gain = (cur_metrics["expected_return"] * active_mpt_portfolio.total_value) * curr_mult
        st.metric(
            "Current Expected Return (μ_p)",
            f"{cur_metrics['expected_return_pct']:.2f}% p.a.",
            f"+{curr_sym} {est_ann_gain:,.0f} / yr est.",
        )
    with m_col2:
        vol_diff = cur_metrics["volatility_pct"] - mv_metrics["volatility_pct"]
        st.metric(
            "Annualized Volatility (σ_p)",
            f"{cur_metrics['volatility_pct']:.2f}% p.a.",
            f"Min Vol Benchmark: {mv_metrics['volatility_pct']:.2f}% ({vol_diff:+.2f}%)",
            delta_color="off",
        )
    with m_col3:
        st.metric(
            "Current Sharpe Ratio",
            f"{cur_metrics['sharpe']:.2f}",
            f"Excess Return: {cur_metrics['expected_return_pct'] - rf_inline_pct:+.2f}% vs R_f ({rf_inline_pct:.1f}%)",
            delta_color="off",
        )
    with m_col4:
        sharpe_uplift = ms_metrics["sharpe"] - cur_metrics["sharpe"]
        st.metric(
            "Target Max Sharpe (Tangency)",
            f"{ms_metrics['sharpe']:.2f}",
            f"{sharpe_uplift:+.2f} uplift (μ={ms_metrics['expected_return_pct']:.1f}%, σ={ms_metrics['volatility_pct']:.1f}%)",
        )

    st.markdown("---")

    # --- INTERACTIVE PLOTLY BUBBLE / SCATTER & EFFICIENT FRONTIER CHART ---
    category_colors = {
        MPT_CATEGORY_CORE_CEDEAR: "#3b82f6",     # Royal Blue
        MPT_CATEGORY_HIGH_BETA: "#f59e0b",       # Amber / Orange
        MPT_CATEGORY_FIXED_INCOME: "#10b981",    # Emerald Green
        MPT_CATEGORY_CASH_FCI: "#a855f7",        # Purple
    }

    fig_mpt = go.Figure()

    # 1. Capital Allocation Line (CAL)
    fig_mpt.add_trace(go.Scatter(
        x=frontier_data["cal_vols_pct"],
        y=frontier_data["cal_returns_pct"],
        mode="lines",
        name=f"Capital Allocation Line (CAL, R_f={rf_inline_pct:.1f}%)",
        line=dict(color="#fbbf24", width=2.2, dash="dash"),
        hovertemplate="<b>Capital Allocation Line (CAL)</b><br>Volatility (σ): %{x:.2f}%<br>Expected Return (μ): %{y:.2f}%<extra></extra>",
    ))

    # 2. Efficient Frontier Curve
    fig_mpt.add_trace(go.Scatter(
        x=frontier_data["frontier_vols_pct"],
        y=frontier_data["frontier_returns_pct"],
        mode="lines",
        name="Markowitz Efficient Frontier",
        line=dict(color="#e2e8f0", width=3.2, dash="solid"),
        customdata=frontier_data["frontier_sharpes"],
        hovertemplate=(
            "<b>Efficient Frontier</b><br>"
            "Annualized Volatility (σ): %{x:.2f}%<br>"
            "Expected Return (μ): %{y:.2f}%<br>"
            "Sharpe Ratio: %{customdata:.2f}<extra></extra>"
        ),
    ))

    # 3. Risk-Free Rate Marker at (0, R_f)
    fig_mpt.add_trace(go.Scatter(
        x=[0.0],
        y=[rf_inline_pct],
        mode="markers+text",
        name=f"Risk-Free Rate (R_f = {rf_inline_pct:.1f}%)",
        text=[f"R_f ({rf_inline_pct:.1f}%)"],
        textposition="middle right",
        marker=dict(symbol="circle", size=11, color="#fbbf24", line=dict(width=1.5, color="#0f172a")),
        hovertemplate=f"<b>Risk-Free Rate (US 10Y)</b><br>Volatility: 0.00%<br>Return: {rf_inline_pct:.2f}%<extra></extra>",
    ))

    # 4. Individual Instrument Bubbles Grouped by Category
    if not df_alloc.empty:
        # In 'Optimal Allocations' view, scale bubble size by Max Sharpe weight (or max of Max Sharpe / Min Vol)
        size_col = (
            "Max Sharpe Weight (%)"
            if mpt_view_toggle == "Optimal Allocations"
            else "Current Weight (%)"
        )
        for cat_name in [
            MPT_CATEGORY_CORE_CEDEAR,
            MPT_CATEGORY_HIGH_BETA,
            MPT_CATEGORY_FIXED_INCOME,
            MPT_CATEGORY_CASH_FCI,
        ]:
            sub_df = df_alloc[df_alloc["Category"] == cat_name].copy()
            if mpt_view_toggle == "Optimal Allocations":
                # Keep assets with non-trivial weight in Current, Max Sharpe, or Min Vol
                sub_df = sub_df[
                    (sub_df["Max Sharpe Weight (%)"] >= 0.5)
                    | (sub_df["Min Vol Weight (%)"] >= 0.5)
                    | (sub_df["Current Weight (%)"] >= 1.0)
                ]
            if sub_df.empty:
                continue

            # Dynamic marker diameter scaled by weight w_i
            weights_for_size = sub_df[size_col].values
            marker_sizes = np.clip(13.0 + np.sqrt(np.maximum(weights_for_size, 0.2)) * 5.2, 13.0, 50.0)

            custom_hover = np.stack([
                sub_df["Ticker"].values,
                sub_df["Name"].values,
                sub_df["Current Weight (%)"].values,
                sub_df["Max Sharpe Weight (%)"].values,
                sub_df["Min Vol Weight (%)"].values,
                sub_df["Sharpe Ratio"].values,
                sub_df["Market Value ($)"].values,
            ], axis=-1)

            fig_mpt.add_trace(go.Scatter(
                x=sub_df["Annualized Volatility (%)"],
                y=sub_df["Expected Return (%)"],
                mode="markers+text",
                name=cat_name,
                text=sub_df["Base Ticker"],
                textposition="top center",
                textfont=dict(size=11, color="#f8fafc"),
                marker=dict(
                    size=marker_sizes,
                    color=category_colors.get(cat_name, "#60a5fa"),
                    opacity=0.86,
                    line=dict(width=1.5, color="#0f172a"),
                ),
                customdata=custom_hover,
                hovertemplate=(
                    "<b>%{customdata[0]}</b> — %{customdata[1]}<br>"
                    f"Category: <b>{cat_name}</b><br>"
                    f"Value: <b>{curr_sym} %{{customdata[6]:,.0f}}</b><br>"
                    "Current Weight: <b>%{customdata[2]:.2f}%</b><br>"
                    "Optimal Max Sharpe Weight: <b>%{customdata[3]:.2f}%</b><br>"
                    "Optimal Min Vol Weight: <b>%{customdata[4]:.2f}%</b><br>"
                    "Expected Return (μ): <b>%{y:.2f}%</b><br>"
                    "Annualized Volatility (σ): <b>%{x:.2f}%</b><br>"
                    "Individual Sharpe Ratio: <b>%{customdata[5]:.2f}</b><extra></extra>"
                ),
            ))

    # 5. Highlight Marker: Current Portfolio (Total Holdings)
    fig_mpt.add_trace(go.Scatter(
        x=[cur_metrics["volatility_pct"]],
        y=[cur_metrics["expected_return_pct"]],
        mode="markers+text",
        name="Current Portfolio (Total Holdings)",
        text=["★ Current Portfolio"],
        textposition="bottom center",
        textfont=dict(size=12, color="#fde047"),
        marker=dict(
            symbol="star",
            size=24,
            color="#facc15",
            line=dict(width=2.2, color="#0f172a"),
        ),
        hovertemplate=(
            "<b>★ Current Portfolio (Total Holdings)</b><br>"
            "Weight: <b>100.0%</b><br>"
            f"Expected Return (μ_p): <b>{cur_metrics['expected_return_pct']:.2f}%</b><br>"
            f"Annualized Volatility (σ_p): <b>{cur_metrics['volatility_pct']:.2f}%</b><br>"
            f"Portfolio Sharpe Ratio: <b>{cur_metrics['sharpe']:.2f}</b><extra></extra>"
        ),
    ))

    # 6. Highlight Marker: Max Sharpe Portfolio (Green Marker + Callout)
    fig_mpt.add_trace(go.Scatter(
        x=[ms_metrics["volatility_pct"]],
        y=[ms_metrics["expected_return_pct"]],
        mode="markers+text",
        name="Max Sharpe Portfolio (Tangency)",
        text=["◆ Max Sharpe"],
        textposition="top left",
        textfont=dict(size=12, color="#4ade80"),
        marker=dict(
            symbol="diamond",
            size=19,
            color="#22c55e",
            line=dict(width=2.0, color="#052e16"),
        ),
        hovertemplate=(
            "<b>◆ Max Sharpe Portfolio (Tangency)</b><br>"
            f"Expected Return (μ*): <b>{ms_metrics['expected_return_pct']:.2f}%</b><br>"
            f"Annualized Volatility (σ*): <b>{ms_metrics['volatility_pct']:.2f}%</b><br>"
            f"Max Sharpe Ratio: <b>{ms_metrics['sharpe']:.2f}</b><extra></extra>"
        ),
    ))

    # 7. Highlight Marker: Min Volatility Portfolio (Blue Marker + Callout)
    fig_mpt.add_trace(go.Scatter(
        x=[mv_metrics["volatility_pct"]],
        y=[mv_metrics["expected_return_pct"]],
        mode="markers+text",
        name="Min Volatility Portfolio",
        text=["● Min Volatility"],
        textposition="bottom right",
        textfont=dict(size=12, color="#38bdf8"),
        marker=dict(
            symbol="hexagon",
            size=18,
            color="#0ea5e9",
            line=dict(width=2.0, color="#082f49"),
        ),
        hovertemplate=(
            "<b>● Minimum Volatility Portfolio</b><br>"
            f"Expected Return (μ_min): <b>{mv_metrics['expected_return_pct']:.2f}%</b><br>"
            f"Annualized Volatility (σ_min): <b>{mv_metrics['volatility_pct']:.2f}%</b><br>"
            f"Sharpe Ratio: <b>{mv_metrics['sharpe']:.2f}</b><extra></extra>"
        ),
    ))

    # Callout annotations for Current, Max Sharpe, and Min Volatility portfolios
    fig_mpt.add_annotation(
        x=ms_metrics["volatility_pct"],
        y=ms_metrics["expected_return_pct"],
        text=f"<b>Max Sharpe ({ms_metrics['sharpe']:.2f})</b><br>μ={ms_metrics['expected_return_pct']:.1f}% | σ={ms_metrics['volatility_pct']:.1f}%",
        showarrow=True,
        arrowhead=2,
        arrowsize=1,
        arrowwidth=1.5,
        arrowcolor="#22c55e",
        ax=-55,
        ay=-42,
        bgcolor="rgba(6, 78, 59, 0.85)",
        bordercolor="#22c55e",
        borderwidth=1,
        font=dict(size=10.5, color="#ecfdf5"),
    )
    fig_mpt.add_annotation(
        x=mv_metrics["volatility_pct"],
        y=mv_metrics["expected_return_pct"],
        text=f"<b>Min Vol ({mv_metrics['volatility_pct']:.1f}%)</b><br>μ={mv_metrics['expected_return_pct']:.1f}% | SR={mv_metrics['sharpe']:.2f}",
        showarrow=True,
        arrowhead=2,
        arrowsize=1,
        arrowwidth=1.5,
        arrowcolor="#0ea5e9",
        ax=55,
        ay=38,
        bgcolor="rgba(12, 74, 110, 0.85)",
        bordercolor="#38bdf8",
        borderwidth=1,
        font=dict(size=10.5, color="#f0f9ff"),
    )
    fig_mpt.add_annotation(
        x=cur_metrics["volatility_pct"],
        y=cur_metrics["expected_return_pct"],
        text=f"<b>Current Holdings</b><br>μ={cur_metrics['expected_return_pct']:.1f}% | σ={cur_metrics['volatility_pct']:.1f}% | SR={cur_metrics['sharpe']:.2f}",
        showarrow=True,
        arrowhead=2,
        arrowsize=1,
        arrowwidth=1.5,
        arrowcolor="#facc15",
        ax=45,
        ay=-38,
        bgcolor="rgba(66, 32, 6, 0.88)",
        bordercolor="#facc15",
        borderwidth=1,
        font=dict(size=10.5, color="#fef9c3"),
    )

    fig_mpt.update_layout(
        title=f"Risk-Return Efficient Frontier & Asset Positioning ({mpt_view_toggle})",
        xaxis_title="Annualized Volatility Risk (σ) [%]",
        yaxis_title="Annualized Expected Return (μ) [%]",
        height=560,
        margin=dict(t=50, b=40, l=20, r=20),
        hovermode="closest",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1.0,
            font=dict(size=11),
        ),
        xaxis=dict(rangemode="tozero", gridcolor="rgba(148, 163, 184, 0.15)"),
        yaxis=dict(gridcolor="rgba(148, 163, 184, 0.15)"),
    )
    st.plotly_chart(fig_mpt, use_container_width=True)

    # --- CURRENT VS OPTIMAL WEIGHTS COMPARISON & ASSET ALLOCATION TABLE ---
    st.markdown("### 📊 Current vs. Markowitz Optimal Asset Allocations")
    alloc_c1, alloc_c2 = st.columns([1.05, 1.35])

    with alloc_c1:
        if not df_alloc.empty:
            df_melt = df_alloc.melt(
                id_vars=["Ticker", "Category"],
                value_vars=["Current Weight (%)", "Max Sharpe Weight (%)", "Min Vol Weight (%)"],
                var_name="Allocation Strategy",
                value_name="Weight (%)",
            )
            fig_opt_bar = px.bar(
                df_melt,
                x="Weight (%)",
                y="Ticker",
                color="Allocation Strategy",
                barmode="group",
                orientation="h",
                color_discrete_map={
                    "Current Weight (%)": "#facc15",
                    "Max Sharpe Weight (%)": "#22c55e",
                    "Min Vol Weight (%)": "#38bdf8",
                },
                title="Current Weight vs. Max Sharpe & Min Volatility Benchmarks (%)",
            )
            fig_opt_bar.update_layout(
                yaxis=dict(autorange="reversed"),
                height=440,
                margin=dict(t=40, b=20, l=10, r=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig_opt_bar, use_container_width=True)

    with alloc_c2:
        st.markdown("##### Asset Allocation & Risk-Return Summary Table")
        if not df_alloc.empty:
            display_alloc = df_alloc.copy()
            val_col_label = f"Total Value ({curr_sym.strip()})"
            display_alloc[val_col_label] = display_alloc["Market Value ($)"].apply(lambda v: f"{curr_sym} {v:,.0f}")
            display_alloc["Current Weight"] = display_alloc["Current Weight (%)"].apply(lambda w: f"{w:.2f}%")
            display_alloc["Max Sharpe Weight"] = display_alloc["Max Sharpe Weight (%)"].apply(lambda w: f"{w:.2f}%")
            display_alloc["Min Vol Weight"] = display_alloc["Min Vol Weight (%)"].apply(lambda w: f"{w:.2f}%")
            display_alloc["Delta (Max Sharpe)"] = display_alloc["Weight Delta vs Max Sharpe (%)"].apply(lambda d: f"{d:+.2f}%")
            display_alloc["Exp. Return (μ)"] = display_alloc["Expected Return (%)"].apply(lambda r: f"{r:.2f}%")
            display_alloc["Volatility (σ)"] = display_alloc["Annualized Volatility (%)"].apply(lambda s: f"{s:.2f}%")
            display_alloc["Sharpe"] = display_alloc["Sharpe Ratio"].apply(lambda sr: f"{sr:.2f}")

            st.dataframe(
                display_alloc[[
                    "Ticker",
                    "Name",
                    "Category",
                    val_col_label,
                    "Current Weight",
                    "Max Sharpe Weight",
                    "Min Vol Weight",
                    "Delta (Max Sharpe)",
                    "Exp. Return (μ)",
                    "Volatility (σ)",
                    "Sharpe",
                ]],
                use_container_width=True,
                hide_index=True,
                height=410,
            )



# ==============================================================================
# TAB 2: VAR & EXPECTED SHORTFALL (BASE VS STRESSED)
# ==============================================================================
with tab_var:
    st.subheader(f"Value at Risk (VaR) & Expected Shortfall Analysis: Base vs. Stressed Scenarios")
    st.caption(f"Evaluated at {conf_level*100:.1f}% confidence interval over a {horizon_days}-day holding horizon.")

    # Methodology Comparison Table
    col_comp1, col_comp2, col_comp3 = st.columns(3)

    with col_comp1:
        st.markdown("#### 1. Parametric (Variance-Covariance)")
        b_p_var = comparison["base"]["parametric"]["var_dollar"] * curr_mult
        b_p_cvar = comparison["base"]["parametric"]["cvar_dollar"] * curr_mult
        s_p_var = comparison["stress"]["parametric"]["var_dollar"] * curr_mult
        s_p_cvar = comparison["stress"]["parametric"]["cvar_dollar"] * curr_mult

        st.metric("Base VaR", f"{curr_sym} {b_p_var:,.0f}", f"{comparison['base']['parametric']['var_pct']:.2f}%")
        st.metric("Base CVaR (Expected Shortfall)", f"{curr_sym} {b_p_cvar:,.0f}", f"{comparison['base']['parametric']['cvar_pct']:.2f}%")
        st.metric("Stressed VaR (sVaR)", f"{curr_sym} {s_p_var:,.0f}", f"{comparison['stress']['parametric']['var_pct']:.2f}%", delta_color="inverse")
        st.metric("Stressed CVaR", f"{curr_sym} {s_p_cvar:,.0f}", f"{comparison['stress']['parametric']['cvar_pct']:.2f}%", delta_color="inverse")

    with col_comp2:
        st.markdown("#### 2. Historical Simulation")
        b_h_var = comparison["base"]["historical"]["var_dollar"] * curr_mult
        b_h_cvar = comparison["base"]["historical"]["cvar_dollar"] * curr_mult
        s_h_var = comparison["stress"]["historical"]["var_dollar"] * curr_mult
        s_h_cvar = comparison["stress"]["historical"]["cvar_dollar"] * curr_mult

        st.metric("Base VaR", f"{curr_sym} {b_h_var:,.0f}", f"{comparison['base']['historical']['var_pct']:.2f}%")
        st.metric("Base CVaR (Expected Shortfall)", f"{curr_sym} {b_h_cvar:,.0f}", f"{comparison['base']['historical']['cvar_pct']:.2f}%")
        st.metric("Stressed VaR (sVaR)", f"{curr_sym} {s_h_var:,.0f}", f"{comparison['stress']['historical']['var_pct']:.2f}%", delta_color="inverse")
        st.metric("Stressed CVaR", f"{curr_sym} {s_h_cvar:,.0f}", f"{comparison['stress']['historical']['cvar_pct']:.2f}%", delta_color="inverse")

    with col_comp3:
        st.markdown("#### 3. Monte Carlo Simulation (10k Paths)")
        b_m_var = comparison["base"]["monte_carlo"]["var_dollar"] * curr_mult
        b_m_cvar = comparison["base"]["monte_carlo"]["cvar_dollar"] * curr_mult
        s_m_var = comparison["stress"]["monte_carlo"]["var_dollar"] * curr_mult
        s_m_cvar = comparison["stress"]["monte_carlo"]["cvar_dollar"] * curr_mult

        st.metric("Base VaR", f"{curr_sym} {b_m_var:,.0f}", f"{comparison['base']['monte_carlo']['var_pct']:.2f}%")
        st.metric("Base CVaR (Expected Shortfall)", f"{curr_sym} {b_m_cvar:,.0f}", f"{comparison['base']['monte_carlo']['cvar_pct']:.2f}%")
        st.metric("Stressed VaR (sVaR)", f"{curr_sym} {s_m_var:,.0f}", f"{comparison['stress']['monte_carlo']['var_pct']:.2f}%", delta_color="inverse")
        st.metric("Stressed CVaR", f"{curr_sym} {s_m_cvar:,.0f}", f"{comparison['stress']['monte_carlo']['cvar_pct']:.2f}%", delta_color="inverse")

    st.markdown("---")

    # Return & Loss Distribution Plot: Base vs Stressed
    st.markdown("### Empirical Loss Distributions & Tail Cutoffs")
    base_losses = comparison["base"]["historical"]["loss_distribution"] * curr_mult
    stress_losses = comparison["stress"]["historical"]["loss_distribution"] * curr_mult

    fig_dist = go.Figure()
    fig_dist.add_trace(go.Histogram(
        x=base_losses,
        nbinsx=60,
        opacity=0.6,
        name="Base Scenario Losses",
        marker_color="#3b82f6"
    ))
    fig_dist.add_trace(go.Histogram(
        x=stress_losses,
        nbinsx=60,
        opacity=0.5,
        name="Stressed Scenario Losses",
        marker_color="#ef4444"
    ))

    # Add vertical lines for Base VaR, Base CVaR, Stressed VaR, Stressed CVaR
    fig_dist.add_vline(x=b_h_var, line_width=2.5, line_dash="dash", line_color="#60a5fa",
                       annotation_text=f"Base VaR: {curr_sym} {b_h_var:,.0f}", annotation_position="top left")
    fig_dist.add_vline(x=b_h_cvar, line_width=2.5, line_dash="dot", line_color="#2563eb",
                       annotation_text=f"Base CVaR: {curr_sym} {b_h_cvar:,.0f}", annotation_position="top left")
    fig_dist.add_vline(x=s_h_var, line_width=2.5, line_dash="dash", line_color="#f87171",
                       annotation_text=f"Stressed VaR: {curr_sym} {s_h_var:,.0f}", annotation_position="top right")
    fig_dist.add_vline(x=s_h_cvar, line_width=2.5, line_dash="dot", line_color="#b91c1c",
                       annotation_text=f"Stressed CVaR: {curr_sym} {s_h_cvar:,.0f}", annotation_position="top right")

    fig_dist.update_layout(
        barmode="overlay",
        xaxis_title=f"Potential Portfolio Loss ({curr_sym})",
        yaxis_title="Frequency / Count",
        margin=dict(t=40, b=20, l=10, r=10),
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(fig_dist, use_container_width=True)

    # Component VaR Risk Decomposition
    st.markdown("### Component VaR Risk Contribution Breakdown")
    c_dec1, c_dec2 = st.columns(2)

    with c_dec1:
        st.markdown("##### Base Regime: Asset Risk Contribution")
        df_comp_base = var_engine.get_component_var_breakdown(conf_level, horizon_days, scenario="base")
        fig_c_base = px.bar(
            df_comp_base,
            x="% Risk Contribution",
            y="Ticker",
            orientation="h",
            color="Asset Class",
            color_discrete_map={
                AssetClass.EQUITY.value: "#3b82f6",
                AssetClass.BOND.value: "#10b981",
                AssetClass.CASH.value: "#8b5cf6",
                AssetClass.DERIVATIVE.value: "#f59e0b"
            }
        )
        fig_c_base.update_layout(yaxis=dict(autorange="reversed"), height=380, margin=dict(t=20, b=10, l=10, r=10))
        st.plotly_chart(fig_c_base, use_container_width=True)

    with c_dec2:
        st.markdown("##### Stressed Regime: Asset Risk Contribution")
        df_comp_stress = var_engine.get_component_var_breakdown(conf_level, horizon_days, scenario="stress")
        fig_c_stress = px.bar(
            df_comp_stress,
            x="% Risk Contribution",
            y="Ticker",
            orientation="h",
            color="Asset Class",
            color_discrete_map={
                AssetClass.EQUITY.value: "#3b82f6",
                AssetClass.BOND.value: "#10b981",
                AssetClass.CASH.value: "#8b5cf6",
                AssetClass.DERIVATIVE.value: "#f59e0b"
            }
        )
        fig_c_stress.update_layout(yaxis=dict(autorange="reversed"), height=380, margin=dict(t=20, b=10, l=10, r=10))
        st.plotly_chart(fig_c_stress, use_container_width=True)


# ==============================================================================
# TAB 3: VAR SUPPORTING SCHEDULES & MARKET VALUE EVOLUTION
# ==============================================================================
with tab_schedules:
    st.subheader("📑 VaR Supporting Schedules & Market Value Evolution")
    st.caption("Audit-ready time-series tracking daily asset market values, returns, dollar PnL, parametric covariance, and empirical tail losses in dual currencies (USD & ARS).")

    # Generate Excel export bytes
    excel_export_bytes = build_var_supporting_excel(
        portfolio=portfolio,
        var_engine=var_engine,
        ccl_rate=fx_rate,
        confidence_level=conf_level,
        horizon_days=horizon_days
    )

    down_c1, down_c2 = st.columns([1.5, 1])
    with down_c1:
        rep_month = str(settings.get('Reporting_Month', 'September_2026')).replace(' ', '_')
        st.download_button(
            label="📥 Download Supporting Schedules (var_supporting_schedules.xlsx)",
            data=excel_export_bytes,
            file_name=f"var_supporting_schedules_{rep_month}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help="Download a multi-tab Excel workbook containing Base & Stressed Market Values (USD & ARS), Returns, PnL, Covariance Matrix, and Tail Exceedance schedules."
        )
    with down_c2:
        st.info(f"💡 **Dual-Currency Valuation**: Base FX CCL Rate = **{fx_rate:,.2f} ARS/USD**")

    st.markdown("---")

    # Filter Controls
    f_c1, f_c2, f_c3 = st.columns([1, 1, 1])
    with f_c1:
        schedule_scenario = st.radio("Market Regime", ["Base Scenario", "Stressed Scenario (sVaR)"], horizontal=True)
        active_scen_key = "stress" if "Stressed" in schedule_scenario else "base"
    with f_c2:
        lookback_choice = st.selectbox(
            "Lookback Window",
            options=["All History (504 Trading Days / 2Y)", "1 Year (252 Trading Days)", "6 Months (126 Trading Days)"],
            index=0
        )
        lookback_days = 504 if "All" in lookback_choice else (252 if "1 Year" in lookback_choice else 126)
    with f_c3:
        chart_curr = st.radio("Currency", ["USD ($)", "ARS ($)"], horizontal=True, index=0 if curr_view == "USD ($)" else 1)
        curr_suffix = "USD" if chart_curr == "USD ($)" else "ARS"
        curr_symbol = "$" if chart_curr == "USD ($)" else "ARS $"

    metric_mode = st.radio(
        "Chart Metric Type",
        ["Total Position Value ($)", "Unit Price ($ / share, bond, contract)"],
        horizontal=True
    )
    is_unit_price = "Unit Price" in metric_mode

    # Generate schedules for active scenario
    active_returns_df = var_engine.stress_returns_df if active_scen_key == "stress" else var_engine.base_returns_df
    # Slice to selected lookback
    sliced_returns = active_returns_df.iloc[-lookback_days:]
    df_mv_full = generate_market_value_evolution(active_returns_df, portfolio, fx_rate)
    df_mv = df_mv_full.iloc[-lookback_days:]
    df_pnl = generate_returns_pnl_schedule(sliced_returns, df_mv, portfolio, fx_rate)

    # 1. Interactive Visual Time-Series Chart
    st.markdown(f"### Historical Evolution: {metric_mode} ({chart_curr})")
    all_tickers = [p.ticker for p in portfolio.positions]
    chart_col_options = (["Portfolio NAV"] if not is_unit_price else []) + all_tickers
    default_selection = (["Portfolio NAV"] if not is_unit_price else []) + [t for t in ["GD30", "AL30", "YPFD.BA", "GGAL.BA"] if t in all_tickers]
    selected_series = st.multiselect(
        "Select Assets / Portfolios to Visualize:",
        options=chart_col_options,
        default=default_selection if default_selection else chart_col_options[:3]
    )

    if selected_series:
        fig_mv = go.Figure()
        for s in selected_series:
            if s == "Portfolio NAV":
                col_name = f"Portfolio_NAV_{curr_suffix}"
            elif is_unit_price:
                col_name = f"{s}_UnitPrice_{curr_suffix}"
            else:
                col_name = f"{s}_TotalVal_{curr_suffix}"

            if col_name in df_mv.columns:
                is_nav = (s == "Portfolio NAV")
                fig_mv.add_trace(go.Scatter(
                    x=df_mv.index,
                    y=df_mv[col_name],
                    mode="lines",
                    name=f"{s} ({'Unit Price' if is_unit_price else 'Total Val'} {curr_symbol})",
                    line=dict(width=3.5 if is_nav else 1.8, dash="solid" if is_nav else "dot" if ("ROFEX" in s or "IRS" in s) else "solid")
                ))
        fig_mv.update_layout(
            xaxis_title="Date",
            yaxis_title=f"{'Unit Price' if is_unit_price else 'Total Market Value'} ({curr_symbol})",
            margin=dict(t=30, b=20, l=10, r=10),
            height=400,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig_mv, use_container_width=True)

    # 2. Supporting Schedules Sub-Tabs
    sub_mv, sub_pnl, sub_param, sub_tail = st.tabs([
        "📈 Market Value & Unit Price History",
        "💰 Daily Returns & Dollar PnL",
        "📐 Parametric Covariance & Correlation",
        "🎯 Empirical Tail-Loss Audit"
    ])

    with sub_mv:
        st.markdown(f"##### Daily Unit Prices & Position Market Values ({schedule_scenario})")
        st.caption("💡 **Column Guide**: `_UnitPrice_USD` / `_UnitPrice_ARS` = price per single share/contract/nominal unit | `_TotalVal_USD` / `_TotalVal_ARS` = total portfolio holding value.")
        display_mv = df_mv.copy()
        display_mv.index = display_mv.index.strftime("%Y-%m-%d")
        st.dataframe(display_mv, use_container_width=True)

    with sub_pnl:
        st.markdown(f"##### Daily Returns & Dollar PnL Schedule ({schedule_scenario})")
        display_pnl = df_pnl.copy()
        display_pnl.index = display_pnl.index.strftime("%Y-%m-%d")
        st.dataframe(display_pnl, use_container_width=True)

    with sub_param:
        st.markdown(f"##### Parametric Risk Matrices & Component VaR ({schedule_scenario})")
        cov_df, corr_df, comp_df = generate_parametric_audit_schedules(
            var_engine, active_scen_key, fx_rate, conf_level, horizon_days
        )
        p_c1, p_c2 = st.columns(2)
        with p_c1:
            st.markdown("###### Correlation Matrix")
            fig_corr = px.imshow(
                corr_df,
                text_auto=".2f",
                color_continuous_scale="RdBu_r",
                zmin=-1, zmax=1,
                title="Asset Correlation Heatmap"
            )
            fig_corr.update_layout(height=420, margin=dict(t=30, b=10, l=10, r=10))
            st.plotly_chart(fig_corr, use_container_width=True)
        with p_c2:
            st.markdown("###### Euler Component VaR Schedule")
            st.dataframe(comp_df, use_container_width=True, hide_index=True)

    with sub_tail:
        st.markdown(f"##### Empirical Tail Losses Beyond VaR Cutoff ({schedule_scenario})")
        tail_df = generate_tail_loss_audit_schedule(
            var_engine, active_scen_key, fx_rate, conf_level, horizon_days
        )
        st.dataframe(tail_df, use_container_width=True, hide_index=True)


# ==============================================================================
# TAB 3: FIXED INCOME & DEBT CURVE
# ==============================================================================
with tab_bonds:
    st.subheader("Argentine Restructured Sovereign Debt Analytics")
    st.caption("Cash flow discounting, Yield-to-Maturity (YTM), Macaulay & Modified Duration, Convexity, and DV01.")

    bonds = portfolio.get_positions_by_class(AssetClass.BOND)
    bond_analytics = []
    for b in bonds:
        d = b.details
        ytm_val = float(d.get("ytm", 0.16))
        mod_dur = float(d.get("modified_duration", 3.0))
        conv = float(d.get("convexity", 10.0))
        clean_p = b.unit_price * 100.0 if b.unit_price < 2.0 else b.unit_price
        bond_analytics.append({
            "ticker": b.ticker,
            "name": b.name,
            "law": d.get("law", "New York"),
            "clean_price": round(clean_p, 2),
            "ytm_percent": round(ytm_val * 100, 2) if ytm_val < 1.0 else round(ytm_val, 2),
            "macaulay_duration": round(mod_dur * (1.0 + (ytm_val if ytm_val < 1.0 else ytm_val/100)/2.0), 2),
            "modified_duration": round(mod_dur, 2),
            "convexity": round(conv, 2),
            "dv01_per_100": round(float(d.get("dv01", 300.0)), 2),
        })

    df_bonds = pd.DataFrame(bond_analytics) if bond_analytics else pd.DataFrame()

    if not df_bonds.empty:
        b_col1, b_col2 = st.columns([1.2, 1])

        with b_col1:
            # Yield curve plot
            fig_yc = px.line(
                df_bonds,
                x="modified_duration",
                y="ytm_percent",
                text="ticker",
                markers=True,
                title="Sovereign Yield vs. Modified Duration Curve",
                labels={"modified_duration": "Modified Duration (Years)", "ytm_percent": "Yield to Maturity (YTM %)"}
            )
            fig_yc.update_traces(textposition="top center", line_color="#10b981", marker=dict(size=12))
            fig_yc.update_layout(height=360, margin=dict(t=40, b=20, l=10, r=10))
            st.plotly_chart(fig_yc, use_container_width=True)

        with b_col2:
            # Duration & Convexity comparison bar
            fig_dur = px.bar(
                df_bonds,
                x="ticker",
                y=["modified_duration", "convexity"],
                barmode="group",
                title="Duration & Convexity Profile across Issues",
                labels={"value": "Metric Value", "ticker": "Bond Issue"}
            )
            fig_dur.update_layout(height=360, margin=dict(t=40, b=20, l=10, r=10))
            st.plotly_chart(fig_dur, use_container_width=True)

        st.markdown("### Sovereign Bond Risk Sensitivity Table")
        df_bonds_display = df_bonds.copy()
        df_bonds_display.columns = [
            "Ticker", "Bond Name", "Governing Law", "Clean Price ($)",
            "YTM (%)", "Macaulay Duration (Yrs)", "Modified Duration (Yrs)",
            "Convexity", "DV01 ($ / 100 Nom)"
        ]
        st.dataframe(df_bonds_display, use_container_width=True, hide_index=True)

    # Dynamic Yield Shift Simulation
    st.markdown("#### Yield Shift Simulator (Parallel Shift)")
    y_shift = st.slider("Parallel Yield Shift (Basis Points)", min_value=-500, max_value=1500, value=200, step=25)
    dy = y_shift / 10000.0

    shift_records = []
    total_bond_pnl = 0.0
    for p in portfolio.get_positions_by_class(AssetClass.BOND):
        mod_d = p.details.get("modified_duration", 3.0)
        conv = p.details.get("convexity", 10.0)
        pct_chg = - mod_d * dy + 0.5 * conv * (dy ** 2)
        pnl = p.market_value * pct_chg * curr_mult
        total_bond_pnl += pnl
        shift_records.append({
            "Ticker": p.ticker,
            "Market Value": f"{curr_sym} {p.market_value * curr_mult:,.0f}",
            "Est Price Change (%)": f"{pct_chg * 100:.2f}%",
            "PnL Impact": f"{curr_sym} {pnl:,.0f}"
        })

    st.dataframe(pd.DataFrame(shift_records), use_container_width=True, hide_index=True)
    st.info(f"**Total Sovereign Debt Book PnL for {y_shift:+d} bps shift**: **{curr_sym} {total_bond_pnl:,.0f}**")


# ==============================================================================
# TAB 4: DERIVATIVES & GREEKS MATRIX
# ==============================================================================
with tab_derivatives:
    st.subheader("Derivatives Book & Greek Risk Sensitivities")
    st.caption("Exchange-traded Rofex futures, GGAL options (Call/Put), OTC USD/ARS NDF, and OTC BADLAR IRS.")

    derivs = portfolio.get_positions_by_class(AssetClass.DERIVATIVE)
    sens_dict = {}
    for d in derivs:
        dt = d.details
        notional_val = d.notional if d.notional else d.market_value
        delta_val = float(dt.get("delta", 1.0))
        sens_dict[d.ticker] = {
            "name": d.name,
            "type": dt.get("type", "Derivative"),
            "notional": notional_val,
            "market_value": d.market_value,
            "delta": delta_val,
            "delta_usd": delta_val * notional_val,
            "gamma": float(dt.get("gamma", 0.0)),
            "vega": float(dt.get("vega", 0.0)),
            "theta": float(dt.get("theta", 0.0)),
            "dv01": float(dt.get("dv01", 0.0)),
            "description": dt.get("description", "")
        }

    g_col1, g_col2, g_col3, g_col4 = st.columns(4)
    with g_col1:
        total_delta = sum(v.get("delta_usd", 0.0) for v in sens_dict.values()) * curr_mult
        st.metric("Aggregate USD Delta Exposure", f"{curr_sym} {total_delta:,.0f}")
    with g_col2:
        total_vega = sum(v.get("vega", 0.0) for v in sens_dict.values()) * curr_mult
        st.metric("Total Equity Vega", f"{curr_sym} {total_vega:,.0f} / vol pt")
    with g_col3:
        total_theta = sum(v.get("theta", 0.0) for v in sens_dict.values()) * curr_mult
        st.metric("Total Options Theta Decay", f"{curr_sym} {total_theta:,.0f} / day")
    with g_col4:
        total_dv01 = sum(v.get("dv01", 0.0) for v in sens_dict.values()) * curr_mult
        st.metric("Rates DV01 (IRS / Swaps)", f"{curr_sym} {total_dv01:,.0f} / bp")

    # Options Payoff Profile Plot
    st.markdown("### GGAL Option Strategy Payoff Profile (Collar / Combined Long Call + Put)")
    spot_range = np.linspace(2.5, 7.5, 100)
    # GGAL Call: Strike 5.0, Premium paid 262.50 / 100 = 2.625
    # GGAL Put: Strike 4.5, Premium paid 175.0 / 100 = 1.75
    c_payoff = np.maximum(0, spot_range - 5.0) - 0.525
    p_payoff = np.maximum(0, 4.5 - spot_range) - 0.350
    comb_payoff = c_payoff + p_payoff

    fig_payoff = go.Figure()
    fig_payoff.add_trace(go.Scatter(x=spot_range, y=c_payoff, mode="lines", name="ATM Call Payoff", line=dict(color="#10b981", dash="dash")))
    fig_payoff.add_trace(go.Scatter(x=spot_range, y=p_payoff, mode="lines", name="OTM Put Payoff", line=dict(color="#3b82f6", dash="dash")))
    fig_payoff.add_trace(go.Scatter(x=spot_range, y=comb_payoff, mode="lines", name="Combined Strategy Payoff", line=dict(color="#f59e0b", width=3)))
    fig_payoff.add_vline(x=5.0, line_dash="dot", line_color="#94a3b8", annotation_text="Spot ($5.00)")
    fig_payoff.update_layout(
        xaxis_title="GGAL Underlying Price ($)",
        yaxis_title="PnL per Share ($)",
        margin=dict(t=30, b=20, l=10, r=10),
        height=360
    )
    st.plotly_chart(fig_payoff, use_container_width=True)

    # Detailed Derivative Positions Table
    st.markdown("### Derivative Positions Detail")
    d_records = []
    for k, v in sens_dict.items():
        d_records.append({
            "Contract": k,
            "Product Name": v["name"],
            "Type": v["type"],
            "Notional": f"{curr_sym} {v['notional'] * curr_mult:,.0f}",
            "Market Value": f"{curr_sym} {v['market_value'] * curr_mult:,.0f}",
            "Delta Exposure": f"{curr_sym} {v.get('delta_usd', 0.0) * curr_mult:,.0f}",
            "Risk Profile / Description": v["description"]
        })
    st.dataframe(pd.DataFrame(d_records), use_container_width=True, hide_index=True)


# ==============================================================================
# TAB 5: MACRO SCENARIO STRESS TESTING
# ==============================================================================
with tab_stress:
    st.subheader("Macro Stress Testing & Historical Argentine Crisis Replays")
    st.caption("Evaluate portfolio resilience under extreme market crises and custom multi-factor shocks.")

    s_left, s_right = st.columns([1, 1.4])

    with s_left:
        st.markdown("#### Historical Crisis Presets")
        scenario_choice = st.selectbox(
            "Select Historical Argentine Event",
            options=list(StressTestEngine.HISTORICAL_SCENARIOS.keys()),
            format_func=lambda k: StressTestEngine.HISTORICAL_SCENARIOS[k]["name"]
        )
        selected_scenario = StressTestEngine.HISTORICAL_SCENARIOS[scenario_choice]
        st.info(f"**Scenario Context**: {selected_scenario['description']}")

        st.markdown("---")
        st.markdown("#### Interactive Factor Sliders")
        eq_shock = st.slider("Equity Market Shock (%)", -60, 40, int(selected_scenario["equity_shock"] * 100), step=5) / 100.0
        bond_shock = st.slider("Sovereign Yield Shift (bps)", -500, 3000, int(selected_scenario["bond_yield_shift_bps"]), step=100)
        fx_shock_val = st.slider("USD/ARS Devaluation (%)", -20, 100, int(selected_scenario["fx_shock"] * 100), step=5) / 100.0
        vol_shock_val = st.slider("Volatility Spike (points)", 0, 60, int(selected_scenario["vol_shock_pts"]), step=5)
        badlar_shock_val = st.slider("BADLAR Rate Shift (bps)", -1000, 3000, int(selected_scenario["badlar_shift_bps"]), step=100)

    # Compute stress test
    stress_result = stress_engine.run_factor_stress_test(
        equity_shock=eq_shock,
        bond_yield_shift_bps=bond_shock,
        fx_shock=fx_shock_val,
        vol_shock_pts=vol_shock_val,
        badlar_shift_bps=badlar_shock_val
    )

    with s_right:
        st.markdown("#### Stress Impact Summary")
        sp1, sp2 = st.columns(2)
        with sp1:
            st.metric(
                "Total Stress PnL Impact",
                f"{curr_sym} {stress_result['total_pnl'] * curr_mult:,.0f}",
                f"{stress_result['portfolio_return_pct']:.2f}% Drawdown",
                delta_color="inverse"
            )
        with sp2:
            st.metric(
                "Stressed Portfolio Value",
                f"{curr_sym} {stress_result['stressed_portfolio_value'] * curr_mult:,.0f}",
                f"Initial: {curr_sym} {stress_result['initial_portfolio_value'] * curr_mult:,.0f}"
            )

        # Asset class breakdown bar
        df_ac_stress = stress_result["by_asset_class"].copy()
        df_ac_stress["PnL Display"] = df_ac_stress["PnL Impact ($)"] * curr_mult

        fig_ac_bar = px.bar(
            df_ac_stress,
            x="Asset Class",
            y="PnL Display",
            color="Asset Class",
            color_discrete_map={
                AssetClass.EQUITY.value: "#3b82f6",
                AssetClass.BOND.value: "#10b981",
                AssetClass.CASH.value: "#8b5cf6",
                AssetClass.DERIVATIVE.value: "#f59e0b"
            },
            title="PnL Contribution by Asset Class Under Stress"
        )
        fig_ac_bar.update_layout(height=280, margin=dict(t=30, b=10, l=10, r=10))
        st.plotly_chart(fig_ac_bar, use_container_width=True)

    st.markdown("### Stress PnL by Individual Asset")
    df_pos_stress = stress_result["by_position"].copy()
    df_pos_stress["Market Value"] = (df_pos_stress["Market Value ($)"] * curr_mult).apply(lambda x: f"{curr_sym} {x:,.0f}")
    df_pos_stress["PnL Impact"] = (df_pos_stress["PnL Impact ($)"] * curr_mult).apply(lambda x: f"{curr_sym} {x:,.0f}")
    df_pos_stress["Stressed Value"] = (df_pos_stress["Stressed Value ($)"] * curr_mult).apply(lambda x: f"{curr_sym} {x:,.0f}")
    df_pos_stress["Return (%)"] = df_pos_stress["Return Impact (%)"].apply(lambda x: f"{x:+.2f}%")

    st.dataframe(
        df_pos_stress[["Ticker", "Name", "Asset Class", "Market Value", "PnL Impact", "Return (%)", "Stressed Value"]],
        use_container_width=True,
        hide_index=True
    )


# ==============================================================================
# TAB 6: METHODOLOGY & DOCUMENTATION
# ==============================================================================
with tab_docs:
    st.subheader("Quantitative Risk Methodology & Mathematical Formulations")

    st.markdown("""
    ### 1. Value at Risk (VaR) & Expected Shortfall (CVaR)

    - **Parametric (Variance-Covariance)**:
      $$\\text{VaR}_\\alpha(h) = z_\\alpha \\cdot \\sigma_p \\cdot \\sqrt{h} \\cdot V$$
      $$\\text{CVaR}_\\alpha(h) = \\sigma_p \\sqrt{h} \\cdot \\frac{\\phi(z_\\alpha)}{1 - \\alpha} \\cdot V$$
      Where $\\sigma_p = \\sqrt{w^T \\Sigma w}$ is portfolio volatility and $\\phi$ is the standard normal PDF.

    - **Historical Simulation**:
      Portfolio daily returns vector $R_{p, t} = \\sum_{i} w_i R_{i, t}$.
      $$\\text{VaR}_\\alpha = \\text{Percentile}\\left( -R_p \\cdot V, \\alpha \\right)$$
      $$\\text{CVaR}_\\alpha = \\mathbb{E}[L \\mid L \\ge \\text{VaR}_\\alpha]$$

    - **Monte Carlo Simulation (10,000 Paths)**:
      Correlated draws generated via Cholesky factor $L$ where $\\Sigma = L L^T$:
      $$r_{sim} = \\mu + L \\cdot Z, \\quad Z \\sim \\mathcal{N}(0, I)$$

    ### 2. Base VaR vs. Stressed VaR (sVaR) Framework (Basel 2.5 / III)
    - **Base VaR**: Calibrated to standard trailing 252-day market conditions (recent empirical volatility & correlations).
    - **Stressed VaR (sVaR)**: Calibrated to an extreme 12-month historical crisis window (Argentine PASO shock / debt restructuring freeze). Volatilities scale $1.8\\times - 2.5\\times$, asset correlations converge towards 1.0, and tail fatness increases ($t$-distribution $\\nu=4$).
    - **Capital Charge**: $\\text{Capital} = 3 \\times \\max(\\text{Base VaR}, \\text{sVaR})$.

    ### 3. Argentine Sovereign Bond Analytics
    - **Modified Duration**: $D_{\\text{mod}} = \\frac{D_{\\text{mac}}}{1 + y/m}$
    - **Convexity Taylor Expansion**: $\\frac{\\Delta P}{P} \\approx -D_{\\text{mod}} \\Delta y + \\frac{1}{2} C (\\Delta y)^2$
    - **DV01**: Dollar change in bond value per 1 basis point ($0.0001$) shift in yield.

    ### 4. Option Greeks (Black-Scholes-Merton)
    - $\\Delta = \\frac{\\partial V}{\\partial S} = \\Phi(d_1)$ (Call) or $\\Phi(d_1) - 1$ (Put)
    - $\\Gamma = \\frac{\\partial^2 V}{\\partial S^2} = \\frac{\\phi(d_1)}{S \\sigma \\sqrt{T}}$
    - $\\mathcal{V} = \\frac{\\partial V}{\\partial \\sigma} = S \\phi(d_1) \\sqrt{T}$
    - $\\Theta = \\frac{\\partial V}{\\partial t}$

    ### 5. Modern Portfolio Theory (MPT) & Markowitz Efficient Frontier
    - **Portfolio Expected Return & Volatility**:
      $$\\mu_p = \\mathbf{w}^T \\boldsymbol{\\mu}, \\quad \\sigma_p = \\sqrt{\\mathbf{w}^T \\boldsymbol{\\Sigma} \\mathbf{w}}, \\quad \\text{Sharpe} = \\frac{\\mu_p - R_f}{\\sigma_p}$$
    - **Maximum Sharpe Ratio (Tangency) Portfolio**:
      $$\\max_{\\mathbf{w}} \\frac{\\mathbf{w}^T \\boldsymbol{\\mu} - R_f}{\\sqrt{\\mathbf{w}^T \\boldsymbol{\\Sigma} \\mathbf{w}}} \\quad \\text{subject to} \\quad \\sum_{i=1}^N w_i = 1, \\; w_i \\ge 0$$
    - **Minimum Volatility Portfolio**:
      $$\\min_{\\mathbf{w}} \\sqrt{\\mathbf{w}^T \\boldsymbol{\\Sigma} \\mathbf{w}} \\quad \\text{subject to} \\quad \\sum_{i=1}^N w_i = 1, \\; w_i \\ge 0$$
    - **Capital Allocation Line (CAL)**:
      $$\\mathbb{E}[R_C] = R_f + \\left( \\frac{\\mu^* - R_f}{\\sigma^*} \\right) \\sigma_C$$
    """)

