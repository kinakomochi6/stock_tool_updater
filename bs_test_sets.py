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

MARKET_100 = tuple(sorted(set(REGRESSION_40) | set(EXPANSION_60)))

BS_TEST_SETS = {
    "none": (),
    "regression-40": REGRESSION_40,
    "expansion-60": EXPANSION_60,
    "market-100": MARKET_100,
}


def get_test_set_codes(name):
    try:
        return list(BS_TEST_SETS[name])
    except KeyError as exc:
        choices = ", ".join(sorted(BS_TEST_SETS))
        raise ValueError(f"Unknown B/S test set: {name}. Choose one of: {choices}") from exc

