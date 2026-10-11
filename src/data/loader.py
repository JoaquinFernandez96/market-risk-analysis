"""Market data loader, persistent local disk cache, and hybrid return generation engine.

Provides:
- Persistent local disk caching (`data/cache/market_returns_cache.csv` & `cache_metadata.json`)
  to minimize Yahoo Finance (`yfinance`) API calls to at most once per day (or delta-only when
  new tickers are added to the portfolio).
- Revision-safe full-window atomic column updates (`period="2y", auto_adjust=True`) so retroactive
  stock splits, dividends, and exchange price revisions never create seam discontinuities.
- Hybrid return matrix construction combining empirical historical returns for Equities/CEDEARs
  with granular, calibrated Cholesky/Student-t series for Argentine sovereign bonds, Lecaps/Boncaps,
  Money Market FCIs, and OTC derivatives.
"""
import json
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import yfinance as yf


ALL_TICKERS = [
    # Equities
    "YPFD.BA", "GGAL.BA", "PAMP.BA", "BMA.BA", "TXAR.BA",
    # Sovereign Bonds
    "GD30", "AL30", "GD35", "AL35", "GD38",
    # Derivatives
    "ROFEX_DLR_3M", "GGAL_C_ATM", "GGAL_P_OTM", "USD_ARS_NDF_6M", "BADLAR_IRS_1Y"
]

# Default local cache directory (git-ignored)
DEFAULT_CACHE_DIR = os.path.join("data", "cache")
RETURNS_CACHE_FILENAME = "market_returns_cache.csv"
METADATA_CACHE_FILENAME = "cache_metadata.json"

# Granular annualized volatility priors (USD-equivalent) across asset classes
GRANULAR_VOL_PRIORS: Dict[str, float] = {
    # Core US CEDEARs & Broad ETFs
    "SPY": 0.165,
    "QQQ": 0.210,
    "DIA": 0.155,
    "AAPL": 0.245,
    "GOOGL": 0.265,
    "GOOG": 0.265,
    "V": 0.205,
    "MSFT": 0.235,
    "AMZN": 0.280,
    "KO": 0.145,
    "BRK.B": 0.160,
    "BRK-B": 0.160,
    "JPM": 0.220,
    "WMT": 0.165,
    "PG": 0.150,
    "JNJ": 0.155,
    # High-Beta CEDEARs & Growth / EM
    "ADBE": 0.315,
    "MELI": 0.380,
    "PBR": 0.365,
    "COPX": 0.340,
    "NVDA": 0.450,
    "TSLA": 0.520,
    "META": 0.360,
    "AMD": 0.440,
    "NFLX": 0.350,
    "VIST": 0.400,
    "EWZ": 0.330,
    "ARKK": 0.480,
    "GLOB": 0.370,
    "PAGS": 0.390,
    # Local BYMA Equities
    "YPFD": 0.420,
    "GGAL": 0.460,
    "PAMP": 0.380,
    "BMA": 0.440,
    "TXAR": 0.350,
    "ALUA": 0.340,
    "CEPU": 0.390,
    "TGSU2": 0.375,
    "EDN": 0.450,
    # Argentine Sovereign Bonds, Boncaps, Lecaps & Corporate ONs
    "T15E7": 0.215,
    "T31Y7": 0.230,
    "TX26": 0.210,
    "TX28": 0.225,
    "BOPREAL": 0.165,
    "GD30": 0.280,
    "GD30D": 0.280,
    "AL30": 0.320,
    "AL30D": 0.320,
    "GD35": 0.260,
    "AL35": 0.290,
    "GD38": 0.250,
    "AE38": 0.280,
    "AL29": 0.295,
    "GD29": 0.265,
    "AL41": 0.285,
    "GD41": 0.255,
    "YCA6O": 0.115,
    "TLC1O": 0.110,
    "IRCFO": 0.115,
    "PAMPO": 0.112,
    # Listed & OTC Derivatives
    "ROFEX_DLR_3M": 0.300,
    "GGAL_C_ATM": 0.850,
    "GGAL_P_OTM": 0.950,
    "USD_ARS_NDF_6M": 0.280,
    "BADLAR_IRS_1Y": 0.180,
}

