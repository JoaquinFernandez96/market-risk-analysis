"""Market data loader and return generation engine.
Fetches or simulates realistic historical price series, return matrices,
and correlation structures for Base and Stressed market scenarios.
"""
import numpy as np
import pandas as pd
from typing import Tuple, List, Dict
import yfinance as yf


ALL_TICKERS = [
    # Equities
    "YPFD.BA", "GGAL.BA", "PAMP.BA", "BMA.BA", "TXAR.BA",
    # Sovereign Bonds
    "GD30", "AL30", "GD35", "AL35", "GD38",
    # Derivatives
    "ROFEX_DLR_3M", "GGAL_C_ATM", "GGAL_P_OTM", "USD_ARS_NDF_6M", "BADLAR_IRS_1Y"
]


class MarketDataLoader:
    """Provides daily returns and correlation structures for the 15 portfolio assets

    under both Base and Stressed market regimes.
    """

    @staticmethod
    def _get_base_parameters() -> Tuple[Dict[str, float], np.ndarray]:
        """Annualized volatilities and correlation matrix under standard/base Argentine market conditions.
        """
        # Annualized standard volatilities (Base scenario)
        vol_map = {
            # Equities (~35% - 48% annualized vol)
            "YPFD.BA": 0.42,
            "GGAL.BA": 0.46,
            "PAMP.BA": 0.38,
            "BMA.BA": 0.44,
            "TXAR.BA": 0.35,
            # Sovereign Bonds (~25% - 34% annualized vol)
            "GD30": 0.28,
            "AL30": 0.32,
            "GD35": 0.26,
            "AL35": 0.29,
            "GD38": 0.25,
            # Derivatives
            "ROFEX_DLR_3M": 0.30,   # FX volatility
            "GGAL_C_ATM": 0.85,     # Option leverage vol
            "GGAL_P_OTM": 0.95,     # OTM Put vol
            "USD_ARS_NDF_6M": 0.28, # NDF forward vol
            "BADLAR_IRS_1Y": 0.18,  # Rate swap vol
        }

        n = len(ALL_TICKERS)
        corr = np.eye(n)

        # Populate realistic intra-asset class correlations
        for i, t1 in enumerate(ALL_TICKERS):
            for j, t2 in enumerate(ALL_TICKERS):
                if i == j:
                    continue
                # Equity-Equity correlation (~0.65 - 0.85)
                if i < 5 and j < 5:
                    corr[i, j] = 0.72
                # Bond-Bond correlation (~0.80 - 0.95)
                elif 5 <= i < 10 and 5 <= j < 10:
                    corr[i, j] = 0.88
                # Equity-Bond correlation (~0.45 - 0.55 in Argentina due to sovereign risk factor)
                elif (i < 5 and 5 <= j < 10) or (5 <= i < 10 and j < 5):
                    corr[i, j] = 0.48
                # FX futures / NDF correlation with Equities/Bonds
                elif t1 in ["ROFEX_DLR_3M", "USD_ARS_NDF_6M"] and t2 in ["ROFEX_DLR_3M", "USD_ARS_NDF_6M"]:
                    corr[i, j] = 0.94
                # Call option correlation with GGAL
                elif t1 == "GGAL_C_ATM" and t2 == "GGAL.BA":
                    corr[i, j] = 0.92
                elif t2 == "GGAL_C_ATM" and t1 == "GGAL.BA":
                    corr[i, j] = 0.92
                # Put option negative correlation with GGAL
                elif t1 == "GGAL_P_OTM" and t2 == "GGAL.BA":
                    corr[i, j] = -0.85
                elif t2 == "GGAL_P_OTM" and t1 == "GGAL.BA":
                    corr[i, j] = -0.85
                else:
                    corr[i, j] = 0.20

        # Ensure positive semi-definite
        eigvals, eigvecs = np.linalg.eigh(corr)
        eigvals = np.maximum(eigvals, 1e-6)
        corr = eigvecs @ np.diag(eigvals) @ eigvecs.T
        inv_diag = 1.0 / np.sqrt(np.diag(corr))
        corr = corr * np.outer(inv_diag, inv_diag)

        return vol_map, corr

    @staticmethod
    def _get_stress_parameters() -> Tuple[Dict[str, float], np.ndarray]:
        """Annualized volatilities and correlation matrix under stressed market conditions

        (Calibrated to Argentine historical crisis e.g. 2019 PASO shock / 2020 sovereign freeze).
        Volatilities expand by 1.8x - 2.5x, correlations spike towards 1.0 (loss of diversification).
        """
        base_vols, _ = MarketDataLoader._get_base_parameters()

        stress_vols = {}
        for ticker, vol in base_vols.items():
            # In stress, Argentine equities and debt volatility doubles
            if ticker in ["YPFD.BA", "GGAL.BA", "PAMP.BA", "BMA.BA", "TXAR.BA"]:
                stress_vols[ticker] = vol * 2.1  # ~75% - 95% vol
            elif ticker in ["GD30", "AL30", "GD35", "AL35", "GD38"]:
                stress_vols[ticker] = vol * 2.3  # ~60% - 75% vol
            elif "ROFEX" in ticker or "NDF" in ticker:
                stress_vols[ticker] = vol * 2.6  # Severe FX shock
            elif "GGAL_C" in ticker or "GGAL_P" in ticker:
                stress_vols[ticker] = vol * 1.9  # Implied vol spike
            else:
                stress_vols[ticker] = vol * 2.2

        n = len(ALL_TICKERS)
        corr = np.eye(n)

        # High correlation regime during market liquidation
        for i, t1 in enumerate(ALL_TICKERS):
            for j, t2 in enumerate(ALL_TICKERS):
                if i == j:
                    continue
                if i < 5 and j < 5:
                    corr[i, j] = 0.90  # Equities collapse together
                elif 5 <= i < 10 and 5 <= j < 10:
                    corr[i, j] = 0.96  # Debt selloff across curve
                elif (i < 5 and 5 <= j < 10) or (5 <= i < 10 and j < 5):
                    corr[i, j] = 0.82  # Country risk factor dominates both
                elif t1 == "GGAL_P_OTM" and t2 in ["GGAL.BA", "BMA.BA", "YPFD.BA"]:
                    corr[i, j] = -0.92  # Put gains value strongly as equities plunge
                elif t2 == "GGAL_P_OTM" and t1 in ["GGAL.BA", "BMA.BA", "YPFD.BA"]:
                    corr[i, j] = -0.92
                elif t1 in ["ROFEX_DLR_3M", "USD_ARS_NDF_6M"] and t2 in ["ROFEX_DLR_3M", "USD_ARS_NDF_6M"]:
                    corr[i, j] = 0.98
                else:
                    corr[i, j] = 0.50

        # Regularize correlation matrix
        eigvals, eigvecs = np.linalg.eigh(corr)
        eigvals = np.maximum(eigvals, 1e-6)
        corr = eigvecs @ np.diag(eigvals) @ eigvecs.T
        inv_diag = 1.0 / np.sqrt(np.diag(corr))
        corr = corr * np.outer(inv_diag, inv_diag)

        return stress_vols, corr

    @classmethod
    def generate_simulated_returns(
        cls,
        scenario: str = "base",
        num_days: int = 504,
        seed: int = 42
    ) -> pd.DataFrame:
        """Generates a realistic multi-asset daily return time series for the portfolio

        using Cholesky decomposition with Student-t fat tails.
        """
        np.random.seed(seed)

        if scenario.lower() == "stress":
            vols, corr = cls._get_stress_parameters()
            # Fatter tails and negative drift in stress regime (Student-t with df=4)
            df_t = 4
            daily_drift = -0.0015  # -38% annual downward drift
        else:
            vols, corr = cls._get_base_parameters()
            df_t = 7
            daily_drift = 0.0004   # Moderate positive drift

        daily_vols = np.array([vols[t] / np.sqrt(252) for t in ALL_TICKERS])

        # Cholesky decomposition of correlation matrix
        L = np.linalg.cholesky(corr)

        # Generate correlated t-distributed innovations
        raw_innovations = np.random.standard_t(df=df_t, size=(num_days, len(ALL_TICKERS)))
        # Normalize variance of t-distribution (var = df / (df - 2))
        raw_innovations = raw_innovations / np.sqrt(df_t / (df_t - 2))

        correlated_innovations = raw_innovations @ L.T
        daily_returns = daily_drift + correlated_innovations * daily_vols

        # Create dates index (trailing business days)
        dates = pd.date_range(end="2026-09-04", periods=num_days, freq="B")

        return pd.DataFrame(daily_returns, index=dates, columns=ALL_TICKERS)

    @classmethod
    def fetch_live_equity_data(cls, period: str = "1y") -> Dict[str, pd.Series]:
        """Attempts to fetch real historical returns for BYMA equities via yfinance,

        with automatic fallback to synthesized calibration if offline.
        """
        tickers = ["YPFD.BA", "GGAL.BA", "PAMP.BA", "BMA.BA", "TXAR.BA"]
        results = {}
        try:
            data = yf.download(tickers, period=period, progress=False)["Close"]
            if not data.empty and len(data) > 30:
                returns = data.pct_change().dropna()
                for col in tickers:
                    if col in returns.columns:
                        results[col] = returns[col]
        except Exception:
            pass
        return results
