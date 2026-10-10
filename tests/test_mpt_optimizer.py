"""Unit tests for Modern Portfolio Theory (MPT) Optimizer, Frontier Generation,
and Broker CSV multi-currency parsing using strictly synthetic test fixtures.
"""
import io
import pytest
import numpy as np
from src.portfolio.excel_loader import load_portfolio_from_excel, parse_argentine_number
from src.portfolio.models import create_default_portfolio, AssetClass
from src.risk.mpt_optimizer import (
    MPTOptimizer,
    classify_and_parameterize_position,
    MPT_CATEGORY_CORE_CEDEAR,
    MPT_CATEGORY_HIGH_BETA,
    MPT_CATEGORY_FIXED_INCOME,
    MPT_CATEGORY_CASH_FCI,
)


SYNTHETIC_PORTFOLIO_REPORT_CSV = """instrumento;cantidad;precio;precioAsOf;moneda;total;variacionDiaria
ARS;1,45;1,00;2026-09-10;ARS;1,45;0,00%
EXT;0,02;1,00;2026-09-10;USD;0,02;0,00%
USD;0,50;1,00;2026-09-10;USD;0,50;0,00%
CEDEAR SPDR S&P 500 (SPY);25;38.500,00;2026-09-10;ARS;962.500,00;0,85%
CEDEAR INVESCO QQQ (QQQ);20;32.100,00;2026-09-10;ARS;642.000,00;1,10%
CEDEAR APPLE INC (AAPL);30;24.000,00;2026-09-10;ARS;720.000,00;0,40%
CEDEAR ALPHABET INC (GOOGL);40;18.500,00;2026-09-10;ARS;740.000,00;0,60%
CEDEAR VISA INC (V);15;28.000,00;2026-09-10;ARS;420.000,00;0,30%
CEDEAR ADOBE INC (ADBE);10;35.000,00;2026-09-10;ARS;350.000,00;-0,50%
CEDEAR MERCADOLIBRE INC (MELI);12;42.000,00;2026-09-10;ARS;504.000,00;1,45%
CEDEAR PETROBRAS (PBR);50;14.200,00;2026-09-10;ARS;710.000,00;0,90%
CEDEAR GLOBAL X COPPER MINERS (COPX);35;16.000,00;2026-09-10;ARS;560.000,00;1,20%
BONCAP 15 ENE 2027 (T15E7);10.000;148,50;2026-09-10;ARS;1.485.000,00;0,25%
BONCAP 31 MAY 2027 (T31Y7);8.000;152,00;2026-09-10;ARS;1.216.000,00;0,30%
BONO BONAR USD 2030 (AL30);1.500;915,00;2026-09-10;ARS;1.372.500,00;0,75%
FCI COCOS AHORRO PESOS (COCOSPPA);500.000;2,15;2026-09-10;ARS;1.075.000,00;0,12%
FCI COCOS RENTA FIJA USD (COCOUSDPA);2.500;1,04;2026-09-10;USD;2.600,00;0,02%
"""


def test_parse_european_decimals_and_artifacts():
    """Verify European decimal formatting and non-numeric artifact stripping."""
    assert pytest.approx(parse_argentine_number("1.289,50")) == 1289.50
    assert pytest.approx(parse_argentine_number("$ 1.192.531,88")) == 1192531.88
    assert pytest.approx(parse_argentine_number("USD 2.600,00")) == 2600.00
    assert pytest.approx(parse_argentine_number("-15,4 %")) == -15.4
    assert parse_argentine_number("-") == 0.0
    assert parse_argentine_number("") == 0.0


def test_broker_csv_parsing_and_fx_revaluation():
    """Verify synthetic broker CSV filters micro-cash, handles multi-currency FX, and revalues on CCL change."""
    port, settings = load_portfolio_from_excel(io.StringIO(SYNTHETIC_PORTFOLIO_REPORT_CSV), ccl_rate=1500.0)
    # Micro-cash rows (ARS 1.45, EXT 0.02, USD 0.50) must be filtered out; 14 valid positions remain
    assert len(port.positions) == 14
    assert pytest.approx(sum(p.weight for p in port.positions), rel=1e-4) == 1.0

    # Check asset classes
    eqs = port.get_positions_by_class(AssetClass.EQUITY)
    bonds = port.get_positions_by_class(AssetClass.BOND)
    cash = port.get_positions_by_class(AssetClass.CASH)
    assert len(eqs) == 9   # SPY, QQQ, AAPL, GOOGL, V, ADBE, MELI, PBR, COPX
    assert len(bonds) == 3  # T15E7, T31Y7, AL30
    assert len(cash) == 2   # COCOSPPA, COCOUSDPA

    # Revalue with a lower CCL rate (1200 ARS/USD): ARS positions increase in USD value while COCOUSDPA stays $2,600
    val_before = port.total_value
    port.revalue_with_ccl(1200.0)
    assert port.total_value > val_before
    cocousd = next(p for p in port.positions if "COCOUSDPA" in p.ticker)
    assert pytest.approx(cocousd.market_value) == 2600.0
    assert pytest.approx(sum(p.weight for p in port.positions), rel=1e-4) == 1.0


