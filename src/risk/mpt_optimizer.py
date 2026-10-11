"""Modern Portfolio Theory (MPT) Quantitative Engine & Markowitz Optimizer.

Models annualized expected returns (mu_i), volatilities (sigma_i), and covariance
structures (Sigma) across Argentine multi-currency portfolios:
- Core CEDEARs (SPY, QQQ, AAPL, GOOGL, V, MSFT, etc.)
- High-Beta CEDEARs & Equities (MELI, PBR, COPX, ADBE, YPFD, GGAL, etc.)
- Fixed Income / Carry (AL30, GD30, Boncaps T15E7, T31Y7, Lecaps, ONs)
- Cash / Money Market FCIs (COCOSPPA, COCOUSDPA, Cauciones, Liquid Cash)

Computes:
- Total Portfolio Expected Return, Volatility, and Sharpe Ratio
- Maximum Sharpe Ratio (Tangency) Portfolio via scipy.optimize.minimize (SLSQP)
- Minimum Volatility Portfolio via scipy.optimize.minimize (SLSQP)
- Efficient Frontier curve & Capital Allocation Line (CAL)
"""
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd
from scipy.optimize import minimize
import yfinance as yf

from src.portfolio.models import Portfolio, Position, AssetClass


# Canonical MPT Asset Categories for color-coding and filtering
MPT_CATEGORY_CORE_CEDEAR = "Core CEDEARs"
MPT_CATEGORY_HIGH_BETA = "High-Beta CEDEARs"
MPT_CATEGORY_FIXED_INCOME = "Fixed Income / Carry"
MPT_CATEGORY_CASH_FCI = "Cash / FCIs"


