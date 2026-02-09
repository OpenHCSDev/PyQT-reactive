# Provenance Button and Reset Button Styling Implementation

## Current Implementation Status

### 1. Provenance Button (COMPLETED)
**Location**: `src/pyqt_reactive/widgets/shared/clickable_help_components.py`

**What was implemented**:
- Created `ProvenanceButton` class that inherits from `ProvenanceNavigationMixin`
- Button always visible but only clickable when provenance exists
- Uses `_has_provenance()` to check if field inherits from ancestor
- Initial visibility set at creation based on provenance
- Dynamic updates in `field_change_dispatcher.py` when any field changes

**Code**:
```python
class ProvenanceButton(QPushButton, ProvenanceNavigationMixin):
    def _on_click(self):
        if self._has_provenance():
            # Navigate to source
    
    def enterEvent(self, event):
        if self._has_provenance():
            # Show pointer cursor
```

**Wiring**:
- Created in `widget_creation_config.py` for enableable groupboxes
- Added to title layout via `addEnableableWidgets()`
- Updated in `field_change_dispatcher.py` after state changes

### 2. Reset Button Styling (COMPLETED BUT NEEDS FIX)
**Location**: `src/pyqt_reactive/utils/styling_utils.py` (NEW)

**What was implemented**:
- Created `update_reset_button_styling()` function
- Applies `*` prefix when field is dirty
- Applies `_` underline when field differs from signature default
- Uses font underline (not CSS) to preserve button styling

**Code**:
```python
def update_reset_button_styling(button, state, field_id, field_name):
    has_star, has_underline = get_field_indicators(state, field_id, field_name)
    text = "Reset"
    if has_star:
        text = "*" + text
    button.setText(text)
    
    # Apply underline via font (preserves other styles)
    font = button.font()
    font.setUnderline(has_underline)
    button.setFont(font)
```

**Wiring**:
- Applied at creation in `widget_creation_config.py`
- Updated in `field_change_dispatcher.py` for ALL reset buttons when any field changes

### 3. Field Change Dispatcher Updates
**Location**: `src/pyqt_reactive/services/field_change_dispatcher.py`

**What was added**:
```python
# Update ProvenanceButton visibility
if groupbox and hasattr(groupbox, 'title_layout'):
    for widget in groupbox.title_layout.findChildren(ProvenanceButton):
        widget.setVisible(widget._has_provenance())
        break

# Update reset button styling for ALL reset buttons
from pyqt_reactive.utils.styling_utils import update_reset_button_styling
for field_name, reset_button in source.reset_buttons.items():
    update_reset_button_styling(reset_button, source.state, source.field_id, field_name)
```

## Issue Reported by User

### Problem Statement
The user reports that both the provenance button (^) and reset button styling (* and _) are NOT syncing properly when field values change.

### Specific Scenarios
1. **Reset All button**: When using the "Reset All" button at the groupbox or window level, individual field reset buttons don't update their * and _ styling
2. **Field labels work correctly**: When resetting, the parameter labels (clickable to provenance) DO clear their _ and * indicators correctly
3. **Reset buttons should behave THE SAME as labels**: The user wants the reset button styling to follow the exact same wiring/signals as the label styling

### Current Behavior
- Label styling updates correctly via `_update_label_styling()` which is called after reset
- Reset button styling is updated in field_change_dispatcher, but apparently not working for all reset scenarios
- Provenance button visibility is updated in field_change_dispatcher, but not syncing

### Expected Behavior
1. When any field value changes (individual reset, reset all, manual edit):
   - Label styling updates (* and _)
   - Reset button styling updates (* and _)
   - Provenance button visibility updates (show/hide)

2. All three should use the SAME signal/wiring mechanism

## Root Cause Analysis

### Current Flow
1. Field value changes (user edit or reset)
2. `state.update_parameter()` is called
3. `FieldChangeDispatcher.dispatch()` is triggered
4. Dispatcher updates:
   - Provenance button visibility
   - Reset button styling
   - Sibling refreshes
5. Separately, label styling is updated via `_update_label_styling()` called from `reset_parameter()`

### Issue
The reset button styling and provenance button updates are happening in the dispatcher, but they may not be triggered in all scenarios (particularly Reset All). The label styling works because it's explicitly called in `reset_parameter()` after the dispatch.

### Solution Needed
Ensure reset button styling and provenance button updates are triggered by the SAME mechanism that updates label styling. This likely means:

1. Hook into the same signal/event that triggers `_update_label_styling()`
2. OR ensure the field_change_dispatcher runs for ALL parameter changes including batch resets
3. OR wire the updates directly into the reset_parameter flow

## Technical Details

### Key Methods
- `_update_label_styling(param_name)` in parameter_form_manager.py - updates label * and _
- `dispatch(event)` in field_change_dispatcher.py - currently updates provenance and reset buttons
- `reset_parameter(param_name)` in parameter_form_manager.py - resets field and triggers dispatch
- `reset_all_parameters()` in parameter_form_manager.py - resets all fields

### Key State Fields
- `state.dirty_fields` - fields with unsaved changes (for *)
- `state.signature_diff_fields` - fields differing from signature (for _)
- `state.get_provenance(dotted_path)` - returns provenance info for navigation

### Wiring Pattern Used by Labels
Labels are updated via:
```python
event = FieldChangeEvent(param_name, reset_value, self, is_reset=True)
FieldChangeDispatcher.instance().dispatch(event)
# Then immediately after:
self._update_label_styling(param_name)
```

The reset button and provenance button should follow this same pattern.

## Action Items

1. **Verify field_change_dispatcher is being called** for ALL reset scenarios (single and batch)
2. **Move reset button and provenance updates** to same location as label updates, or ensure dispatcher runs
3. **Test both scenarios**:
   - Individual field reset via reset button
   - Batch reset via "Reset All" button
4. **Verify provenance button** shows/hides correctly in both scenarios
5. **Verify reset button** shows * and _ correctly in both scenarios
