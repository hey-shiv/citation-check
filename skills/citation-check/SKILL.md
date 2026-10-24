---
name: citation-check
description: Check that every reference in a .bib file is a real paper with the right title, year and first author. Use when the user asks to check, verify or audit citations or references, or before submitting a paper.
---

# Citation check

1. Find the .bib file. If the user did not name one, look for `*.bib` in the project and ask if there are several.

2. Run the check:

   `python3 ~/.claude/research-kit/citation_check.py <file.bib>`

   It takes about a second per entry. Pass `--mailto <their email>` only if the user gives it.

3. Report in under 10 lines:
   - the counts line at the end
   - every NOT_FOUND and MISMATCH entry with its key and the problem
   - ERROR entries as "could not check", never as fake

4. For a MISMATCH, show what the index found next to what the entry claims, and offer to correct the entry to match the found record. Edit the .bib only after the user agrees.

5. For a NOT_FOUND, say the paper could not be found in Crossref, OpenAlex or arXiv. It may be made up, or it may be a thesis, a book chapter or a very new preprint. Ask the user where they got it.

6. Never invent a replacement reference. Only suggest a record the script actually returned.