# Institutional USD-equivalent annualized priors: (expected_return_mu, annualized_vol_sigma, mpt_category)
INSTRUMENT_MPT_PRIORS: Dict[str, Tuple[float, float, str]] = {
    # --- Core CEDEARs (Broad US Indices & Quality Mega-Cap Compounders) ---
    "SPY": (0.105, 0.165, MPT_CATEGORY_CORE_CEDEAR),
    "QQQ": (0.130, 0.210, MPT_CATEGORY_CORE_CEDEAR),
    "DIA": (0.095, 0.155, MPT_CATEGORY_CORE_CEDEAR),
    "AAPL": (0.125, 0.245, MPT_CATEGORY_CORE_CEDEAR),
    "GOOGL": (0.132, 0.265, MPT_CATEGORY_CORE_CEDEAR),
    "GOOG": (0.132, 0.265, MPT_CATEGORY_CORE_CEDEAR),
    "V": (0.115, 0.205, MPT_CATEGORY_CORE_CEDEAR),
    "MSFT": (0.128, 0.235, MPT_CATEGORY_CORE_CEDEAR),
    "AMZN": (0.138, 0.280, MPT_CATEGORY_CORE_CEDEAR),
    "KO": (0.082, 0.145, MPT_CATEGORY_CORE_CEDEAR),
    "BRK.B": (0.102, 0.160, MPT_CATEGORY_CORE_CEDEAR),
    "JPM": (0.110, 0.220, MPT_CATEGORY_CORE_CEDEAR),
    "WMT": (0.092, 0.165, MPT_CATEGORY_CORE_CEDEAR),
    "PG": (0.085, 0.150, MPT_CATEGORY_CORE_CEDEAR),
    "JNJ": (0.084, 0.155, MPT_CATEGORY_CORE_CEDEAR),

    # --- High-Beta CEDEARs (Growth, Thematic, EM & Cyclicals) ---
    "ADBE": (0.122, 0.315, MPT_CATEGORY_HIGH_BETA),
    "MELI": (0.168, 0.380, MPT_CATEGORY_HIGH_BETA),
    "PBR": (0.148, 0.365, MPT_CATEGORY_HIGH_BETA),
    "COPX": (0.142, 0.340, MPT_CATEGORY_HIGH_BETA),
    "NVDA": (0.185, 0.450, MPT_CATEGORY_HIGH_BETA),
    "TSLA": (0.160, 0.520, MPT_CATEGORY_HIGH_BETA),
    "META": (0.150, 0.360, MPT_CATEGORY_HIGH_BETA),
    "AMD": (0.158, 0.440, MPT_CATEGORY_HIGH_BETA),
    "NFLX": (0.140, 0.350, MPT_CATEGORY_HIGH_BETA),
    "VIST": (0.175, 0.400, MPT_CATEGORY_HIGH_BETA),
    "EWZ": (0.135, 0.330, MPT_CATEGORY_HIGH_BETA),
    "ARKK": (0.145, 0.480, MPT_CATEGORY_HIGH_BETA),
    "GLOB": (0.135, 0.370, MPT_CATEGORY_HIGH_BETA),
    "PAGS": (0.130, 0.390, MPT_CATEGORY_HIGH_BETA),

    # --- Local BYMA Equities (Mapped into High-Beta / Equity Sleeve) ---
    "YPFD": (0.172, 0.420, MPT_CATEGORY_HIGH_BETA),
    "GGAL": (0.180, 0.460, MPT_CATEGORY_HIGH_BETA),
    "PAMP": (0.158, 0.380, MPT_CATEGORY_HIGH_BETA),
    "BMA": (0.174, 0.440, MPT_CATEGORY_HIGH_BETA),
    "TXAR": (0.132, 0.350, MPT_CATEGORY_HIGH_BETA),
    "ALUA": (0.130, 0.340, MPT_CATEGORY_HIGH_BETA),
    "CEPU": (0.155, 0.390, MPT_CATEGORY_HIGH_BETA),
    "TGSU2": (0.152, 0.375, MPT_CATEGORY_HIGH_BETA),
    "EDN": (0.165, 0.450, MPT_CATEGORY_HIGH_BETA),

    # --- Fixed Income / Carry (Sovereign Bonds, Boncaps, Lecaps, Corporate ONs) ---
    "T15E7": (0.136, 0.215, MPT_CATEGORY_FIXED_INCOME),
    "T31Y7": (0.142, 0.230, MPT_CATEGORY_FIXED_INCOME),
    "AL30": (0.165, 0.305, MPT_CATEGORY_FIXED_INCOME),
    "AL30D": (0.165, 0.305, MPT_CATEGORY_FIXED_INCOME),
    "GD30": (0.155, 0.275, MPT_CATEGORY_FIXED_INCOME),
    "GD30D": (0.155, 0.275, MPT_CATEGORY_FIXED_INCOME),
    "AL35": (0.158, 0.290, MPT_CATEGORY_FIXED_INCOME),
    "GD35": (0.148, 0.260, MPT_CATEGORY_FIXED_INCOME),
    "GD38": (0.145, 0.250, MPT_CATEGORY_FIXED_INCOME),
    "AE38": (0.152, 0.280, MPT_CATEGORY_FIXED_INCOME),
    "AL29": (0.160, 0.295, MPT_CATEGORY_FIXED_INCOME),
    "GD29": (0.150, 0.265, MPT_CATEGORY_FIXED_INCOME),
    "AL41": (0.150, 0.285, MPT_CATEGORY_FIXED_INCOME),
    "GD41": (0.144, 0.255, MPT_CATEGORY_FIXED_INCOME),
    "BOPREAL": (0.115, 0.165, MPT_CATEGORY_FIXED_INCOME),
    "TX26": (0.125, 0.210, MPT_CATEGORY_FIXED_INCOME),
    "TX28": (0.130, 0.225, MPT_CATEGORY_FIXED_INCOME),
    "YCA6O": (0.085, 0.115, MPT_CATEGORY_FIXED_INCOME),
    "TLC1O": (0.082, 0.110, MPT_CATEGORY_FIXED_INCOME),
    "IRCFO": (0.086, 0.115, MPT_CATEGORY_FIXED_INCOME),
    "PAMPO": (0.084, 0.112, MPT_CATEGORY_FIXED_INCOME),

    # --- Money Market / FCIs / Cash ---
    "COCOUSDPA": (0.046, 0.022, MPT_CATEGORY_CASH_FCI),
    "COCOSPPA": (0.049, 0.042, MPT_CATEGORY_CASH_FCI),
    "COCODAA": (0.054, 0.048, MPT_CATEGORY_CASH_FCI),
    "FCI_MM_ARS": (0.048, 0.040, MPT_CATEGORY_CASH_FCI),
    "CAUCION_USD": (0.044, 0.015, MPT_CATEGORY_CASH_FCI),
    "CAUCION_ARS": (0.048, 0.038, MPT_CATEGORY_CASH_FCI),
    "CASH_USD": (0.042, 0.010, MPT_CATEGORY_CASH_FCI),
    "CASH_ARS": (0.042, 0.035, MPT_CATEGORY_CASH_FCI),
    "CASH_EXT": (0.042, 0.010, MPT_CATEGORY_CASH_FCI),
}


