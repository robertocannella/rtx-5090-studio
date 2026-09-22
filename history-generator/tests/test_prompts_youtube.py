import prompts


def test_build_youtube_metadata_tool_shape():
    tool = prompts.build_youtube_metadata_tool()
    assert tool["function"]["name"] == "propose_youtube_metadata"
    props = tool["function"]["parameters"]["properties"]
    assert set(props) == {"title", "description", "tags", "category"}
    assert tool["function"]["parameters"]["required"] == ["title", "description", "tags", "category"]


def test_build_youtube_metadata_system_mentions_domain_and_forbids_timestamps():
    system = prompts.build_youtube_metadata_system("math")
    assert prompts.DOMAINS["math"]["label"] in system
    assert "timestamp" in system.lower()


def test_build_youtube_metadata_user_includes_topic_title_and_script():
    user = prompts.build_youtube_metadata_user(
        "Ancient Rome", "Roman Concrete and Aqueducts", "history", 3720, "the full script text",
    )
    assert "Ancient Rome" in user
    assert "Roman Concrete and Aqueducts" in user
    assert "the full script text" in user
    assert "62 minutes" in user
