"""Voice-profile parsing: markdown text → VoiceProfile.

Pure (string in, model out) — file reading happens once in the composition
root. Stdlib-only, per the core boundary rule.

The format is forgiving:

    ## Style notes
    - mostly lowercase, minimal punctuation

    ## Samples
    - nah that's not how any of this works
    - source: you made it up

Sections whose heading contains "sample" contribute their `- `/`* ` bullets as
samples; everything else (including preamble before any heading) becomes the
style notes. A file with no headings at all is treated entirely as notes.
"""

from __future__ import annotations

import re

from .models import VoiceProfile

_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")


def parse_voice_profile(text: str) -> VoiceProfile:
    notes_lines: list[str] = []
    samples: list[str] = []
    in_samples = False

    for line in text.splitlines():
        heading = _HEADING_RE.match(line.strip())
        if heading:
            in_samples = "sample" in heading.group(1).lower()
            continue  # heading lines themselves never enter notes or samples
        if in_samples:
            bullet = _BULLET_RE.match(line.strip())
            if bullet and bullet.group(1).strip():
                samples.append(bullet.group(1).strip())
            # non-bullet lines in a samples section are ignored
        else:
            notes_lines.append(line)

    notes = "\n".join(notes_lines).strip()
    return VoiceProfile(notes=notes, samples=tuple(samples))
