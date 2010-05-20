import logging
from SessionTester import SessionTester

logger = logging.getLogger('TESTS ')
logger.setLevel(logging.DEBUG)

def test_sessions():
    for no_datastore in (False, True):
        for cot in (0, 10*1024, 2**30):
            if no_datastore:
                test_db = 'without'
            else:
                test_db = 'with'
            if cot == 0:
                test_cookie = 'no data stored in cookies'
            elif cot == 2**30:
                test_cookie = 'data only stored in cookies'
            else:
                test_cookie = 'store data in cookies when its encoded size<=%dB' % cot
            logger.info('*'*50)
            logger.info('Testing %s datastore and %s' % (test_db, test_cookie))
            yield check_sessions, no_datastore, cot

def check_sessions(no_datastore, cookie_only_threshold):
    st = SessionTester(no_datastore=no_datastore, cookie_only_threshold=cookie_only_threshold)

    st.start_request()
    st['x'] = 7
    st.finish_request_and_check()

    # ... and do more requests ...
