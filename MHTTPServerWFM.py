#!/usr/bin/env python
# encoding: utf-8

"""Multiple Threading HTTP Server With File Management.

This program is extended from the standard `SimpleHTTPServer` module by adding
upload and delete file features.

"""

__version__ = "0.1"
__all__ = ["HTTPRequestHandlerWFM"]
__author__ = "Jinzheng Zhang"
__email__ = "tianchaijz@gmail.com"
__git__ = "https://github.com/tianchaijz/MTHTTPServerWFM"


import os
import sys
import re
import cgi
import json
import shutil
import socket
import urllib
import hashlib
import logging
import mimetypes
import posixpath
import threading
from copy import deepcopy
from SocketServer import ThreadingMixIn
from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO


# ============================== Config ==============================
ENC = sys.stdout.encoding
ENC_MAP = {"cp936": "gbk"}
CHARSET = ENC_MAP.get(ENC, "utf-8")

reload(sys)
sys.setdefaultencoding("utf-8")

logging.basicConfig(level=logging.DEBUG)

FILE_NAME = os.path.basename(str(__file__)).split('.')[0]
# ====================================================================


class HTMLStyle(object):
    CSS = """
body { background:#FFF; color:#000;
font-family:Helvetica, Arial, sans-serif; }
h1 { margin:.5em 0 0; }
h2 { margin:.8em 0 .3em; }
h3 { margin:.5em 0 .3em; }

table { font-size:.8em; border-collapse:collapse;
border-bottom:1px #DED solid; width:100%; margin:.5em 0; }

thead th { font-size:1em; background:#DED;
border:.2em solid #FFF; padding:.1em .3em; }

tbody tr.odd { background:#F5F5F5; }
tbody th { text-align:left; }
tbody td { height:1.2em; text-align:right; }
"""
    GETPAGE = """
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8"/>
    <title>Directory listing for {directory}</title>
    <style>{css}</style>
  </head>
<body>
  <h2>Directory listing for {directory}</h2>
  <div>
    <hr>
    <form enctype="multipart/form-data" method="post">
      Upload File: <input name="file" type="file"/>
      <input type="submit" value="Upload"/>
    </form>
    <hr>
  </div>
  <div>
    <form action="/delete" method="post">
      Delete File: <input type="text" name="filename">
      <input type="submit" value="Submit">
    </form>
    <hr>
  </div>
  <div>
    <table>
      <thead>
        <tr> <th rowspan="2">NAME</th> <th colspan="2">INFO</th> </tr>
        <tr> <th>SIZE</th> <th>SHA1SUM</th> </tr>
      </thead>
"""
    POSTPAGE = """
<!DOCTYPE html>
  <html>
  <head> <meta charset="utf-8"/> <title>Result Page</title> </head>
  <body>
    <h2>Result:</h2>
    <hr>
    <strong>{result}: </strong>
    {msg}
    <hr><br><a href="{refer}">Go Back</a>
  <body>
</html>
"""
    TBODY = """
<tbody>
  {tr_class}
    <th><a href="{linkname}">{displayname}</a></th>
    <td>{size}</td> <td>{sha1sum}</td>
  </tr>
</tbody>
"""

    def __init__(self):
        self.count = 0

    def gen_getpage(self, **kwargs):
        kwargs["css"] = HTMLStyle.CSS
        return HTMLStyle.GETPAGE.format(**kwargs)

    def gen_postpage(self, **kwargs):
        return HTMLStyle.POSTPAGE.format(**kwargs)

    def gen_table_body(self, **kwargs):
        self.count = 1 - self.count
        if self.count > 0:
            tr_class = '<tr class="odd">'
        else:
            tr_class = '<tr>'
        kwargs["tr_class"] = tr_class
        return HTMLStyle.TBODY.format(**kwargs)


