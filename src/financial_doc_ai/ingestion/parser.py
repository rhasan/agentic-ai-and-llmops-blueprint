import re

import markdownify
from bs4 import BeautifulSoup


class FilingParser:
    """Parses 10-K HTML filings to extract text and tables as clean Markdown."""

    def __init__(self, footer_repeat_threshold: int = 5):
        # A line whose normalized form recurs at least this many times is treated
        # as running page furniture (header/footer) and stripped. See
        # _strip_repeated_lines.
        self._footer_repeat_threshold = footer_repeat_threshold

    def parse_html(self, html_bytes: bytes) -> str:
        """Parses the raw HTML bytes, removing styles/scripts and returning Markdown."""
        # 1. Parse the raw HTML
        soup = BeautifulSoup(html_bytes, "html.parser")

        # 2. Remove tags that contain no useful text for the LLM
        for element in soup(["script", "style", "meta", "title", "noscript"]):
            element.decompose()
        
        # 3. Remove hidden elements (a basic check for 'display: none')
        for element in soup.find_all(style=lambda value: value and "display:none" in value.replace(" ", "").lower()):
            element.decompose()

        # 4. Convert the cleaned HTML into Markdown
        html_content = str(soup)
        md_content = markdownify.markdownify(
            html_content,
            heading_style="ATX",
            escape_asterisks=False,
            escape_underscores=False
        )

        # 5. Clean up excessive blank lines
        cleaned_md = "\n".join(
            line for line in md_content.splitlines() if line.strip() or line == ""
        )

        # 6. Strip running headers/footers (page furniture repeated on every page)
        cleaned_md = self._strip_repeated_lines(cleaned_md)

        # 7. Collapse the blank runs the strip may have opened up
        cleaned_md = re.sub(r'\n{3,}', '\n\n', cleaned_md).strip()

        return cleaned_md

    def _strip_repeated_lines(self, md: str) -> str:
        """Remove running headers/footers — lines that repeat across the document.

        Page furniture like "Apple Inc. | 2024 Form 10-K | 57" is printed on every
        page and survives extraction as noise (it ends up as its own tiny chunk,
        polluting retrieval). Such lines recur many times differing only by the
        page number, whereas a real footnote appears once. So we count each line's
        *normalized* form (digits collapsed, whitespace squeezed) and drop the
        originals whose form recurs at least the threshold number of times.

        Blank lines and table lines (starting with `|`) are never counted or
        dropped: table content is off-limits, and the threshold is what keeps
        footnotes safe (they don't repeat).
        """
        def normalize(line: str) -> str:
            return re.sub(r"\s+", " ", re.sub(r"\d+", "#", line)).strip().lower()

        def is_furniture_candidate(line: str) -> bool:
            return bool(line.strip()) and not line.lstrip().startswith("|")

        lines = md.splitlines()
        counts: dict[str, int] = {}
        for line in lines:
            if is_furniture_candidate(line):
                key = normalize(line)
                counts[key] = counts.get(key, 0) + 1

        return "\n".join(
            line
            for line in lines
            if not (
                is_furniture_candidate(line)
                and counts.get(normalize(line), 0) >= self._footer_repeat_threshold
            )
        )