# Argentine equities with liquid US ADRs (mapped to USD ADR to avoid nominal ARS inflation distortion)
ARG_ADR_MAP: Dict[str, str] = {
    "YPFD": "YPF",
    "GGAL": "GGAL",
    "PAMP": "PAM",
    "BMA": "BMA",
    "CEPU": "CEPU",
    "TGSU2": "TGS",
    "EDN": "EDN",
    "LOMA": "LOMA",
    "CRES": "CRESY",
    "BBAR": "BBAR",
    "SUPV": "SUPV",
    "TECO2": "TEO",
    "IRSA": "IRS",
}

# Purely domestic BYMA equities without liquid US ADRs (queried with .BA suffix)
DOMESTIC_BYMA_EQUITIES = {
    "TXAR", "ALUA", "BYMA", "VALO", "COME", "MIRG", "TRAN", "METR", "TGNO4",
    "CVH", "AGRO", "BHIP", "BOLT", "CAPX", "CARC", "CELU", "CGPA2", "CTIO",
    "DGCE", "DGCU2", "DYCA", "FERR", "FIPL", "GAMI", "GARO", "GBAN", "GCLA",
    "GRIM", "HARG", "HAVA", "INTR", "INVJ", "LEDE", "LONG", "MOLA", "MOLI",
    "MORI", "OEST", "PATA", "POLL", "RICH", "RIGO", "ROSE", "SAMI", "SEMI",
}


