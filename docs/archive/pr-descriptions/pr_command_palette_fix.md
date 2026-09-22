Fixes two issues with the command palette:

1. **Auto-selection bug**: Removed automatic selection of first item ("Ver Normas Consolidadas") that was always highlighted
2. **Missing closing animation**: Added smooth closing animation matching the elegant opening animation

## Changes

### Selection Management
- Removed automatic `selected` class from first item
- Added keyboard navigation with ArrowUp/ArrowDown keys
- Reset selection when filtering/searching commands
- Only select items when user navigates with arrow keys

### Closing Animation
- Added `.closing` class for exit animation
- Implemented `fadeOutDown` keyframes (reverse of `fadeInUp`)
- Smooth scale down (1.0 → 0.92) with translateY
- Staggered animation for header and results (250ms and 200ms)
- 300ms total animation duration matching opening

## UX Improvements
- Items are no longer pre-selected, giving user full control
- Smooth bidirectional animations enhance perceived quality
- Keyboard navigation provides better accessibility

