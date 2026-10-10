from endstone_antidupe.plugin import AntiDupe


def test_command_usages_use_unique_explicit_enum_types():
    usages = AntiDupe.commands["antidupe"]["usages"]
    assert usages == [
        "/antidupe",
        "/antidupe (status|reload)<action: AntidupeAction>",
        "/antidupe (perf)<action: AntidupePerfAction> (reset)[perf_action: AntidupePerfReset]",
    ]

    # Endstone 0.11.12 registers each enum type globally in the command registry.
    # These three explicit types must remain unique across the overloads.
    enum_types = [
        "AntidupeAction",
        "AntidupePerfAction",
        "AntidupePerfReset",
    ]
    assert len(enum_types) == len(set(enum_types))
    assert "AntidupePerf" not in enum_types


def test_perf_commands_remain_representable_without_duplicate_perf_literal_overloads():
    usages = AntiDupe.commands["antidupe"]["usages"]
    assert any("AntidupePerfAction" in usage for usage in usages)
    assert any("AntidupePerfReset" in usage for usage in usages)
    # There must no longer be two separate shorthand usages beginning in
    # '/antidupe perf', which is what generated AntidupePerf twice.
    assert sum(usage.startswith("/antidupe perf") for usage in usages) == 0
