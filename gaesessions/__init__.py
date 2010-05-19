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
COOKIE_PATH = "/"
DEFAULT_LIFETIME = datetime.timedelta(days=7)

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
    """Manages loading, reading/writing key-value pairs, and saving of a session."""
    DIRTY_BUT_DONT_PERSIST_TO_DB = 1

    def __init__(self, sid=None, lifetime=DEFAULT_LIFETIME, no_datastore=False):
        """If sid is set, then the session for that sid (if any) is loaded.
        Otherwise, sid will be loaded from the HTTP_COOKIE (if any).
        """
        self.sid = None
        self.cookie_header_data = None
        self.data = {}
        self.data = None # not yet loaded
        self.dirty = False  # has the session been changed?
        self.lifetime = lifetime
        self.no_datastore = no_datastore

        if sid:
            self.__set_sid(sid, False)
        else:
            try:
                # check the cookie to see if a session has been started
                cookie = SimpleCookie(os.environ['HTTP_COOKIE'])
                cookie_sid = cookie['sid'].value
                if cookie_sid:
                    self.__set_sid(cookie_sid, False)
            except (CookieError, KeyError):
                # no session has been started for this user
                return

    def is_active(self):
        """Returns True if this session is active (i.e., it has been assigned a
        session ID and will be or has been persisted)."""
        return self.sid is not None

    def ensure_data_loaded(self):
        """Fetch the session data if it hasn't been retrieved it yet."""
        if self.data is None and self.sid:
            self.__retrieve_data()

    def get_expiration(self):
        """Returns the timestamp at which this session will expire."""
        try:
            return int(self.sid.split('_')[0])
        except:
            return 0

    def __make_sid(self, expire_dt=None):
        """Returns a new session ID."""
        # make a random ID (random.randrange() is 10x faster but less secure?)
        if not expire_dt:
            expire_dt = datetime.datetime.now() + self.lifetime
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
        return pickle.dumps((eP,eO), 2)

    @staticmethod
    def __decode_data(pdump):
        """Returns a data dictionary after decoding it from "pickled+" form."""
        eP, eO = pickle.loads(pdump)
        for k,v in eP.iteritems():
            eO[k] = db.model_from_protobuf(v)
        return eO

    def regenerate_id(self, expiration=None):
        """Assigns the session a new session ID (data carries over).  This
        should be called whenever a user authenticates to prevent session
        fixation attacks."""
        if self.sid:
            self.ensure_data_loaded()  # ensure we have the data before we delete it
            self.__set_sid(self.__make_sid(expiration))
            self.dirty = True  # ensure the data is written to the new session

    def start(self, expiration=None):
        """Starts a new session.  expiration specifies when it will expire.  If
        expiration is not specified, then self.lifetime will used to
        determine the expiration date.

        Normally this method does not need to be called directly - a session is
        automatically started when the first value is added to the session.
        """
        self.dirty = True
        self.data = {}
        self.__set_sid(self.__make_sid(expiration), True)

    def terminate(self, clear_data=True):
        """Deletes the session and its data, and expires the user's cookie."""
        if clear_data:
            self.__clear_data()
        self.sid = None
        self.data = None
        self.dirty = False
        self.__set_cookie('', MIN_DATE) # clear their cookie

    def __set_sid(self, sid, make_cookie=True):
        """Sets the session ID, deleting the old session if one existed.  The
        session's data will remain intact (only the session ID changes)."""
        if self.sid:
            self.__clear_data()
        self.sid = sid
        self.db_key = db.Key.from_path(SessionModel.kind(), sid)

        # set the cookie if requested
        if make_cookie:
            expiration = datetime.datetime.fromtimestamp(self.get_expiration())
            self.__set_cookie(self.sid, expiration)

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
            if self.no_datastore:
                logging.info("can't find session data in memcache for sid=%s (using memcache only sessions)" % self.sid)
                self.terminate(False) # we lost it; just kill the session
                return
            session_model_instance = db.get(self.db_key)
            if session_model_instance:
                pdump = session_model_instance.pdump
            else:
                logging.error("can't find session data in the datastore for sid=%s" % self.sid)
                self.terminate(False) # we lost it; just kill the session
                return
        self.data = self.__decode_data(pdump)
        # check for expiration and terminate the session if it has expired
        if time.time() > self.get_expiration():
            self.terminate()

    def save(self, only_if_changed=True):
        """Saves the data associated with this session to memcache.  It also
        tries to persist it to the datastore (if not a no_datastore session).

        Normally this method does not need to be called directly - a session is
        automatically saved at the end of the request if any changes were made.
        """
        if not self.sid:
            return # no session is active
        if only_if_changed and not self.dirty:
            return # nothing has changed

        # do the pickling ourselves b/c we need it for the datastore anyway
        pdump = self.__encode_data(self.data)
        mc_ok = memcache.set(self.sid, pdump)

        # persist the session to the datastore
        if self.dirty is Session.DIRTY_BUT_DONT_PERSIST_TO_DB or self.no_datastore:
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
    def clear(self):
        """Removes all data from the session (but does not terminate it)."""
        if self.sid:
            self.data = {}
            self.dirty = True

    def get(self, key, default=None):
        """Retrieves a value from the session."""
        self.ensure_data_loaded()
        return self.data.get(key, default)

    def has_key(self, key):
        """Returns True if key is set."""
        self.ensure_data_loaded()
        return self.data.has_key(key)

    def pop(self, key, default=None):
        """Removes key and returns its value, or default if key is not present."""
        self.ensure_data_loaded()
        self.dirty = True
        return self.data.pop(key, default)

    def pop_quick(self, key, default=None):
        """Removes key and returns its value, or default if key is not present.
        The change will only be persisted to memcache until another change
        necessitates a write to the datastore."""
        self.ensure_data_loaded()
        if self.dirty is False:
            self.dirty = Session.DIRTY_BUT_DONT_PERSIST_TO_DB
        return self.data.pop(key, default)

    def set_quick(self, key, value):
        """Set a value named key on this session.  The change will only be
        persisted to memcache until another change necessitates a write to the
        datastore.  This will start a session if one is not already active."""
        dirty = self.dirty
        self[key] = value
        if dirty is False or dirty is Session.DIRTY_BUT_DONT_PERSIST_TO_DB:
            self.dirty = Session.DIRTY_BUT_DONT_PERSIST_TO_DB

    def __getitem__(self, key):
        """Returns the value associated with key on this session."""
        self.ensure_data_loaded()
        return self.data.__getitem__(key)

    def __setitem__(self, key, value):
        """Set a value named key on this session.  This will start a session if
        one is not already active."""
        self.ensure_data_loaded()
        if not self.sid:
            self.start()
        self.data.__setitem__(key, value)
        self.dirty = True

    def __delitem__(self, key):
        """Deletes the value associated with key on this session."""
        self.ensure_data_loaded()
        self.data.__delitem__(key)
        self.dirty = True

    def __iter__(self):
        """Returns an iterator over the keys (names) of the stored values."""
        self.ensure_data_loaded()
        return self.data.iterkeys()

    def __contains__(self, key):
        """Returns True if key is present on this session."""
        self.ensure_data_loaded()
        return self.data.__contains__(key)

    def __str__(self):
        """Returns a string representation of the session."""
        if self.sid:
            self.ensure_data_loaded()
            return "SID=%s %s" % (self.sid, self.data)
        else:
            return "uninitialized session"

class SessionMiddleware(object):
    """WSGI middleware that adds session support."""
    def __init__(self, app, lifetime=DEFAULT_LIFETIME, no_datastore=False):
        self.app = app
        self.lifetime = lifetime
        self.no_datastore = no_datastore

    def __call__(self, environ, start_response):
        # initialize a session for the current user
        global _current_session
        _current_session = Session(lifetime=self.lifetime, no_datastore=self.no_datastore)

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
