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

# A second blind set fixed after the first holdout improvements. It broadens
# coverage across railways, property, retail/hospitality, warehousing,
# asset-heavy manufacturing, utilities, and telecommunications.
REAL_ESTATE_HOLDOUT_B_40 = (
    "9020", "9021", "9022", "9046", "9142", "9049", "9052",
    "8804", "8818", "8860", "8876", "8892", "8934", "3231",
    "3465", "3254", "3291", "3299",
    "3086", "3382", "7532", "7453", "9983", "4680", "9722", "9616",
    "9304", "9305", "9324",
    "5401", "5411", "5711", "5802", "5108", "5201", "5202", "5332",
    "9501", "9502", "9432",
)

# Third blind set, fixed before search-recall and unsupported-layout work. It
# mixes disclosure-heavy sectors with manufacturers that often have no target
# note, so both recall and false-positive resistance are exercised.
REAL_ESTATE_HOLDOUT_C_40 = (
    "9003", "9006", "9010", "9023", "9031", "9075",
    "8803", "8848", "8871", "8923", "3245", "3284", "3452", "3498",
    "8267", "8273", "8237", "9843", "3092", "3088", "3391", "3549",
    "9064", "9065", "9076", "9369",
    "9603", "9706", "9726", "9713",
    "3401", "3402", "4005", "4042", "4063", "4188", "4901", "4911",
    "6301", "6501",
)


REAL_ESTATE_TEST_SETS = {
    "regression-5": REAL_ESTATE_REGRESSION_5,
    "holdout-30": REAL_ESTATE_HOLDOUT_30,
    "holdout-b-40": REAL_ESTATE_HOLDOUT_B_40,
    "holdout-c-40": REAL_ESTATE_HOLDOUT_C_40,
}


def get_real_estate_test_set_codes(name):
    try:
        return list(REAL_ESTATE_TEST_SETS[name])
    except KeyError as exc:
        choices = ", ".join(sorted(REAL_ESTATE_TEST_SETS))
        raise ValueError(
            f"Unknown real-estate test set: {name}. Choose one of: {choices}"
        ) from exc
