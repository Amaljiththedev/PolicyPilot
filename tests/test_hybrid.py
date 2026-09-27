from app.api.services.retrieval import rrf_merge


def test_item_in_both_lists_beats_item_in_one():
    # 3 is 2nd in both lists; 1 is 1st in only one list
    assert rrf_merge([[1, 3, 2], [4, 3, 5]])[0] == 3


def test_all_ids_kept_once():
    out = rrf_merge([[1, 2], [2, 3]])
    assert sorted(out) == [1, 2, 3]


def test_single_list_keeps_order():
    assert rrf_merge([[7, 8, 9]]) == [7, 8, 9]
