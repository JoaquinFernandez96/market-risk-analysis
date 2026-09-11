"""Unit tests for Portfolio, VaR Engine, and Stress Testing."""
import pytest
import numpy as np
from src.portfolio.models import create_default_portfolio, AssetClass
from src.risk.var_engine import VaREngine
from src.risk.stress_testing import StressTestEngine


@pytest.fixture
def portfolio():
    return create_default_portfolio()


@pytest.fixture
def var_engine(portfolio):
    return VaREngine(portfolio)


def test_portfolio_construction(portfolio):
    """Ensure portfolio has exactly 15 assets and sums to $10M USD."""
    assert len(portfolio.positions) == 15
    equities = portfolio.get_positions_by_class(AssetClass.EQUITY)
    bonds = portfolio.get_positions_by_class(AssetClass.BOND)
    derivatives = portfolio.get_positions_by_class(AssetClass.DERIVATIVE)

    assert len(equities) == 5
    assert len(bonds) == 5
    assert len(derivatives) == 5

    assert pytest.approx(portfolio.total_value, 0.01) == 10_000_000.0
    total_weights = sum(p.weight for p in portfolio.positions)
    assert pytest.approx(total_weights, 0.001) == 1.0


def test_base_vs_stressed_var(var_engine):
    """Verify Stressed VaR is strictly greater than Base VaR."""
    res = var_engine.run_scenario_comparison(confidence_level=0.95, horizon_days=1)

    base_hist_var = res["base"]["historical"]["var_dollar"]
    stress_hist_var = res["stress"]["historical"]["var_dollar"]

    # Stress scenario must amplify risk
    assert stress_hist_var > base_hist_var
    assert res["comparison"]["stress_multiplier"] > 1.0

    # CVaR must be greater than or equal to VaR in both regimes
    assert res["base"]["historical"]["cvar_dollar"] >= base_hist_var
    assert res["stress"]["historical"]["cvar_dollar"] >= stress_hist_var


def test_monte_carlo_var(var_engine):
    """Verify Monte Carlo simulation runs and produces positive VaR."""
    mc_res = var_engine.calculate_monte_carlo_var(
        var_engine.base_returns_df, confidence_level=0.95, horizon_days=1, num_simulations=2000
    )
    assert mc_res["var_dollar"] > 0
    assert mc_res["cvar_dollar"] >= mc_res["var_dollar"]


def test_component_var_euler_property(var_engine):
    """Verify that sum of Component VaR across all assets equals total Parametric VaR."""
    df_comp = var_engine.get_component_var_breakdown(confidence_level=0.95, horizon_days=1, scenario="base")
    total_component_var = df_comp["Component VaR ($)"].sum()

    param_res = var_engine.calculate_parametric_var(var_engine.base_returns_df, confidence_level=0.95, horizon_days=1)
    total_param_var = param_res["var_dollar"]

    # Euler's theorem: sum(Component VaR) == Portfolio VaR
    assert pytest.approx(total_component_var, rel=1e-2) == total_param_var


def test_stress_test_engine(portfolio):
    """Verify stress test scenarios run and yield expected directional moves."""
    engine = StressTestEngine(portfolio)
    paso_res = engine.run_historical_scenario("2019_PASO_SHOCK")

    assert paso_res["total_pnl"] < 0  # Black Monday crash must lead to loss
    assert paso_res["portfolio_return_pct"] < 0
    assert len(paso_res["by_position"]) == 15


def test_diversification_benefit(var_engine):
    """Verify diversification benefit reduces risk below sum of standalone VaRs."""
    res = var_engine.run_scenario_comparison(confidence_level=0.95, horizon_days=1)
    div_dollar = res["comparison"]["diversification_benefit_dollar"]
    div_pct = res["comparison"]["diversification_benefit_pct"]

    assert div_dollar > 0.0
    assert div_pct > 0.0
    assert div_pct < 100.0


def test_portfolio_scaling(portfolio):
    """Verify portfolio scaling to retail size ($50,000) preserves weights and proportions."""
    retail_port = portfolio.scale_to_nav(50_000.0)

    assert pytest.approx(retail_port.total_value, rel=1e-3) == 50_000.0
    assert len(retail_port.positions) == len(portfolio.positions)

    # Weights must match exactly
    for orig_p, scaled_p in zip(portfolio.positions, retail_port.positions):
        assert pytest.approx(orig_p.weight, rel=1e-3) == scaled_p.weight
