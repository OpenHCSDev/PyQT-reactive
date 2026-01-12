# pyqt-formgen

**React-quality reactive form generation framework for PyQt6**

[![PyPI version](https://badge.fury.io/py/pyqt-formgen.svg)](https://badge.fury.io/py/pyqt-formgen)
[![Documentation Status](https://readthedocs.org/projects/pyqt-formgen/badge/?version=latest)](https://pyqt-formgen.readthedocs.io/en/latest/?badge=latest)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- **Dataclass-Driven Forms**: Automatically generate UI forms from Python dataclasses
- **ObjectState Integration**: First-class support for lazy configuration and hierarchical inheritance
- **ABC-Based Protocols**: Type-safe widget contracts with clean interfaces
- **Reactive Updates**: React-style lifecycle hooks with cross-window synchronization
- **Theming System**: ColorScheme-based styling with dynamic theme switching
- **Flash Animations**: Game-engine inspired visual feedback for value changes
- **Window Management**: Scoped window registry with navigation support

## Quick Start

```python
from dataclasses import dataclass
from PyQt6.QtWidgets import QApplication
from pyqt_formgen.forms import ParameterFormManager

@dataclass
class ProcessingConfig:
    input_path: str = ""
    output_path: str = ""
    num_workers: int = 4
    enable_gpu: bool = False

app = QApplication([])
form = ParameterFormManager(ProcessingConfig)
form.show()
app.exec()
```

## Installation

```bash
pip install pyqt-formgen
```

For development:
```bash
git clone https://github.com/trissim/pyqt-formgen.git
cd pyqt-formgen
pip install -e ".[dev]"
```

## Architecture

The package is organized in layers:

```
pyqt_formgen/
├── core/        # Tier 1: Pure PyQt6 utilities
├── protocols/   # Tier 2: Widget ABCs and adapters
├── services/    # Tier 3: Reusable service layer
├── forms/       # Tier 4: ParameterFormManager
├── theming/     # Color schemes and styling
├── widgets/     # Extended widget implementations
└── animation/   # Flash effects and visual feedback
```

## Key Components

### ParameterFormManager

Auto-generates forms from dataclasses with full type support:

```python
from pyqt_formgen.forms import ParameterFormManager

form = ParameterFormManager(MyConfig)
config = form.collect_values()  # Get typed config back
```

### WindowManager

Singleton window registry with scope-based navigation:

```python
from pyqt_formgen.services import WindowManager

window = WindowManager.show_or_focus("config:plate1", lambda: ConfigWindow(...))
WindowManager.navigate_to("config:plate1", field="exposure_time")
```

### Theming

Dynamic theme switching with consistent styling:

```python
from pyqt_formgen.theming import ColorScheme, apply_theme

apply_theme(widget, ColorScheme.DARK)
```

## Documentation

Full documentation available at [pyqt-formgen.readthedocs.io](https://pyqt-formgen.readthedocs.io)

## License

MIT License - see LICENSE file for details

## Contributing

Contributions welcome! Please see CONTRIBUTING.md for guidelines.

## Credits

Developed by Tristan Simas. Extracted from [OpenHCS](https://github.com/trissim/openhcs) for general-purpose use.
