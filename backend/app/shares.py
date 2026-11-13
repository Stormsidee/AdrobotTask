def normalize_shares(weights: list[int]) -> list[int]:
    """Scale integer weights to 100 and distribute rounding by remainder."""
    if not weights:
        return []
    if not sum(weights):
        weights = [1] * len(weights)
    total = sum(weights)
    quotients = [divmod(weight * 100, total) for weight in weights]
    shares = [whole for whole, _ in quotients]
    ranked = sorted(range(len(weights)), key=lambda index: -quotients[index][1])
    for index in ranked[:100 - sum(shares)]:
        shares[index] += 1
    return shares


def shares_with_new_offer(weights: list[int]) -> list[int]:
    if not weights or not sum(weights):
        return normalize_shares([1] * (len(weights) + 1))
    # Give the new offer the average weight of the current offers.
    return normalize_shares([weight * len(weights) for weight in weights] + [sum(weights)])