def normalize_base_ticker(ticker: str) -> str:
    """Normalizes a broker or BYMA ticker (e.g. 'SPY.BA' -> 'SPY', 'AL30D' -> 'AL30') for lookup."""
    t = str(ticker).strip().upper()
    if t.endswith(".BA"):
        t = t[:-3]
    return t


def classify_and_parameterize_position(pos: Position) -> Dict[str, Any]:
    """Determines the MPT category, annualized expected return (mu), and annualized
    volatility (sigma) for a single Portfolio Position.
    """
    base_t = normalize_base_ticker(pos.ticker)
    name_upper = str(pos.name).upper()
    ticker_upper = str(pos.ticker).upper()

    # 1. Direct lookup in calibrated table
    if base_t in INSTRUMENT_MPT_PRIORS:
        mu, sigma, cat = INSTRUMENT_MPT_PRIORS[base_t]
        return {
            "ticker": pos.ticker,
            "base_ticker": base_t,
            "name": pos.name,
            "category": cat,
            "expected_return": float(mu),
            "volatility": float(sigma),
        }

    # Check if stripping trailing D/C matches a bond (e.g. AL30D -> AL30)
    if len(base_t) >= 5 and base_t[-1] in ("D", "C") and base_t[:-1] in INSTRUMENT_MPT_PRIORS:
        mu, sigma, cat = INSTRUMENT_MPT_PRIORS[base_t[:-1]]
        return {
            "ticker": pos.ticker,
            "base_ticker": base_t[:-1],
            "name": pos.name,
            "category": cat,
            "expected_return": float(mu),
            "volatility": float(sigma),
        }

    # 2. Rule-based classification by AssetClass and keywords
    if (
        pos.asset_class == AssetClass.CASH
        or any(k in ticker_upper for k in ["CASH", "CAUCION", "COCOS", "FCI", "MM", "LIQUID"])
        or any(k in name_upper for k in ["FCI", "FONDO", "MONEY MARKET", "AHORRO", "CAUCION", "LIQUIDEZ"])
    ):
        is_usd = "USD" in ticker_upper or "USD" in name_upper or "DOLAR" in name_upper
        mu = 0.045 if is_usd else 0.049
        sigma = 0.020 if is_usd else 0.042
        return {
            "ticker": pos.ticker,
            "base_ticker": base_t,
            "name": pos.name,
            "category": MPT_CATEGORY_CASH_FCI,
            "expected_return": mu,
            "volatility": sigma,
        }

    if (
        pos.asset_class == AssetClass.BOND
        or any(k in ticker_upper for k in ["T15", "T31", "AL", "GD", "TX", "BOP", "S31", "S14", "LECAP", "BONCAP"])
        or any(k in name_upper for k in ["BONO", "BONCAP", "LECAP", "LETRA", "TESORO", "GLOBAL", "BONAR"])
    ):
        ytm = float(pos.details.get("ytm", 0.145))
        if ytm > 1.0:
            ytm = ytm / 100.0
        mod_dur = float(pos.details.get("modified_duration", 2.5))
        # Expected USD return modeled from effective yield adjusted for credit/FX carry
        mu = float(np.clip(ytm * 0.90, 0.08, 0.22))
        sigma = float(np.clip(0.14 + mod_dur * 0.045, 0.15, 0.35))
        return {
            "ticker": pos.ticker,
            "base_ticker": base_t,
            "name": pos.name,
            "category": MPT_CATEGORY_FIXED_INCOME,
            "expected_return": mu,
            "volatility": sigma,
        }

    if pos.asset_class == AssetClass.DERIVATIVE:
        if any(k in ticker_upper for k in ["ROFEX", "NDF", "IRS", "BADLAR"]):
            return {
                "ticker": pos.ticker,
                "base_ticker": base_t,
                "name": pos.name,
                "category": MPT_CATEGORY_FIXED_INCOME,
                "expected_return": 0.115,
                "volatility": 0.240,
            }
        return {
            "ticker": pos.ticker,
            "base_ticker": base_t,
            "name": pos.name,
            "category": MPT_CATEGORY_HIGH_BETA,
            "expected_return": 0.165,
            "volatility": 0.480,
        }

    # Default Equity classification: distinguish Core vs High-Beta
    beta = float(pos.details.get("beta", 1.1))
    if beta <= 1.05 and not ticker_upper.endswith(".BA"):
        cat = MPT_CATEGORY_CORE_CEDEAR
        mu, sigma = 0.112, 0.215
    else:
        cat = MPT_CATEGORY_HIGH_BETA
        mu, sigma = 0.148, 0.360

    return {
        "ticker": pos.ticker,
        "base_ticker": base_t,
        "name": pos.name,
        "category": cat,
        "expected_return": mu,
        "volatility": sigma,
    }


