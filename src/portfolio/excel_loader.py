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


def parse_argentine_number(val) -> float:
    """Parses Argentine decimal/thousand format (e.g. 1.192.531,88 or 1455,3 or 100)."""
    if pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def load_portfolio_from_cocos_csv(
    file_source: Union[str, io.BytesIO],
    ccl_rate: float = 1582.60
) -> Tuple[Portfolio, Dict[str, Any]]:
    """Parses standard Argentine broker export CSVs (such as Cocos Capital).
    Extracts Tickers, Quantities, Prices, and maps them to Equities, Bonds, and Cash.
    """
    import re
    import csv

    settings = DEFAULT_SETTINGS.copy()
    settings["USD_ARS_CCL_Rate"] = ccl_rate
    settings["Portfolio_Name"] = "Cocos Capital Portfolio"

    if isinstance(file_source, str):
        with open(file_source, "r", encoding="utf-8-sig", errors="ignore") as f:
            lines = f.readlines()
    else:
        content = file_source.read()
        if isinstance(content, bytes):
            content = content.decode("utf-8-sig", errors="ignore")
        lines = content.splitlines()

    positions = []
    sep = ";" if any(";" in l for l in lines[:5]) else ","

    reader = csv.DictReader(lines, delimiter=sep)
    for row in reader:
        r = {k.strip().lower(): str(v).strip() for k, v in row.items() if k}
        instr = r.get("instrumento", r.get("especie", r.get("ticker", "")))
        if not instr:
            continue

        # Extract ticker from parentheses e.g. "CEDEAR SPDR S&P 500 (SPY)" -> SPY
        m = re.search(r'\(([^)]+)\)$', instr)
        if m:
            ticker = m.group(1).strip()
            name = instr[:m.start()].strip()
        else:
            ticker = instr.strip()
            name = instr.strip()

        qty = parse_argentine_number(r.get("cantidad", 0))
        price_val = parse_argentine_number(r.get("precio", 0))
        total_val = parse_argentine_number(r.get("total", 0))
        moneda = r.get("moneda", "ARS").upper()

        if total_val <= 0.0 and qty > 0 and price_val > 0:
            total_val = qty * price_val

        # Convert to USD
        if moneda == "USD":
            mkt_val_usd = total_val
            unit_price_usd = price_val
        else:
            mkt_val_usd = total_val / ccl_rate
            unit_price_usd = price_val / ccl_rate

        if mkt_val_usd < 0.5:
            # Skip dust (e.g. 0,01 ARS)
            continue

        instr_upper = instr.upper()
        ticker_upper = ticker.upper()

        if any(c in ticker_upper for c in ["ARS", "USD", "EXT", "CAUCION"]) or "FCI" in instr_upper:
            asset_class = AssetClass.CASH
            c_type = "Money Market FCI" if "FCI" in instr_upper else "Liquid Cash"
            pos = Position(
                ticker=f"CASH_{ticker}" if ticker in ["ARS", "USD", "EXT"] else ticker,
                name=name or ticker,
                asset_class=asset_class,
                quantity=mkt_val_usd,
                unit_price=1.0,
                market_value=round(mkt_val_usd, 2),
                currency="USD",
                details={"type": c_type, "moneda": moneda, "total_ars": total_val if moneda == "ARS" else total_val * ccl_rate}
            )
        elif any(b in instr_upper for b in ["BONO", "LETRA", "LECAP", "BONCAP", "DEUDA", "STEP UP"]) or any(b in ticker_upper for b in ["AL", "GD", "T15", "T31", "TX", "BOP"]):
            asset_class = AssetClass.BOND
            try:
                metrics = ArgentineBondPricer.calculate_risk_metrics(ticker, market_price=unit_price_usd*100)
                mod_dur = metrics["modified_duration"]
                convexity = metrics["convexity"]
                dv01 = metrics["dv01_per_100"]
                ytm = metrics["ytm_percent"] / 100.0
            except Exception:
                mod_dur = 2.5
                convexity = 8.0
                dv01 = 280.0
                ytm = 0.16

            pos = Position(
                ticker=ticker,
                name=name or ticker,
                asset_class=asset_class,
                quantity=qty,
                unit_price=unit_price_usd,
                market_value=round(mkt_val_usd, 2),
                currency="USD",
                details={
                    "law": "Argentina" if ("AL" in ticker or "T" in ticker) else "New York",
                    "ytm": ytm,
                    "modified_duration": mod_dur,
                    "convexity": convexity,
                    "dv01": dv01,
                    "coupon": 0.0075 if ("30" in ticker) else 0.036
                }
            )
        else:
            # Equities / Cedears
            asset_class = AssetClass.EQUITY
            clean_ticker = ticker if (".BA" in ticker or "CEDEAR" not in instr_upper) else f"{ticker}.BA"
            pos = Position(
                ticker=clean_ticker,
                name=name or ticker,
                asset_class=asset_class,
                quantity=qty,
                unit_price=unit_price_usd,
                market_value=round(mkt_val_usd, 2),
                currency="USD",
                details={"sector": "Cedear US / Equities" if "CEDEAR" in instr_upper else "BYMA Equity"}
            )

        positions.append(pos)

    if not positions:
        return create_default_portfolio(), settings

    port = Portfolio(name="Cocos Capital Portfolio", positions=positions)
    port.update_weights()
    return port, settings


