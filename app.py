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
uploaded_file = st.sidebar.file_uploader("Upload Monthly `input.xlsx`", type=["xlsx", "xls"])

if uploaded_file is not None:
    portfolio, settings = load_portfolio_from_excel(uploaded_file)
    source_label = f"Uploaded `{uploaded_file.name}`"
elif os.path.exists("input.xlsx"):
    portfolio, settings = load_portfolio_from_excel("input.xlsx")
    source_label = "Local `input.xlsx`"
else:
    portfolio = create_default_portfolio()
    settings = DEFAULT_SETTINGS.copy()
    source_label = "Default System Portfolio"

st.sidebar.success(f"**Source**: {source_label}\n\n**Cycle**: {settings.get('Reporting_Month', 'Monthly')}")

# Download template button
template_bytes = get_excel_template_bytes()
st.sidebar.download_button(
    label="📥 Download Template (input.xlsx)",
    data=template_bytes,
    file_name="input.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    help="Download formatted Excel workbook template to update monthly holdings and parameters."
)

var_engine = VaREngine(portfolio)
stress_engine = StressTestEngine(portfolio)

st.sidebar.markdown("---")
st.sidebar.markdown("### Currency & Valuation")
default_ccl = float(settings.get("USD_ARS_CCL_Rate", 1280.0))
fx_rate = st.sidebar.number_input("USD/ARS CCL Rate", min_value=500.0, max_value=5000.0, value=default_ccl, step=10.0)
curr_view = st.sidebar.radio("Display Currency", ["USD ($)", "ARS ($)"], horizontal=True)
curr_mult = fx_rate if curr_view == "ARS ($)" else 1.0
curr_sym = "ARS $" if curr_view == "ARS ($)" else "USD $"

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
num_der = len(portfolio.get_positions_by_class(AssetClass.DERIVATIVE))
st.sidebar.info(
    f"💡 **Active Portfolio Book**: {len(portfolio.positions)} Positions\n\n"
    f"• **Equities**: {num_eq} positions\n"
    f"• **Sovereign Debt**: {num_bd} positions\n"
    f"• **Derivatives**: {num_der} contracts"
)


# --- TOP BANNER METRICS ---
comparison = var_engine.run_scenario_comparison(confidence_level=conf_level, horizon_days=horizon_days)

st.title("🏛️ Argentine Trading Portfolio - Market Risk Analysis")
st.markdown(
    f"**Live Risk Dashboard** | Institutional Trading Book | Standard Base Regime vs. **Stressed VaR (sVaR)** | Horizon: **{horizon_days}d** | Confidence: **{conf_level*100:.1f}%**"
)

kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
with kpi1:
    port_val = portfolio.total_value * curr_mult
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Portfolio NAV</div>
        <div class="metric-value">{curr_sym} {port_val:,.0f}</div>
        <div class="metric-sub">15 Book Positions</div>
    </div>
    """, unsafe_allow_html=True)

with kpi2:
    base_var = comparison["base"]["historical"]["var_dollar"] * curr_mult
    base_pct = comparison["base"]["historical"]["var_pct"]
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Base VaR (Hist {conf_level*100:.1f}%)</div>
        <div class="metric-value">{curr_sym} {base_var:,.0f}</div>
        <div class="metric-sub">{base_pct:.2f}% of NAV | {horizon_days}d horizon</div>
    </div>
    """, unsafe_allow_html=True)

with kpi3:
    stress_var = comparison["stress"]["historical"]["var_dollar"] * curr_mult
    stress_pct = comparison["stress"]["historical"]["var_pct"]
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
tab_overview, tab_var, tab_bonds, tab_derivatives, tab_stress, tab_docs = st.tabs([
    "📊 Portfolio Overview",
    "⚡ VaR & Expected Shortfall (Base vs Stress)",
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
                AssetClass.DERIVATIVE.value: "#f59e0b"
            },
            title="Exposure Weights by Individual Asset (%)"
        )
        fig_bar.update_layout(yaxis=dict(autorange="reversed"), margin=dict(t=40, b=10, l=10, r=10), height=340)
        st.plotly_chart(fig_bar, use_container_width=True)

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
                AssetClass.DERIVATIVE.value: "#f59e0b"
            }
        )
        fig_c_stress.update_layout(yaxis=dict(autorange="reversed"), height=380, margin=dict(t=20, b=10, l=10, r=10))
        st.plotly_chart(fig_c_stress, use_container_width=True)


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
    """)
