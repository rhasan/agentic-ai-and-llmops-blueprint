from financial_doc_ai.ingestion.parser import FilingParser


def test_filing_parser_removes_styles_and_scripts():
    html = b"""
    <html>
    <head>
        <style>.hidden { display: none; }</style>
        <script>console.log('test');</script>
    </head>
    <body>
        <h1>Title</h1>
        <p style="display:none;">This is hidden.</p>
        <p>This is visible.</p>
        <table>
            <tr><th>Header 1</th><th>Header 2</th></tr>
            <tr><td>Data 1</td><td>Data 2</td></tr>
        </table>
    </body>
    </html>
    """
    parser = FilingParser()
    md = parser.parse_html(html)
    
    assert "Title" in md
    assert "This is visible." in md
    assert "This is hidden." not in md
    assert "console.log" not in md
    assert ".hidden" not in md
    
    # Check that table converted
    assert "Header 1" in md
    assert "Data 1" in md


def test_strip_repeated_lines_removes_running_footer():
    # The footer differs only by page number; its normalized form recurs on every
    # "page", so it is stripped. The one-off footnote and prose survive.
    parser = FilingParser(footer_repeat_threshold=5)
    # Distinct prose per page (as real content is), each followed by the running
    # footer that differs only by page number.
    prose = [
        "Supply chain concentration exposes us to component shortages.",
        "Foreign exchange volatility may reduce reported net sales.",
        "We face intense competition across all product categories.",
        "Our business is subject to evolving global tax regulation.",
        "Intellectual-property disputes could be costly to defend.",
        "Reliance on outsourcing partners concentrates operational risk.",
        "Cybersecurity incidents could disrupt services and harm trust.",
    ]
    md = "\n".join(
        f"{prose[p - 1]}\nApple Inc. | 2024 Form 10-K | {p}" for p in range(1, 8)
    ) + "\n(1) Excludes restructuring charges of $2.3 billion."

    out = parser._strip_repeated_lines(md)

    assert "Apple Inc." not in out                       # running footer gone
    assert "Excludes restructuring charges" in out        # unique footnote kept
    for line in prose:                                    # all distinct prose kept
        assert line in out


def test_strip_repeated_lines_keeps_below_threshold():
    # A line repeating fewer than threshold times is not furniture — keep it.
    parser = FilingParser(footer_repeat_threshold=5)
    md = "\n".join("Apple Inc. | 2024 Form 10-K | %d" % p for p in range(1, 4))

    out = parser._strip_repeated_lines(md)

    assert out.count("Apple Inc.") == 3


def test_strip_repeated_lines_never_drops_table_rows():
    # An identical table row repeated many times must survive — table content is
    # off-limits regardless of frequency.
    parser = FilingParser(footer_repeat_threshold=3)
    md = "\n".join("| cell | cell |" for _ in range(10))

    out = parser._strip_repeated_lines(md)

    assert out.count("| cell | cell |") == 10
