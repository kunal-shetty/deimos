# DOCX Skill

Use this skill whenever the user asks for a Word document, `.docx` file, report, letter, memo, resume, or any other formal document deliverable.

## How document creation works in Deimos

You don't write raw `.docx` XML. Instead, you call the `create_docx` tool with a structured `content` array describing the document, and Deimos builds the file with `python-docx`.

## Workflow

1. Plan the document structure first (headings, sections, what goes where).
2. Call `create_docx` with the full `content` array and a `output_path` ending in `.docx`.
3. After creation, tell the user where the file was saved. Do not try to read the binary `.docx` back with `read_file` — it won't be readable as text.

## Content block types

The `content` parameter is a JSON array of blocks, each with a `type` field:

### heading
```json
{"type": "heading", "text": "Quarterly Report", "level": 1}
```
`level` is 1-4 (1 = title-sized, 4 = smallest heading). Use level 1 once per document for the main title; level 2 for major sections; level 3 for subsections.

### paragraph
```json
{"type": "paragraph", "text": "This report summarizes Q3 performance across all regions."}
```
For inline emphasis, wrap text in `**bold**` or `*italic*` markers — Deimos parses simple markdown-style emphasis within paragraph text.

### bullet_list
```json
{"type": "bullet_list", "items": ["First point", "Second point", "Third point"]}
```

### numbered_list
```json
{"type": "numbered_list", "items": ["Step one", "Step two", "Step three"]}
```

### table
```json
{
  "type": "table",
  "headers": ["Name", "Role", "Department"],
  "rows": [
    ["Kunal", "Developer", "Engineering"],
    ["Sakshi", "Designer", "Product"]
  ]
}
```
First row is always treated as a styled header row.

### page_break
```json
{"type": "page_break"}
```

### spacer
```json
{"type": "spacer"}
```
Adds a blank line — use sparingly, paragraphs already have spacing.

## Best practices

- **Always start with a level-1 heading** as the document title, unless the user explicitly wants a title-less document (e.g. a letter).
- **Use level-2 headings for sections** (e.g. "Introduction", "Findings", "Recommendations") — don't bold a paragraph to fake a heading.
- **Prefer tables over bullet lists for structured/comparable data** (e.g. names + roles + dates). Use bullet lists for unordered points, numbered lists for sequential steps.
- **Keep paragraphs focused** — one idea per paragraph, not giant walls of text.
- **For letters/memos**, skip the level-1 title and start directly with the date/recipient block as plain paragraphs, then the body.
- **For reports**, structure is: Title → optional intro paragraph → sections with level-2 headings → conclusion/recommendations.
- **Don't over-format.** Bold and italics should highlight genuinely important terms, not be sprinkled everywhere.
- Save output files with descriptive names: `quarterly_report.docx`, not `output.docx` or `document.docx`.

## Example: building a short report

```json
{
  "output_path": "hrbot_module_summary.docx",
  "content": [
    {"type": "heading", "text": "HRBot Module Summary", "level": 1},
    {"type": "paragraph", "text": "This document summarizes the current state of the HRBot employee management modules as of June 2026."},
    {"type": "heading", "text": "Completed Modules", "level": 2},
    {"type": "bullet_list", "items": ["Payroll", "Leave Management", "Attendance", "Branches", "Users"]},
    {"type": "heading", "text": "Module Status", "level": 2},
    {
      "type": "table",
      "headers": ["Module", "Status", "Notes"],
      "rows": [
        ["Payroll", "Complete", "PDF export via html2canvas + jsPDF"],
        ["Attendance", "Complete", "Calendar with clickable day editing"],
        ["Announcements", "In progress", "Backend models being generated"]
      ]
    },
    {"type": "heading", "text": "Next Steps", "level": 2},
    {"type": "numbered_list", "items": ["Finish announcements backend", "Build reimbursements module", "Polish notification system"]}
  ]
}
```