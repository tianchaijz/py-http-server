MHTTPServerWFM
==============

A Python multithreading HTTP server extended from the standard
`SimpleHTTPServer` module with which you can upload and delete files and it can
calculate file's sha1sum for verifing.

The server uses UTF-8 as the default encoding for html display. `CJK` characters
are displayed correctly in both browser and terminal wherever the server is
running at \*nix or Windows platforms.

**Warning**: It only works under Python 2.

## USAGE
```
python MHTTPServerWFM.py [port] [path]
```
