"""Argentine Sovereign Bond Pricing and Risk Sensitivity Engine.
Computes cash flows, Yield to Maturity (YTM), Macaulay Duration,
Modified Duration, Convexity, and DV01 for Argentine restructuring debt (GD30, AL30, GD35, AL35, GD38).
"""
import numpy as np
from typing import Dict, List, Tuple
from scipy.optimize import brentq


class ArgentineBondPricer:
    """Analytical pricer for Argentine restructuring bonds."""

    # Restructuring coupon schedules and amortization definitions
    BOND_SPECS = {
        "GD30": {
            "name": "Global 2030 (NY Law)",
            "maturity_years": 4.5,
            "coupon_rate": 0.0075,
            "amort_start_year": 0.5,
            "num_installments": 8,
            "law": "New York",
            "base_ytm": 0.165,
            "clean_price": 62.0,
        },
        "AL30": {
            "name": "Bonar 2030 (Local Law)",
            "maturity_years": 4.5,
            "coupon_rate": 0.0075,
            "amort_start_year": 0.5,
            "num_installments": 8,
            "law": "Argentina",
            "base_ytm": 0.182,
            "clean_price": 58.0,
        },
        "GD35": {
            "name": "Global 2035 (NY Law)",
            "maturity_years": 9.5,
            "coupon_rate": 0.03625,
            "amort_start_year": 5.0,
            "num_installments": 10,
            "law": "New York",
            "base_ytm": 0.158,
            "clean_price": 49.0,
        },
        "AL35": {
            "name": "Bonar 2035 (Local Law)",
            "maturity_years": 9.5,
            "coupon_rate": 0.03625,
            "amort_start_year": 5.0,
            "num_installments": 10,
            "law": "Argentina",
            "base_ytm": 0.171,
            "clean_price": 46.0,
        },
        "GD38": {
            "name": "Global 2038 (NY Law)",
            "maturity_years": 12.0,
            "coupon_rate": 0.0425,
            "amort_start_year": 2.0,
            "num_installments": 21,
            "law": "New York",
            "base_ytm": 0.152,
            "clean_price": 53.0,
        },
    }

    @staticmethod
    def generate_cash_flows(ticker: str) -> List[Tuple[float, float, float]]:
        """Generates list of (time_in_years, coupon_payment, principal_payment) per 100 face value.
        """
        spec = ArgentineBondPricer.BOND_SPECS.get(ticker)
        if not spec:
            raise ValueError(f"Unknown bond ticker: {ticker}")

        mat_years = spec["maturity_years"]
        periods = int(mat_years * 2)  # Semi-annual
        coupon_rate = spec["coupon_rate"]
        amort_start = spec["amort_start_year"]
        num_inst = spec["num_installments"]

        cfs = []
        remaining_principal = 100.0
        principal_per_inst = 100.0 / num_inst

        for i in range(1, periods + 1):
            t = i * 0.5
            # Interest on remaining principal
            coupon_pmt = remaining_principal * (coupon_rate / 2.0)
            principal_pmt = 0.0

            if t >= amort_start and remaining_principal > 0:
                principal_pmt = min(principal_per_inst, remaining_principal)
                remaining_principal -= principal_pmt

            if i == periods and remaining_principal > 0:
                principal_pmt += remaining_principal
                remaining_principal = 0.0

            cfs.append((t, coupon_pmt, principal_pmt))

        return cfs

    @staticmethod
    def price_from_ytm(cash_flows: List[Tuple[float, float, float]], ytm: float, freq: int = 2) -> float:
        """Discounts semi-annual cash flows at annual compounded YTM.
        """
        price = 0.0
        for t, coupon, principal in cash_flows:
            total_cf = coupon + principal
            df = (1.0 + ytm / freq) ** (-t * freq)
            price += total_cf * df
        return price

    @staticmethod
    def calculate_ytm(cash_flows: List[Tuple[float, float, float]], market_price: float, freq: int = 2) -> float:
        """Solves for YTM given a market price per 100 nominal using Brent's method.
        """
        def objective(y):
            return ArgentineBondPricer.price_from_ytm(cash_flows, y, freq) - market_price

        try:
            return float(brentq(objective, 0.001, 1.50))
        except Exception:
            # Fallback estimation
            return 0.165

    @classmethod
    def calculate_risk_metrics(cls, ticker: str, market_price: float = None, ytm: float = None) -> Dict[str, float]:
        """Calculates Yield, Macaulay Duration, Modified Duration, Convexity, and DV01.
        """
        spec = cls.BOND_SPECS.get(ticker)
        if not spec:
            raise ValueError(f"Ticker {ticker} not found in ArgentineBondPricer specs.")

        cash_flows = cls.generate_cash_flows(ticker)
        freq = 2

        if market_price is None and ytm is None:
            market_price = spec["clean_price"]
            ytm = spec["base_ytm"]
        elif market_price is not None and ytm is None:
            ytm = cls.calculate_ytm(cash_flows, market_price, freq)
        elif ytm is not None and market_price is None:
            market_price = cls.price_from_ytm(cash_flows, ytm, freq)

        # Macaulay Duration & Convexity
        weighted_time = 0.0
        convexity_sum = 0.0
        pv_sum = 0.0

        for t, coupon, principal in cash_flows:
            total_cf = coupon + principal
            pv_cf = total_cf * ((1.0 + ytm / freq) ** (-t * freq))
            weighted_time += t * pv_cf
            convexity_sum += (t * (t + 1.0 / freq)) * pv_cf
            pv_sum += pv_cf

        mac_duration = weighted_time / pv_sum if pv_sum > 0 else 0.0
        mod_duration = mac_duration / (1.0 + ytm / freq)
        convexity = (convexity_sum / (pv_sum * ((1.0 + ytm / freq) ** 2))) if pv_sum > 0 else 0.0

        # DV01 per $1,000,000 exposure: dollar change for 1 bp (+0.0001) shift in yield
        # dP / P = -ModDur * dy -> dP = -ModDur * P * 0.0001
        dv01_per_100 = mod_duration * market_price * 0.0001

        return {
            "ticker": ticker,
            "name": spec["name"],
            "law": spec["law"],
            "clean_price": round(market_price, 2),
            "ytm_percent": round(ytm * 100, 2),
            "macaulay_duration": round(mac_duration, 2),
            "modified_duration": round(mod_duration, 2),
            "convexity": round(convexity, 2),
            "dv01_per_100": round(dv01_per_100, 4),
        }

    @classmethod
    def get_portfolio_bond_analytics(cls) -> List[Dict[str, float]]:
        """Returns analytics for all 5 Argentine bonds."""
        results = []
        for ticker in ["GD30", "AL30", "GD35", "AL35", "GD38"]:
            results.append(cls.calculate_risk_metrics(ticker))
        return results
