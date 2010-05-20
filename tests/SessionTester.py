from base64 import b64decode, b64encode
import logging
import pickle
from webtest import TestApp
from main import ANY_SID, DEFAULT_COOKIE_KEY, make_application, SessionState

def session_method(f):
    """Decorator which returns a function which calls the original function,
    records its output, and adds the function+args to the list of calls to be
    duplicated on the test web server too.
    """
    def stub(*args, **kwargs):
        myself = args[0]
        rpc = (f.__name__, args[1:], kwargs)
        myself.rpcs.append(rpc)
        myself.outputs.append(f(*args, **kwargs))
        logging.info('rpc enqueud: %s(%s, %s)' % (f.__name__,args[1:],kwargs))
    return stub

class SessionTester(object):
    """Manages testing a session by executing a mocked version of a Session and
    the "real thing" (being run by main.py) and then verifying that they output
    the same information and end up in the same state.
    """
    def __init__(self, **kwargs):
        if not kwargs.has_key('cookie_key'):
            kwargs['cookie_key'] = DEFAULT_COOKIE_KEY
        self.app = TestApp(make_application(**kwargs))
        self.ss = SessionState(None, {}, False, False) # current state of the session
        self.rpcs = None          # calls on Session object waiting to be made remotely
        self.outputs = None       # outputs of local procedure calls
        self.api_statuses = None  # whether various APIs are up or down
        self.app_args = kwargs

        # extra checks; if None, then don't do them
        self.check_expir = None
        self.check_sid_is_not = None

    def start_request(self, mc_can_read=True, mc_can_write=True, db_can_read=True, db_can_write=True):
        """Initiates a new batch of session operations which will all be
        performed within one request and then checked when
        finish_request_and_check() is called.
        """
        if self.rpcs:
            raise RuntimeError("tried to start a request before finishing the previous request")

        self.api_statuses = dict(mc_can_rd=mc_can_read, mc_can_wr=mc_can_write,
                                 db_can_rd=db_can_read, db_can_wr=db_can_read)
        self.rpcs = []
        self.outputs = []

    def finish_request_and_check(self):
        """Executes the set of RPCs requested since start_request() was called
        and checks to see if the response is successful and matches the
        expected Session state.  Outputs of each RPC are also compared with the
        expected outputs.
        """
        if self.rpcs is None:
            raise RuntimeError("tried to finish a request before starting a request")
        resp = self.app.post('/', dict(rpcs=b64encode(pickle.dumps(self.rpcs)), api_statuses=b64encode(pickle.dumps(self.api_statuses))))
        assert resp.status[:3] == '200', 'did not get code 200 back: %s' % resp
        remote_outputs, remote_ss = pickle.loads(b64decode(resp.body))
        assert self.ss == remote_ss, 'mismatch b/w local and remote states:\n\tlocal: %s\n\tremote: %s' % (self.ss, remote_ss)
        assert len(remote_outputs)==len(self.outputs), 'internal test error: number outputs should be the same'
        assert len(remote_outputs)==len(self.rpcs), 'internal test error: number outputs should be the same as the number of RPCs'
        for i in xrange(len(remote_outputs)):
            l, r = self.outputs[i], remote_outputs[i]
            assert l==r, 'output for rpc #%d (%s) does not match:\n\tlocal: %s\n\tremote: %s' % (i, self.rpcs[i], l, r)

        # extra checks we sometimes need to do
        if self.check_expir:
            expir_remote = int(remote_ss.sid.split('_')[0])
            assert self.check_expir==expir_remote, "remote expiration %s does match the expected expiration %s" % (expir_remote, self.check_expir)
            self.check_expir = None
        if self.check_sid_is_not:
            assert self.check_sid_is_not != remote_ss.sid, 'remote sid should not be %s' % remote_ss.sid

        # if we were okay with whatever sid the remote host assigned, adopt it now
        if self.ss.sid == ANY_SID:
            self.ss.sid = remote_ss.sid

        self.api_statuses = self.outputs = self.rpcs = None



    # **************************************************************************
    # helpers for our mocks of Session methods
    def __check_expir(self, expiration):
        if expiration is not None:
            self.check_expir = int(time.mktime((expire_dt).timetuple()))

    def __set_in_mc_db_to_true_if_ok(self):
        self.ss.in_db = not self.app_args['no_datastore'] and self.api_statuses['db_can_wr'] and self.api_statuses['db_can_rd']
        self.ss.in_mc = self.api_statuses['mc_can_wr'] and self.api_statuses['mc_can_rd']

    def __start(self, expiration=None):
        self.ss.data = {}
        self.ss.sid = ANY_SID
        if self.app_args['cookie_only_threshold'] < 0:
            self.__set_in_mc_db_to_true_if_ok()
        else:
            self.ss.in_db = self.ss.in_mc = False  # cookie-only
        self.__check_expir(expiration)

    # mocks for all the 'public' methods on Session
    @session_method
    def make_cookie_headers(self):
        raise NotImplementedError("we don't test this directly")

    @session_method
    def is_active(self):
        return self.ss.sid is not None

    @session_method
    def ensure_data_loaded(self):
        pass  # our data is always loaded

    @session_method
    def get_expiration(self):
        try:
            return int(self.ss.sid.split('_')[0])
        except:
            return 0

    @session_method
    def regenerate_id(self, expiration=None):
        if self.ss.sid:
            self.check_sid_is_not = self.ss.sid
            self.check_expir = int(self.ss.sid.split('_')[0])
            self.ss.sid = ANY_SID
        self.__check_expir(expiration)

    @session_method
    def start(self, expiration=None):
        self.__start(expiration)

    @session_method
    def terminate(self, clear_data=True):
        self.ss.sid = None
        self.ss.data = None
        self.ss.in_db = False
        self.ss.in_mc = False

    @session_method
    def save(self, persist_even_if_using_cookie=False):
        if not persist_even_if_using_cookie:
            pass  # save happens at the end anyway; doing it in the middle is a no-op assuming no exceptions are raised
        elif self.ss.sid:
            self.__set_in_mc_db_to_true_if_ok()

    @session_method
    def clear(self):
        self.ss.data.clear()

    @session_method
    def get(self, key, default=None):
        return self.ss.data.get(key, default)

    @session_method
    def has_key(self, key):
        return self.ss.data.has_key(key)

    @session_method
    def pop(self, key, default=None):
        return self.ss.data.pop(key, default)

    @session_method
    def pop_quick(self, key, default=None):
        # TODO: this doesn't verify that it doesn't go to db if it shouldn't
        return self.ss.data.pop(key, default)

    @session_method
    def set_quick(self, key, value):
        # TODO: this doesn't verify that it doesn't go to db if it shouldn't
        self.ss.data.__setitem__(key, value)

    @session_method
    def __getitem__(self, key):
        return self.ss.data.__getitem__(key)

    @session_method
    def __setitem__(self, key, value):
        if not self.ss.sid:
            self.__start()
        self.ss.data.__setitem__(key, value)

    @session_method
    def __delitem__(self, key):
        self.ss.data.__delitem__(key)

    @session_method
    def __iter__(self):
        return self.ss.data.iterkeys()

    @session_method
    def __contains__(self, key):
        return self.ss.data.__contains__(key)

    @session_method
    def __str__(self):
        if self.ss.sid:
            return "SID=%s %s" % (self.ss.sid, self.ss.data)
        else:
            return "uninitialized session"