def load_portfolio_from_excel(
    file_source: Union[str, io.BytesIO] = "input.xlsx"
) -> Tuple[Portfolio, Dict[str, Any]]:
    """Loads and validates a trading portfolio from an Excel spreadsheet or broker CSV.

    :param file_source: Filepath or BytesIO buffer from Streamlit file_uploader
    :return: (Portfolio object, settings dict)
    """
    # Check if CSV file or buffer
    is_csv = False
    if isinstance(file_source, str) and file_source.lower().endswith(".csv"):
        is_csv = True
    elif hasattr(file_source, "name") and str(file_source.name).lower().endswith(".csv"):
        is_csv = True

    if is_csv:
        return load_portfolio_from_cocos_csv(file_source)

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

        ccl_rate = float(settings.get("USD_ARS_CCL_Rate", 1582.60))

        # -------------------------------------------------------------
        # 2. PARSE EQUITIES / CEDEARS
        # -------------------------------------------------------------
        eq_sheet = next((sheet_map[s] for s in sheet_names if "equit" in s or "stock" in s or "accion" in s or "cedear" in s), None)
        if eq_sheet:
            df_eq = pd.read_excel(excel_file, sheet_name=eq_sheet)
            for _, r in df_eq.iterrows():
                ticker = str(r.get("Ticker", "")).strip()
                if not ticker or pd.isna(ticker):
                    continue
                name = str(r.get("Name", ticker))
                qty = float(r.get("Quantity", 0.0))
                price = float(r.get("Unit_Price_USD", 0.0))

                # Auto-convert from ARS if USD price missing
                if price <= 0.0:
                    for ars_col in ["Unit_Price_ARS", "Price_ARS", "Price_ARS_BYMA", "Precio_ARS"]:
                        if ars_col in r and pd.notna(r[ars_col]) and float(r[ars_col]) > 0:
                            price = float(r[ars_col]) / ccl_rate
                            break

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
        # 3. PARSE SOVEREIGN BONDS & CORPORATE ONs
        # -------------------------------------------------------------
        bond_sheet = next((sheet_map[s] for s in sheet_names if any(k in s for k in ["bond", "bono", "deuda", "renta fija", "on"])), None)
        if bond_sheet:
            df_bonds = pd.read_excel(excel_file, sheet_name=bond_sheet)
            for _, r in df_bonds.iterrows():
                ticker = str(r.get("Ticker", "")).strip()
                if not ticker or pd.isna(ticker):
                    continue
                name = str(r.get("Name", ticker))
                law = str(r.get("Governing_Law", "New York"))
                qty = float(r.get("Nominal_Quantity", r.get("Quantity", 0.0)))
                clean_price = float(r.get("Clean_Price_USD", 0.0))

                # Auto-convert from ARS if clean price USD missing
                if clean_price <= 0.0:
                    for ars_col in ["Clean_Price_ARS", "Price_ARS", "Precio_ARS"]:
                        if ars_col in r and pd.notna(r[ars_col]) and float(r[ars_col]) > 0:
                            clean_price = (float(r[ars_col]) / ccl_rate) / 100.0
                            break
                if clean_price <= 0.0:
                    clean_price = 0.50

                mkt_val = float(r.get("Market_Value_USD", 0.0))
                if mkt_val <= 0.0 and qty > 0:
                    mkt_val = qty * clean_price

                # Check if risk metrics are in Excel, otherwise calculate via ArgentineBondPricer
                mod_dur = float(r.get("Modified_Duration", 0.0)) if pd.notna(r.get("Modified_Duration")) else 0.0
                convexity = float(r.get("Convexity", 0.0)) if pd.notna(r.get("Convexity")) else 0.0
                dv01 = float(r.get("DV01", 0.0)) if pd.notna(r.get("DV01")) else 0.0
                ytm = float(r.get("YTM", 0.0)) if pd.notna(r.get("YTM")) else 0.0

                if mod_dur <= 0.0:
                    try:
                        metrics = ArgentineBondPricer.calculate_risk_metrics(ticker, market_price=clean_price*100)
                        mod_dur = metrics["modified_duration"]
                        convexity = metrics["convexity"]
                        dv01 = metrics["dv01_per_100"]
                        ytm = metrics["ytm_percent"] / 100.0
                    except Exception:
                        mod_dur = 2.8
                        convexity = 10.0
                        dv01 = 300.0
                        ytm = 0.15

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
        # 4. PARSE CASH & LIQUIDITY (Caución, Money Market FCI, Cash)
        # -------------------------------------------------------------
        cash_sheet = next((sheet_map[s] for s in sheet_names if any(k in s for k in ["cash", "liquid", "caja", "caucion"])), None)
        if cash_sheet:
            df_cash = pd.read_excel(excel_file, sheet_name=cash_sheet)
            for _, r in df_cash.iterrows():
                ticker = str(r.get("Ticker", r.get("Identifier", ""))).strip()
                if not ticker or pd.isna(ticker):
                    continue
                name = str(r.get("Name", ticker))
                c_type = str(r.get("Type", "Cash"))
                amt_usd = float(r.get("Amount_USD", r.get("Market_Value_USD", 0.0)))
                amt_ars = float(r.get("Amount_ARS", 0.0))
                if amt_usd <= 0.0 and amt_ars > 0.0:
                    amt_usd = amt_ars / ccl_rate
                elif amt_ars <= 0.0 and amt_usd > 0.0:
                    amt_ars = amt_usd * ccl_rate

                yield_pct = float(r.get("Annual_Yield_Pct", r.get("Yield", 0.0))) if pd.notna(r.get("Annual_Yield_Pct", r.get("Yield", None))) else 0.0

                positions.append(Position(
                    ticker=ticker,
                    name=name,
                    asset_class=AssetClass.CASH,
                    quantity=amt_usd,
                    unit_price=1.0,
                    market_value=amt_usd,
                    currency="USD",
                    details={
                        "type": c_type,
                        "amount_ars": amt_ars,
                        "annual_yield": yield_pct,
                        "description": f"Liquid funds yielding {yield_pct:.1f}% p.a."
                    }
                ))

        # -------------------------------------------------------------
        # 5. PARSE DERIVATIVES (Optional: Rofex Futures, Options, NDFs, Swaps)
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
