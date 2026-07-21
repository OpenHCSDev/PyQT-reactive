# Quick start

## Installation

```bash
python -m pip install pyqt-reactive
```

## ObjectState-backed form

```python
from dataclasses import dataclass

from PyQt6.QtWidgets import QApplication
from objectstate import ObjectState, set_base_config_type
from pyqt_reactive.forms.parameter_form_manager import (
    FormManagerConfig,
    ParameterFormManager,
)
from pyqt_reactive.theming import ColorScheme

@dataclass
class MyConfig:
    name: str = "default"
    count: int = 10
    enabled: bool = True

app = QApplication([])
set_base_config_type(MyConfig)
state = ObjectState(MyConfig(), scope_id="example")
form = ParameterFormManager(
    state,
    config=FormManagerConfig(color_scheme=ColorScheme()),
)
form.show()
app.exec()
```

``ObjectState`` owns values, hierarchy, dirty tracking, and history.
``ParameterFormManager`` owns the PyQt view and writes changes back to that
state. Multiple views should receive the same registered state rather than
constructing independent models.