def test_mpt_optimizer_categories_and_benchmarks():
    """Verify MPT asset classification, portfolio metrics, Max Sharpe, Min Vol, and Efficient Frontier."""
    port, _ = load_portfolio_from_excel(io.StringIO(SYNTHETIC_PORTFOLIO_REPORT_CSV), ccl_rate=1500.0)
    mpt = MPTOptimizer(port, risk_free_rate=0.042, use_yfinance=False)

    # Check all 4 categories are represented
    cats = set(mpt.categories)
    assert MPT_CATEGORY_CORE_CEDEAR in cats
    assert MPT_CATEGORY_HIGH_BETA in cats
    assert MPT_CATEGORY_FIXED_INCOME in cats
    assert MPT_CATEGORY_CASH_FCI in cats

    cur = mpt.portfolio_metrics()
    max_sharpe = mpt.optimize_max_sharpe()
    min_vol = mpt.optimize_min_volatility()

    # Mathematical invariants of Markowitz optimization:
    # 1. Weights sum to 1 and are non-negative
    assert pytest.approx(np.sum(max_sharpe["weights"]), rel=1e-4) == 1.0
    assert np.all(max_sharpe["weights"] >= -1e-6)
    assert pytest.approx(np.sum(min_vol["weights"]), rel=1e-4) == 1.0
    assert np.all(min_vol["weights"] >= -1e-6)

    # 2. Max Sharpe portfolio must achieve Sharpe >= Current portfolio and >= Min Vol portfolio
    assert max_sharpe["sharpe"] >= cur["sharpe"] - 1e-4
    assert max_sharpe["sharpe"] >= min_vol["sharpe"] - 1e-4

    # 3. Min Volatility portfolio must achieve Volatility <= Current portfolio and <= Max Sharpe portfolio
    assert min_vol["volatility"] <= cur["volatility"] + 1e-4
    assert min_vol["volatility"] <= max_sharpe["volatility"] + 1e-4

    # 4. Efficient frontier and CAL generation
    frontier = mpt.generate_efficient_frontier(num_points=25)
    assert len(frontier["frontier_vols_pct"]) >= 10
    assert len(frontier["frontier_returns_pct"]) == len(frontier["frontier_vols_pct"])
    assert len(frontier["cal_vols_pct"]) == 3
    assert pytest.approx(frontier["cal_returns_pct"][0]) == 4.20

    # 5. Allocation summary dataframe
    df_alloc = mpt.get_asset_allocation_dataframe(max_sharpe, min_vol)
    assert len(df_alloc) == 14
    assert pytest.approx(df_alloc["Current Weight (%)"].sum(), abs=0.1) == 100.0
    assert pytest.approx(df_alloc["Max Sharpe Weight (%)"].sum(), abs=0.1) == 100.0
    assert pytest.approx(df_alloc["Min Vol Weight (%)"].sum(), abs=0.1) == 100.0

    # 6. Subportfolio filter ("CEDEARs Only")
    cedear_sub = mpt.filter_subportfolio("CEDEARs Only")
    assert len(cedear_sub.positions) == 9
    assert pytest.approx(sum(p.weight for p in cedear_sub.positions), rel=1e-4) == 1.0


def test_mpt_on_default_institutional_portfolio():
    """Verify MPTOptimizer also runs cleanly on the default 15-position institutional portfolio."""
    port = create_default_portfolio()
    mpt = MPTOptimizer(port, risk_free_rate=0.042)
    frontier = mpt.generate_efficient_frontier(num_points=20)
    assert frontier["max_sharpe"]["sharpe"] >= frontier["current"]["sharpe"] - 1e-4
    assert frontier["min_vol"]["volatility_pct"] <= frontier["current"]["volatility_pct"] + 1e-2
