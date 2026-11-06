"""Parse Boox NeoReader reading-note exports into blocks for Roam Research.

The CLI accepts either the path of an exported notes file or the raw note text
itself, and turns every highlight into blocks that can be pasted straight into
a Roam Research page::

    > The highlight, exactly as it appears in the book
        Your annotation about that highlight
        Page 8 (Chapter 1. Loomings), Noted at 2026-11-03 19:43

Only the highlight is a quotation from the book, so only it carries the ``>``.
Roam makes one block out of every pasted line and renders ``*`` as a literal
character, so blocks are separated by line breaks alone, each one is written as a
single line, and nesting is carried by indentation rather than by a bullet
marker.

The export is UTF-8 text that was decoded as Windows-1252 on its way off the
device, so it arrives full of mojibake: em dashes and curly quotes come back as
three-character sequences, the annotation marker comes back wrapped in
mis-decoded CJK brackets, and non-breaking spaces come back as a stray capital
A-circumflex.  :func:`fix_encoding` undoes all of that before anything else
looks at the text.
"""

import datetime
import pathlib
import re

import typer

# --------------------------------------------------------------------------- #
# What the NeoReader export looks like
# --------------------------------------------------------------------------- #

NOTE_DELIMITER = "-------------------"

#: ``2026-11-03 19:43``, tolerating a ``T`` separator and optional seconds.
TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?")

#: ``Page No.: 8`` / ``Page: 8`` / ``Page 8``.
PAGE_PATTERN = re.compile(r"Page\s*(?:No\.?)?\s*:?\s*(?P<page>\d+)", re.IGNORECASE)

#: One or more blank lines, which is what separates two annotations.
BLANK_LINE_PATTERN = re.compile(r"\n\s*\n")

#: The annotation marker as it reads once the encoding has been repaired.
ANNOTATION_MARKER = "\u3010Annotation\u3011"

#: The brackets the marker can arrive in: as it should be, mangled, mangled with
#: its stray control byte dropped, and plain ASCII.  Any opening is matched with
#: any closing, because :func:`fix_encoding` can repair one half of the marker
#: and not the other (the opening is an incomplete UTF-8 sequence on its own).
ANNOTATION_MARKER_OPENINGS: tuple[str, ...] = ("\u3010", "\u00e3\u20ac\u0090", "\u00e3\u20ac", "[")
ANNOTATION_MARKER_CLOSINGS: tuple[str, ...] = (
    "\u3011",
    "\u00e3\u20ac\u0091",
    "\u00e3\u20ac\u2018",
    "\u00e3\u20ac",
    "]",
)

ANNOTATION_MARKER_PATTERN = re.compile(
    r"(?:{})\s*Annotation\s*(?:{})".format(
        "|".join(re.escape(opening) for opening in ANNOTATION_MARKER_OPENINGS),
        "|".join(re.escape(closing) for closing in ANNOTATION_MARKER_CLOSINGS),
    ),
    re.IGNORECASE,
)

# --------------------------------------------------------------------------- #
# What the Roam output looks like
# --------------------------------------------------------------------------- #

#: Only the highlight is a quotation from the book, so only it is marked as one.
QUOTE_PREFIX = "> "

#: Roam renders ``*`` literally but does honour indentation, so nesting is carried
#: by the indent alone: one line is one block, and an indented line nests under the
#: block above it.
CHILD_INDENT = "    "

#: Stands in for a paragraph break inside a highlight.  Roam's soft line break is
#: Shift+Enter in the UI and has no paste-time syntax, so a real newline would
#: split the highlight across several blocks; a visible separator keeps the whole
#: highlight in one block while still showing where its paragraphs fell.
PARAGRAPH_SEPARATOR = " // "

#: What ends a sentence, allowing for a closing quote or bracket after it.
SENTENCE_END_PATTERN = re.compile(r"""[.!?]["')\u201d\u2019]*$""")

#: What starts a sentence, so a break between two of them reads as a paragraph.
OPENING_QUOTES = "\"'(\u201c\u2018"

#: Appended to the input file name to build the output file name.
OUTPUT_SUFFIX = "_OUTPUT"

# --------------------------------------------------------------------------- #
# Encoding repair
# --------------------------------------------------------------------------- #

