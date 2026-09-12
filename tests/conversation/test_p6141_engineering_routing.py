from nexuss.conversation.stabilization import deterministic_route


def test_verify_p614_with_constitution_constraint_routes_engineering():
    result = deterministic_route(
        "Nexuss, verify P6.14 and confirm the Constitution boundary remains intact."
    )
    assert result is not None
    assert result.route.value == "action"
    assert result.capability_hint == "engineering.verify_acceptance"


def test_build_constraint_containing_constitution_still_routes_build():
    result = deterministic_route(
        "Nexuss, build yourself: improve diagnostics without modifying the Constitution."
    )
    assert result is not None
    assert result.route.value == "action"
    assert result.capability_hint == "engineering.build_artifact"


def test_identity_question_still_routes_constitutionally():
    result = deterministic_route("Who founded Nexuss?")
    assert result is not None
    assert result.route.value == "chat"
