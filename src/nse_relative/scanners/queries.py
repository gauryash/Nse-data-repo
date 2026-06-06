"""
Chartink scan clauses (queries).

Each query is a string that the Chartink screener API understands.
"""

# Monthly RSI(2) <= 10
QUERY_MONTHLY_RSI_2 = (
    "({1090574} ( monthly rsi( 2 ) <= 10 ) )"
)

# Monthly close within 95-99% of 120-month high (near ATH)
QUERY_MONTHLY_ATH = (
    "({1090574} ( monthly close / monthly max( 120 , monthly high ) >= 0.95 "
    "and monthly close / monthly max( 120 , monthly high ) <= 0.99 ))"
)

# Stock near 75% of 52-week high with EMA and volume filters
QUERY_NEAR_52W_HIGH = (
    "( {cash} ( latest close >= latest max( 252 , latest high ) * .75 "
    "and latest close / 65 days ago close > 1 "
    "and latest close > 20 "
    "and latest ema( latest close , 20 ) > latest ema( latest close , 50 ) "
    "and latest close > latest ema( latest close , 50 ) "
    "and latest volume > 50000 ) )"
)

# Potential breakouts: price within 5% of 200-day high, recent consolidation
QUERY_POTENTIAL_BREAKOUTS = (
    "({cash}(latest close * 1.05 > latest max( 200 , latest high ) "
    "and latest max( 30 , latest high ) <= 30 days ago max( 200 , latest high ) "
    "and latest volume > latest sma( volume,50 ) "
    "and latest close > 90))"
)

# 3-4 week tight close pattern (low volatility consolidation)
QUERY_TIGHT_CLOSE = (
    "( {cash} ( weekly close <= 1 week ago close * 1.015 "
    "and weekly close >= 1 week ago close * .985 "
    "and weekly close <= 2 weeks ago close * 1.015 "
    "and weekly close >= 2 weeks ago close * .985 "
    "and weekly close <= 3 weeks ago close * 1.015 "
    "and weekly close >= 3 weeks ago close * .985 "
    "and weekly high <= 4 weeks ago high * 1.015 "
    "and weekly low >= 4 weeks ago low * .985 "
    "and market cap >= 100 ) )"
)

# Fundamentally strong stocks with consistent 5-year profit growth, near EMA
QUERY_FUNDAMENTALLY_STRONG = (
    "( {1090574} ( yearly net profit/reported profit after tax "
    "> 1 year ago net profit/reported profit after tax "
    "and 1 year ago net profit/reported profit after tax "
    "> 2 years ago net profit/reported profit after tax "
    "and 2 years ago net profit/reported profit after tax "
    "> 3 years ago net profit/reported profit after tax "
    "and 3 years ago net profit/reported profit after tax "
    "> 4 years ago net profit/reported profit after tax "
    "and monthly close >= monthly ema( close,21 ) * .98 "
    "and monthly close <= monthly ema( close,21 ) * 1.02 "
    "and monthly ema( close,21 ) >= monthly ema( close,50 ) * 1.05 ) )"
)

# 5-minute intraday volume burst scanner
# Note: [=1] = current bar, [=-75] = 75 bars ago (valid Chartink bar-index syntax)
QUERY_5MIN_INTRADAY_VOLUME_BURST = (
    "( {cash} (  [=1] 5 minute volume /  daily sma(  [=-75] 5 minute volume , 14 ) >  2 "
    "and  daily avg true range( 14 ) >  8 "
    "and  daily sma(  daily volume , 14 ) >  50000 ) )"
)