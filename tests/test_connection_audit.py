from scripts.audit_retrieval_connections import classify_missing, extract_links, graph_distances


def test_extract_links_excludes_heading_self_reference_and_external_law():
    parents = {
        "jo-1": "제1조 (신청)\n제2조를 따른다. 민법 제2조 및 민법 제660조는 외부다.",
        "jo-2": "제2조 (심사)\n제1조를 참조한다.",
    }
    links, external = extract_links(parents)
    assert links == {"jo-1": ["jo-2"], "jo-2": ["jo-1"]}
    assert external == [
        {"source": "jo-1", "target": "jo-2"},
        {"source": "jo-1", "target": "jo-660"},
    ]


def test_missing_is_classified_at_first_failed_stage_for_each_required_article():
    assert classify_missing(
        ["jo-1", "jo-2", "jo-3", "jo-4"],
        ["jo-1", "jo-2", "jo-3"],
        ["jo-1", "jo-2"],
        ["jo-1"],
    ) == {"candidate_missing": ["jo-4"], "parent_missing": ["jo-3"], "context_missing": ["jo-2"]}


def test_graph_distances_do_not_treat_unreachable_articles_as_recovered():
    assert graph_distances(
        {"jo-1": ["jo-2"], "jo-2": ["jo-3"], "jo-3": []}, ["jo-1"], ["jo-2", "jo-3", "jo-4"]
    ) == {
        "jo-2": 1,
        "jo-3": 2,
        "jo-4": None,
    }