# Windows-1252 puts printable characters in the 0x80-0x9F range that latin-1
# leaves as C1 control codes.  Those are the characters that give the mangled
# text away (a euro sign, a trade mark sign, ...), so this maps each of them
# back to the single byte it came from.
_WINDOWS_1252_HIGH_BYTES: dict[int, int] = {
    0x80: 0x20AC,
    0x82: 0x201A,
    0x83: 0x0192,
    0x84: 0x201E,
    0x85: 0x2026,
    0x86: 0x2020,
    0x87: 0x2021,
    0x88: 0x02C6,
    0x89: 0x2030,
    0x8A: 0x0160,
    0x8B: 0x2039,
    0x8C: 0x0152,
    0x8E: 0x017D,
    0x91: 0x2018,
    0x92: 0x2019,
    0x93: 0x201C,
    0x94: 0x201D,
    0x95: 0x2022,
    0x96: 0x2013,
    0x97: 0x2014,
    0x98: 0x02DC,
    0x99: 0x2122,
    0x9A: 0x0161,
    0x9B: 0x203A,
    0x9C: 0x0153,
    0x9E: 0x017E,
    0x9F: 0x0178,
}

_CHAR_TO_BYTE: dict[str, bytes] = {
    chr(code_point): bytes([byte]) for byte, code_point in _WINDOWS_1252_HIGH_BYTES.items()
}

#: Characters that can stand in for a single byte in the 0x80-0xBF range, i.e.
#: the UTF-8 continuation bytes plus their Windows-1252 look-alikes.
_CONTINUATIONS = r"\x80-\xbf" + re.escape("".join(_CHAR_TO_BYTE))

#: A UTF-8 lead character followed by one to three continuation characters - the
#: shape every mangled character has.
_MANGLED_SEQUENCE_PATTERN = re.compile(rf"[\xc2-\xf4][{_CONTINUATIONS}]{{1,3}}")

#: A leftover A-circumflex that is *not* followed by a continuation character
#: cannot be part of a real character: it is a mangled non-breaking space.
_NBSP_ARTIFACT_PATTERN = re.compile(rf"\xc2(?![{_CONTINUATIONS}])")


def _as_single_bytes(run: str) -> bytes:
    """Return the bytes ``run`` was made of before it was decoded as Windows-1252."""
    return b"".join(
        _CHAR_TO_BYTE[character] if character in _CHAR_TO_BYTE else character.encode("latin-1") for character in run
    )


def _repair_sequence(match: re.Match[str]) -> str:
    """Re-decode one mangled sequence, longest first, leaving it alone if that fails."""
    mangled = match.group()
    for length in range(len(mangled), 1, -1):
        try:
            repaired = _as_single_bytes(mangled[:length]).decode("utf-8")
        except UnicodeDecodeError:
            continue
        return repaired + mangled[length:]
    return mangled


def fix_encoding(text: str) -> str:
    """Undo the Windows-1252 mangling that the NeoReader export introduces.

    Mangled sequences are repaired first, then the A-circumflex characters left
    behind by non-breaking spaces are dropped.  Anything that does not decode as
    UTF-8 is left exactly as it was, so text that was never mangled is safe.

    Args:
        text: Text from a NeoReader export.

    Returns:
        The same text with its encoding artifacts repaired.

    Examples:
        >>> fix_encoding("they wanted\\u00e2\\u20ac\\u201dthe open sea")
        'they wanted\\u2014the open sea'
        >>> fix_encoding("19:43\\u00c2 \\u00c2 |\\u00c2 \\u00c2 Page No.: 8")
        '19:43  |  Page No.: 8'
        >>> fix_encoding("plain text is left alone")
        'plain text is left alone'
    """
    repaired = _MANGLED_SEQUENCE_PATTERN.sub(_repair_sequence, text.replace("\u00a0", " "))
    return _NBSP_ARTIFACT_PATTERN.sub("", repaired)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

#: The export opens with a book header line ("Reading Notes | <<title>>").  It
#: sits above the first highlight but is not a chapter heading.
BOOK_HEADER_PATTERN = re.compile(r"^\s*Reading Notes\b|<<.+>>", re.IGNORECASE)


def _collapse_whitespace(text: str) -> str:
    """Squeeze runs of whitespace, left behind by mangled spaces, into single spaces."""
    return re.sub(r"\s+", " ", text).strip()


def _find_timestamp(lines: list[str]) -> tuple[int, str] | None:
    """Return the index of the first line carrying a datetime, and that datetime."""
    for index, line in enumerate(lines):
        match = TIMESTAMP_PATTERN.search(line)
        if match is not None:
            return index, match.group()
    return None


def get_text_from_path(input_path: str) -> str:
    """Read an exported notes file.

    Args:
        input_path: Path to the exported notes file.

    Returns:
        The whole file as one string.
    """
    with open(input_path, encoding="utf-8") as file:
        return file.read()


