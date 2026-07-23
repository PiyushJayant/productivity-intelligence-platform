import pytest

from setup.migrate import quote_identifier


def test_database_identifier_is_strictly_validated():
    assert quote_identifier("productivity_platform") == '"productivity_platform"'

    for invalid in ("Productivity", "productivity-platform", "postgres; DROP DATABASE postgres"):
        with pytest.raises(ValueError, match="ALLOYDB_DATABASE"):
            quote_identifier(invalid)
