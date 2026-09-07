"""Unit tests for pricing models: Argentine sovereign bonds and derivatives."""
import pytest
from src.pricing.bonds import ArgentineBondPricer
from src.pricing.derivatives import BlackScholesOption, DerivativesRiskEngine


def test_bond_cash_flows_generation():
    """Verify cash flows for AL30 and GD30 are generated correctly."""
    for ticker in ["GD30", "AL30", "GD35", "AL35", "GD38"]:
        cfs = ArgentineBondPricer.generate_cash_flows(ticker)
        assert len(cfs) > 0
        total_principal = sum(p for _, _, p in cfs)
        assert pytest.approx(total_principal, 0.01) == 100.0


def test_bond_risk_metrics():
    """Verify YTM, Modified Duration, and Convexity calculation."""
    metrics = ArgentineBondPricer.calculate_risk_metrics("GD30")
    assert "ytm_percent" in metrics
    assert "modified_duration" in metrics
    assert "convexity" in metrics
    assert "dv01_per_100" in metrics
    # Restructured 2030 bonds have modified duration around 2-3 years
    assert 1.5 < metrics["modified_duration"] < 4.0
    assert metrics["convexity"] > 0
    assert metrics["dv01_per_100"] > 0


def test_black_scholes_call_and_put():
    """Verify analytical option pricing and Greek signs."""
    # Call option ATM
    call_greeks = BlackScholesOption.calculate_greeks(
        spot=100.0, strike=100.0, time_to_maturity=0.25, rate=0.05, volatility=0.30, option_type="call"
    )
    assert call_greeks["price"] > 0
    assert 0.0 < call_greeks["delta"] < 1.0
    assert call_greeks["gamma"] > 0
    assert call_greeks["vega"] > 0
    assert call_greeks["theta"] < 0  # Time decay is negative

    # Put option ATM
    put_greeks = BlackScholesOption.calculate_greeks(
        spot=100.0, strike=100.0, time_to_maturity=0.25, rate=0.05, volatility=0.30, option_type="put"
    )
    assert put_greeks["price"] > 0
    assert -1.0 < put_greeks["delta"] < 0.0
    assert put_greeks["gamma"] > 0
    assert put_greeks["vega"] > 0


def test_derivatives_risk_engine():
    """Verify sensitivities aggregated for all 5 derivatives."""
    sens = DerivativesRiskEngine.get_all_derivatives_sensitivities()
    assert len(sens) == 5
    assert "ROFEX_DLR_3M" in sens
    assert "GGAL_C_ATM" in sens
    assert "GGAL_P_OTM" in sens
    assert "USD_ARS_NDF_6M" in sens
    assert "BADLAR_IRS_1Y" in sens
