from pdf_sft.stages.generate import requested_type_schedule


def test_requested_type_schedule_applies_run_level_weights() -> None:
    weights = {
        "visual_spatial": 0.40,
        "structured_layout": 0.45,
        "text_reasoning": 0.15,
    }
    three = requested_type_schedule(weights, 3)
    assert sorted(three) == ["structured_layout", "text_reasoning", "visual_spatial"]

    twenty = requested_type_schedule(weights, 20)
    assert twenty.count("visual_spatial") == 8
    assert twenty.count("structured_layout") == 9
    assert twenty.count("text_reasoning") == 3
    assert all(
        twenty[index : index + 4] != [task_type] * 4
        for task_type in weights
        for index in range(len(twenty) - 3)
    )
