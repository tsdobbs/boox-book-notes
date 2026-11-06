# boox-book-notes

[![Commit activity](https://img.shields.io/github/commit-activity/m/tsdobbs/boox-book-notes)](https://github.com/tsdobbs/boox-book-notes)
[![License](https://img.shields.io/github/license/tsdobbs/boox-book-notes)](https://github.com/tsdobbs/boox-book-notes/blob/main/LICENSE)

Parse the notes exported from Boox's NeoReader into blocks for Roam Research.

- **Github repository**: <https://github.com/tsdobbs/boox-book-notes/>

## Usage

Parse an exported notes file into Roam blocks:

```bash
uv run python -m boox_book_notes.note_parse path/to/my_notes.txt
```

Installing the package puts the same command on your path as `boox-book-notes`:

```bash
uv tool install boox-book-notes
boox-book-notes path/to/my_notes.txt
```

This writes `path/to/my_notes_OUTPUT.txt` next to the input and prints the same
blocks to stdout, ready to paste straight into Roam Research:

```markdown
> The highlight, exactly as it appears in the book
    Your annotation about that highlight
    Page 8 (Chapter 1. Loomings), Noted at 2026-11-03 19:43
```

Only the highlight carries the `>`, because only it is a quotation from the book.
Roam makes one block out of every pasted line and renders `*` as a literal
character, so there are no bullet markers: each block is one line, and nesting is
carried by indentation alone.  The highlight is the parent block, with your
annotations, page, chapter heading and timestamp indented underneath it.

A highlight that runs over several paragraphs still lands in a single block, with
` // ` marking where each paragraph began.  Roam's soft line break is Shift+Enter
in the UI and has no paste-time syntax, so a real line break would split the
highlight across several blocks instead.

You can also pass the note text itself instead of a path; the result is then
written to `NOTES_OUTPUT_<timestamp>.txt` in the current directory:

```bash
uv run python -m boox_book_notes.note_parse "$(cat path/to/my_notes.txt)"
```

The export off the device is UTF-8 that was decoded as Windows-1252, so the
parser repairs the resulting mojibake as it goes: em dashes and curly quotes, the
`【Annotation】` marker, and the stray `Â` characters left behind by
non-breaking spaces.

---

Repository initiated with [osprey-oss/cookiecutter-uv](https://github.com/osprey-oss/cookiecutter-uv).
