from __future__ import annotations

from .models import ViewState


class NavigationHistory:
    """A view stack that preserves each list's selected leaf."""

    def __init__(self, initial: ViewState) -> None:
        self._stack = [initial]

    @property
    def current(self) -> ViewState:
        return self._stack[-1]

    @property
    def can_go_back(self) -> bool:
        return len(self._stack) > 1

    def remember_selection(self, selected: int) -> None:
        self.current.selected = max(0, selected)

    def push(self, state: ViewState) -> None:
        self._stack.append(state)

    def replace(self, state: ViewState) -> None:
        self._stack[-1] = state

    def back(self) -> ViewState:
        if self.can_go_back:
            self._stack.pop()
        return self.current

    def reset(self, state: ViewState) -> None:
        self._stack[:] = [state]

