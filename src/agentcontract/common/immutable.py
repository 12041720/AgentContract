"""Shared immutable data structures and deep freezing utilities."""

from collections.abc import Iterable, Iterator, Mapping
from types import MappingProxyType
from typing import Any
from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema


def _freeze_value(val: Any) -> Any:
    """Recursively convert nested mutable collections into immutable equivalents."""
    if isinstance(val, (FrozenDict, frozenset)):
        return val
    if isinstance(val, Mapping):
        return FrozenDict({str(k): _freeze_value(v) for k, v in val.items()})
    if isinstance(val, (list, tuple)):
        return tuple(_freeze_value(v) for v in val)
    if isinstance(val, set):
        return frozenset(_freeze_value(v) for v in val)
    return val


class FrozenDict(Mapping[str, Any]):
    """An immutable mapping that wraps an internal read-only mapping via composition.

    Subclasses Mapping (not dict) and backs its storage with a MappingProxyType so
    that no mutable methods exist and direct attribute access to `_data` cannot
    mutate contents. Durable domain metadata and selectors are protected from in-place alteration.
    """

    __slots__ = ("_data", "_hash")

    def __init__(
        self,
        mapping_or_iterable: Mapping[str, Any] | Iterable[tuple[str, Any]] | None = None,
        **kwargs: Any,
    ) -> None:
        raw: dict[str, Any] = {}
        if mapping_or_iterable is not None:
            raw.update(dict(mapping_or_iterable))
        if kwargs:
            raw.update(kwargs)
        frozen_data = {str(k): _freeze_value(v) for k, v in raw.items()}
        self._data: MappingProxyType[str, Any] = MappingProxyType(frozen_data)
        self._hash: int | None = None

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __repr__(self) -> str:
        return f"FrozenDict({dict(self._data)!r})"

    def __copy__(self) -> "FrozenDict":
        return self

    def __deepcopy__(self, memo: Any) -> "FrozenDict":
        return self

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FrozenDict):
            return self._data == other._data
        if isinstance(other, Mapping):
            return self._data == dict(other)
        return False

    def __hash__(self) -> int:
        if self._hash is None:
            items = []
            for k, v in sorted(self._data.items()):
                try:
                    h = hash(v)
                except TypeError:
                    h = hash(id(v))
                items.append((k, h))
            self._hash = hash(tuple(items))
        return self._hash

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        dict_schema = handler(dict[str, Any])

        def _serialize(v: Any) -> Any:
            if isinstance(v, FrozenDict):
                return {str(k): _serialize(val) for k, val in v._data.items()}
            if isinstance(v, (list, tuple)):
                return [_serialize(val) for val in v]
            if isinstance(v, (set, frozenset)):
                return [_serialize(val) for val in v]
            return v

        return core_schema.no_info_after_validator_function(
            cls,
            dict_schema,
            serialization=core_schema.plain_serializer_function_ser_schema(
                _serialize,
                return_schema=core_schema.dict_schema(),
            ),
        )