class FileInfoHandler(object):
    FILE_LOCK = threading.Lock()

    def __init__(self):
        self.info_file = "__%s.json" % FILE_NAME
        self.lock = threading.Lock()
        try:
            FileInfoHandler.FILE_LOCK.acquire()
            with open(self.info_file, 'rb') as fd:
                self.info = json.load(fd, encoding=ENC)
        except Exception, e:
            logging.exception(str(e))
        finally:
            FileInfoHandler.FILE_LOCK.release()
            if not hasattr(self, "info"):
                self.info = {}
                self.flush_info()
        self.oldinfo = deepcopy(self.info)

    def _gen_info(self, file):
        def hashfile(fd, hasher, blocksize=65536):
            buf = fd.read(blocksize)
            while len(buf) > 0:
                hasher.update(buf)
                buf = fd.read(blocksize)
            return hasher.hexdigest()

        try:
            size = str(os.path.getsize(file))
            mtime = str(os.path.getmtime(file))
            with open(file, 'rb') as fd:
                sha1sum = hashfile(fd, hashlib.sha1())
            self.lock.acquire()
            self.info[file] = {
                "sha1sum": sha1sum,
                "size": size,
                "mtime": mtime
            }
        except IOError, e:
            logging.exception("!!!! %s: %s" % (file, str(e)))
        finally:
            self.lock.release()
        self.flush_info()

    def get_info(self, file):
        file_info = self.info.get(file, False)
        if file_info:
            file_mtime = os.path.getmtime(file)
            if str(file_mtime) != file_info["mtime"]:
                logging.info("---- update file info - %s" % file)
                self.add_info(file)
            return file_info
        else:
            if os.path.isfile(file):
                self.add_info(file)
            return self.dummy_info()

    def del_info(self, file):
        try:
            self.lock.acquire()
            del self.info[file]
            logging.info("---- delete file info - %s" % file)
        except KeyError:
            logging.exception("!!!! %s not found" % file)
        except ValueError, e:
            logging.exception(str(e))
        finally:
            self.lock.release()
        self.flush_info()

    def add_info(self, file):
        if os.path.isfile(file):
            thread = threading.Thread(
                target=self._gen_info,
                args=(file,),
                name="Thread-" + file,
            )
            thread.daemon = True
            thread.start()

    def flush_info(self):
        try:
            FileInfoHandler.FILE_LOCK.acquire()
            self.lock.acquire()
            with open(self.info_file, 'wb') as fd:
                json.dump(self.info, fd, encoding=ENC)
        except Exception, e:
            logging.exception(str(e))
        finally:
            self.lock.release()
            FileInfoHandler.FILE_LOCK.release()

    def need_flush(self):
        info_diff = set(self.info) - set(self.oldinfo)
        if info_diff:
            return True
        return False

    def dummy_info(self):
        return {"size": '', "sha1sum": ''}


