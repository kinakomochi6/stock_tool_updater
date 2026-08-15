REAL_ESTATE_REGRESSION_5 = (
    "6396",
    "9635",
    "6042",
    "3123",
    "9366",
)


REAL_ESTATE_TEST_SETS = {
    "regression-5": REAL_ESTATE_REGRESSION_5,
}


def get_real_estate_test_set_codes(name):
    try:
        return list(REAL_ESTATE_TEST_SETS[name])
    except KeyError as exc:
        choices = ", ".join(sorted(REAL_ESTATE_TEST_SETS))
        raise ValueError(
            f"Unknown real-estate test set: {name}. Choose one of: {choices}"
        ) from exc
