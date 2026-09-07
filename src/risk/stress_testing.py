"""Portfolio Stress Testing and Scenario Analysis Engine.
Simulates macroeconomic shock events (2019 PASO, 2020 COVID/Restructuring, 2023 Electoral Run),
as well as dynamic multi-factor sensitivity stress testing.
"""
from typing import Dict, List, Any
import numpy as np
import pandas as pd
from src.portfolio.models import Portfolio, AssetClass


class StressTestEngine:
    """Stress testing engine applying multi-factor shocks to equity, bond, and derivative books."""

    HISTORICAL_SCENARIOS = {
        "2019_PASO_SHOCK": {
            "name": "2019 PASO Primary Election Shock (Aug 2019)",
            "description": "Black Monday in Argentina: Merval plunged 48% in USD, sovereign spreads exploded +1,500 bps, USD/ARS surged +30%.",
            "equity_shock": -0.48,
            "bond_yield_shift_bps": 1500,
            "fx_shock": 0.30,
            "vol_shock_pts": 45.0,
            "badlar_shift_bps": 1800,
        },
        "2020_COVID_RESTRUCTURING": {
            "name": "2020 Global COVID & Debt Restructuring Crisis",
            "description": "Global liquidity freeze coupled with Argentine debt default negotiations; sovereign bonds dropped to 30 cents, high FX volatility.",
            "equity_shock": -0.32,
            "bond_yield_shift_bps": 2200,
            "fx_shock": 0.22,
            "vol_shock_pts": 35.0,
            "badlar_shift_bps": -400,
        },
        "2023_ELECTORAL_DEVALUATION": {
            "name": "2023 Post-Primary FX Devaluation Shock",
            "description": "Official 22% single-day currency jump and parallel FX rally; equities acted as nominal hedges while sovereign spreads fluctuated.",
            "equity_shock": 0.15,
            "bond_yield_shift_bps": 800,
            "fx_shock": 0.54,
            "vol_shock_pts": 28.0,
            "badlar_shift_bps": 2100,
        },
        "GLOBAL_RECESSION_EM_SELLOFF": {
            "name": "Global Emerging Market Stagflation & Rate Spike",
            "description": "US 10Y yield spike above 5%, global risk-off, EM capital flight and commodity price contraction.",
            "equity_shock": -0.25,
            "bond_yield_shift_bps": 750,
            "fx_shock": 0.15,
            "vol_shock_pts": 20.0,
            "badlar_shift_bps": 600,
        }
    }

    def __init__(self, portfolio: Portfolio):
        self.portfolio = portfolio

    def run_factor_stress_test(
        self,
        equity_shock: float = -0.20,          # e.g. -20%
        bond_yield_shift_bps: float = 500.0,  # e.g. +500 bps
        fx_shock: float = 0.25,               # e.g. +25% USD/ARS
        vol_shock_pts: float = 15.0,          # e.g. +15 vol points
        badlar_shift_bps: float = 500.0       # e.g. +500 bps
    ) -> Dict[str, Any]:
        """Evaluates portfolio PnL under specific simultaneous factor shocks."""
        dy = bond_yield_shift_bps / 10_000.0  # Convert bps to decimal yield change

        results_by_position = []
        total_pnl = 0.0

        for pos in self.portfolio.positions:
            pnl = 0.0
            impact_pct = 0.0

            if pos.asset_class == AssetClass.EQUITY:
                # Individual stock beta sensitivity (banks higher beta)
                beta = 1.15 if "GGAL" in pos.ticker or "BMA" in pos.ticker else (1.05 if "YPF" in pos.ticker else 0.90)
                effective_shock = equity_shock * beta
                pnl = pos.market_value * effective_shock
                impact_pct = effective_shock * 100.0

            elif pos.asset_class == AssetClass.BOND:
                # Bond duration and convexity second-order Taylor expansion:
                # dP/P ~= -D_mod * dy + 0.5 * C * (dy)^2
                mod_dur = pos.details.get("modified_duration", 3.5)
                convexity = pos.details.get("convexity", 15.0)
                price_change_pct = - mod_dur * dy + 0.5 * convexity * (dy ** 2)
                pnl = pos.market_value * price_change_pct
                impact_pct = price_change_pct * 100.0

            elif pos.asset_class == AssetClass.DERIVATIVE:
                if "ROFEX" in pos.ticker:
                    # Futures: 1.0 delta on notional against FX devaluation
                    notional = pos.notional or pos.market_value
                    pnl = notional * fx_shock
                    impact_pct = (pnl / pos.market_value) * 100.0

                elif "USD_ARS_NDF" in pos.ticker:
                    # OTC NDF: ~0.95 delta on notional against FX devaluation
                    notional = pos.notional or pos.market_value
                    pnl = notional * fx_shock * 0.95
                    impact_pct = (pnl / pos.market_value) * 100.0

                elif "GGAL_C_ATM" in pos.ticker:
                    # Call option: Delta * dS + 0.5 * Gamma * (dS)^2 + Vega * dVol
                    # dS in dollar is spot * equity_shock
                    spot = 5.0
                    dS = spot * equity_shock
                    delta = pos.details.get("delta", 0.54)
                    gamma = pos.details.get("gamma", 0.082)
                    vega_pts = pos.details.get("vega", 980.0) / 160_000.0  # per share
                    contracts = 160_000.0
                    opt_dp = (delta * dS + 0.5 * gamma * (dS ** 2) + vega_pts * vol_shock_pts) * contracts
                    # Option cannot lose more than its market value
                    pnl = max(-pos.market_value, opt_dp)
                    impact_pct = (pnl / pos.market_value) * 100.0

                elif "GGAL_P_OTM" in pos.ticker:
                    # Put option: Delta (negative) * dS + 0.5 * Gamma * (dS)^2 + Vega * dVol
                    spot = 5.0
                    dS = spot * equity_shock
                    delta = pos.details.get("delta", -0.28)
                    gamma = pos.details.get("gamma", 0.065)
                    vega_pts = pos.details.get("vega", 720.0) / 160_000.0
                    contracts = 160_000.0
                    opt_dp = (delta * dS + 0.5 * gamma * (dS ** 2) + vega_pts * vol_shock_pts) * contracts
                    pnl = max(-pos.market_value, opt_dp)
                    impact_pct = (pnl / pos.market_value) * 100.0

                elif "BADLAR_IRS" in pos.ticker:
                    # IRS: +DV01 per bp of BADLAR increase
                    dv01 = pos.details.get("dv01", 185.0)
                    pnl = dv01 * badlar_shift_bps
                    impact_pct = (pnl / pos.market_value) * 100.0

            total_pnl += pnl
            results_by_position.append({
                "Ticker": pos.ticker,
                "Name": pos.name,
                "Asset Class": pos.asset_class.value,
                "Market Value ($)": round(pos.market_value, 2),
                "PnL Impact ($)": round(pnl, 2),
                "Return Impact (%)": round(impact_pct, 2),
                "Stressed Value ($)": round(max(0.0, pos.market_value + pnl), 2),
            })

        df_positions = pd.DataFrame(results_by_position)

        # Asset class level summary
        asset_class_pnl = df_positions.groupby("Asset Class").agg(
            {"Market Value ($)": "sum", "PnL Impact ($)": "sum"}
        ).reset_index()
        asset_class_pnl["Class Return (%)"] = (
            asset_class_pnl["PnL Impact ($)"] / asset_class_pnl["Market Value ($)"] * 100.0
        ).round(2)

        tot_val = self.portfolio.total_value
        portfolio_return_pct = (total_pnl / tot_val * 100.0) if tot_val > 0 else 0.0

        return {
            "total_pnl": round(total_pnl, 2),
            "portfolio_return_pct": round(portfolio_return_pct, 2),
            "initial_portfolio_value": round(tot_val, 2),
            "stressed_portfolio_value": round(tot_val + total_pnl, 2),
            "by_position": df_positions,
            "by_asset_class": asset_class_pnl,
        }

    def run_historical_scenario(self, scenario_key: str) -> Dict[str, Any]:
        """Runs one of the pre-defined historical Argentine crisis scenarios."""
        scenario = self.HISTORICAL_SCENARIOS.get(scenario_key)
        if not scenario:
            raise ValueError(f"Scenario {scenario_key} not recognized.")

        res = self.run_factor_stress_test(
            equity_shock=scenario["equity_shock"],
            bond_yield_shift_bps=scenario["bond_yield_shift_bps"],
            fx_shock=scenario["fx_shock"],
            vol_shock_pts=scenario["vol_shock_pts"],
            badlar_shift_bps=scenario["badlar_shift_bps"],
        )
        res["scenario_meta"] = scenario
        return res
