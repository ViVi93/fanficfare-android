# Copyright 2026 FanFicFare team
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

## not compatibly with py2, SortKey not available.
DO_PROFILING = False
if DO_PROFILING:
    from io import StringIO
    import cProfile, pstats
    from pstats import SortKey
    def do_cprofile(func):
        def profiled_func(*args, **kwargs):
            profile = cProfile.Profile()
            try:
                profile.enable()
                result = func(*args, **kwargs)
                profile.disable()
                return result
            finally:
                # profile.print_stats()
                s = StringIO()
                sortby = SortKey.CUMULATIVE
                ps = pstats.Stats(profile, stream=s).sort_stats(sortby)
                ps.print_stats(20)
                print(s.getvalue())
        return profiled_func
else:
    ## no-nothing for py2
    def do_cprofile(func):
        def profiled_func(*args, **kwargs):
            return func(*args, **kwargs)
        return profiled_func
