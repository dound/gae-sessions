from base64 import b64decode
import logging
import pickle

from google.appengine.ext import db
from nose.tools import assert_equal, assert_not_equal, assert_raises

from main import make_entity
from gaesessions import SessionMiddleware
from SessionTester import SessionTester

# Tests to do (each on a variety of configurations):
#   0) Correct session usage
#   1) Session expiration
#   2) Invalid method usage
#   3) Memcache loss
#   4) Bad cookie data (e.g., sig invalid due to data changed by user)

logger = logging.getLogger('TESTS ')
logger.setLevel(logging.DEBUG)

def test_middleware():
    """Tests that the middleware requires cookie_key when it should."""
    logging.debug("cookie_key is required if there is a cookie_only_threshold")
    assert_raises(ValueError, SessionMiddleware, None, cookie_only_threshold=10)
    SessionMiddleware(None, cookie_only_threshold=10, cookie_key='blah')
    SessionMiddleware(None, cookie_only_threshold=0)

def test_sessions():
    """Run a variety of tests on various session configurations (includes
    whether or not to use the datastore and the cookie only threshold).
    """
    CHECKS = (check_correct_usage,)
    # not yet written: check_expiration, check_invalid_usage, check_memcache_loss, check_bad_cookie)
    for no_datastore in (False, True):
        if no_datastore:
            test_db = 'without'
        else:
            test_db = 'with'
        for cot in (0, 10*1024, 2**30):
            if cot == 0:
                test_cookie = 'no data stored in cookies'
            elif cot == 2**30:
                test_cookie = 'data only stored in cookies'
            else:
                test_cookie = 'store data in cookies when its encoded size<=%dB' % cot
            for check in CHECKS:
                logger.debug('\n\n' + '*'*50)
                logger.debug('Running %s %s datastore and %s' % (check.__name__, test_db, test_cookie))
                yield check, no_datastore, cot

def minitest_divider(test):
    logger.debug('\n\n' + '-'*50)
    logger.debug(test)

