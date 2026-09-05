# -*- coding: utf-8 -*-

# Copyright 2026 FanFicFare team
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

## ensure_X() methods moved from six.py

def ensure_binary(s, encoding='utf-8', errors='strict'):
    """Coerce **s** to bytes.
      - `str` -> encoded to `bytes`
      - `bytes` -> `bytes`
    """
    if isinstance(s, bytes):
        return s
    if isinstance(s, str):
        return s.encode(encoding, errors)
    raise TypeError("not expecting type '%s'" % type(s))


def ensure_str(s, encoding='utf-8', errors='strict'):
    """Coerce *s* to `str`.
      - `str` -> `str`
      - `bytes` -> decoded to `str`
    """
    # Optimization: Fast return for the common case.
    if type(s) is str:
        return s
    if isinstance(s, bytes):
        return s.decode(encoding, errors)
    elif not isinstance(s, (str, bytes)):
        raise TypeError("not expecting type '%s'" % type(s))
    return s


def ensure_text(s, encoding='utf-8', errors='strict'):
    """Coerce *s* to str.
      - `str` -> `str`
      - `bytes` -> decoded to `str`
    """
    if isinstance(s, bytes):
        return s.decode(encoding, errors)
    elif isinstance(s, str):
        return s
    else:
        raise TypeError("not expecting type '%s'" % type(s))
