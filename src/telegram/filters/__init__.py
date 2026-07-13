from aiogram import Router
from aiogram.filters import or_f

from .private import PrivateFilter
from .support_group import SupportGroupFilter

__all__ = [
    "setup_global_filters",
]


def setup_global_filters(router: Router) -> None:
    # Allow private chats OR the support operator group. Without the second branch the
    # global private-only filter drops every operator reply sent in a forum topic
    # before it can reach the support router.
    filters = [
        or_f(PrivateFilter(), SupportGroupFilter()),
    ]

    for filter in filters:
        router.message.filter(filter)
