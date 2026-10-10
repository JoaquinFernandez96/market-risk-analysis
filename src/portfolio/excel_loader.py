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
    """Parses Argentine/European decimal/thousand format (e.g. 1.192.531,88 or 1.289,50)
    and strips non-numeric currency/percentage artifacts.
    """
    import re
    if pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    # Strip non-numeric artifacts (currency symbols, spaces, letters) keeping digits, '.', ',', '-', '+'
    s = re.sub(r"[^\d\.,\-+]", "", s)
    if not s or s in ("-", "+", ".", ","):
        return 0.0
    if "." in s and "," in s:
        # Determine whether ',' or '.' is the decimal separator (last separator wins)
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
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
    """Parses standard Argentine broker export CSVs (such as Cocos Capital portfolio_report.csv).
    Extracts Tickers, Quantities, Prices, handles multi-currency FX conversions (ARS/USD/EXT),
    filters micro-cash dust balances, and maps instruments to Equities, Bonds, and Cash/FCIs.
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
        if hasattr(file_source, "seek"):
            file_source.seek(0)
        content = file_source.read()
        if isinstance(content, bytes):
            content = content.decode("utf-8-sig", errors="ignore")
        lines = content.splitlines()

    positions = []
    sep = ";" if any(";" in l for l in lines[:5]) else ","

    reader = csv.DictReader(lines, delimiter=sep)
    for row in reader:
        r = {k.strip().lower(): str(v).strip() for k, v in row.items() if k}
        instr = next((r[k] for k in ["instrumento", "especie", "ticker", "activo", "descripcion"] if k in r and r[k]), "")
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

        raw_qty = next((r[k] for k in ["cantidad", "tenencia", "nominales", "posicion"] if k in r), 0)
        raw_price = next((r[k] for k in ["precio", "cotizacion", "costo", "ultimo_precio"] if k in r), 0)
        raw_total = next((r[k] for k in ["total", "valuacion", "monto", "importe"] if k in r), 0)
        raw_moneda = next((r[k] for k in ["moneda", "divisa"] if k in r), "ARS")

        qty = parse_argentine_number(raw_qty)
        price_val = parse_argentine_number(raw_price)
        total_val = parse_argentine_number(raw_total)
        moneda = str(raw_moneda).strip().upper()

        if total_val <= 0.0 and qty > 0 and price_val > 0:
            total_val = qty * price_val

        # Convert to USD using CCL / MEP FX rate for ARS-denominated rows
        is_usd_ccy = moneda in ("USD", "EXT", "U$S", "US$", "DOLAR", "DÓLAR")
        if is_usd_ccy:
            mkt_val_usd = total_val
            unit_price_usd = (mkt_val_usd / qty) if (qty > 0 and total_val > 0) else price_val
        else:
            mkt_val_usd = total_val / ccl_rate
            unit_price_usd = (mkt_val_usd / qty) if (qty > 0 and total_val > 0) else (price_val / ccl_rate)

        instr_upper = instr.upper()
        ticker_upper = ticker.upper()
        is_raw_cash_row = ticker_upper in ("ARS", "USD", "EXT", "PESOS", "DOLARES", "DÓLARES")

        # Filter out dust or micro-cash balances (e.g. residual ARS/EXT/USD cash rows)
        if mkt_val_usd < 0.5 or (is_raw_cash_row and mkt_val_usd < 5.0):
            continue

        if (
            is_raw_cash_row
            or any(c in ticker_upper for c in ["ARS", "USD", "EXT", "CAUCION", "COCOS", "FCI", "MM", "FBA", "SBS"])
            or any(c in instr_upper for c in ["FCI", "FONDO", "MONEY MARKET", "AHORRO", "CAUCION", "LIQUIDEZ"])
        ):
            asset_class = AssetClass.CASH
            c_type = "Money Market FCI" if ("FCI" in instr_upper or "COCOS" in ticker_upper or "FONDO" in instr_upper) else "Liquid Cash"
            pos = Position(
                ticker=f"CASH_{ticker_upper}" if is_raw_cash_row else ticker,
                name=name or ticker,
                asset_class=asset_class,
                quantity=mkt_val_usd if is_raw_cash_row else (qty if qty > 0 else mkt_val_usd),
                unit_price=1.0 if is_raw_cash_row else unit_price_usd,
                market_value=round(mkt_val_usd, 2),
                currency="USD",
                details={
                    "type": c_type,
                    "moneda": moneda,
                    "total_ars": total_val if not is_usd_ccy else total_val * ccl_rate,
                    "raw_total_ars": total_val if not is_usd_ccy else None,
                    "annual_yield": 4.5 if is_usd_ccy else 4.8,
                }
            )
        elif any(b in instr_upper for b in ["BONO", "LETRA", "LECAP", "BONCAP", "DEUDA", "STEP UP"]) or any(b in ticker_upper for b in ["AL", "GD", "T15", "T31", "TX", "BOP", "S31", "S14", "AE38"]):
            asset_class = AssetClass.BOND
            try:
                metrics = ArgentineBondPricer.calculate_risk_metrics(ticker, market_price=unit_price_usd*100)
                mod_dur = metrics["modified_duration"]
                convexity = metrics["convexity"]
                dv01 = metrics["dv01_per_100"]
                ytm = metrics["ytm_percent"] / 100.0
            except Exception:
                mod_dur = 1.8 if any(k in ticker_upper for k in ["T15", "T31", "S31", "S14"]) else 2.5
                convexity = 5.0 if any(k in ticker_upper for k in ["T15", "T31", "S31", "S14"]) else 8.0
                dv01 = 200.0
                ytm = 0.145 if any(k in ticker_upper for k in ["T15", "T31", "S31", "S14"]) else 0.16

            pos = Position(
                ticker=ticker,
                name=name or ticker,
                asset_class=asset_class,
                quantity=qty,
                unit_price=unit_price_usd,
                market_value=round(mkt_val_usd, 2),
                currency="USD",
                details={
                    "law": "Argentina" if ("AL" in ticker_upper or "T" in ticker_upper or "S" in ticker_upper) else "New York",
                    "ytm": ytm,
                    "modified_duration": mod_dur,
                    "convexity": convexity,
                    "dv01": dv01,
                    "coupon": 0.0075 if ("30" in ticker_upper) else 0.036,
                    "moneda": moneda,
                    "raw_total_ars": total_val if not is_usd_ccy else None,
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
                details={
                    "sector": "Cedear US / Equities" if "CEDEAR" in instr_upper else "BYMA Equity",
                    "moneda": moneda,
                    "raw_total_ars": total_val if not is_usd_ccy else None,
                }
            )

        positions.append(pos)

    if not positions:
        return create_default_portfolio(), settings

    port = Portfolio(name="Cocos Capital Portfolio", positions=positions)
    port.update_weights()
    return port, settings


def load_portfolio_from_excel(
    file_source: Union[str, io.BytesIO] = "input.xlsx",
    ccl_rate: float = None
) -> Tuple[Portfolio, Dict[str, Any]]:
    """Loads and validates a trading portfolio from an Excel spreadsheet or broker CSV.

    :param file_source: Filepath or BytesIO buffer from Streamlit file_uploader
    :param ccl_rate: Optional USD/ARS CCL or MEP exchange rate override for CSV parsing
    :return: (Portfolio object, settings dict)
    """
    # Check if CSV file or buffer
    is_csv = False
    if isinstance(file_source, str) and file_source.lower().endswith(".csv"):
        is_csv = True
    elif hasattr(file_source, "name") and str(file_source.name).lower().endswith(".csv"):
        is_csv = True
    elif isinstance(file_source, io.StringIO):
        is_csv = True
        file_source.seek(0)
    elif isinstance(file_source, io.BytesIO):
        # Peak at first few bytes to distinguish CSV from ZIP/Excel
        pos = file_source.tell()
        sample = file_source.read(8)
        file_source.seek(pos)
        # Excel zip files start with PK\x03\x04
        if sample and not sample.startswith(b"PK"):
            is_csv = True

    if is_csv:
        eff_ccl = float(ccl_rate) if (ccl_rate is not None and ccl_rate > 0) else 1582.60
        return load_portfolio_from_cocos_csv(file_source, ccl_rate=eff_ccl)

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
