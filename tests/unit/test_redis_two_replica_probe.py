from scripts.redis_two_replica_integration_probe import opaque_alpha_suffix


def test_cache_probe_suffix_is_unique_alphabetic_and_guardrail_safe() -> None:
    first = opaque_alpha_suffix()
    second = opaque_alpha_suffix()

    assert len(first) == 32
    assert first.isalpha()
    assert first.islower()
    assert first != second
