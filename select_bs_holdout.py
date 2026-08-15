import argparse
import random
from collections import defaultdict

from bs_test_sets import BS_TEST_SETS
from firebase_master_test import get_all_listed_codes


MARKET_QUOTAS = {
    "Prime": 35,
    "Standard": 35,
    "Growth": 20,
    "PRO": 10,
}


def normalize_market(market):
    if "プライム" in market:
        return "Prime"
    if "スタンダード" in market:
        return "Standard"
    if "グロース" in market:
        return "Growth"
    if "PRO Market" in market:
        return "PRO"
    return None


def select_holdout(companies, excluded_codes, seed, quotas=None):
    quotas = quotas or MARKET_QUOTAS
    rng = random.Random(seed)
    selected = []

    for market, quota in quotas.items():
        sector_pools = defaultdict(list)
        for company in companies:
            if company["code"] in excluded_codes:
                continue
            if normalize_market(company["market"]) != market:
                continue
            sector_pools[company["sector"]].append(company)

        sectors = sorted(sector_pools)
        rng.shuffle(sectors)
        for pool in sector_pools.values():
            rng.shuffle(pool)

        picked = []
        while len(picked) < quota:
            progressed = False
            for sector in sectors:
                if sector_pools[sector] and len(picked) < quota:
                    picked.append(sector_pools[sector].pop())
                    progressed = True
            if not progressed:
                break

        if len(picked) != quota:
            raise RuntimeError(
                f"Not enough unseen {market} issuers: expected {quota}, got {len(picked)}"
            )
        selected.extend(picked)

    return selected


def main():
    parser = argparse.ArgumentParser(
        description="Select a deterministic, sector-diverse blind B/S holdout."
    )
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()

    excluded_codes = {
        code
        for name, codes in BS_TEST_SETS.items()
        if name != "none"
        for code in codes
    }
    selected = select_holdout(
        get_all_listed_codes(),
        excluded_codes=excluded_codes,
        seed=args.seed,
    )

    print(
        f"selected={len(selected)} unique={len({row['code'] for row in selected})} "
        f"overlap={len({row['code'] for row in selected} & excluded_codes)}"
    )
    for index in range(0, len(selected), 8):
        codes = ", ".join(f'\"{row["code"]}\"' for row in selected[index:index + 8])
        print(f"    {codes},")

    print("\ncode|market|sector|name")
    for row in selected:
        print(
            f"{row['code']}|{normalize_market(row['market'])}|"
            f"{row['sector']}|{row['name']}"
        )


if __name__ == "__main__":
    main()
