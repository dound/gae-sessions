from base64 import b64decode, b64encode
import logging
import pickle

from google.appengine.api import memcache
from google.appengine.ext import db, webapp
from google.appengine.ext.webapp.util import run_wsgi_app

from gaesessions import get_current_session, Session, SessionMiddleware, SessionModel, delete_expired_sessions

logger = logging.getLogger('SERVER')
logger.setLevel(logging.DEBUG)

class TestModel(db.Model):
    s = db.StringProperty()
    i = db.IntegerProperty()
    f = db.FloatProperty()

# note: these entities are about 900B when stored as a protobuf
def get_test_entity(i):
    """Create the entity just like it would be in the datastore (so our tests don't actually go to the datastore)."""
    return TestModel(key=db.Key.from_path('TestModel', str(i)), s="a"*500, i=i, f=i*10.0)

class SessionState(object):
    def __init__(self, sid, data, dirty, in_mc, in_db):
        self.sid = sid
        if not data:
            self.data = {}  # treat None and empty dictionary the same
        else:
            self.data = data
        self.in_mc = in_mc
        self.in_db = in_db  # whether it is in the db AND accessible (i.e., db is up)

    def __cmp__(self, s):
        c = cmp(self.sid, s.sid)
        if c != 0: return c
        c = cmp(self.data, s.data)
        if c != 0: return c
        c = cmp(self.in_mc, s.in_mc)
        if c != 0: return c
        return cmp(self.in_db, s.in_db)

    def __str__(self):
        return 'sid=%s in_mc=%s in_db=%s data=%s' % (self.sid, self.in_mc, self.in_db, self.data)

def make_ss(session):
    sid = session.sid
    if not sid:
        in_mc = in_db = False
    else:
        pdump = memcache.get(sid)
        if pdump and session.data==Session._Session__decode_data(pdump):
            in_mc = True
        else:
            in_mc = False

        try:
            sm = SessionModel.get_by_key_name(sid)
            if sm and session.data==Session._Session__decode_data(sm.pdump):
                in_db = True
            else:
                in_db = False
                if sm:
                    logger.info('in db, but stale: current=%s db=%s' % (session.data, Session._Session__decode_data(sm.pdump)))
                else:
                    logger.info('session not in db at all')
        except Exception, e:
            logging.warn('db failed: %s => %s' % (type(e), e))
            in_db = False  # db failure (perhaps it is down)
    return SessionState(sid, session.data, session.dirty, in_mc, in_db)

class CleanupExpiredSessions(webapp.RequestHandler):
    def get(self):
        num_before = SessionModel.all().count()
        delete_expired_sessions()
        num_after = SessionModel.all().count()
        self.response.out.write('%d,%d' % (num_before, num_after))

class DeleteAll(webapp.RequestHandler):
    def get(self):
        memcache.flush_all()
        db.delete(SessionModel.all(keys_only=True).fetch(1000))

class FlushMemcache(webapp.RequestHandler):
    def get(self):
        memcache.flush_all()
        self.response.out.write('ok')

class RPCHandler(webapp.RequestHandler):
    def get(self):
        self.response.out.write('ok')

    def post(self):
        try:
            api_statuses = pickle.loads(b64decode(self.request.get('api_statuses')))
        except Exception, e:
            logger.error('failed to unpickle api_statuses: %s' % e)
            return self.error(500)
        logger.info("api statuses: %s" % api_statuses)

        try:
            rpcs = pickle.loads(b64decode(self.request.get('rpcs')))
        except Exception, e:
            logger.error('failed to unpickle RPCs: %s' % e)
            return self.error(500)
        logger.info("rpcs: %s" % rpcs)

        # TODO: apply the API statuses; remember to unapply before returning too

        session = get_current_session()
        outputs = []
        for fname,args,kwargs in rpcs:
            try:
                f = getattr(session, fname)
                try:
                    output = f(*args, **kwargs)
                except Exception, e:
                    output = '%s-%s' % (type(e), e)
                outputs.append(output)
                logger.info('%s(%s, %s) => %s' % (f, args, kwargs, output))
            except Exception, e:
                logger.error('failed to execute RPC: %s(session, *%s, **%s) - %s' % (f,args,kwargs,e))
                return self.error(500)
        self.request.environ['test_outputs'] = outputs

class GetSession(webapp.RequestHandler):
    def get(self):
        s = Session(sid=self.request.get('sid'), cookie_key='dontcare')
        s.ensure_data_loaded()
        self.response.out.write(b64encode(pickle.dumps(s.data)))

class TestingMiddleware(object):
    """Dumps session state and environ['test_outputs'] into the response if the
    'test_outputs' key is set.  This middleware should wrap the sessions
    middleware so that the dumped session state is the final state (i.e., after
    the middleware has finished and no more changes are being made to it).
    """
    def __init__(self, app):
        self.app = app
    def __call__(self, environ, start_response):
        # On app engine and the dev server, os.environ also contains HTTP_COOKIE
        # and gae-sessions relies on this so we copy it over for this test.
        # (running with nose-gae and webtest this doesn't happen)
        import os
        os.environ['HTTP_COOKIE'] = environ.get('HTTP_COOKIE', '')

        def my_start_response(status, headers, exc_info=None):
            ret = start_response(status, headers, exc_info)
            if environ.has_key('test_outputs'):
                outputs = environ['test_outputs']
                resp = (outputs, make_ss(get_current_session()))
                # add to the response ...
                content = b64encode(pickle.dumps(resp))
                ret(content)
                headers.append(('Content-Length', len(content)))
            return ret

        return self.app(environ, my_start_response)

def make_application(**kwargs):
    app = webapp.WSGIApplication([('/',               RPCHandler),
                                  ('/flush_memcache', FlushMemcache),
                                  ('/cleanup',        CleanupExpiredSessions),
                                  ('/get_by_sid',     GetSession),
                                  ('/delete_all',     DeleteAll),
                                  ], debug=True)
    return TestingMiddleware(SessionMiddleware(app, **kwargs))

DEFAULT_COOKIE_KEY = '\xedd\xa7\x83\xf2\xd3\xdc%!U8s\x10\x19\xae\x8f\xce\x82\x94\x92\x9c\xf4`\xb4\xca\xcb\x91.\x0eIA~\xc5\xc0\xd5\xaeeIJ\xaf\x88}=\xc8\x96\xed.\xcb\xe7C\x81\xa3\r\xca\xeb\x1c\xfc\xa4V\xc5l\xf7+\xec'
def main(): run_wsgi_app(make_application(cookie_key=DEFAULT_COOKIE_KEY))
if __name__ == '__main__': main()
