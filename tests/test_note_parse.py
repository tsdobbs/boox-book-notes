"""Tests for :mod:`boox_book_notes.note_parse`.

The mangled characters below are written as escapes so that this file stays
pure ASCII: the NeoReader export is UTF-8 that was decoded as Windows-1252, so
an em dash arrives as three characters (``â`` + euro sign + right double quote)
and the annotation marker arrives wrapped in mangled CJK brackets.
"""

import pathlib

import pytest

from boox_book_notes.note_parse import (
    assemble_output_note,
    fix_encoding,
    get_text_from_path,
    main,
    parse_annotations,
    parse_body,
    parse_meta,
    split_notes,
)

TEST_NOTES = pathlib.Path(__file__).parent / "test_data" / "test_notes.txt"

# What the export *should* have said.
EM_DASH = "\u2014"
LEFT_DOUBLE_QUOTE = "\u201c"
RIGHT_DOUBLE_QUOTE = "\u201d"
RIGHT_SINGLE_QUOTE = "\u2019"
MARKER = "\u3010Annotation\u3011"

# What the export actually says.
MANGLED_EM_DASH = "\u00e2\u20ac\u201d"
MANGLED_LEFT_DOUBLE_QUOTE = "\u00e2\u20ac\u0153"
MANGLED_RIGHT_DOUBLE_QUOTE = "\u00e2\u20ac\u009d"
MANGLED_RIGHT_SINGLE_QUOTE = "\u00e2\u20ac\u2122"
MANGLED_MARKER = "\u00e3\u20ac\u0090Annotation\u00e3\u20ac\u2018"
MANGLED_MARKER_WITHOUT_CONTROL_BYTE = "\u00e3\u20acAnnotation\u00e3\u20ac\u2018"
MANGLED_SPACE = "\u00c2 "

META_LINE = f"2026-11-03 19:43{MANGLED_SPACE}{MANGLED_SPACE}|{MANGLED_SPACE}{MANGLED_SPACE}Page No.: 8"

MANGLED_CHARACTERS = (
    "\u00c2",
    "\u00e2",
    "\u00e3",
    "\u20ac",
    "\u2122",
    "\u0090",
    "\u009d",
)


def test_split_notes_splits_on_the_delimiter():
    assert split_notes("first-------------------second") == ["first", "second"]


def test_split_notes_keeps_a_trailing_chunk_after_the_last_delimiter():
    assert split_notes("first-------------------") == ["first", ""]


def test_get_text_from_path_reads_the_whole_file():
    text = get_text_from_path(str(TEST_NOTES))

    assert text.startswith("Reading Notes")
    assert MANGLED_MARKER in text


def test_fix_encoding_repairs_mangled_punctuation():
    assert fix_encoding(f"wanted{MANGLED_EM_DASH}maximum") == f"wanted{EM_DASH}maximum"
    assert fix_encoding(f"{MANGLED_LEFT_DOUBLE_QUOTE}quoted") == f"{LEFT_DOUBLE_QUOTE}quoted"
    assert fix_encoding(f"today{MANGLED_RIGHT_SINGLE_QUOTE}s") == f"today{RIGHT_SINGLE_QUOTE}s"


def test_fix_encoding_repairs_the_mangled_annotation_marker():
    assert fix_encoding(f"A highlight\n{MANGLED_MARKER}my note") == f"A highlight\n{MARKER}my note"


def test_fix_encoding_drops_mangled_non_breaking_spaces():
    assert fix_encoding(f"19:43{MANGLED_SPACE}{MANGLED_SPACE}|{MANGLED_SPACE}Page No.: 8") == "19:43  | Page No.: 8"


def test_fix_encoding_leaves_clean_text_alone():
    clean = "Page 8 (Chapter 1. Loomings), Noted at 2026-11-03 19:43 - plain ASCII, and a real em dash \u2014"

    assert fix_encoding(clean) == clean


def test_parse_meta_reads_the_page_and_datetime():
    assert parse_meta(f"{META_LINE}\nA highlight") == "Page 8, Noted at 2026-11-03 19:43"


def test_parse_meta_reads_a_chapter_heading_above_the_datetime():
    note = f"Chapter 1. Loomings\n{META_LINE}\nA highlight"

    assert parse_meta(note) == "Page 8 (Chapter 1. Loomings), Noted at 2026-11-03 19:43"


def test_parse_meta_throws_away_everything_above_the_heading():
    note = f"Reading Notes | <<Some Book>>\nSome other junk\nChapter 1. Loomings\n{META_LINE}\nA highlight"

    assert parse_meta(note) == "Page 8 (Chapter 1. Loomings), Noted at 2026-11-03 19:43"


