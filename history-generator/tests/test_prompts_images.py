import prompts


def test_every_domain_has_an_image_style():
    for domain, d in prompts.DOMAINS.items():
        assert d.get("image_style"), f"domain {domain!r} is missing image_style"


def test_build_image_prompts_tool_shape():
    tool = prompts.build_image_prompts_tool(3)
    schema = tool["function"]["parameters"]["properties"]["prompts"]
    assert tool["function"]["name"] == "propose_image_prompts"
    assert schema["minItems"] == 3
    assert schema["maxItems"] == 3


def test_build_image_prompts_system_mentions_domain_style_and_forbids_text():
    system = prompts.build_image_prompts_system("math")
    assert prompts.DOMAINS["math"]["image_style"] in system
    assert "text" in system.lower()


def test_build_image_prompts_user_includes_script_and_titles():
    user = prompts.build_image_prompts_user("Roman Concrete", "How it was made", "It was durable and cheap.")
    assert "Roman Concrete" in user
    assert "How it was made" in user
    assert "It was durable and cheap." in user
