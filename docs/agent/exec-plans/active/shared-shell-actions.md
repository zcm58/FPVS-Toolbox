# Shared shell actions

## Scope

Give Home, Settings, Library, and tool commands shared Qt actions. Native menus
reuse the shared registration and command guards. Embedded workspace routes,
project settings and beta acknowledgement use their existing owners.

## Plan

1. Build shared actions in `Main_App.gui.shell_actions` and use them in the
   native menus. Leave project and tool callbacks with `MainWindow` and the
   Library controller.
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

On 2026-11-17 the main workflow updates and newer GUI polish were reconciled
with the public Library. The current shell uses the 1200 × 800 default/minimum,
File/View/Tools menus and shared action availability. Ten scoped native Qt cases
passed on the laptop display, including Library visibility and action locking.
