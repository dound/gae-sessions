"""A fast, lightweight, and secure session WSGI middleware for use with GAE."""
from Cookie import CookieError, SimpleCookie
import datetime
import hashlib
import logging
import pickle
import os
import time

from google.appengine.api import memcache
from google.appengine.ext import db

# Configurable cookie options
COOKIE_PATH     = "/"
COOKIE_LIFETIME = datetime.timedelta(days=7)

# a date in the past used to expire cookies on the client's side
MIN_DATE = datetime.datetime.fromtimestamp(0)

_current_session = None
def get_current_session():
    return _current_session

class SessionModel(db.Model):
    """Contains session data.  key_name is the session ID and pdump contains a
    pickled dictionary which maps session variables to their values."""
    pdump = db.BlobProperty()

class Session(object):
    DIRTY_BUT_DONT_PERSIST_TO_DB = 1

    """Manages loading, user reading/writing, and saving of a session."""
    def __init__(self):
        self.sid = None
        self.cookie_header_data = None
        self.data = {}
        self.dirty = False  # has the session been changed?

        try:
            # check the cookie to see if a session has been started
            cookie = SimpleCookie(os.environ['HTTP_COOKIE'])
            self.__set_sid(cookie['sid'].value, False)
        except (CookieError, KeyError):
            # no session has been started for this user
            return

        # eagerly fetch the data for the active session (we'll probably need it)
        self.__retrieve_data()

    def is_active(self):
        return self.sid is not None

    @staticmethod
    def __make_sid():
        """Returns a new session ID."""
        # make a random ID (random.randrange() is 10x faster but less secure?)
        expire_dt = datetime.datetime.now() + COOKIE_LIFETIME
        expire_ts = int(time.mktime((expire_dt).timetuple()))
        return str(expire_ts) + '_' + hashlib.md5(os.urandom(16)).hexdigest()

    @staticmethod
    def __encode_data(d):
        """Returns a "pickled+" encoding of d.  d values of type db.Model are
        protobuf encoded before pickling to minimize CPU usage & data size."""
        # separate protobufs so we'll know how to decode (they are just strings)
        eP = {} # for models encoded as protobufs
        eO = {} # for everything else
        for k,v in d.iteritems():
            if isinstance(v, db.Model):
                eP[k] = db.model_to_protobuf(v)
            else:
                eO[k] = v
        return pickle.dumps((eP,eO))

    @staticmethod
    def __decode_data(pdump):
        """Returns a data dictionary after decoding it from "pickled+" form."""
        eP, eO = pickle.loads(pdump)
        for k,v in eP.iteritems():
            eO[k] = db.model_from_protobuf(v)
        return eO

    def user_is_now_logged_in(self):
        """Assigns the session a new session ID (data carries over).  This helps
        nullify session fixation attacks."""
        self.__set_sid(self.__make_sid())
        self.dirty = True

    def start(self, expiration=None):
        """Starts a new session.  expiration specifies when it will expire.  If
        expiration is not specified, then COOKIE_LIFETIME will used to determine
        the expiration date."""
        self.dirty = True
        self.data = {}
        self.__set_sid(self.__make_sid(), True, expiration)

    def terminate(self, clear_data=True):
        """Ends the session and cleans it up."""
        if clear_data:
            self.__clear_data()
        self.sid = None
        self.data.clear()
        self.dirty = False
        self.__set_cookie('', MIN_DATE) # clear their cookie

    def __set_sid(self, sid, make_cookie=True, expiration=None):
        """Sets the session ID, deleting the old session if one existed.  The
        session's data will remain intact (only the session ID changes)."""
        if self.sid:
            self.__clear_data()
        self.sid = sid
        self.db_key = db.Key.from_path(SessionModel.kind(), sid)

        # set the cookie if requested
        if not make_cookie: return
        if expiration:
            self.data['expiration'] = expiration
        elif not self.data.has_key('expiration'):
            self.data['expiration'] = datetime.datetime.now() + COOKIE_LIFETIME
        self.__set_cookie(self.sid, self.data['expiration'])

    def __set_cookie(self, sid, exp_time):
        cookie = SimpleCookie()
        cookie["sid"] = sid
        cookie["sid"]["path"] = COOKIE_PATH
        cookie["sid"]["expires"] = exp_time.strftime("%a, %d-%b-%Y %H:%M:%S PST")
        self.cookie_header_data = cookie.output(header='')

    def __clear_data(self):
        """Deletes this session from memcache and the datastore."""
        if self.sid:
            memcache.delete(self.sid) # not really needed; it'll go away on its own
            try:
                db.delete(self.db_key)
            except:
                logging.warning("unable to cleanup session from the datastore for sid=%s" % self.sid)

    def __retrieve_data(self):
        """Sets the data associated with this session after retrieving it from
        memcache or the datastore.  Assumes self.sid is set.  Checks for session
        expiration after getting the data."""
        pdump = memcache.get(self.sid)
        if pdump is None:
            # memcache lost it, go to the datastore
            session_model_instance = db.get(self.db_key)
            if session_model_instance:
                pdump = session_model_instance.pdump
            else:
                logging.error("can't find session data in the datastore for sid=%s" % self.sid)
                self.terminate(False) # we lost it; just kill the session
                return
        self.data = self.__decode_data(pdump)
        # check for expiration and terminate the session if it has expired
        if datetime.datetime.now() > self.data.get('expiration', MIN_DATE):
            self.terminate()

    def save(self, only_if_changed=True):
        """Saves the data associated with this session to memcache.  It also
        tries to persist it to the datastore."""
        if not self.sid:
            return # no session is active
        if only_if_changed and not self.dirty:
            return # nothing has changed

        # do the pickling ourselves b/c we need it for the datastore anyway
        pdump = self.__encode_data(self.data)
        mc_ok = memcache.set(self.sid, pdump)

        # persist the session to the datastore
        if self.dirty is Session.DIRTY_BUT_DONT_PERSIST_TO_DB:
            return
        try:
            SessionModel(key_name=self.sid, pdump=pdump).put()
        except db.TransactionFailedError:
            logging.warning("unable to persist session to datastore for sid=%s" % self.sid)
        except db.CapabilityDisabledError:
            pass # nothing we can do here

        # retry the memcache set after the db op if the memcache set failed
        if not mc_ok:
            memcache.set(self.sid, pdump)

    def get_cookie_out(self):
        """Returns the cookie data to set (if any), otherwise None.  This also
        clears the cookie data (it only needs to be set once)."""
        if self.cookie_header_data:
            ret = self.cookie_header_data
            self.cookie_header_data = None
            return ret
        else:
            return None

    # Users may interact with the session through a dictionary-like interface.
    def get(self, key, default=None):
        return self.data.get(key, default)

    def has_key(self, key):
        return self.data.has_key(key)

    def pop(self, key, default=None):
        self.dirty = True
        return self.data.pop(key, default)

    def pop_quick(self, key, default=None):
        if self.dirty is False:
            self.dirty = Session.DIRTY_BUT_DONT_PERSIST_TO_DB
        return self.data.pop(key, default)

    def set_quick(self, key, value):
        """Set a value named key on this session like normal, except don't
        bother persisting the value all the way to the datastore (until another
        action necessitates the write)."""
        dirty = self.dirty
        self[key] = value
        if dirty is False:
            self.dirty = Session.DIRTY_BUT_DONT_PERSIST_TO_DB

    def __getitem__(self, key):
        return self.data.__getitem__(key)

    def __setitem__(self, key, value):
        """Set a value named key on this session.  This will start this session
        if it had not already been started."""
        if not self.sid:
            self.start()
        self.data.__setitem__(key, value)
        self.dirty = True

    def __delitem__(self, key):
        if key == 'expiration':
            raise KeyError("expiration may not be removed")
        else:
            self.data.__delitem__(key)
            self.dirty = True

    def __iter__(self):
        """Returns an iterator over the keys (names) of the stored values."""
        return self.data.iterkeys()

    def __contains__(self, key):
        return self.data.__contains__(key)

    def __str__(self):
        """Returns a string representation of the session."""
        if self.sid:
            return "SID=%s %s" % (self.sid, self.data)
        else:
            return "uninitialized session"

class SessionMiddleware(object):
    """WSGI middleware that adds session support."""
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        # initialize a session for the current user
        global _current_session
        _current_session = Session()

        # create a hook for us to insert a cookie into the response headers
        def my_start_response(status, headers, exc_info=None):
            cookie_out = _current_session.get_cookie_out()
            if cookie_out:
                headers.append(('Set-Cookie', cookie_out))
            _current_session.save() # store the session if it was changed
            return start_response(status, headers, exc_info)

        # let the app do its thing
        return self.app(environ, my_start_response)

def delete_expired_sessions():
    """Deletes expired sessions from the datastore.
    If there are more than 1000 expired sessions, only 1000 will be removed.
    Returns True if all expired sessions have been removed.
    """
    now_str = unicode(int(time.time()))
    q = db.Query(SessionModel, keys_only=True)
    key = db.Key.from_path('SessionModel', now_str + u'\ufffd')
    q.filter('__key__ < ', key)
    results = q.fetch(1000)
    db.delete(results)
    logging.info('gae-sessions: deleted %d expired sessions from the datastore' % len(results))
    return len(results)<1000