class MPTOptimizer:
    """Modern Portfolio Theory (MPT) quantitative engine & Markowitz frontier solver."""

    def __init__(
        self,
        portfolio: Portfolio,
        risk_free_rate: float = 0.042,
        use_yfinance: bool = False,
        lookback_period: str = "1y",
    ):
        self.portfolio = portfolio
        self.portfolio.update_weights()
        self.risk_free_rate = float(risk_free_rate)
        self.use_yfinance = use_yfinance
        self.lookback_period = lookback_period

        self.positions: List[Position] = list(self.portfolio.positions)
        self.n_assets = len(self.positions)
        self.tickers = [p.ticker for p in self.positions]
        self.weights = np.array([p.weight for p in self.positions], dtype=float)
        if self.weights.sum() > 0:
            self.weights = self.weights / self.weights.sum()

        # Parameterize each position
        self.asset_Meta: List[Dict[str, Any]] = [
            classify_and_parameterize_position(p) for p in self.positions
        ]

        if self.use_yfinance:
            self._enrich_with_yfinance()

        self.mu = np.array([m["expected_return"] for m in self.asset_Meta], dtype=float)
        self.sigma = np.array([m["volatility"] for m in self.asset_Meta], dtype=float)
        self.categories = [m["category"] for m in self.asset_Meta]

        self.corr_matrix = self._build_correlation_matrix()
        self.cov_matrix = np.outer(self.sigma, self.sigma) * self.corr_matrix

    def _enrich_with_yfinance(self) -> None:
        """Fetches rolling daily adjusted returns via the persistent local disk cache
        (`MarketDataLoader.sync_local_cache`) and blends empirical volatility/returns with institutional priors.
        """
        from src.data.loader import MarketDataLoader

        try:
            cached_df, _ = MarketDataLoader.sync_local_cache(self.tickers)
            if cached_df.empty:
                return

            lookback_days = 252 if self.lookback_period == "1y" else 504
            ret_df = cached_df.tail(lookback_days)
            if len(ret_df) < 40:
                return

            for idx, m in enumerate(self.asset_Meta):
                yf_sym = MarketDataLoader.map_to_yahoo_symbol(m["ticker"])
                if yf_sym and yf_sym in ret_df.columns:
                    series = ret_df[yf_sym].dropna()
                    if len(series) >= 40:
                        emp_vol = float(series.std() * np.sqrt(252))
                        emp_ret = float(series.mean() * 252)
                        prior_mu = m["expected_return"]
                        prior_vol = m["volatility"]
                        # Black-Litterman / Shrinkage blend (50% empirical + 50% prior for return, 70% empirical for vol)
                        blended_mu = float(np.clip(0.5 * emp_ret + 0.5 * prior_mu, 0.05, 0.30))
                        blended_vol = float(np.clip(0.7 * emp_vol + 0.3 * prior_vol, 0.10, 0.65))
                        self.asset_Meta[idx]["expected_return"] = blended_mu
                        self.asset_Meta[idx]["volatility"] = blended_vol
        except Exception:
            # Graceful fallback to calibrated priors if offline or rate-limited
            pass

    def _build_correlation_matrix(self) -> np.ndarray:
        """Constructs a positive-definite multi-asset correlation matrix across the portfolio."""
        n = self.n_assets
        if n == 0:
            return np.zeros((0, 0))
        if n == 1:
            return np.ones((1, 1))

        corr = np.eye(n, dtype=float)
        us_tech_etfs = {"SPY", "QQQ", "AAPL", "GOOGL", "GOOG", "MSFT", "V", "ADBE", "NVDA", "META", "AMZN"}
        commodities_em = {"PBR", "COPX", "EWZ", "VIST"}
        arg_equities = {"YPFD", "GGAL", "PAMP", "BMA", "TXAR", "ALUA", "CEPU", "TGSU2", "EDN"}
        boncaps_lecaps = {"T15E7", "T31Y7", "TX26", "TX28"}
        sov_usd_bonds = {"AL30", "GD30", "AL35", "GD35", "GD38", "AE38", "AL29", "GD29", "AL41", "GD41"}

        for i in range(n):
            for j in range(i + 1, n):
                m_i = self.asset_Meta[i]
                m_j = self.asset_Meta[j]
                cat_i, cat_j = m_i["category"], m_j["category"]
                bt_i, bt_j = m_i["base_ticker"], m_j["base_ticker"]

                # Cash / FCIs have near-zero correlation with risky assets
                if cat_i == MPT_CATEGORY_CASH_FCI and cat_j == MPT_CATEGORY_CASH_FCI:
                    rho = 0.25
                elif cat_i == MPT_CATEGORY_CASH_FCI or cat_j == MPT_CATEGORY_CASH_FCI:
                    other_cat = cat_j if cat_i == MPT_CATEGORY_CASH_FCI else cat_i
                    rho = 0.08 if other_cat == MPT_CATEGORY_FIXED_INCOME else 0.02

                # Intra-Core CEDEARs
                elif cat_i == MPT_CATEGORY_CORE_CEDEAR and cat_j == MPT_CATEGORY_CORE_CEDEAR:
                    if {bt_i, bt_j} == {"SPY", "QQQ"}:
                        rho = 0.88
                    elif "SPY" in (bt_i, bt_j) or "QQQ" in (bt_i, bt_j):
                        rho = 0.76
                    else:
                        rho = 0.68

                # Core CEDEAR vs High-Beta CEDEAR
                elif {cat_i, cat_j} == {MPT_CATEGORY_CORE_CEDEAR, MPT_CATEGORY_HIGH_BETA}:
                    hb_bt = bt_i if cat_i == MPT_CATEGORY_HIGH_BETA else bt_j
                    if hb_bt in us_tech_etfs or hb_bt == "MELI":
                        rho = 0.64
                    elif hb_bt in commodities_em:
                        rho = 0.42
                    elif hb_bt in arg_equities:
                        rho = 0.35
                    else:
                        rho = 0.55

                # Intra-High-Beta CEDEARs / Local Equities
                elif cat_i == MPT_CATEGORY_HIGH_BETA and cat_j == MPT_CATEGORY_HIGH_BETA:
                    if bt_i in arg_equities and bt_j in arg_equities:
                        rho = 0.74
                    elif bt_i in commodities_em and bt_j in commodities_em:
                        rho = 0.58
                    else:
                        rho = 0.50

                # Intra-Fixed Income / Carry
                elif cat_i == MPT_CATEGORY_FIXED_INCOME and cat_j == MPT_CATEGORY_FIXED_INCOME:
                    if bt_i in boncaps_lecaps and bt_j in boncaps_lecaps:
                        rho = 0.88
                    elif bt_i in sov_usd_bonds and bt_j in sov_usd_bonds:
                        rho = 0.90
                    else:
                        rho = 0.65

                # Fixed Income vs Equities / CEDEARs
                elif MPT_CATEGORY_FIXED_INCOME in (cat_i, cat_j):
                    eq_bt = bt_j if cat_i == MPT_CATEGORY_FIXED_INCOME else bt_i
                    if eq_bt in arg_equities:
                        rho = 0.52  # Sovereign risk factor links local stocks & bonds
                    elif eq_bt in commodities_em:
                        rho = 0.28
                    else:
                        rho = 0.22  # Low correlation between US CEDEARs and Argentine carry/bonds
                else:
                    rho = 0.30

                corr[i, j] = rho
                corr[j, i] = rho

        # Ensure positive definiteness via eigenvalue flooring
        eigvals, eigvecs = np.linalg.eigh(corr)
        eigvals = np.maximum(eigvals, 1e-5)
        corr_pd = eigvecs @ np.diag(eigvals) @ eigvecs.T
        inv_std = 1.0 / np.sqrt(np.diag(corr_pd))
        corr_pd = corr_pd * np.outer(inv_std, inv_std)
        np.fill_diagonal(corr_pd, 1.0)
        return corr_pd

    def portfolio_metrics(self, weights: Optional[np.ndarray] = None) -> Dict[str, float]:
        """Computes portfolio expected return (mu_p), volatility (sigma_p), and Sharpe ratio."""
        w = self.weights if weights is None else np.asarray(weights, dtype=float)
        if len(w) == 0 or np.sum(w) <= 0:
            return {"expected_return": 0.0, "volatility": 0.0, "sharpe": 0.0}
        w = w / np.sum(w)
        mu_p = float(w.T @ self.mu)
        var_p = float(w.T @ self.cov_matrix @ w)
        sigma_p = float(np.sqrt(max(var_p, 1e-10)))
        sharpe_p = float((mu_p - self.risk_free_rate) / sigma_p) if sigma_p > 1e-8 else 0.0
        return {
            "expected_return": mu_p,
            "expected_return_pct": round(mu_p * 100.0, 2),
            "volatility": sigma_p,
            "volatility_pct": round(sigma_p * 100.0, 2),
            "sharpe": round(sharpe_p, 3),
        }

    def optimize_max_sharpe(self, max_weight: float = 1.0) -> Dict[str, Any]:
        """Finds the Maximum Sharpe Ratio (Tangency) Portfolio:
        max (w^T mu - R_f) / sqrt(w^T Sigma w) s.t. sum(w_i) = 1, 0 <= w_i <= max_weight.
        """
        n = self.n_assets
        if n == 0:
            return {"weights": np.array([]), "expected_return": 0.0, "volatility": 0.0, "sharpe": 0.0}
        if n == 1:
            w_opt = np.array([1.0])
            m = self.portfolio_metrics(w_opt)
            return {**m, "weights": w_opt}

        eff_max_w = max(max_weight, 1.0 / n + 1e-4)
        bounds = tuple((0.0, min(1.0, eff_max_w)) for _ in range(n))
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        init_w = np.full(n, 1.0 / n)

        def neg_sharpe(w: np.ndarray) -> float:
            mu_p = float(w @ self.mu)
            vol_p = float(np.sqrt(max(w @ self.cov_matrix @ w, 1e-12)))
            return -(mu_p - self.risk_free_rate) / vol_p

        res = minimize(
            neg_sharpe,
            init_w,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"ftol": 1e-10, "maxiter": 500},
        )
        w_opt = res.x if res.success else init_w
        w_opt = np.clip(w_opt, 0.0, 1.0)
        w_opt = w_opt / np.sum(w_opt)
        metrics = self.portfolio_metrics(w_opt)
        return {**metrics, "weights": w_opt, "success": bool(res.success)}

    def optimize_min_volatility(self, max_weight: float = 1.0) -> Dict[str, Any]:
        """Finds the Global Minimum Volatility Portfolio:
        min sqrt(w^T Sigma w) s.t. sum(w_i) = 1, 0 <= w_i <= max_weight.
        """
        n = self.n_assets
        if n == 0:
            return {"weights": np.array([]), "expected_return": 0.0, "volatility": 0.0, "sharpe": 0.0}
        if n == 1:
            w_opt = np.array([1.0])
            m = self.portfolio_metrics(w_opt)
            return {**m, "weights": w_opt}

        eff_max_w = max(max_weight, 1.0 / n + 1e-4)
        bounds = tuple((0.0, min(1.0, eff_max_w)) for _ in range(n))
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        init_w = np.full(n, 1.0 / n)

        def port_vol(w: np.ndarray) -> float:
            return float(np.sqrt(max(w @ self.cov_matrix @ w, 1e-12)))

        res = minimize(
            port_vol,
            init_w,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"ftol": 1e-10, "maxiter": 500},
        )
        w_opt = res.x if res.success else init_w
        w_opt = np.clip(w_opt, 0.0, 1.0)
        w_opt = w_opt / np.sum(w_opt)
        metrics = self.portfolio_metrics(w_opt)
        return {**metrics, "weights": w_opt, "success": bool(res.success)}

    def generate_efficient_frontier(
        self,
        num_points: int = 40,
        max_weight: float = 1.0,
    ) -> Dict[str, Any]:
        """Generates the Markowitz Efficient Frontier curve by sweeping target return levels
        from the Minimum Volatility portfolio return up to the maximum achievable return,
        along with the Capital Allocation Line (CAL).
        """
        min_vol_res = self.optimize_min_volatility(max_weight=max_weight)
        max_sharpe_res = self.optimize_max_sharpe(max_weight=max_weight)
        current_res = self.portfolio_metrics(self.weights)

        n = self.n_assets
        if n <= 1:
            vol_pt = current_res["volatility_pct"]
            ret_pt = current_res["expected_return_pct"]
            return {
                "frontier_vols_pct": [vol_pt],
                "frontier_returns_pct": [ret_pt],
                "frontier_sharpes": [current_res["sharpe"]],
                "cal_vols_pct": [0.0, vol_pt * 1.25],
                "cal_returns_pct": [
                    round(self.risk_free_rate * 100.0, 2),
                    round((self.risk_free_rate + max_sharpe_res["sharpe"] * (vol_pt * 1.25 / 100.0)) * 100.0, 2),
                ],
                "current": current_res,
                "max_sharpe": max_sharpe_res,
                "min_vol": min_vol_res,
            }

        eff_max_w = max(max_weight, 1.0 / n + 1e-4)
        bounds = tuple((0.0, min(1.0, eff_max_w)) for _ in range(n))

        # Determine max achievable return under max_weight constraint
        if eff_max_w >= 0.999:
            max_ret = float(np.max(self.mu)) * 0.998
        else:
            res_max_ret = minimize(
                lambda w: -float(w @ self.mu),
                np.full(n, 1.0 / n),
                method="SLSQP",
                bounds=bounds,
                constraints=[{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}],
            )
            max_ret = float(res_max_ret.x @ self.mu) * 0.998 if res_max_ret.success else float(np.max(self.mu))

        min_ret = max(float(np.min(self.mu)), min_vol_res["expected_return"] * 0.92)
        target_returns = np.linspace(min_ret, max_ret, num_points)

        frontier_vols_pct = []
        frontier_returns_pct = []
        frontier_sharpes = []

        prev_w = min_vol_res["weights"]
        for target_mu in target_returns:
            constraints = [
                {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
                {"type": "eq", "fun": lambda w, t=target_mu: float(w @ self.mu) - t},
            ]
            res = minimize(
                lambda w: float(np.sqrt(max(w @ self.cov_matrix @ w, 1e-12))),
                prev_w,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"ftol": 1e-9, "maxiter": 300},
            )
            if res.success:
                prev_w = res.x
                m = self.portfolio_metrics(res.x)
                frontier_vols_pct.append(m["volatility_pct"])
                frontier_returns_pct.append(m["expected_return_pct"])
                frontier_sharpes.append(m["sharpe"])

        # Capital Allocation Line (CAL): from (0, R_f) through Max Sharpe up to max asset vol
        max_axis_vol_pct = max(
            float(np.max(self.sigma)) * 100.0 * 1.10,
            current_res["volatility_pct"] * 1.15,
            max_sharpe_res["volatility_pct"] * 1.35,
        )
        cal_vols_pct = [0.0, max_sharpe_res["volatility_pct"], round(max_axis_vol_pct, 2)]
        rf_pct = self.risk_free_rate * 100.0
        ms_sharpe = max_sharpe_res["sharpe"]
        cal_returns_pct = [
            round(rf_pct, 2),
            max_sharpe_res["expected_return_pct"],
            round(rf_pct + ms_sharpe * max_axis_vol_pct, 2),
        ]

        return {
            "frontier_vols_pct": frontier_vols_pct,
            "frontier_returns_pct": frontier_returns_pct,
            "frontier_sharpes": frontier_sharpes,
            "cal_vols_pct": cal_vols_pct,
            "cal_returns_pct": cal_returns_pct,
            "current": current_res,
            "max_sharpe": max_sharpe_res,
            "min_vol": min_vol_res,
        }

    def get_asset_allocation_dataframe(
        self,
        max_sharpe_res: Optional[Dict[str, Any]] = None,
        min_vol_res: Optional[Dict[str, Any]] = None,
        currency_multiplier: float = 1.0,
    ) -> pd.DataFrame:
        """Builds a comprehensive DataFrame of all portfolio positions with individual
        expected returns, volatilities, Sharpe ratios, current weights, and optimal weights.
        """
        if max_sharpe_res is None:
            max_sharpe_res = self.optimize_max_sharpe()
        if min_vol_res is None:
            min_vol_res = self.optimize_min_volatility()

        w_ms = max_sharpe_res["weights"]
        w_mv = min_vol_res["weights"]

        rows = []
        for i, pos in enumerate(self.positions):
            meta = self.asset_Meta[i]
            mu_i = self.mu[i]
            sig_i = self.sigma[i]
            sharpe_i = (mu_i - self.risk_free_rate) / sig_i if sig_i > 1e-8 else 0.0
            cur_w_pct = float(self.weights[i] * 100.0)
            ms_w_pct = float(w_ms[i] * 100.0) if i < len(w_ms) else 0.0
            mv_w_pct = float(w_mv[i] * 100.0) if i < len(w_mv) else 0.0

            rows.append({
                "Ticker": pos.ticker,
                "Base Ticker": meta["base_ticker"],
                "Name": pos.name,
                "Category": meta["category"],
                "Asset Class": pos.asset_class.value,
                "Market Value ($)": round(pos.market_value * currency_multiplier, 2),
                "Current Weight (%)": round(cur_w_pct, 2),
                "Max Sharpe Weight (%)": round(ms_w_pct, 2),
                "Min Vol Weight (%)": round(mv_w_pct, 2),
                "Weight Delta vs Max Sharpe (%)": round(ms_w_pct - cur_w_pct, 2),
                "Expected Return (%)": round(mu_i * 100.0, 2),
                "Annualized Volatility (%)": round(sig_i * 100.0, 2),
                "Sharpe Ratio": round(sharpe_i, 2),
            })

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values(by="Current Weight (%)", ascending=False).reset_index(drop=True)
        return df

    def filter_subportfolio(self, filter_mode: str = "All Assets") -> "Portfolio":
        """Returns a filtered Portfolio according to the user's selected view mode:
        - 'All Assets': All positions in the portfolio
        - 'CEDEARs Only': Only Equity / CEDEAR positions (Core CEDEARs & High-Beta CEDEARs)
        - 'Optimal Allocations': Positions that have non-trivial weight in Current, Max Sharpe, or Min Vol
        """
        if filter_mode == "CEDEARs Only":
            selected = [
                Position(
                    ticker=p.ticker,
                    name=p.name,
                    asset_class=p.asset_class,
                    quantity=p.quantity,
                    unit_price=p.unit_price,
                    market_value=p.market_value,
                    weight=p.weight,
                    currency=p.currency,
                    notional=p.notional,
                    details=dict(p.details),
                )
                for i, p in enumerate(self.positions)
                if self.asset_Meta[i]["category"] in (MPT_CATEGORY_CORE_CEDEAR, MPT_CATEGORY_HIGH_BETA)
            ]
            if selected:
                sub = Portfolio(name=f"{self.portfolio.name} (CEDEARs / Equities)", positions=selected)
                sub.update_weights()
                return sub

        return self.portfolio
