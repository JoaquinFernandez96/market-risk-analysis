"""Supporting schedules and Excel export engine for Parametric and Historical VaR.
Reconstructs daily asset market value evolution, returns, dollar PnL series,
covariance/correlation matrices, and tail-loss audit tables in dual currencies (USD & ARS).
"""
import io
from typing import Dict, Any, Tuple
import numpy as np
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from src.portfolio.models import Portfolio
from src.risk.var_engine import VaREngine


def generate_market_value_evolution(
    returns_df: pd.DataFrame,
    portfolio: Portfolio,
    ccl_rate: float
) -> pd.DataFrame:
    """Reconstructs daily market value evolution ($ USD and $ ARS) for all portfolio assets

    normalized so that the final row matches current portfolio market values.
    """
    dates = returns_df.index
    pos_dict = {p.ticker: p for p in portfolio.positions}
    tickers = [p.ticker for p in portfolio.positions]

    # Calculate cumulative growth from daily returns: (1 + r).cumprod()
    cum_ret = (1.0 + returns_df[tickers]).cumprod()
    final_cum = cum_ret.iloc[-1]

    data = {}
    total_mv_usd = pd.Series(0.0, index=dates)

    for t in tickers:
        final_val_usd = pos_dict[t].market_value
        qty = pos_dict[t].quantity
        # Historical evolution backwards such that row[-1] == final_val_usd
        mv_usd = final_val_usd * (cum_ret[t] / final_cum[t])
        mv_ars = mv_usd * ccl_rate

        # Calculate unit price per share / bond / contract
        if qty > 0:
            unit_p_usd = mv_usd / qty
        else:
            unit_p_usd = mv_usd
        unit_p_ars = unit_p_usd * ccl_rate

        # Unambiguous column headers
        round_digits = 4 if (pos_dict[t].unit_price < 10.0) else 2
        data[f"{t}_UnitPrice_USD"] = unit_p_usd.round(round_digits)
        data[f"{t}_UnitPrice_ARS"] = unit_p_ars.round(2)
        data[f"{t}_TotalVal_USD"] = mv_usd.round(2)
        data[f"{t}_TotalVal_ARS"] = mv_ars.round(2)
        total_mv_usd += mv_usd

    df_mv = pd.DataFrame(data, index=dates)
    df_mv["Portfolio_NAV_USD"] = total_mv_usd.round(2)
    df_mv["Portfolio_NAV_ARS"] = (total_mv_usd * ccl_rate).round(2)
    df_mv.index.name = "Date"

    return df_mv


def generate_returns_pnl_schedule(
    returns_df: pd.DataFrame,
    mv_df: pd.DataFrame,
    portfolio: Portfolio,
    ccl_rate: float
) -> pd.DataFrame:
    """Generates daily returns (%) and daily dollar PnL (USD & ARS) for each asset

    and the aggregated portfolio.
    """
    tickers = [p.ticker for p in portfolio.positions]
    dates = returns_df.index

    data = {}
    port_daily_pnl_usd = pd.Series(0.0, index=dates)

    for t in tickers:
        # Return in %
        ret_pct = returns_df[t] * 100.0
        data[f"{t}_Return(%)"] = ret_pct.round(2)

        # Dollar PnL = Market Value Yesterday * Return Today
        usd_col = f"{t}_TotalVal_USD" if f"{t}_TotalVal_USD" in mv_df.columns else f"{t}_USD"
        if usd_col in mv_df.columns:
            prev_mv_usd = mv_df[usd_col].shift(1).fillna(mv_df[usd_col].iloc[0])
            pnl_usd = prev_mv_usd * returns_df[t]
            pnl_ars = pnl_usd * ccl_rate
            data[f"{t}_PnL_USD"] = pnl_usd.round(2)
            data[f"{t}_PnL_ARS"] = pnl_ars.round(2)
            port_daily_pnl_usd += pnl_usd

    df_pnl = pd.DataFrame(data, index=dates)
    df_pnl["Portfolio_Daily_PnL_USD"] = port_daily_pnl_usd.round(2)
    df_pnl["Portfolio_Daily_PnL_ARS"] = (port_daily_pnl_usd * ccl_rate).round(2)

    # Portfolio daily return %
    prev_tot_usd = mv_df["Portfolio_NAV_USD"].shift(1).fillna(mv_df["Portfolio_NAV_USD"].iloc[0])
    df_pnl["Portfolio_Return(%)"] = ((port_daily_pnl_usd / prev_tot_usd) * 100.0).round(2)
    df_pnl.index.name = "Date"

    return df_pnl