class HTTPRequestHandlerWFM(BaseHTTPRequestHandler):

    """HTTP request handler with GET, HEAD and POST commands.

    This serves files from the current directory and any of its
    subdirectories.  The MIME type for files is determined by
    calling the .guess_type() method.

    The GET, HEAD and POST requests are identical except that the HEAD
    request omits the actual contents of the file.

    """

    server_version = "MHTTPServerWFM/" + __version__

    WORK_PATH = os.getcwd()
    FIH = FileInfoHandler()
    HS = HTMLStyle()

    def __init__(self, *args, **kwargs):
        logging.debug(">>>> __init__ %s" % (self.__class__.__name__))
        self.fih = HTTPRequestHandlerWFM.FIH
        self.hs = HTTPRequestHandlerWFM.HS
        BaseHTTPRequestHandler.__init__(self, *args, **kwargs)

    def do_GET(self):
        """Serve a GET request."""
        logging.debug(">>>> current thread: %s" % threading.current_thread())
        f = self.send_head()
        if f:
            try:
                self.copyfile(f, self.wfile)
            finally:
                f.close()

    def do_HEAD(self):
        """Serve a HEAD request."""
        f = self.send_head()
        if f:
            f.close()

    def do_POST(self):
        """Serve a POST request."""
        def parse_post_data():
            if self.path == "/delete":
                form = cgi.FieldStorage(
                    fp=self.rfile,
                    headers=self.headers,
                    environ={
                        "REQUEST_METHOD": "POST",
                        "CONTENT_TYPE": self.headers["Content-Type"],
                    }
                )
                filename = form.getvalue("filename")
                if filename is None:
                    return (False, "no file specified")
                filename = urllib.unquote(filename).decode("utf-8")
                work_path = HTTPRequestHandlerWFM.WORK_PATH
                if os.path.isdir(work_path):
                    fullname = os.path.join(work_path, filename)
                    try:
                        os.remove(fullname)
                        self.fih.del_info(fullname)
                        logging.warn("deleting file %s" % fullname.encode(ENC))
                        return (True,
                                "file %s deleted" % fullname)
                    except OSError, e:
                        return (False, str(e).decode("string_escape"))
            else:
                return self.deal_post_file()

        res, msg = parse_post_data()
        logging.info("==== POST %s, %s, by: %s"
                     % (res, msg, self.client_address))
        f = StringIO()
        postpage = self.hs.gen_postpage(
            result=str(res),
            msg=msg,
            refer=self.headers["Referer"]
        )
        f.write(postpage)
        length = f.tell()
        f.seek(0)
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        if f:
            self.copyfile(f, self.wfile)
            f.close()

    def deal_post_file(self):
        self.is_upload = True
        try:
            boundary = self.headers.plisttext.split("=")[1]
        except IndexError:
            self.is_upload = False

        if self.is_upload:
            content_length = remainbytes = int(self.headers["Content-Length"])
            line = self.rfile.readline()
            remainbytes -= len(line)
            if boundary not in line:
                return (False, "content can't begin with boundary")
            line = self.rfile.readline()
            remainbytes -= len(line)
            fn = re.findall(
                r'Content-Disposition.*name="file"; filename="(.+)"',
                line
            )
            if not fn:
                return (False, "can't find out the file name")
            path = self.translate_path(self.path)
            fn = os.path.join(path, fn[0].decode("utf-8"))
            while os.path.exists(fn):
                fn += "_"
            line = self.rfile.readline()
            remainbytes -= len(line)
            line = self.rfile.readline()
            remainbytes -= len(line)
            try:
                out = open(fn, 'wb')
                logging.info("==== POST File: %s, Content-Length: %d"
                             % (fn.encode(ENC), content_length))
                logging.info("---- writing to file: %s" % fn)
            except IOError, e:
                return (False, "can't create file: %s" % str(e))

            preline = self.rfile.readline()
            remainbytes -= len(preline)
            while remainbytes > 0:
                line = self.rfile.readline()
                remainbytes -= len(line)
                if boundary in line:
                    preline = preline[0:-1]
                    if preline.endswith('\r'):
                        preline = preline[0:-1]
                    out.write(preline)
                    out.close()
                    return (True, "file '%s' uploaded" % fn)
                else:
                    out.write(preline)
                    preline = line
            return (False, "unexpect ends of data.")
        else:
            body = self.rfile.read()
            return (False, "unknow post data: %s ..." % body[0:9])

    def send_head(self):
        """Common code for GET and HEAD commands.

        This sends the response code and MIME headers.

        Return value is either a file object (which has to be copied
        to the outputfile by the caller unless the command was HEAD,
        and must be closed by the caller under all circumstances), or
        None, in which case the caller has nothing further to do.

        """
        path = self.translate_path(self.path)
        f = None
        if os.path.isdir(path):
            if not self.path.endswith('/'):
                # redirect browser - doing basically what apache does
                self.send_response(301)
                self.send_header("Location", self.path + "/")
                self.end_headers()
                return None
            for index in "index.html", "index.htm":
                index = os.path.join(path, index)
                if os.path.exists(index):
                    path = index
                    break
            else:
                HTTPRequestHandlerWFM.WORK_PATH = path
                return self.list_directory(path)
        ctype = "%s; charset=%s" % (self.guess_type(path), CHARSET)
        try:
            # Always read in binary mode. Opening files in text mode may cause
            # newline translations, making the actual size of the content
            # transmitted *less* than the content-length!
            f = open(path, 'rb')
            logging.info("==== GET File: %s" % path.encode(ENC))
        except IOError, e:
            self.send_error(404, str(e))
            return None
        try:
            self.send_response(200)
            self.send_header("Content-type", ctype)
            fs = os.fstat(f.fileno())
            self.send_header("Content-Length", str(fs[6]))
            self.send_header(
                "Last-Modified",
                self.date_time_string(fs.st_mtime)
            )
            self.end_headers()
            return f
        except:
            f.close()
            raise

    def list_directory(self, path):
        """Helper to produce a directory listing (absent index.html).

        Return value is either a file object, or None (indicating an
        error).  In either case, the headers are sent, making the
        interface the same as for send_head().

        """
        try:
            files = os.listdir(path)
            list = map(lambda s:
                       (s if isinstance(s, unicode) else s.decode(ENC)), files)
            logging.info("==== GET Directory: %s" % path.encode(ENC))
        except os.error:
            self.send_error(403, "No permission to list directory")
            return None
        list.sort(key=lambda a: a.lower())
        f = StringIO()
        displaypath = cgi.escape(urllib.unquote(self.path))
        f.write(self.hs.gen_getpage(directory=displaypath))
        for name in list:
            fullname = os.path.join(path, name)
            displayname = linkname = name
            info = self.fih.get_info(fullname)

            # Append / for directories or @ for symbolic links
            if os.path.isdir(fullname):
                displayname = name + "/"
                linkname = name + "/"
            if os.path.islink(fullname):
                displayname = name + "@"
                # Note: a link to a directory displays with @ and links with /
            f.write(self.hs.gen_table_body(
                linkname=urllib.quote(linkname.encode("utf-8")),
                displayname=cgi.escape(displayname.encode("utf-8")),
                **info
            ))
        f.write("\n".join(["</table>", "</div>", "</body>", "</html>"]))
        length = f.tell()
        f.seek(0)
        self.send_response(200)
        self.send_header("Content-Length", str(length))
        self.end_headers()
        if self.fih.need_flush():
            self.fih.flush_info()
        return f

    def translate_path(self, path):
        """Translate a /-separated PATH to the local filename syntax.

        Components that mean special things to the local file system
        (e.g. drive or directory names) are ignored.  (XXX They should
        probably be diagnosed.)

        """
        # abandon query parameters
        path = path.split('?', 1)[0]
        path = path.split('#', 1)[0]
        # Don't forget explicit trailing slash when normalizing. Issue17324
        trailing_slash = path.rstrip().endswith('/')
        path = posixpath.normpath(urllib.unquote(path).decode("utf-8"))
        words = path.split('/')
        words = filter(None, words)
        path = os.getcwd()
        for word in words:
            drive, word = os.path.splitdrive(word)
            head, word = os.path.split(word)
            if word in (os.curdir, os.pardir):
                continue
            path = os.path.join(path, word)
        if trailing_slash:
            path += '/'
        return path

    def copyfile(self, source, outputfile):
        """Copy all data between two file objects.

        The SOURCE argument is a file object open for reading
        (or anything with a read() method) and the DESTINATION
        argument is a file object open for writing (or
        anything with a write() method).

        The only reason for overriding this would be to change
        the block size or perhaps to replace newlines by CRLF
        -- note however that this the default server uses this
        to copy binary data as well.

        """
        shutil.copyfileobj(source, outputfile)

    def guess_type(self, path):
        """Guess the type of a file.

        Argument is a PATH (a filename).

        Return value is a string of the form type/subtype,
        usable for a MIME Content-type header.

        The default implementation looks the file's extension
        up in the table self.extensions_map, using application/octet-stream
        as a default; however it would be permissible (if
        slow) to look inside the data to make a better guess.

        """

        base, ext = posixpath.splitext(path)
        if ext in self.extensions_map:
            return self.extensions_map[ext]
        ext = ext.lower()
        if ext in self.extensions_map:
            return self.extensions_map[ext]
        else:
            return self.extensions_map['']

    if not mimetypes.inited:
        mimetypes.init()  # try to read system mime.types
    extensions_map = mimetypes.types_map.copy()
    extensions_map.update({
        '': 'application/octet-stream',  # Default
        '.c': 'text/plain',
        '.h': 'text/plain',
        '.sh': 'text/plain',
        '.py': 'text/plain',
        '.txt': 'text/plain',
        '.lua': 'text/plain',
        '.json': 'application/json',
    })


class MultiThreadingServer(ThreadingMixIn, HTTPServer):
    pass


def main():
    if sys.argv[1:]:
        port = int(sys.argv[1])
    else:
        port = 8000

    if sys.argv[2:]:
        os.chdir(sys.argv[2])

    server_address = ('', port)
    server = MultiThreadingServer(server_address, HTTPRequestHandlerWFM)
    sa = server.socket.getsockname()

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        print("IP Address", s.getsockname()[0])
        s.close()
    except:
        pass

    print "Serving HTTP on", sa[0], "port", sa[1], "..."
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Serving Finished.")

if __name__ == '__main__':
    main()
