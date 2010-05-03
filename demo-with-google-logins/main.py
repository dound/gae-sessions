import os

from google.appengine.api import users
from google.appengine.ext import db, webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

from gaesessions import get_current_session

def redirect_with_msg(h, msg, dst='/'):
    get_current_session()['msg'] = msg
    h.redirect(dst)

def render_template(h, file, template_vals):
    path = os.path.join(os.path.dirname(__file__), 'templates', file)
    h.response.out.write(template.render(path, template_vals))

# create our own simple users model to track our user's data
class MyUser(db.Model):
    user = db.UserProperty()
    past_view_count = db.IntegerProperty(default=0) # just for demo purposes ...

class LoginHandler(webapp.RequestHandler):
    """Receive the POST from RPX with our user's login information."""
    def get(self):
        user = users.get_current_user()
        if not user:
            return redirect_with_message(self, 'Try logging in first.')
        
        # close any active session the user has since he is trying to login
        session = get_current_session()
        if session.is_active():
            session.terminate()

        # get the user's record (ignore TransactionFailedError for the demo)
        user = MyUser.get_or_insert(user.user_id(), user=user)

        # start a session for the user (old one was terminated)
        session['me'] = user
        session['pvsli'] = 0 # pages viewed since logging in
        redirect_with_msg(self, 'success!')

class MainPage(webapp.RequestHandler):
    def get(self):
        session = get_current_session()
        d = dict(login_url=users.create_login_url("/login_response"))
        if session.has_key('msg'):
            d['msg'] = session['msg']
            del session['msg'] # only show the message once

        if session.has_key('pvsli'):
            session['pvsli'] += 1
            d['myuser'] = session['me']
            d['num_now'] = session['pvsli']
        render_template(self, "index.html", d)

class Page2(webapp.RequestHandler):
    def get(self):
        session = get_current_session()
        d = {}
        if session.has_key('pvsli'):
            session['pvsli'] += 1
            d['myuser'] = session['me']
            d['num_now'] = session['pvsli']
        render_template(self, "page2.html", d)

class LogoutPage(webapp.RequestHandler):
    def get(self):
        session = get_current_session()
        if session.has_key('me'):
            # update the user's record with total views
            myuser = session['me']
            myuser.past_view_count += session['pvsli']
            myuser.put()
            session.terminate()
            redirect_with_msg(self, 'Logout complete: goodbye ' + myuser.user.nickname())
        else:
            redirect_with_msg(self, "How silly, you weren't logged in")

application = webapp.WSGIApplication([('/', MainPage),
                                      ('/2', Page2),
                                      ('/logout', LogoutPage),
                                      ('/login_response', LoginHandler),
                                     ])

def main(): run_wsgi_app(application)
if __name__ == '__main__': main()
