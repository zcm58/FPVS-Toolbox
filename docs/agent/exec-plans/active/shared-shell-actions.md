# Shared shell actions

## Scope

Give Home, Settings, and tool commands shared Qt actions. Move tool registration
out of the sidebar. Keep the menu and sidebar layouts, embedded workspace routes,
project settings behavior, and beta acknowledgement workflow.

## Plan

1. Build shared actions in `Main_App.gui.shell_actions` and use them in both
   shell surfaces. Keep sidebar labels, icons and selection styling in the
   sidebar, and leave project and tool callbacks with `MainWindow`.
2. Have the existing processing navigation lock control action availability.
   Preserve the disabled styling and restore the actions' earlier state at
   unlock. Keep project and Settings draft guards on the existing routes.
3. Verify shared triggers and availability in the registered Qt shell smoke
   tests. Run the GUI focused and repository precommit gates. Follow the
   [visible shell acceptance](../../architecture/gui.md#native-menus-and-tool-navigation)
   in an approved visible session.

## Status

Implemented on 2026-11-11. The GUI focused gate passed 774 tests. The
repository precommit gate passed 350 tests with two skips. Strict MkDocs
passed. On the visible Windows desktop, all 40 main-window Qt smoke tests and
three related Settings Qt cases passed. The smoke tests cover shared tool
activation, processing and cache-reset lockout, restoration, and beta
acknowledgement. The manual walkthrough with a real project remains available
in the GUI contract.