def split_notes(full_text: str) -> list[str]:
    """Splits a big set of text on a specific delimiter

    Args:
        full_text: Multiple notes in a big string

    Returns:
        List of strings, each representing a single note
    """

    return full_text.split(NOTE_DELIMITER)


def parse_meta(note: str) -> str:
    """Summarise where a note came from as a single line of text.

    The first line of a note is either its ``<datetime> | Page No.: <page>`` line
    or, when the highlight opens a chapter, the chapter heading with that line
    underneath it.  Only the line directly above the datetime line can be a
    heading; anything higher up (the book header, for instance) is thrown away.

    Args:
        note: A single note, as produced by :func:`split_notes`.

    Returns:
        ``Page 8 (Chapter 1. Loomings), Noted at 2026-11-03 19:43``, or an
        empty string when the note carries no datetime at all.

    Examples:
        >>> parse_meta("2026-11-03 19:53\\u00c2 \\u00c2 |\\u00c2 \\u00c2 Page No.: 9\\nA highlight")
        'Page 9, Noted at 2026-11-03 19:53'
        >>> parse_meta("Chapter 1. Loomings\\n2026-11-03 19:43  |  Page No.: 8\\nA highlight")
        'Page 8 (Chapter 1. Loomings), Noted at 2026-11-03 19:43'
    """
    lines = [line.strip() for line in fix_encoding(note).splitlines()]

    found = _find_timestamp(lines)
    if found is None:
        return ""
    index, timestamp = found

    heading = _collapse_whitespace(lines[index - 1]) if index > 0 else ""
    if BOOK_HEADER_PATTERN.search(heading):
        heading = ""

    page_match = PAGE_PATTERN.search(lines[index])
    page = page_match.group("page") if page_match else None

    location = f"Page {page}" if page is not None else ""
    if heading:
        location = f"{location} ({heading})" if location else f"({heading})"

    return f"{location}, Noted at {timestamp}" if location else f"Noted at {timestamp}"


def parse_body(note: str) -> str:
    """Return the highlighted text itself, without the meta line or the annotations.

    The highlight is everything between the datetime line and the annotation
    marker; when a note has no marker, the highlight runs to the end of the note.

    Args:
        note: A single note, as produced by :func:`split_notes`.

    Returns:
        The highlighted text, which may span several lines.

    Examples:
        >>> parse_body("2026-11-03 19:53  |  Page No.: 9\\nIgnorance is the parent of fear")
        'Ignorance is the parent of fear'
        >>> parse_body("2026-11-03 19:54  |  Page No.: 10\\nA highlight\\n\\u3010Annotation\\u3011my note")
        'A highlight'
    """
    lines = fix_encoding(note).splitlines()

    found = _find_timestamp(lines)
    highlight_lines = lines[found[0] + 1 :] if found is not None else lines
    body = "\n".join(highlight_lines)

    marker = ANNOTATION_MARKER_PATTERN.search(body)
    if marker is not None:
        body = body[: marker.start()]

    return body.strip()


def parse_annotations(note: str) -> list[str] | None:
    """Return the annotations you attached to a note.

    Everything after the annotation marker is yours rather than the book's.  A
    blank line separates one annotation from the next, and a note with a single
    annotation still comes back as a list of one.

    Args:
        note: A single note, as produced by :func:`split_notes`.

    Returns:
        The annotations in the order they were written, or ``None`` when the note
        carries no annotation marker at all.

    Examples:
        >>> parse_annotations("2026-11-03 20:43  |  Page No.: 16\\nA highlight") is None
        True
        >>> parse_annotations("A highlight\\n\\u3010Annotation\\u3011first\\n\\nsecond")
        ['first', 'second']
    """
    text = fix_encoding(note)

    marker = ANNOTATION_MARKER_PATTERN.search(text)
    if marker is None:
        return None

    everything_after = text[marker.end() :]
    return [annotation.strip() for annotation in BLANK_LINE_PATTERN.split(everything_after) if annotation.strip()]


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


