"""Derivatives pricing and risk sensitivity engine.
Includes Black-Scholes-Merton for European options (with analytical Greeks),
Rofex FX Futures modeling, FX Non-Deliverable Forwards (NDF), and BADLAR Interest Rate Swaps.
"""
import numpy as np
from scipy.stats import norm
from typing import Dict, Any


class BlackScholesOption:
    """Black-Scholes-Merton Option Analytical Pricer & Greek Sensitivities."""

    @staticmethod
    def calculate_greeks(
        spot: float,
        strike: float,
        time_to_maturity: float,
        rate: float,
        volatility: float,
        option_type: str = "call"
    ) -> Dict[str, float]:
        """Calculates price and Greeks: Delta, Gamma, Vega, Theta, Rho.

        :param spot: Spot price of underlying ($)
        :param strike: Option strike price ($)
        :param time_to_maturity: Time in years (e.g. 45/365)
        :param rate: Risk-free interest rate (annualized, e.g. 0.05)
        :param volatility: Implied volatility (annualized, e.g. 0.65)
        :param option_type: 'call' or 'put'
        """
        if time_to_maturity <= 0:
            price = max(0.0, (spot - strike) if option_type == "call" else (strike - spot))
            return {
                "price": price,
                "delta": 1.0 if (option_type == "call" and spot > strike) else 0.0,
                "gamma": 0.0,
                "vega": 0.0,
                "theta": 0.0,
                "rho": 0.0
            }

        d1 = (np.log(spot / strike) + (rate + 0.5 * volatility ** 2) * time_to_maturity) / (volatility * np.sqrt(time_to_maturity))
        d2 = d1 - volatility * np.sqrt(time_to_maturity)

        phi_d1 = norm.pdf(d1)
        cdf_d1 = norm.cdf(d1)
        cdf_d2 = norm.cdf(d2)

        discount = np.exp(-rate * time_to_maturity)

        if option_type.lower() == "call":
            price = spot * cdf_d1 - strike * discount * cdf_d2
            delta = cdf_d1
            rho = strike * time_to_maturity * discount * cdf_d2 / 100.0  # per 1% rate change
            theta = (- (spot * phi_d1 * volatility) / (2 * np.sqrt(time_to_maturity))
                     - rate * strike * discount * cdf_d2) / 365.0  # 1-day decay
        else:
            price = strike * discount * norm.cdf(-d2) - spot * norm.cdf(-d1)
            delta = cdf_d1 - 1.0
            rho = - strike * time_to_maturity * discount * norm.cdf(-d2) / 100.0
            theta = (- (spot * phi_d1 * volatility) / (2 * np.sqrt(time_to_maturity))
                     + rate * strike * discount * norm.cdf(-d2)) / 365.0

        # Gamma and Vega are identical for Calls and Puts
        gamma = phi_d1 / (spot * volatility * np.sqrt(time_to_maturity))
        vega = spot * phi_d1 * np.sqrt(time_to_maturity) / 100.0  # per 1% change in vol

        return {
            "price": round(float(price), 4),
            "delta": round(float(delta), 4),
            "gamma": round(float(gamma), 4),
            "vega": round(float(vega), 4),
            "theta": round(float(theta), 4),
            "rho": round(float(rho), 4),
        }


class DerivativesRiskEngine:
    """Manages Greeks aggregation and valuation for portfolio derivatives."""

    @classmethod
    def get_all_derivatives_sensitivities(cls) -> Dict[str, Dict[str, Any]]:
        """Returns risk sensitivity profile for the 5 portfolio derivatives."""
        # 1. Rofex USD/ARS 3M Futures (Long $1.5M notional)
        rofex_fx = {
            "name": "Matba Rofex USD/ARS 3M Futures",
            "type": "Exchange Futures",
            "notional": 1_500_000.0,
            "market_value": 450_000.0,
            "delta_usd": 1_500_000.0,  # 1.0 delta on underlying USD
            "gamma": 0.0,
            "vega": 0.0,
            "theta": 0.0,
            "dv01": 0.0,
            "description": "Linear FX exposure: +1% USD/ARS devaluation = +$15,000 gain"
        }

        # 2. GGAL ATM Call (Spot=$5.0, Strike=$5.0, T=45/365, Vol=65%, r=5%)
        ggal_spot = 5.0
        c_greeks = BlackScholesOption.calculate_greeks(
            spot=ggal_spot, strike=5.0, time_to_maturity=45 / 365, rate=0.05, volatility=0.65, option_type="call"
        )
        call_contracts = 160_000  # Underlying shares
        ggal_call = {
            "name": "GGAL 45D ATM Call Option",
            "type": "Option - Call",
            "notional": 800_000.0,
            "market_value": 420_000.0,
            "delta": c_greeks["delta"],
            "delta_usd": c_greeks["delta"] * 800_000.0,
            "gamma": c_greeks["gamma"],
            "gamma_usd": c_greeks["gamma"] * 800_000.0,
            "vega": c_greeks["vega"] * call_contracts,
            "theta": c_greeks["theta"] * call_contracts,
            "description": f"Delta: {c_greeks['delta']} | Vega: ${c_greeks['vega'] * call_contracts:,.0f}/vol pt"
        }

        # 3. GGAL OTM Protective Put (Spot=$5.0, Strike=$4.5, T=45/365, Vol=72%, r=5%)
        p_greeks = BlackScholesOption.calculate_greeks(
            spot=ggal_spot, strike=4.5, time_to_maturity=45 / 365, rate=0.05, volatility=0.72, option_type="put"
        )
        put_contracts = 160_000
        ggal_put = {
            "name": "GGAL 45D OTM Put Option",
            "type": "Option - Put",
            "notional": 800_000.0,
            "market_value": 280_000.0,
            "delta": p_greeks["delta"],
            "delta_usd": p_greeks["delta"] * 800_000.0,
            "gamma": p_greeks["gamma"],
            "gamma_usd": p_greeks["gamma"] * 800_000.0,
            "vega": p_greeks["vega"] * put_contracts,
            "theta": p_greeks["theta"] * put_contracts,
            "description": f"Delta: {p_greeks['delta']} (Hedge) | Vega: ${p_greeks['vega'] * put_contracts:,.0f}/vol pt"
        }

        # 4. OTC USD/ARS NDF 6M ($1.2M notional)
        usd_ndf = {
            "name": "OTC USD/ARS 6M NDF",
            "type": "OTC Forward",
            "notional": 1_200_000.0,
            "market_value": 450_000.0,
            "delta_usd": 1_140_000.0,  # Discounted delta ~0.95
            "gamma": 0.0,
            "vega": 0.0,
            "theta": -85.0,
            "dv01": -120.0,
            "description": "Synthetic USD long / ARS short forward hedge"
        }

        # 5. OTC BADLAR IRS 1Y ($2.0M notional equivalent)
        badlar_irs = {
            "name": "OTC BADLAR 1Y IRS (Pay Fixed / Rec Float)",
            "type": "Interest Rate Swap",
            "notional": 2_000_000.0,
            "market_value": 400_000.0,
            "delta_usd": 0.0,
            "gamma": 0.0,
            "vega": 0.0,
            "theta": 0.0,
            "dv01": 185.0,  # +$185 gain per 1 bp increase in floating BADLAR rate
            "description": "+$18,500 gain per 100 bps monetary tightening in BADLAR"
        }

        return {
            "ROFEX_DLR_3M": rofex_fx,
            "GGAL_C_ATM": ggal_call,
            "GGAL_P_OTM": ggal_put,
            "USD_ARS_NDF_6M": usd_ndf,
            "BADLAR_IRS_1Y": badlar_irs,
        }
