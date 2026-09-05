# hdrgrep

Pull one header's value out of a big pile of raw HTTP header dumps.

## the problem

If you've ever run something like this in a loop against a hundred thousand
URLs:

```sh
curl -sD - -o /dev/null "$url" >> dump.txt
```

you end up with a file where each response's headers are appended one after
another, separated by blank lines:

```
HTTP/1.1 200 OK
Content-Type: text/html; charset=utf-8
Cache-Control: max-age=0, private
Set-Cookie: session=abc123; Path=/

HTTP/1.1 200 OK
Content-Type: application/json
Cache-Control: no-store

...
```

Now you want to know: what `Cache-Control` values actually came back across
all those requests? Opening a multi-gigabyte file in an editor doesn't work,
and a quick script that does `f.read()` and splits on blank lines will load
the whole thing into memory before it prints a single line.

`hdrgrep` reads the file line by line, keeps only the current block's
headers in memory, and prints matches as it finds them. It behaves the same
whether the input is 10 lines or 10 million.

## usage

```sh
hdrgrep -H Cache-Control dump.txt
```

```
max-age=0, private
no-store
```

Read from stdin instead of a file:

```sh
cat dump.txt | hdrgrep -H content-type
```

Header names are matched case-insensitively, since that's how HTTP treats
them.

Count how many blocks had the header at all, instead of printing values:

```sh
hdrgrep -H set-cookie --count dump.txt
```

Keep the header's original name attached to each printed value:

```sh
hdrgrep -H content-type --with-name dump.txt
```

```
Content-Type: text/html; charset=utf-8
Content-Type: application/json
```

## input format

Each block is a request line or status line (optional), followed by
`Name: value` header lines, followed by a blank line. This is exactly what
`curl -D -` writes per request, so the common way to build an input file is
appending its output across many requests. Obsolete line folding (a header
value continued on an indented line) is supported; chunked or
otherwise-encoded message bodies are not read or skipped, so don't point
this at raw traffic dumps that still have bodies in them.

## running it

No dependencies beyond the standard library.

```sh
python -m hdrgrep -H content-type dump.txt
```

or install it locally:

```sh
pip install -e .
hdrgrep -H content-type dump.txt
```

## license

MIT, see LICENSE.
