from SessionTester import SessionTester

def test_simple():
    st = SessionTester(cookie_only_threshold=10*1024)

    st.start_request()
    st['x'] = 7
    st.finish_request_and_check()

    # ... and do more requests ...
