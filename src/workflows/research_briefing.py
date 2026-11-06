"""Deterministic projection of a research run into a reader-facing briefing.

The engine's other outputs are written for a machine consumer. This one is
written for a person, so the shape it must hold is a writing standard rather
than a data contract: noun-phrase titles carrying a role label, figures drawn
as code blocks, every time-dependent figure carrying its as-of date. The rules
live in `skills/ulw-research/references/briefing-format.md`; the ones a
function can decide are checked here, because a prose rule no surface
validates is a hope.

Nothing in this module reaches the network, spawns a process, or opens a file
viewer. `render_research_briefing_page` returns one self-contained HTML
document with its own print rules; turning that into a PDF is the reader's
print dialog or an explicit generation handoff, never a claim OMH makes.
"""

from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import urlsplit

from .temporal_source_receipts import validate_temporal_source_receipt

RESEARCH_BRIEFING_SCHEMA_VERSION = "research_briefing/v1"

#: The interview answer that decides which document the run produces.
BRIEFING_AUDIENCES = ("human_briefing", "coding_agent_handoff")

#: Asked only on the human branch. `page` is a print-ready HTML document.
BRIEFING_OUTPUT_FORMATS = ("markdown", "page", "both")

#: Closed vocabulary. Without a role label a reader cannot tell whether a
#: section states a problem, an advantage, or an observation.
BRIEFING_ROLE_LABELS = (
    "concept",
    "problem",
    "option",
    "solution",
    "reversal",
    "case",
    "guideline",
    "constraint",
    "pitfall",
    "limit",
    "cost",
    "deployment",
    "check",
)

#: Scaffolding captions the document renders around the author's own prose.
#: The document body may be written in any language, and a Korean briefing with
#: English section captions is a half-translated document. OMH does not own a
#: translation table -- it would have to be maintained for every language the
#: engine can write in -- so callers supply every rendered label for non-English
#: documents. Only explicitly English documents may use the English defaults.
BRIEFING_CAPTION_KEYS = (
    "question",
    "as_of",
    "learning_objectives",
    "assumed_knowledge",
    "out_of_scope",
    "figures",
    "figure_value",
    "figure_basis",
    "figure_as_of",
    "glossary",
    "traps",
    "sources",
    "basis_measured",
    "basis_assumed",
    "basis_derived",
    "source_class_upstream_official",
    "source_class_practitioner",
    "source_class_unattributed",
    "retrieved_on",
    "live_page",
    "historical_capture",
    "capture_time_unknown",
    "capture_provider",
    "claim_boundary",
)

_DEFAULT_CAPTIONS = {
    "question": "Question",
    "as_of": "As of",
    "learning_objectives": "What you can do after reading",
    "assumed_knowledge": "Assumed knowledge",
    "out_of_scope": "Out of scope",
    "figures": "Figures",
    "figure_value": "Value",
    "figure_basis": "Basis",
    "figure_as_of": "As of",
    "glossary": "Appendix A: glossary",
    "traps": "Appendix B: misconceptions and traps",
    "sources": "Appendix C: sources",
    "basis_measured": "measured",
    "basis_assumed": "assumed",
    "basis_derived": "derived",
    "source_class_upstream_official": "upstream_official",
    "source_class_practitioner": "practitioner",
    "source_class_unattributed": "unattributed",
    "retrieved_on": "retrieved",
    "live_page": "live page",
    "historical_capture": "historical capture",
    "capture_time_unknown": "capture time unknown",
    "capture_provider": "via",
}

#: A figure is measured, assumed, or derived; the axis is separate from the
#: source class below, and neither one settles completion.
BRIEFING_FIGURE_BASES = ("measured", "assumed", "derived")

#: Upstream official guidance is the strongest class and still not evidence
#: that anything was done.
BRIEFING_SOURCE_CLASSES = ("upstream_official", "practitioner", "unattributed")

#: Connectives whose deletion leaves the claim intact, plus the intensifiers
#: the format bans outright.
_BANNED_PROSE = (
    "dramatically",
    "overwhelmingly",
    "decisively",
    "game-changing",
    "revolutionary",
)

