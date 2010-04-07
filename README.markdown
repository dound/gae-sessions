GAE Sessions
=

NOTE: This software is NOT ready for use.  I'm very much in the process of
completing the initial implementation but it should be ready soon :).


Advantages:
-
 * __Lightweight__: One short file and references to a handful of standard libs.
 * __High Availability__ is ensured by persisting all changes to the datastore.
 * __Fast and Efficient__
     - Uses memcache to minimize read times.
     - Minimizes gets() and puts() by compactly storing all values in one field.
     - Automatically converts db.Model instances to protobufs for more
       efficient storage and CPU usage.
     - Frequency of writes is minimized by only writing if there is a change,
       and only once per request (when the response is being sent).
 * __Simple to Use__
     - Easily installed as WSGI Middleware.
     - You may access session values as attributes or via a dictionary interface.
     - The session automatically initializes when you first assign a value.
       Until then, no cookies are set and no writes are done.


Limitations:
-
  * Limited to 1MB of data in a session.  (to fit in a single memcache entry)
  * No checks for User-Agent or IP consistency (yet).
  * I'm sure you'll have lots to add to this list :).


Installation
-

After downloading and unpacking gae-sessions, copy the 'gaesessions' folder into
your app's root directory.

gae-sessions includes WSGI middleware to make it easy to integrate into your app
- you just need to add in the middleware.  If you're using App Engine's built in
webapp framework, or any other framework that calls the
[run_wsgi_app](http://code.google.com/appengine/docs/python/tools/webapp/utilmodule.html)
function, you can use App Engine's configuration framework to install
gae-sessions.  Create a file called "appengine_config.py" in your app's root
directory, and put the following in it:

    from gaesessions import SessionMiddleware
    def webapp_add_wsgi_middleware(app):
        app = SessionMiddleware(app)
        return app


Example Usage
-
    from gaesessions import _current_session as session
    session.blah = 325
    session['another-var'] = some_model_instance
    del session.blah  # remove 'blah' from the session


_Author_: [David Underhill](http://www.dound.com)

_Updated_: 2010-Apr-07
