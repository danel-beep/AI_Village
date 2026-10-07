from aivillage.mapgen import LOT_NAMES
from aivillage.population import NAMES
from aivillage.run import seat_order


def test_cycled_models_do_not_follow_name_order():
    # The alphabetically first villager (often Boris, who is in every village) must not always get models[0].
    names = ["Aaron", "Boris", "Celia", "Dora", "Edgar"]
    firsts = {seat_order(names, seed)[0] for seed in range(1, 40)}
    assert len(firsts) == len(names)
    assert seat_order(names, 7) == seat_order(list(reversed(names)), 7)  # seeded: same village, same seats


def test_lot_names_are_not_villager_names():
    words = {w for lot in LOT_NAMES for w in lot.split()}
    assert not words & set(NAMES)
