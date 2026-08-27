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