class MarketDataLoader:
    """Provides daily returns and correlation structures for portfolio assets
    under both Base and Stressed market regimes, backed by a persistent local disk cache.
    """

    @staticmethod
    def _strip_ba(ticker: str) -> str:
        t = str(ticker).strip().upper()
        return t[:-3] if t.endswith(".BA") else t

    @classmethod
    def is_cash_or_fci(cls, ticker: str) -> bool:
        t_upper = str(ticker).strip().upper()
        return any(
            c in t_upper
            for c in ["CASH", "CAUCION", "LIQUID", "FCI", "COCOS", "MONEY", "FBA", "SBS"]
        )

    @classmethod
    def is_bond_or_fixed_income(cls, ticker: str) -> bool:
        t_upper = str(ticker).strip().upper()
        base_t = cls._strip_ba(t_upper)
        if base_t in {
            "GD30", "GD30D", "AL30", "AL30D", "GD35", "AL35", "GD38", "AE38",
            "AL29", "GD29", "AL41", "GD41", "T15E7", "T31Y7", "TX26", "TX28",
            "BOPREAL", "YCA6O", "TLC1O", "IRCFO", "PAMPO",
        }:
            return True
        return any(
            b in t_upper
            for b in ["GD3", "GD4", "AL2", "AL3", "AL4", "TX2", "AE3", "T2V", "BON", "T15", "T31", "BOP", "LECAP", "BONCAP"]
        )

    @classmethod
    def is_derivative(cls, ticker: str) -> bool:
        t_upper = str(ticker).strip().upper()
        return any(
            d in t_upper
            for d in ["ROFEX", "NDF", "IRS", "BADLAR", "_C_ATM", "_P_OTM", "OPTION", "FUTURE"]
        )

    @classmethod
    def map_to_yahoo_symbol(cls, ticker: str) -> Optional[str]:
        """Maps a portfolio ticker to its optimal Yahoo Finance symbol for USD risk modeling,
        or returns None for local bonds, Lecaps/Boncaps, Money Market FCIs, and OTC derivatives.
        """
        if cls.is_cash_or_fci(ticker) or cls.is_bond_or_fixed_income(ticker) or cls.is_derivative(ticker):
            return None

        base_t = cls._strip_ba(ticker)
        if not base_t:
            return None

        if base_t in ARG_ADR_MAP:
            return ARG_ADR_MAP[base_t]
        if base_t in DOMESTIC_BYMA_EQUITIES:
            return f"{base_t}.BA"

        # Standard US CEDEAR / global equity ticker (e.g. BRK.B -> BRK-B, SPY.BA -> SPY)
        return base_t.replace(".", "-")

    @classmethod
    def get_ticker_prior_vol(cls, ticker: str, scenario: str = "base") -> float:
        """Returns the granular annualized volatility prior for any ticker under Base or Stress."""
        t_upper = str(ticker).strip().upper()
        base_t = cls._strip_ba(t_upper)

        if cls.is_cash_or_fci(t_upper):
            return 0.0001

        # Direct lookup in granular dictionary
        vol = GRANULAR_VOL_PRIORS.get(t_upper) or GRANULAR_VOL_PRIORS.get(base_t)
        if vol is None and len(base_t) >= 5 and base_t[-1] in ("D", "C"):
            vol = GRANULAR_VOL_PRIORS.get(base_t[:-1])

        if vol is None:
            if any(o in t_upper for o in ["YCA6O", "TLC1O", "IRCFO", "PAMPO", "ON"]):
                vol = 0.14
            elif cls.is_bond_or_fixed_income(t_upper):
                vol = 0.28
            elif t_upper.endswith(".BA") or base_t in DOMESTIC_BYMA_EQUITIES or base_t in ARG_ADR_MAP:
                vol = 0.42
            else:
                # Default unrecognized US/global equity
                vol = 0.28

        if scenario.lower() != "stress":
            return float(vol)

        # Stress regime multiplier calibrated by asset class
        if t_upper in ["YPFD.BA", "GGAL.BA", "PAMP.BA", "BMA.BA", "TXAR.BA"] or base_t in ARG_ADR_MAP or base_t in DOMESTIC_BYMA_EQUITIES:
            return float(vol * 2.1)
        elif cls.is_bond_or_fixed_income(t_upper):
            return float(vol * 2.3)
        elif "ROFEX" in t_upper or "NDF" in t_upper:
            return float(vol * 2.6)
        elif "GGAL_C" in t_upper or "GGAL_P" in t_upper:
            return float(vol * 1.9)
        elif base_t in GRANULAR_VOL_PRIORS:
            # US CEDEARs expand by ~1.85x under global/local stress
            return float(vol * 1.85)
        return float(vol * 2.1)

    @staticmethod
    def _get_base_parameters() -> Tuple[Dict[str, float], np.ndarray]:
        """Annualized volatilities and correlation matrix under standard/base Argentine market conditions."""
        vol_map = {
            "YPFD.BA": 0.42,
            "GGAL.BA": 0.46,
            "PAMP.BA": 0.38,
            "BMA.BA": 0.44,
            "TXAR.BA": 0.35,
            "GD30": 0.28,
            "AL30": 0.32,
            "GD35": 0.26,
            "AL35": 0.29,
            "GD38": 0.25,
            "ROFEX_DLR_3M": 0.30,
            "GGAL_C_ATM": 0.85,
            "GGAL_P_OTM": 0.95,
            "USD_ARS_NDF_6M": 0.28,
            "BADLAR_IRS_1Y": 0.18,
        }

        n = len(ALL_TICKERS)
        corr = np.eye(n)

        for i, t1 in enumerate(ALL_TICKERS):
            for j, t2 in enumerate(ALL_TICKERS):
                if i == j:
                    continue
                if i < 5 and j < 5:
                    corr[i, j] = 0.72
                elif 5 <= i < 10 and 5 <= j < 10:
                    corr[i, j] = 0.88
                elif (i < 5 and 5 <= j < 10) or (5 <= i < 10 and j < 5):
                    corr[i, j] = 0.48
                elif t1 in ["ROFEX_DLR_3M", "USD_ARS_NDF_6M"] and t2 in ["ROFEX_DLR_3M", "USD_ARS_NDF_6M"]:
                    corr[i, j] = 0.94
                elif (t1 == "GGAL_C_ATM" and t2 == "GGAL.BA") or (t2 == "GGAL_C_ATM" and t1 == "GGAL.BA"):
                    corr[i, j] = 0.92
                elif (t1 == "GGAL_P_OTM" and t2 == "GGAL.BA") or (t2 == "GGAL_P_OTM" and t1 == "GGAL.BA"):
                    corr[i, j] = -0.85
                else:
                    corr[i, j] = 0.20

        eigvals, eigvecs = np.linalg.eigh(corr)
        eigvals = np.maximum(eigvals, 1e-6)
        corr = eigvecs @ np.diag(eigvals) @ eigvecs.T
        inv_diag = 1.0 / np.sqrt(np.diag(corr))
        corr = corr * np.outer(inv_diag, inv_diag)

        return vol_map, corr

    @staticmethod
    def _get_stress_parameters() -> Tuple[Dict[str, float], np.ndarray]:
        """Annualized volatilities and correlation matrix under stressed market conditions."""
        base_vols, _ = MarketDataLoader._get_base_parameters()

        stress_vols = {}
        for ticker, vol in base_vols.items():
            if ticker in ["YPFD.BA", "GGAL.BA", "PAMP.BA", "BMA.BA", "TXAR.BA"]:
                stress_vols[ticker] = vol * 2.1
            elif ticker in ["GD30", "AL30", "GD35", "AL35", "GD38"]:
                stress_vols[ticker] = vol * 2.3
            elif "ROFEX" in ticker or "NDF" in ticker:
                stress_vols[ticker] = vol * 2.6
            elif "GGAL_C" in ticker or "GGAL_P" in ticker:
                stress_vols[ticker] = vol * 1.9
            else:
                stress_vols[ticker] = vol * 2.2

        n = len(ALL_TICKERS)
        corr = np.eye(n)

        for i, t1 in enumerate(ALL_TICKERS):
            for j, t2 in enumerate(ALL_TICKERS):
                if i == j:
                    continue
                if i < 5 and j < 5:
                    corr[i, j] = 0.90
                elif 5 <= i < 10 and 5 <= j < 10:
                    corr[i, j] = 0.96
                elif (i < 5 and 5 <= j < 10) or (5 <= i < 10 and j < 5):
                    corr[i, j] = 0.82
                elif (t1 == "GGAL_P_OTM" and t2 in ["GGAL.BA", "BMA.BA", "YPFD.BA"]) or (
                    t2 == "GGAL_P_OTM" and t1 in ["GGAL.BA", "BMA.BA", "YPFD.BA"]
                ):
                    corr[i, j] = -0.92
                elif t1 in ["ROFEX_DLR_3M", "USD_ARS_NDF_6M"] and t2 in ["ROFEX_DLR_3M", "USD_ARS_NDF_6M"]:
                    corr[i, j] = 0.98
                else:
                    corr[i, j] = 0.50

        eigvals, eigvecs = np.linalg.eigh(corr)
        eigvals = np.maximum(eigvals, 1e-6)
        corr = eigvecs @ np.diag(eigvals) @ eigvecs.T
        inv_diag = 1.0 / np.sqrt(np.diag(corr))
        corr = corr * np.outer(inv_diag, inv_diag)

        return stress_vols, corr

    @classmethod
    def _pairwise_prior_correlation(cls, t1: str, t2: str, scenario: str, base_corr: np.ndarray) -> float:
        """Computes structured pairwise correlation between any two portfolio tickers."""
        if t1 == t2:
            return 1.0
        if cls.is_cash_or_fci(t1) or cls.is_cash_or_fci(t2):
            return 0.0
        if t1 in ALL_TICKERS and t2 in ALL_TICKERS:
            return float(base_corr[ALL_TICKERS.index(t1), ALL_TICKERS.index(t2)])

        is_stress = scenario.lower() == "stress"
        b1, b2 = cls._strip_ba(t1), cls._strip_ba(t2)

        # Put option hedge correlation against equities
        if "GGAL_P" in (t1, t2) and (b1 in ARG_ADR_MAP or b2 in ARG_ADR_MAP):
            return -0.92 if is_stress else -0.85

        bond1, bond2 = cls.is_bond_or_fixed_income(t1), cls.is_bond_or_fixed_income(t2)
        arg1 = b1 in ARG_ADR_MAP or b1 in DOMESTIC_BYMA_EQUITIES or t1.endswith(".BA") and b1 not in GRANULAR_VOL_PRIORS
        arg2 = b2 in ARG_ADR_MAP or b2 in DOMESTIC_BYMA_EQUITIES or t2.endswith(".BA") and b2 not in GRANULAR_VOL_PRIORS

        if bond1 and bond2:
            return 0.92 if is_stress else 0.85
        if arg1 and arg2:
            return 0.88 if is_stress else 0.72
        if (bond1 and arg2) or (bond2 and arg1):
            return 0.80 if is_stress else 0.48
        if bond1 or bond2:
            # US CEDEAR vs Argentine Bond
            return 0.55 if is_stress else 0.22

        # Both are US CEDEARs / Global Equities
        us_core_tech = {"SPY", "QQQ", "AAPL", "GOOGL", "GOOG", "MSFT", "V", "ADBE", "NVDA", "META", "AMZN"}
        if {b1, b2} == {"SPY", "QQQ"}:
            return 0.94 if is_stress else 0.88
        if b1 in us_core_tech and b2 in us_core_tech:
            return 0.84 if is_stress else 0.68
        return 0.75 if is_stress else 0.52

    # ==========================================================================
    # PERSISTENT LOCAL DISK CACHE MANAGEMENT
    # ==========================================================================

    @classmethod
    def _get_cache_paths(cls, cache_dir: Optional[str] = None) -> Tuple[str, str, str]:
        c_dir = cache_dir or DEFAULT_CACHE_DIR
        ret_path = os.path.join(c_dir, RETURNS_CACHE_FILENAME)
        meta_path = os.path.join(c_dir, METADATA_CACHE_FILENAME)
        return c_dir, ret_path, meta_path

    @classmethod
    def load_cache_from_disk(
        cls, cache_dir: Optional[str] = None
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Reads cached historical daily returns and metadata from local disk."""
        _, ret_path, meta_path = cls._get_cache_paths(cache_dir)
        meta: Dict[str, Any] = {"last_sync_date": None, "last_sync_timestamp": None, "tickers": {}}
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    loaded_meta = json.load(f)
                    if isinstance(loaded_meta, dict):
                        meta.update(loaded_meta)
            except Exception:
                pass

        if os.path.exists(ret_path):
            try:
                df = pd.read_csv(ret_path, index_col=0, parse_dates=True)
                if not df.empty:
                    df.index = pd.to_datetime(df.index).tz_localize(None)
                    df = df.sort_index()
                    return df, meta
            except Exception:
                pass

        return pd.DataFrame(), meta

    @classmethod
    def _save_cache_to_disk(
        cls,
        df: pd.DataFrame,
        meta: Dict[str, Any],
        cache_dir: Optional[str] = None
    ) -> None:
        """Atomically writes updated historical returns and metadata to local disk."""
        c_dir, ret_path, meta_path = cls._get_cache_paths(cache_dir)
        try:
            os.makedirs(c_dir, exist_ok=True)
            tmp_ret = f"{ret_path}.tmp"
            tmp_meta = f"{meta_path}.tmp"

            df_to_save = df.sort_index().tail(600).round(6)
            df_to_save.index.name = "Date"
            df_to_save.to_csv(tmp_ret)
            os.replace(tmp_ret, ret_path)

            with open(tmp_meta, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
            os.replace(tmp_meta, meta_path)
        except Exception:
            # Defend against Windows file locks if user has the CSV open in Excel
            pass

    @classmethod
    def _download_yahoo_returns_batch(
        cls,
        yf_symbols: List[str],
        period: str = "2y"
    ) -> Dict[str, pd.Series]:
        """Fetches full 2-year split- and dividend-adjusted closes (`auto_adjust=True`)
        in a single batched request and computes cleaned daily returns.
        """
        if not yf_symbols:
            return {}

        unique_syms = sorted(list(set(yf_symbols)))
        fetched: Dict[str, pd.Series] = {}
        try:
            raw = yf.download(
                unique_syms,
                period=period,
                interval="1d",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if raw is None or raw.empty:
                return {}

            close_df = raw["Close"] if "Close" in raw else raw
            if isinstance(close_df, pd.Series):
                close_df = close_df.to_frame(name=unique_syms[0])

            close_df.index = pd.to_datetime(close_df.index).tz_localize(None)
            close_df = close_df.sort_index()

            for sym in unique_syms:
                if sym in close_df.columns:
                    s = close_df[sym].dropna()
                    if len(s) >= 30:
                        ret = s.pct_change().dropna()
                        # Guard against unadjusted corporate action / CEDEAR ratio seams
                        ret = ret.clip(lower=-0.35, upper=0.35)
                        fetched[sym] = ret
        except Exception:
            pass

        return fetched

    @classmethod
    def sync_local_cache(
        cls,
        portfolio_tickers: List[str],
        force_refresh: bool = False,
        cache_dir: Optional[str] = None
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Ensures local disk cache has up-to-date 2-year adjusted returns for all Yahoo-eligible
        portfolio tickers.

        - Makes 0 API calls if all required tickers were already synced today.
        - Makes only a delta call for missing tickers if a new stock was added today.
        - Overwrites the full 2-year column per fetched ticker so retroactive splits, dividends,
          and price revisions are seamlessly applied without boundary jumps.
        """
        cached_df, meta = cls.load_cache_from_disk(cache_dir=cache_dir)
        today_str = date.today().isoformat()
        ticker_dates: Dict[str, str] = meta.get("tickers", {})

        # Map portfolio tickers to Yahoo symbols
        sym_map: Dict[str, str] = {}
        for t in portfolio_tickers:
            yf_sym = cls.map_to_yahoo_symbol(t)
            if yf_sym:
                sym_map[t] = yf_sym

        required_yf_syms = sorted(list(set(sym_map.values())))
        if not required_yf_syms:
            return cached_df, meta

        if force_refresh:
            syms_to_fetch = required_yf_syms
        else:
            syms_to_fetch = [
                sym for sym in required_yf_syms
                if sym not in cached_df.columns
                or cached_df[sym].dropna().shape[0] < 30
                or ticker_dates.get(sym) != today_str
            ]

        if not syms_to_fetch:
            return cached_df, meta

        fetched_map = cls._download_yahoo_returns_batch(syms_to_fetch, period="2y")

        # Fallback: if any new ticker without .BA failed, try with .BA suffix on BYMA
        missing_after_first = [s for s in syms_to_fetch if s not in fetched_map and not s.endswith(".BA")]
        if missing_after_first:
            ba_candidates = [f"{s}.BA" for s in missing_after_first]
            ba_fetched = cls._download_yahoo_returns_batch(ba_candidates, period="2y")
            for orig_sym in missing_after_first:
                ba_sym = f"{orig_sym}.BA"
                if ba_sym in ba_fetched:
                    fetched_map[orig_sym] = ba_fetched[ba_sym]

        if fetched_map:
            new_df = pd.DataFrame(fetched_map)
            new_df.index = pd.to_datetime(new_df.index).tz_localize(None)

            if cached_df.empty:
                cached_df = new_df
            else:
                # Union index and atomically overwrite updated columns across the full 2Y window
                combined_index = cached_df.index.union(new_df.index).sort_values()
                cached_df = cached_df.reindex(combined_index)
                for sym, series in fetched_map.items():
                    cached_df[sym] = series.reindex(combined_index)

            # Drop rows where all tickers are NaN (e.g. non-trading holidays)
            cached_df = cached_df.dropna(how="all").tail(600)

            for sym in fetched_map:
                ticker_dates[sym] = today_str

            meta["tickers"] = ticker_dates
            meta["last_sync_date"] = today_str
            meta["last_sync_timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cls._save_cache_to_disk(cached_df, meta, cache_dir=cache_dir)

        return cached_df, meta

    @classmethod
    def get_cache_status(
        cls,
        portfolio_tickers: Optional[List[str]] = None,
        cache_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """Returns diagnostic metadata about the local market data cache for UI display."""
        cached_df, meta = cls.load_cache_from_disk(cache_dir=cache_dir)
        today_str = date.today().isoformat()
        ticker_dates = meta.get("tickers", {})

        mapped_syms = []
        if portfolio_tickers:
            for t in portfolio_tickers:
                s = cls.map_to_yahoo_symbol(t)
                if s:
                    mapped_syms.append(s)

        cached_portfolio_syms = [s for s in set(mapped_syms) if s in cached_df.columns]
        all_synced_today = bool(
            mapped_syms
            and all(ticker_dates.get(s) == today_str and s in cached_df.columns for s in set(mapped_syms))
        )

        return {
            "has_cache_file": not cached_df.empty,
            "last_sync_date": meta.get("last_sync_date") or "Never",
            "last_sync_timestamp": meta.get("last_sync_timestamp") or "Never",
            "total_cached_tickers": len(cached_df.columns),
            "cached_days": len(cached_df),
            "portfolio_yahoo_eligible": len(set(mapped_syms)),
            "portfolio_cached_count": len(cached_portfolio_syms),
            "is_fresh_today": all_synced_today,
        }

    # ==========================================================================
    # RETURN SERIES GENERATION (HYBRID EMPIRICAL + CHOLESKY)
    # ==========================================================================

    @classmethod
    def generate_simulated_returns(
        cls,
        scenario: str = "base",
        tickers: List[str] = None,
        num_days: int = 504,
        seed: int = 42,
        use_live_cache: bool = False,
        force_refresh: bool = False,
        cache_dir: Optional[str] = None,
    ) -> pd.DataFrame:
        """Generates a multi-asset daily return time series (504 trading days).

        - When `use_live_cache=False` (or for non-Yahoo instruments / offline fallback):
          Uses granular per-ticker volatilities and structured correlation matrices via
          Cholesky decomposition with Student-t fat tails.
        - When `use_live_cache=True`:
          Syncs/reads real 2-year split-adjusted daily returns from the persistent local disk cache
          (`data/cache/market_returns_cache.csv`), blending empirical equity/CEDEAR returns in Base
          and calibrating Stressed VaR above empirical volatility.
        """
        np.random.seed(seed)
        active_tickers = tickers if tickers is not None else ALL_TICKERS
        is_stress = scenario.lower() == "stress"

        if is_stress:
            _, base_corr = cls._get_stress_parameters()
            df_t = 4
            daily_drift = -0.0015
        else:
            _, base_corr = cls._get_base_parameters()
            df_t = 7
            daily_drift = 0.0004

        cached_df = pd.DataFrame()
        if use_live_cache:
            cached_df, _ = cls.sync_local_cache(
                active_tickers, force_refresh=force_refresh, cache_dir=cache_dir
            )

        n = len(active_tickers)
        vols_list: List[float] = []
        is_cash: List[bool] = []

        for t in active_tickers:
            cash_flag = cls.is_cash_or_fci(t)
            is_cash.append(cash_flag)
            prior_vol = cls.get_ticker_prior_vol(t, scenario=scenario)

            # In Stress mode with live cache, ensure stressed vol scales above any higher empirical vol
            if is_stress and use_live_cache and not cached_df.empty and not cash_flag:
                yf_sym = cls.map_to_yahoo_symbol(t)
                if yf_sym and yf_sym in cached_df.columns:
                    emp_s = cached_df[yf_sym].dropna().tail(num_days)
                    if len(emp_s) >= 60:
                        emp_ann_vol = float(emp_s.std() * np.sqrt(252))
                        prior_vol = max(prior_vol, emp_ann_vol * 1.95)

            vols_list.append(prior_vol)

        daily_vols = np.array([v / np.sqrt(252) for v in vols_list])

        # Build structured correlation matrix
        corr = np.eye(n)
        for i, t1 in enumerate(active_tickers):
            for j, t2 in enumerate(active_tickers):
                if i == j:
                    continue
                if is_cash[i] or is_cash[j]:
                    corr[i, j] = 0.0
                else:
                    corr[i, j] = cls._pairwise_prior_correlation(t1, t2, scenario, base_corr)

        # Ensure positive semi-definite correlation matrix
        eigvals, eigvecs = np.linalg.eigh(corr)
        eigvals = np.maximum(eigvals, 1e-6)
        corr = eigvecs @ np.diag(eigvals) @ eigvecs.T
        inv_diag = 1.0 / np.sqrt(np.diag(corr))
        corr = corr * np.outer(inv_diag, inv_diag)

        L = np.linalg.cholesky(corr)

        raw_innovations = np.random.standard_t(df=df_t, size=(num_days, n))
        raw_innovations = raw_innovations / np.sqrt(df_t / (df_t - 2))

        correlated_innovations = raw_innovations @ L.T
        daily_returns = daily_drift + correlated_innovations * daily_vols

        dates = pd.date_range(end="2026-09-04", periods=num_days, freq="B")
        sim_df = pd.DataFrame(daily_returns, index=dates, columns=active_tickers)

        # Overlay real empirical historical returns in Base scenario when local cache is enabled
        if use_live_cache and not is_stress and not cached_df.empty:
            tail_cache = cached_df.tail(num_days)
            if len(tail_cache) >= 60:
                # If we have full num_days in cache, adopt real trading dates
                if len(tail_cache) == num_days:
                    sim_df.index = tail_cache.index

                for idx_t, t in enumerate(active_tickers):
                    yf_sym = cls.map_to_yahoo_symbol(t)
                    if yf_sym and yf_sym in tail_cache.columns:
                        emp_series = tail_cache[yf_sym].dropna()
                        if len(emp_series) >= 60:
                            k = min(len(emp_series), num_days)
                            sim_df.iloc[-k:, idx_t] = emp_series.values[-k:]

                # Keep GGAL option hedges correlated with empirical GGAL.BA moves on the same dates
                if "GGAL.BA" in sim_df.columns:
                    ggal_ret = sim_df["GGAL.BA"].values
                    ggal_std = float(np.std(ggal_ret))
                    if ggal_std > 1e-6:
                        z_ggal = (ggal_ret - float(np.mean(ggal_ret))) / ggal_std
                        for opt_t, rho_opt in [("GGAL_C_ATM", 0.92), ("GGAL_P_OTM", -0.85)]:
                            if opt_t in sim_df.columns:
                                opt_idx = active_tickers.index(opt_t)
                                idio = raw_innovations[:, opt_idx]
                                comb_z = rho_opt * z_ggal + np.sqrt(1.0 - rho_opt**2) * idio
                                sim_df[opt_t] = daily_drift + comb_z * daily_vols[opt_idx]

        return sim_df

    @classmethod
    def fetch_live_equity_data(cls, period: str = "1y") -> Dict[str, pd.Series]:
        """Fetches historical returns for core BYMA equities via the persistent local cache."""
        tickers = ["YPFD.BA", "GGAL.BA", "PAMP.BA", "BMA.BA", "TXAR.BA"]
        cached_df, _ = cls.sync_local_cache(tickers)
        results: Dict[str, pd.Series] = {}
        for t in tickers:
            yf_sym = cls.map_to_yahoo_symbol(t)
            if yf_sym and yf_sym in cached_df.columns:
                s = cached_df[yf_sym].dropna()
                if len(s) > 30:
                    results[t] = s.tail(252)
        return results
