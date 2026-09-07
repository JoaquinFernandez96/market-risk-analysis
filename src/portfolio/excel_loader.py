"""Excel Portfolio Loader.
Parses multi-tab input.xlsx workbooks to build dynamic, monthly-updated
Portfolio objects with arbitrary holdings and risk settings.
"""
import io
import os
from typing import Dict, Tuple, Any, Union
import pandas as pd

from .models import Portfolio, Position, AssetClass, create_default_portfolio
from src.pricing.bonds import ArgentineBondPricer


DEFAULT_SETTINGS = {
    "Portfolio_Name": "Trading Portfolio Argentina",
    "USD_ARS_CCL_Rate": 1280.0,
    "Default_Confidence_Level": 0.95,
    "Default_Holding_Period_Days": 1,
    "Stress_Vol_Multiplier": 2.2,
    "Stress_Correlation_Spike": 0.90,
    "Reporting_Month": "September 2026"
}


def load_portfolio_from_excel(
    file_source: Union[str, io.BytesIO] = "input.xlsx"
) -> Tuple[Portfolio, Dict[str, Any]]:
    """Loads and validates a trading portfolio from an Excel spreadsheet.

    :param file_source: Filepath or BytesIO buffer from Streamlit file_uploader
    :return: (Portfolio object, settings dict)
    """
    if isinstance(file_source, str) and not os.path.exists(file_source):
        print(f"Warning: {file_source} not found. Falling back to default portfolio.")
        return create_default_portfolio(), DEFAULT_SETTINGS.copy()

    try:
        excel_file = pd.ExcelFile(file_source)
        sheet_names = [s.strip().lower() for s in excel_file.sheet_names]
        sheet_map = {s.strip().lower(): s for s in excel_file.sheet_names}

        positions = []
        settings = DEFAULT_SETTINGS.copy()

        # -------------------------------------------------------------
        # 1. PARSE SETTINGS
        # -------------------------------------------------------------
        settings_sheet = next((sheet_map[s] for s in sheet_names if "setting" in s or "config" in s), None)
        if settings_sheet:
            df_set = pd.read_excel(excel_file, sheet_name=settings_sheet)
            if "Parameter" in df_set.columns and "Value" in df_set.columns:
                for _, row in df_set.iterrows():
                    param = str(row["Parameter"]).strip()
                    val = row["Value"]
                    if pd.notna(val) and param:
                        try:
                            # Parse numeric if possible
                            if str(val).replace('.', '', 1).isdigit():
                                settings[param] = float(val) if '.' in str(val) else int(val)
                            else:
                                settings[param] = val
                        except Exception:
                            settings[param] = val

        # -------------------------------------------------------------
        # 2. PARSE EQUITIES
        # -------------------------------------------------------------
        eq_sheet = next((sheet_map[s] for s in sheet_names if "equit" in s or "stock" in s or "accion" in s), None)
        if eq_sheet:
            df_eq = pd.read_excel(excel_file, sheet_name=eq_sheet)
            for _, r in df_eq.iterrows():
                ticker = str(r.get("Ticker", "")).strip()
                if not ticker or pd.isna(ticker):
                    continue
                name = str(r.get("Name", ticker))
                qty = float(r.get("Quantity", 0.0))
                price = float(r.get("Unit_Price_USD", 0.0))
                mkt_val = float(r.get("Market_Value_USD", 0.0))
                if mkt_val <= 0.0 and qty > 0 and price > 0:
                    mkt_val = qty * price
                elif price <= 0.0 and qty > 0 and mkt_val > 0:
                    price = mkt_val / qty

                sector = str(r.get("Sector", "General Equity"))
                adr = str(r.get("ADR_Ticker", ""))
                beta = float(r.get("Beta", 1.0)) if pd.notna(r.get("Beta")) else 1.0

                positions.append(Position(
                    ticker=ticker,
                    name=name,
                    asset_class=AssetClass.EQUITY,
                    quantity=qty,
                    unit_price=price,
                    market_value=mkt_val,
                    currency="USD",
                    details={"sector": sector, "adrexchange": adr, "beta": beta}
                ))

        # -------------------------------------------------------------
        # 3. PARSE SOVEREIGN BONDS
        # -------------------------------------------------------------
        bond_sheet = next((sheet_map[s] for s in sheet_names if "bond" in s or "bono" in s or "deuda" in s), None)
        if bond_sheet:
            df_bonds = pd.read_excel(excel_file, sheet_name=bond_sheet)
            for _, r in df_bonds.iterrows():
                ticker = str(r.get("Ticker", "")).strip()
                if not ticker or pd.isna(ticker):
                    continue
                name = str(r.get("Name", ticker))
                law = str(r.get("Governing_Law", "New York"))
                qty = float(r.get("Nominal_Quantity", 0.0))
                clean_price = float(r.get("Clean_Price_USD", 0.50))
                mkt_val = float(r.get("Market_Value_USD", 0.0))
                if mkt_val <= 0.0 and qty > 0:
                    mkt_val = qty * clean_price

                # Check if risk metrics are in Excel, otherwise calculate via ArgentineBondPricer
                mod_dur = float(r.get("Modified_Duration", 0.0)) if pd.notna(r.get("Modified_Duration")) else 0.0
                convexity = float(r.get("Convexity", 0.0)) if pd.notna(r.get("Convexity")) else 0.0
                dv01 = float(r.get("DV01", 0.0)) if pd.notna(r.get("DV01")) else 0.0
                ytm = float(r.get("YTM", 0.16)) if pd.notna(r.get("YTM")) else 0.16

                if mod_dur <= 0.0:
                    try:
                        metrics = ArgentineBondPricer.calculate_risk_metrics(ticker, market_price=clean_price*100)
                        mod_dur = metrics["modified_duration"]
                        convexity = metrics["convexity"]
                        dv01 = metrics["dv01_per_100"]
                        ytm = metrics["ytm_percent"] / 100.0
                    except Exception:
                        mod_dur = 3.0
                        convexity = 12.0
                        dv01 = 300.0

                positions.append(Position(
                    ticker=ticker,
                    name=name,
                    asset_class=AssetClass.BOND,
                    quantity=qty,
                    unit_price=clean_price,
                    market_value=mkt_val,
                    currency="USD",
                    details={
                        "law": law,
                        "ytm": ytm,
                        "modified_duration": mod_dur,
                        "convexity": convexity,
                        "dv01": dv01,
                        "maturity": str(r.get("Maturity_Date", "2030-07-09")),
                        "coupon": float(r.get("Coupon_Rate", 0.01))
                    }
                ))

        # -------------------------------------------------------------
        # 4. PARSE DERIVATIVES
        # -------------------------------------------------------------
        deriv_sheet = next((sheet_map[s] for s in sheet_names if "deriv" in s or "opcion" in s or "futuro" in s), None)
        if deriv_sheet:
            df_deriv = pd.read_excel(excel_file, sheet_name=deriv_sheet)
            for _, r in df_deriv.iterrows():
                ticker = str(r.get("Identifier", r.get("Ticker", ""))).strip()
                if not ticker or pd.isna(ticker):
                    continue
                name = str(r.get("Name", ticker))
                d_type = str(r.get("Type", "Derivative"))
                qty = float(r.get("Quantity_Contracts", 1.0))
                price = float(r.get("Unit_Price_USD", 0.0))
                mkt_val = float(r.get("Market_Value_USD", 0.0))
                if mkt_val <= 0.0 and qty > 0 and price > 0:
                    mkt_val = qty * price
                notional = float(r.get("Notional_USD", mkt_val)) if pd.notna(r.get("Notional_USD")) else mkt_val

                delta = float(r.get("Delta", 1.0)) if pd.notna(r.get("Delta")) else 1.0
                gamma = float(r.get("Gamma", 0.0)) if pd.notna(r.get("Gamma")) else 0.0
                vega = float(r.get("Vega", 0.0)) if pd.notna(r.get("Vega")) else 0.0
                theta = float(r.get("Theta", 0.0)) if pd.notna(r.get("Theta")) else 0.0
                dv01 = float(r.get("DV01", 0.0)) if pd.notna(r.get("DV01")) else 0.0
                desc = str(r.get("Description", ""))

                positions.append(Position(
                    ticker=ticker,
                    name=name,
                    asset_class=AssetClass.DERIVATIVE,
                    quantity=qty,
                    unit_price=price if price > 0 else mkt_val,
                    market_value=mkt_val,
                    notional=notional,
                    currency="USD",
                    details={
                        "type": d_type,
                        "delta": delta,
                        "gamma": gamma,
                        "vega": vega,
                        "theta": theta,
                        "dv01": dv01,
                        "description": desc,
                        "underlying": str(r.get("Underlying", ""))
                    }
                ))

        if not positions:
            print("Warning: No positions parsed from Excel. Falling back to default portfolio.")
            return create_default_portfolio(), settings

        portfolio = Portfolio(name=settings.get("Portfolio_Name", "Trading Portfolio Argentina"), positions=positions)
        portfolio.update_weights()
        return portfolio, settings

    except Exception as exc:
        print(f"Error loading Excel file: {exc}. Falling back to default.")
        return create_default_portfolio(), DEFAULT_SETTINGS.copy()


def get_excel_template_bytes() -> bytes:
    """Reads input.xlsx and returns raw bytes for file download in Streamlit."""
    if os.path.exists("input.xlsx"):
        with open("input.xlsx", "rb") as f:
            return f.read()
    else:
        # Generate on the fly
        from create_template_excel import build_template
        build_template()
        with open("input.xlsx", "rb") as f:
            return f.read()
