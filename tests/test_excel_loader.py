"""Unit tests for Excel loading and monthly portfolio updating."""
import io
import pytest
import pandas as pd
from src.portfolio.excel_loader import load_portfolio_from_excel, get_excel_template_bytes
from src.portfolio.models import AssetClass
from src.risk.var_engine import VaREngine


def test_load_default_input_xlsx():
    """Verify input.xlsx loads properly and produces positions across asset classes."""
    portfolio, settings = load_portfolio_from_excel("input.xlsx")
    assert len(portfolio.get_positions_by_class(AssetClass.EQUITY)) == 5
    assert len(portfolio.get_positions_by_class(AssetClass.BOND)) == 5
    assert len(portfolio.get_positions_by_class(AssetClass.DERIVATIVE)) == 5
    assert len(portfolio.get_positions_by_class(AssetClass.CASH)) == 2
    assert len(portfolio.positions) == 17
    assert portfolio.total_value > 0
    assert "USD_ARS_CCL_Rate" in settings
    assert settings["USD_ARS_CCL_Rate"] == 1582.60


def test_zero_derivatives_and_ars_pricing():
    """Verify retail portfolio with only equities in ARS, bonds, and cash (0 derivatives)."""
    excel_buf = io.BytesIO()
    with pd.ExcelWriter(excel_buf, engine='openpyxl') as writer:
        df_eq = pd.DataFrame([
            {"Ticker": "YPFD.BA", "Name": "YPF", "Quantity": 100, "Price_ARS": 8370.0},
            {"Ticker": "GGAL.BA", "Name": "Galicia", "Quantity": 200, "Price_ARS": 6960.0},
        ])
        df_eq.to_excel(writer, sheet_name="Equities", index=False)

        df_bonds = pd.DataFrame([
            {"Ticker": "GD30", "Name": "Global 30", "Nominal_Quantity": 1000, "Clean_Price_USD": 0.58}
        ])
        df_bonds.to_excel(writer, sheet_name="Bonds", index=False)

        df_cash = pd.DataFrame([
            {"Ticker": "CAUCION_ARS", "Name": "Caucion", "Amount_ARS": 1582600.0, "Annual_Yield_Pct": 28.0}
        ])
        df_cash.to_excel(writer, sheet_name="Cash_Liquidity", index=False)

        df_set = pd.DataFrame([
            {"Parameter": "Portfolio_Name", "Value": "Retail Clean Portfolio"},
            {"Parameter": "USD_ARS_CCL_Rate", "Value": 1582.60}
        ])
        df_set.to_excel(writer, sheet_name="Settings", index=False)

    excel_buf.seek(0)
    retail_port, _ = load_portfolio_from_excel(excel_buf)

    assert len(retail_port.positions) == 4
    assert len(retail_port.get_positions_by_class(AssetClass.DERIVATIVE)) == 0
    assert len(retail_port.get_positions_by_class(AssetClass.CASH)) == 1
    # YPF: 100 * 8370 / 1582.60 ~= $528.88 USD
    # GGAL: 200 * 6960 / 1582.60 ~= $879.57 USD
    # GD30: 1000 * 0.58 = $580.00 USD
    # Caucion: 1582600 / 1582.60 = $1000.00 USD
    assert pytest.approx(retail_port.total_value, rel=1e-2) == (528.88 + 879.57 + 580.0 + 1000.0)

    # Risk engine should run with 0 derivatives without errors
    engine = VaREngine(retail_port)
    res = engine.run_scenario_comparison(0.95, 1)
    assert res["base"]["historical"]["var_dollar"] > 0


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


def test_load_argentine_broker_csv_synthetic():
    """Verify loading synthetic Argentine broker CSV statement with semicolon and latin decimals."""
    synthetic_csv = (
        "Cuenta;Especie;Tenencia;Precio;Valuacion;Tipo\n"
        "12345;CEDEAR SPDR S&P 500 (SPY);100;20220,00;2022000,00;CEDEAR\n"
        "12345;BONO BONAR USD 2030 (AL30D);50;85700,00;42850,00;BONO\n"
        "12345;FCI COCOS AHORRO CLASE A;1000;1,45;1450,00;FCI\n"
    )
    port, settings = load_portfolio_from_excel(io.StringIO(synthetic_csv))
    assert len(port.positions) == 3
    assert port.total_value > 0
    engine = VaREngine(port)
    comp = engine.run_scenario_comparison(0.95, 1)
    assert comp["base"]["historical"]["var_dollar"] > 0
    assert comp["stress"]["historical"]["var_dollar"] > 0


def test_load_cocos_capital_csv():
    """Verify loading real Argentine broker CSV statement if present locally."""
    csv_path = "COCOS/portfolio_report_20260910.csv"
    import os
    if os.path.exists(csv_path):
        port, settings = load_portfolio_from_excel(csv_path)
        assert len(port.positions) > 10
        assert port.total_value > 0
        eqs = port.get_positions_by_class(AssetClass.EQUITY)
        bonds = port.get_positions_by_class(AssetClass.BOND)
        cash = port.get_positions_by_class(AssetClass.CASH)
        assert len(eqs) >= 5  # SPY, QQQ, AAPL, MELI, PAMP, etc.
        assert len(bonds) >= 2  # AL30, T15E7, T31Y7
        assert len(cash) >= 1  # COCOSPPA, COCOUSDPA, Cash

        # Verify risk engine runs on the real Cocos portfolio
        engine = VaREngine(port)
        comp = engine.run_scenario_comparison(0.95, 1)
        assert comp["base"]["historical"]["var_dollar"] > 0
        assert comp["stress"]["historical"]["var_dollar"] > 0


def test_load_cocos_capital_excel():
    """Verify loading input_cocos.xlsx spreadsheet containing Cocos broker holdings."""
    xlsx_path = "input_cocos.xlsx"
    import os
    if os.path.exists(xlsx_path):
        port, settings = load_portfolio_from_excel(xlsx_path)
        assert len(port.positions) == 17
        assert port.total_value > 20000.0  # ~$24,800 USD
        assert len(port.get_positions_by_class(AssetClass.EQUITY)) == 11
        assert len(port.get_positions_by_class(AssetClass.BOND)) == 3
        assert len(port.get_positions_by_class(AssetClass.CASH)) == 3

        # Test risk metrics on Excel version
        engine = VaREngine(port)
        res = engine.run_scenario_comparison(0.95, 1)
        assert res["base"]["historical"]["var_dollar"] > 0


def test_excel_template_bytes():
    """Verify template bytes are returned for user download."""
    data = get_excel_template_bytes()
    assert isinstance(data, bytes)
    assert len(data) > 1000
