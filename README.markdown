GAE Sessions
=

NOTE: This is beta software.  If you discover a problem, please report it on the
[gae-sessions issues page](http://github.com/dound/gae-sessions/issues).


Advantages:
-
 * __Lightweight__: One short file and references to a handful of standard libs.
 * __High Availability__ is ensured by persisting all changes to the datastore.
     - If you don't need this, you can use <code>set\_quick()</code> and
       <code>pop\_quick()</code> and data will only be changed in memcache.
 * __Fast and Efficient__
     - [__Orders of magnitude
       faster__](http://wiki.github.com/dound/gae-sessions/comparison-with-alternative-libraries)
       than other session libraries for app engine.
     - Uses memcache to minimize read times.
     - Minimizes gets() and puts() by compactly storing all values in one field.
     - Automatically converts db.Model instances to protobufs for more
       efficient storage and CPU usage.
     - Frequency of writes is minimized by *only writing if there is a change*,
       and *only once per request* (when the response is being sent).
     - Session data is lazily loaded - if you don't use the session for a
       request, zero overhead is added.
 * __Simple to Use__
     - Easily installed as WSGI Middleware.
     - Session values are accessed via a dictionary interface.
     - The session automatically initializes when you first assign a value.
       Until then, no cookies are set and no writes are done.
     - Sessions expire automatically (based on a lifetime you can specify).


Limitations:
-
  * Limited to 1MB of data in a session.  (to fit in a single memcache entry)
  * No checks for User-Agent or IP consistency.
  * I'm sure you'll have lots to add to this list :).


Installation
-

After downloading and unpacking gae-sessions, copy the 'gaesessions' folder into
your app's root directory.

gae-sessions includes WSGI middleware to make it easy to integrate into your app
- you just need to add in the middleware.  If you're using App Engine's built-in
webapp framework, or any other framework that calls the
[run_wsgi_app](http://code.google.com/appengine/docs/python/tools/webapp/utilmodule.html)
function, you can use App Engine's configuration framework to install
gae-sessions.  Create a file called "appengine_config.py" in your app's root
directory, and put the following in it:

    from gaesessions import SessionMiddleware
    def webapp_add_wsgi_middleware(app):
        app = SessionMiddleware(app)
        return app

The default session lifetime is 7 days.  You may configure how long a session
lasts like this: `SessionMiddleware(app, lifetime=datetime.timedelta(hours=2))`.

If you want ALL of your changes persisted ONLY to memcache, then create the
middleware like this: `SessionMiddleware(app, no_datastore=True)`.  This will
result in faster writes but your session data might be lost at any time!

You will also want to create a cronjob to periodically remove expired sessions
from the datastore.  You can find the [example
cronjob](http://github.com/dound/gae-sessions/tree/master/demo/cron.yaml) and
the [cleanup handler](http://github.com/dound/gae-sessions/tree/master/demo/cleanup_sessions.py)
it calls in the [demo].


Example Usage
-

There is a complete demo application in the 'demo' folder - just launch it with
the development server (or upload it to GAE) and check it out.  This demo uses
OpenID via [RPX](http://www.rpxnow.com) for user authentication.  There's
another demo in the 'demo-with-google-logins' folder which uses Google Accounts
for authentication Here's a few lines of example code too:

    from gaesessions import get_current_session
    session = get_current_session()
    if session.is_active():
        c = session.get('counter', 0)
        session['counter'] = c + 1
        session['blah'] = 325
        del session.blah  # remove 'blah' from the session
        # model instances and other complex objects can be stored too

        # If you don't care if a particular change to the session is persisted
        # to the datastore, then you can use the "quick" methods.  They will
        # only cause the session to be stored to memcache.  Of course if you mix
        # regular and quick methods, then everything will be persisted to the
        # datastore (and memcache) at the end of the request like usual.
        session.set_quick('x', 9)
        x = session.get('x')
        x = session.pop_quick('x')

    # ...
    # when the user logs in, it is recommended that you rotate the session ID (security)
    session.regenerate_id()


_Author_: [David Underhill](http://www.dound.com)  
_Updated_: 2010-May-17 (v0.9-beta)  
_License_: Apache License Version 2.0

For more information, please visit the [gae-sessions webpage](http://github.com/dound/gae-sessions/).
