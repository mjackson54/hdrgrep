import io
import json
import unittest

from hdrgrep.cli import find_header, find_headers, iter_blocks, run


def block_lines(*lines):
    """Build an iterable of lines the way a file object would yield them."""
    return [line + "\n" for line in lines]


class IterBlocksTests(unittest.TestCase):
    def test_single_block_with_status_line(self):
        lines = block_lines(
            "HTTP/1.1 200 OK",
            "Content-Type: text/html",
            "Cache-Control: no-store",
            "",
        )
        blocks = list(iter_blocks(lines))
        self.assertEqual(len(blocks), 1)
        start_line, headers = blocks[0]
        self.assertEqual(start_line, "HTTP/1.1 200 OK")
        self.assertEqual(
            headers, [("Content-Type", "text/html"), ("Cache-Control", "no-store")]
        )

    def test_multiple_blocks_back_to_back(self):
        lines = block_lines(
            "HTTP/1.1 200 OK",
            "Content-Type: text/html",
            "",
            "HTTP/1.1 404 Not Found",
            "Content-Type: application/json",
            "",
        )
        blocks = list(iter_blocks(lines))
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0][1], [("Content-Type", "text/html")])
        self.assertEqual(blocks[1][1], [("Content-Type", "application/json")])

    def test_block_without_trailing_blank_line_is_still_yielded(self):
        # A file that ends mid-block (no final blank line) shouldn't lose data.
        lines = block_lines(
            "HTTP/1.1 200 OK",
            "Content-Type: text/html",
        )
        blocks = list(iter_blocks(lines))
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0][1], [("Content-Type", "text/html")])

    def test_block_without_start_line(self):
        lines = block_lines(
            "Content-Type: text/html",
            "",
        )
        blocks = list(iter_blocks(lines))
        start_line, headers = blocks[0]
        self.assertIsNone(start_line)
        self.assertEqual(headers, [("Content-Type", "text/html")])

    def test_line_folding_appends_to_previous_value(self):
        lines = block_lines(
            "HTTP/1.1 200 OK",
            "Cache-Control: max-age=0,",
            " private",
            "",
        )
        blocks = list(iter_blocks(lines))
        self.assertEqual(blocks[0][1], [("Cache-Control", "max-age=0, private")])

    def test_line_folding_with_tab_indent(self):
        lines = block_lines(
            "HTTP/1.1 200 OK",
            "X-Note: first part",
            "\tsecond part",
            "",
        )
        blocks = list(iter_blocks(lines))
        self.assertEqual(blocks[0][1], [("X-Note", "first part second part")])

    def test_leading_indented_line_with_no_preceding_header_becomes_start_line(self):
        # An indented line has nothing to fold onto when it's the first line
        # of a block, so it's treated like any other non-header line: it
        # becomes the start line rather than being silently dropped.
        lines = block_lines(
            "  stray continuation",
            "Content-Type: text/html",
            "",
        )
        blocks = list(iter_blocks(lines))
        start_line, headers = blocks[0]
        self.assertEqual(start_line, "  stray continuation")
        self.assertEqual(headers, [("Content-Type", "text/html")])

    def test_malformed_line_inside_block_is_skipped(self):
        lines = block_lines(
            "HTTP/1.1 200 OK",
            "Content-Type: text/html",
            "this is not a header line",
            "Cache-Control: no-store",
            "",
        )
        blocks = list(iter_blocks(lines))
        self.assertEqual(
            blocks[0][1],
            [("Content-Type", "text/html"), ("Cache-Control", "no-store")],
        )

    def test_second_malformed_line_is_not_mistaken_for_start_line(self):
        # Only the very first non-header line of a block can become the
        # start line; anything after headers have begun is just skipped.
        lines = block_lines(
            "HTTP/1.1 200 OK",
            "Content-Type: text/html",
            "another garbage line",
            "",
        )
        blocks = list(iter_blocks(lines))
        start_line, headers = blocks[0]
        self.assertEqual(start_line, "HTTP/1.1 200 OK")
        self.assertEqual(headers, [("Content-Type", "text/html")])

    def test_carriage_returns_are_stripped(self):
        lines = ["HTTP/1.1 200 OK\r\n", "Content-Type: text/html\r\n", "\r\n"]
        blocks = list(iter_blocks(lines))
        self.assertEqual(blocks[0][0], "HTTP/1.1 200 OK")
        self.assertEqual(blocks[0][1], [("Content-Type", "text/html")])

    def test_empty_input_yields_no_blocks(self):
        self.assertEqual(list(iter_blocks([])), [])

    def test_consecutive_blank_lines_yield_no_empty_blocks(self):
        lines = block_lines(
            "HTTP/1.1 200 OK",
            "Content-Type: text/html",
            "",
            "",
            "",
        )
        blocks = list(iter_blocks(lines))
        self.assertEqual(len(blocks), 1)


