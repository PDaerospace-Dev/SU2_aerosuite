import pytest

from aerosuite.engine.editing import set_parameter
from aerosuite.engine.errors import ProjectError
from aerosuite.engine.models import Settings


@pytest.mark.parametrize("key", ["CFL_NUMBER", "MARKER_FAR"])
def test_set_parameter_rejects_empty_values(key):
    settings = Settings()
    with pytest.raises(
        ProjectError,
        match=rf"^{key} needs a value; remove the setting to go back to the template value \(CLI: --unset {key}\)$",
    ):
        set_parameter(settings, key, "  ")
    assert settings.overrides == {} and settings.markers == {}
