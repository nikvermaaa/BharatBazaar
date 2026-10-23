from datetime import date, datetime
from typing import Tuple, Union

def fiscal_period(d: Union[date, datetime, str]) -> Tuple[str, str]:
    """
    Return (fiscal_year, quarter) for an Indian calendar date.
    In India, FY runs from April 1 to March 31.
    FY is named by the END year (e.g. April 2026 - March 2027 is FY27).
    
    Examples:
        fiscal_period(date(2026, 5, 10)) -> ("FY27", "Q1")
        fiscal_period(date(2026, 8, 15)) -> ("FY27", "Q2")
        fiscal_period(date(2026, 11, 20)) -> ("FY27", "Q3")
        fiscal_period(date(2027, 2, 5)) -> ("FY27", "Q4")
        fiscal_period(date(2027, 3, 31)) -> ("FY27", "Q4")
        fiscal_period(date(2027, 4, 1)) -> ("FY28", "Q1")
    """
    if isinstance(d, str):
        # Support formats like YYYY-MM-DD or ISO
        d = datetime.fromisoformat(d[:10]).date()
    elif isinstance(d, datetime):
        d = d.date()

    if d.month >= 4:
        fy = d.year + 1
    else:
        fy = d.year

    quarter_map = {
        4: 1, 5: 1, 6: 1,      # Q1: Apr - Jun
        7: 2, 8: 2, 9: 2,      # Q2: Jul - Sep
        10: 3, 11: 3, 12: 3,   # Q3: Oct - Dec
        1: 4, 2: 4, 3: 4       # Q4: Jan - Mar
    }
    q = quarter_map[d.month]
    return f"FY{str(fy)[-2:]}", f"Q{q}"

def fiscal_period_str(d: Union[date, datetime, str]) -> str:
    fy, q = fiscal_period(d)
    return f"{q} {fy}"
