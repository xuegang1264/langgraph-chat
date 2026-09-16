from app.services.dashscope import clean_model_content


def test_clean_model_content_removes_safety_tag() -> None:
    content = (
        "<ds_safety>[用户未成年]否 [分类]其他 "
        "[判定]内容为技术方案讨论。 [规则]无</ds_safety>Safe"
        "可以先拆成前端、后端和测试三个任务。"
    )

    assert clean_model_content(content) == "可以先拆成前端、后端和测试三个任务。"


def test_clean_model_content_keeps_normal_reply() -> None:
    assert clean_model_content("正常回复") == "正常回复"
