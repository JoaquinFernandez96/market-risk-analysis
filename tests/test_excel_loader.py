"""Unit tests for Excel loading and monthly portfolio updating."""
import io
import pytest
import pandas as pd
from src.portfolio.excel_loader import load_portfolio_from_excel, get_excel_template_bytes
from src.portfolio.models import AssetClass
from src.risk.var_engine import VaREngine


def test_load_default_input_xlsx():
    """Verify input.xlsx loads properly and produces 15 assets."""
    portfolio, settings = load_portfolio_from_excel("input.xlsx")
    assert len(portfolio.positions) == 15
    assert len(portfolio.get_positions_by_class(AssetClass.EQUITY)) == 5
    assert len(portfolio.get_positions_by_class(AssetClass.BOND)) == 5
    assert len(portfolio.get_positions_by_class(AssetClass.DERIVATIVE)) == 5
    assert portfolio.total_value > 0
    assert "USD_ARS_CCL_Rate" in settings
    assert settings["USD_ARS_CCL_Rate"] == 1280.0


def test_dynamic_portfolio_with_new_stock():
    """Test updating portfolio dynamically by loading an Excel buffer with an added stock."""
    # Read existing input.xlsx and modify in memory
    excel_buf = io.BytesIO()
    with pd.ExcelWriter(excel_buf, engine='openpyxl') as writer:
        # Equities with an additional stock: ALUA.BA
        df_eq = pd.DataFrame([
            {"Ticker": "YPFD.BA", "Name": "YPF", "Quantity": 20000, "Unit_Price_USD": 32.0, "Market_Value_USD": 640000.0, "Sector": "Energy"},
            {"Ticker": "GGAL.BA", "Name": "Galicia", "Quantity": 150000, "Unit_Price_USD": 5.0, "Market_Value_USD": 750000.0, "Sector": "Financials"},
            {"Ticker": "ALUA.BA", "Name": "Aluar", "Quantity": 500000, "Unit_Price_USD": 1.2, "Market_Value_USD": 600000.0, "Sector": "Materials"}
        ])
        df_eq.to_excel(writer, sheet_name="Equities", index=False)

        # 2 Bonds
        df_bonds = pd.DataFrame([
            {"Ticker": "GD30", "Name": "Global 30", "Nominal_Quantity": 1000000, "Clean_Price_USD": 0.62, "Market_Value_USD": 620000.0, "Modified_Duration": 2.63, "Convexity": 8.9},
            {"Ticker": "GD35", "Name": "Global 35", "Nominal_Quantity": 1000000, "Clean_Price_USD": 0.49, "Market_Value_USD": 490000.0, "Modified_Duration": 4.98, "Convexity": 34.1}
        ])
        df_bonds.to_excel(writer, sheet_name="Bonds", index=False)

        # 1 Derivative
        df_deriv = pd.DataFrame([
            {"Identifier": "ROFEX_DLR_3M", "Name": "Rofex Futures", "Quantity_Contracts": 500, "Unit_Price_USD": 300.0, "Market_Value_USD": 150000.0, "Notional_USD": 500000.0}
        ])
        df_deriv.to_excel(writer, sheet_name="Derivatives", index=False)

        # Settings
        df_set = pd.DataFrame([
            {"Parameter": "Portfolio_Name", "Value": "Custom Monthly Book"},
            {"Parameter": "USD_ARS_CCL_Rate", "Value": 1350.0}
        ])
        df_set.to_excel(writer, sheet_name="Settings", index=False)

    excel_buf.seek(0)
    custom_portfolio, custom_settings = load_portfolio_from_excel(excel_buf)

    assert len(custom_portfolio.positions) == 6
    assert custom_portfolio.name == "Custom Monthly Book"
    assert custom_settings["USD_ARS_CCL_Rate"] == 1350.0

    # Ensure VaREngine computes correctly with dynamic tickers
    engine = VaREngine(custom_portfolio)
    comp = engine.run_scenario_comparison(confidence_level=0.95, horizon_days=1)
    assert comp["base"]["historical"]["var_dollar"] > 0
    assert comp["stress"]["historical"]["var_dollar"] > comp["base"]["historical"]["var_dollar"]


def test_excel_template_bytes():
    """Verify template bytes are returned for user download."""
    data = get_excel_template_bytes()
    assert isinstance(data, bytes)
    assert len(data) > 1000
