import typing
from typing import Any, Callable

from adaptix import Retort
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.dto.base import TrackableMixin


class BaseDaoImpl:
    # A DTO's `id` is the row's primary key. Every caller of `_serialize_for_update`
    # already keys its UPDATE on it, so it can only ever appear in the SET clause by
    # mistake — and a mistake there rewrites the identity of the row being updated.
    _IMMUTABLE_FIELDS: typing.Final[frozenset[str]] = frozenset({"id"})

    def __init__(self, session: AsyncSession, retort: Retort) -> None:
        self.session = session
        self.retort = retort

    def _serialize_for_update(
        self,
        dto: Any,
        dto_class: type,
        db_model: type,
        pre_process: Callable[[Any], Any] | None = None,
    ) -> dict:
        type_hints = typing.get_type_hints(dto_class)
        result = {}
        for key in dto.changed_data:
            if key in self._IMMUTABLE_FIELDS:
                continue

            full_value = getattr(dto, key)
            field_type = type_hints.get(key)

            if pre_process is not None:
                full_value = pre_process(full_value)

            serialized = self.retort.dump(full_value, field_type)

            if isinstance(getattr(dto, key), TrackableMixin) and getattr(dto, key).changed_data:
                changed_keys = getattr(dto, key).changed_data.keys()
                partial = {k: v for k, v in serialized.items() if k in changed_keys}
                column = getattr(db_model, key)
                result[key] = column.concat(partial)
            else:
                result[key] = serialized

        return result
