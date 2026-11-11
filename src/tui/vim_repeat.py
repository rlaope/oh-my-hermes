"""IO-free, allocation-free-of-expanded-payload dot-repeat admission.

Call ``preflight(composer, change, count, continuation=False)`` BEFORE making a
candidate, copying maps, taking an undo snapshot, or reserving image tokens.
It returns a small immutable RepeatPlan, or raises ValueError.  The caller still
owns execution/rollback, undo, retention, and BEL.  No live Composer field is
written and no Composer allocation/mutation method is called.

The approved direction is an atom-reference virtual draft.  Existing Composer
semantic resolvers run unbound against a metered Sequence and identity atom
bounds; there is no key replay and no second implementation of word/object
semantics.  Only virtual splices and put/r payload construction are specialized.

Accounting is deliberately explicit and independently injectable. A *visit* is
one successful atom read: source atom emission, scalar Sequence access, each
member of a slice/iteration, or an atom read while splicing, yanking, stitching
Unicode boundaries, and resolving the final endpoint. Re-reading an atom really
charges again. Length/boundary arithmetic and moving opaque references in a
list splice do not inspect atoms and do not charge. Sequence exhaustion is not
a visit. Source character segmentation and metadata string comparisons are not
additional atom reads. All semantic helper scans go through the same Sequence;
there are no unmetered atom walks. Admission aborts BEFORE the excess read.

A step is one primitive replacement (including each opened-line newline and
an empty valid c replacement). A counted put/r is one replacement. Bytes are
UTF-8 of inserted text, plus chip expansions and image labels per inserted
occurrence; a chip's compact label and an image's token are included too.
Generated line delimiters and remapped chip labels count. Replaced/deleted
content is not an inserted payload. Image demand counts every fresh allocation
native put makes, even unused image-map entries. Limits are inclusive.

Virtual lists contain bounded atom references, never an expanded repeated
string or a copy of the real metadata maps. Unicode concatenation is restricted
to touching grapheme boundaries; it never joins an entire payload/draft.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, overload

# The native resolvers intentionally use a structural virtual self rather than
# a Composer instance. Keep that adapter boundary explicit to type checkers.
import unicodedata

from . import composer as _c
from . import width as _w

_Native: Any = _c.Composer

if TYPE_CHECKING:
    from .composer import Composer, _RepeatChange

MAX_STEPS = 16384
MAX_MATERIALIZED_BYTES = 2 * 1024 * 1024
MAX_FRESH_IMAGES = 512
MAX_ATOM_VISITS = 65536
TOKEN_CAPACITY = _c._TOKEN_LAST - _c._TOKEN_FIRST + 1
_INSERT_COMMANDS = frozenset(("i", "a", "I", "A", "o", "O"))


@dataclass(frozen=True)
class Limits:
    steps: int = MAX_STEPS
    materialized_bytes: int = MAX_MATERIALIZED_BYTES
    fresh_images: int = MAX_FRESH_IMAGES
    atom_visits: int = MAX_ATOM_VISITS


DEFAULT_LIMITS = Limits()


@dataclass(frozen=True)
class Work:
    steps: int
    materialized_bytes: int
    fresh_images: int
    atom_visits: int


@dataclass(frozen=True)
class RepeatPlan:
    count: int
    copies: int
    insertion: bool
    continuation: bool
    final_atoms: int
    final_caret_atom: int
    final_caret: int
    work: Work

    @property
    def atom_visits(self) -> int:
        return self.work.atom_visits


class PreflightError(ValueError):
    """A semantic or resource rejection; no live state has been changed."""


class LimitExceeded(PreflightError):
    def __init__(self, resource: str, limit: int, attempted: int):
        self.resource, self.limit, self.attempted = resource, limit, attempted
        super().__init__(f"dot repeat {resource} limit {limit} exceeded ({attempted})")


class WorkCounter:
    """Public counter/test seam; on_visit receives each approved cumulative read.

    Pass ``limits=Limits(atom_visits=n)`` or ``on_visit=callback`` to preflight.
    The callback observes virtual work only; it must not mutate the composer.
    """

    def __init__(self, limits: Limits = DEFAULT_LIMITS,
                 on_visit: Callable[[int], None] | None = None):
        if any(value < 0 for value in (limits.steps, limits.materialized_bytes,
                                      limits.fresh_images, limits.atom_visits)):
            raise ValueError("negative repeat limit")
        self.limits = limits
        self.steps = self.materialized_bytes = self.fresh_images = self.atom_visits = 0
        self.on_visit = on_visit

    def check(self, resource: str, amount: int) -> None:
        limit = getattr(self.limits, resource)
        if amount > limit:
            raise LimitExceeded(resource, limit, amount)

    def visit(self) -> None:
        value = self.atom_visits + 1
        self.check("atom_visits", value)
        self.atom_visits = value
        if self.on_visit is not None:
            self.on_visit(value)

    def step(self) -> None:
        self.check("steps", self.steps + 1)
        self.steps += 1

    def payload(self, amount: int) -> None:
        self.check("materialized_bytes", self.materialized_bytes + amount)
        self.materialized_bytes += amount

    def images(self, amount: int) -> None:
        self.check("fresh_images", self.fresh_images + amount)
        self.fresh_images += amount

    def result(self) -> Work:
        return Work(self.steps, self.materialized_bytes, self.fresh_images, self.atom_visits)


def _utf8(text: str) -> int:
    # Never encode a potentially enormous owned chip expansion into a new bytes.
    return sum(1 if ord(ch) < 0x80 else 2 if ord(ch) < 0x800 else
               3 if ord(ch) < 0x10000 else 4 for ch in text)


@dataclass(frozen=True)
class _Atom:
    value: str
    chip: str | None = None
    image: bool = False
    label: str | None = None


class _Atoms(Sequence[str]):
    """The single gateway for reading any virtual atom, including our own scans."""

    def __init__(self, work: WorkCounter):
        self._items: list[_Atom] = []
        self.work = work

    def __len__(self) -> int:
        return len(self._items)

    def atom(self, index: int) -> _Atom:
        # A failed/out-of-range access is not an atom visit.
        if not -len(self._items) <= index < len(self._items):
            raise IndexError(index)
        self.work.visit()
        return self._items[index]

    @overload
    def __getitem__(self, index: int) -> str: ...

    @overload
    def __getitem__(self, index: slice) -> list[str]: ...

    def __getitem__(self, index: int | slice) -> str | list[str]:
        if isinstance(index, slice):
            return [self.atom(at).value for at in range(*index.indices(len(self)))]
        return self.atom(index).value

    def __iter__(self) -> Iterator[str]:
        for at in range(len(self)):
            yield self[at]

    def refs(self, start: int = 0, end: int | None = None) -> Iterator[_Atom]:
        for at in range(start, len(self) if end is None else end):
            yield self.atom(at)

    def append_source(self, atom: _Atom) -> None:
        # Source traversal emits one atom. Storing/moving its reference is not
        # another visit; future consumers must use atom()/refs().
        self.work.visit()
        self._items.append(atom)

    def splice(self, start: int, end: int, refs: list[_Atom]) -> None:
        self._items[start:end] = refs


class _Pastes(Mapping[str, str]):
    """Borrow live metadata; keep only virtual additions and occurrence counts."""

    def __init__(self, base: Mapping[str, str]):
        self.base = base
        self.added: dict[str, str] = {}
        self.present: dict[str, int] = {}
        self.pruned = False

    def __getitem__(self, label: str) -> str:
        if self.pruned and not self.present.get(label, 0):
            raise KeyError(label)
        return self.added[label] if label in self.added else self.base[label]

    def __iter__(self):
        for label in self.base:
            if label not in self.added and (not self.pruned or self.present.get(label, 0)):
                yield label
        for label in self.added:
            if not self.pruned or self.present.get(label, 0):
                yield label

    def __len__(self):
        return sum(1 for _ in self)

    def adjust(self, atom: _Atom, amount: int) -> None:
        if atom.chip is not None:
            label = atom.label or atom.value
            self.present[label] = self.present.get(label, 0) + amount


def _probe(first: str, last: str, length: int) -> str:
    # width._extends only uses first, last, and the single-codepoint RI case.
    return first if length == 1 else first + last


def _source(text: str, pastes: Mapping[str, str], images: Mapping[str, object],
            work: WorkCounter) -> _Atoms:
    """Stream source atoms without Composer._atoms()/clusters(full_text).

    Chip labels are a bounded retained metadata vocabulary. A trie avoids an
    unmetered full draft search for every label. Longest matches agree with the
    composer's union of coincident chip spans for its generated label grammar.
    """
    trie: dict = {}
    for label in pastes:
        if not label:
            continue
        node = trie
        for ch in label:
            node = node.setdefault(ch, {})
        node[None] = label
    result = _Atoms(work)
    at = 0
    while at < len(text):
        node, scan, label = trie, at, None
        while scan < len(text) and text[scan] in node:
            node = node[text[scan]]
            scan += 1
            if None in node:
                label = node[None]
        if label is not None:
            start = at
            at += len(label)
            last = label[-1]
            while at < len(text) and _w._extends(_probe(label[0], last, at - start), text[at]):
                last = text[at]
                at += 1
            atom = _Atom(unicodedata.normalize("NFC", text[start:at]), pastes[label], label=label)
        else:
            start = at
            first = last = text[at]
            at += 1
            while at < len(text) and _w._extends(_probe(first, last, at - start), text[at]):
                last = text[at]
                at += 1
            value = text if start == 0 and at == len(text) else text[start:at]
            value = unicodedata.normalize("NFC", value)
            atom = _Atom(value, image=value[0] in images)
        result.append_source(atom)
    return result


class _Virtual:
    # These are the native semantic implementations, not approximations.
    _command = _Native._command
    _execute_repeat = _Native._execute_repeat
    _motion_span = _Native._motion_span
    _word_classes = _Native._word_classes
    _text_object_span = _Native._text_object_span
    _quote_object_span = _Native._quote_object_span
    _bracket_object_span = _Native._bracket_object_span
    _operate = _Native._operate
    _lines = _Native._lines
    _line_span = _Native._line_span
    _search = _Native._search
    _clamp_normal = _Native._clamp_normal

    def __init__(self, composer: Composer, work: WorkCounter):
        self.work = work
        self.pastes = _Pastes(composer.pastes)
        self.units = _source(composer.text, composer.pastes, composer.images, work)
        self.caret = 0  # Internal coordinates are always atom boundaries.
        chars = 0
        for atom in self.units.refs():
            self.pastes.adjust(atom, 1)
            if chars < composer.caret:
                self.caret += 1
            chars += len(atom.value)
        if composer.caret < 0 or composer.caret > chars:
            raise PreflightError("invalid composer caret")
        self.visual = False
        self.normal = composer.normal
        self.masked = composer.masked
        self._register = composer._register
        self._last_search = composer._last_search
        self._paste_count = composer._paste_count
        self._image_labels = composer.images  # borrowed, never copied or written
        self.initial_tokens: set[str] = set()
        # Atom reads, including token-capacity inspection, are metered.
        for atom in self.units.refs():
            for ch in atom.value:
                if _c._is_token(ch):
                    self.initial_tokens.add(ch)

    def _atoms(self):
        return self.units, range(len(self.units) + 1), self.caret

    def _drop_pending(self):
        pass  # Virtual semantic calls never dispatch or retain key grammar.

    def _enter_insert(self, change: bool = False):
        self.normal = False

    def _search_motion(self, *args, **kwargs):
        result = _Native._search_motion(self, *args, **kwargs)
        if result is None:
            raise PreflightError("repeat find target unavailable")
        return result

    def _operate_span(self, operator, span):
        if span is None:
            raise PreflightError("repeat motion/object unavailable")
        if not (0 <= span[0] <= span[1] <= len(self.units)):
            raise PreflightError("repeat span out of bounds")
        if operator != "c" and span[0] == span[1]:
            raise PreflightError("empty repeat deletion")
        _Native._operate_span(self, operator, span)

    def _yank(self, start, end, linewise):
        # Native register acquisition reads each deleted atom; no text/map copy.
        for _atom in self.units.refs(start, end):
            pass

    def _contains(self, needle: str) -> bool:
        # KMP scans the virtual string, including matches across atom boundaries.
        if not needle:
            return True
        fail = [0] * len(needle)
        size = 0
        for at in range(1, len(needle)):
            while size and needle[at] != needle[size]:
                size = fail[size - 1]
            if needle[at] == needle[size]:
                size += 1
            fail[at] = size
        size = 0
        for atom in self.units.refs():
            for ch in atom.value:
                while size and ch != needle[size]:
                    size = fail[size - 1]
                if ch == needle[size]:
                    size += 1
                if size == len(needle):
                    return True
        return False

    def _chip_label(self, cleaned: str, taken=()):
        cut = len(cleaned)
        while cut and cleaned[cut - 1] == _c.NEWLINE:
            cut -= 1
        lines = cleaned.count(_c.NEWLINE, 0, cut) + 1
        while True:
            self._paste_count += 1
            label = (_c.PASTE_CHIP.format(number=self._paste_count, lines=lines)
                     if lines > 1 else _c.PASTE_CHIP_ONE_LINE.format(
                         number=self._paste_count, chars=len(cleaned)))
            if label not in self.pastes and label not in taken and not self._contains(label):
                return label

    def _payload_bytes(self, atoms: _Atoms) -> int:
        total = 0
        for atom in atoms.refs():
            total += _utf8(atom.value)
            if atom.chip is not None:
                total += _utf8(atom.chip)
            if atom.image and atom.value in self._image_labels:
                total += _utf8(self._image_labels[atom.value][0])
        return total

    def _replace(self, start: int, end: int, insert: str = ""):
        payload = _source(insert, self.pastes, self._image_labels, self.work)
        self.work.payload(self._payload_bytes(payload))
        self._splice(start, end, payload.refs())

    def _splice(self, start: int, end: int, payload: Iterator[_Atom]):
        if not 0 <= start <= end <= len(self.units):
            raise PreflightError("insertion recipe out of bounds")
        self.work.step()
        for atom in self.units.refs(start, end):
            self.pastes.adjust(atom, -1)
        # Touch only adjacent graphemes. Ordinary copies do not walk the draft.
        left = start - 1 if start else start
        right = end
        folded = _Atoms(self.work)
        if left < start:
            atom = self.units.atom(left)
            self.pastes.adjust(atom, -1)
            folded._items.append(atom)

        def append(atom):
            if folded and atom.chip is None:
                previous = folded.atom(-1)
                if _w._extends(previous.value, atom.value[0]):
                    # Only a touching glyph can join. Never concatenate payloads.
                    value = unicodedata.normalize("NFC", previous.value + atom.value)
                    if previous.chip is not None:
                        folded._items[-1] = _Atom(value, previous.chip, label=previous.label or previous.value)
                        return
                    parts = _w._segment(value)
                    folded._items.pop()
                    for part in parts:
                        if previous.image and part[0] == previous.value[0]:
                            folded._items.append(_Atom(previous.value[0], image=True))
                        else:
                            folded._items.append(_Atom(part, image=atom.image and part[0] == atom.value[0]))
                    return
            folded._items.append(atom)

        for atom in payload:
            append(atom)
        # This is NFC(prefix through insertion), just as native _set computes.
        endpoint = sum(len(atom.value) for atom in folded.refs())
        while right < len(self.units):
            atom = self.units.atom(right)
            if folded:
                previous = folded.atom(-1)
                joins = (atom.chip is None
                         and _w._extends(previous.value, atom.value[0]))
            else:
                joins = False
            if not joins:
                break
            self.pastes.adjust(atom, -1)
            append(atom)
            right += 1
        # Resolve the insertion boundary; an endpoint inside a joined glyph
        # floors to that glyph's boundary, matching Composer._set.
        chars = 0
        caret = left
        for offset, atom in enumerate(folded.refs()):
            chars += len(atom.value)
            if chars <= endpoint:
                caret = left + offset + 1
            self.pastes.adjust(atom, 1)
        self.units.splice(left, right, folded._items)
        self.caret = caret
        self.pastes.pruned = True

    def _replace_chars(self, char: str, times: int):
        cleaned = _c._clean(char, self.masked)
        _start, end = _c._line_of(self.units, self.caret)
        if not cleaned or _c.NEWLINE in cleaned or self.caret + times > end:
            raise PreflightError("repeat replacement extent unavailable")
        payload = _source(cleaned, self.pastes, self._image_labels, self.work)
        self.work.payload(self._payload_bytes(payload) * times)
        at = self.caret
        self._splice(at, at + times,
                     (atom for _ in range(times) for atom in payload.refs()))
        if self.caret > 0:
            self.caret -= 1

    def _put(self, after: bool, times: int):
        register = self._register
        if register is None or (not register.text and not register.linewise):
            raise PreflightError("repeat put payload unavailable")
        # Remapping is virtual metadata. No text.replace/translate/join, token
        # generation, opaque image retention, or real map copy occurs here.
        source = _source(register.text, register.pastes, register.images, self.work)
        remaps: dict[str, str] = {}
        for label, pasted in register.pastes.items():
            if (self.pastes.get(label, pasted) != pasted
                    or (label not in self.pastes and self._contains(label))):
                new = self._chip_label(pasted, taken=register.pastes)
                remaps[label] = new
                label = new
            self.pastes.added[label] = pasted
            # Native map insertion precedes _replace's metadata pruning.
        per_copy = 0
        for atom in source.refs():
            label = atom.label or atom.value
            mapped = remaps.get(label, label)
            per_copy += _utf8(mapped) + (_utf8(atom.value[len(label):]) if atom.label else 0)
            if atom.chip is not None:
                per_copy += _utf8(atom.chip)
            if atom.image and atom.value in register.images:
                per_copy += _utf8(register.images[atom.value][0])
        self.work.payload(per_copy * times + (times if register.linewise else 0))
        self.work.images(len(register.images) * times)
        start, end = _c._line_of(self.units, self.caret)
        at = (end if after else start) if register.linewise else (
            self.caret + 1 if after and self.caret < end else self.caret)

        def copies():
            if register.linewise and after:
                self.work.visit()
                yield _Atom(_c.NEWLINE)
            for copy in range(times):
                if register.linewise and copy:
                    self.work.visit()
                    yield _Atom(_c.NEWLINE)
                for atom in source.refs():
                    if atom.image:
                        # A private-use placeholder is indistinguishable to
                        # semantic scans, but is NOT a token reservation.
                        yield _Atom(chr(_c._TOKEN_FIRST), image=True)
                    elif (atom.label or atom.value) in remaps:
                        label = atom.label or atom.value
                        mapped = remaps[label]
                        yield _Atom(mapped + atom.value[len(label):], atom.chip, label=mapped)
                    else:
                        yield atom
            if register.linewise and not after:
                self.work.visit()
                yield _Atom(_c.NEWLINE)

        self._splice(at, at, copies())
        if register.linewise:
            self.caret = at + 1 if after else at
            line_start, line_end = _c._line_of(self.units, self.caret)
            self.caret = _c._first_blank_free(self.units, line_start, line_end)
        elif self.caret > 0:
            self.caret -= 1

    def recipe(self, change: _RepeatChange):
        origin = self.caret
        for offset, deleted, payload in change.recipe:
            at = origin + offset
            if deleted < 0 or not 0 <= at <= at + deleted <= len(self.units):
                raise PreflightError("insertion recipe out of bounds")
            self._replace(at, at + deleted, payload)
        endpoint = origin + change.terminal
        if not 0 <= endpoint <= len(self.units):
            raise PreflightError("insertion endpoint out of bounds")
        self.caret = endpoint


def _validate(change: _RepeatChange) -> tuple[bool, bool]:
    command = change.command
    insertion = command in _INSERT_COMMANDS or command in ("s", "S", "C") or command.startswith("c")
    valid = command in _INSERT_COMMANDS or command in ("x", "X", "s", "S", "D", "C", "p", "P")
    if command.startswith("r") and len(command) > 1:
        valid = True
    if len(command) >= 2 and command[0] in "dc":
        tail = command[1:]
        valid = ((tail.startswith(("V", "L")) and tail[1:].isascii() and tail[1:].isdigit()) or tail in (command[0], "h", "l", "0", "^", "$", "w", "W", "b", "B", "e", "E", "ge", "gE", "j", "k", "gg", "G")
                 or (len(tail) == 2 and tail[0] in "ia"
                     and tail[1] in ("w", *_c._QUOTE_CHARS, *_c._BRACKET_PAIRS))
                 or (len(tail) == 2 and tail[0] in "fFtT"))
    if not valid or (change.recipe and not insertion):
        raise PreflightError("unsupported semantic repeat descriptor")
    return insertion, command in _INSERT_COMMANDS


def preflight(composer: Composer, change: _RepeatChange, count: int,
              continuation: bool = False, *, limits: Limits = DEFAULT_LIMITS,
              on_visit: Callable[[int], None] | None = None) -> RepeatPlan:
    """Approve a whole replay without changing/allocating any Composer state.

    count is the effective (already overridden) count; like grammar, it saturates
    at 9999. continuation is only for extra counted insertion copies, while the
    live session is still INSERT. final_caret is a native string offset;
    final_caret_atom is an atom boundary. Neither is the next copy's origin:
    recipe copies use the preceding terminal INSERT endpoint until one final
    native INSERT->NORMAL transition. A plan is valid only for this exact draft.
    """
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise PreflightError("invalid repeat count")
    count = min(count, _c.VIM_COUNT_CAP)
    insertion, repeated = _validate(change)
    if continuation and not repeated:
        raise PreflightError("continuation requires an insertion command")
    copies = count if repeated else 1
    work = WorkCounter(limits, on_visit)
    structural = copies if change.command in ("o", "O") else 0
    leading = 0 if repeated else 1
    work.check("steps", len(change.recipe) * copies + structural + leading)
    # Arithmetic admission before source atomization, label remapping, or any
    # counted expansion. More precise put metadata accounting follows virtually.
    recipe_bytes = sum(_utf8(payload) for _at, _deleted, payload in change.recipe)
    work.check("materialized_bytes", recipe_bytes * copies + structural)
    if change.command.startswith("r"):
        work.check("materialized_bytes", _utf8(_c._clean(change.command[1:], composer.masked)) * count)
    if change.command in ("p", "P"):
        register = change.register
        if register is None or (not register.text and not register.linewise):
            raise PreflightError("repeat put payload unavailable")
        work.check("fresh_images", len(register.images) * count)
        work.check("materialized_bytes", _utf8(register.text) * count
                   + (count if register.linewise else 0))
    virtual = _Virtual(composer, work)
    demand = (len(change.register.images) * count
              if change.command in ("p", "P") and change.register is not None else 0)
    # Pool occupancy is a union, not len(images): unmapped PUA text and stale
    # mapped tokens both make candidates unavailable to native _new_token.
    for token in composer.images:
        if len(token) == 1 and _c._is_token(token):
            virtual.initial_tokens.add(token)
    if demand > TOKEN_CAPACITY - len(virtual.initial_tokens):
        raise PreflightError("image token pool exhausted")
    for number in range(copies):
        if not continuation or change.command in ("o", "O"):
            if number == 0 or change.command in ("o", "O"):
                virtual._execute_repeat(change, 1 if repeated else count)
        if insertion:
            # Failed leading c motions must never be followed by a recipe.
            if virtual.normal:
                raise PreflightError("repeat change did not enter INSERT")
            virtual.recipe(change)
    if insertion and not continuation:
        virtual.normal = True
        if virtual.caret > 0 and virtual.units[virtual.caret - 1] != _c.NEWLINE:
            virtual.caret -= 1
    if not continuation:
        virtual._clamp_normal()
    char_caret = sum(len(atom.value) for atom in virtual.units.refs(0, virtual.caret))
    return RepeatPlan(count, copies, insertion, continuation, len(virtual.units),
                      virtual.caret, char_caret, work.result())
