import search


def test_build_index_includes_home_and_guides_and_posts():
    posts = [{"slug": "welcome", "title": "Welcome", "body_html": "<p>Hello there.</p>", "tags": ["intro"]}]
    index = search.build_index("<p>Home text</p>", "<p>Guide text</p>", "<p>Plot guide text</p>", posts)

    locations = {d["location"] for d in index["docs"]}
    assert locations == {"", "latex-guide/", "matplotlib-guide/", "blog/welcome/"}
    assert index["config"]["fields"]["title"]["boost"] == 1000.0
    post_doc = next(d for d in index["docs"] if d["location"] == "blog/welcome/")
    assert post_doc["tags"] == ["intro"]


def test_build_index_strips_html_tags_from_text():
    posts = []
    index = search.build_index(
        "<h1>Title</h1><p>Body <strong>text</strong>.</p>", "<p>Guide</p>", "<p>Plot guide</p>", posts,
    )
    home_doc = next(d for d in index["docs"] if d["location"] == "")
    assert "<" not in home_doc["text"]
    assert "Body" in home_doc["text"]
    assert "text" in home_doc["text"]
