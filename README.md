# pyqt-reactive

Reactive, ObjectState-backed forms and reusable application infrastructure for
PyQt6.

[![PyPI version](https://badge.fury.io/py/pyqt-reactive.svg)](https://badge.fury.io/py/pyqt-reactive)
[![Documentation Status](https://readthedocs.org/projects/pyqt-reactive/badge/?version=latest)](https://pyqt-reactive.readthedocs.io/en/latest/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

## Quick start

``ParameterFormManager`` renders an existing ``ObjectState``. The state is the
model; the form is a view over it.

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
class ProcessingConfig:
    input_path: str = ""
    num_workers: int = 4
    enable_gpu: bool = False

app = QApplication([])
set_base_config_type(ProcessingConfig)
state = ObjectState(ProcessingConfig(), scope_id="processing")
form = ParameterFormManager(
    state,
    config=FormManagerConfig(color_scheme=ColorScheme()),
)
form.show()
app.exec()
```

Do not pass a dataclass type or instance directly to
``ParameterFormManager``. Create ``ObjectState(instance)`` so edits, dirty
tracking, hierarchy, and cross-window updates share one authority.

## Ownership

pyqt-reactive owns generic widget protocols and strategies, form lifecycle,
field-change dispatch, reusable services and managers, previews, animations,
and window infrastructure. Host applications own domain workflows and adapters.

## Installation

```bash
python -m pip install pyqt-reactive
```

For development:

```bash
git clone https://github.com/OpenHCSDev/PyQT-reactive.git
cd PyQT-reactive
python -m pip install -e ".[dev]"
```

Full documentation: [pyqt-reactive.readthedocs.io](https://pyqt-reactive.readthedocs.io)
