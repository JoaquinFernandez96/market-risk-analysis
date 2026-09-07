"""Script to generate a formatted master input Excel template (input.xlsx)

for monthly portfolio updates.
"""
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


def build_template():
    wb = openpyxl.Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    # Styles
    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10)
    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    # -------------------------------------------------------------
    # TAB 1: EQUITIES
    # -------------------------------------------------------------
    ws_eq = wb.create_sheet(title="Equities")
    eq_headers = ["Ticker", "Name", "Quantity", "Unit_Price_USD", "Market_Value_USD", "Sector", "ADR_Ticker", "Beta"]
    ws_eq.append(eq_headers)

    eq_rows = [
        ["YPFD.BA", "YPF S.A. Cl D (BYMA)", 25000, 32.0, 800000.0, "Energy / Oil & Gas", "YPF", 1.05],
        ["GGAL.BA", "Grupo Financiero Galicia (BYMA)", 160000, 5.0, 800000.0, "Financials / Banking", "GGAL", 1.18],
        ["PAMP.BA", "Pampa Energía S.A. (BYMA)", 80000, 6.25, 500000.0, "Utilities & Power", "PAM", 0.95],
        ["BMA.BA", "Banco Macro S.A. (BYMA)", 70000, 7.142857, 500000.0, "Financials / Commercial Banking", "BMA", 1.15],
        ["TXAR.BA", "Ternium Argentina S.A. (BYMA)", 400000, 1.0, 400000.0, "Materials / Steel & Industrial", "", 0.88],
    ]
    for r in eq_rows:
        ws_eq.append(r)

    # -------------------------------------------------------------
    # TAB 2: SOVEREIGN BONDS
    # -------------------------------------------------------------
    ws_bonds = wb.create_sheet(title="Bonds")
    bond_headers = [
        "Ticker", "Name", "Governing_Law", "Nominal_Quantity", "Clean_Price_USD",
        "Market_Value_USD", "Maturity_Date", "Maturity_Years", "Coupon_Rate",
        "YTM", "Modified_Duration", "Convexity", "DV01"
    ]
    ws_bonds.append(bond_headers)

    bond_rows = [
        ["GD30", "Global USD 2030 (NY Law)", "New York", 1935484.0, 0.62, 1200000.0, "2030-07-09", 4.5, 0.0075, 0.165, 2.63, 8.92, 315.6],
        ["AL30", "Bonar USD 2030 (Local Law)", "Argentina", 2068965.0, 0.58, 1200000.0, "2030-07-09", 4.5, 0.0075, 0.182, 2.56, 8.50, 307.2],
        ["GD35", "Global USD 2035 (NY Law)", "New York", 2040816.0, 0.49, 1000000.0, "2035-07-09", 9.5, 0.03625, 0.158, 4.98, 34.1, 498.0],
        ["AL35", "Bonar USD 2035 (Local Law)", "Argentina", 1739130.0, 0.46, 800000.0, "2035-07-09", 9.5, 0.03625, 0.171, 4.82, 32.5, 385.6],
        ["GD38", "Global USD 2038 (NY Law)", "New York", 1509434.0, 0.53, 800000.0, "2038-01-09", 12.0, 0.0425, 0.152, 5.58, 44.8, 446.4],
    ]
    for r in bond_rows:
        ws_bonds.append(r)

    # -------------------------------------------------------------
    # TAB 3: DERIVATIVES
    # -------------------------------------------------------------
    ws_deriv = wb.create_sheet(title="Derivatives")
    deriv_headers = [
        "Identifier", "Name", "Type", "Quantity_Contracts", "Unit_Price_USD",
        "Market_Value_USD", "Notional_USD", "Underlying", "Delta", "Gamma", "Vega", "Theta", "DV01", "Description"
    ]
    ws_deriv.append(deriv_headers)

    deriv_rows = [
        ["ROFEX_DLR_3M", "Matba Rofex USD/ARS 3M Futures (Long)", "FX Futures", 1500.0, 300.0, 450000.0, 1500000.0, "USD/ARS", 1.0, 0.0, 0.0, 0.0, 0.0, "Long USD hedge contract against ARS depreciation"],
        ["GGAL_C_ATM", "GGAL 45D Call Option (ATM)", "Option - Call", 1600.0, 262.50, 420000.0, 800000.0, "GGAL", 0.54, 0.082, 980.0, -1250.0, 0.0, "Call Option ATM 45 days strike $5.00"],
        ["GGAL_P_OTM", "GGAL 45D Put Option (OTM Protective)", "Option - Put", 1600.0, 175.0, 280000.0, 800000.0, "GGAL", -0.28, 0.065, 720.0, -920.0, 0.0, "Protective Put OTM strike $4.50"],
        ["USD_ARS_NDF_6M", "OTC USD/ARS Non-Deliverable Forward 6M", "FX NDF (OTC)", 1.0, 450000.0, 450000.0, 1200000.0, "USD/ARS", 0.95, 0.0, 0.0, -85.0, -120.0, "Synthetic long USD / short ARS forward"],
        ["BADLAR_IRS_1Y", "OTC BADLAR Interest Rate Swap 1Y", "Interest Rate Swap", 1.0, 400000.0, 400000.0, 2000000.0, "BADLAR", 0.0, 0.0, 0.0, 0.0, 185.0, "Pay Fixed 40% / Receive Floating BADLAR"],
    ]
    for r in deriv_rows:
        ws_deriv.append(r)

    # -------------------------------------------------------------
    # TAB 4: SETTINGS
    # -------------------------------------------------------------
    ws_set = wb.create_sheet(title="Settings")
    ws_set.append(["Parameter", "Value", "Description"])
    settings_rows = [
        ["Portfolio_Name", "Trading Portfolio Argentina", "Display name of portfolio"],
        ["USD_ARS_CCL_Rate", 1280.0, "CCL exchange rate for USD/ARS conversion"],
        ["Default_Confidence_Level", 0.95, "Baseline VaR confidence interval (e.g. 0.95, 0.99)"],
        ["Default_Holding_Period_Days", 1, "Holding period horizon in trading days"],
        ["Stress_Vol_Multiplier", 2.2, "Volatility scaling factor under stressed regime"],
        ["Stress_Correlation_Spike", 0.90, "Correlation convergence level during market stress"],
        ["Reporting_Month", "September 2026", "Monthly reporting cycle label"],
    ]
    for r in settings_rows:
        ws_set.append(r)

    # Apply styling & auto-fit columns to all sheets
    for sheet in wb.worksheets:
        sheet.views.sheetView[0].showGridLines = True
        for col_idx, col in enumerate(sheet.iter_cols(values_only=False), start=1):
            max_len = 0
            for row_idx, cell in enumerate(col, start=1):
                cell.font = data_font
                cell.border = thin_border
                if row_idx == 1:
                    cell.fill = header_fill
                    cell.font = header_font
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                val_str = str(cell.value or "")
                max_len = max(max_len, len(val_str))
            col_letter = get_column_letter(col_idx)
            sheet.column_dimensions[col_letter].width = max(max_len + 4, 12)

    wb.save("input.xlsx")
    print("Master input template successfully generated at input.xlsx")


if __name__ == "__main__":
    build_template()
