from _office_utils import range_to_matrix, format_response, get_target_range_address, exit_code_for


def test_range_to_matrix_scalar():
    assert range_to_matrix(5) == [[5]]
    assert range_to_matrix(None) == [[None]]


def test_range_to_matrix_single_row_multi_col():
    # pywin32는 한 행 여러 열도 ((a, b, c),) 형태로 반환
    assert range_to_matrix((("a", "b", "c"),)) == [["a", "b", "c"]]


def test_range_to_matrix_single_col_multi_row():
    assert range_to_matrix((("a",), ("b",))) == [["a"], ["b"]]


def test_format_response_extra_cannot_override_reserved_keys():
    res = format_response("ok", "clean", "undo", preview="p", extra={"status": "error", "action": "restored", "x": 1})
    assert res["status"] == "ok"
    assert res["action"] == "undo"
    assert res["x"] == 1


def test_get_target_range_address():
    assert get_target_range_address("B2", 3, 2) == "B2:C4"


def test_exit_code_for():
    assert exit_code_for({"status": "ok"}) == 0
    assert exit_code_for({"status": "no_match"}) == 0
    assert exit_code_for({"status": "error"}) == 1
    assert exit_code_for({"status": "partial"}) == 1
