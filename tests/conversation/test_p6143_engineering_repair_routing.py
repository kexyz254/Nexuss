from nexuss.conversation.stabilization import deterministic_route


def test_failed_build_repair_outranks_constitution_words():
    route = deterministic_route(
        "Nexuss, repair the most recent failed P6.15 engineering task. "
        "Do not modify the Constitution or credentials."
    )
    assert route is not None
    assert route.route.value == "action"
    assert route.capability_hint == "engineering.repair_failed_build"
    assert route.action_instruction.startswith("Repair latest failed engineering build:")


def test_identity_question_still_routes_as_chat():
    route = deterministic_route("Who founded Nexuss?")
    assert route is not None
    assert route.route.value == "chat"
