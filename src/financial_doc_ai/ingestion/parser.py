import re

import markdownify
from bs4 import BeautifulSoup


class FilingParser:
    """Parses 10-K HTML filings to extract text and tables as clean Markdown."""

    def __init__(self):
        pass

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
        cleaned_md = re.sub(r'\n{3,}', '\n\n', cleaned_md).strip()

        return cleaned_md
