"""Curated stock-code sets for repeatable B/S diagnostics."""

REGRESSION_40 = (
    "1605", "2413", "2914", "3123", "3382", "3402", "4188", "4452",
    "4502", "4661", "5020", "5401", "6178", "6501", "6758", "7011",
    "7203", "7974", "8031", "8058", "8306", "8316", "8411", "8591",
    "8750", "8766", "8801", "8802", "9005", "9020", "9022", "9101",
    "9104", "9202", "9366", "9432", "9501", "9503", "9735", "9984",
)

# Companies not included in REGRESSION_40. The set spans primary industries,
# financial institutions, infrastructure, and companies using different GAAPs.
EXPANSION_60 = (
    "1301", "1332", "1515", "1662", "1719", "1802", "1928", "2002",
    "2269", "2502", "2802", "3105", "3861", "4005", "4063", "4151",
    "4519", "4543", "4568", "4578", "4901", "5108", "5201", "5332",
    "5706", "5713", "5802", "6301", "6367", "6645", "6861", "6954",
    "6981", "7167", "7186", "7267", "7733", "7741", "7751", "7832",
    "8001", "8015", "8053", "8267", "8308", "8601", "8604", "8630",
    "8697", "8830", "9064", "9142", "9201", "9301", "9401", "9433",
    "9602", "9706", "9843", "9956",
)

# A second, non-overlapping market sample selected from the current JPX list.
# It covers all 33 industries, Prime/Standard/Growth, Tokyo Pro Market, and
# the newer alphanumeric security-code format.
BREADTH_100 = (
    "131A", "7915", "7865", "7794", "8425", "7196", "7320", "5310",
    "5287", "5301", "5122", "5184", "5185", "6058", "5871", "7063",
    "3877", "3947", "3943", "3486", "3772", "3300", "8725", "7326",
    "7388", "9319", "9353", "9326", "4251", "4615", "4934", "4548",
    "4558", "4593", "8020", "7501", "7685", "7520", "3825", "456A",
    "1898", "1828", "1444", "4344", "3997", "4371", "6331", "6334",
    "6232", "1377", "1382", "1380", "9110", "9171", "9127", "5019",
    "5015", "5013", "9233", "9204", "9206", "7731", "7727", "7774",
    "3569", "3583", "442A", "8616", "8699", "5834", "7239", "7247",
    "7318", "5943", "5939", "523A", "5461", "5612", "5484", "1663",
    "1514", "8354", "8416", "8359", "9041", "9057", "9045", "9517",
    "9514", "350A", "6785", "6803", "6597", "5741", "5753", "5858",
    "2579", "2818", "2936", "1418",
)

MARKET_100 = tuple(sorted(set(REGRESSION_40) | set(EXPANSION_60)))
MARKET_200 = tuple(sorted(set(MARKET_100) | set(BREADTH_100)))

BS_TEST_SETS = {
    "none": (),
    "regression-40": REGRESSION_40,
    "expansion-60": EXPANSION_60,
    "breadth-100": BREADTH_100,
    "market-100": MARKET_100,
    "market-200": MARKET_200,
}


def get_test_set_codes(name):
    try:
        return list(BS_TEST_SETS[name])
    except KeyError as exc:
        choices = ", ".join(sorted(BS_TEST_SETS))
        raise ValueError(f"Unknown B/S test set: {name}. Choose one of: {choices}") from exc