def test_parse_meta_ignores_the_book_header():
    note = f"Reading Notes | <<Some Book>>\n{META_LINE}\nA highlight"

    assert parse_meta(note) == "Page 8, Noted at 2026-11-03 19:43"


def test_parse_meta_repairs_a_mangled_heading():
    note = f"Chapter 71. The Jeroboam{MANGLED_RIGHT_SINGLE_QUOTE}s Story\n{META_LINE}\nA highlight"

    assert (
        parse_meta(note) == f"Page 8 (Chapter 71. The Jeroboam{RIGHT_SINGLE_QUOTE}s Story), Noted at 2026-11-03 19:43"
    )


def test_parse_meta_without_a_page_number():
    assert parse_meta("2026-11-03 19:43\nA highlight") == "Noted at 2026-11-03 19:43"


def test_parse_meta_without_a_datetime_is_empty():
    assert parse_meta("Just some text with no meta line") == ""


def test_parse_body_returns_the_highlight_after_the_datetime_line():
    assert parse_body(f"{META_LINE}\nA highlight") == "A highlight"


def test_parse_body_stops_at_the_annotation_marker():
    note = f"{META_LINE}\nA highlight\n{MANGLED_MARKER}my note"

    assert parse_body(note) == "A highlight"


def test_parse_body_runs_to_the_end_without_a_marker():
    note = f"Chapter 1. Loomings\n{META_LINE}\nFirst line\nSecond line"

    assert parse_body(note) == "First line\nSecond line"


def test_parse_body_repairs_mangled_punctuation():
    note = f"{META_LINE}\nwanted{MANGLED_EM_DASH}the open sea"

    assert parse_body(note) == f"wanted{EM_DASH}the open sea"


def test_parse_annotations_returns_none_without_a_marker():
    assert parse_annotations(f"{META_LINE}\nA highlight") is None


def test_parse_annotations_returns_a_single_annotation_as_a_list():
    assert parse_annotations(f"A highlight\n{MANGLED_MARKER}my note") == ["my note"]


def test_parse_annotations_splits_on_blank_lines():
    note = f"A highlight\n{MARKER}first\n\nsecond\n\nthird"

    assert parse_annotations(note) == ["first", "second", "third"]


def test_parse_annotations_keeps_lines_that_are_not_blank_line_separated_together():
    note = f"A highlight\n{MARKER}first line\nstill the first annotation"

    assert parse_annotations(note) == ["first line\nstill the first annotation"]


@pytest.mark.parametrize(
    "marker",
    [
        MARKER,
        MANGLED_MARKER,
        MANGLED_MARKER_WITHOUT_CONTROL_BYTE,
        "\u00e3\u20acAnnotation\u3011",
        "[Annotation]",
        "[annotation]",
    ],
)
def test_parse_annotations_understands_alternative_marker_encodings(marker):
    assert parse_annotations(f"A highlight\n{marker}my note") == ["my note"]


def test_assemble_output_note_nests_annotations_and_meta_under_the_highlight():
    assert assemble_output_note("Page 8, Noted at 2026-11-03 19:43", "A highlight", ["first", "second"]) == (
        "> A highlight\n    first\n    second\n    Page 8, Noted at 2026-11-03 19:43"
    )


def test_assemble_output_note_without_annotations():
    assert assemble_output_note("Page 8, Noted at 2026-11-03 19:43", "A highlight", None) == (
        "> A highlight\n    Page 8, Noted at 2026-11-03 19:43"
    )


def test_assemble_output_note_keeps_a_multi_paragraph_highlight_in_one_block():
    assert assemble_output_note("Page 8", "First paragraph.\nSecond paragraph.", None) == (
        "> First paragraph. // Second paragraph.\n    Page 8"
    )


def test_assemble_output_note_closes_up_a_line_that_was_only_wrapped():
    assert assemble_output_note("Page 8", "a sentence that was\nwrapped mid-way", None) == (
        "> a sentence that was wrapped mid-way\n    Page 8"
    )


def test_assemble_output_note_without_a_highlight_leaves_nothing_indented():
    assert assemble_output_note("Page 8", "", ["my note"]) == "my note\nPage 8"


def test_assemble_output_note_without_anything_to_say_is_empty():
    assert assemble_output_note("", "", None) == ""


def _parse(full_text: str) -> list[str]:
    """Parse raw export text into one output note per highlight."""
    output_notes = []
    for note in split_notes(full_text):
        if not note.strip():
            continue
        output_note = assemble_output_note(parse_meta(note), parse_body(note), parse_annotations(note))
        if output_note:
            output_notes.append(output_note)
    return output_notes


