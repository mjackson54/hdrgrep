"""Extract one header's value from a stream of raw HTTP header blocks.

Input is expected to look like what `curl -D -` writes: an optional
request/status line, then "Name: value" header lines, then a blank line.
Any number of these blocks can be concatenated back to back in one file,
which is what you get from appending curl's -D output across many requests
in a load test or a scripted crawl.

The whole point of this tool is that such a file can be gigabytes long, so
we never read it in one go. We walk it line by line and only ever hold the
headers of the current block in memory.
"""

import argparse
import re
import sys

# RFC 7230 section 3.2: a header field-name is a token, and tokens are made
# of these characters. Matching against this (rather than just splitting on
# the first colon) is what lets us tell a header line apart from a request
# or status line, since "GET / HTTP/1.1" and "HTTP/1.1 200 OK" don't match.
HEADER_RE = re.compile(r"^([!#$%&'*+\-.^_`|~0-9A-Za-z]+):[ \t]*(.*)$")


def iter_blocks(lines):
    """Yield (start_line, headers) for each header block in an iterable of lines.

    headers is a list of (name, value) tuples, in the order they appeared.
    start_line is the request/status line if one was present, else None.
    Only the current block's data is ever held onto, so this stays cheap
    no matter how many blocks the input contains.
    """
    start_line = None
    headers = []
    in_block = False

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")

        if line == "":
            if in_block:
                yield start_line, headers
            start_line = None
            headers = []
            in_block = False
            continue

        in_block = True

        if line[:1] in (" ", "\t") and headers:
            # Obsolete line folding (RFC 7230 section 3.2.4): a continuation
            # of the previous header's value on the next line.
            name, value = headers[-1]
            headers[-1] = (name, value + " " + line.strip())
            continue

        match = HEADER_RE.match(line)
        if match:
            headers.append((match.group(1), match.group(2)))
        elif not headers and start_line is None:
            start_line = line
        # else: a malformed line inside a block; skip it rather than abort
        # a multi-gigabyte run over one bad line.

    if in_block:
        yield start_line, headers


def find_headers(headers, names):
    """Return headers matching any of names, case-insensitively.

    Matches are returned in the order they appeared in the block, not
    grouped by which requested name they matched, so output with multiple
    -H flags reads the same as the original block.
    """
    lowered = {name.lower() for name in names}
    return [(n, v) for n, v in headers if n.lower() in lowered]


def find_header(headers, name):
    """Return the values of all headers matching name, case-insensitively."""
    return find_headers(headers, (name,))


def run(lines, header_names, out, count_only, with_name):
    matches = 0
    for _start_line, headers in iter_blocks(lines):
        found = find_headers(headers, header_names)
        if not found:
            continue
        matches += 1
        if count_only:
            continue
        for name, value in found:
            if with_name:
                out.write(f"{name}: {value}\n")
            else:
                out.write(f"{value}\n")

    if count_only:
        out.write(f"{matches}\n")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="hdrgrep",
        description=(
            "Extract a header's value from a stream of raw HTTP header "
            "blocks (as written by `curl -D -`), one match per line."
        ),
    )
    parser.add_argument(
        "file",
        nargs="?",
        default="-",
        help="file to read (default: stdin)",
    )
    parser.add_argument(
        "-H",
        "--header",
        action="append",
        required=True,
        metavar="NAME",
        help=(
            "header name to extract, e.g. Content-Type (matched case-insensitively). "
            "Repeat to extract multiple headers in one pass."
        ),
    )
    parser.add_argument(
        "-c",
        "--count",
        action="store_true",
        help="print the number of blocks containing any requested header, instead of its values",
    )
    parser.add_argument(
        "--with-name",
        action="store_true",
        help="prefix each printed value with the header's original name",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.file == "-":
        run(sys.stdin, args.header, sys.stdout, args.count, args.with_name)
        return 0

    try:
        with open(args.file, "r", encoding="utf-8", errors="replace") as fh:
            run(fh, args.header, sys.stdout, args.count, args.with_name)
    except OSError as exc:
        print(f"hdrgrep: {exc.filename}: {exc.strerror}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
