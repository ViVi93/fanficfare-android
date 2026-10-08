# -*- coding: utf-8 -*-

# Copyright 2022 FanFicFare team
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import logging
logger = logging.getLogger(__name__)

# py2 vs py3 transition
from .. import exceptions

from urllib3.util.retry import Retry
from urllib.parse import urlparse
import requests
from requests.exceptions import HTTPError as RequestsHTTPError
from requests.adapters import HTTPAdapter
from requests_file import FileAdapter

## makes requests/cloudscraper dump req/resp headers.
# import http.client as http_client
# http_client.HTTPConnection.debuglevel = 5

from .log import make_log
from .base_fetcher import FetcherResponse, Fetcher

class RequestsFetcher(Fetcher):
    def __init__(self,getConfig_fn,getConfigList_fn):
        super(RequestsFetcher,self).__init__(getConfig_fn,getConfigList_fn)
        self.requests_session = None
        self.retries = self.make_retries()
        ## Android patch: images get their own session (fail fast) and a per-run
        ## memo of hosts that already failed - see request() below.
        self.image_session = None
        self.image_retries = self.make_image_retries()
        self.dead_image_hosts = set()

    def set_cookiejar(self,cookiejar):
        super(RequestsFetcher,self).set_cookiejar(cookiejar)
        ## in case where cookiejar is set second
        if  self.requests_session:
            self.requests_session.cookies = self.cookiejar
        if  self.image_session:
            self.image_session.cookies = self.cookiejar

    def make_image_retries(self):
        ## Android patch: images are optional content; upstream has no
        ## image-specific policy, so a dead image host costs the full request
        ## retry ladder - measured ~24-30s of urllib3 sleeps PER image
        ## reference, and old stories are full of them (postimg.org etc).
        ## FFF only logs "Failed to load or convert image ... skipping" at the
        ## end, so the download just looks frozen. One quick retry only.
        return Retry(total=1,
                     other=0,
                     backoff_factor=1,
                     backoff_max=2,
                     allowed_methods={'GET'},
                     status_forcelist={429, 500, 502, 503, 504},
                     raise_on_status=False)

    def make_retries(self):
        try:
            total = int(self.getConfig('max_request_retries',4))
            if total < 0:
                raise ValueError('max_request_retries must be non-negative')
        except (ValueError, TypeError) as e:
            logger.error("max_request_retries setting failed: %s -- Using default value(4)"%e)
            total = 4
        ## Cloudflare 525 means the TLS handshake with the origin
        ## failed.  Retry intermittent failures seen on AO3 without
        ## broadening POST retries to other Cloudflare errors.
        ## Optional for users who'd rather fail fast.
        status_forcelist={413, 429, 500, 502, 503, 504}
        if self.getConfig('retry_http_525_failures'):
            status_forcelist.add(525)
        ## Android patch: bound how long ONE request may stall a download.
        ## urllib3 defaults are backoff_max=120s and retry_after_max=21600s (six
        ## hours), and it sleeps inside the ladder where the app cannot
        ## interrupt it. A dead image host or a rate limiter answering
        ## "Retry-After: 21600" could therefore park a whole story fetch - and,
        ## with the app's engine gate, the entire download queue - for hours.
        ## Cap the ladder and let the app-level retry decide instead.
        try:
            return Retry(total=total,
                         other=0, # rather fail SSL errors/etc quick
                         backoff_factor=2,# factor 2=4,8,16sec
                         allowed_methods={'GET','POST'},
                         status_forcelist=status_forcelist,
                         raise_on_status=False, # to match w/o retries behavior
                         backoff_max=10,
                         retry_after_max=60)
        except TypeError: # urllib3 without retry_after_max
            return Retry(total=total,
                         other=0,
                         backoff_factor=2,
                         allowed_methods={'GET','POST'},
                         status_forcelist=status_forcelist,
                         raise_on_status=False,
                         backoff_max=10)

    def make_sesssion(self):
        return requests.Session()

    def do_mounts(self,session,retries=None):
        if retries is None:
            retries = self.retries
        if self.getConfig('use_ssl_default_seclevelone',False):
            import ssl
            class TLSAdapter(HTTPAdapter):
                def init_poolmanager(self, *args, **kwargs):
                    ctx = ssl.create_default_context()
                    ctx.set_ciphers('DEFAULT@SECLEVEL=1')
                    kwargs['ssl_context'] = ctx
                    return super(TLSAdapter, self).init_poolmanager(*args, **kwargs)
            session.mount('https://', TLSAdapter(max_retries=retries))
        else:
            session.mount('https://', HTTPAdapter(max_retries=retries))
        session.mount('http://', HTTPAdapter(max_retries=retries))
        session.mount('file://', FileAdapter())
        # logger.debug("Session Proxies Before:%s"%session.proxies)
        ## try to get OS proxy settings via Calibre
        try:
            # logger.debug("Attempting to collect proxy settings through Calibre")
            from calibre import get_proxies
            try:
                proxies = get_proxies()
                if proxies:
                    logger.debug("Calibre Proxies:%s"%proxies)
                session.proxies.update(proxies)
            except Exception as e:
                logger.error("Failed during proxy collect/set %s"%e)
        except:
            pass
        if self.getConfig('http_proxy'):
            session.proxies['http'] = self.getConfig('http_proxy')
        if self.getConfig('https_proxy'):
            session.proxies['https'] = self.getConfig('https_proxy')
        if session.proxies:
            logger.debug("Session Proxies After INI:%s"%session.proxies)

    def get_requests_session(self):
        if not self.requests_session:
            self.requests_session = self.make_sesssion()
            self.do_mounts(self.requests_session)
            ## in case where cookiejar is set first
            if self.cookiejar is not None: # present but *empty* jar==False
                self.requests_session.cookies = self.cookiejar
        return self.requests_session

    def get_image_session(self):
        ## Android patch: image fetches use the short retry ladder (and a
        ## shorter timeout in request()) so one dead image host cannot hold up
        ## a whole story download.
        if not self.image_session:
            self.image_session = self.make_sesssion()
            self.do_mounts(self.image_session, retries=self.image_retries)
            if self.cookiejar is not None:
                self.image_session.cookies = self.cookiejar
        return self.image_session

    def use_verify(self):
        return not self.getConfig('use_ssl_unverified_context',False)

    def request(self,method,url,headers=None,parameters=None,json=None):
        '''Returns a FetcherResponse regardless of mechanism'''
        if method not in ('GET','POST'):
            raise NotImplementedError()
        ## Android patch: image requests (base_fetcher sets Accept: image/* for
        ## them) use the short-ladder session, a shorter timeout, and a per-run
        ## memo of hosts that already failed hard. A story full of images from a
        ## dead host used to spend ~24-30s per image inside urllib3's sleeps.
        is_image = bool(headers) and headers.get('Accept') == 'image/*'
        host = urlparse(url).netloc if is_image else ''
        if is_image and host and host in self.dead_image_hosts:
            raise requests.exceptions.ConnectionError(
                "image host %s already failed in this session"%host)
        try:
            logger.debug(make_log('RequestsFetcher',method,url,hit='REQ',bar='-'))
            ## resp = requests Response object
            timeout = 60.0
            try:
                timeout = float(self.getConfig("connect_timeout",timeout))
            except Exception as e:
                logger.error("connect_timeout setting failed: %s -- Using default value(%s)"%(e,timeout))
            if is_image:
                try:
                    timeout = float(self.getConfig("image_connect_timeout",15.0))
                except Exception:
                    timeout = 15.0
            resp = (self.get_image_session() if is_image else self.get_requests_session()).request(
                method, url,
                headers=headers,
                data=parameters,
                json=json,
                verify=self.use_verify(),
                timeout=timeout)
            logger.debug("response code:%s"%resp.status_code)
            resp.raise_for_status() # raises RequestsHTTPError if error code.
            # consider 'cached' if from file.
            fromcache = resp.url.startswith('file:')
            ## currently only saving response json if there input was json.
            ## for flaresolverr_proxy
            resp_json = None
            if json:
                try:
                    resp_json = resp.json()
                except:
                    pass
            # logger.debug(resp_json)
            return FetcherResponse(resp.content,
                                   resp.url,
                                   fromcache,
                                   resp_json)
        except RequestsHTTPError as e:
            ## not RequestsHTTPError(requests.exceptions.HTTPError) or
            ## urllib.error import HTTPError because we want code
            ## *and* content for that one trekfanfiction catch.
            raise exceptions.HTTPErrorFFF(
                url,
                e.response.status_code,
                e.args[0],# error_msg
                e.response.content # data
                )
        except Exception as e:
            ## Android patch: a host that failed hard (DNS/connect) is recorded so
            ## the rest of this run's images from it are skipped instantly instead
            ## of each paying the retry ladder. FFF treats image failures as
            ## non-fatal and marks them 'failedtoload' in the EPUB.
            if is_image and host:
                self.dead_image_hosts.add(host)
                logger.debug("image host %s marked failed for this run: %s"%(host,e))
            raise

    def __del__(self):
        if self.requests_session is not None:
            self.requests_session.close()
        if self.image_session is not None:
            self.image_session.close()