def _render_block(text: str, prefix: str = "") -> str:
    """Render ``text`` as one Roam block, which means as one line.

    Roam starts a new block for every pasted line, so the block's lines are folded
    onto a single one: a break that only wrapped the text is closed up with a
    space, while a break between two paragraphs stays visible as
    :data:`PARAGRAPH_SEPARATOR`.

    Args:
        text: The text of the block; blank lines in it are dropped.
        prefix: What opens the line, e.g. ``"> "`` to quote it or
            :data:`CHILD_INDENT` to nest it under the block above it.

    Returns:
        The rendered block, or an empty string when ``text`` is blank.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""

    folded = ""
    for line in lines:
        if not folded:
            folded = line
        else:
            separator = PARAGRAPH_SEPARATOR if _is_paragraph_break(folded, line) else " "
            folded = f"{folded}{separator}{line}"

    return f"{prefix}{folded}"


def _is_paragraph_break(previous: str, following: str) -> bool:
    """Whether the break between two lines separates paragraphs, not wrapped text.

    The export does not wrap its lines, so a break normally falls between two
    paragraphs.  It reads as a wrap only when the text before it does not end a
    sentence *and* the text after it does not start one, which is how a line that
    was merely broken in the middle of a sentence looks.

    Args:
        previous: The text already folded onto the line.
        following: The line about to be folded onto it.

    Returns:
        Whether the break between them should stay visible.
    """
    ends_sentence = bool(SENTENCE_END_PATTERN.search(previous.rstrip()))
    starts_sentence = following[:1].isupper() or following[:1] in OPENING_QUOTES
    return ends_sentence or starts_sentence


def assemble_output_note(meta: str, body: str, annotations: list[str] | None) -> str:
    """Assemble one parsed note into blocks that Roam Research can paste.

    The highlight is the parent block, quoted because it comes from the book, and
    each annotation and the meta line are indented underneath it, so a highlight
    and everything said about it nest together::

        > The highlight, exactly as it appears in the book
            Your annotation about that highlight
            Page 8 (Chapter 1. Loomings), Noted at 2026-11-03 19:43

    Args:
        meta: The source line, from :func:`parse_meta`.
        body: The highlight, from :func:`parse_body`.
        annotations: Your annotations, from :func:`parse_annotations`.

    Returns:
        The note as Roam blocks, or an empty string when there is nothing to say.

    Examples:
        >>> print(assemble_output_note("Page 8, Noted at 2026-11-03 19:43", "A highlight", ["my note"]))
        > A highlight
            my note
            Page 8, Noted at 2026-11-03 19:43
        >>> print(assemble_output_note("Page 9, Noted at 2026-11-03 19:53", "One paragraph.\\nTwo.", None))
        > One paragraph. // Two.
            Page 9, Noted at 2026-11-03 19:53
    """
    # Without a highlight there is no parent to nest under, and an indented block
    # would attach itself to the last block of the note before it.
    indent = CHILD_INDENT if body.strip() else ""

    blocks = [_render_block(body, QUOTE_PREFIX)]
    blocks.extend(_render_block(annotation, indent) for annotation in annotations or [])
    blocks.append(_render_block(meta, indent))

    return "\n".join(block for block in blocks if block)


def _get_output_path(input_path: pathlib.Path) -> pathlib.Path:
    """Return the path the parsed notes are written to, e.g. ``notes_OUTPUT.txt``."""
    return input_path.with_name(f"{input_path.stem}{OUTPUT_SUFFIX}{input_path.suffix}")


def main(input_path_or_text: str) -> None:
    """Parse a NeoReader export into Roam blocks, write them out and print them.

    Args:
        input_path_or_text: Path to an exported notes file, or the raw note text
            itself.  A file is parsed into ``<name>_OUTPUT<extension>`` next to it;
            raw text is written to ``NOTES_OUTPUT_<timestamp>.txt`` in the current
            directory.
    """
    try:
        path = pathlib.Path(input_path_or_text)
        is_file = path.is_file()
        input_text = get_text_from_path(input_path_or_text) if is_file else input_path_or_text
    except OSError:
        is_file = False
        input_text = input_path_or_text  # assume it's text

    notes = split_notes(input_text)

    output_notes: list[str] = []

    for note in notes:
        if not note.strip():
            continue

        meta = parse_meta(note)
        body = parse_body(note)
        annotations = parse_annotations(note)

        output_note = assemble_output_note(meta, body, annotations)
        if output_note:
            output_notes.append(output_note)

    output_text = "\n".join(output_notes)

    if is_file:
        output_path: str | pathlib.Path = _get_output_path(path)
    else:
        output_path = f"NOTES_OUTPUT_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output_text + "\n")

    print(output_text)


def cli() -> None:
    """Run the parser from the command line.

    This is the ``boox-book-notes`` console script; it takes one argument, a path
    to an exported notes file or the raw note text itself, exactly as
    :func:`main` does.
    """
    typer.run(main)


if __name__ == "__main__":  # pragma: no cover
    cli()
