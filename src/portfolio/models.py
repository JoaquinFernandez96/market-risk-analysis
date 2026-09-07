"""Portfolio models, position definitions, and baseline portfolio construction.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
import pandas as pd


class AssetClass(str, Enum):
    EQUITY = "Equity"
    BOND = "Sovereign Bond"
    DERIVATIVE = "Derivative"


@dataclass
class Position:
    ticker: str
    name: str
    asset_class: AssetClass
    quantity: float
    unit_price: float
    market_value: float
    weight: float = 0.0
    currency: str = "USD"
    notional: Optional[float] = None
    details: Dict[str, any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "Ticker": self.ticker,
            "Name": self.name,
            "Asset Class": self.asset_class.value,
            "Quantity": self.quantity,
            "Unit Price ($)": self.unit_price,
            "Market Value ($)": self.market_value,
            "Weight (%)": round(self.weight * 100, 2),
            "Notional ($)": self.notional if self.notional else self.market_value,
            "Currency": self.currency,
        }


@dataclass
class Portfolio:
    name: str
    positions: List[Position]
    base_currency: str = "USD"

    @property
    def total_value(self) -> float:
        return sum(pos.market_value for pos in self.positions)

    def update_weights(self):
        tot = self.total_value
        if tot > 0:
            for p in self.positions:
                p.weight = p.market_value / tot

    def get_positions_by_class(self, asset_class: AssetClass) -> List[Position]:
        return [p for p in self.positions if p.asset_class == asset_class]

    def to_dataframe(self) -> pd.DataFrame:
        self.update_weights()
        return pd.DataFrame([p.to_dict() for p in self.positions])

    def asset_class_summary(self) -> pd.DataFrame:
        self.update_weights()
        df = self.to_dataframe()
        grouped = df.groupby("Asset Class").agg(
            {"Market Value ($)": "sum", "Weight (%)": "sum", "Ticker": "count"}
        ).rename(columns={"Ticker": "Count"}).reset_index()
        return grouped


def create_default_portfolio() -> Portfolio:
    """Creates a realistic $10,000,000 USD institutional trading portfolio

    composed of 5 BYMA equities, 5 Argentine sovereign bonds, and 5 derivatives.
    """
    positions = [
        # --- 5 BYMA EQUITIES (30% = $3,000,000) ---
        Position(
            ticker="YPFD.BA",
            name="YPF S.A. Cl D (BYMA)",
            asset_class=AssetClass.EQUITY,
            quantity=25000,
            unit_price=32.0,
            market_value=800_000.0,
            currency="USD",
            details={"sector": "Energy / Oil & Gas", "adrexchange": "YPF"}
        ),
        Position(
            ticker="GGAL.BA",
            name="Grupo Financiero Galicia (BYMA)",
            asset_class=AssetClass.EQUITY,
            quantity=160000,
            unit_price=5.0,
            market_value=800_000.0,
            currency="USD",
            details={"sector": "Financials / Banking", "adrexchange": "GGAL"}
        ),
        Position(
            ticker="PAMP.BA",
            name="Pampa Energía S.A. (BYMA)",
            asset_class=AssetClass.EQUITY,
            quantity=80000,
            unit_price=6.25,
            market_value=500_000.0,
            currency="USD",
            details={"sector": "Utilities & Power", "adrexchange": "PAM"}
        ),
        Position(
            ticker="BMA.BA",
            name="Banco Macro S.A. (BYMA)",
            asset_class=AssetClass.EQUITY,
            quantity=70000,
            unit_price=7.143,
            market_value=500_000.0,
            currency="USD",
            details={"sector": "Financials / Commercial Banking", "adrexchange": "BMA"}
        ),
        Position(
            ticker="TXAR.BA",
            name="Ternium Argentina S.A. (BYMA)",
            asset_class=AssetClass.EQUITY,
            quantity=400000,
            unit_price=1.00,
            market_value=400_000.0,
            currency="USD",
            details={"sector": "Materials / Steel & Industrial"}
        ),

        # --- 5 ARGENTINE SOVEREIGN BONDS (50% = $5,000,000) ---
        Position(
            ticker="GD30",
            name="Bono Global USD 2030 (NY Law)",
            asset_class=AssetClass.BOND,
            quantity=1_935_484.0,  # Nominal USD
            unit_price=0.620,      # $62.0 per 100 nominal
            market_value=1_200_000.0,
            currency="USD",
            details={
                "maturity": "2030-07-09",
                "coupon": 0.0075,  # Step up coupon schedule
                "ytm": 0.165,      # 16.5% YTM
                "law": "New York",
                "duration": 2.85,
                "modified_duration": 2.63,
                "convexity": 8.92,
                "dv01": 315.6
            }
        ),
        Position(
            ticker="AL30",
            name="Bono Bonar USD 2030 (Local Law)",
            asset_class=AssetClass.BOND,
            quantity=2_068_965.0,
            unit_price=0.580,      # $58.0 per 100 nominal
            market_value=1_200_000.0,
            currency="USD",
            details={
                "maturity": "2030-07-09",
                "coupon": 0.0075,
                "ytm": 0.182,      # 18.2% YTM
                "law": "Argentina",
                "duration": 2.78,
                "modified_duration": 2.56,
                "convexity": 8.50,
                "dv01": 307.2
            }
        ),
        Position(
            ticker="GD35",
            name="Bono Global USD 2035 (NY Law)",
            asset_class=AssetClass.BOND,
            quantity=2_040_816.0,
            unit_price=0.490,      # $49.0 per 100 nominal
            market_value=1_000_000.0,
            currency="USD",
            details={
                "maturity": "2035-07-09",
                "coupon": 0.03625,
                "ytm": 0.158,
                "law": "New York",
                "duration": 5.40,
                "modified_duration": 4.98,
                "convexity": 34.1,
                "dv01": 498.0
            }
        ),
        Position(
            ticker="AL35",
            name="Bono Bonar USD 2035 (Local Law)",
            asset_class=AssetClass.BOND,
            quantity=1_739_130.0,
            unit_price=0.460,      # $46.0 per 100 nominal
            market_value=800_000.0,
            currency="USD",
            details={
                "maturity": "2035-07-09",
                "coupon": 0.03625,
                "ytm": 0.171,
                "law": "Argentina",
                "duration": 5.25,
                "modified_duration": 4.82,
                "convexity": 32.5,
                "dv01": 385.6
            }
        ),
        Position(
            ticker="GD38",
            name="Bono Global USD 2038 (NY Law)",
            asset_class=AssetClass.BOND,
            quantity=1_509_434.0,
            unit_price=0.530,      # $53.0 per 100 nominal
            market_value=800_000.0,
            currency="USD",
            details={
                "maturity": "2038-01-09",
                "coupon": 0.0425,
                "ytm": 0.152,
                "law": "New York",
                "duration": 6.10,
                "modified_duration": 5.58,
                "convexity": 44.8,
                "dv01": 446.4
            }
        ),

        # --- 5 DERIVATIVES (20% = $2,000,000) ---
        Position(
            ticker="ROFEX_DLR_3M",
            name="Matba Rofex USD/ARS 3M Futures (Long)",
            asset_class=AssetClass.DERIVATIVE,
            quantity=1500.0,       # 1,500 contracts ($1,000 each = $1.5M notional)
            unit_price=300.0,      # Initial Margin & MTM per contract ($)
            market_value=450_000.0,
            notional=1_500_000.0,
            currency="USD",
            details={
                "type": "FX Futures",
                "exchange": "Matba Rofex",
                "tenor": "90 Days",
                "delta": 1.0,
                "underlying": "USD/ARS",
                "description": "Long USD hedge contract against ARS depreciation"
            }
        ),
        Position(
            ticker="GGAL_C_ATM",
            name="GGAL 45D Call Option (ATM)",
            asset_class=AssetClass.DERIVATIVE,
            quantity=1600.0,       # 1,600 option contracts
            unit_price=262.50,
            market_value=420_000.0,
            notional=800_000.0,
            currency="USD",
            details={
                "type": "Option - Call",
                "strike": 5.00,
                "expiry_days": 45,
                "iv": 0.65,        # 65% annualized vol
                "delta": 0.54,
                "gamma": 0.082,
                "vega": 980.0,
                "theta": -1250.0,
                "underlying": "GGAL"
            }
        ),
        Position(
            ticker="GGAL_P_OTM",
            name="GGAL 45D Put Option (OTM Protective)",
            asset_class=AssetClass.DERIVATIVE,
            quantity=1600.0,
            unit_price=175.0,
            market_value=280_000.0,
            notional=800_000.0,
            currency="USD",
            details={
                "type": "Option - Put",
                "strike": 4.50,
                "expiry_days": 45,
                "iv": 0.72,        # 72% annualized vol (volatility skew)
                "delta": -0.28,
                "gamma": 0.065,
                "vega": 720.0,
                "theta": -920.0,
                "underlying": "GGAL"
            }
        ),
        Position(
            ticker="USD_ARS_NDF_6M",
            name="OTC USD/ARS Non-Deliverable Forward 6M",
            asset_class=AssetClass.DERIVATIVE,
            quantity=1.0,
            unit_price=450_000.0,
            market_value=450_000.0,
            notional=1_200_000.0,
            currency="USD",
            details={
                "type": "FX NDF (OTC)",
                "counterparty": "Tier 1 Investment Bank",
                "tenor": "180 Days",
                "forward_rate": 1380.0,
                "spot_rate": 1250.0,
                "delta": 0.95,
                "description": "Synthetic long USD / short ARS forward"
            }
        ),
        Position(
            ticker="BADLAR_IRS_1Y",
            name="OTC BADLAR Interest Rate Swap 1Y (Pay Fixed/Rec Float)",
            asset_class=AssetClass.DERIVATIVE,
            quantity=1.0,
            unit_price=400_000.0,
            market_value=400_000.0,
            notional=2_000_000.0,
            currency="USD",
            details={
                "type": "Interest Rate Swap (OTC)",
                "tenor": "1 Year",
                "pay_rate": "40.0% Fixed ARS",
                "receive_rate": "BADLAR + 250 bps Floating",
                "dv01": 185.0,
                "description": "Protection against Argentine monetary rate spikes"
            }
        ),
    ]

    portfolio = Portfolio(name="Trading Portfolio Argentina", positions=positions)
    portfolio.update_weights()
    return portfolio