BRIEFING_CLAIM_BOUNDARY = (
    "A research briefing is prepared decision context. It is not execution, review, CI, "
    "merge-readiness, or merge evidence, and a rendered page is not a rendered PDF without "
    "observed file evidence."
)

_EXPORT_STATUSES = ("prepared", "handoff_prepared", "rendered_observed")


def _rows(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def research_briefing_errors(value: Any) -> list[str]:
    """Return every contract and format violation, most structural first."""
    issues: list[str] = []
    if not isinstance(value, dict):
        return ["research briefing must be a mapping"]
    if value.get("schema_version") != RESEARCH_BRIEFING_SCHEMA_VERSION:
        issues.append(f"schema_version must be {RESEARCH_BRIEFING_SCHEMA_VERSION}")

    audience = _text(value.get("audience"))
    if audience not in BRIEFING_AUDIENCES:
        issues.append(f"audience must be one of {', '.join(BRIEFING_AUDIENCES)}")
    formats = [_text(item) for item in _rows(value.get("output_formats"))]
    if audience == "human_briefing":
        if not formats:
            issues.append("human_briefing must declare at least one output format")
        for item in formats:
            if item not in BRIEFING_OUTPUT_FORMATS:
                issues.append(f"unknown output format {item!r}")
    elif formats:
        issues.append("coding_agent_handoff takes no output format; the format question is human-only")

    if not _text(value.get("language")):
        issues.append("language must be declared explicitly; it is never inferred from the request")
    if not _text(value.get("question")):
        issues.append("question is required")
    if not _text(value.get("title")):
        issues.append("title is required; both renderers print it")
    if not _text(value.get("as_of")):
        issues.append("as_of is required so time-dependent figures carry their date")

    issues.extend(_section_errors(_rows(value.get("sections"))))
    issues.extend(_figure_errors(_rows(value.get("figures"))))
    issues.extend(_source_errors(_rows(value.get("sources"))))

    issues.extend(_label_errors(value.get("role_labels"), BRIEFING_ROLE_LABELS, "role_labels"))
    issues.extend(_label_errors(value.get("captions"), BRIEFING_CAPTION_KEYS, "captions"))
    issues.extend(_translation_errors(value))

    export = value.get("export")
    if not isinstance(export, dict):
        issues.append("export must be a mapping of format to status")
    else:
        for key, status in export.items():
            if _text(status) not in _EXPORT_STATUSES:
                issues.append(f"export status for {key!r} must be one of {', '.join(_EXPORT_STATUSES)}")
    if _text(value.get("claim_boundary")) != BRIEFING_CLAIM_BOUNDARY:
        issues.append("claim_boundary must be the exact briefing boundary sentence")
    return issues


def _translation_errors(value: dict[str, Any]) -> list[str]:
    """Require caller-owned translations for the union of both renderers' labels.

    This is a completeness check, not language detection or translation review.
    The structured boundary and receipt vocabulary stay unchanged in the payload.
    """
    if not _text(value.get("language")) or _text(value["language"]).casefold() == "en":
        return []
    roles = {
        _text(section.get("role")) for section in _rows(value.get("sections"))
        if isinstance(section, dict) and _text(section.get("role")) in BRIEFING_ROLE_LABELS
    }
    keys = {"question", "as_of", "claim_boundary"}
    for key in ("learning_objectives", "assumed_knowledge", "out_of_scope", "glossary", "traps", "sources"):
        if _rows(value.get(key)):
            keys.add(key)
    if _rows(value.get("figures")):
        keys.update(("figures", "figure_value", "figure_basis", "figure_as_of"))
        for figure in _rows(value["figures"]):
            if isinstance(figure, dict) and _text(figure.get("basis")) in BRIEFING_FIGURE_BASES:
                keys.add(f"basis_{_text(figure['basis'])}")
    for source in _rows(value.get("sources")):
        if not isinstance(source, dict):
            continue
        keys.add("retrieved_on")
        if _text(source.get("source_class")) in BRIEFING_SOURCE_CLASSES:
            keys.add(f"source_class_{_text(source['source_class'])}")
        receipt = source.get("temporal_source_receipt")
        if isinstance(receipt, dict):
            if receipt.get("evidence_kind") == "live_page":
                keys.add("live_page")
            else:
                keys.update(("historical_capture", "capture_provider"))
                if not _text(receipt.get("captured_at")):
                    keys.add("capture_time_unknown")
    issues: list[str] = []
    for where, required in (("role_labels", roles), ("captions", keys)):
        labels = value.get(where)
        for key in sorted(required):
            if not isinstance(labels, dict) or not _text(labels.get(key)):
                issues.append(f"{where}: {key!r} is required for a non-English briefing")
    return issues


def _label_errors(value: Any, allowed: tuple[str, ...], where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, dict):
        return [f"{where} must be a mapping"]
    issues: list[str] = []
    for key, label in value.items():
        if key not in allowed:
            issues.append(f"{where}: {key!r} is not one of {', '.join(allowed)}")
        if not _text(label):
            issues.append(f"{where}: {key!r} has an empty label")
    return issues


def _section_errors(sections: list[Any]) -> list[str]:
    issues: list[str] = []
    if not sections:
        return ["at least one section is required"]
    seen: set[str] = set()
    for index, section in enumerate(sections):
        where = f"section {index}"
        if not isinstance(section, dict):
            issues.append(f"{where} must be a mapping")
            continue
        role = _text(section.get("role"))
        if role not in BRIEFING_ROLE_LABELS:
            issues.append(f"{where}: role must be one of {', '.join(BRIEFING_ROLE_LABELS)}")
        title = _text(section.get("title"))
        issues.extend(f"{where}: {problem}" for problem in _title_errors(title))
        key = title.casefold()
        if key and key in seen:
            issues.append(f"{where}: title {title!r} repeats an earlier section title")
        seen.add(key)
        paragraphs = [_text(item) for item in _rows(section.get("paragraphs"))]
        if not paragraphs:
            issues.append(f"{where}: at least one paragraph is required")
        for paragraph in paragraphs:
            issues.extend(f"{where}: {problem}" for problem in _prose_errors(paragraph))
    return issues


def _title_errors(title: str) -> list[str]:
    """Check the title rules a function can decide."""
    issues: list[str] = []
    if not title:
        return ["title is required"]
    if title.endswith((".", "!")):
        issues.append(f"title {title!r} is a sentence; compress it to a noun phrase")
    if title.endswith("?"):
        issues.append(f"title {title!r} is a question; name the subject instead")
    if title[0].isdigit() or title[0] in "①②③④⑤⑥⑦⑧⑨":
        issues.append(f"title {title!r} opens with numeric scaffolding")
    return issues


def _prose_errors(paragraph: str) -> list[str]:
    issues: list[str] = []
    folded = paragraph.casefold()
    for banned in _BANNED_PROSE:
        if banned in folded:
            issues.append(f"paragraph uses the banned intensifier {banned!r}")
    if paragraph.endswith("?"):
        issues.append("paragraph ends on a rhetorical question")
    return issues


def _figure_errors(figures: list[Any]) -> list[str]:
    issues: list[str] = []
    for index, figure in enumerate(figures):
        where = f"figure {index}"
        if not isinstance(figure, dict):
            issues.append(f"{where} must be a mapping")
            continue
        if not _text(figure.get("label")):
            issues.append(f"{where}: label is required")
        if _text(figure.get("basis")) not in BRIEFING_FIGURE_BASES:
            issues.append(f"{where}: basis must be one of {', '.join(BRIEFING_FIGURE_BASES)}")
        if not _text(figure.get("value")):
            issues.append(f"{where}: value is required")
        if _text(figure.get("basis")) == "measured" and not _text(figure.get("as_of")):
            issues.append(f"{where}: a measured figure carries the date it was measured")
    return issues


def _source_errors(sources: list[Any]) -> list[str]:
    issues: list[str] = []
    for index, source in enumerate(sources):
        where = f"source {index}"
        if not isinstance(source, dict):
            issues.append(f"{where} must be a mapping")
            continue
        # IDs are optional, but supplied values must render without coercion loss.
        # Bound integers before conversion, independently of Python's digit limit.
        # Nonblank strings are opaque identifiers: never strip or normalize them.
        identifier = source.get("id")
        if identifier is not None and not (
            (type(identifier) is int and 1 <= identifier <= 2**63 - 1)
            or (isinstance(identifier, str) and bool(identifier.strip()))
        ):
            issues.append(f"{where}: id must be a nonblank string or an integer from 1 to 9223372036854775807 (not bool)")
        if not _text(source.get("title")):
            issues.append(f"{where}: title is required")
        if _text(source.get("source_class")) not in BRIEFING_SOURCE_CLASSES:
            issues.append(f"{where}: source_class must be one of {', '.join(BRIEFING_SOURCE_CLASSES)}")
        if not _text(source.get("retrieved_on")):
            issues.append(f"{where}: retrieved_on is required for a cited source")
        if source.get("url") not in (None, "") and not _safe_source_url(source["url"]):
            issues.append(f"{where}: url must be an absolute http or https URL without credentials or whitespace")
        issues.extend(f"{where}: {problem}" for problem in _source_receipt_errors(source))
    return issues


def _safe_source_url(value: Any) -> bool:
    """Validate navigation only; never fetch, repair, or normalize a citation."""
    if not isinstance(value, str) or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    if "\\" in value:
        return False
    try:
        parts = urlsplit(value)
        return (
            parts.scheme in ("http", "https") and bool(parts.hostname)
            and parts.username is None and parts.password is None
            and (parts.port is None or 0 < parts.port <= 65535)
        )
    except ValueError:
        return False


def _source_receipt_errors(source: dict[str, Any]) -> list[str]:
    """A source may carry its `temporal_source_receipt/v1`, unchanged.

    The briefing is a consumer, not an author: it validates the receipt with
    the receipt's own validator and refuses a source whose class or URL
    disagrees with it, because a receipt whose meaning the citation contradicts
    has not been preserved.
    """
    receipt = source.get("temporal_source_receipt")
    if receipt is None:
        return []
    issues = validate_temporal_source_receipt(receipt)
    if issues:
        return issues
    if _text(source.get("source_class")) != receipt["source_class"]:
        issues.append("source_class must match the temporal_source_receipt it carries")
    if _text(source.get("url")) and _text(source.get("url")) != receipt["source_url"]:
        issues.append("url must match the temporal_source_receipt source_url it carries")
    return issues


def _source_capture_note(value: Any, source: dict[str, Any]) -> str:
    """The capture clock, kept apart from the retrieval clock the line already carries."""
    receipt = source.get("temporal_source_receipt")
    if not isinstance(receipt, dict):
        return ""
    if receipt.get("evidence_kind") == "live_page":
        return f", {_caption(value, 'live_page')}"
    captured = _text(receipt.get("captured_at")) or _caption(value, "capture_time_unknown")
    return (f", {_caption(value, 'historical_capture')} {captured} "
            f"{_caption(value, 'capture_provider')} {receipt.get('capture_provider', '')}")


def build_research_briefing(
    *,
    audience: str,
    question: str,
    as_of: str,
    language: str,
    output_formats: tuple[str, ...] = (),
    title: str = "",
    learning_objectives: tuple[str, ...] = (),
    assumed_knowledge: tuple[str, ...] = (),
    out_of_scope: tuple[str, ...] = (),
    sections: tuple[dict[str, Any], ...] = (),
    figures: tuple[dict[str, Any], ...] = (),
    glossary: tuple[dict[str, str], ...] = (),
    traps: tuple[str, ...] = (),
    sources: tuple[dict[str, Any], ...] = (),
    role_labels: dict[str, str] | None = None,
    captions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Assemble the payload and validate it before returning."""
    payload: dict[str, Any] = {
        "schema_version": RESEARCH_BRIEFING_SCHEMA_VERSION,
        "audience": audience,
        "output_formats": list(output_formats),
        "language": language,
        "title": title or question,
        "question": question,
        "as_of": as_of,
        "learning_objectives": list(learning_objectives),
        "assumed_knowledge": list(assumed_knowledge),
        "out_of_scope": list(out_of_scope),
        "sections": [dict(section) for section in sections],
        "figures": [dict(figure) for figure in figures],
        "glossary": [dict(entry) for entry in glossary],
        "traps": list(traps),
        "sources": [dict(source) for source in sources],
        "role_labels": dict(role_labels or {}),
        "captions": dict(captions or {}),
        # Preparing a document is never rendering one, so every declared
        # format starts at `prepared` and only observed file evidence moves it.
        "export": {name: "prepared" for name in output_formats},
        "claim_boundary": BRIEFING_CLAIM_BOUNDARY,
    }
    issues = research_briefing_errors(payload)
    if issues:
        raise ValueError(issues[0])
    return payload


def _role_label(value: Any, role: str) -> str:
    labels = value.get("role_labels")
    if isinstance(labels, dict) and _text(labels.get(role)):
        return _text(labels[role])
    return role.capitalize()


def _caption(value: Any, key: str) -> str:
    captions = value.get("captions")
    if isinstance(captions, dict) and _text(captions.get(key)):
        return _text(captions[key])
    return BRIEFING_CLAIM_BOUNDARY if key == "claim_boundary" else _DEFAULT_CAPTIONS[key]


def _section_heading(value: Any, section: dict[str, Any]) -> str:
    return f"{_role_label(value, _text(section['role']))} - {section['title']}"


def render_research_briefing_markdown(value: Any) -> str:
    """Render the briefing as Markdown in the structure the format requires."""
    issues = research_briefing_errors(value)
    if issues:
        raise ValueError(issues[0])
    lines: list[str] = [f"# {value['title']}", ""]
    lines.append(f"{_caption(value, 'question')}: {value['question']}")
    lines.append(f"{_caption(value, 'as_of')}: {value['as_of']}")
    lines.append("")
    for key in ("learning_objectives", "assumed_knowledge", "out_of_scope"):
        rows = _rows(value.get(key))
        if rows:
            lines.extend([f"## {_caption(value, key)}", ""])
            lines.extend(f"- {item}" for item in rows)
            lines.append("")
    for section in _rows(value.get("sections")):
        lines.extend([f"## {_section_heading(value, section)}", ""])
        for paragraph in _rows(section.get("paragraphs")):
            lines.extend([str(paragraph), ""])
        figure = _text(section.get("figure"))
        if figure:
            lines.extend(["```", figure, "```", ""])
    figures = _rows(value.get("figures"))
    if figures:
        lines.extend([f"## {_caption(value, 'figures')}", ""])
        for figure in figures:
            stamp = f", {figure['as_of']}" if _text(figure.get("as_of")) else ""
            basis = _caption(value, f"basis_{_text(figure['basis'])}")
            lines.append(f"- {figure['label']}: {figure['value']} ({basis}{stamp})")
        lines.append("")
    glossary = _rows(value.get("glossary"))
    if glossary:
        lines.extend([f"## {_caption(value, 'glossary')}", ""])
        lines.extend(f"- {entry['term']}: {entry['definition']}" for entry in glossary)
        lines.append("")
    traps = _rows(value.get("traps"))
    if traps:
        lines.extend([f"## {_caption(value, 'traps')}", ""])
        lines.extend(f"- {item}" for item in traps)
        lines.append("")
    sources = _rows(value.get("sources"))
    if sources:
        lines.extend([f"## {_caption(value, 'sources')}", ""])
        for source in sources:
            location = f" - {_markdown_source_text(source['url'])}" if _text(source.get("url")) else ""
            identifier = f"[{_markdown_source_text(source['id'])}] " if source.get("id") is not None else ""
            lines.append(
                f"- {identifier}{_markdown_source_text(source['title'])}{location} "
                f"({_markdown_source_text(_caption(value, 'source_class_' + _text(source['source_class'])))}, "
                f"{_markdown_source_text(_caption(value, 'retrieved_on'))} "
                f"{_markdown_source_text(source['retrieved_on'])}"
                f"{_markdown_source_text(_source_capture_note(value, source))})"
            )
        lines.append("")
    lines.extend([f"> {_caption(value, 'claim_boundary')}", ""])
    return "\n".join(lines)


def _markdown_source_text(value: Any) -> str:
    """Keep untrusted citation fields as text, not HTML or Markdown syntax."""
    text = str(value)
    return "".join(
        f"&#{ord(char)};"
        if char in "\\`*{}[]\n\r" or (
            char == "_" and not (
                0 < index < len(text) - 1 and text[index - 1].isalnum() and text[index + 1].isalnum()
            )
        )
        else escape(char, quote=False)
        for index, char in enumerate(text)
    )


def _page_source_location(source: dict[str, Any]) -> str:
    """An inert navigation link whose visible URL also survives printing."""
    url = source.get("url")
    location = f' - <a href="{escape(str(url))}">{escape(str(url))}</a>' if _text(url) else ""
    identifier = f"[{escape(str(source['id']))}] " if source.get("id") is not None else ""
    return f"{identifier}{escape(str(source['title']))}{location}"


def _page_list(heading: str, rows: list[Any]) -> str:
    """Render one captioned list, or nothing when the list is empty."""
    if not rows:
        return ""
    items = "".join(f"<li>{escape(str(item))}</li>" for item in rows)
    return f"<section><h2>{escape(heading)}</h2><ul>{items}</ul></section>"


def _page_section(value: Any, section: dict[str, Any]) -> str:
    paragraphs = "".join(f"<p>{escape(str(item))}</p>" for item in _rows(section.get("paragraphs")))
    figure = _text(section.get("figure"))
    drawing = f"<pre>{escape(figure)}</pre>" if figure else ""
    return (
        f"<section class=\"sec\"><h2>{escape(_section_heading(value, section))}</h2>{paragraphs}{drawing}</section>"
    )


def render_research_briefing_page(value: Any) -> str:
    """One self-contained, print-ready HTML document. No external request.

    Every font is a stack of faces the reader already has, because a `<link>`
    to a web font would fetch at open time -- the shape the repo's network
    invariant exists to prevent. `@page` and the print block are what make the
    reader's own print dialog produce a sane PDF.
    """
    issues = research_briefing_errors(value)
    if issues:
        raise ValueError(issues[0])
    sections = "".join(_page_section(value, section) for section in _rows(value.get("sections")))
    figures = _rows(value.get("figures"))
    figure_rows = "".join(
        "<tr><td>{label}</td><td>{amount}</td><td>{basis}</td><td>{stamp}</td></tr>".format(
            label=escape(str(figure.get("label", ""))),
            amount=escape(str(figure.get("value", ""))),
            basis=escape(_caption(value, f"basis_{_text(figure['basis'])}")),
            stamp=escape(str(figure.get("as_of", "") or "-")),
        )
        for figure in figures
    )
    figure_block = (
        f"<section><h2>{escape(_caption(value, 'figures'))}</h2><table><thead><tr>"
        f"<th>{escape(_caption(value, 'figures'))}</th>"
        f"<th>{escape(_caption(value, 'figure_value'))}</th>"
        f"<th>{escape(_caption(value, 'figure_basis'))}</th>"
        f"<th>{escape(_caption(value, 'figure_as_of'))}</th>"
        f"</tr></thead><tbody>{figure_rows}</tbody></table></section>"
        if figures
        else ""
    )
    glossary = _rows(value.get("glossary"))
    glossary_block = (
        f"<section><h2>{escape(_caption(value, 'glossary'))}</h2><dl>"
        + "".join(
            f"<dt>{escape(str(entry.get('term', '')))}</dt>"
            f"<dd>{escape(str(entry.get('definition', '')))}</dd>"
            for entry in glossary
        )
        + "</dl></section>"
        if glossary
        else ""
    )
    sources = _rows(value.get("sources"))
    source_block = (
        f"<section><h2>{escape(_caption(value, 'sources'))}</h2><ol>"
        + "".join(
            "<li>{title}<span class=\"muted\"> &middot; {cls} &middot; {retrieved} {stamp}{capture}</span></li>".format(
                title=_page_source_location(source),
                cls=escape(_caption(value, f"source_class_{_text(source['source_class'])}")),
                retrieved=escape(_caption(value, "retrieved_on")),
                stamp=escape(str(source.get("retrieved_on", ""))),
                capture=escape(_source_capture_note(value, source)),
            )
            for source in sources
        )
        + "</ol></section>"
        if sources
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="{escape(str(value['language']))}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(str(value['title']))}</title>
<style>
  :root {{
    --page: #fdfdfc; --ink: #1a1a16; --muted: #6c6c62; --hair: #e2e2da; --rule: #c8c8bd;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --page: #131312; --ink: #f0f0ea; --muted: #9a9a90; --hair: #2d2d29; --rule: #43433d; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 3rem 1.5rem 5rem; background: var(--page); color: var(--ink);
    font-family: 'Iowan Old Style', 'Palatino Linotype', Palatino, Georgia, 'Nanum Myeongjo', serif;
    font-size: 16px; line-height: 1.65;
  }}
  .wrap {{ max-width: 46rem; margin: 0 auto; }}
  h1 {{ font-size: 1.75rem; line-height: 1.25; margin: 0 0 .75rem; letter-spacing: -.015em; }}
  h2 {{
    font-size: 1rem; margin: 2.5rem 0 .75rem; letter-spacing: .01em;
    padding-bottom: .35rem; border-bottom: 1px solid var(--rule);
  }}
  p {{ margin: 0 0 .9rem; }}
  .meta {{ color: var(--muted); font-size: .8125rem; margin: 0 0 .2rem; }}
  .lede {{ border-bottom: 2px solid var(--rule); padding-bottom: 1.25rem; margin-bottom: .5rem; }}
  ul, ol {{ margin: 0 0 .9rem; padding-left: 1.2rem; }}
  li {{ margin: 0 0 .3rem; }}
  dt {{ font-weight: 600; }}
  dd {{ margin: 0 0 .55rem; padding-left: 0; color: var(--muted); }}
  pre {{
    font-family: ui-monospace, SFMono-Regular, Menlo, 'Cascadia Mono', monospace;
    font-size: .8125rem; line-height: 1.5; background: transparent; color: var(--ink);
    border: 1px solid var(--hair); border-radius: 6px; padding: .85rem 1rem;
    overflow-x: auto; margin: 0 0 1.1rem;
  }}
  table {{ width: 100%; border-collapse: collapse; font-size: .875rem; margin: 0 0 1.1rem; }}
  th, td {{ text-align: left; padding: .4rem .5rem; border-bottom: 1px solid var(--hair); }}
  th {{ font-weight: 600; color: var(--muted); font-size: .75rem;
        text-transform: uppercase; letter-spacing: .07em; }}
  .muted {{ color: var(--muted); }}
  .boundary {{
    margin-top: 3rem; padding: .85rem 1rem; border-left: 3px solid var(--rule);
    color: var(--muted); font-size: .875rem;
  }}
  @page {{ size: A4; margin: 20mm 18mm; }}
  @media print {{
    :root {{ --page: #ffffff; --ink: #101010; --muted: #55554e; --hair: #d8d8d0; --rule: #b4b4a8; }}
    body {{ padding: 0; font-size: 10.5pt; }}
    .wrap {{ max-width: none; }}
    h2 {{ break-after: avoid; }}
    .sec, pre, table, li {{ break-inside: avoid; }}
  }}
</style>
</head>
<body>
<div class="wrap">
<header class="lede">
<h1>{escape(str(value['title']))}</h1>
<p class="meta">{escape(_caption(value, 'question'))}: {escape(str(value['question']))}</p>
<p class="meta">{escape(_caption(value, 'as_of'))} {escape(str(value['as_of']))}</p>
</header>
{_page_list(_caption(value, "learning_objectives"), _rows(value.get("learning_objectives")))}
{_page_list(_caption(value, "assumed_knowledge"), _rows(value.get("assumed_knowledge")))}
{_page_list(_caption(value, "out_of_scope"), _rows(value.get("out_of_scope")))}
{sections}
{figure_block}
{glossary_block}
{_page_list(_caption(value, "traps"), _rows(value.get("traps")))}
{source_block}
<p class="boundary">{escape(_caption(value, 'claim_boundary'))}</p>
</div>
</body>
</html>
"""
