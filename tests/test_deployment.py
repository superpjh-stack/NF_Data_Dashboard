import base64
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import sys
import tempfile
from threading import Thread
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from server import authorized,source,Handler

class AuthenticationTests(unittest.TestCase):
    def header(self,user='tester',password='test-password'):
        return 'Basic '+base64.b64encode(f'{user}:{password}'.encode()).decode()
    def test_local_default_and_required_missing_credentials(self):
        with patch.dict(os.environ,{},clear=True):self.assertTrue(authorized(None))
        with patch.dict(os.environ,{'DASHBOARD_AUTH_REQUIRED':'1'},clear=True):
            self.assertFalse(authorized(None));self.assertFalse(authorized(self.header()))
    def test_valid_invalid_and_malformed_headers(self):
        with patch.dict(os.environ,{'DASHBOARD_USER':'tester','DASHBOARD_PASSWORD':'test-password'},clear=True):
            self.assertTrue(authorized(self.header()))
            for h in (None,'Basic !!!','Bearer token','Basic '+base64.b64encode(b'no-colon').decode(),self.header(password='wrong'),self.header(user='wrong')):
                self.assertFalse(authorized(h))
    def test_partial_configuration_fails_closed(self):
        with patch.dict(os.environ,{'DASHBOARD_USER':'tester'},clear=True):self.assertFalse(authorized(self.header()))
    def test_all_data_routes_require_login(self):
        with patch.dict(os.environ,{'DASHBOARD_AUTH_REQUIRED':'1','DASHBOARD_USER':'tester','DASHBOARD_PASSWORD':'test-password'},clear=True),patch.object(Handler,'log_message'):
            httpd=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            thread=Thread(target=httpd.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{httpd.server_port}'
            try:
                for path in ('/','/api/overview','/api/eda','/download?id=x','/api/sheet?id=x','/eda-report','/export','/app.js','/style.css'):
                    with self.assertRaises(HTTPError) as caught:urlopen(base+path)
                    self.assertEqual(caught.exception.code,401)
                    caught.exception.close()
                with urlopen(Request(base+'/',headers={'Authorization':self.header()})) as r:self.assertEqual(r.status,200)
                try:
                    with urlopen(base+'/healthz') as r:self.assertEqual(r.status,200)
                except HTTPError as e:self.assertEqual(e.code,503);e.close()
            finally:httpd.shutdown();httpd.server_close();thread.join()

class SourceMountTests(unittest.TestCase):
    def test_source_root_override_and_path_escape(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'sources';root.mkdir();(root/'sample.xlsx').write_bytes(b'fixture')
            db=Mock();db.execute.return_value.fetchone.return_value={'id':'x','path':'sample.xlsx'}
            with patch.dict(os.environ,{'SOURCE_ROOT':str(root)}):
                _,path=source(db,'x');self.assertEqual(path,(root/'sample.xlsx').resolve())
                outside=Path(td)/'outside.txt';outside.write_text('outside')
                db.execute.return_value.fetchone.return_value={'id':'x','path':'../outside.txt'}
                with self.assertRaises(FileNotFoundError):source(db,'x')
                (root/'link.txt').symlink_to(outside)
                db.execute.return_value.fetchone.return_value={'id':'x','path':'link.txt'}
                with self.assertRaises(FileNotFoundError):source(db,'x')

if __name__=='__main__':unittest.main()
