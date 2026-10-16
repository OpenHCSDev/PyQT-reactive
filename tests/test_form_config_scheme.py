"""The form configuration owns its resolved scheme, not its analysis context."""
from dataclasses import dataclass

import pytest
from objectstate import set_base_config_type
from formbridge.forms.parameter_form_service import ParameterFormService
from pyqt_reactive.forms.form_init_service import ConfigBuilderService, ExtractedParameters
from pyqt_reactive.forms.parameter_form_manager import FormManagerConfig
from pyqt_reactive.theming import ColorScheme


@pytest.mark.parametrize('explicit', [False, True], ids=['default', 'explicit'])
def test_config_derivation_preserves_the_resolved_color_scheme(qapp, explicit):
    @dataclass
    class Settings:
        text: str = 'hello'
    set_base_config_type(Settings)
    scheme = ColorScheme() if explicit else None
    result = ConfigBuilderService.build(
        '', ExtractedParameters(default_value={'text': 'hello'}, param_type={'text': str},
                                object_instance=Settings()),
        None, scheme, None, ParameterFormService(), FormManagerConfig(color_scheme=scheme),
    )
    assert isinstance(result.config.color_scheme, ColorScheme)
    if explicit:
        assert result.config.color_scheme is scheme
    assert result.config.color_scheme.styles.generate_config_window_style()
