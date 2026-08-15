REAL_ESTATE_REGRESSION_5 = (
    "6396",
    "9635",
    "6042",
    "3123",
    "9366",
)

# Fixed before evaluating structural-extractor results. The set spans railways,
# real estate, retail, warehousing, leisure, trading, energy, and manufacturing.
REAL_ESTATE_HOLDOUT_30 = (
    "9001", "9005", "9007", "9008", "9009", "9041", "9042", "9044",
    "9045", "9048", "8801", "8802", "8830", "3003", "3289", "8233",
    "8242", "3099", "9301", "9302", "9303", "9364", "9602", "4661",
    "8136", "8058", "5020", "2502", "2503", "7911",
)


REAL_ESTATE_TEST_SETS = {
    "regression-5": REAL_ESTATE_REGRESSION_5,
    "holdout-30": REAL_ESTATE_HOLDOUT_30,
}


def get_real_estate_test_set_codes(name):
    try:
        return list(REAL_ESTATE_TEST_SETS[name])
    except KeyError as exc:
        choices = ", ".join(sorted(REAL_ESTATE_TEST_SETS))
        raise ValueError(
            f"Unknown real-estate test set: {name}. Choose one of: {choices}"
        ) from exc