class FindHeaderTests(unittest.TestCase):
    def test_matches_case_insensitively(self):
        headers = [("Content-Type", "text/html")]
        self.assertEqual(
            find_header(headers, "content-type"), [("Content-Type", "text/html")]
        )

    def test_returns_all_matches_in_order(self):
        headers = [
            ("Set-Cookie", "a=1"),
            ("Content-Type", "text/html"),
            ("Set-Cookie", "b=2"),
        ]
        self.assertEqual(
            find_header(headers, "Set-Cookie"), [("Set-Cookie", "a=1"), ("Set-Cookie", "b=2")]
        )

    def test_no_match_returns_empty_list(self):
        headers = [("Content-Type", "text/html")]
        self.assertEqual(find_header(headers, "X-Missing"), [])

    def test_exact_case_rejects_different_casing(self):
        headers = [("Content-Type", "text/html")]
        self.assertEqual(
            find_header(headers, "content-type", exact_case=True), []
        )

    def test_exact_case_matches_identical_casing(self):
        headers = [("Content-Type", "text/html")]
        self.assertEqual(
            find_header(headers, "Content-Type", exact_case=True),
            [("Content-Type", "text/html")],
        )


class FindHeadersTests(unittest.TestCase):
    def test_matches_any_of_several_names_in_block_order(self):
        headers = [
            ("Set-Cookie", "a=1"),
            ("Content-Type", "text/html"),
            ("X-Other", "ignored"),
        ]
        self.assertEqual(
            find_headers(headers, ["content-type", "set-cookie"]),
            [("Set-Cookie", "a=1"), ("Content-Type", "text/html")],
        )

    def test_no_names_matches_nothing(self):
        headers = [("Content-Type", "text/html")]
        self.assertEqual(find_headers(headers, []), [])

    def test_exact_case_matches_only_requested_spelling(self):
        headers = [
            ("content-type", "text/html"),
            ("Content-Type", "application/json"),
        ]
        self.assertEqual(
            find_headers(headers, ["Content-Type"], exact_case=True),
            [("Content-Type", "application/json")],
        )


class RunTests(unittest.TestCase):
    def test_prints_matching_values(self):
        lines = block_lines(
            "HTTP/1.1 200 OK",
            "Content-Type: text/html",
            "",
            "HTTP/1.1 200 OK",
            "Content-Type: application/json",
            "",
        )
        out = io.StringIO()
        run(lines, ["content-type"], out, count_only=False, with_name=False)
        self.assertEqual(out.getvalue(), "text/html\napplication/json\n")

    def test_with_name_prefixes_original_name(self):
        lines = block_lines("Content-Type: text/html", "")
        out = io.StringIO()
        run(lines, ["content-type"], out, count_only=False, with_name=True)
        self.assertEqual(out.getvalue(), "Content-Type: text/html\n")

    def test_count_only_prints_block_count_not_values(self):
        lines = block_lines(
            "Content-Type: text/html",
            "",
            "X-Other: yes",
            "",
            "Content-Type: application/json",
            "",
        )
        out = io.StringIO()
        run(lines, ["content-type"], out, count_only=True, with_name=False)
        self.assertEqual(out.getvalue(), "2\n")

    def test_no_matches_prints_nothing(self):
        lines = block_lines("Content-Type: text/html", "")
        out = io.StringIO()
        run(lines, ["x-missing"], out, count_only=False, with_name=False)
        self.assertEqual(out.getvalue(), "")

    def test_multiple_header_names_match_in_block_order(self):
        lines = block_lines(
            "HTTP/1.1 200 OK",
            "Set-Cookie: a=1",
            "Content-Type: text/html",
            "Cache-Control: no-store",
            "",
        )
        out = io.StringIO()
        run(
            lines,
            ["content-type", "set-cookie"],
            out,
            count_only=False,
            with_name=True,
        )
        self.assertEqual(
            out.getvalue(), "Set-Cookie: a=1\nContent-Type: text/html\n"
        )

    def test_multiple_header_names_count_blocks_matching_any(self):
        lines = block_lines(
            "Content-Type: text/html",
            "",
            "Set-Cookie: a=1",
            "",
            "X-Other: yes",
            "",
        )
        out = io.StringIO()
        run(
            lines,
            ["content-type", "set-cookie"],
            out,
            count_only=True,
            with_name=False,
        )
        self.assertEqual(out.getvalue(), "2\n")

    def test_exact_case_excludes_differently_cased_header(self):
        lines = block_lines(
            "content-type: text/html",
            "",
            "Content-Type: application/json",
            "",
        )
        out = io.StringIO()
        run(
            lines,
            ["Content-Type"],
            out,
            count_only=False,
            with_name=False,
            exact_case=True,
        )
        self.assertEqual(out.getvalue(), "application/json\n")

    def test_json_output_prints_one_object_per_match(self):
        lines = block_lines(
            "HTTP/1.1 200 OK",
            "Content-Type: text/html",
            "",
            "HTTP/1.1 200 OK",
            "Content-Type: application/json",
            "",
        )
        out = io.StringIO()
        run(
            lines,
            ["content-type"],
            out,
            count_only=False,
            with_name=False,
            json_output=True,
        )
        records = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(
            records,
            [
                {"name": "Content-Type", "value": "text/html"},
                {"name": "Content-Type", "value": "application/json"},
            ],
        )

    def test_json_output_with_count(self):
        lines = block_lines(
            "Content-Type: text/html",
            "",
            "X-Other: yes",
            "",
        )
        out = io.StringIO()
        run(
            lines,
            ["content-type"],
            out,
            count_only=True,
            with_name=False,
            json_output=True,
        )
        self.assertEqual(json.loads(out.getvalue()), {"count": 1})


if __name__ == "__main__":
    unittest.main()
