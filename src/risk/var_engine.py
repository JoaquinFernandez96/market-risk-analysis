"""Comprehensive Market Risk and Value at Risk (VaR) Engine.
Implements:
- Base VaR vs. Stressed VaR (sVaR) scenarios
- Parametric (Variance-Covariance) VaR & CVaR
- Historical Simulation VaR & CVaR
- Monte Carlo VaR (10,000 paths) & CVaR
- Marginal VaR and Component VaR (Euler risk decomposition)
"""
import numpy as np
import pandas as pd
from scipy.stats import norm
from typing import Dict, Any, List
from src.portfolio.models import Portfolio
from src.data.loader import MarketDataLoader, ALL_TICKERS


class VaREngine:
    """Quantitative engine for Base and Stressed VaR and Expected Shortfall."""

    def __init__(
        self,
        portfolio: Portfolio,
        use_live_cache: bool = False,
        force_refresh: bool = False,
    ):
        self.portfolio = portfolio
        self.portfolio.update_weights()
        self.total_value = self.portfolio.total_value
        self.use_live_cache = use_live_cache

        # Dynamic list of active tickers from portfolio
        self.tickers = [p.ticker for p in self.portfolio.positions]
        self.weights = np.array([p.weight for p in self.portfolio.positions])

        # Load base and stress return datasets (backed by persistent local disk cache when enabled)
        self.base_returns_df = MarketDataLoader.generate_simulated_returns(
            scenario="base",
            tickers=self.tickers,
            num_days=504,
            seed=42,
            use_live_cache=use_live_cache,
            force_refresh=force_refresh,
        )
        self.stress_returns_df = MarketDataLoader.generate_simulated_returns(
            scenario="stress",
            tickers=self.tickers,
            num_days=504,
            seed=101,
            use_live_cache=use_live_cache,
            force_refresh=False,
        )

    def calculate_parametric_var(
        self,
        returns_df: pd.DataFrame,
        confidence_level: float = 0.95,
        horizon_days: int = 1
    ) -> Dict[str, float]:
        """Calculates Parametric (Variance-Covariance) VaR and CVaR."""
        cov_matrix = returns_df[self.tickers].cov().values
        port_var = float(self.weights.T @ cov_matrix @ self.weights)
        port_vol = np.sqrt(max(port_var, 1e-8))

        # Holding period scale
        horizon_vol = port_vol * np.sqrt(horizon_days)

        z_score = norm.ppf(confidence_level)
        var_pct = z_score * horizon_vol
        var_dollar = var_pct * self.total_value

        # Expected Shortfall (CVaR) under normal distribution
        cvar_pct = horizon_vol * (norm.pdf(z_score) / (1.0 - confidence_level))
        cvar_dollar = cvar_pct * self.total_value

        # Marginal and Component VaR
        # Marginal VaR_i = (Cov @ w)_i / port_vol * z_score
        marginal_var = (cov_matrix @ self.weights) / port_vol * z_score * np.sqrt(horizon_days)
        # Component VaR_i = w_i * Marginal_VaR_i * Total_Value
        component_var = self.weights * marginal_var * self.total_value

        # Standalone VaR sum and Diversification Benefit
        standalone_vars = [
            z_score * np.sqrt(horizon_days) * np.sqrt(max(cov_matrix[i, i], 1e-12)) * (self.weights[i] * self.total_value)
            for i in range(len(self.tickers))
        ]
        sum_standalone = float(sum(standalone_vars))
        div_benefit_dollar = float(max(0.0, sum_standalone - var_dollar))
        div_benefit_pct = float((div_benefit_dollar / sum_standalone * 100.0) if sum_standalone > 0 else 0.0)

        return {
            "var_dollar": round(float(var_dollar), 2),
            "var_pct": round(float(var_pct * 100), 2),
            "cvar_dollar": round(float(cvar_dollar), 2),
            "cvar_pct": round(float(cvar_pct * 100), 2),
            "daily_vol_pct": round(float(port_vol * 100), 2),
            "annualized_vol_pct": round(float(port_vol * np.sqrt(252) * 100), 2),
            "component_var": component_var,
            "diversification_benefit_dollar": round(div_benefit_dollar, 2),
            "diversification_benefit_pct": round(div_benefit_pct, 2),
            "sum_standalone_var": round(sum_standalone, 2),
        }

    def calculate_historical_var(
        self,
        returns_df: pd.DataFrame,
        confidence_level: float = 0.95,
        horizon_days: int = 1
    ) -> Dict[str, float]:
        """Calculates Non-Parametric Historical Simulation VaR and CVaR."""
        # Daily portfolio returns series
        port_daily_returns = returns_df[self.tickers].values @ self.weights

        # Scale returns to horizon if > 1 day
        if horizon_days > 1:
            # Overlapping rolling sum for horizon
            port_returns = pd.Series(port_daily_returns).rolling(window=horizon_days).sum().dropna().values
        else:
            port_returns = port_daily_returns

        # Losses (loss is negative return)
        losses = - port_returns * self.total_value

        # Quantile loss
        percentile_idx = confidence_level * 100.0
        var_dollar = float(np.percentile(losses, percentile_idx))
        var_pct = (var_dollar / self.total_value) * 100.0

        # Conditional VaR / Expected Shortfall: average of losses exceeding VaR
        tail_losses = losses[losses >= var_dollar]
        cvar_dollar = float(np.mean(tail_losses)) if len(tail_losses) > 0 else var_dollar
        cvar_pct = (cvar_dollar / self.total_value) * 100.0

        return {
            "var_dollar": round(var_dollar, 2),
            "var_pct": round(var_pct, 2),
            "cvar_dollar": round(cvar_dollar, 2),
            "cvar_pct": round(cvar_pct, 2),
            "loss_distribution": losses,
        }

    def calculate_monte_carlo_var(
        self,
        returns_df: pd.DataFrame,
        confidence_level: float = 0.95,
        horizon_days: int = 1,
        num_simulations: int = 10_000,
        seed: int = 777
    ) -> Dict[str, float]:
        """Calculates Monte Carlo VaR and CVaR with 10,000 simulated correlated draws."""
        np.random.seed(seed)
        cov_matrix = returns_df[self.tickers].cov().values
        means = returns_df[self.tickers].mean().values

        # Cholesky decomposition of covariance
        # Add small regularization to diagonal if needed
        diag_reg = np.eye(len(self.tickers)) * 1e-7
        L = np.linalg.cholesky(cov_matrix + diag_reg)

        # Standard normal random matrix (num_simulations x num_assets)
        Z = np.random.normal(0, 1, size=(num_simulations, len(self.tickers)))

        # Correlated simulated 1-day returns
        sim_returns_1d = means + Z @ L.T

        # Scale to horizon
        sim_returns_horizon = sim_returns_1d * np.sqrt(horizon_days)

        # Portfolio returns and losses
        sim_port_returns = sim_returns_horizon @ self.weights
        sim_losses = - sim_port_returns * self.total_value

        var_dollar = float(np.percentile(sim_losses, confidence_level * 100.0))
        var_pct = (var_dollar / self.total_value) * 100.0

        tail_losses = sim_losses[sim_losses >= var_dollar]
        cvar_dollar = float(np.mean(tail_losses)) if len(tail_losses) > 0 else var_dollar
        cvar_pct = (cvar_dollar / self.total_value) * 100.0

        return {
            "var_dollar": round(var_dollar, 2),
            "var_pct": round(var_pct, 2),
            "cvar_dollar": round(cvar_dollar, 2),
            "cvar_pct": round(cvar_pct, 2),
            "sim_losses": sim_losses,
        }

    def get_component_var_breakdown(
        self,
        confidence_level: float = 0.95,
        horizon_days: int = 1,
        scenario: str = "base"
    ) -> pd.DataFrame:
        """Returns detailed Component VaR and percentage risk contribution per asset."""
        returns_df = self.stress_returns_df if scenario.lower() == "stress" else self.base_returns_df
        param_res = self.calculate_parametric_var(returns_df, confidence_level, horizon_days)

        total_var = param_res["var_dollar"]
        comp_vars = param_res["component_var"]

        pos_dict = {p.ticker: p for p in self.portfolio.positions}

        records = []
        for i, ticker in enumerate(self.tickers):
            pos = pos_dict.get(ticker)
            cvar_i = comp_vars[i]
            pct_contrib = (cvar_i / total_var * 100.0) if total_var > 0 else 0.0

            records.append({
                "Ticker": ticker,
                "Name": pos.name if pos else ticker,
                "Asset Class": pos.asset_class.value if pos else "Other",
                "Weight (%)": round(self.weights[i] * 100.0, 2),
                "Market Value ($)": round(self.weights[i] * self.total_value, 2),
                "Component VaR ($)": round(float(cvar_i), 2),
                "% Risk Contribution": round(float(pct_contrib), 2),
            })

        df = pd.DataFrame(records)
        return df.sort_values(by="Component VaR ($)", ascending=False).reset_index(drop=True)

    def run_scenario_comparison(
        self,
        confidence_level: float = 0.95,
        horizon_days: int = 1
    ) -> Dict[str, Any]:
        """Runs side-by-side comparative analysis between Base VaR and Stressed VaR."""
        # 1. Base Scenario Metrics
        base_param = self.calculate_parametric_var(self.base_returns_df, confidence_level, horizon_days)
        base_hist = self.calculate_historical_var(self.base_returns_df, confidence_level, horizon_days)
        base_mc = self.calculate_monte_carlo_var(self.base_returns_df, confidence_level, horizon_days)

        # 2. Stressed Scenario Metrics
        stress_param = self.calculate_parametric_var(self.stress_returns_df, confidence_level, horizon_days)
        stress_hist = self.calculate_historical_var(self.stress_returns_df, confidence_level, horizon_days)
        stress_mc = self.calculate_monte_carlo_var(self.stress_returns_df, confidence_level, horizon_days)

        # Stress Multiplier (sVaR / Base VaR)
        stress_multiplier = (
            stress_hist["var_dollar"] / base_hist["var_dollar"]
            if base_hist["var_dollar"] > 0 else 1.0
        )
        cvar_multiplier = (
            stress_hist["cvar_dollar"] / base_hist["cvar_dollar"]
            if base_hist["cvar_dollar"] > 0 else 1.0
        )

        # Capital Buffer required under Basel Stressed VaR framework: Max(Base VaR, sVaR)
        capital_requirement = stress_hist["var_dollar"] * 3.0  # Basel standard 3x multiplier
        base_capital = base_hist["var_dollar"] * 3.0
        additional_stress_capital = capital_requirement - base_capital

        return {
            "confidence_level": confidence_level,
            "horizon_days": horizon_days,
            "portfolio_value": self.total_value,
            "base": {
                "parametric": base_param,
                "historical": base_hist,
                "monte_carlo": base_mc,
                "portfolio_annual_vol": base_param["annualized_vol_pct"],
            },
            "stress": {
                "parametric": stress_param,
                "historical": stress_hist,
                "monte_carlo": stress_mc,
                "portfolio_annual_vol": stress_param["annualized_vol_pct"],
            },
            "comparison": {
                "var_dollar_delta": round(stress_hist["var_dollar"] - base_hist["var_dollar"], 2),
                "var_pct_delta": round(stress_hist["var_pct"] - base_hist["var_pct"], 2),
                "stress_multiplier": round(stress_multiplier, 2),
                "cvar_multiplier": round(cvar_multiplier, 2),
                "base_capital_3x": round(base_capital, 2),
                "stress_capital_3x": round(capital_requirement, 2),
                "additional_capital_needed": round(additional_stress_capital, 2),
                "diversification_benefit_dollar": base_param["diversification_benefit_dollar"],
                "diversification_benefit_pct": base_param["diversification_benefit_pct"],
                "stress_diversification_benefit_dollar": stress_param["diversification_benefit_dollar"],
                "stress_diversification_benefit_pct": stress_param["diversification_benefit_pct"],
            }
        }