def check_correct_usage(no_datastore, cookie_only_threshold):
    st = SessionTester(no_datastore=no_datastore, cookie_only_threshold=cookie_only_threshold)
    st.verify_active_sessions_in_db(0)

    minitest_divider('try doing nothing (no session should be started)')
    st.noop()
    st.verify_active_sessions_in_db(0)

    # helper function which checks how many sessions we should have in the db
    # given the current test's configuration
    def expected_num_sessions_in_db_if_db_used(num, num_above_cookie_thresh=0):
        if not no_datastore:
            if cookie_only_threshold == 0:
                st.verify_active_sessions_in_db(num)
            else:
                st.verify_active_sessions_in_db(num_above_cookie_thresh)
        else:
            st.verify_active_sessions_in_db(0)  # cookie or memcache only

    minitest_divider('start a session with a single write')
    st.start_request()
    str(st)
    assert st.get_expiration()==0, "no session yet => no expiration yet"
    assert st.is_active() is False
    st['x'] = 7
    assert st.is_active() is True
    st.finish_request_and_check()
    expected_num_sessions_in_db_if_db_used(1)

    minitest_divider('start another session')
    st2 = SessionTester(st=st, no_datastore=no_datastore, cookie_only_threshold=cookie_only_threshold)
    st2.start_request()
    assert not st2.is_active()
    assert st2.get('x') is None, "shouldn't get other session's data"
    assert not st2.is_active(), "still shouldn't be active - nothing set yet"
    st2['x'] = 'st2x'
    assert st2.is_active()
    st2.finish_request_and_check()
    expected_num_sessions_in_db_if_db_used(2)

    minitest_divider('each session should get a unique sid')
    assert st2.ss.sid != st.ss.sid

    minitest_divider('we should still have the values we set earlier')
    st.start_request()
    str(st)
    assert_equal(st['x'], 7)
    st.finish_request_and_check()
    st2.start_request()
    assert_equal(st2['x'], 'st2x')
    st2.finish_request_and_check()

    minitest_divider("check get session by sid, save(True), and terminate()")
    if cookie_only_threshold == 0:
        data1 = st.ss.data
        data2 = st2.ss.data
    else:
        # data is being stored in cookie-only form => won't be in the db
        data1 = data2 = {}
    resp = st.get_url('/get_by_sid?sid=%s' % st.ss.sid)
    assert_equal(pickle.loads(b64decode(resp.body)), data1)
    resp = st2.get_url('/get_by_sid?sid=%s' % st2.ss.sid)
    assert_equal(pickle.loads(b64decode(resp.body)), data2)
    expected_num_sessions_in_db_if_db_used(2)
    st.start_request()
    st['y'] = 9    # make the session dirty
    st.save(True)  # force it to persist to the db even though it normally wouldn't
    st.finish_request_and_check()

    # now the data should be in the db
    resp = st.get_url('/get_by_sid?sid=%s' % st.ss.sid)
    assert_equal(pickle.loads(b64decode(resp.body)), st.ss.data)
    expected_num_sessions_in_db_if_db_used(2, 1)
    st.start_request()
    st.terminate()  # remove it from the db
    st.finish_request_and_check()
    expected_num_sessions_in_db_if_db_used(1)

    minitest_divider("should be able to terminate() and then start a new session all in one request")
    st.start_request()
    st['y'] = 'yy'
    assert_equal(st.get('y'), 'yy')
    st.terminate()
    assert_raises(KeyError, st.__getitem__, 'y')
    st['x'] = 7
    st.finish_request_and_check()
    expected_num_sessions_in_db_if_db_used(2)

    minitest_divider("regenerating SID test")
    initial_sid = st.ss.sid
    st.start_request()
    initial_expir = st.get_expiration()
    st.regenerate_id()
    assert_equal(st['x'], 7, "data should not be affected")
    st.finish_request_and_check()
    assert_not_equal(initial_sid, st.ss.sid, "regenerated sid should be different")
    assert_equal(initial_expir, st._get_expiration(), "expiration should not change")
    st.start_request()
    assert_equal(st['x'], 7, "data should not be affected")
    st.finish_request_and_check()
    expected_num_sessions_in_db_if_db_used(2)

    minitest_divider("check basic dictionary operations")
    st.start_request()
    st['s'] = 'aaa'
    st['i'] = 99
    st['f'] = 4.37
    assert_equal(st.pop('s'), 'aaa')
    assert_equal(st.pop('s'), None)
    assert_equal(st.pop('s', 'nil'), 'nil')
    assert st.has_key('i')
    assert not st.has_key('s')
    assert_equal(st.get('i'), 99)
    assert_equal(st.get('ii'), None)
    assert_equal(st.get('iii', 3), 3)
    assert_equal(st.get('f'), st['f'])
    del st['f']
    assert_raises(KeyError, st.__getitem__, 'f')
    assert 'f' not in st
    assert 'i' in st
    assert_equal(st.get('x'), 7)
    st.clear()
    assert 'i' not in st
    assert 'x' not in st
    st.finish_request_and_check()

    minitest_divider("add complex data (models and objects) to the session")
    st.start_request()
    st['model'] = make_entity(0)
    st['dict'] = dict(a='alpha', c='charlie', e='echo')
    st['list'] = ['b', 'd', 'f']
    st['set'] = set([2, 3, 5, 7, 11, 13, 17, 19])
    st['tuple'] = (7, 7, 1985)
    st.finish_request_and_check()

def main():
    """Run nose tests and generate a coverage report."""
    import coverage
    import nose
    import os
    from shutil import rmtree
    rmtree('./covhtml', ignore_errors=True)
    try:
        os.remove('./.coverage')
    except Exception,e:
        pass

    # run nose in its own process because the .coverage file isn't written
    # until the process terminates and we need to read it
    nose.run()

if __name__ == '__main__': main()