@pytest.fixture(scope="module")
def example_output() -> list[str]:
    """The example export in ``tests/test_data``, parsed into Roam blocks."""
    return _parse(get_text_from_path(str(TEST_NOTES)))


def test_every_highlight_in_the_example_export_becomes_a_note(example_output):
    assert len(example_output) == 12


def test_no_mangled_characters_survive_the_example_export(example_output):
    everything = "\n".join(example_output)

    assert not [character for character in MANGLED_CHARACTERS if character in everything]


def test_every_note_ends_with_its_meta_line_indented_under_the_highlight(example_output):
    meta_lines = [note.splitlines()[-1] for note in example_output]

    assert len(meta_lines) == 12
    assert all(line.startswith("    Page") and ", Noted at " in line for line in meta_lines)


def test_every_highlight_is_a_single_unindented_block(example_output):
    highlight_lines = [note.splitlines()[0] for note in example_output]

    assert len(highlight_lines) == 12
    assert all(line.startswith("> ") for line in highlight_lines)


def test_only_the_highlight_is_marked_as_a_quote(example_output):
    child_lines = [line for note in example_output for line in note.splitlines()[1:]]

    assert len(child_lines) == 21
    assert not [line for line in child_lines if line.lstrip().startswith(">")]


def test_the_first_note_of_the_example_export(example_output):
    assert example_output[0] == (
        f"> Call me Ishmael. Some years ago{EM_DASH}never mind how long precisely{EM_DASH}having little or no "
        "money in my purse, and nothing particular to interest me on shore, I thought I would sail about a "
        "little and see the watery part of the world. // It is a way I have of driving off the spleen and "
        "regulating the circulation.\n"
        "    The most famous opening in American literature, and it arrives as a confession rather than an "
        f"introduction. // Note how Melville refuses to date his own story{EM_DASH}{LEFT_DOUBLE_QUOTE}never "
        f"mind how long precisely.{RIGHT_DOUBLE_QUOTE}\n"
        "    Page 3 (Chapter 1. Loomings), Noted at 2026-11-03 19:43"
    )


def test_a_multi_paragraph_highlight_folds_into_one_line(example_output):
    highlight = example_output[1].splitlines()[0]

    assert highlight.count(" // ") == 2
    assert highlight.startswith("> Whenever I find myself growing grim about the mouth;")
    assert highlight.endswith("I quietly take to the ship.")


def test_a_note_with_a_heading_and_several_annotations(example_output):
    note = example_output[7].splitlines()

    assert len(note) == 4
    assert note[0] == "> It is the whiteness of the whale that above all things appals me."
    assert note[-3:] == [
        f"    He keeps circling {LEFT_DOUBLE_QUOTE}the whiteness of the whale{RIGHT_DOUBLE_QUOTE} as though "
        "the colour itself were the antagonist.",
        "    The symbol is never resolved, which is precisely why it survives the book.",
        "    Page 112 (Chapter 42. The Whiteness of the Whale), Noted at 2026-11-03 20:58",
    ]


def test_a_note_without_an_annotation(example_output):
    assert example_output[2] == (
        "> There now is your insular city of the Manhattoes, belted round by wharves as Indian isles by "
        f"coral reefs{EM_DASH}commerce surrounds it with her surf.\n    Page 5, Noted at 2026-11-03 19:54"
    )


def test_main_writes_the_parsed_notes_next_to_the_input(tmp_path, capsys):
    input_path = tmp_path / "notes.txt"
    input_path.write_text(f"{META_LINE}\nA highlight\n{MANGLED_MARKER}my note\n", encoding="utf-8")

    main(str(input_path))

    output_path = tmp_path / "notes_OUTPUT.txt"
    assert output_path.is_file()
    assert (
        output_path.read_text(encoding="utf-8") == "> A highlight\n    my note\n    Page 8, Noted at 2026-11-03 19:43\n"
    )
    assert capsys.readouterr().out.startswith("> A highlight")


def test_main_accepts_raw_text_and_writes_a_timestamped_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    main(f"{META_LINE}\nA highlight")

    written = list(tmp_path.glob("NOTES_OUTPUT_*.txt"))
    assert len(written) == 1
    assert written[0].read_text(encoding="utf-8") == "> A highlight\n    Page 8, Noted at 2026-11-03 19:43\n"


def test_main_skips_the_empty_chunk_after_the_last_delimiter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    main(f"{META_LINE}\nA highlight\n-------------------")

    written = list(tmp_path.glob("NOTES_OUTPUT_*.txt"))
    assert written[0].read_text(encoding="utf-8") == "> A highlight\n    Page 8, Noted at 2026-11-03 19:43\n"