def generate_parametric_audit_schedules(
    var_engine: VaREngine,
    scenario: str,
    ccl_rate: float,
    confidence_level: float,
    horizon_days: int
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Generates Covariance Matrix, Correlation Matrix, and Component VaR schedule."""
    returns_df = var_engine.stress_returns_df if scenario.lower() == "stress" else var_engine.base_returns_df
    tickers = var_engine.tickers

    # 1. Annualized Covariance Matrix (%)
    cov_annual = (returns_df[tickers].cov() * 252.0 * 10000.0).round(2)

    # 2. Correlation Matrix
    corr_matrix = returns_df[tickers].corr().round(4)

    # 3. Component VaR breakdown
    df_comp = var_engine.get_component_var_breakdown(
        confidence_level=confidence_level, horizon_days=horizon_days, scenario=scenario
    ).copy()

    df_comp["Component VaR (ARS)"] = (df_comp["Component VaR ($)"] * ccl_rate).round(2)
    df_comp["Market Value (ARS)"] = (df_comp["Market Value ($)"] * ccl_rate).round(2)

    return cov_annual, corr_matrix, df_comp


def generate_tail_loss_audit_schedule(
    var_engine: VaREngine,
    scenario: str,
    ccl_rate: float,
    confidence_level: float,
    horizon_days: int
) -> pd.DataFrame:
    """Generates empirical tail-loss audit schedule for Historical Simulation."""
    returns_df = var_engine.stress_returns_df if scenario.lower() == "stress" else var_engine.base_returns_df
    hist_res = var_engine.calculate_historical_var(returns_df, confidence_level, horizon_days)

    losses = hist_res["loss_distribution"]
    var_threshold = hist_res["var_dollar"]

    # Filter tail events (losses exceeding VaR threshold)
    tail_losses = sorted([l for l in losses if l >= var_threshold], reverse=True)
    records = []
    for rank, loss_usd in enumerate(tail_losses, start=1):
        records.append({
            "Tail Rank": rank,
            "Loss ($ USD)": round(loss_usd, 2),
            "Loss ($ ARS)": round(loss_usd * ccl_rate, 2),
            "Loss (% NAV)": round(loss_usd / var_engine.total_value * 100.0, 2),
            "Exceeds VaR ($)": round(loss_usd - var_threshold, 2),
            "VaR Cutoff ($ USD)": round(var_threshold, 2),
            "CVaR / Expected Shortfall ($ USD)": round(hist_res["cvar_dollar"], 2),
        })

    if not records:
        # Fallback if no exceedances
        records.append({
            "Tail Rank": 1,
            "Loss ($ USD)": round(var_threshold, 2),
            "Loss ($ ARS)": round(var_threshold * ccl_rate, 2),
            "Loss (% NAV)": round(var_threshold / var_engine.total_value * 100.0, 2),
            "Exceeds VaR ($)": 0.0,
            "VaR Cutoff ($ USD)": round(var_threshold, 2),
            "CVaR / Expected Shortfall ($ USD)": round(hist_res["cvar_dollar"], 2),
        })

    return pd.DataFrame(records)


def build_var_supporting_excel(
    portfolio: Portfolio,
    var_engine: VaREngine,
    ccl_rate: float,
    confidence_level: float = 0.95,
    horizon_days: int = 1
) -> bytes:
    """Builds and styles the 6-tab supporting schedule workbook in memory (openpyxl)."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # Remove default blank sheet

    # Standard styling
    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    sub_fill = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10)
    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    # 1. Base Market Values & Returns
    base_mv = generate_market_value_evolution(var_engine.base_returns_df, portfolio, ccl_rate)
    base_pnl = generate_returns_pnl_schedule(var_engine.base_returns_df, base_mv, portfolio, ccl_rate)

    # 2. Stressed Market Values & Returns
    stress_mv = generate_market_value_evolution(var_engine.stress_returns_df, portfolio, ccl_rate)
    stress_pnl = generate_returns_pnl_schedule(var_engine.stress_returns_df, stress_mv, portfolio, ccl_rate)

    # 3. Parametric Matrices
    base_cov, base_corr, base_comp = generate_parametric_audit_schedules(
        var_engine, "base", ccl_rate, confidence_level, horizon_days
    )
    stress_cov, stress_corr, stress_comp = generate_parametric_audit_schedules(
        var_engine, "stress", ccl_rate, confidence_level, horizon_days
    )

    # 4. Tail Loss Audits
    base_tail = generate_tail_loss_audit_schedule(var_engine, "base", ccl_rate, confidence_level, horizon_days)
    stress_tail = generate_tail_loss_audit_schedule(var_engine, "stress", ccl_rate, confidence_level, horizon_days)

    sheets_to_add = [
        ("Base_Market_Values", base_mv.reset_index()),
        ("Base_Returns_PnL", base_pnl.reset_index()),
        ("Stressed_Market_Values", stress_mv.reset_index()),
        ("Stressed_Returns_PnL", stress_pnl.reset_index()),
    ]

    for title, df in sheets_to_add:
        ws = wb.create_sheet(title=title)
        # Format dates nicely
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")

        ws.append(list(df.columns))
        for row in df.itertuples(index=False):
            ws.append(list(row))

    # Tab 5: Parametric_Risk_Matrix
    ws_param = wb.create_sheet(title="Parametric_Risk_Matrix")
    ws_param.append(["PARAMETRIC RISK AUDIT: COVARIANCE & CORRELATION SCHEDULES"])
    ws_param.append(["Base Regime: Annualized Covariance Matrix (bps / %^2)"])
    ws_param.append(["Ticker"] + list(base_cov.columns))
    for t in base_cov.index:
        ws_param.append([t] + list(base_cov.loc[t]))

    ws_param.append([])
    ws_param.append(["Base Regime: Correlation Matrix"])
    ws_param.append(["Ticker"] + list(base_corr.columns))
    for t in base_corr.index:
        ws_param.append([t] + list(base_corr.loc[t]))

    ws_param.append([])
    ws_param.append(["Euler Component VaR Decomposition (Base vs Stressed)"])
    ws_param.append(list(base_comp.columns))
    for row in base_comp.itertuples(index=False):
        ws_param.append(list(row))

    # Tab 6: VaR_CVaR_Tail_Audit
    ws_tail = wb.create_sheet(title="VaR_CVaR_Tail_Audit")
    ws_tail.append([f"HISTORICAL SIMULATION TAIL-LOSS AUDIT (Confidence: {confidence_level*100:.1f}%, Horizon: {horizon_days}d)"])
    ws_tail.append(["1. Base Scenario: Exceedance Losses Beyond VaR Cutoff"])
    ws_tail.append(list(base_tail.columns))
    for row in base_tail.itertuples(index=False):
        ws_tail.append(list(row))

    ws_tail.append([])
    ws_tail.append(["2. Stressed Scenario (sVaR): Exceedance Losses Beyond Stressed VaR Cutoff"])
    ws_tail.append(list(stress_tail.columns))
    for row in stress_tail.itertuples(index=False):
        ws_tail.append(list(row))

    # Apply styling & auto-fit columns to all sheets
    for sheet in wb.worksheets:
        sheet.views.sheetView[0].showGridLines = True
        for col_idx, col in enumerate(sheet.iter_cols(values_only=False), start=1):
            max_len = 0
            for row_idx, cell in enumerate(col, start=1):
                cell.font = data_font
                cell.border = thin_border
                if row_idx == 1:
                    cell.fill = header_fill
                    cell.font = header_font
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                val_str = str(cell.value or "")
                max_len = max(max_len, len(val_str))
            col_letter = get_column_letter(col_idx)
            sheet.column_dimensions[col_letter].width = max(max_len + 3, 12)

    # Save to BytesIO
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()
